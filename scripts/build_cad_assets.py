"""Materialize canonical public PNG/starting STEP assets; no target STEP export."""
import base64
import hashlib
import json
from pathlib import Path
from faraday_manufacturing_benchmark.cad_cases import catalog,build
from faraday_manufacturing_benchmark.cad import generate_packet
from faraday_manufacturing_benchmark.cad_kernel import versions
from faraday_manufacturing_benchmark.shopfloor import digest
ROOT=Path(__file__).resolve().parents[1]


def main():
    out=ROOT/'src/faraday_manufacturing_benchmark/data/cad_assets';out.mkdir(parents=True,exist_ok=True)
    manifest=dict(provenance='synthetic-generated',kernel_versions=versions(),generator_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'src/faraday_manufacturing_benchmark'/name for name in ('cad_cases.py','cad_kernel.py','cad_drawings.py')]},cases={})
    for i,t in enumerate(catalog(),1):
        packet=generate_packet(t);directory=out/t['id'];directory.mkdir(parents=True,exist_ok=True);assets={}
        for key,filename in [('drawing','drawing.png'),('baseline_step','revision-a.step')]:
            if key not in packet:continue
            asset=packet[key];blob=base64.b64decode(asset['base64']);(directory/filename).write_bytes(blob)
            assets[key]={k:v for k,v in asset.items() if k!='base64'};assets[key]['filename']=filename
        manifest['cases'][t['id']]=dict(spec_sha256=digest(build(t)),public_metadata={k:v for k,v in packet.items() if k not in ('drawing','baseline_step')},files=assets)
        if i%8==0:print(f'{i}/{len(catalog())} canonical CAD packets',flush=True)
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    print('Canonical CAD assets ready; target geometry and recipes were not exported.')
    return 0

if __name__=='__main__':raise SystemExit(main())
