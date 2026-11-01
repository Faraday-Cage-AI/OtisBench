import copy
from dataclasses import replace
import math
import pytest
from faraday_manufacturing_benchmark.calculations import SOLVERS
from faraday_manufacturing_benchmark.catalog import TASKS
from faraday_manufacturing_benchmark.grading import equal,grade
from faraday_manufacturing_benchmark.protocol import answer_schema
from faraday_manufacturing_benchmark.season import CASES,FactorySeason,idle_policy,standard_cost,replay


def task(family,n=0):return [t for t in TASKS if t['family']==family][n]


def test_quote_gross_margin_not_markup():
    assert SOLVERS['quote_cost'](task('quote_cost')['inputs'])==dict(blanks=125,cost_cents=303900,minimum_price_cents=434143)


def test_interrupted_soak_is_not_accumulated_release():
    assert SOLVERS['heat_treatment'](task('heat_treatment',1)['inputs'])==dict(in_band_minutes=55,continuous_soak_minutes=30,release=False)


def test_gdt_diametral_error_and_mmc_bonus():
    a=SOLVERS['gdt_position'](task('gdt_position')['inputs'])
    assert a['position_error_mm']==pytest.approx(.2)
    assert a['allowed_mm']==pytest.approx(.22)
    assert a['accept'] is True
    assert SOLVERS['gdt_position'](task('gdt_position',1)['inputs'])['accept'] is False


def test_mrp_time_phasing_and_negative_release_day():
    x=dict(opening_units=0,demand_units=[9,11],scheduled_receipts_units=[0,0],safety_units=0,lot_multiple_units=10,lead_days=2)
    assert SOLVERS['mrp'](x)==dict(projected_units=[1,0],planned_receipts=[{'day':0,'units':10},{'day':1,'units':10}],planned_releases=[{'day':-2,'units':10},{'day':-1,'units':10}])


def test_sample_without_replacement():
    x=dict(lot_units=10,lot_defects=2,sample_units=2,accept_number=0,observed_defects=0)
    assert SOLVERS['acceptance_sampling'](x)==dict(accept=True,probability_accept=28/45)


def test_unreleased_and_expired_lots_cannot_cover_shortage():
    a=SOLVERS['fefo_issue'](task('fefo_issue',1)['inputs'])
    assert a==dict(allocations=[{'lot':'L3','units':60},{'lot':'L4','units':30}],shortage_units=20)


def test_safety_severity_is_not_hidden_by_low_rpn():
    a=SOLVERS['fmea_priority'](task('fmea_priority')['inputs'])
    assert a['rpn']['guard']==10
    assert a['action_ids']==['guard','seal']


def test_cutting_stock_accounts_for_kerf():
    x=dict(pieces_mm=[600,600],bar_mm=1200,kerf_mm=3)
    assert SOLVERS['cutting_stock'](x)==dict(feasible=True,bars=2,waste_mm=1200)


def test_exact_capacity_and_units():
    x=dict(projected_area_cm2=10,cavity_mpa=20,cavities=2,safety_factor=1,finished_dimension_mm=99,shrink_fraction=.01,yield_fraction=1,cycle_seconds=30,machine_clamp_kn=40)
    a=SOLVERS['injection_molding'](x)
    assert a==dict(tool_dimension_mm=100,clamp_kn=40,parts_hour=240,machine_suitable=True)


@pytest.mark.parametrize('bad',[True,'1',float('nan'),float('inf'),None])
def test_numeric_grader_rejects_invalid_types(bad):
    assert not equal(bad,1.0,1e-6,1e-5)


def test_bool_is_not_a_numeric_answer():
    assert not equal(1,True,1e-6,1e-5)
    assert not equal(True,1,1e-6,1e-5)


def test_missing_and_extra_fields_cannot_succeed():
    t=task('kanban')
    assert grade(t,{})['score']==0
    assert not grade(t,{'cards':11,'authorized_units':440,'extra':'ignore'})['strict_success']
    assert grade(t,{'cards':11,'authorized_units':440})['strict_success']


