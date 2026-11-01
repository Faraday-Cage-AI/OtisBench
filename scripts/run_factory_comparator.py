"""Reproduce pinned upstream author qualification; no models or provider keys.

Requires macOS sandbox-exec and Python >=3.12. This verifies local deterministic
controls, not the upstream Harbor boundary or the publisher's paid model run.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import time
ROOT=Path(__file__).resolve().parents[1]
CACHE=ROOT/'runs/comparator-audit/2026-11-01'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--python',required=True);parser.add_argument('--fetch',action='store_true');args=parser.parse_args()
    if platform.system()!='Darwin' or not Path('/usr/bin/sandbox-exec').is_file():parser.error('this local qualification recipe requires macOS network denial')
    python=shutil.which(args.python)
    if not python:parser.error('Python runtime not found')
    config=json.loads((ROOT/'docs/comparators/sources.json').read_text());repo=config['repositories']['factory'];commit=repo['commit'];tree=json.loads((CACHE/'factory-tree.json').read_text())
    if tree['sha']!=commit or tree.get('truncated') is not False:parser.error('pinned source tree missing or incomplete; capture comparator sources first')
    chosen=[r for r in tree['tree'] if r['type']=='blob' and (r['path'].startswith('factorybench/') or r['path'] in ('LICENSE','LICENSE-DATA'))]
    target=CACHE/'factory-upstream';target.mkdir(exist_ok=True)
    def materialize(row):
        path=target/row['path']
        if not path.resolve().is_relative_to(target.resolve()):raise ValueError('unsafe upstream path')
        if args.fetch and not path.is_file():
            path.parent.mkdir(parents=True,exist_ok=True);url=f'https://raw.githubusercontent.com/{repo["repository"]}/{commit}/{row["path"]}'
            subprocess.run(['curl','--fail','--silent','--show-error','--location','--proto','=https','--proto-redir','=https','--max-time','30','--max-filesize','12000000',url,'--output',str(path)],capture_output=True,check=True)
        blob=path.read_bytes()
        if hashlib.sha1(b'blob '+str(len(blob)).encode()+b'\0'+blob).hexdigest()!=row['sha']:raise ValueError('pinned Git blob mismatch: '+row['path'])
        return str(path.relative_to(target)),sha(path)
    hashes=dict(ThreadPoolExecutor(max_workers=6).map(materialize,chosen))
    version=subprocess.run([python,'--version'],capture_output=True,text=True,check=True).stdout.strip();output=CACHE/'factory-local-qualification.json'
    script='import sys,runpy;assert sys.version_info>=(3,12);sys.path.insert(0,sys.argv[1]);sys.argv=["factorybench.evaluation","--output",sys.argv[2]];runpy.run_module("factorybench.evaluation",run_name="__main__")'
    with tempfile.TemporaryDirectory(prefix='faraday-upstream-eval-') as directory:
        started=time.monotonic();p=subprocess.run(['/usr/bin/sandbox-exec','-p','(version 1)(allow default)(deny network*)',python,'-I','-S','-B','-c',script,str(target),str(output)],cwd=directory,env={'HOME':directory,'TMPDIR':directory,'PATH':'/usr/bin:/bin','LANG':'C'},capture_output=True,text=True,timeout=180);elapsed=time.monotonic()-started
    execution=dict(commit=commit,python=python,python_version=version,python_binary_sha256=sha(Path(python)),returncode=p.returncode,elapsed_seconds=elapsed,stderr=p.stderr[-2000:],source_hashes=hashes,source_unchanged=all(sha(target/name)==digest for name,digest in hashes.items()),network='OS denied for local deterministic qualification process',scope='Upstream self-qualification, not a model run and not reproduction of Harbor agent isolation.',recipe_sha256=sha(Path(__file__)))
    (CACHE/'factory-local-execution.json').write_text(json.dumps(execution,indent=2,sort_keys=True)+'\n')
    if p.returncode or not execution['source_unchanged']:print(json.dumps(execution));return 1
    q=json.loads(output.read_text());published=json.loads((CACHE/'factory-qualification.source').read_text());matched=q==published
    print(json.dumps(dict(qualification_passed=q['qualification_passed'],tasks=q['task_count'],executions=q['executions'],exact_publisher_report_match=matched)))
    return 0 if matched and q['qualification_passed'] else 1

if __name__=='__main__':raise SystemExit(main())
