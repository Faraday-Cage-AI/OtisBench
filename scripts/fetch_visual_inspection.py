"""Acquire official CC-BY-4.0 VisA image/mask bytes without a duplicate tar copy."""
from __future__ import annotations

from collections import Counter
import argparse
import csv
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile

ROOT=Path(__file__).resolve().parents[1]
URL='https://amazon-visual-anomaly.s3.us-west-2.amazonaws.com/VisA_20220922.tar'
ETAG='"05c830591a1172938cb714895c9e0cfb-113"'
ARCHIVE_BYTES=1929840640
REVISION='2a692ab575001cbde74d402d897a7286086c6199'
REPOSITORY_SHA={
    'LICENSE-DATASET':'9e5f1b3c610b9c2da5c313bf81d577a7d1acec686bdb0384edefa6df0f90cd94',
    'README.md':'803d1a86c80fcdebc63dfabd041f78336c433ca635b735668aadb24bfc124917',
    'utils/metrics.py':'9b7633092638debca775e1ddc5ab2177cce75f1290298b84a5a065f430f1658d',
    'utils/id2class.py':'4b862131cb8c080f864815fb16ab906165691618fd4734edf35131b759eb25e3',
    'split_csv/1cls.csv':'a48557e6033318cb90556f706196bc9d247a776a23ea51aecee5a80dd0332995',
}


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda:source.read(1<<20),b''):h.update(block)
    return h.hexdigest()


def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n')


def member_name(name):
    path=PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or '\\' in name or not path.parts:
        raise ValueError('unsafe archive member path')
    return path.as_posix().rstrip('/')


class HashReader:
    def __init__(self,source):self.source=source;self.hash=hashlib.sha256();self.count=0
    def read(self,size=-1):
        value=self.source.read(size);self.hash.update(value);self.count+=len(value);return value


def acquire(destination,repository):
    destination=Path(destination).resolve();repository=Path(repository).resolve()
    if destination.exists():raise ValueError('refusing to overwrite retained acquisition')
    for name,expected in REPOSITORY_SHA.items():
        if sha(repository/name)!=expected:raise ValueError('pinned upstream repository file changed: '+name)
    rows=list(csv.DictReader((repository/'split_csv/1cls.csv').open()))
    if len(rows)!=10821 or len({row['image'] for row in rows})!=10821:raise ValueError('official split inventory differs')
    needed={row['image'] for row in rows}|{row['mask'] for row in rows if row['mask']}
    if len(needed)!=12021:raise ValueError('official image/mask inventory differs')
    if shutil.disk_usage(destination.parent).free<ARCHIVE_BYTES+int(1.5*(1<<30)):
        raise ValueError('insufficient free disk for unique image bytes plus 1.5 GiB reserve')
    destination.mkdir(parents=True);raw=destination/'raw';raw.mkdir();files={};seen=set()
    with (destination/'curl.log').open('wb') as log:
        process=subprocess.Popen(['curl','--fail','--location','--proto','=https','--tlsv1.2','--max-time','900',
            '--header','If-Match: '+ETAG,'--dump-header',str(destination/'headers.txt'),URL],stdout=subprocess.PIPE,stderr=log)
        stream=HashReader(process.stdout)
        try:
            with tarfile.open(fileobj=stream,mode='r|') as archive:
                for member in archive:
                    name=member_name(member.name)
                    if name in seen:raise ValueError('duplicate archive member')
                    seen.add(name)
                    if not (member.isfile() or member.isdir()):raise ValueError('unsupported archive member type')
                    if name not in needed:continue
                    if member.size>10*(1<<20):raise ValueError('unexpectedly large individual image')
                    if shutil.disk_usage(destination).free<member.size+int(1.5*(1<<30)):
                        raise ValueError('stopping acquisition before disk reserve is consumed')
                    path=raw/name;path.parent.mkdir(parents=True,exist_ok=True)
                    with archive.extractfile(member) as source,path.open('wb') as output:shutil.copyfileobj(source,output)
                    if path.stat().st_size!=member.size:raise ValueError('truncated member')
                    files[name]=dict(sha256=sha(path),bytes=member.size,tar_header_offset=member.offset,data_offset=member.offset_data)
                    if len(files)%1000==0:print(json.dumps(dict(retained_files=len(files),stream_bytes=stream.count)),flush=True)
            while stream.read(1<<20):pass
            status=process.wait(timeout=30)
            if status or stream.count!=ARCHIVE_BYTES or set(files)!=needed:
                raise ValueError('source stream, process or required file closure differs')
        finally:
            process.stdout.close()
            if process.poll() is None:process.terminate();process.wait(timeout=30)
    headers=(destination/'headers.txt').read_text()
    if ETAG not in headers or f'Content-Length: {ARCHIVE_BYTES}'.lower() not in headers.lower():
        raise ValueError('upstream archive identity headers differ')
    manifest=dict(protocol='visa-official-acquisition/1',source_url=URL,etag=ETAG,archive_bytes=stream.count,
        archive_sha256=stream.hash.hexdigest(),repository_revision=REVISION,
        repository=str(repository.relative_to(ROOT)),repository_sha256=REPOSITORY_SHA,
        official_images=len(rows),official_masks=len(needed)-len(rows),categories=sorted({row['object'] for row in rows}),
        image_split_counts={':'.join(key):value for key,value in sorted(Counter((row['object'],row['split'],row['label']) for row in rows).items())},
        raw_files=files,fetcher_sha256=sha(__file__),native_case_count_added=0,
        license='CC-BY-4.0; upstream image/mask bytes unchanged; attribution and source license retained in repository snapshots.',
        scope='All official 1-class split images/masks. Official public labels are development evaluation, not an author-private workflow holdout or customer-site validation.')
    save(destination/'manifest.json',manifest);print(json.dumps({key:manifest[key] for key in ('official_images','official_masks','archive_sha256')}),flush=True)
    return manifest


