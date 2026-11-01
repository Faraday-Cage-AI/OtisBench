from copy import deepcopy
import math
import pytest
from faraday_manufacturing_benchmark.shopfloor_cases import catalog,build_records,ROUTES,DISRUPTIONS
from faraday_manufacturing_benchmark.shopfloor import ManufacturingWorkflow,required_controls,replay
from faraday_manufacturing_benchmark.shopfloor_runner import public_task,run


def case(disruption='split_material_lots',family='precision_cnc'):
    return next(t for t in catalog() if t['family']==family and t['disruption']==disruption)


def read(world,*systems):
    for system in systems:assert world.call('read',system=system)['ok']


def reserve(world,lot,units):
    read(world,'PLM','WMS')
    r=world.call('reserve_material',lot_id=lot,units=units)
    assert r['ok'],r
    return r['reservation']['id']


def first_ready(disruption='split_material_lots'):
    w=ManufacturingWorkflow(case(disruption));w.call('wait',minutes=20)
    n=w.records['ERP']['required_units']
    if disruption=='split_material_lots':
        a=w.records['WMS']['lots']['LOT-MAIN']['units'];reserve(w,'LOT-MAIN',a);reserve(w,'LOT-ALT',n-a)
    else:reserve(w,'LOT-MAIN',n)
    # A hand-controlled unit-test instruction makes control validity independent of the reference solver.
    w.records['PLM']['instructions']['OP-01']=dict(revision=w.records['PLM']['revision'],control_kind='energy',energy_kwh_batch=100,batch_units=20,tolerance_fraction=.001)
    read(w,'PLM','MES','HR','QMS','WMS')
    return w,dict(operation_id='OP-01',machine_id='M-01',operator_id='EMP-01-Q',start_minute=w.clock+1,units=n,controls={'energy_kwh_per_unit':5})


def test_large_catalog_has_distinct_routes_and_disruption_contracts():
    tasks=catalog()
    assert len(tasks)==1024
    assert len({t['id'] for t in tasks})==1024
    assert len({tuple(t['route']) for t in tasks})==len(ROUTES)
    assert {t['disruption'] for t in tasks}==set(DISRUPTIONS)
    assert all('seed' not in public_task(t) for t in tasks)


def test_structural_generation_is_deterministic():
    for variant in DISRUPTIONS:
        t=case(variant);a=build_records(t);b=build_records(t)
        assert a==b
        assert sum(o['quantity'] for o in a['ERP']['orders'])==a['ERP']['required_units']
        assert a['MES']['operations']


def test_material_reservation_rejects_lookalike_and_consignment():
    w=ManufacturingWorkflow(case());read(w,'PLM','WMS')
    before=deepcopy(w.records['WMS'])
    for lot in ('LOT-LOOKALIKE','LOT-CONSIGNED'):
        assert not w.call('reserve_material',lot_id=lot,units=1)['ok']
    assert w.records['WMS']==before


def test_missing_reads_do_not_reserve_material():
    w=ManufacturingWorkflow(case())
    assert not w.call('reserve_material',lot_id='LOT-MAIN',units=1)['ok']
    assert not w.records['WMS']['reservations']


def test_revision_change_invalidates_reads_and_changes_process_settings():
    w=ManufacturingWorkflow(case('drawing_effectivity'));read(w,'PLM','WMS')
    old=deepcopy(w.records['PLM']['instructions']['OP-01'])
    w.call('wait',minutes=20)
    assert w.records['PLM']['revision']=='B'
    assert not w._current('PLM')
    assert required_controls(old)!=required_controls(w.records['PLM']['instructions']['OP-01'])
    assert not w.call('reserve_material',lot_id='LOT-MAIN',units=1)['ok']


def test_reserved_lot_can_become_held_before_consumption():
    w=ManufacturingWorkflow(case('late_quality_hold'));reserve(w,'LOT-MAIN',1)
    w.call('wait',minutes=20)
    assert w.records['WMS']['lots']['LOT-MAIN']['status']=='hold'
    assert w.records['WMS']['lots']['LOT-MAIN']['units']>0
    assert not w.consumed


def test_start_consumes_material_once_and_records_genealogy():
    w,args=first_ready();n=args['units']
    result=w.call('start_operation',**args)
    assert result['ok'],result
    assert sum(r['units'] for r in w.consumed)==n
    assert all(r['status']=='consumed' for r in w.records['WMS']['reservations'].values())
    before=deepcopy(w.records['WMS']);spent=w.spent_cents
    args['start_minute']=w.clock+1
    assert not w.call('start_operation',**args)['ok']
    assert w.records['WMS']==before
    assert w.spent_cents==spent


def test_unqualified_operator_cannot_start_and_does_not_consume():
    w,args=first_ready('certification_gap');args['operator_id']='EMP-01'
    before=deepcopy(w.records['WMS'])
    assert not w.call('start_operation',**args)['ok']
    assert w.records['WMS']==before
    assert w.spent_cents==0


