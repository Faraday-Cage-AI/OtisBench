"""Pinned Business Bench process validator; local authored controls, not model runs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[1]
CACHE=ROOT/'runs/expanded-survey/2026-11-01/businessbench'
PIN='0d09882b59a16f190feac09abc9331a733a6f96b'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def sources():
    metadata=json.loads((CACHE/'commit.json').read_text())
    if metadata['sha']!=PIN:raise ValueError('unexpected Business Bench commit')
    entries={r['path']:r for r in json.loads((CACHE/'tree.json').read_text())['tree'] if r['type']=='blob'};hashes={}
    for path in sorted((CACHE/'source').rglob('*')):
        if not path.is_file():continue
        name=path.relative_to(CACHE/'source').as_posix()
        if name not in entries:continue
        value=path.read_bytes();git=hashlib.sha1(b'blob '+str(len(value)).encode()+b'\0'+value).hexdigest()
        if git!=entries[name]['sha']:raise ValueError('pinned source differs: '+name)
        hashes[name]=sha(path)
    return hashes


def run(destination,seeds):
    destination=Path(destination).resolve()
    if destination.exists() or not destination.is_relative_to(ROOT):raise ValueError('use a fresh local output directory')
    fingerprints=sources();destination.mkdir(parents=True);runtime=ROOT/'runs/expanded-survey/business-runtime/bin/python'
    code='''import sys,json,gzip,shutil,platform,sqlite3,importlib.metadata,time,subprocess
from pathlib import Path
source=Path(sys.argv[1]);output=Path(sys.argv[2]);seeds=json.loads(sys.argv[3]);sys.path.insert(0,str(source/'bench'))
import validate_process as v
original=v.pr.run_attempt;episodes=[]
def retain(task,harness,seed,run_idx,results_root,*args,**kwargs):
    result=original(task,harness,seed,run_idx,results_root,*args,**kwargs)
    key=f'{task}-seed{seed}-{harness}-run{run_idx}-{len(episodes):04}'
    work=Path(result['work_dir']);db=work/'final.db';receipt=output/(key+'.json');database=output/(key+'.db.gz')
    if shutil.disk_usage(output).free<1536*1024**2:raise ValueError('less than 1.5 GiB free; stopping before more retained comparator data')
    if db.exists():database.write_bytes(gzip.compress(db.read_bytes(),mtime=0))
    receipt.write_text(json.dumps(result,indent=2,sort_keys=True)+'\\n')
    episodes.append({'task':task,'harness':harness,'seed':seed,'run':run_idx,'receipt':receipt.name,'database':database.name if db.exists() else None,'passed':result.get('passed'),'error':result.get('error'),'reference_build':bool(kwargs.get('reference_pass'))})
    return result
v.pr.run_attempt=retain
tasks=sorted(p.parent.name for p in (source/'tasks/process').glob('*/task.yaml'));assert tasks==json.loads(sys.argv[4]),'source task selection differs from pinned tree'
rows=[]
for task in tasks:
    for seed in seeds:
        start=time.monotonic()
        try:problems=v.validate(task,seed,True)
        except Exception as error:problems=[type(error).__name__+': '+str(error)]
        row={'task':task,'seed':seed,'passed':not problems,'problems':problems,'wall_seconds':time.monotonic()-start};rows.append(row)
        (output/'progress.json').write_text(json.dumps({'status':'running','scenarios':rows,'episodes':episodes},indent=2)+'\\n')
        print(task,seed,'PASS' if not problems else 'FAIL',problems,flush=True)
report={'status':'complete','validation_passed':all(r['passed'] for r in rows),'tasks':tasks,'seeds':seeds,'scenarios':rows,'episodes':episodes,
'runtime':{'python':sys.version,'sqlite':sqlite3.sqlite_version,'platform':platform.platform(),'packages':{d.metadata['Name']:d.version for d in importlib.metadata.distributions()},'pdftotext':subprocess.run(['pdftotext','-v'],capture_output=True,text=True).stderr.splitlines()[0]}}
(output/'validation.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\\n')
# A completed matrix retains failed cells instead of treating exceptions as passes.
'''
    entries=json.loads((CACHE/'tree.json').read_text())['tree']
    expected_tasks=sorted(r['path'].split('/')[2] for r in entries if r['type']=='blob' and r['path'].startswith('tasks/process/') and r['path'].endswith('/task.yaml'))
    env={'PATH':str(runtime.parent)+':/opt/homebrew/bin:'+os.defpath,'HOME':str(destination),'TMPDIR':str(destination),'LANG':'C','LC_ALL':'C','PYTHONDONTWRITEBYTECODE':'1'}
    with (destination/'execution.stdout').open('w') as stdout,(destination/'execution.stderr').open('w') as stderr:
        result=subprocess.run([str(runtime),'-I','-c',code,str(CACHE/'source'),str(destination),json.dumps(seeds),json.dumps(expected_tasks)],env=env,stdout=stdout,stderr=stderr,timeout=3600)
    if result.returncode:raise ValueError('upstream process validation failed; retained logs at '+str(destination))
    if sources()!=fingerprints:raise ValueError('source changed during comparator run')
    record=dict(passed=json.loads((destination/'validation.json').read_text())['validation_passed'],commit=PIN,source_sha256=fingerprints,runner_sha256=sha(__file__),validation=json.loads((destination/'validation.json').read_text()),
        files={p.name:sha(p) for p in destination.iterdir() if p.is_file()},
        scope='Unchanged public process validator, strict local authored policies on selected declared seeds. Local HTTP/SQLite mode is not official model isolation; no paid model, production ERP, independent practitioner or new native Faraday case claim.')
    (destination/'reproduction.json').write_text(json.dumps(record,indent=2,sort_keys=True)+'\n');return record


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',default='runs/expanded-survey/business-reproduction-v2');p.add_argument('--seeds',default='0,1,2,3,4');a=p.parse_args()
    r=run(a.output_dir,[int(s) for s in a.seeds.split(',')]);print(json.dumps(dict(passed=r['passed'],scenarios=len(r['validation']['scenarios']),episodes=len(r['validation']['episodes']))));raise SystemExit(0 if r['passed'] else 1)
