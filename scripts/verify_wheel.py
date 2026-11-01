"""Verify every frozen source/asset in a built wheel and smoke-test installed CAD.

The temporary installation uses existing optional CAD dependencies; no provider,
real ERP, customer system or untrusted submitted Python is executed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(wheel,output):
    wheel=Path(wheel).resolve();version=tomllib.loads((ROOT/'pyproject.toml').read_text())['project']['version']
    manifest=json.loads((ROOT/'manifest.json').read_text());assets=sources=0
    with zipfile.ZipFile(wheel) as archive:
        names=archive.namelist()
        if len(names)!=len(set(names)):raise ValueError('duplicate wheel entries')
        for name,expected in manifest['sha256'].items():
            if not name.startswith('src/'):continue
            path=name[4:]
            if path not in names or hashlib.sha256(archive.read(path)).hexdigest()!=expected:raise ValueError('wheel source/asset mismatch: '+name)
            if Path(name).suffix in ('.png','.pdf','.step'):assets+=1
            else:sources+=1
        for name in ('LICENSE','NOTICE','DATA_LICENSE'):
            matches=[path for path in names if path.endswith('.dist-info/licenses/'+name)]
            if len(matches)!=1 or archive.read(matches[0])!=(ROOT/name).read_bytes():raise ValueError('missing or different distribution license/notice: '+name)
        metadata_name=next(name for name in names if name.endswith('.dist-info/METADATA'))
        metadata=archive.read(metadata_name).decode()
        if '\nVersion: '+version+'\n' not in '\n'+metadata:raise ValueError('wheel version mismatch')
    with tempfile.TemporaryDirectory(prefix='faraday-wheel-') as directory:
        target=Path(directory)/'installed'
        installed=subprocess.run(['uv','pip','install','--python',sys.executable,'--target',str(target),'--no-deps',str(wheel)],capture_output=True,text=True)
        if installed.returncode:raise ValueError('temporary wheel install failed: '+installed.stderr[-1000:])
        code='''import json,sys
from pathlib import Path
import faraday_manufacturing_benchmark as package
from faraday_manufacturing_benchmark.cad_cases import catalog,build
from faraday_manufacturing_benchmark.cad import grade_candidate,public_packet
assert Path(package.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve())
rows=[]
for family in ('rounded_plate','chamfered_pocket','tapered_hub','lofted_adapter'):
    task=next(t for t in catalog() if t['family']==family and t['mode']=='text_and_drawing' and t['draw']==0)
    packet=public_packet(task)
    result=grade_candidate(task,dict(program=build(task)['program']))
    assert result['strict_success'],result
    rows.append(dict(family=family,score=result['score'],strict_success=result['strict_success']))
print(json.dumps(dict(version=package.__version__,cases=len(catalog()),families=len({t['family'] for t in catalog()}),advanced_smoke=rows)))
'''
        env=dict(os.environ,PYTHONPATH=str(target),RUST_LOG='error')
        run=subprocess.run([sys.executable,'-c',code,str(target)],env=env,capture_output=True,text=True,timeout=180)
        if run.returncode:raise ValueError('installed-wheel CAD smoke failed: '+run.stderr[-2000:])
        smoke=json.loads(run.stdout)
        if smoke['version']!=version or smoke['cases']!=manifest['cad_cases']:raise ValueError('installed wheel catalog mismatch')
    report=dict(passed=True,wheel=str(wheel.relative_to(ROOT)),wheel_sha256=sha(wheel),version=version,
        release_manifest_sha256=sha(ROOT/'manifest.json'),verifier_sha256=sha(Path(__file__)),frozen_assets_matched=assets,
        frozen_source_json_files_matched=sources,licenses_present=['LICENSE','NOTICE','DATA_LICENSE'],installed_wheel=smoke,
        scope='Artifact source/asset/metadata integrity and four installed-wheel author geometry controls. Not an external-model or expert-validation result.')
    Path(output).write_text(json.dumps(report,indent=2,sort_keys=True)+'\n');return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--wheel',required=True);p.add_argument('--output',default='reports/wheel-verification.json');args=p.parse_args()
    r=verify(args.wheel,args.output);print(json.dumps({k:r[k] for k in ('passed','version','frozen_assets_matched','frozen_source_json_files_matched','wheel_sha256')}))
