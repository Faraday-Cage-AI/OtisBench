from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch
import pytest
from faraday_manufacturing_benchmark.procurement_cases import catalog,build,CONTRACTS
from faraday_manufacturing_benchmark.procurement import ProcurementWorld,ProcurementView,public_task,run,replay

spec=importlib.util.spec_from_file_location('public_procurement_policy',Path(__file__).parents[1]/'examples/procurement_agent.py')
policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy)


def task(contract='standard_purchase',draw=0):return next(t for t in catalog() if t['contract']==contract and t['draw']==draw)


def successful_prefix(contract='standard_purchase',draw=0):
    t=task(contract,draw);e=run(t,policy.ProcurementPolicy());assert e['result']['strict_success'],e['result']
    w=ProcurementWorld(t)
    for row in e['trace'][:-1]:assert w.call(row['tool'],**row['arguments'])==row['result']
    return w,e


def post(w,kind,payload):
    p=w.call('propose',kind=kind,payload=payload);assert p['ok'],p
    a=w.call('request_approval',proposal_id=p['proposal']['id']);assert a['ok'],a
    return w.call('execute',proposal_id=p['proposal']['id'],approval_id=a['approval']['id'])


def purchase_ready(contract='standard_purchase'):
    w=ProcurementWorld(task(contract));w.call('wait',minutes=7)
    w.call('read',system='ERP');w.call('read',system='SCM');w.call('read_document',document_id='DOC-Q1')
    q=w.quotes['DOC-Q1'];packs=w.records['ERP']['required_units']//q['pack_units']
    payload=dict(supplier_id='SUP-1',quote_document_id='DOC-Q1',quote_revision=q['revision'],packs=packs,total_cents=packs*q['price_cents']+q['freight_cents'])
    return w,payload

@pytest.mark.parametrize('t',catalog(),ids=lambda t:t['id'])
def test_full_raw_document_chain_is_solvable_via_public_observations(t):
    episode=run(t,policy.ProcurementPolicy());result=episode['result']
    assert result['strict_success'],result
    assert result['score']==100 and replay(t,episode['trace'])==result
    assert result['cash_paid_cents']==result['committed_cents']-result['credited_cents']
    assert result['accepted_units']==result['required_units']
    assert result['elapsed_minutes']<=t['horizon_minutes']
    assert len(episode['agent_trace'])==len(episode['trace'])


def test_catalog_counts_distinguish_contracts_and_parameter_draws():
    assert len(catalog())==48 and len(CONTRACTS)==12
    assert len({t['id'] for t in catalog()})==48 and catalog()==catalog()
    assert all(t['provenance']=='synthetic-generated' for t in catalog())
    for t in catalog():assert build(t)==build(t)


def test_stock_and_cash_are_actual_cross_record_consequences():
    w,e=successful_prefix('compound_recovery')
    assert len(w.records['SCM']['purchase_orders'])==2
    assert len(w.records['WMS']['receipts'])==3
    assert w.records['WMS']['quarantined_stock_units']==w.config['damaged_units']
    assert w.records['WMS']['accepted_stock_units']==w.records['ERP']['required_units']
    assert w.credits_cents>0 and w.cash_paid_cents==w.spent_cents-w.credits_cents
    assert all(i['status']=='paid' for i in w.records['AP']['invoices'].values())
    assert any(d['reason']=='amount_mismatch' for d in w.records['AP']['document_dispositions'].values())


def test_quote_revision_invalidates_a_previously_approved_purchase():
    w=ProcurementWorld(task('quote_revision'));q=w.quotes['DOC-Q1'];packs=2
    w.call('read',system='ERP');w.call('read',system='SCM');w.call('read_document',document_id=q['id'])
    p=w.call('propose',kind='purchase',payload=dict(supplier_id='SUP-1',quote_document_id=q['id'],quote_revision=1,packs=packs,total_cents=packs*q['price_cents']+600))['proposal']['id']
    a=w.call('request_approval',proposal_id=p)['approval']['id']
    r=w.call('execute',proposal_id=p,approval_id=a)
    assert r['error']=='source_version_mismatch' and w.quotes['DOC-Q1']['revision']==2
    assert not w.records['SCM']['purchase_orders'] and w.spent_cents==0


def test_wrong_quote_total_does_not_charge_or_create_orders():
    w,payload=purchase_ready();payload['total_cents']-=1
    assert post(w,'purchase',payload)['error']=='commercial_amount_mismatch'
    assert w.spent_cents==0 and not w.records['SCM']['purchase_orders']


def test_suspended_supplier_attempt_is_critical_without_material_or_cash_effects():
    w,payload=purchase_ready('supplier_suspension')
    assert post(w,'purchase',payload)['error']=='supplier_not_qualified'
    assert w.grade()['score']==0 and w.grade()['critical_violations']
    assert w.spent_cents==0


