"""Full public-page/OCR baseline, references, replay and verifier corruption controls."""
from copy import deepcopy
from pathlib import Path
import gzip
import hashlib
import json
from faraday_manufacturing_benchmark.document_cases import catalog,reference
from faraday_manufacturing_benchmark.documents import run,replay,grade,FACTS,GROUPS,extractor_versions,assets
from faraday_manufacturing_benchmark.isolation import isolated_agent
from faraday_manufacturing_benchmark.grading import summarize
ROOT=Path(__file__).resolve().parents[1]


def changed(value,field):
    if isinstance(value,bool):return not value
    if isinstance(value,int):return value+1
    if field=='hold_reasons':return value[:-1] if value else ['invoice_variance']
    if field in ('release_lots','quarantine_lots'):
        bad=deepcopy(value)
        if bad:bad[0]['units']+=1
        else:bad=[dict(lot_id='LOT-NOT-ISSUED',units=1)]
        return bad
    raise ValueError('unsupported mutation')


def main():
    rows=[];results=[];out=ROOT/'runs/qualification/documents';out.mkdir(parents=True,exist_ok=True)
    for index,task in enumerate(catalog(),1):
        with isolated_agent(ROOT/'examples/document_agent.py',timeout=15) as agent:
            episode=run(task,agent);episode['isolation']=agent.isolation
        actual=replay(task,episode);expected,_=reference(task);reference_passed=grade(task,expected)['strict_success'];mutations=[]
        for i,line in enumerate(expected['lines']):
            for field in FACTS:
                bad=deepcopy(expected);bad['lines'][i][field]=changed(line[field],field);mutations.append(dict(line_id=i+1,field=field,rejected=not grade(task,bad)['strict_success']))
            for group in GROUPS:
                bad=deepcopy(expected);bad['lines'][i]['evidence'][group]=[dict(document_id='D-NOT-ISSUED',page=1)];mutations.append(dict(line_id=i+1,field='evidence.'+group,rejected=not grade(task,bad)['strict_success']))
        weak=grade(task,expected,read_pages=set());empty=grade(task,{});missing=deepcopy(expected);missing['lines'].pop();duplicated=deepcopy(expected);duplicated['lines'][3]=deepcopy(duplicated['lines'][0])
        packet_root,entry=assets(task)
        receipt=out/(task['id']+'.json.gz');receipt.write_bytes(gzip.compress(json.dumps(episode,sort_keys=True,allow_nan=False).encode(),mtime=0))
        row=dict(task_id=task['id'],mode=task['mode'],reference_consistent=reference_passed,strict_success=episode['result']['strict_success'],exact_replay=actual==episode['result'],no_read_strict_failure=not weak['strict_success'],empty_zero=empty['score']==0,line_coverage_controls=not grade(task,missing)['strict_success'] and not grade(task,duplicated)['strict_success'],mutations=mutations,tool_calls=len(episode['trace']),pdf_documents=len(entry['documents']),pages=sum(len(d['pages']) for d in entry['documents']),receipt=str(receipt.relative_to(ROOT)),receipt_sha256=hashlib.sha256(receipt.read_bytes()).hexdigest());rows.append(row);results.append(actual)
        print(f'{index}/32 {task["id"]}: strict={row["strict_success"]}, replay={row["exact_replay"]}',flush=True)
    paths=list((ROOT/'src').rglob('*.py'))+[Path(__file__).resolve(),ROOT/'examples/document_agent.py',ROOT/'src/faraday_manufacturing_benchmark/data/document_assets/manifest.json']
    report=dict(track='document-qualification',control='Standalone public-form parsing/reconciliation policy inside the offline macOS boundary. PDF extraction and Tesseract OCR are source tools, not model reasoning. Author references are consistency controls, not independent ground truth.',source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)},extractor_versions=extractor_versions(),cases=rows,summary=summarize(results),mutations=sum(len(r['mutations']) for r in rows),mutations_rejected=sum(m['rejected'] for r in rows for m in r['mutations']),limitations=['Synthetic regular forms and clean rasterized pages; not arbitrary real supplier documents or degraded scan calibration.','Matched PDF modes repeat 16 underlying business scenarios; 32 packets are not 32 independent skills.','No learned-model or vision-model performance claim.','Assessment recommendations do not create POs, release actual stock or pay invoices; coupled execution has its own procurement track.','No independent practitioner or held-out validation.'])
    (ROOT/'reports/documents-qualification.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    passed=all(r['reference_consistent'] and r['strict_success'] and r['exact_replay'] and r['no_read_strict_failure'] and r['empty_zero'] and r['line_coverage_controls'] and all(m['rejected'] for m in r['mutations']) for r in rows)
    print(json.dumps(dict(passed=passed,cases=len(rows),strict_successes=sum(r['strict_success'] for r in rows),mutations=report['mutations'],mutations_rejected=report['mutations_rejected'])))
    return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
