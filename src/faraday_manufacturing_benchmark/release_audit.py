"""Read-only release evidence integrity checks, not independent qualification.

Checks current catalogs, versioned sources, full per-case coverage, controls and
retained receipts. It does not rerun agents or trust aggregate green counts in
place of case-level records. Hashes detect drift, not malicious author tampering.
"""
import gzip
import hashlib
import json
from pathlib import Path
from .catalog import TASKS
from .cli import workflows,workflow_catalog
from .supply_cases import catalog as supply_catalog
from .sensor_cases import catalog as sensor_catalog
from .procurement_cases import catalog as procurement_catalog
from .cad_cases import catalog as cad_catalog
from .season import CASES
from .document_cases import catalog as document_catalog


def local_file(root,name):
    path=(root/name).resolve()
    if not path.is_relative_to(root.resolve()):raise ValueError('path escapes repository')
    return path


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_row(track,row):
    checks=[]
    def need(ok,label):
        if not ok:checks.append(label)
    if track!='seasons':need(row.get('strict_success') is True,'reference strict success')
    if track not in ('engineering','cad'):need(row.get('exact_replay') is True,'exact replay')
    if track=='workflow':
        need(row.get('read_only_score')==0,'read-only control');need(row.get('unsafe_score')==0 and row.get('unsafe_critical') is True,'unsafe control')
    elif track=='engineering':
        need(row.get('schema_valid') is True,'answer schema')
        need(set(row.get('schema_controls',{}))=={'empty','extra','missing'} and all(v is True for v in row.get('schema_controls',{}).values()),'schema controls')
        need(bool(row.get('field_mutations')) and all(m.get('rejected') is True for m in row.get('field_mutations',[])),'field mutations')
    elif track=='supply-chain':
        need(row.get('read_only_zero') is True and row.get('unsafe_critical_zero') is True,'negative controls')
        need(row.get('field_mutations',0)>0 and row.get('field_mutations_rejected')==row.get('field_mutations'),'field mutations')
    elif track in ('procurement','sensors'):
        need(row.get('read_only_zero') is True and row.get('unauthorized_critical_zero') is True,'negative controls')
        mm=row.get('mutations',{})
        if track=='procurement':
            need(set(mm)=={'invoice_amount','missing_ap_readback','physical_quantity'} and all(m.get('exercised') is True and m.get('strict_success') is False for m in mm.values()),'ledger mutations')
        else:need(bool(mm) and all(m.get('strict_success') is False for m in mm),'answer mutations')
    elif track=='documents':
        need(row.get('reference_consistent') is True and row.get('no_read_strict_failure') is True and row.get('empty_zero') is True and row.get('line_coverage_controls') is True,'document reference/negative controls')
        mm=row.get('mutations',[])
        from .documents import FACTS,GROUPS
        expected={(i,f) for i in range(1,5) for f in list(FACTS)+['evidence.'+g for g in GROUPS]}
        need(len(mm)==len(expected) and {(m.get('line_id'),m.get('field')) for m in mm}==expected and all(m.get('rejected') is True for m in mm),'document field/evidence mutations')
    elif track=='cad':
        need(row.get('kernel_replay_strict') is True,'kernel replay')
        mm=row.get('geometric_mutations',{});need(set(mm)=={'bounding_box_only','stale_revision','wrong_datum'} and all(v is False for v in mm.values()),'geometry mutations')
        advanced=('rounded_plate','chamfered_pocket','tapered_hub','lofted_adapter')
        if any(row.get('task_id','').startswith('cad-'+family+'-') for family in advanced):
            need(row.get('advanced_operation_omitted_strict_success') is False,'advanced operation omission')
    elif track=='execution':
        c=row.get('controls',{});need(set(c)=={'negative-control/noop','negative-control/read-only','negative-control/unauthorized-write'},'control coverage')
        need(bool(c) and all(v.get('strict_success') is False for v in c.values()),'control strict success')
        need(c.get('negative-control/noop',{}).get('efficiency')==0,'idle efficiency')
        need(c.get('negative-control/read-only',{}).get('efficiency')==0,'read-only efficiency')
        u=c.get('negative-control/unauthorized-write',{});need(u.get('score')==0 and u.get('critical') is True,'unauthorized control')
    elif track=='seasons':
        need(row.get('ledger_passed') is True and row.get('ledger_errors')==[],'independent ledger')
        expected={'cash','capacity','terminal_profit','terminal_holding','shipment'}
        if row.get('policy')!='idle':expected|={'receipt','purchase','yield'}
        mm=row.get('mutations',[]);need({m.get('kind') for m in mm}==expected and all(m.get('rejected') is True for m in mm),'ledger mutations')
        need(row.get('weeks')==26,'complete horizon')
    return checks


