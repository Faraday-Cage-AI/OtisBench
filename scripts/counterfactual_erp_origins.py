"""Fresh-fixture, private-reference-assisted origin diagnostic; not a model score."""
import argparse
from pathlib import Path
import json
import subprocess
import time
from faraday_manufacturing_benchmark import erp_compat as erp
ROOT=Path(__file__).resolve().parents[1]


def difference(left,right):
    changes=[]
    if set(left)!=set(right):raise ValueError('business model projection changed')
    for model in left:
        a={r['id']:r for r in left[model]};b={r['id']:r for r in right[model]}
        if set(a)!=set(b):raise ValueError('counterfactual created/deleted business records')
        for key in a:
            for field in set(a[key])|set(b[key]):
                if a[key].get(field)!=b[key].get(field):changes.append(dict(model=model,id=key,field=field,before=a[key].get(field),after=b[key].get(field)))
    return changes


def run(receipt_path,output,po_name,origins):
    receipt_path=Path(receipt_path).resolve();output=Path(output).resolve()
    if not receipt_path.is_relative_to(ROOT) or not output.is_relative_to(ROOT) or output.exists():raise ValueError('use existing local receipt and fresh local output')
    if len(origins)!=len(set(origins)) or not origins:raise ValueError('origins must be a nonempty unique list')
    receipt=erp.read(receipt_path) if hasattr(erp,'read') else json.loads(receipt_path.read_text());receipt_sha=erp.sha(receipt_path)
    for name,expected in receipt['artifacts'].items():
        path=(ROOT/name).resolve()
        if not path.is_relative_to(ROOT) or erp.sha(path)!=expected:raise ValueError('original campaign evidence changed')
    snapshot=(ROOT/receipt['snapshot_manifest']).parent;manifest=json.loads((snapshot/'manifest.json').read_text());case=Path(manifest['case_dir']);erp.check_source(case)
    sources={str(p.relative_to(ROOT)):erp.sha(p) for p in [Path(__file__),ROOT/'src/faraday_manufacturing_benchmark/erp_compat.py',ROOT/'src/faraday_manufacturing_benchmark/erp_protocol.py']}
    output.mkdir(parents=True);start=time.monotonic();rpc=[]
    with erp.restored(snapshot) as (container,bridge,loaded):
        initial=erp.probe(bridge)
        if erp.digest(initial)!=manifest['baseline_state_digest']:raise ValueError('initial restored state differs')
        container.copy_in(case/'solution','/solution')
        execution=subprocess.run(['docker','exec',container.cid,'bash','/solution/solve.sh'],capture_output=True,timeout=240)
        (output/'reference-execution.log').write_bytes(execution.stdout+execution.stderr)
        reference=erp.grade(container,case,output/'original-reference');before=erp.probe(bridge)
        matches=[r for r in before['purchase.order'] if r['name']==po_name]
        if len(matches)!=1:raise ValueError('purchase order not unique')
        po=matches[0];old=po['origin'];new=', '.join(origins)
        active={r['name'] for r in before['mrp.production'] if r['state']=='confirmed'}
        if not set(origins)<=active:raise ValueError('diagnostic origin is not a confirmed manufacturing order')
        def write(value):
            request=dict(model='purchase.order',method='write',kwargs=dict(ids=[po['id']],vals=dict(origin=value)))
            response=bridge.decide('erp_gateway',request);rpc.append(dict(request=request,response=response))
            if not response['ok'] or response['value'] is not True:raise ValueError('constrained origin write rejected')
        write(new);changed=erp.probe(bridge);corrected=erp.grade(container,case,output/'counterfactual')
        write(old);reverted=erp.probe(bridge);reverted_result=erp.grade(container,case,output/'reverted')
        erp.save(output/'initial-business-state.json',initial);erp.save(output/'reference-business-state.json',before)
        erp.save(output/'counterfactual-business-state.json',changed);erp.save(output/'reverted-business-state.json',reverted)
    changes=difference(before,changed);expected=[dict(model='purchase.order',id=po['id'],field='origin',before=old,after=new)]
    if any(erp.sha(ROOT/name)!=expected_sha for name,expected_sha in sources.items()):raise ValueError('diagnostic implementation changed during run')
    if erp.sha(receipt_path)!=receipt_sha:raise ValueError('original campaign receipt changed')
    same_spend=reference['verifier']['spend']==corrected['verifier']['spend']
    demonstrated=execution.returncode==0 and not reference['upstream_passed'] and corrected['upstream_passed'] and corrected['upstream_score']==100 and changes==expected and before==reverted and reference==reverted_result and same_spend
    report=dict(task_id=receipt['task_id'],control_kind='private-reference-assisted single-field counterfactual diagnostic',demonstrated=demonstrated,
        original_receipt=str(receipt_path.relative_to(ROOT)),original_receipt_sha256=receipt_sha,source_sha256=sources,
        snapshot_manifest_sha256=erp.sha(snapshot/'manifest.json'),restoration=loaded['restoration'],reference_exit_code=execution.returncode,
        original_result=reference,counterfactual_result=corrected,reverted_result=reverted_result,rpc_trace=rpc,business_changes=changes,
        only_requested_origin_changed=changes==expected,exact_business_state_reversal=before==reverted,exact_verdict_reversal=reference==reverted_result,
        exact_original_campaign_verdict=reference==receipt['reference'],spend_summary_unchanged=same_spend,
        native_case_count_added=0,wall_seconds=time.monotonic()-start,
        artifacts={str(p.relative_to(ROOT)):erp.sha(p) for p in output.rglob('*') if p.is_file()},
        scope='Unchanged private upstream reference first, then one constrained public-business origin write, then reversal. Not an initial-state public agent, learned model, private holdout, upstream patch or replacement of the failed campaign verdict.')
    erp.save(output/'counterfactual.json',report)
    return {k:report[k] for k in ['task_id','demonstrated','only_requested_origin_changed','exact_business_state_reversal','spend_summary_unchanged']}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--receipt',required=True);p.add_argument('--output',required=True);p.add_argument('--purchase-order',required=True);p.add_argument('--origin',action='append',required=True);a=p.parse_args()
    print(json.dumps(run(a.receipt,a.output,a.purchase_order,a.origin)))
