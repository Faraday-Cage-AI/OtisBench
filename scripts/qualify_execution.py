"""Full native inherited-task qualification under the disclosed scoring fork."""
from pathlib import Path
import gzip
import hashlib
import json
from faraday_manufacturing_benchmark.cli import workflows
from faraday_industrial_benchmark.agents import OracleAgent,NoopAgent,ReadOnlyAgent,UnsafeAgent
from faraday_industrial_benchmark.models import IncidentTask
from faraday_industrial_benchmark.runner import BenchmarkRunner
ROOT=Path(__file__).resolve().parents[1]


def main():
    runner=BenchmarkRunner();out=ROOT/'runs/qualification/execution';out.mkdir(parents=True,exist_ok=True);rows=[]
    for i,spec in enumerate(workflows(),1):
        t=IncidentTask.from_dict(spec);r=runner.run_task(t,OracleAgent()).to_dict();replayed=runner.replay(t,r['trace'])
        exact=replayed['exact_match'] and all(replayed[k]==r[k] for k in ('score','initial_state_hash','final_state_hash','final_answer','applied_events'))
        controls={}
        for a in (NoopAgent(),ReadOnlyAgent(),UnsafeAgent()):
            control=runner.run_task(t,a).score
            controls[a.name]=dict(strict_success=control.strict_success,score=control.score,critical=control.critical_failure,efficiency=control.dimensions['efficiency']['score'])
        path=out/(t.id+'.json.gz');path.write_bytes(gzip.compress(json.dumps(r,sort_keys=True,allow_nan=False).encode(),mtime=0))
        rows.append(dict(task_id=t.id,family=t.family,strict_success=r['score']['strict_success'],exact_replay=exact,controls=controls,receipt=str(path.relative_to(ROOT)),receipt_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        if i%10==0:print(f'{i}/{len(workflows())} execution tasks',flush=True)
    paths=list((ROOT/'src').rglob('*.py'))+[Path(__file__).resolve(),ROOT/'src/faraday_manufacturing_benchmark/data/workflows.json']
    report=dict(track='execution-qualification',control='Author family-specific oracle using tool results/playbooks; no model or independent practitioner claim.',scoring_contract='manufacturing-execution/2-outcome-gated-efficiency',source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)},cases=rows,
        summary=dict(cases=len(rows),families=len({r['family'] for r in rows}),strict_successes=sum(r['strict_success'] for r in rows)),exact_replays=sum(r['exact_replay'] for r in rows),
        limitations=['Discovery can earn criterion partial credit; read-only strict success must remain false.','Efficiency bonus is zero until the workflow criteria complete.','Native scoring fork is not directly comparable to upstream unmodified scores.','Synthetic in-process controls do not establish model isolation or held-out performance.'])
    (ROOT/'reports/execution-qualification.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    passed=all(r['strict_success'] and r['exact_replay'] and all(not c['strict_success'] for c in r['controls'].values()) and r['controls']['negative-control/noop']['efficiency']==0 and r['controls']['negative-control/read-only']['efficiency']==0 and r['controls']['negative-control/unauthorized-write']['critical'] and r['controls']['negative-control/unauthorized-write']['score']==0 for r in rows)
    print(json.dumps(dict(passed=passed,**report['summary'],exact_replays=report['exact_replays'])))
    return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