def audit(root):
    root=Path(root).resolve();tracks={
        'workflow':workflow_catalog(),'engineering':TASKS,'supply-chain':supply_catalog(),
        'procurement':procurement_catalog(),'sensors':sensor_catalog(),'cad':cad_catalog(),'execution':workflows(),'documents':document_catalog(),
        'seasons':[dict(id=(c.id,d,p)) for c in CASES for d in range(3) for p in ('idle','rule','maintenance')]}
    results={}
    for track,catalog in tracks.items():
        errors=[];rows=[]
        try:
            path=root/f'reports/{track}-qualification.json';report=json.loads(path.read_text());rows=report['cases']
            expected={t['id'] for t in catalog}
            actual=[(r['case_id'],r['draw'],r['policy']) if track=='seasons' else r['task_id'] for r in rows]
            if len(set(actual))!=len(actual) or set(actual)!=expected:errors.append('catalog coverage: duplicate, missing or unexpected cases')
            sources=report['source_hashes'];required={str(p.relative_to(root)) for p in (root/'src').rglob('*.py')}|{f'scripts/qualify_{"workflows" if track=="workflow" else "supply_chain" if track=="supply-chain" else track}.py'}
            if not required<=sources.keys():errors.append('incomplete source fingerprint coverage')
            for name,expected_sha in sources.items():
                if sha(local_file(root,name))!=expected_sha:errors.append('stale source: '+name)
            if track=='execution' and report.get('scoring_contract')!='manufacturing-execution/2-outcome-gated-efficiency':errors.append('execution scoring contract')
            for identity,row in zip(actual,rows):
                errors.extend(f'{identity}: {err}' for err in validate_row(track,row))
                path=local_file(root,row['receipt'])
                if sha(path)!=row['receipt_sha256']:errors.append(f'{identity}: receipt hash mismatch');continue
                receipt=json.loads(gzip.decompress(path.read_bytes()))
                rid=(receipt.get('case_id'),receipt.get('draw'),receipt.get('policy')) if track=='seasons' else receipt.get('evaluator_task_id',receipt.get('task_id',receipt.get('task',{}).get('id')))
                if rid!=identity:errors.append(f'{identity}: receipt identity mismatch')
                score=receipt.get('score') if track=='execution' else receipt.get('result')
                if track!='seasons' and (not isinstance(score,dict) or score.get('strict_success') is not True):errors.append(f'{identity}: receipt strict failure')
                if track=='documents':
                    from .isolation import POLICY_VERSION
                    meta=receipt.get('isolation',{})
                    if meta.get('policy_version')!=POLICY_VERSION or meta.get('agent_sha256')!=sha(root/'examples/document_agent.py'):errors.append(f'{identity}: document isolation metadata mismatch')
                if track=='seasons' and (receipt.get('ledger_audit',{}).get('passed') is not True or receipt.get('result',{}).get('profit_cents')!=row['profit_cents']):errors.append(f'{identity}: receipt ledger mismatch')
        except (OSError,ValueError,KeyError,TypeError,AttributeError) as exc:errors.append(f'invalid or missing evidence: {exc}')
        results[track]=dict(passed=not errors,cases=len(rows),errors=errors)
    isolation=audit_isolation(root);erp=audit_erp_compatibility(root)
    return dict(passed=all(v['passed'] for v in results.values()) and isolation['passed'] and erp['passed'],isolation=isolation,erp_compatibility=erp,scope='Current-source native qualification evidence integrity; no new replay, model performance, independent validation, or comprehensiveness claim.',tracks=results)


