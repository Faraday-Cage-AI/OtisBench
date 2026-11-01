from copy import deepcopy
from pathlib import Path
import base64
import hashlib
import json
import pytest
from faraday_manufacturing_benchmark.document_cases import catalog,build,reference
from faraday_manufacturing_benchmark.documents import grade,DocumentWorld,public_task,assets


def task(family,draw=0,mode='searchable_pdf'):return next(t for t in catalog() if t['family']==family and t['draw']==draw and t['mode']==mode)


@pytest.mark.parametrize('t',catalog(),ids=lambda t:t['id'])
def test_reference_schema_and_matched_pdf_business_truth(t):
    a,_=reference(t);assert grade(t,a)['strict_success']
    other=deepcopy(t);other['mode']='image_pdf' if t['mode']=='searchable_pdf' else 'searchable_pdf'
    assert reference(other)==reference(t)
    startup=json.dumps(public_task(t))
    assert t['family'] not in startup and str(t['seed']) not in startup


def test_current_drawing_and_ack_control_release_not_latest_draft():
    t=task('revision_effectivity');a,_=reference(t);r=a['lines'][0]
    assert r['delivered_ea']==r['ordered_ea'] and r['accepted_ea']==0
    assert r['quarantine_lots'][0]['units']==r['delivered_ea']
    assert r['hold_reasons']==['drawing_mismatch','invoice_variance']
    assert a['lines'][1]['accepted_ea']==a['lines'][1]['ordered_ea']


def test_split_transit_and_duplicate_pods_do_not_create_receipts():
    t=task('split_delivery');a,_=reference(t);r=a['lines'][0]
    assert r['delivered_ea']==r['ordered_ea']//2==r['accepted_ea']
    assert r['shortfall_ea']==r['ordered_ea']-r['accepted_ea']
    assert 'short_receipt' in r['hold_reasons']
    assert len({c['page'] for c in r['evidence']['receiving']})==2


def test_deviation_is_scoped_capped_and_cannot_use_expired_or_draft():
    valid=reference(task('supplier_deviation',0))[0]['lines'][0]
    draft=reference(task('supplier_deviation',1))[0]['lines'][0]
    assert valid['accepted_ea']==valid['ordered_ea']//2
    assert draft['accepted_ea']==0
    assert 'grade_deviation' in valid['hold_reasons'] and 'grade_deviation' in draft['hold_reasons']


def test_short_delivery_credit_and_wrong_certificate_are_separate():
    a=reference(task('receiving_units',1))[0]['lines'];source=build(task('receiving_units',1));pack=source['lines'][0]['pack']
    assert a[0]['accepted_ea']==a[0]['ordered_ea']-pack
    assert a[0]['approve_payment'] and a[0]['net_invoice_cents']==a[0]['supported_payable_cents']
    assert a[1]['delivered_ea']==a[1]['ordered_ea'] and a[1]['accepted_ea']==0
    assert 'certificate_mismatch' in a[1]['hold_reasons']


def test_wrong_destination_and_customs_hold_have_different_physical_state():
    wrong=reference(task('cross_shipment'))[0]['lines'][0];held=reference(task('customs_release'))[0]['lines'][0]
    assert wrong['delivered_ea']==0 and wrong['quarantine_lots']==[]
    assert held['delivered_ea']==held['ordered_ea'] and held['accepted_ea']==0
    assert held['quarantine_lots'] and 'customs_hold' in held['hold_reasons']


def test_invoice_copies_are_alternatives_not_multiple_liabilities():
    t=task('credit_duplicate');a,rules=reference(t);source=build(t)
    assert a['lines'][0]['net_invoice_cents']==source['lines'][0]['ordered']*source['lines'][0]['price']
    assert len(rules[1]['invoice_alternatives'])==2
    alternative=deepcopy(a);alternative['lines'][0]['evidence']['invoice']=rules[1]['invoice_alternatives'][1:]
    assert grade(t,alternative)['strict_success']


def test_correct_numbers_without_observed_source_pages_cannot_be_strict():
    t=task('customs_release');answer,_=reference(t)
    assert not grade(t,answer,read_pages=set())['strict_success']
    bad=deepcopy(answer);bad['lines'][0]['ordered_ea']=True
    assert grade(t,bad)['score']==0
    duplicate=deepcopy(answer);duplicate['lines'][3]=deepcopy(duplicate['lines'][0]);assert not grade(t,duplicate)['strict_success']


def test_citations_cannot_be_swapped_for_superseded_documents():
    t=task('revision_effectivity');a,_=reference(t);old=next(d for d in build(t)['documents'] if d['role']=='po-old')
    a['lines'][0]['evidence']['purchase']=[dict(document_id=old['id'],page=1)]
    assert not grade(t,a)['strict_success']


@pytest.mark.parametrize('mode',['searchable_pdf','image_pdf'])
def test_actual_pdf_and_image_bytes_match_and_mode_has_real_text_difference(mode):
    pytest.importorskip('pypdf');from pypdf import PdfReader
    from io import BytesIO
    t=task('revision_effectivity',mode=mode);root,entry=assets(t)
    for d in entry['documents']:
        pdf=root.joinpath(d['filename']).read_bytes();assert hashlib.sha256(pdf).hexdigest()==d['sha256']
        reader=PdfReader(BytesIO(pdf));assert len(reader.pages)==len(d['pages'])
        assert bool(reader.pages[0].extract_text().strip())==(mode=='searchable_pdf')
        for p in d['pages']:assert hashlib.sha256(root.joinpath(p['filename']).read_bytes()).hexdigest()==p['sha256']


def test_raw_page_tool_returns_only_content_and_rejects_bad_requests():
    pytest.importorskip('pypdf');w=DocumentWorld(task('revision_effectivity'));docs=w.call('list_documents')['documents'];d=docs[0]
    result=w.call('read_page',document_id=d['id'],page=1,method='text')
    assert result['ok'] and 'RFQ' in result['text'] and 'reference' not in result
    assert not w.call('read_page',document_id=d['id'],page=True,method='text')['ok']
    assert not w.call('read_page',document_id='../private',page=1,method='text')['ok']
    image=w.call('read_page',document_id=d['id'],page=1,method='image');assert base64.b64decode(image['image_base64']).startswith(b'\x89PNG')
    assert not w.grade()['strict_success']


def test_public_document_cli_and_isolated_replay(tmp_path):
    import platform,subprocess,sys
    if platform.system()!='Darwin':pytest.skip('requires live macOS sandbox-exec')
    pytest.importorskip('pypdf')
    root=Path(__file__).resolve().parents[1];out=tmp_path/'documents.json'
    command=[sys.executable,'-m','faraday_manufacturing_benchmark','isolated','--track','documents','--task','doc-invoice_matching-01-searchable_pdf','--agent-file',str(root/'examples/document_agent.py'),'--output',str(out)]
    result=subprocess.run(command,capture_output=True,text=True,timeout=20);assert result.returncode==0,result.stderr
    artifact=json.loads(out.read_text());assert artifact['episodes'][0]['result']['strict_success']
    replayed=subprocess.run([sys.executable,'-m','faraday_manufacturing_benchmark','replay',str(out)],capture_output=True,text=True,timeout=20);assert replayed.returncode==0,replayed.stderr
