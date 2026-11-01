"""Recorded scan-policy integrity and separate fresh public-observation replay."""
import argparse
from collections import Counter
from io import BytesIO
import json
from pathlib import Path
from pypdf import PdfReader
import supplier_scans as scans
from faraday_manufacturing_benchmark.documents import grade
from faraday_manufacturing_benchmark.document_cases import build as source_build
from faraday_manufacturing_benchmark.isolation import isolated_agent,POLICY_VERSION
ROOT=scans.ROOT


def safe(root,name):
    path=(root/name).resolve()
    if not path.is_relative_to(root.resolve()):raise ValueError('path escapes declared root')
    return path


def validate(report_path,source_snapshot=None):
    report_path=Path(report_path).resolve();report=json.loads(report_path.read_text())
    if report.get('status')!='complete' or report.get('protocol')!='supplier-scan-public-agent/1':raise ValueError('incomplete or unknown scan report')
    source_root=Path(source_snapshot).resolve() if source_snapshot else ROOT
    required={'scripts/qualify_scan_agent.py','scripts/scan_ocr_tools.py','scripts/supplier_scans.py','scripts/document_formats.py',
        'examples/supplier_scan_agent.py','src/faraday_manufacturing_benchmark/documents.py',
        'src/faraday_manufacturing_benchmark/document_cases.py','src/faraday_manufacturing_benchmark/isolation.py'}
    if set(report['source_sha256'])!=required:raise ValueError('incomplete source coverage')
    for name,expected in report['source_sha256'].items():
        if scans.formats.sha(safe(source_root,name))!=expected:raise ValueError('scan implementation commitment changed: '+name)
    policy=safe(source_root,'examples/supplier_scan_agent.py')
    meta=report['isolation']
    if meta['policy_version']!=POLICY_VERSION or meta['agent_sha256']!=scans.formats.sha(policy) or meta['network']!='denied':raise ValueError('agent isolation metadata inconsistent')
    probe=report['private_path_probe'];paths=probe['result']['paths']
    if probe['host_positive_controls']!=4 or len(paths)!=4 or any(r.get('readable') is not False or r.get('error_type')!='PermissionError' for r in paths.values()):raise ValueError('private-path probe verdict inconsistent')
    corpus=safe(ROOT,report['corpus']);manifest=scans.validate_corpus(corpus)
    if scans.formats.sha(corpus/'manifest.json')!=report['extension_manifest_sha256']:raise ValueError('corpus manifest changed')
    entries={e['packet']:e for e in manifest['cases']};rows=report['cases']
    if len(rows)!=len(entries) or {r['packet'] for r in rows}!=set(entries):raise ValueError('missing, duplicate or extra scan case')
    if report['presentations_expected']!=len(entries) or report['presentations_resolved']!=len(entries) or report['exact_public_observation_replays']!=len(entries):raise ValueError('completion coverage inconsistent')
    tasks=scans.source_tasks();totals={p:Counter() for p in scans.PROFILES};negative_count=no_read_count=0
    for row in rows:
        entry=entries[row['packet']];task=tasks[entry['evaluator_task_id']]
        if row['profile']!=entry['profile']:raise ValueError('profile mismatch')
        path=safe(ROOT,row['receipt'])
        if scans.formats.sha(path)!=row['receipt_sha256']:raise ValueError('receipt changed')
        receipt=json.loads(path.read_text())
        if receipt['packet']!=row['packet'] or receipt['extension_manifest_sha256']!=report['extension_manifest_sha256']:raise ValueError('receipt provenance inconsistent')
        meta=json.loads((corpus/entry['packet']/'task.json').read_text());ocr=receipt['ocr']
        expected_pages={(d['id'],p['page']):p for d in meta['documents'] for p in d['pages']};lookup={(r['document_id'],r['page']):r for r in ocr}
        if len(ocr)!=len(expected_pages) or set(lookup)!=set(expected_pages):raise ValueError('OCR page coverage differs')
        for key,r in lookup.items():
            if r['source_sha256']!=expected_pages[key]['sha256']:raise ValueError('OCR page hash mismatch')
        payload={'documents':[]}
        for doc in meta['documents']:
            payload['documents'].append(dict(id=doc['id'],pages=[dict(page=p['page'],text=lookup[doc['id'],p['page']]['text'] if lookup[doc['id'],p['page']]['exit_code']==0 else '') for p in doc['pages']]))
        if receipt['payload']!=payload:raise ValueError('agent payload not derived solely from public OCR observations')
        pages_read={key for key,r in lookup.items() if r['exit_code']==0};answer=receipt['response'].get('answer')
        if answer is not None:
            if grade(task,answer,pages_read)!=receipt['result']:raise ValueError('recorded business grade inconsistent')
            if receipt['corrupted_answer'] is None or grade(task,receipt['corrupted_answer'],pages_read)!=receipt['corrupted_result'] or receipt['corrupted_result']['strict_success']:raise ValueError('quantity corruption control inconsistent')
            from copy import deepcopy
            expected=deepcopy(answer);expected['lines'][0]['ordered_ea']+=1
            if receipt['corrupted_answer']!=expected:raise ValueError('corruption did not exercise quantity')
            negative_count+=1
            if grade(task,answer,set())['strict_success']:raise ValueError('no-read evidence control accepted')
            no_read_count+=1
        elif receipt['result']!=dict(score=0.,strict_success=False,error_type='ExtractionFailed') or not receipt['response'].get('error'):
            raise ValueError('extraction failure inconsistently scored')
        metrics=[]
        for document in source_build(task)['documents']:
            reader=PdfReader(BytesIO(scans.formats.render(document,'legacy_statement')))
            for page,pdf_page in enumerate(reader.pages,1):metrics.append(dict(document_id=document['id'],page=page,**scans.token_metrics(pdf_page.extract_text(),lookup[document['id'],page]['text'])))
        if receipt['metrics']!=metrics:raise ValueError('retained-text OCR metrics inconsistent')
        expected=dict(pages=len(ocr),expected_tokens=sum(m['expected_tokens'] for m in metrics),observed_tokens=sum(m['observed_tokens'] for m in metrics),matched_tokens=sum(m['matched_tokens'] for m in metrics),
                      strict_success=receipt['result']['strict_success'],score=receipt['result']['score'],error=receipt['response'].get('error'))
        if any(row[k]!=v for k,v in expected.items()):raise ValueError('case summary inconsistent')
        total=totals[row['profile']];total['presentations']+=1;total['strict_successes']+=row['strict_success'];total['score']+=row['score']
        for key in ['expected_tokens','observed_tokens','matched_tokens']:total[key]+=row[key]
    for profile,total in totals.items():
        expected=dict(presentations=total['presentations'],strict_successes=total['strict_successes'],mean_business_score=total['score']/total['presentations'],
            token_recall=total['matched_tokens']/total['expected_tokens'],token_precision=total['matched_tokens']/total['observed_tokens'] if total['observed_tokens'] else 0.)
        if report['profiles'][profile]!=expected:raise ValueError('profile summary inconsistent')
    return report,policy,dict(integrity_passed=True,current_sources=not bool(source_snapshot),presentations=len(rows),
        quantity_corruptions_rejected=negative_count,no_read_controls_rejected=no_read_count,profiles=report['profiles'])