def test_catalog_is_unique_and_schemas_do_not_contain_answers():
    assert len({t['id'] for t in TASKS})==len(TASKS)
    assert set(t['family'] for t in TASKS)==set(SOLVERS)
    for t in TASKS:
        schema=answer_schema(t)
        assert set(schema['properties'])==set(t['output_fields'])
        assert schema['additionalProperties'] is False
        assert all('const' not in v and 'default' not in v for v in schema['properties'].values())


def test_purchase_pack_conversion_and_cash_conservation():
    w=FactorySeason(replace(CASES[0],weeks=1))
    cash=w.cash;raw=copy.deepcopy(w.raw)
    row=w.step(dict(purchase_packs={'MOTOR':2},jobs=[],maintain=[],expedite=[]))
    assert w.pipeline[0]['units']==8
    assert w.pipeline[0]['value_cents']==28800
    assert w.raw==raw
    assert w.cash==cash+w.sales-sum(w.costs.values())
    r=w.result()
    assert r['profit_cents']==r['final_cash_cents']+r['terminal_raw_cents']+r['terminal_fg_cents']+r['terminal_pipeline_cents']-r['initial_equity_cents']


def test_invalid_production_is_atomic():
    w=FactorySeason(replace(CASES[0],weeks=1));raw=copy.deepcopy(w.raw)
    row=w.step(dict(jobs=[dict(product='PUMP',units=1000)]))
    assert w.raw==raw
    assert w.costs['conversion']==0
    assert not row['jobs']
    assert row['rejected']


def test_invalid_purchase_does_not_spend():
    w=FactorySeason(replace(CASES[0],weeks=1))
    w.step(dict(purchase_packs={'MOTOR':True,'SEAL':-1,'CAST':999}))
    assert w.costs['procurement']==0
    assert not w.pipeline


def test_production_consumes_started_not_only_good_units():
    w=FactorySeason(replace(CASES[0],weeks=1));raw=copy.deepcopy(w.raw)
    row=w.step(dict(jobs=[dict(product='PUMP',units=10)]))
    assert w.raw['CAST']==raw['CAST']-10
    assert w.raw['SEAL']==raw['SEAL']-20
    assert row['jobs'][0]['good_units']+row['jobs'][0]['scrap_units']==10
    assert w.costs['conversion']==21000


def test_capacity_rejection_does_not_consume_inputs():
    w=FactorySeason(replace(CASES[0],weeks=1,capacity_scale=.01));raw=copy.deepcopy(w.raw)
    row=w.step(dict(jobs=[dict(product='VALVE',units=10)]))
    assert w.raw==raw
    assert 'finite capacity exceeded' in row['rejected']


def test_common_random_numbers_and_replay_tampering():
    case=replace(CASES[0],weeks=2)
    a=FactorySeason(case,1);b=FactorySeason(case,1)
    assert a.commitment==b.commitment
    for _ in range(2):a.step(idle_policy(a.observe()))
    assert replay(case,1,a.trace)==a.result()
    changed=copy.deepcopy(a.trace);changed[0]['cash_cents']+=1
    with pytest.raises(ValueError,match='replay mismatch'):replay(case,1,changed)


def test_current_observation_cannot_access_future_world():
    a=FactorySeason(CASES[0]).observe()
    assert not set(a)&{'exogenous','seed','yields','future_demand'}


def test_cannot_score_unfinished_world():
    with pytest.raises(ValueError,match='unfinished'):FactorySeason(CASES[0]).result()


def test_pack_scenario_changes_real_material_quantities():
    case=next(c for c in CASES if c.mode=='packs')
    w=FactorySeason(replace(case,weeks=1));w.step(dict(purchase_packs={'SEAL':1}))
    assert w.pipeline[0]['units']==144
    assert w.pipeline[0]['value_cents']==25920


def test_maintenance_and_setup_history_are_observable():
    w=FactorySeason(replace(CASES[0],weeks=2));w.step(dict(maintain=['mill']))
    o=w.observe()
    assert o['service_through_week']['mill']==3
    assert o['last_product_by_center']['mill'] is None


def test_malformed_job_product_is_rejected_atomically():
    w=FactorySeason(replace(CASES[0],weeks=1))
    row=w.step(dict(jobs=[dict(product=['PUMP'],units=1)]))
    assert 'invalid production product or units' in row['rejected']


