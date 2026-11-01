from copy import deepcopy
import json
from unittest.mock import patch
import pytest
from faraday_manufacturing_benchmark.supply_cases import catalog,FAMILIES
from faraday_manufacturing_benchmark.supply_reference import solve
from faraday_manufacturing_benchmark.supply_chain import SupplyChainWorld,SupplyView,action_valid,public_task,replay,run


def task(family='source_award',variant=0):return next(t for t in catalog() if t['family']==family and t['variant']==variant)

def read_all(w):
    if w.pending:assert w.call('wait',minutes=6)['ok']
    for system in w.task['systems']:assert w.call('read',system=system)['ok']

def post(w,action):
    p=w.call('propose',action=action);assert p['ok'],p
    a=w.call('request_approval',proposal_id=p['proposal']['id']);assert a['ok'],a
    r=w.call('execute',proposal_id=p['proposal']['id'],approval_id=a['approval']['id']);assert r['ok'],r
    return r['transaction_id']

# Fixed base-case regression expectations anchor each reference contract. These
# are author-maintained fixtures, not independent practitioner ground truth.
BASE={
 'source_award':dict(supplier_id='SUP-1',units=100,total_cents=9000),
 'dual_source_allocation':dict(allocation_units=[60,0,140],total_cents=15200),
 'landed_cost_award':dict(source='import',goods_usd_cents=10560,duty_cents=528,total_cents=13388),
 'quantity_break_buy':dict(buy_units=100,invoice_cents=10000,objective_cents=10000),
 'moq_pack_netting':dict(net_units=90,buy_units=96,packs=4),
 'blanket_release':dict(release_units=80,cost_cents=8000,remaining_units=70,escalate=False),
 'po_amendment':dict(approved=True,total_units=150,open_units=70,commitment_cents=16500),
 'expedite_recovery':dict(lane_id='LANE-3',purchase_units=80,cost_cents=10600,unresolved_units=0),
 'interplant_transfer':dict(transfer_units=[0,50],cost_cents=1000,unresolved_units=0),
 'reorder_safety_stock':dict(safety_units=15,reorder_point_units=115,inventory_position_units=170,buy_units=0),
 'time_phased_netting':dict(projected_units=[15,45,10,15],receipts_units=[25,0,25,25],release_periods=[-1,1,2]),
 'receiving_disposition':dict(accept_units=70,quarantine_units=5,reject_units=0,open_po_units=5),
 'shelf_life_allocation':dict(allocations=[dict(lot_id='LOT-1',units=40),dict(lot_id='LOT-3',units=20)],shortage_units=0),
 'cycle_count_adjustment':dict(adjustment_units=-10,adjustment_value_cents=-1000,ending_units=110,escalate=False),
 'three_way_match':dict(hold=False,reasons=[],pay_cents=6500),
 'duplicate_invoice':dict(duplicate_ids=['BILL-1'],conflict_ids=[],hold=True),
 'freight_claim':dict(file_claim=True,loss_cents=12000,claim_cents=11000),
 'supplier_return':dict(return_units=20,credit_cents=10000,net_recovery_cents=8800,escalate=False),
 'supplier_recall_scope':dict(hold_lots=['FG-1','KIT-1','RAW-1','WIP-1'],notify_shipments=['SHIP-1','SHIP-3'],shipped_units=15,quarantine_units=8),
 'transport_mode':dict(lane_id='LANE-2',cost_cents=5600,escalate=False),
 'container_capacity':dict(units_per_container=83,book_containers=2,cost_cents=16000,unshipped_units=0),
 'supplier_otif':dict(otif_fraction=2/3,late_units=80,short_units=0,escalate=True),
 'carbon_constrained_award':dict(supplier_id='SUP-3',total_cents=7000,carbon_kg=50),
 'alternate_effectivity':dict(part_id='PART-1',cost_cents=9600,shortage_units=0),
}

@pytest.mark.parametrize('family',list(BASE))
def test_fixed_business_contracts(family):
    t=task(family);assert solve(family,t['inputs'])==BASE[family]
    w=SupplyChainWorld(t);read_all(w);tid=post(w,BASE[family]);assert w.call('read_back',transaction_id=tid)['ok'];assert w.call('finish',transaction_id=tid)['ok']
    assert w.grade()['strict_success'];assert replay(t,w.trace)==w.grade()


def test_catalog_counts_are_structural_not_draw_inflation():
    tasks=catalog();assert tasks==catalog();assert len(tasks)==96;assert len(FAMILIES)==24
    assert len({t['id'] for t in tasks})==96
    for f in FAMILIES:
        rows=[t for t in tasks if t['family']==f]
        assert len({json.dumps(t['inputs'],sort_keys=True) for t in rows})==4
        assert all(t['provenance']=='synthetic-authored' for t in rows)

@pytest.mark.parametrize('t',catalog(),ids=lambda t:t['id'])
def test_every_synthetic_condition_can_post_replay_and_finish(t):
    w=SupplyChainWorld(t);read_all(w);answer=solve(t['family'],w.inputs)
    assert action_valid(answer,t['fields'])
    tid=post(w,answer);assert w.call('read_back',transaction_id=tid)['ok'];assert w.call('finish',transaction_id=tid)['ok']
    assert w.grade()['strict_success'];assert replay(t,w.trace)==w.grade()