def replay(report_path,output,source_snapshot=None):
    output=Path(output)
    if output.exists():raise ValueError('replay output exists; preserve prior run')
    report,policy,summary=validate(report_path,source_snapshot);rows=[]
    with isolated_agent(policy) as agent:
        for row in report['cases']:
            receipt=json.loads(safe(ROOT,row['receipt']).read_text());response=agent.decide('supplier_scan_public_ocr',receipt['payload'])
            if response!=receipt['response']:raise ValueError('fresh isolated response differs: '+row['packet'])
            rows.append(dict(packet=row['packet'],receipt_sha256=row['receipt_sha256'],payload_sha256=scans.formats.digest(receipt['payload']),
                             recorded_response_sha256=scans.formats.digest(receipt['response']),fresh_response_sha256=scans.formats.digest(response)))
        isolation=agent.isolation
    result=dict(report_sha256=scans.formats.sha(report_path),auditor_sha256=scans.formats.sha(__file__),agent_sha256=scans.formats.sha(policy),
        exact_replay=True,presentations=len(rows),cases=rows,isolation=isolation,
        scope='Fresh isolated policy replay of retained public OCR observations, including failures. OCR preprocessing is not rerun.')
    scans.formats.save(output,result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['check','replay']);p.add_argument('--report',required=True);p.add_argument('--source-snapshot');p.add_argument('--output');a=p.parse_args()
    if a.command=='check':
        _,_,result=validate(a.report,a.source_snapshot);result['scope']='Current or archived source, public-payload, OCR metric and business-control integrity; no new OCR or independent validation.'
        if a.output:scans.formats.save(a.output,result)
        print(json.dumps(result))
    else:
        if not a.output:p.error('replay requires --output')
        result=replay(a.report,a.output,a.source_snapshot);print(json.dumps({k:result[k] for k in ['exact_replay','presentations']}))
