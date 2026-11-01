"""Export only verified public synthetic replenishment states to a zip."""
import argparse
import json
from pathlib import Path
import zipfile

from replenishment_benchmark import ROOT, sha, save
from qualify_replenishment import audit


def verify(archive, public):
    manifest=json.loads((public/'manifest.json').read_text())
    expected=set(manifest['files'])|{'manifest.json'}
    with zipfile.ZipFile(archive) as bundle:
        if len(bundle.namelist())!=len(expected) or set(bundle.namelist())!=expected:
            raise ValueError('public archive inventory differs')
        for name in expected:
            if bundle.read(name)!=(public/name).read_bytes(): raise ValueError('public archive bytes differ')
    return dict(passed=True,public_manifest_sha256=sha(public/'manifest.json'),zip_sha256=sha(archive),
        archive=str(archive.relative_to(ROOT)),files=len(expected),development_cases=128,native_case_count_added=0)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='output/replenishment/replenishment-public-development-v1.zip')
    args=parser.parse_args();archive=ROOT/args.output
    if archive.exists(): raise ValueError('refusing to overwrite public archive')
    report=ROOT/'runs/replenishment-development-v1/qualification.json';audit(report)
    public=report.parent/'public'; manifest=json.loads((public/'manifest.json').read_text())
    archive.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as bundle:
        for name in sorted(set(manifest['files'])|{'manifest.json'}): bundle.write(public/name,name)
    result=verify(archive,public);save(ROOT/'reports/replenishment-public-bundle.json',result)
    print(json.dumps(result))