def audit_isolation(root):
    """Integrity of local OS-boundary probes and declared public-control coverage."""
    from .isolation import POLICY_VERSION
    import errno
    errors=[];rows=[]
    try:
        report=json.loads((root/'reports/isolation-qualification.json').read_text());rows=report['cases']
        sources={'workflow':'tests/workflow_qualification_policy.py','procurement':'examples/procurement_agent.py','supply-chain':'examples/supply_award_agent.py','sensors':'examples/vibration_agent.py','cad':'examples/cad_plate_agent.py'}
        expected={('workflow',t['id']) for t in workflow_catalog()}|{('procurement',t['id']) for t in procurement_catalog()}|{('supply-chain',t['id']) for t in supply_catalog() if t['family']=='source_award'}|{('sensors',t['id']) for t in sensor_catalog() if t['family']=='vibration_order'}|{('cad',t['id']) for t in cad_catalog() if t['family']=='drilled_plate' and t['mode']=='text_and_drawing'}
        actual=[(r['track'],r['task_id']) for r in rows]
        if len(set(actual))!=len(actual) or set(actual)!=expected:errors.append('isolation catalog coverage')
        required={str(p.relative_to(root)) for p in (root/'src').rglob('*.py')}|set(sources.values())|{'scripts/qualify_isolation.py','examples/isolation_probe.py'}
        if not required<=report['source_hashes'].keys():errors.append('isolation source coverage')
        for name,digest in report['source_hashes'].items():
            if sha(local_file(root,name))!=digest:errors.append('stale isolation source: '+name)
        if report['policy_version']!=POLICY_VERSION:errors.append('isolation policy version')
        probes=report['boundary_probes'];denied={'evaluator_source','catalog','outside_file','outside_write','symlink_read','hardlink','network','process_spawn','runtime_site_packages'}
        if probes.get('passed') is not True:errors.append('boundary probes failed')
        if not all(probes['unsandboxed'][k]['allowed'] is True for k in denied):errors.append('missing positive boundary controls')
        if not all(probes['restricted'][k]['allowed'] is False and probes['restricted'][k]['errno'] in (errno.EPERM,errno.EACCES) for k in denied):errors.append('OS permission denials not established')
        r=probes['restricted']
        if r['benchmark_import_visible'] is not False or r['environment_canary_visible'] is not False or set(r['environment_keys'])!={'HOME','TMPDIR','LANG','LC_ALL'}:errors.append('environment or import boundary')
        if not r['own_code_readable'] or not r['scratch_usable']:errors.append('sandbox unusable')
        for row in rows:
            label=row['task_id'];source=sources[row['track']]
            if row['strict_success'] is not True or row['replay_passed'] is not True:errors.append(label+': isolated qualification failed')
            if row['source']!=source or row['agent_sha256']!=sha(local_file(root,source)):errors.append(label+': agent source mismatch')
            path=local_file(root,row['receipt'])
            if sha(path)!=row['receipt_sha256']:errors.append(label+': isolated receipt hash mismatch');continue
            receipt=json.loads(gzip.decompress(path.read_bytes()));meta=receipt['isolation']
            if receipt['evaluator_task_id']!=label or receipt['result']['strict_success'] is not True:errors.append(label+': isolated receipt mismatch')
            if meta['agent_sha256']!=row['agent_sha256'] or meta['policy_version']!=POLICY_VERSION or row['policy_version']!=POLICY_VERSION:errors.append(label+': launch metadata mismatch')
    except (OSError,ValueError,KeyError,TypeError,AttributeError) as exc:errors.append('invalid or missing isolation evidence: '+str(exc))
    return dict(passed=not errors,episodes=len(rows),errors=errors)


