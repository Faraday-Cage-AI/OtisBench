"""Full synthetic season replay, independent accounting, and corruption controls."""
from copy import deepcopy
from pathlib import Path
import gzip
import hashlib
import json
from faraday_manufacturing_benchmark.season import CASES,FactorySeason,PRODUCTS,POLICY,idle_policy,rule_policy,replay
from faraday_manufacturing_benchmark.season_audit import audit_trace
from faraday_manufacturing_benchmark.season_policies import maintenance_policy
from faraday_manufacturing_benchmark.statistics import paired_comparison,season_score
ROOT=Path(__file__).resolve().parents[1]
POLICIES={'idle':idle_policy,'rule':rule_policy,'maintenance':maintenance_policy}


def mutations(trace,result):
    bad=deepcopy(trace);bad[0]['cash_cents']+=1;yield 'cash',bad,result
    bad=deepcopy(trace);bad[0]['remaining_capacity_minutes']['mill']+=1;yield 'capacity',bad,result
    bad_result=deepcopy(result);bad_result['profit_cents']+=1;yield 'terminal_profit',trace,bad_result
    bad_result=deepcopy(result);bad_result['costs_cents']['holding']+=1;yield 'terminal_holding',trace,bad_result
    for label,key,field in [('receipt','receipts','units'),('purchase','purchases','value_cents'),('yield','jobs','good_units'),('shipment','shipments','revenue_cents')]:
        index=next((i for i,row in enumerate(trace) if row[key]),None)
        if index is not None:
            bad=deepcopy(trace);bad[index][key][0][field]+=1;yield label,bad,result


def main():
    out=ROOT/'runs/qualification/seasons';out.mkdir(parents=True,exist_ok=True);rows=[];results={name:[] for name in POLICIES}
    for case in CASES:
        for draw in range(3):
            for name,policy in POLICIES.items():
                world=FactorySeason(case,draw)
                for _ in range(case.weeks):world.step(policy(world.observe()))
                result=deepcopy(world.result());results[name].append(result)
                args=dict(products=PRODUCTS,materials=world.materials,policy=POLICY,exogenous=world.exogenous)
                audited=audit_trace(case,draw,world.trace,result,**args)
                checks=[dict(kind=kind,rejected=not audit_trace(case,draw,trace,reported,**args)['passed']) for kind,trace,reported in mutations(world.trace,result)]
                receipt=dict(case_id=case.id,draw=draw,policy=name,trace=world.trace,result=result,committed_exogenous=world.exogenous,ledger_audit=audited)
                path=out/f'{case.id}-{draw}-{name}.json.gz';path.write_bytes(gzip.compress(json.dumps(receipt,sort_keys=True,allow_nan=False).encode(),mtime=0))
                rows.append(dict(case_id=case.id,draw=draw,policy=name,weeks=len(world.trace),exact_replay=replay(case,draw,world.trace)==result,ledger_passed=audited['passed'],ledger_errors=audited['errors'],mutations=checks,profit_cents=result['profit_cents'],score=result['score'],rejected_actions=result['rejected_actions'],receipt=str(path.relative_to(ROOT)),receipt_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        print(f'{case.id}: 9 complete seasons replayed and audited',flush=True)
    paths=list((ROOT/'src').rglob('*.py'))+[Path(__file__).resolve()]
    report=dict(track='season-qualification',control='Disclosed deterministic author policies; no model, optimal-policy, or independent practitioner claim.',source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)},cases=rows,
        summary=dict(factory_cases=len(CASES),draws_per_case=3,policies=list(POLICIES),episodes=len(rows),weeks=sum(r['weeks'] for r in rows),exact_replays=sum(r['exact_replay'] for r in rows),ledger_passes=sum(r['ledger_passed'] for r in rows),mutations=sum(len(r['mutations']) for r in rows),mutations_rejected=sum(m['rejected'] for r in rows for m in r['mutations'])),
        policy_scores={name:season_score(rr) for name,rr in results.items()},paired_comparisons={name+'_vs_rule':paired_comparison(rr,results['rule']) for name,rr in results.items() if name!='rule'},
        limitations=['All scenarios, demand, delays and yields are synthetic.','Accounting verifier uses separate reconstruction code but shares authored operating rules; no independent validation claim.','Policy results are development baselines, not a model leaderboard.','Season scores are unclipped profit / demand contribution margin; replay and accounting validity do not imply optimal performance.'])
    (ROOT/'reports/seasons-qualification.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    passed=all(r['exact_replay'] and r['ledger_passed'] and all(m['rejected'] for m in r['mutations']) for r in rows)
    print(json.dumps(dict(passed=passed,**report['summary'],policy_scores=report['policy_scores'])))
    return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
