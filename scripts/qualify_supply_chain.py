"""Reference consistency / negative controls, explicitly not model performance."""
from pathlib import Path
import gzip
import hashlib
import json
from faraday_manufacturing_benchmark.supply_cases import catalog
from faraday_manufacturing_benchmark.supply_chain import SupplyChainWorld,replay
from faraday_manufacturing_benchmark.supply_reference import solve
from faraday_manufacturing_benchmark.grading import summarize
ROOT=Path(__file__).resolve().parents[1]


def main():
    rows=[];results=[];out=ROOT/'runs/qualification/supply-chain';out.mkdir(parents=True,exist_ok=True)
    for t in catalog():
        w=SupplyChainWorld(t)
        if w.pending:w.call('wait',minutes=6)
        for system in t['systems']:w.call('read',system=system)
        answer=solve(t['family'],w.inputs)
        pid=w.call('propose',action=answer)['proposal']['id']
        aid=w.call('request_approval',proposal_id=pid)['approval']['id']
        tid=w.call('execute',proposal_id=pid,approval_id=aid)['transaction_id']
        w.call('read_back',transaction_id=tid);w.call('finish',transaction_id=tid)
        result=w.grade();exact=replay(t,w.trace)==result;results.append(result)
        weak=SupplyChainWorld(t)
        for system in t['systems']:weak.call('read',system=system)
        unsafe=SupplyChainWorld(t);unsafe.call('execute',proposal_id='PROP-fake',approval_id='AUTH-fake')
        # Every field mutation must destroy strict success even when it has valid
        # JSON types. This checks verifier sensitivity, not just the happy path.
        rejected=0
        for key,value in answer.items():
            bad=dict(answer)
            if isinstance(value,bool):bad[key]=not value
            elif isinstance(value,(int,float)):bad[key]=value+1
            elif isinstance(value,list):bad[key]=value+['invalid']
            elif value is None:bad[key]=0
            else:bad[key]=value+'-WRONG'
            mutated=SupplyChainWorld(t)
            if mutated.pending:mutated.call('wait',minutes=6)
            for system in t['systems']:mutated.call('read',system=system)
            proposal=mutated.call('propose',action=bad)
            if proposal['ok']:
                p=proposal['proposal']['id'];a=mutated.call('request_approval',proposal_id=p)['approval']['id'];tx=mutated.call('execute',proposal_id=p,approval_id=a)['transaction_id']
                mutated.call('read_back',transaction_id=tx);mutated.call('finish',transaction_id=tx)
            rejected+=not mutated.grade()['strict_success']
        receipt=dict(evaluator_task_id=t['id'],result=result,trace=w.trace)
        path=out/(t['id']+'.json.gz');path.write_bytes(gzip.compress(json.dumps(receipt,sort_keys=True,allow_nan=False).encode(),mtime=0))
        rows.append(dict(task_id=t['id'],strict_success=result['strict_success'],exact_replay=exact,read_only_zero=weak.grade()['score']==0,unsafe_critical_zero=unsafe.grade()['score']==0 and bool(unsafe.grade()['critical_violations']),field_mutations=len(answer),field_mutations_rejected=rejected,receipt=str(path.relative_to(ROOT)),receipt_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    paths=list((ROOT/'src').rglob('*.py'))+[Path(__file__).resolve()]
    report=dict(track='supply-chain-qualification',control='Evaluator-reference consistency control; uses reference answers and is NOT agent performance or independent ground truth.',source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)},summary=summarize(results),exact_replays=sum(r['exact_replay'] for r in rows),read_only_zero_scores=sum(r['read_only_zero'] for r in rows),unsafe_critical_zero_scores=sum(r['unsafe_critical_zero'] for r in rows),field_mutations=sum(r['field_mutations'] for r in rows),field_mutations_rejected=sum(r['field_mutations_rejected'] for r in rows),cases=rows)
    (ROOT/'reports/supply-chain-qualification.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    passed=all(r['strict_success'] and r['exact_replay'] and r['read_only_zero'] and r['unsafe_critical_zero'] and r['field_mutations_rejected']==r['field_mutations'] for r in rows)
    print(json.dumps(dict(passed=passed,cases=len(rows),mutations=report['field_mutations'],rejected=report['field_mutations_rejected'])))
    return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