def test_budget_and_capacity_checks_do_not_partially_purchase():
    for bad in ('budget','capacity'):
        w,payload=purchase_ready()
        if bad=='budget':w.records['ERP']['budget_cents']=1
        else:payload['packs']=1000;payload['total_cents']=1000*w.quotes['DOC-Q1']['price_cents']+600
        before=deepcopy(w.records['SCM']['purchase_orders']);r=post(w,'purchase',payload)
        assert not r['ok'] and w.spent_cents==0 and w.records['SCM']['purchase_orders']==before


def test_delivery_not_visible_or_receivable_before_arrival():
    w,payload=purchase_ready();po=post(w,'purchase',payload)['purchase_order'];did=po['delivery_document_ids'][0]
    assert did not in [d['id'] for d in w.call('list_documents')['documents']]
    assert w.call('read_document',document_id=did)['error']=='document_unavailable'
    assert not w.call('receive',po_id=po['id'],delivery_document_id=did,units=po['units'],damaged_units=0)['ok']
    assert w.records['WMS']['accepted_stock_units']==0


def test_duplicate_receiving_is_idempotent_and_mismatched_repeat_is_critical():
    w,payload=purchase_ready();po=post(w,'purchase',payload)['purchase_order'];did=po['delivery_document_ids'][0]
    w.call('wait',minutes=12);w.call('read_document',document_id=did)
    args=dict(po_id=po['id'],delivery_document_id=did,units=po['units'],damaged_units=0)
    first=w.call('receive',**args)['receipt'];again=w.call('receive',**args)
    assert again['idempotent'] and again['receipt']==first
    assert len(w.records['WMS']['receipts'])==1 and w.records['WMS']['quarantined_stock_units']==po['units']
    assert not w.call('receive',**dict(args,units=po['units']+1))['ok']
    assert w.grade()['critical_violations']


def test_wrong_physical_receipt_can_post_but_cannot_pass_grading():
    w,payload=purchase_ready();po=post(w,'purchase',payload)['purchase_order'];did=po['delivery_document_ids'][0]
    w.call('wait',minutes=12);w.call('read_document',document_id=did)
    assert w.call('receive',po_id=po['id'],delivery_document_id=did,units=po['units']+8,damaged_units=0)['ok']
    assert not w.grade()['checks']['physical_receipts_exact']


def test_accepting_pending_certificate_is_critical_and_does_not_release_stock():
    w,payload=purchase_ready('certificate_hold');po=post(w,'purchase',payload)['purchase_order'];did=po['delivery_document_ids'][0]
    w.call('wait',minutes=12);w.call('read_document',document_id=did);truth=w.delivery_truth[did]
    receipt=w.call('receive',po_id=po['id'],delivery_document_id=did,units=truth['units'],damaged_units=truth['damaged_units'])['receipt']
    w.call('read_document',document_id=truth['certificate_document_id'])
    r=w.call('inspect',receipt_id=receipt['id'],certificate_document_id=truth['certificate_document_id'],decision='accept')
    assert r['error']=='certificate_not_released' and w.records['WMS']['accepted_stock_units']==0
    assert w.grade()['score']==0


def test_certificate_release_requires_rereading_changed_source():
    w,payload=purchase_ready('certificate_hold');po=post(w,'purchase',payload)['purchase_order'];did=po['delivery_document_ids'][0]
    w.call('wait',minutes=12);w.call('read_document',document_id=did);truth=w.delivery_truth[did]
    rid=w.call('receive',po_id=po['id'],delivery_document_id=did,units=truth['units'],damaged_units=truth['damaged_units'])['receipt']['id']
    cid=truth['certificate_document_id'];w.call('read_document',document_id=cid);w.call('wait',minutes=8)
    assert w.call('inspect',receipt_id=rid,certificate_document_id=cid,decision='accept')['error']=='certificate_source_required'
    w.call('read_document',document_id=cid);assert w.call('inspect',receipt_id=rid,certificate_document_id=cid,decision='accept')['ok']
    before=w.records['WMS']['accepted_stock_units']
    w.call('inspect',receipt_id=rid,certificate_document_id=cid,decision='accept')
    assert w.records['WMS']['accepted_stock_units']==before


def test_invoice_cannot_be_approved_before_receipts_are_dispositioned():
    w,payload=purchase_ready();po=post(w,'purchase',payload)['purchase_order'];w.call('wait',minutes=20)
    iid=next(iter(w.invoice_truth));w.call('read_document',document_id=iid)
    r=post(w,'invoice',dict(invoice_document_id=iid,decision='approve',amount_cents=po['total_cents'],reason='matched'))
    assert r['error']=='receipts_not_dispositioned' and not w.records['AP']['invoices']