def test_whole_numeric_counts_match_without_bool_coercion():
    assert equal(11.0,11,1e-6,1e-5)
    assert not equal(11.001,11,1e-6,1e-5)


def test_bom_aggregates_shared_material_and_scrap_starts():
    assert SOLVERS['multilevel_bom'](task('multilevel_bom')['inputs'])==dict(
        gross_requirements_units={'BLANK':22,'BODY':11,'PUMP':12,'ROTOR':11,'SEAL':31},
        planned_starts_units={'BLANK':20,'BODY':10,'PUMP':11,'ROTOR':12,'SEAL':20},
        release_day={'BLANK':1,'BODY':5,'PUMP':8,'ROTOR':6,'SEAL':4})


def test_bom_service_demand_combines_before_component_netting():
    a=SOLVERS['multilevel_bom'](task('multilevel_bom',1)['inputs'])
    assert a['gross_requirements_units']['BODY']==19
    assert a['planned_starts_units']['BODY']==20
    assert a['planned_starts_units']['BLANK']==30
    assert a['release_day']['BLANK']==-5


def test_line_balancing_enforces_indivisible_tasks():
    assert SOLVERS['assembly_line_balance'](task('assembly_line_balance')['inputs'])==dict(feasible=True,stations=3,balance_efficiency=145/180)
    assert SOLVERS['assembly_line_balance'](task('assembly_line_balance',1)['inputs'])==dict(feasible=False,stations=None,balance_efficiency=None)


def test_paired_comparison_rejects_changed_factory_budgets():
    from faraday_manufacturing_benchmark.statistics import paired_comparison
    a=[dict(case_id=k,draw=0,profit_cents=10,demand_margin_cents=100,exogenous_commitment='same',environment_commitment='budget-a') for k in ('one','two')]
    b=copy.deepcopy(a);b[0]['environment_commitment']='budget-b'
    with pytest.raises(ValueError,match='different factory'):paired_comparison(a,b)


def test_case_cluster_comparison_keeps_identical_scores_paired():
    from faraday_manufacturing_benchmark.statistics import paired_comparison
    a=[dict(case_id=k,draw=d,profit_cents=10+d,demand_margin_cents=100,exogenous_commitment=f'{k}-{d}',environment_commitment='same') for k in ('one','two') for d in range(2)]
    r=paired_comparison(a,copy.deepcopy(a),resamples=100)
    assert r['difference']==0
    assert r['interval_95']==[0,0]


def test_decision_transport_does_not_hang_on_partial_line(tmp_path):
    import sys,shlex
    from faraday_manufacturing_benchmark.agents import DecisionAgent
    script=tmp_path/'partial.py'
    script.write_text("import sys,time\nsys.stdin.readline()\nsys.stdout.write('{')\nsys.stdout.flush()\ntime.sleep(10)\n")
    with DecisionAgent(shlex.join([sys.executable,str(script)]),timeout=.2) as agent:
        with pytest.raises(ValueError,match='timed out'):agent.decide('engineering',{'id':'test'})


def test_decision_transport_keeps_process_memory(tmp_path):
    import sys,shlex
    from faraday_manufacturing_benchmark.agents import DecisionAgent
    script=tmp_path/'agent.py'
    script.write_text("import sys,json\nn=0\nfor line in sys.stdin:\n n+=1\n print(json.dumps({'turn':n}),flush=True)\n")
    with DecisionAgent(shlex.join([sys.executable,str(script)]),timeout=2) as agent:
        assert agent.decide('factory',{})=={'turn':1}
        assert agent.decide('factory',{})=={'turn':2}


def test_agent_deadline_covers_large_input_to_a_process_that_never_reads(tmp_path):
    import shlex,sys,time
    from faraday_manufacturing_benchmark.agents import DecisionAgent
    script=tmp_path/'no_input.py';script.write_text('import time\ntime.sleep(10)\n')
    start=time.monotonic()
    with DecisionAgent(shlex.join([sys.executable,str(script)]),timeout=.1) as external:
        with pytest.raises(ValueError,match='input timed out'):external.decide('cad',{'drawing':'x'*1000000})
    assert time.monotonic()-start<3
