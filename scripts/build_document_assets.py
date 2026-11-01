"""Freeze public PDF/page inputs. Private generated truth never enters assets."""
from pathlib import Path
import hashlib
import json
import subprocess
from faraday_manufacturing_benchmark.document_cases import catalog,build
from faraday_manufacturing_benchmark.document_render import assets
from faraday_manufacturing_benchmark.shopfloor import digest
ROOT=Path(__file__).resolve().parents[1]


def main():
    target=ROOT/'src/faraday_manufacturing_benchmark/data/document_assets';target.mkdir(parents=True,exist_ok=True);entries={};cache={}
    for task in catalog():
        root=target/task['id'];root.mkdir(exist_ok=True);documents=[]
        for doc in build(task)['documents']:
            key=(task['seed'],doc['id'])
            if key not in cache:cache[key]=assets(doc,task['draw'])
            vector,raster,pages=cache[key];blob=vector if task['mode']=='searchable_pdf' else raster;name=doc['id']+'.pdf';(root/name).write_bytes(blob)
            pagefiles=[]
            for i,png in enumerate(pages,1):
                filename=f'{doc["id"]}-p{i}.png';(root/filename).write_bytes(png);pagefiles.append(dict(filename=filename,sha256=hashlib.sha256(png).hexdigest()))
            documents.append(dict(id=doc['id'],title=doc['title'],filename=name,mime_type='application/pdf',sha256=hashlib.sha256(blob).hexdigest(),pages=pagefiles))
        entries[task['id']]=dict(spec_sha256=digest(build(task)),documents=documents)
        print(task['id'],len(documents),'PDF documents',flush=True)
    sources=[ROOT/'src/faraday_manufacturing_benchmark/document_cases.py',ROOT/'src/faraday_manufacturing_benchmark/document_render.py',Path(__file__).resolve()]
    manifest=dict(format='procurement-document-assets/1',generator_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},renderer=subprocess.run(['pdftoppm','-v'],capture_output=True,text=True,check=True).stderr.splitlines()[0],cases=entries)
    (target/'manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')

if __name__=='__main__':main()
