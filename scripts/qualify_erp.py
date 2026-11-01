"""Selected real-Odoo compatibility qualification; not native case/model counts."""
from pathlib import Path
from copy import deepcopy
import hashlib
import json
from faraday_manufacturing_benchmark.erp_compat import restored,probe,digest,grade,run_agent,replay_episode,sha,save,REVISION
ROOT=Path(__file__).resolve().parents[1]
SELECTION=('2000-v1','2064-v1','2160-v1')


def main():
    output=ROOT/'runs/qualification/erp-compat';output.mkdir(parents=True,exist_ok=True);rows=[]
    for selected in SELECTION:
        snapshot=ROOT/'runs/erp-compat/baselines'/selected;manifest=json.loads((snapshot/'manifest.json').read_text());case=Path(manifest['case_dir'])
        with restored(snapshot) as (container,bridge,_):
            before=probe(bridge);weak=grade(container,case,output/selected/'noop')
        with restored(snapshot) as (container,bridge,_):
            container.copy_in(case/'solution','/solution');execution=container.run(['bash','/solution/solve.sh'],timeout=240)
            path=output/selected/'oracle.log';path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(execution.stdout+execution.stderr)
            after=probe(bridge);reference=grade(container,case,output/selected/'reference')
            new_mo=[r for r in after['mrp.production'] if r['id'] not in {x['id'] for x in before['mrp.production']}]
        row=dict(source_task=manifest['upstream']['task_id'],snapshot_manifest=str((snapshot/'manifest.json').relative_to(ROOT)),snapshot_manifest_sha256=sha(snapshot/'manifest.json'),baseline_digest=manifest['baseline_state_digest'],noop_score=weak['upstream_score'],noop_failed=not weak['upstream_passed'],reference_score=reference['upstream_score'],reference_passed=reference['upstream_passed'],new_manufacturing_orders=new_mo,reference_control='Pinned upstream oracle; reads private reference plan. This is not a public-information agent or model result.')
        rows.append(row);print(selected,'noop',row['noop_score'],'reference',row['reference_score'],'new MOs',len(new_mo),flush=True)
    policies=output/'policies';policies.mkdir(exist_ok=True);source=(ROOT/'examples/erp_buy_agent.py').read_text();prefix=source.split("if __name__=='__main__':")[0]
    def policy(name,body):
        path=policies/(name+'.py');path.write_text(prefix+'\n'+body);return path
    noop=policy('noop',"for line in sys.stdin:print(json.dumps(dict(tool='finish',arguments={})),flush=True)\n")
    unsafe=policy('unauthorized',"""agent=Buyer();pending=False
for line in sys.stdin:
    message=json.loads(line)
    if pending:decision=dict(tool='finish',arguments={})
    else:
        decision=agent.decide(message['track'],message['payload'])
        if decision['tool']=='finish':decision=dict(tool='rpc',arguments=dict(model='res.users.apikeys',method='search_read',kwargs=dict(domain=[],fields=['id'])));pending=True
    print(json.dumps(decision),flush=True)
""")
    wrong=policy('wrong-price',"""agent=Buyer()
for line in sys.stdin:
    message=json.loads(line);decision=agent.decide(message['track'],message['payload'])
    if decision.get('tool')=='rpc' and decision['arguments']['model']=='purchase.order' and decision['arguments']['method']=='create':
        decision['arguments']['kwargs']['vals_list'][0]['order_line'][0][2]['price_unit']+=100
    print(json.dumps(decision),flush=True)
""")
    snapshot=ROOT/'runs/erp-compat/baselines/2000-v1';public=run_agent(snapshot,ROOT/'examples/erp_buy_agent.py',output/'public-buyer.json',20);replayed=replay_episode(public,output/'public-buyer-replay')
    controls={}
    for name,path in [('noop',noop),('unauthorized',unsafe),('wrong_price',wrong)]:
        episode=run_agent(snapshot,path,output/(name+'.json'),20);controls[name]=dict(result=episode['result'],critical_violations=episode['critical_violations'],status=episode['status'],path=str((output/(name+'.json')).relative_to(ROOT)),sha256=sha(output/(name+'.json')))
        print('Public-interface control',name,episode['result']['upstream_score'],episode['result']['adapter_passed'],flush=True)
    paths=list((ROOT/'src').rglob('*.py'))+[Path(__file__).resolve(),ROOT/'examples/erp_buy_agent.py']
    report=dict(track='erp-compatibility-qualification',upstream_revision=REVISION,selected_upstream_cases=3,upstream_catalog_cases=300,native_case_count_added=0,selection=rows,public_buyer=dict(result=public['result'],episode=str((output/'public-buyer.json').relative_to(ROOT)),episode_sha256=sha(output/'public-buyer.json'),exact_replay=replayed,agent_sha256=sha(ROOT/'examples/erp_buy_agent.py')),controls=controls,source_hashes={str(p.relative_to(ROOT)):sha(p) for p in sorted(paths)},limitations=['Upstream compatibility cases are not new Faraday-authored tasks.','Public observation-only buyer supports one simple purchasing prompt; manufacturing reference controls use private upstream plans.','Exact replay is checked for the selected public buyer, not all 300 cases or all valid Odoo action sequences.','Runtime wall clock is not virtualized; mismatches are rejected, not normalized away.','Local immutable Docker image, private SQL/filestore baselines and source caches must be retained.','No learned model, independent practitioner or held-out generalization result.'])
    passed=all(r['noop_failed'] and r['reference_passed'] for r in rows) and public['result']['adapter_passed'] and all(replayed[k] for k in ('exact_responses','exact_business_state','exact_verifier')) and all(not r['result']['adapter_passed'] for r in controls.values()) and controls['unauthorized']['result']['upstream_passed'] and bool(controls['unauthorized']['critical_violations']) and not controls['wrong_price']['result']['upstream_passed']
    report['qualification_passed']=passed;save(ROOT/'reports/erp-compatibility-qualification.json',report)
    print(json.dumps(dict(qualification_passed=passed,selected_upstream_cases=3,public_buyer_cases=1,reference_models_new=[len(r['new_manufacturing_orders']) for r in rows])));return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
