"""Read-only integrity audit of selected public invoice qualification evidence.

Checks recorded replay/verifier artifacts; does not start Odoo or rerun an agent.
"""
import json
from pathlib import Path
from erp_invoice_runner import ROOT,base,sources,protocol
from qualify_erp_invoices import CASES


def local(path):
    value=(ROOT/path).resolve()
    if not value.is_relative_to(ROOT):raise ValueError('invoice evidence path outside checkout')
    return value


def audit():
    report=json.loads((ROOT/'reports/erp-invoice-qualification.json').read_text())
    if report.get('qualification_passed') is not True:raise ValueError('invoice qualification is not passing')
    if report['protocol']!=protocol.VERSION or report['selected_upstream_cases']!=3 or report['native_case_count_added']!=0:raise ValueError('invoice qualification scope mismatch')
    for name,expected in report['source_sha256'].items():
        if base.sha(local(name))!=expected:raise ValueError('invoice qualification source changed')
    if len(report['cases'])!=3 or {row['task'] for row in report['cases']}!=set(CASES):raise ValueError('invoice case coverage mismatch')
    artifacts={};posted=linked=0
    for row in report['cases']:
        path=local(row['episode'])
        if base.sha(path)!=row['episode_sha256']:raise ValueError('invoice episode changed')
        episode=json.loads(path.read_text())
        if episode['source_sha256']!=sources() or episode['contract_sha256']!=base.digest(protocol.contract()):raise ValueError('invoice runtime/contract mismatch')
        if episode['agent_sha256']!=episode['agent_isolation']['agent_sha256'] or episode['agent_sha256']!=base.sha(ROOT/'examples/erp_invoice_agent.py'):raise ValueError('invoice staged agent/source mismatch')
        if episode['status']!='finished' or episode['critical_violations'] or not episode['result']['adapter_passed'] or episode['result']!=row['result']:raise ValueError('incomplete invoice positive control')
        if not all(row['replay'][key] is True for key in ('exact_responses','exact_business_state','exact_verifier')):raise ValueError('invoice exact replay not recorded')
        for reward in [path.parent/(path.stem+'-evidence')/'verifier/reward.json',ROOT/'runs/invoice-extension'/(row['task']+'-replay')/'verifier/reward.json']:
            if json.loads(reward.read_text())!=episode['result']['verifier']:raise ValueError('invoice verifier/replay result differs')
            artifacts[str(reward.relative_to(ROOT))]=base.sha(reward)
        ids={invoice['id'] for invoice in episode['posted_customer_invoices']}
        references={identity for order in episode['linked_sales_invoices'] for identity in order['invoice_ids']}
        if ids!=references or len(episode['linked_sales_invoices'])!=4 or any(invoice['state']!='posted' or invoice['move_type']!='out_invoice' for invoice in episode['posted_customer_invoices']):raise ValueError('invoice posting/linkage inventory mismatch')
        snapshot=Path(episode['snapshot_path'])
        if not snapshot.resolve().is_relative_to(ROOT) or base.sha(snapshot/'manifest.json')!=episode['snapshot_manifest_sha256']:raise ValueError('invoice fixture commitment differs')
        manifest=json.loads((snapshot/'manifest.json').read_text());base.snapshot_contract(manifest);base.check_source(manifest['case_dir'])
        for name,expected in manifest['files'].items():
            target=(snapshot/name).resolve()
            if not target.is_relative_to(snapshot.resolve()) or base.sha(target)!=expected:raise ValueError('invoice fixture artifact differs')
        artifacts[row['episode']]=base.sha(path);posted+=len(ids);linked+=len(episode['linked_sales_invoices'])
    for name,row in report['controls'].items():
        path=local(row['episode'])
        if base.sha(path)!=row['episode_sha256']:raise ValueError('invoice negative control changed')
        episode=json.loads(path.read_text())
        if episode['source_sha256']!=sources() or episode['result']!=row['result']:raise ValueError('invoice negative control provenance mismatch')
        policy=ROOT/'runs/invoice-extension/negative-policies'/('wrong-downpayment.py' if name=='wrong_downpayment' else 'context-override.py')
        if episode['agent_sha256']!=base.sha(policy) or episode['agent_sha256']!=episode['agent_isolation']['agent_sha256'] or episode['critical_violations']!=row['critical']:raise ValueError('invoice negative-policy identity differs')
        artifacts[str(policy.relative_to(ROOT))]=base.sha(policy)
        artifacts[row['episode']]=base.sha(path)
    wrong=report['controls']['wrong_downpayment'];unsafe=report['controls']['forbidden_context']
    if not wrong['exercised'] or wrong['result']['upstream_passed'] or wrong['critical'] or wrong['status']!='finished':raise ValueError('wrong-amount control incomplete or accepted')
    if not unsafe['result']['upstream_passed'] or unsafe['result']['adapter_passed'] or unsafe['result']['adapter_score']!=0 or not unsafe['critical']:raise ValueError('context permission control failed')
    return dict(integrity_passed=True,selected_upstream_cases=3,native_case_count_added=0,linked_sales=linked,posted_customer_invoices=posted,
        qualification_sha256=base.sha(ROOT/'reports/erp-invoice-qualification.json'),artifact_sha256=artifacts,auditor_sha256=base.sha(__file__),
        scope='Selected recorded public-control, fixture, linkage and replay/verifier integrity. No fresh Odoo run, model inference, full-catalog or independent-review claim.')


if __name__=='__main__':
    report=audit();base.save(ROOT/'reports/erp-invoice-audit.json',report)
    print(json.dumps({key:report[key] for key in ['integrity_passed','selected_upstream_cases','linked_sales','posted_customer_invoices']}))