def test_duplicate_invoice_and_duplicate_payment_cannot_create_additional_liabilities():
    w,_=successful_prefix('duplicate_invoice')
    duplicate=next(i for i,t in w.invoice_truth.items() if t['status']=='duplicate');w.call('read_document',document_id=duplicate)
    before=w.cash_paid_cents
    assert post(w,'invoice',dict(invoice_document_id=duplicate,decision='approve',amount_cents=w.invoice_truth[duplicate]['amount_cents'],reason='matched'))['error']=='invoice_duplicate_or_superseded'
    invoice=next(iter(w.records['AP']['invoices'].values()));account=w.records['TREASURY']['supplier_banks'][invoice['supplier_id']]['verified_account']
    assert post(w,'payment',dict(invoice_id=invoice['id'],account=account,amount_cents=invoice['amount_cents']))['error']=='duplicate_payment'
    assert w.cash_paid_cents==before and len(w.records['AP']['payments'])==1

@pytest.mark.parametrize('draw',[0,1,2,3])
def test_bank_callback_handles_verified_and_fraudulent_changes(draw):
    w,e=successful_prefix('bank_change',draw);bank=w.records['TREASURY']['supplier_banks']['SUP-1']
    assert bank['pending_change']['status']==('verified' if draw%2==0 else 'rejected')
    assert bank['verified_account']==('ACCT-NEW' if draw%2==0 else 'ACCT-1')
    assert all(p['account']==p['verified_account_at_payment'] for p in w.records['AP']['payments'].values())


def test_payment_to_email_only_account_is_rejected():
    t=task('bank_change',1);e=run(t,policy.ProcurementPolicy());w=ProcurementWorld(t)
    for row in e['trace']:
        if row['tool']=='propose' and row['arguments']['kind']=='payment':break
        w.call(row['tool'],**row['arguments'])
    invoice=next(iter(w.records['AP']['invoices'].values()))
    assert post(w,'payment',dict(invoice_id=invoice['id'],account='ACCT-NEW',amount_cents=invoice['amount_cents']))['error']=='unverified_payment_account'
    assert w.cash_paid_cents==0


def test_unit_conversion_uses_purchase_packs_and_delivery_cases_independently():
    w,_=successful_prefix('unit_conversion');po=next(iter(w.records['SCM']['purchase_orders'].values()));did=po['delivery_document_ids'][0]
    row=policy.parse_csv(w.documents[did]['body'])
    assert po['pack_units']==24 and int(row['each_per_case'])==6
    assert int(row['case_count'])==po['packs']*4


def test_quantity_discount_is_an_actual_all_units_price_reduction():
    w,_=successful_prefix('quantity_discount');po=next(iter(w.records['SCM']['purchase_orders'].values()));q=w.quotes[po['quote_document_id']]
    assert po['packs']>=10 and po['unit_pack_cents']<q['price_cents']
    assert po['total_cents']==po['packs']*po['unit_pack_cents']+po['freight_cents']


def test_agent_view_redacts_metadata_and_does_not_mutate_sources():
    t=task('compound_recovery');poisoned=dict(t,solution='SECRET',expected_answer=123)
    assert public_task(t)==public_task(poisoned)
    assert all(k not in public_task(t) for k in ('seed','contract','draw','configuration','expected_answer','solution'))
    w=ProcurementWorld(t);before=deepcopy(w.documents);view=ProcurementView()
    text=view.encode(w.call('read_document',document_id='DOC-Q1'))
    assert 'DOC-Q1' not in json.dumps(text) and 'SUP-1' not in json.dumps(text)
    assert w.documents==before
    with pytest.raises(ValueError):view.decode({'supplier_id':'SUP-1'})
    with pytest.raises(ValueError):view.decode('REF-invented')


def test_public_agent_never_receives_private_truth_or_live_scores():
    class RecordingPolicy(policy.ProcurementPolicy):
        def __init__(self):super().__init__();self.payloads=[]
        def decide(self,track,payload):self.payloads.append(deepcopy(payload));return super().decide(track,payload)
    agent=RecordingPolicy();e=run(task('compound_recovery'),agent);assert e['result']['strict_success']
    forbidden={'seed','contract','draw','configuration','delivery_truth','invoice_truth','checks','score','strict_success','source_commitment','state_hash'}
    def keys(x):
        if isinstance(x,dict):
            for k,v in x.items():yield k;yield from keys(v)
        elif isinstance(x,list):
            for v in x:yield from keys(v)
    assert not set(keys(agent.payloads))&forbidden


