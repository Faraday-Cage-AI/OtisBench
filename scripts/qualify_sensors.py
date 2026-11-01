"""Raw-sensor reference consistency and adversarial checks, NOT model results."""
from pathlib import Path
from copy import deepcopy
import gzip
import hashlib
import importlib.util
import json
from faraday_manufacturing_benchmark.sensor_cases import catalog
from faraday_manufacturing_benchmark.sensor_reference import solve
from faraday_manufacturing_benchmark.sensors import SensorWorld,run,replay
from faraday_manufacturing_benchmark.grading import summarize
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('vibration_control',ROOT/'examples/vibration_agent.py');baseline=importlib.util.module_from_spec(spec);spec.loader.exec_module(baseline)


def ready(t):
    world=SensorWorld(t);world.call('read_asset');world.call('read_policy');world.call('list_streams');cursor=0
    while cursor is not None:cursor=world.call('read_stream',stream_id='STREAM-1',cursor=cursor,limit=64)['next_cursor']
    return world


def finish(world,answer):
    proposal=world.call('propose',assessment=answer)
    if not proposal['ok']:return
    p=proposal['proposal']['id'];a=world.call('request_approval',proposal_id=p)['approval']['id'];rid=world.call('execute',proposal_id=p,approval_id=a)['assessment_id']
    world.call('read_result',assessment_id=rid);world.call('finish',assessment_id=rid)


def main():
    output=ROOT/'runs/qualification/sensors';output.mkdir(parents=True,exist_ok=True);rows=[];results=[];public_control=[]
    for t in catalog():
        world=ready(t);answer=solve(world.policy,world.stream['csv']);finish(world,answer);result=world.grade();results.append(result);exact=replay(t,world.trace)==result
        path=output/(t['id']+'.json.gz');path.write_bytes(gzip.compress(json.dumps(dict(evaluator_task_id=t['id'],trace=world.trace,result=result),sort_keys=True,allow_nan=False).encode(),mtime=0))
        weak=ready(t)
        unsafe=ready(t);unauthorized_proposal=unsafe.call('propose',assessment=answer)['proposal']['id'];unsafe.call('execute',proposal_id=unauthorized_proposal,approval_id='APPROVAL-unknown')
        mutants=[]
        for key,value in answer.items():
            bad=deepcopy(answer)
            if key=='decision':bad[key]='service' if value=='continue' else 'continue'
            elif value is None:bad[key]=0
            elif isinstance(value,(int,float)):bad[key]=value+1
            else:bad[key]=value+'-wrong'
            mutation=ready(t);finish(mutation,bad);mutants.append(dict(field=key,strict_success=mutation.grade()['strict_success']))
        rows.append(dict(task_id=t['id'],strict_success=result['strict_success'],exact_replay=exact,read_only_zero=weak.grade()['score']==0,
            unauthorized_critical_zero=unsafe.grade()['score']==0 and bool(unsafe.grade()['critical_violations']),mutations=mutants,
            receipt=str(path.relative_to(ROOT)),receipt_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        if t['family']=='vibration_order':
            e=run(t,baseline.VibrationAgent());public_control.append(dict(task_id=t['id'],strict_success=e['result']['strict_success'],exact_replay=replay(t,e['trace'])==e['result']))
    paths=list((ROOT/'src').rglob('*.py'))+[ROOT/'examples/vibration_agent.py',Path(__file__).resolve()]
    report=dict(track='manufacturing-sensors-qualification',control='Evaluator-reference consistency over all raw streams; NOT independent sensor truth or model performance.',
        separate_public_control='Hand-coded vibration-only agent parses public CSV pages and uses no evaluator imports. Not a model result; not coverage of other analysis families.',
        source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)},summary=summarize(results),
        exact_replays=sum(r['exact_replay'] for r in rows),mutations=sum(len(r['mutations']) for r in rows),mutations_rejected=sum(not m['strict_success'] for r in rows for m in r['mutations']),
        public_vibration_control=public_control,cases=rows,
        limitations=['Synthetic signals and declared thresholds; no live sensor, calibration or plant validation.','Approximate regression uncertainty is not guaranteed confidence coverage or validated remaining useful life.','Task-specific deterministic analysis is not a general anomaly-detection leaderboard.','Public development conditions, not private held-out generalization.'])
    (ROOT/'reports/sensors-qualification.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    passed=all(r['strict_success'] and r['exact_replay'] and r['read_only_zero'] and r['unauthorized_critical_zero'] and all(not m['strict_success'] for m in r['mutations']) for r in rows) and all(r['strict_success'] and r['exact_replay'] for r in public_control)
    print(json.dumps(dict(passed=passed,cases=len(rows),families=len(report['summary']['families']),mutations=report['mutations'],mutations_rejected=report['mutations_rejected'],public_vibration_successes=sum(r['strict_success'] for r in public_control))))
    return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