def audit_erp_compatibility(root):
    """Separate selected upstream ERP checks; never changes native case counts."""
    errors=[];rows=[]
    try:
        report=json.loads((root/'reports/erp-compatibility-qualification.json').read_text());rows=report['selection']
        expected={'2000_easy_01_buy_only_baseline','2064_medium_08_single_bom_single_workcenter','2160_hard_17_shared_component_subassemblies_branch_assigned'}
        if len(rows)!=3 or {r['source_task'] for r in rows}!=expected or report.get('native_case_count_added')!=0:errors.append('ERP compatibility selection/provenance mismatch')
        required={str(p.relative_to(root)) for p in (root/'src').rglob('*.py')}|{'scripts/qualify_erp.py','examples/erp_buy_agent.py'}
        if not required<=report['source_hashes'].keys():errors.append('ERP source fingerprint coverage')
        for name,digest in report['source_hashes'].items():
            if sha(local_file(root,name))!=digest:errors.append('stale ERP compatibility source: '+name)
        for row in rows:
            if not row['noop_failed'] or not row['reference_passed'] or row['reference_score']!=100:errors.append(row['source_task']+': ERP reference/weak control failed')
            if row['source_task'][:4] in ('2064','2160') and not row['new_manufacturing_orders']:errors.append(row['source_task']+': no actual new manufacturing records')
            manifest_path=local_file(root,row['snapshot_manifest'])
            if sha(manifest_path)!=row['snapshot_manifest_sha256']:errors.append('ERP baseline manifest changed')
            manifest=json.loads(manifest_path.read_text())
            for name,digest in manifest['files'].items():
                path=(manifest_path.parent/name).resolve()
                if not path.is_relative_to(manifest_path.parent.resolve()) or sha(path)!=digest:errors.append('ERP baseline file changed: '+name)
        public=report['public_buyer'];episode_path=local_file(root,public['episode'])
        if sha(episode_path)!=public['episode_sha256'] or not public['result']['adapter_passed']:errors.append('ERP public buyer failed or receipt changed')
        if not all(public['exact_replay'].get(k) is True for k in ('exact_responses','exact_business_state','exact_verifier')):errors.append('ERP public buyer exact replay not established')
        controls=report['controls']
        if set(controls)!={'noop','unauthorized','wrong_price'}:errors.append('ERP public control coverage')
        for name,row in controls.items():
            path=local_file(root,row['path'])
            if sha(path)!=row['sha256'] or row['result']['adapter_passed']:errors.append('ERP negative control failed: '+name)
        unsafe=controls['unauthorized']
        if not unsafe['result']['upstream_passed'] or not unsafe['critical_violations'] or unsafe['result'].get('adapter_score')!=0:errors.append('ERP permission gate not established')
        wrong=json.loads(local_file(root,controls['wrong_price']['path']).read_text())
        posted=any(r['decision'].get('tool')=='rpc' and r['decision']['arguments'].get('model')=='purchase.order' and r['decision']['arguments'].get('method')=='create' and r['result'].get('ok') is True for r in wrong['trace'])
        read_back=any(r['decision'].get('tool')=='rpc' and r['decision']['arguments'].get('model')=='purchase.order' and r['decision']['arguments'].get('method')=='read' and r['result'].get('ok') is True and any('amount_untaxed' in v for v in r['result'].get('value',[])) for r in wrong['trace'])
        if not posted or not read_back or controls['wrong_price']['result']['upstream_passed']:errors.append('ERP valid-but-wrong persisted write was not rejected by business grader')
        if not report['qualification_passed']:errors.append('ERP compatibility qualification failed')
    except (OSError,ValueError,KeyError,TypeError,AttributeError) as exc:errors.append('invalid or missing ERP compatibility evidence: '+str(exc))
    return dict(passed=not errors,selected_upstream_cases=len(rows),native_case_count_added=0,errors=errors)
