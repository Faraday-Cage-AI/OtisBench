"""Qualify the separate real hydraulic source/split/metric/isolation evidence."""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
from hydraulic_benchmark import ROOT,TARGETS,PROTOCOL,read,save,sha,verify,metrics,replay
from faraday_manufacturing_benchmark.isolation import isolated_agent

PROBE = '''import json,sys
for line in sys.stdin:
    request=json.loads(line);result={}
    for path in request['payload']['paths']:
        try:
            with open(path,'rb') as stream:stream.read(1)
            result[path]={'readable':True}
        except OSError as exc:result[path]={'readable':False,'error_type':type(exc).__name__}
    print(json.dumps({'paths':result}),flush=True)
'''


def qualify(destination, output):
    destination=Path(destination).resolve();manifest=verify(destination)
    truth=read(destination/'evaluator/truth.json');groups=read(destination/'evaluator/split-groups.json')
    test={key:row for key,row in truth.items() if row['split']=='test'}
    expected={tuple(row['condition']):row['split'] for row in groups}
    observed={}
    for row in truth.values():
        group=tuple(row['labels'][target] for target in TARGETS)
        if expected[group]!=row['split']:raise ValueError('condition split leakage')
        observed.setdefault(group,set()).add(row['split'])
    if len(observed)!=144 or any(len(splits)!=1 for splits in observed.values()):raise ValueError('group coverage/leakage')
    public_test=read(destination/'public/test.json')
    if any(set(row)!={'id','features'} for row in public_test):raise ValueError('test labels/metadata exposed')
    if any(len(row['features'])!=112 for row in public_test):raise ValueError('feature shape mismatch')
    oracle={key:{target:{str(level):float(row['labels'][target]==level) for level in levels} for target,levels in TARGETS.items()} for key,row in test.items()}
    oracle_result=metrics(test,oracle)
    if oracle_result['joint_exact_accuracy']!=1:raise ValueError('oracle grading failure')
    corrupted=deepcopy(oracle)
    for key,row in test.items():
        levels=TARGETS['cooler'];wrong=levels[(levels.index(row['labels']['cooler'])+1)%len(levels)]
        corrupted[key]['cooler']={str(level):float(level==wrong) for level in levels}
    if metrics(test,corrupted)['joint_exact_accuracy']!=0:raise ValueError('incorrect target accepted')
    private_paths=[destination/'evaluator/truth.json',destination/'evaluator/split-groups.json',destination/'evaluator/raw/PS1.npy',ROOT/'runs/hydraulic-uci-447.zip',ROOT/'scripts/hydraulic_benchmark.py']
    for path in private_paths:
        with path.open('rb') as stream:
            if not stream.read(1):raise ValueError('probe path not live')
    with tempfile.TemporaryDirectory(prefix='hydraulic-probe-') as directory:
        source=Path(directory)/'probe.py';source.write_text(PROBE)
        with isolated_agent(source) as agent:
            probe=agent.decide('hydraulic_probe',dict(paths=[str(path) for path in private_paths]));isolation=agent.isolation
        if set(probe['paths'])!={str(path) for path in private_paths} or any(row['readable'] or row.get('error_type')!='PermissionError' for row in probe['paths'].values()):raise ValueError('evaluator read boundary failed')
    results={}
    for method,path in [('majority',ROOT/'reports/hydraulic-prior-baseline.json'),('knn',ROOT/'reports/hydraulic-knn-baseline.json')]:
        episode=read(path)
        if episode.get('status')!='complete' or episode['method']!=method:raise ValueError('baseline incomplete')
        if episode['agent_sha256']!=sha(ROOT/'examples/hydraulic_knn_agent.py'):raise ValueError('baseline agent changed')
        checked=replay(destination,path)
        results[method]=dict(episode=str(path.relative_to(ROOT)),episode_sha256=sha(path),regrade_passed=checked['passed'],metrics=episode['metrics'],wall_seconds=episode['wall_seconds'])
    controls=[]
    path=destination/'public/test.json';original=path.read_bytes()
    try:
        path.write_bytes(original+b'\n')
        try:verify(destination)
        except ValueError:controls.append(dict(control='changed_public_observations',rejected=True))
        else:raise ValueError('modified source accepted')
    finally:path.write_bytes(original)
    verify(destination)
    report=dict(protocol=PROTOCOL,qualification_passed=True,source_manifest=str((destination/'manifest.json').relative_to(ROOT)),source_manifest_sha256=sha(destination/'manifest.json'),
        sources={str(path.relative_to(ROOT)):sha(path) for path in [Path(__file__),ROOT/'scripts/hydraulic_benchmark.py',ROOT/'examples/hydraulic_knn_agent.py']},
        source_cycles=2205,condition_groups=144,group_overlap_between_partitions=0,native_case_count_added=0,
        test_cycles=len(test),oracle_joint_exact_accuracy=1,wrong_cooler_all_cycles_joint_exact_accuracy=0,
        evaluator_paths_denied=len(private_paths),host_read_positive_controls=len(private_paths),probe=probe,isolation=isolation,
        source_integrity_controls=controls,baselines=results,
        scope='Pinned real-data grouped development classification, local learned/prior baselines and evaluator-read controls. No private workflow holdout, expert review, operational maintenance, cross-rig or LLM claim.')
    save(output,report);return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',default='runs/hydraulic-development-v1');p.add_argument('--output',default='reports/hydraulic-qualification.json');args=p.parse_args()
    r=qualify(args.input,args.output)
    print(json.dumps({k:r[k] for k in ['qualification_passed','source_cycles','condition_groups','test_cycles','evaluator_paths_denied']}))