def test_valid_machine_is_not_enough_when_batch_limit_is_exceeded():
    w,args=first_ready('batch_capacity');before=deepcopy(w.records['WMS'])
    assert not w.call('start_operation',**args)['ok']
    assert w.records['WMS']==before
    args.update(machine_id='M-01-ALT',start_minute=w.clock+1)
    assert w.call('start_operation',**args)['ok']


def test_tool_replacement_is_required_for_exhausted_primary():
    w,args=first_ready('tool_life_exhaustion')
    assert not w.call('start_operation',**args)['ok']
    read(w,'CMMS','MES')
    assert w.call('replace_tool',machine_id='M-01')['ok']
    read(w,'PLM','MES','HR','QMS','WMS');args['start_minute']=w.clock+1
    assert w.call('start_operation',**args)['ok']


def test_fixture_conflict_is_not_ignored():
    w,args=first_ready('shared_fixture');before=deepcopy(w.records['WMS'])
    assert not w.call('start_operation',**args)['ok']
    assert w.records['WMS']==before
    args['start_minute']=180
    assert w.call('start_operation',**args)['ok']


def test_wrong_process_control_is_executable_but_quality_relevant():
    w,args=first_ready();args['controls']['energy_kwh_per_unit']=4
    assert w.call('start_operation',**args)['ok']
    assert w.parameters_ok is False
    assert w.records['MES']['operations'][0]['parameters_ok'] is False


def test_shipment_without_quality_release_is_critical():
    w=ManufacturingWorkflow(case())
    assert not w.call('ship',order_id='SO-1',units=1,serials=['SN-0001'])['ok']
    assert w.grade()['score']==0
    assert w.grade()['critical_violations']


def test_purchase_approval_cannot_be_rebound_to_more_units():
    w=ManufacturingWorkflow(case());read(w,'ERP','PLM')
    approval=w.call('request_approval',kind='purchase',payload={'units':4,'expedited':False})['approval']['id']
    assert not w.call('purchase',units=5,expedited=False,approval_id=approval)['ok']
    assert not w.records['SCM']['purchase_orders']
    assert w.spent_cents==0


def test_supplier_receipt_occurs_once_and_requires_lead_time():
    w=ManufacturingWorkflow(case());read(w,'ERP','PLM')
    aid=w.call('request_approval',kind='purchase',payload={'units':4,'expedited':True})['approval']['id']
    po=w.call('purchase',units=4,expedited=True,approval_id=aid)['purchase_order']
    assert po['lot_id'] not in w.records['WMS']['lots']
    w.call('wait',minutes=65)
    assert w.records['WMS']['lots'][po['lot_id']]['units']==4
    w.call('wait',minutes=10)
    assert w.records['WMS']['lots'][po['lot_id']]['units']==4
    assert not w.call('purchase',units=4,expedited=True,approval_id=aid)['ok']


def test_finish_with_hallucinated_evidence_does_not_finish():
    w=ManufacturingWorkflow(case())
    assert not w.call('finish',evidence_ids=['SHIP-FAKE','INSP-FAKE'])['ok']
    assert not w.finished
    assert not w.grade()['strict_success']


def test_replay_rejects_tampered_transitions():
    w=ManufacturingWorkflow(case());read(w,'ERP','PLM')
    assert replay(case(),w.trace)==w.grade()
    changed=deepcopy(w.trace);changed[0]['result']['version']=100
    with pytest.raises(ValueError,match='replay mismatch'):replay(case(),changed)


def test_wrong_control_schemas_are_atomic():
    w,args=first_ready();before=deepcopy(w.records['WMS'])
    args['controls']={'rpm':5000}
    assert not w.call('start_operation',**args)['ok']
    assert w.records['WMS']==before
    assert w.spent_cents==0


def test_controls_cover_physical_process_types():
    assert required_controls(dict(control_kind='welding',volts=20,amps=100,efficiency=.8,travel_mm_min=200))=={'heat_kj_mm':.48}
    assert required_controls(dict(control_kind='forming',projected_area_cm2=10,cavity_mpa=20,cavities=2,safety_factor=1))=={'clamp_kn':40}
    assert required_controls(dict(control_kind='thermal',target_temperature_c=200,base_soak_minutes=20,section_mm=4))=={'temperature_c':200,'soak_minutes':40}


def test_same_grade_without_certificate_is_not_usable_stock():
    w=ManufacturingWorkflow(case());read(w,'PLM','WMS')
    assert not w.call('reserve_material',lot_id='LOT-UNCERTIFIED',units=1)['ok']
    assert not w.records['WMS']['reservations']


def test_breakdown_interrupts_running_wip_and_blocks_completion():
    w=ManufacturingWorkflow(case('machine_breakdown'))
    op=w.records['MES']['operations'][0]
    op.update(status='running',machine='M-01',finish=100,start=5,units=10)
    w.call('wait',minutes=20)
    assert op['status']=='interrupted'
    assert not w.call('complete_operation',operation_id='OP-01')['ok']
    read(w,'MES','WMS')
    assert w.call('reroute_interrupted_operation',operation_id='OP-01')['ok']
    assert op['status']=='pending'


