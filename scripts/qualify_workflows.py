"""Full-catalog feasibility and negative controls; never a model leaderboard run."""
from pathlib import Path
import gzip
import hashlib
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from workflow_qualification_policy import FeasibilityPolicy
from faraday_manufacturing_benchmark.shopfloor import ManufacturingWorkflow,replay
from faraday_manufacturing_benchmark.shopfloor_cases import catalog
from faraday_manufacturing_benchmark.shopfloor_runner import run,summary


def main():
    paths=list((ROOT/'src').rglob('*.py'))+[ROOT/'tests/workflow_qualification_policy.py',Path(__file__).resolve()]
    source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
    tasks=catalog();out=ROOT/'runs/qualification/workflows';out.mkdir(parents=True,exist_ok=True)
    rows=[];results=[]
    for i,t in enumerate(tasks,1):
        episode=run(t,FeasibilityPolicy());actual=replay(t,episode['trace']);exact=actual==episode['result']
        path=out/(t['id']+'.json.gz')
        data=json.dumps(episode,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
        path.write_bytes(gzip.compress(data,mtime=0))
        weak=ManufacturingWorkflow(t)
        for system in t['systems']:weak.call('read',system=system)
        unsafe=ManufacturingWorkflow(t);unsafe.call('purchase',units=4,expedited=False,approval_id='unapproved')
        rows.append(dict(task_id=t['id'],strict_success=actual['strict_success'],exact_replay=exact,read_only_score=weak.grade()['score'],
            unsafe_score=unsafe.grade()['score'],unsafe_critical=bool(unsafe.grade()['critical_violations']),
            receipt=str(path.relative_to(ROOT)),receipt_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            source_commitment=actual['source_commitment'],final_state_hash=actual['final_state_hash']))
        results.append(actual)
        if i%64==0:print(f'{i}/{len(tasks)} workflows; strict={sum(r["strict_success"] for r in rows)}',flush=True)
    report=dict(benchmark='Faraday Manufacturing Benchmark',track='workflow-qualification',source_hashes=source_hashes,
        control='hand-coded observation-only feasibility policy; fixed initial wait of 20 minutes; not a model result',
        limitations=['Author-written control and grader are not independent practitioner validation.','Public development cases; no private held-out generalization claim.','Simulated records, machines and economics; not live ERP or physical factory validation.'],
        summary=summary(results),exact_replays=sum(r['exact_replay'] for r in rows),
        read_only_zero_scores=sum(r['read_only_score']==0 for r in rows),unsafe_critical_zero_scores=sum(r['unsafe_critical'] and r['unsafe_score']==0 for r in rows),cases=rows)
    path=ROOT/'reports/workflow-qualification.json';path.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    passed=all(r['strict_success'] and r['exact_replay'] and r['read_only_score']==0 and r['unsafe_score']==0 and r['unsafe_critical'] for r in rows)
    print(json.dumps(dict(passed=passed,cases=len(rows),strict_successes=report['summary']['strict_successes'],report=str(path))),flush=True)
    return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
