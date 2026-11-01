"""Adversarial local OS boundary probes plus sandboxed public-policy episodes.

No paid model calls and no claim that these public cases are held out.
"""
from pathlib import Path
import errno
import gzip
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
from faraday_manufacturing_benchmark.isolation import isolated_agent,POLICY_VERSION
from faraday_manufacturing_benchmark.isolation_runner import contracts,run_task,replay_episode
ROOT=Path(__file__).resolve().parents[1]
DENIED=('evaluator_source','catalog','outside_file','outside_write','symlink_read','hardlink','network','process_spawn','runtime_site_packages')


def boundary_probes():
    with tempfile.TemporaryDirectory(prefix='faraday-private-probe-') as directory,socket.socket() as server:
        base=Path(directory);secret=base/'canary';secret.write_text('synthetic isolation canary, not a real credential')
        control=base/'control';control.mkdir();server.bind(('127.0.0.1',0));server.listen()
        site=Path(sys.base_prefix)/'lib'/f'python{sys.version_info.major}.{sys.version_info.minor}'/'site-packages'
        sitefile=next(site.glob('*.py'),None)
        if sitefile is None:raise ValueError('qualification requires an existing site-package file for its runtime boundary probe')
        payload=dict(read_paths=dict(evaluator_source=str(ROOT/'src/faraday_manufacturing_benchmark/calculations.py'),catalog=str(ROOT/'src/faraday_manufacturing_benchmark/data/supply_chain_tasks.json'),outside_file=str(secret),runtime_site_packages=str(sitefile)),outside_write=str(base/'control-write'),port=server.getsockname()[1])
        env=dict(os.environ,FARADAY_ISOLATION_CANARY='synthetic nonsecret env canary')
        raw=subprocess.run([str(Path(sys._base_executable).resolve()),'-I','-S',str(ROOT/'examples/isolation_probe.py')],input=json.dumps(dict(payload=payload))+'\n',text=True,capture_output=True,cwd=control,env=env,timeout=10,check=True)
        unsandboxed=json.loads(raw.stdout)
        prior=os.environ.get('FARADAY_ISOLATION_CANARY');os.environ['FARADAY_ISOLATION_CANARY']='synthetic nonsecret env canary'
        payload['outside_write']=str(base/'isolated-write')
        try:
            with isolated_agent(ROOT/'examples/isolation_probe.py',timeout=10) as agent:
                restricted=agent.decide('isolation-probe',payload);metadata=agent.isolation
        finally:
            if prior is None:os.environ.pop('FARADAY_ISOLATION_CANARY',None)
            else:os.environ['FARADAY_ISOLATION_CANARY']=prior
        positive=all(unsandboxed[k]['allowed'] is True for k in DENIED) and unsandboxed['environment_canary_visible'] is True
        negative=all(restricted[k]['allowed'] is False and restricted[k]['errno'] in (errno.EPERM,errno.EACCES) for k in DENIED)
        clean=restricted['benchmark_import_visible'] is False and restricted['environment_canary_visible'] is False and set(restricted['environment_keys'])=={'HOME','TMPDIR','LANG','LC_ALL'}
        usable=restricted['own_code_readable'] is True and restricted['scratch_usable'] is True
        return dict(passed=positive and negative and clean and usable and not (base/'isolated-write').exists(),positive_control_passed=positive,denial_checks_passed=negative,environment_passed=clean,scratch_passed=usable,unsandboxed=unsandboxed,restricted=restricted,isolation=metadata)


def selections():
    for track,source in [('workflow','tests/workflow_qualification_policy.py'),('procurement','examples/procurement_agent.py'),('supply-chain','examples/supply_award_agent.py'),('sensors','examples/vibration_agent.py'),('cad','examples/cad_plate_agent.py')]:
        catalog,*_=contracts(track)
        for task in catalog():
            if track=='supply-chain' and task['family']!='source_award':continue
            if track=='sensors' and task['family']!='vibration_order':continue
            if track=='cad' and not (task['family']=='drilled_plate' and task['mode']=='text_and_drawing'):continue
            yield track,source,task


def main():
    probes=boundary_probes();out=ROOT/'runs/qualification/isolation';out.mkdir(parents=True,exist_ok=True);rows=[]
    if not probes['passed']:raise ValueError('isolation boundary probes failed; refusing to qualify agent runs')
    print('Unsandboxed positive controls and all OS denial/environment probes passed.',flush=True)
    for index,(track,source,task) in enumerate(selections(),1):
        episode=run_task(track,task,ROOT/source,timeout=15);actual=replay_episode(track,task,episode)
        exact=actual['strict_success'] if track=='cad' else actual==episode['result']
        path=out/f'{task["id"]}.json.gz';path.write_bytes(gzip.compress(json.dumps(episode,sort_keys=True,allow_nan=False).encode(),mtime=0))
        rows.append(dict(track=track,task_id=task['id'],strict_success=episode['result']['strict_success'],replay_passed=exact,source=source,agent_sha256=episode['isolation']['agent_sha256'],policy_version=episode['isolation']['policy_version'],receipt=str(path.relative_to(ROOT)),receipt_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        if index%64==0:print(f'{index} sandboxed public-control episodes completed and replayed',flush=True)
    paths=list((ROOT/'src').rglob('*.py'))+[Path(__file__).resolve(),ROOT/'examples/isolation_probe.py']+[ROOT/source for source in sorted({r['source'] for r in rows})]
    report=dict(track='isolation-qualification',policy_version=POLICY_VERSION,boundary_probes=probes,cases=rows,source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(paths))},
        summary={track:dict(episodes=len(rr),strict_successes=sum(r['strict_success'] for r in rr),replay_passes=sum(r['replay_passed'] for r in rr)) for track in sorted({r['track'] for r in rows}) for rr in [[r for r in rows if r['track']==track]]},
        control='Standalone hand-coded public-observation policies in a local macOS default-deny sandbox; not learned-model performance.',limitations=['Platform-specific OS probes; not an independent security audit or kernel-exploit assessment.','Source and task files are denied locally, but all evaluated cases remain public development cases.','Supply-chain, sensor and CAD runs cover explicitly selected example-agent subsets only.','Workflow and procurement controls cover their complete current catalogs.','Legacy execution, engineering, seasons, networked providers and non-stdlib agent dependencies are not qualified by this report.'])
    (ROOT/'reports/isolation-qualification.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    passed=probes['passed'] and bool(rows) and all(r['strict_success'] and r['replay_passed'] for r in rows)
    print(json.dumps(dict(passed=passed,episodes=len(rows),summary=report['summary'])),flush=True)
    return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
