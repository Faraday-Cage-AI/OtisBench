"""Capture primary comparator sources with verified TLS; --check is offline/read-only.

Caches are retained under ignored runs/, not redistributed as benchmark data.
No model/provider calls. A source snapshot is not independent validation.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parents[1]
CONFIG=ROOT/'docs/comparators/sources.json'
REPORT=ROOT/'reports/comparator-source-inventory.json'
CACHE=ROOT/'runs/comparator-audit/2026-11-01'
HOSTS={'raw.githubusercontent.com','api.github.com','arxiv.org','autodeskailab.github.io','larkagents.com'}


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_sources(config):
    ids=set();filenames=set()
    for source in config['sources']:
        url=urlsplit(source['url'])
        if url.scheme!='https' or url.hostname not in HOSTS or url.username or url.password:raise ValueError('source is not an allowed primary HTTPS endpoint')
        if not re.fullmatch(r'[a-z0-9-]+',source['id']) or source['id'] in ids:raise ValueError('invalid or duplicate source ID')
        filename=source['cache_file']
        if filename in ('.','..') or Path(filename).name!=filename or filename in filenames:raise ValueError('invalid or duplicate cache filename')
        ids.add(source['id']);filenames.add(filename)
        if source['kind'].startswith('pinned_repository_'):
            commit=source.get('commit','')
            parts=url.path.strip('/').split('/')
            pinned_file=source['kind']=='pinned_repository_file' and url.hostname=='raw.githubusercontent.com' and len(parts)>=4 and parts[2]==commit
            pinned_tree=source['kind']=='pinned_repository_tree' and url.hostname=='api.github.com' and len(parts)==6 and parts[0]=='repos' and parts[3:5]==['git','trees'] and parts[5]==commit
            if not re.fullmatch('[a-f0-9]{40}',commit) or not (pinned_file or pinned_tree):raise ValueError('unpinned repository source')
    return config


def capture(source,refresh=False):
    path=CACHE/source['cache_file'];record=dict(source);record['cache_path']=str(path.relative_to(ROOT));record['observation']='existing cached bytes; original HTTP timestamp not retained'
    if refresh or not path.is_file():
        part=path.with_suffix(path.suffix+'.partial')
        p=subprocess.run(['curl','--silent','--show-error','--fail','--location','--proto','=https','--proto-redir','=https','--max-redirs','3','--max-time','40','--max-filesize','12000000','--write-out','%{http_code}',source['url'],'--output',str(part)],capture_output=True,text=True,timeout=45)
        record.update(http_status=p.stdout[-3:],observation='fresh HTTPS retrieval',retrieved_at=datetime.now(timezone.utc).isoformat())
        if p.returncode:
            part.unlink(missing_ok=True);record.update(status='unavailable',error=p.stderr[-500:]);return record
        part.replace(path)
    record.update(status='available',sha256=sha(path),bytes=path.stat().st_size,cache_modified_at=datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat())
    return record


def check_inventory(config,report):
    errors=[];expected={r['id']:r for r in config['sources']};rows=report.get('sources',[])
    if len(rows)!=len(expected) or {r['id'] for r in rows}!=set(expected):errors.append('source coverage mismatch')
    if report.get('config_sha256')!=sha(CONFIG) or report.get('collector_sha256')!=sha(Path(__file__)):errors.append('collector/config fingerprint mismatch')
    for r in rows:
        if r['id'] not in expected:continue
        if any(r.get(k)!=v for k,v in expected[r['id']].items()):errors.append(r['id']+': source identity mismatch')
        if r['status']=='available':
            path=ROOT/r['cache_path']
            if not path.resolve().is_relative_to(CACHE.resolve()) or path.resolve()!=(CACHE/r['cache_file']).resolve() or not path.is_file() or sha(path)!=r['sha256']:errors.append(r['id']+': missing/changed cached source')
        elif r['status']!='unavailable':errors.append(r['id']+': unrecognized retrieval status')
    return errors


def main():
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');p.add_argument('--refresh',action='store_true');args=p.parse_args()
    config=validate_sources(json.loads(CONFIG.read_text()))
    if args.check:
        if args.refresh:p.error('--check cannot refresh network sources')
        errors=check_inventory(config,json.loads(REPORT.read_text()));print(json.dumps(dict(integrity_passed=not errors,errors=errors,scope='Cached primary-source integrity, not benchmark capability or qualification.')));return int(bool(errors))
    CACHE.mkdir(parents=True,exist_ok=True)
    rows=list(ThreadPoolExecutor(max_workers=6).map(lambda s:capture(s,args.refresh),config['sources']))
    report=dict(schema='comparative-source-inventory/1',assessment_date=config['assessment_date'],created_at=datetime.now(timezone.utc).isoformat(),config_sha256=sha(CONFIG),collector_sha256=sha(Path(__file__)),sources=rows,limitations=['Pinned repositories and snapshots are source evidence, not independent validation.','Mutable publisher pages are identified by content hash and observation time.','Retrieval failures mean unknown evidence, not absent capability.'])
    REPORT.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n');print(json.dumps(dict(sources=len(rows),available=sum(r['status']=='available' for r in rows),unavailable=[r['id'] for r in rows if r['status']!='available'])));return 0

if __name__=='__main__':raise SystemExit(main())