def test_batch_release_is_idempotent_and_preserves_shipped_serials():
    w=ManufacturingWorkflow(case())
    w.records['QMS']['release']=dict(inspection_id='INSP-1',revision='C',minute=10)
    w.records['WMS']['serials']={'SN-0001':dict(status='shipped')}
    assert w.call('release_batch',inspection_id='INSP-1')['ok']
    assert w.records['WMS']['serials']['SN-0001']['status']=='shipped'


def test_budget_excludes_using_all_premium_alternates_indiscriminately():
    for family in ROUTES:
        r=build_records(case(family=family));qty=r['ERP']['required_units']
        premium=sum(math.ceil(m['setup_minutes']+m['minutes_per_unit']*qty)*m['cents_per_minute'] for k,m in r['MES']['machines'].items() if k.endswith('-ALT'))
        assert premium>r['ERP']['budget_cents']


def test_an_empty_workflow_cannot_earn_credit_for_just_explaining_a_plan():
    w=ManufacturingWorkflow(case());read(w,'ERP','PLM')
    assert w.grade()['score']==0
    assert not w.grade()['strict_success']


def micro_work_order(disruption='split_material_lots'):
    """Four-unit, one-operation unit fixture; not a catalog benchmark episode."""
    w=ManufacturingWorkflow(case(disruption));r=w.records
    r['ERP']['required_units']=4;r['ERP']['orders']=[dict(id='SO-1',quantity=4,shipped=0,due_minute=1000,priority=1)]
    r['WMS']['lots']['LOT-MAIN']['units']=4
    r['MES']['operations']=r['MES']['operations'][:1]
    r['PLM']['route']=r['PLM']['route'][:1]
    r['PLM']['instructions']['OP-01']=dict(revision='C',control_kind='energy',energy_kwh_batch=20,batch_units=4,tolerance_fraction=.001)
    r['MES']['machines']['M-01'].update(setup_minutes=0,minutes_per_unit=1)
    return w


def manufacture_micro(w):
    read(w,'ERP');reserve(w,'LOT-MAIN',4)
    read(w,'PLM','MES','HR','QMS','WMS')
    assert w.call('start_operation',operation_id='OP-01',machine_id='M-01',operator_id='EMP-01-Q',start_minute=w.clock+1,units=4,controls={'energy_kwh_per_unit':5})['ok']
    w.call('wait',minutes=4)
    assert w.call('complete_operation',operation_id='OP-01')['ok']
    read(w,'QMS','PLM','MES')
    return w.call('measure',fixture_id='FIX-01')['inspection']


def release_and_deliver_micro(w,inspection):
    assert w.call('disposition',inspection_id=inspection['id'],decision='accept')['ok']
    read(w,'QMS','PLM','WMS')
    assert w.call('release_batch',inspection_id=inspection['id'])['ok']
    shipped=w.call('ship',order_id='SO-1',units=4,serials=['SN-0001','SN-0002','SN-0003','SN-0004'])
    assert shipped['ok'],shipped
    assert w.call('finish',evidence_ids=[inspection['id'],shipped['shipment']['id']])['ok']
    assert w.grade()['strict_success']
    assert w.grade()['score']==100


def test_complete_micro_manufacturing_transaction_has_real_shipped_output():
    w=micro_work_order();inspection=manufacture_micro(w)
    release_and_deliver_micro(w,inspection)
    assert w.records['WMS']['finished_stock']==0
    assert sum(r['units'] for r in w.consumed)==4
    assert len(w.records['WMS']['shipments']['SHIP-1']['serials'])==4


def test_nonconformance_requires_rework_and_new_measurement():
    w=micro_work_order('failed_final_inspection');inspection=manufacture_micro(w)
    assert inspection['failed_units']==3
    assert w.call('disposition',inspection_id=inspection['id'],decision='rework')['ok']
    read(w,'ERP','PLM')
    payload=dict(inspection_id=inspection['id'],units=3)
    aid=w.call('request_approval',kind='rework',payload=payload)['approval']['id']
    assert w.call('rework',**payload,approval_id=aid)['ok']
    read(w,'QMS','PLM','MES')
    measured=w.call('measure',fixture_id='FIX-01')['inspection']
    assert measured['id']!=inspection['id']
    assert measured['failed_units']==0
    release_and_deliver_micro(w,measured)


def test_frozen_workflow_manifest_matches_authored_case_design():
    from faraday_manufacturing_benchmark.cli import workflow_catalog
    assert workflow_catalog()==catalog()


def test_delayed_inbound_case_contains_actual_delayed_supply():
    w=ManufacturingWorkflow(case('late_inbound_material'))
    po=w.records['SCM']['purchase_orders']['PO-DELAYED']
    assert po['due_minute']==720
    assert po['lot_id'] not in w.records['WMS']['lots']
    w.call('wait',minutes=300);w.call('wait',minutes=300);w.call('wait',minutes=130)
    assert w.records['WMS']['lots'][po['lot_id']]['units']==po['units']