def test_pending_amendment_invalidates_old_reads_and_changes_actual_inputs():
    w=SupplyChainWorld(task(variant=2));old=deepcopy(w.inputs)
    w.call('read',system='ERP');w.call('wait',minutes=5)
    assert w.version==2 and not w.pending and w.inputs!=old
    assert not w.call('propose',action=BASE['source_award'])['ok']
    assert not w.proposals


def test_proposal_requires_all_authoritative_sources():
    w=SupplyChainWorld(task());w.call('read',system='ERP')
    assert not w.call('propose',action=BASE['source_award'])['ok']
    assert not w.proposals


def test_approval_is_bound_to_exact_proposal_and_single_use():
    w=SupplyChainWorld(task());read_all(w)
    p=w.call('propose',action=BASE['source_award'])['proposal']['id'];a=w.call('request_approval',proposal_id=p)['approval']['id']
    other=dict(BASE['source_award'],total_cents=1)
    p2=w.call('propose',action=other)['proposal']['id']
    assert not w.call('execute',proposal_id=p2,approval_id=a)['ok'];assert not w.transactions
    assert w.call('execute',proposal_id=p,approval_id=a)['ok']
    assert not w.call('execute',proposal_id=p,approval_id=a)['ok'];assert len(w.transactions)==1
    assert w.grade()['score']==0


def test_wrong_commercial_decision_is_not_corrected_or_blocked_by_an_answer_key():
    w=SupplyChainWorld(task());read_all(w);bad=dict(BASE['source_award'],supplier_id='SUP-3',total_cents=7000)
    with patch('faraday_manufacturing_benchmark.supply_reference.solve',side_effect=AssertionError('no solver during execution')):
        tid=post(w,bad)
        assert w.call('read_back',transaction_id=tid)['transaction']['action']==bad
        w.call('finish',transaction_id=tid)
    assert not w.grade()['strict_success'];assert w.grade()['score']<100


def test_finish_requires_independent_read_back():
    w=SupplyChainWorld(task());read_all(w);tid=post(w,BASE['source_award'])
    assert not w.call('finish',transaction_id=tid)['ok'];assert not w.finished
    assert not w.grade()['strict_success']


def test_replay_detects_result_action_and_hash_tampering():
    t=task();w=SupplyChainWorld(t);read_all(w);tid=post(w,BASE['source_award']);w.call('read_back',transaction_id=tid);w.call('finish',transaction_id=tid)
    for path in ('result','arguments','state_hash'):
        trace=deepcopy(w.trace)
        if path=='state_hash':trace[-1][path]='0'*64
        else:trace[-1][path]['transaction_id']='TXN-FAKE'
        with pytest.raises(ValueError,match='replay mismatch'):replay(t,trace)


def test_public_contract_and_observations_have_no_answers_or_evaluator_labels():
    t=task('supplier_recall_scope',2);poisoned=deepcopy(t);poisoned['solution']='SECRET';poisoned['seed']=123
    assert public_task(t)==public_task(poisoned)
    text=json.dumps(public_task(poisoned))
    for forbidden in ('SECRET','variant','family','seed','expected','reference_answer'):assert forbidden not in text
    w=SupplyChainWorld(t);view=SupplyView(t)
    for system in t['systems']:
        result=view.encode(w.call('read',system=system));text=json.dumps(result)
        assert 'source_commitment' not in text and 'strict_success' not in text
        assert 'RAW-1' not in text


def test_opaque_identifiers_round_trip_and_preserve_sort_contract():
    t=task('supplier_recall_scope');view=SupplyView(t);answer=BASE[t['family']]
    encoded=view.encode(answer)
    assert encoded['hold_lots']==sorted(encoded['hold_lots'])
    assert view.decode(encoded)==answer
    assert SupplyView(t).encode(answer)!=encoded
    with pytest.raises(ValueError):view.decode('RAW-1')
    with pytest.raises(ValueError):view.decode('REF-invented')


def test_typed_actions_reject_booleans_nonfinite_extra_fields_and_string_numbers():
    t=task();base=BASE['source_award']
    for value in (True,1.0,'100',float('nan'),float('inf')):
        assert not action_valid(dict(base,units=value),t['fields'])
    assert not action_valid(dict(base,extra=1),t['fields'])


def test_api_copies_cannot_mutate_posted_actions():
    w=SupplyChainWorld(task());read_all(w);action=deepcopy(BASE['source_award']);tid=post(w,action);action['units']=1
    result=w.call('read_back',transaction_id=tid);result['transaction']['action']['units']=2
    assert w.transactions[tid]['action']['units']==100


def test_weak_controls_do_not_pass():
    for t in catalog():
        w=SupplyChainWorld(t);read_all(w)
        assert w.grade()['score']==0 and not w.grade()['strict_success']
        w.call('execute',proposal_id='PROP-FAKE',approval_id='AUTH-FAKE')
        assert w.grade()['critical_violations'] and w.grade()['score']==0


def test_cli_export_neutral_and_listing_does_not_execute(tmp_path,capsys):
    from faraday_manufacturing_benchmark.cli import main
    assert main(['list','--track','supply-chain'])==0
    assert len(capsys.readouterr().out.splitlines())==96
    path=tmp_path/'contract.json'
    assert main(['export-agent','--task',task()['id'],'--output',str(path)])==0
    data=json.loads(path.read_text());assert data['track']=='supply_chain'
    assert 'inputs' not in data['payload']['task'] and 'source_award' not in path.read_text()