def verify(destination):
    destination=Path(destination);manifest=json.loads((destination/'manifest.json').read_text())
    if manifest['repository_revision']!=REVISION or manifest['repository_sha256']!=REPOSITORY_SHA or manifest['archive_bytes']!=ARCHIVE_BYTES or manifest['etag']!=ETAG or manifest['source_url']!=URL or manifest['native_case_count_added']!=0:
        raise ValueError('source identity/scope differs')
    repository=ROOT/manifest['repository']
    for name,expected in REPOSITORY_SHA.items():
        if sha(repository/name)!=expected:raise ValueError('upstream repository snapshot changed')
    rows=list(csv.DictReader((repository/'split_csv/1cls.csv').open()))
    expected={row['image'] for row in rows}|{row['mask'] for row in rows if row['mask']}
    if set(manifest['raw_files'])!=expected or len(rows)!=10821:raise ValueError('raw file closure differs')
    actual={path.relative_to(destination/'raw').as_posix() for path in (destination/'raw').rglob('*') if path.is_file()}
    if actual!=expected:raise ValueError('raw directory inventory differs')
    for name,record in manifest['raw_files'].items():
        path=destination/'raw'/member_name(name)
        if sha(path)!=record['sha256'] or path.stat().st_size!=record['bytes']:raise ValueError('raw image bytes changed')
    return dict(passed=True,images=len(rows),masks=len(expected)-len(rows),manifest_sha256=sha(destination/'manifest.json'))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['acquire','verify'])
    parser.add_argument('--destination',default='runs/visual-inspection-data-v1');parser.add_argument('--repository',default='runs/visual-inspection-source-v1/repository')
    args=parser.parse_args()
    if args.command=='acquire':acquire(ROOT/args.destination,ROOT/args.repository)
    else:print(json.dumps(verify(ROOT/args.destination)))