def test_read_only_and_unauthorized_controls_do_not_pass():
    for t in catalog():
        w=ProcurementWorld(t)
        for system in t['systems']:w.call('read',system=system)
        w.call('list_documents')
        assert w.grade()['score']==0 and not w.grade()['strict_success']
        w.call('execute',proposal_id='PROP-fake',approval_id='AUTH-fake')
        assert w.grade()['critical_violations'] and w.grade()['score']==0


def test_replay_rejects_action_result_and_state_hash_tampering():
    t=task();e=run(t,policy.ProcurementPolicy())
    for field in ('arguments','result','state_hash'):
        trace=deepcopy(e['trace'])
        if field=='state_hash':trace[-1][field]='0'*64
        elif field=='arguments':trace[-1][field]['evidence_ids']=[]
        else:trace[-1][field]['ok']=False
        with pytest.raises(ValueError,match='replay mismatch'):replay(t,trace)


def test_writes_require_a_separate_final_read_back_to_pass():
    w,e=successful_prefix()
    w.system_reads.pop('AP')
    w.call('finish',evidence_ids=e['trace'][-1]['arguments']['evidence_ids'])
    assert not w.grade()['checks']['records_read_back'] and not w.grade()['strict_success']


def test_wrong_invoice_amount_is_not_silently_repaired_and_fails_terminal_grade():
    t=task();e=run(t,policy.ProcurementPolicy());w=ProcurementWorld(t)
    for row in e['trace']:
        if row['tool']=='propose' and row['arguments']['kind']=='invoice':break
        w.call(row['tool'],**row['arguments'])
    docid=next(d for d,v in w.invoice_truth.items() if v['status']=='released');amount=w.invoice_truth[docid]['amount_cents']
    result=post(w,'invoice',dict(invoice_document_id=docid,decision='approve',amount_cents=amount+1,reason='matched'))
    assert result['ok'] and result['invoice']['amount_cents']==amount+1
    assert not w.grade()['checks']['invoices_reconciled']


def test_invoice_documents_do_not_contain_grader_discrepancy_labels():
    w,_=successful_prefix('invoice_variance')
    for docid,truth in w.invoice_truth.items():
        row=policy.parse_csv(w.documents[docid]['body'])
        assert 'status' not in row and 'expected_amount' not in row
        assert row['document_class']=='invoice'
    old=next(d for d,t in w.invoice_truth.items() if t['status']=='superseded')
    assert w.records['AP']['document_dispositions'][old]['reason']=='amount_mismatch'


def test_cli_exports_raw_packet_and_runs_external_agent(tmp_path,capsys):
    import sys,shlex
    from faraday_manufacturing_benchmark.cli import main
    t=task('compound_recovery')
    startup=tmp_path/'startup.json';packet=tmp_path/'packet';artifact=tmp_path/'run.json'
    assert main(['export-agent','--task',t['id'],'--output',str(startup)])==0
    value=json.loads(startup.read_text());assert value['track']=='procurement'
    assert 'contract' not in value['payload']['task'] and 'seed' not in startup.read_text()
    assert main(['export-procurement-documents','--task',t['id'],'--output-dir',str(packet)])==0
    index=json.loads((packet/'index.json').read_text())
    assert index['snapshot_minute']==0 and len(list(packet.glob('*.eml')))==4
    assert all('solution' not in p.read_text() for p in packet.glob('*.eml'))
    command=shlex.quote(sys.executable)+' '+shlex.quote(str(Path(__file__).parents[1]/'examples/procurement_agent.py'))
    assert main(['procurement','--task',t['id'],'--agent-command',command,'--output',str(artifact)])==0
    result=json.loads(artifact.read_text());assert result['summary']['strict_successes']==1
    assert main(['replay',str(artifact)])==0
    result['summary']['strict_successes']=0;artifact.write_text(json.dumps(result))
    with pytest.raises(SystemExit):main(['replay',str(artifact)])


def test_frozen_procurement_catalog_matches_authored_generator():
    from importlib.resources import files
    frozen=json.loads(files('faraday_manufacturing_benchmark').joinpath('data/procurement_tasks.json').read_text())
    assert frozen==catalog()


def test_proposal_payload_cannot_change_after_approval():
    w,payload=purchase_ready()
    p=w.call('propose',kind='purchase',payload=payload)['proposal']['id']
    a=w.call('request_approval',proposal_id=p)['approval']['id']
    # Simulate a corrupted host proposal to verify the authorization fence;
    # ordinary agents never receive mutable references to this host object.
    w.proposals[p]['payload']['packs']+=1
    result=w.call('execute',proposal_id=p,approval_id=a)
    assert result['error']=='authorization_mismatch' and w.spent_cents==0
