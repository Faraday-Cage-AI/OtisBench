"""Isolated public-text scan policy with public image-only OCR preprocessing."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from io import BytesIO
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
from pypdf import PdfReader
import supplier_scans as scans
from scan_ocr_tools import recognize
from faraday_manufacturing_benchmark.documents import grade
from faraday_manufacturing_benchmark.document_cases import build as source_build
from faraday_manufacturing_benchmark.isolation import isolated_agent
ROOT = scans.ROOT
POLICY = ROOT / 'examples/supplier_scan_agent.py'
PROBE = '''import json,sys
for line in sys.stdin:
    result={}
    for path in json.loads(line)['payload']['paths']:
        try:
            with open(path,'rb') as stream:stream.read(1)
            result[path]={'readable':True}
        except OSError as error:result[path]={'readable':False,'error_type':type(error).__name__}
    print(json.dumps({'paths':result}),flush=True)
'''


def frozen_sources():
    names = ['scripts/qualify_scan_agent.py','scripts/scan_ocr_tools.py','scripts/supplier_scans.py',
             'scripts/document_formats.py','examples/supplier_scan_agent.py','src/faraday_manufacturing_benchmark/documents.py',
             'src/faraday_manufacturing_benchmark/document_cases.py','src/faraday_manufacturing_benchmark/isolation.py']
    return {name:scans.formats.sha(ROOT/name) for name in names}


def isolation_probe(corpus):
    paths = [ROOT/'src/faraday_manufacturing_benchmark/document_cases.py', ROOT/'src/faraday_manufacturing_benchmark/documents.py',
             ROOT/'scripts/qualify_scan_agent.py', ROOT/'runs/supplier-scans-qualification-v2/doc-revision_effectivity-01-raster_control.json']
    for path in paths:
        if not path.read_bytes():raise ValueError('probe private path missing')
    with tempfile.TemporaryDirectory(prefix='scan-agent-probe-') as temporary:
        path=Path(temporary)/'probe.py';path.write_text(PROBE)
        with isolated_agent(path) as agent:result=agent.decide('scan-probe',dict(paths=[str(p) for p in paths]));isolation=agent.isolation
    if set(result['paths'])!={str(p) for p in paths} or any(r.get('readable') or r.get('error_type')!='PermissionError' for r in result['paths'].values()):raise ValueError('private-path isolation failed')
    return dict(result=result,host_positive_controls=len(paths),isolation=isolation)


def run(corpus, destination, report_path, workers=2):
    corpus=Path(corpus).resolve();destination=Path(destination).resolve();report_path=Path(report_path).resolve()
    if destination.exists():raise ValueError('run already exists; preserve original receipts')
    if not destination.is_relative_to(ROOT) or not report_path.is_relative_to(ROOT):raise ValueError('evidence must remain in checkout')
    manifest=scans.validate_corpus(corpus);sources=frozen_sources();probe=isolation_probe(corpus);destination.mkdir(parents=True)
    tasks=scans.source_tasks();cases=[]
    with ThreadPoolExecutor(max_workers=workers) as pool,isolated_agent(POLICY) as agent:
        for entry in manifest['cases']:
            packet=corpus/entry['packet'];meta=json.loads((packet/'task.json').read_text());jobs=[]
            for document in meta['documents']:
                for page in document['pages']:
                    path=packet/page['filename']
                    if scans.formats.sha(path)!=page['sha256']:raise ValueError('public page changed')
                    jobs.append((document,page,path))
            ocr=list(pool.map(lambda job:dict(document_id=job[0]['id'],page=job[1]['page'],source_sha256=job[1]['sha256'],**recognize(job[2])),jobs))
            lookup={(r['document_id'],r['page']):r for r in ocr};payload={'documents':[]}
            for document in meta['documents']:
                payload['documents'].append(dict(id=document['id'],pages=[dict(page=p['page'],text=lookup[document['id'],p['page']]['text'] if lookup[document['id'],p['page']]['exit_code']==0 else '') for p in document['pages']]))
            # Only the public OCR text and page identities enter the isolated policy.
            response=agent.decide('supplier_scan_public_ocr',payload)
            task=tasks[entry['evaluator_task_id']];pages_read={(r['document_id'],r['page']) for r in ocr if r['exit_code']==0}
            answer=response.get('answer');result=grade(task,answer,pages_read) if answer is not None else dict(score=0.,strict_success=False,error_type='ExtractionFailed')
            negative=None;corrupted=None
            if answer is not None:
                corrupted=deepcopy(answer);corrupted['lines'][0]['ordered_ea']+=1;negative=grade(task,corrupted,pages_read)
                if negative['strict_success']:raise ValueError('wrong quantity accepted')
            # Ground-truth source material is consulted only after the agent reply.
            source=source_build(task);metrics=[]
            for document in source['documents']:
                clean=PdfReader(BytesIO(scans.formats.render(document,'legacy_statement')))
                for page,pdf_page in enumerate(clean.pages,1):metrics.append(dict(document_id=document['id'],page=page,**scans.token_metrics(pdf_page.extract_text(),lookup[document['id'],page]['text'])))
            path=destination/(entry['packet']+'.json')
            scans.formats.save(path,dict(packet=entry['packet'],extension_manifest_sha256=scans.formats.sha(corpus/'manifest.json'),
                payload=payload,ocr=ocr,metrics=metrics,response=response,result=result,corrupted_answer=corrupted,corrupted_result=negative))
            cases.append(dict(packet=entry['packet'],profile=entry['profile'],receipt=str(path.relative_to(ROOT)),receipt_sha256=scans.formats.sha(path),
                strict_success=result['strict_success'],score=result['score'],error=response.get('error'),
                pages=len(ocr),expected_tokens=sum(r['expected_tokens'] for r in metrics),observed_tokens=sum(r['observed_tokens'] for r in metrics),matched_tokens=sum(r['matched_tokens'] for r in metrics)))
            report=dict(protocol='supplier-scan-public-agent/1',status='running',native_case_count_added=0,source_sha256=sources,
                extension_manifest_sha256=scans.formats.sha(corpus/'manifest.json'),corpus=str(corpus.relative_to(ROOT)),
                presentations_expected=len(manifest['cases']),presentations_resolved=len(cases),cases=cases,
                isolation=agent.isolation,private_path_probe=probe,
                tesseract=subprocess.run(['tesseract','--version'],capture_output=True,text=True,check=True).stdout.splitlines()[0],
                scope='Author public-image OCR tool plus isolated standard-library reconciliation policy on the same public development corpus. No private holdout, general supplier OCR, practitioner review or LLM result.')
            scans.formats.save(report_path,report)
            print(entry['packet'],result['score'],result['strict_success'],response.get('error'),flush=True)
    # Fresh isolated replay of all recorded public observations, including failures.
    with isolated_agent(POLICY) as agent:
        for row in cases:
            receipt=json.loads((ROOT/row['receipt']).read_text())
            if agent.decide('supplier_scan_public_ocr',receipt['payload'])!=receipt['response']:raise ValueError('agent response replay differs')
    if frozen_sources()!=sources:raise ValueError('qualification implementation changed')
    report['status']='complete';report['exact_public_observation_replays']=len(cases);report['profiles']={}
    for profile in scans.PROFILES:
        rows=[r for r in cases if r['profile']==profile];n=sum(r['expected_tokens'] for r in rows);m=sum(r['observed_tokens'] for r in rows);hit=sum(r['matched_tokens'] for r in rows)
        report['profiles'][profile]=dict(presentations=len(rows),strict_successes=sum(r['strict_success'] for r in rows),
            mean_business_score=sum(r['score'] for r in rows)/len(rows),token_recall=hit/n,token_precision=hit/m if m else 0.)
    scans.formats.save(report_path,report);return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--corpus',default='output/pdf/supplier-scans-v2');p.add_argument('--run-dir',required=True);p.add_argument('--report',required=True);p.add_argument('--workers',type=int,default=2);a=p.parse_args()
    if not 1<=a.workers<=4:raise ValueError('workers must be 1..4')
    print(json.dumps(run(a.corpus,a.run_dir,a.report,a.workers)['profiles']))
