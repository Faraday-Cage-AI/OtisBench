"""Reproduce pinned SemiKong author qualification; retain every local episode."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
CACHE=ROOT/'runs/expanded-survey/2026-11-01'
PIN='24eaa3e239839576041fc3b1ce48af611951ac63'
FILES=['benchmark/__init__.py','benchmark/semikongbench100/__init__.py','benchmark/semikongbench100/spec.py',
       'benchmark/semikongbench100/world.py','benchmark/semikongbench100/evaluation.py','benchmark/semikongbench100/schema.sql']


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path,value):Path(path).write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')


def verified_source():
    pins=json.loads((CACHE/'repository-pins.json').read_text());pin=pins['semikong']
    if pin['repository']!='blobfishai/semiconductor-agent-simulation' or pin['commit']!=PIN:raise ValueError('unexpected source identity')
    tree=json.loads((CACHE/'semikong/tree.json').read_text());entries={r['path']:r for r in tree['tree'] if r['type']=='blob'}
    if tree.get('truncated') is not False:raise ValueError('truncated source tree')
    source=CACHE/'semikong/source';hashes={}
    for name in FILES+['benchmark/semikongbench100/release/huggingface/qualification.json']:
        data=(source/name).read_bytes();git=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        if git!=entries[name]['sha']:raise ValueError('pinned Git blob mismatch: '+name)
        hashes[name]=sha(source/name)
    return source,hashes


def run(destination):
    destination=Path(destination).resolve()
    if destination.exists() or not destination.is_relative_to(ROOT):raise ValueError('use a fresh local run directory')
    source,hashes=verified_source();destination.mkdir(parents=True)
    code='''import sys,json,gzip,platform,sqlite3
from pathlib import Path
from collections import defaultdict
sys.path.insert(0,sys.argv[1]);output=Path(sys.argv[2])
from benchmark.semikongbench100 import evaluation as e
from benchmark.semikongbench100.spec import build_tasks
tasks=build_tasks();original=e.run_episode;seen=defaultdict(int);rows=[]
labels=['oracle','oracle_replay','noop','shortcut','state_only','wrong_source','wrong_target','unsafe_release']
def retain(task,steps):
    result=original(task,steps);index=seen[task['task_id']];seen[task['task_id']]+=1;label=labels[index]
    path=output/(task['task_id']+'-'+label+'.json.gz')
    path.write_bytes(gzip.compress(json.dumps(result,separators=(',',':')).encode(),mtime=0))
    rows.append({'task_id':task['task_id'],'policy':label,'receipt':path.name,'passed':result['verdict']['passed'],'score':result['verdict']['score']})
    return result
e.run_episode=retain
qualification=e.qualify(tasks)
(output/'qualification.json').write_text(json.dumps(qualification,indent=2,sort_keys=True)+'\\n')
assert len(rows)==800 and all(n==8 for n in seen.values())
assert qualification==json.loads(Path(sys.argv[3]).read_text()),'local qualification differs from pinned publisher artifact'
# Independently repeat the published scorer on every retained state/trace.
by_id={task['task_id']:task for task in tasks}
for row in rows:
    receipt=json.loads(gzip.decompress((output/row['receipt']).read_bytes()))
    assert e.score_episode(by_id[row['task_id']],receipt['before'],receipt['after'],receipt['trace'])==receipt['verdict']
(output/'episodes.json').write_text(json.dumps(rows,indent=2,sort_keys=True)+'\\n')
(output/'runtime.json').write_text(json.dumps({'python':sys.version,'sqlite':sqlite3.sqlite_version,'platform':platform.platform(),'overlay':'Host Python 3.11 standard library; publisher CLI examples name Python 3.12. No source or policy changes.'},indent=2)+'\\n')
print(json.dumps({'qualification_passed':qualification['qualification_passed'],'episodes':len(rows),'oracle':qualification['oracle'],'determinism':qualification['determinism']}))
'''
    env={'PATH':os.defpath,'HOME':str(destination),'TMPDIR':str(destination),'LANG':'C','LC_ALL':'C','PYTHONDONTWRITEBYTECODE':'1'}
    published=source/'benchmark/semikongbench100/release/huggingface/qualification.json'
    execution=subprocess.run([sys.executable,'-I','-S','-c',code,str(source),str(destination),str(published)],env=env,capture_output=True,text=True,timeout=1200)
    (destination/'execution.stdout').write_text(execution.stdout);(destination/'execution.stderr').write_text(execution.stderr)
    if execution.returncode:raise ValueError('upstream qualification failed; retained stderr: '+execution.stderr[-1500:])
    _,after=verified_source()
    if after!=hashes:raise ValueError('source changed during run')
    report=dict(passed=True,commit=PIN,source_sha256=hashes,runner_sha256=sha(__file__),runtime=json.loads((destination/'runtime.json').read_text()),
        qualification=json.loads((destination/'qualification.json').read_text()),retained_episode_count=800,
        files={p.name:sha(p) for p in destination.iterdir() if p.is_file()},
        scope='Pinned upstream unchanged author-policy/verifier qualification and retained-state regrading. No learned model, native Faraday task, Harbor isolation, production fab integration or independent practitioner validation.')
    save(destination/'reproduction.json',report);return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',default='runs/expanded-survey/semikong-reproduction-v2');a=p.parse_args();r=run(a.output_dir)
    print(json.dumps(dict(passed=r['passed'],retained_episodes=r['retained_episode_count'],oracle=r['qualification']['oracle'])))
