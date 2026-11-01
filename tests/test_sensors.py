from copy import deepcopy
import csv
import importlib.util
import io
import json
import math
from pathlib import Path
from unittest.mock import patch
import pytest
from faraday_manufacturing_benchmark.sensor_cases import catalog,build,SPECS
from faraday_manufacturing_benchmark.sensor_reference import solve
from faraday_manufacturing_benchmark.sensors import SensorWorld,SensorView,public_task,run,replay,valid_assessment

spec=importlib.util.spec_from_file_location('vibration_agent',Path(__file__).parents[1]/'examples/vibration_agent.py')
agent=importlib.util.module_from_spec(spec);spec.loader.exec_module(agent)


def task(family='vibration_order',condition='normal'):return next(t for t in catalog() if t['family']==family and t['condition']==condition)

def csv_body(rows):
    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows);return stream.getvalue()


def analyze(family,rows,**parameters):
    policy=deepcopy(build(task(family))['policy']);policy['parameters'].update(parameters)
    return solve(policy,csv_body(rows))


def ready(t=None):
    w=SensorWorld(t or task());w.call('read_asset');w.call('read_policy');w.call('list_streams')
    cursor=0
    while cursor is not None:cursor=w.call('read_stream',stream_id='STREAM-1',cursor=cursor,limit=64)['next_cursor']
    return w


def post(w,assessment):
    p=w.call('propose',assessment=assessment);assert p['ok'],p
    a=w.call('request_approval',proposal_id=p['proposal']['id']);assert a['ok'],a
    return w.call('execute',proposal_id=p['proposal']['id'],approval_id=a['approval']['id'])

@pytest.mark.parametrize('t',catalog(),ids=lambda t:t['id'])
def test_every_raw_condition_supports_reference_consistency_and_replay(t):
    w=ready(t);expected=solve(w.policy,w.stream['csv']);assert valid_assessment(expected,w.policy['assessment_fields'])
    rid=post(w,expected)['assessment_id'];w.call('read_result',assessment_id=rid);w.call('finish',assessment_id=rid)
    assert w.grade()['strict_success'] and replay(t,w.trace)==w.grade()
    assert w.grade()['observed_rows']==w.stream['row_count']

@pytest.mark.parametrize('condition',['normal','fault','missing','boundary'])
def test_independent_vibration_policy_uses_only_public_streams(condition):
    t=task(condition=condition);episode=run(t,agent.VibrationAgent())
    assert episode['result']['strict_success'] and replay(t,episode['trace'])==episode['result']


def test_catalog_distinguishes_analysis_families_and_authored_conditions():
    assert catalog()==catalog() and len(catalog())==48 and len(SPECS)==12
    assert len({t['id'] for t in catalog()})==48
    for t in catalog():
        data=build(t);assert data==build(t)
        assert len(list(csv.DictReader(io.StringIO(data['stream']['csv']))))==data['stream']['row_count']
        assert 'expected' not in data['stream'] and 'score' not in data['stream']


def test_analytic_vibration_and_acceleration_moments():
    rows=[dict(time_s=i/8,velocity_mm_s=2*math.cos(2*math.pi*i/8),quality='good') for i in range(8)]
    result=analyze('vibration_order',rows,sample_hz=8,shaft_rpm=60)
    assert result['rms_mm_s']==pytest.approx(math.sqrt(2));assert result['dominant_hz']==1;assert result['diagnosis']=='imbalance'
    for row in rows:row['velocity_mm_s']*=2
    changed=analyze('vibration_order',rows,sample_hz=8,shaft_rpm=60)
    assert changed['rms_mm_s']==pytest.approx(2*result['rms_mm_s']) and changed['dominant_order']==result['dominant_order']
    bearing=analyze('bearing_impulsiveness',[dict(acceleration_g=(-1)**i,quality='good') for i in range(64)])
    assert bearing==dict(valid_samples=64,rms_g=1,crest_factor=1,kurtosis=1,decision='continue')


def test_analytic_thermal_soak_and_unknown_gap_breaking():
    rows=[dict(time_min=t,temperature_c=200,quality='good') for t in (0,10,20)]
    result=analyze('thermal_soak_trace',rows,maximum_gap_minutes=10,required_soak_minutes=20)
    assert result==dict(known_minutes=20,longest_soak_minutes=20,maximum_c=200,decision='continue')
    rows[1]['temperature_c']='';result=analyze('thermal_soak_trace',rows,maximum_gap_minutes=10,required_soak_minutes=20)
    assert result['known_minutes']==0 and result['longest_soak_minutes']==0 and result['decision']=='inspect'


def test_pressure_temperature_compensation_and_exact_regression():
    rows=[dict(time_min=i,pressure_kpa=(100-.2*i)*(293.15+i)/293.15,temperature_c=20+i,quality='good') for i in range(8)]
    result=analyze('pressure_decay',rows)
    assert result['leak_kpa_min']==pytest.approx(.2)
    assert result['uncertainty_lower']==pytest.approx(.2) and result['uncertainty_upper']==pytest.approx(.2) and result['decision']=='stop'


def test_motor_rms_and_declared_imbalance_definition():
    result=analyze('motor_phase_current',[dict(current_a=1,current_b=2,current_c=1,quality='good') for _ in range(8)])
    assert result['valid_samples']==8 and result['decision']=='stop'
    assert [result['rms_a'],result['rms_b'],result['rms_c']]==[1,2,1]
    assert result['imbalance_percent']==pytest.approx(50)


def test_tool_wear_prediction_uses_future_observation_uncertainty():
    rows=[dict(time_hour=i,wear_mm=.1+.01*i,quality='good') for i in range(8)]
    result=analyze('tool_wear_prediction',rows)
    assert result['slope_mm_hour']==pytest.approx(.01) and result['predicted_wear_mm']==pytest.approx(.23)
    assert result['prediction_lower_mm']==pytest.approx(.23) and result['remaining_hours']==pytest.approx(18)
    for i,row in enumerate(rows):row['wear_mm']+=.01*(-1)**i
    noisy=analyze('tool_wear_prediction',rows)
    assert noisy['prediction_upper_mm']-noisy['prediction_lower_mm']>result['prediction_upper_mm']-result['prediction_lower_mm']


def test_spc_missing_samples_break_runs_instead_of_disappearing():
    rows=[dict(time_min=i,dimension_mm=10.04,quality='good') for i in range(8)]
    result=analyze('spc_trace',rows);assert result['longest_same_side_run']==8 and result['beyond_limit_count']==0 and result['decision']=='stop'
    rows.insert(4,dict(time_min=3.5,dimension_mm='',quality='bad'))
    result=analyze('spc_trace',rows);assert result['longest_same_side_run']==4 and result['decision']=='continue'


def test_energy_tariff_boundaries_and_meter_reset_semantics():
    rows=[dict(time_min=0,meter_kwh=100,good_units_interval=0,reset_at_previous=0,quality='good'),dict(time_min=10,meter_kwh=102,good_units_interval=10,reset_at_previous=0,quality='good'),dict(time_min=20,meter_kwh=104,good_units_interval=10,reset_at_previous=0,quality='good')]
    result=analyze('energy_meter_trace',rows)
    assert result==dict(known_kwh=4,unknown_minutes=0,cost_cents=90,kwh_per_good_unit=.2,decision='continue')
    rows[-1]['meter_kwh']=2;rows[-1]['reset_at_previous']=1
    assert analyze('energy_meter_trace',rows)==result
    rows[-1]['reset_at_previous']=0
    result=analyze('energy_meter_trace',rows);assert result['unknown_minutes']==10 and result['cost_cents'] is None and result['decision']=='inspect'


def test_cold_chain_integrates_duration_rather_than_counting_hot_points():
    result=analyze('cold_chain_trace',[dict(time_min=t,temperature_c=temp,quality='good') for t,temp in [(0,10),(5,10),(10,4)]])
    assert result==dict(known_minutes=10,above_limit_minutes=10,maximum_c=10,decision='continue')


def test_redundant_sensors_detect_common_mode_bias_against_reference():
    rows=[dict(sensor_a=52,sensor_b=50,reference=50,quality='good') for _ in range(8)]
    result=analyze('redundant_sensor_bias',rows);assert result['suspect_channel']=='A' and result['decision']=='service'
    for r in rows:r['sensor_b']=52
    result=analyze('redundant_sensor_bias',rows);assert result['maximum_pair_delta']==0 and result['suspect_channel']=='both' and result['decision']=='stop'


def test_flow_balance_accounts_for_inventory_and_measurement_error():
    rows=[dict(time_min=t,inlet_l_min=10,outlet_l_min=9,tank_liters=100,quality='good') for t in (0,5)]
    result=analyze('flow_mass_balance',rows)
    assert result==dict(known_minutes=5,unknown_minutes=0,leak_liters=5,uncertainty_lower_liters=4,uncertainty_upper_liters=6,decision='continue')
    rows[-1]['tank_liters']=105
    assert analyze('flow_mass_balance',rows)['leak_liters']==0


def test_censored_assets_are_not_counted_as_successes():
    rows=[dict(asset_id=str(i),complete=1,failed=0,followup_hours=1000) for i in range(4)]
    result=analyze('cohort_failure_risk',rows,minimum_complete_assets=1,z=2)
    assert result==dict(complete_assets=4,failures=0,risk_fraction=0,wilson_lower=0,wilson_upper=.5,decision='inspect')
    rows.extend(dict(asset_id='C'+str(i),complete=0,failed='',followup_hours=100) for i in range(100))
    assert analyze('cohort_failure_risk',rows,minimum_complete_assets=1,z=2)==result


def test_pagination_reports_total_and_union_coverage_without_false_completeness():
    w=SensorWorld(task());w.call('read_asset');w.call('read_policy')
    first=w.call('read_stream',stream_id='STREAM-1',cursor=0,limit=64)
    assert first['next_cursor']==64 and first['returned_rows']==64 and first['total_rows']==128
    w.call('read_stream',stream_id='STREAM-1',cursor=0,limit=64)
    assert len(w.coverage)==64
    assert w.call('propose',assessment=solve(w.policy,w.stream['csv']))['error']=='complete_source_evidence_required'
    for cursor,limit in ((-1,64),(False,64),(0,65),(129,64),(0,True)):
        assert not w.call('read_stream',stream_id='STREAM-1',cursor=cursor,limit=limit)['ok']


def test_incorrect_analysis_executes_unchanged_and_cannot_pass():
    w=ready(task(condition='fault'));bad=solve(w.policy,w.stream['csv']);bad['decision']='continue'
    with patch('faraday_manufacturing_benchmark.sensor_reference.solve',side_effect=AssertionError('no solver may act for the agent')):
        rid=post(w,bad)['assessment_id'];result=w.call('read_result',assessment_id=rid)
        assert result['asset']['status']=='operating' and result['result']['assessment']==bad
        w.call('finish',assessment_id=rid)
    assert not w.grade()['strict_success']


def test_operational_action_and_independent_read_back_are_required():
    w=ready(task('tool_wear_prediction','fault'));assessment=solve(w.policy,w.stream['csv']);rid=post(w,assessment)['assessment_id']
    assert w.asset['status']=='maintenance_required' and w.asset['work_orders']['WO-1']['kind']=='service'
    assert w.call('finish',assessment_id=rid)['error']=='current_read_back_required'
    w.call('read_result',assessment_id=rid);assert w.call('finish',assessment_id=rid)['ok'] and w.grade()['strict_success']


def test_approval_binding_and_reuse_are_critical():
    w=ready();assessment=solve(w.policy,w.stream['csv']);p=w.call('propose',assessment=assessment)['proposal']['id'];a=w.call('request_approval',proposal_id=p)['approval']['id']
    other=w.call('propose',assessment=dict(assessment,decision='inspect'))['proposal']['id']
    assert not w.call('execute',proposal_id=other,approval_id=a)['ok'] and w.result is None
    assert w.call('execute',proposal_id=p,approval_id=a)['ok']
    assert not w.call('execute',proposal_id=p,approval_id=a)['ok'] and w.grade()['score']==0


def test_public_sources_exclude_answers_conditions_and_private_identifiers():
    t=task();assert public_task(t)==public_task(dict(t,solution='SECRET',expected_answer=1))
    assert not set(public_task(t))&{'seed','family','condition','solution','expected_answer'}
    w=SensorWorld(t);view=SensorView();visible=view.encode(w.call('read_stream',stream_id='STREAM-1',cursor=0,limit=64))
    assert 'STREAM-1' not in json.dumps(visible) and 'expected' not in visible
    with pytest.raises(ValueError):view.decode('STREAM-1')
    with pytest.raises(ValueError):view.decode('REF-guessed')


def test_replay_detects_forged_results_actions_and_hashes():
    t=task();e=run(t,agent.VibrationAgent())
    for field in ('arguments','result','state_hash'):
        trace=deepcopy(e['trace'])
        if field=='state_hash':trace[-1][field]='0'*64
        elif field=='result':trace[-1][field]['ok']=False
        else:trace[-1][field]['assessment_id']='ASSESS-fake'
        with pytest.raises(ValueError,match='replay mismatch'):replay(t,trace)


def test_exact_three_sigma_point_is_not_beyond_limit_due_to_float_roundoff():
    rows=[dict(time_min=i,dimension_mm=10+(.01 if i%2 else -.01),quality='good') for i in range(12)]
    rows[6]['dimension_mm']=10.15
    result=analyze('spc_trace',rows)
    assert result['maximum_abs_z']==pytest.approx(3) and result['beyond_limit_count']==0 and result['decision']=='continue'


def test_policy_and_stream_export_copies_do_not_mutate_future_cases():
    t=task();source=build(t);before=deepcopy(source)
    source['policy']['parameters']['shaft_rpm']=1
    assert build(t)==before
    w=ready(t);copy=w.call('read_policy');copy['policy']['parameters']['shaft_rpm']=1
    assert w.policy['parameters']['shaft_rpm']==600


def test_typed_assessments_reject_nonfinite_bool_counts_and_extra_fields():
    w=ready();correct=solve(w.policy,w.stream['csv'])
    for value in (True,1.0,None,'128'):
        assert not valid_assessment(dict(correct,valid_samples=value),w.policy['assessment_fields'])
    for value in (float('nan'),float('inf'),True,'1.4'):
        assert not valid_assessment(dict(correct,rms_mm_s=value),w.policy['assessment_fields'])
    assert not valid_assessment(dict(correct,extra=1),w.policy['assessment_fields'])


def test_cli_export_and_external_agent_have_no_reference_answers(tmp_path):
    import hashlib,shlex,sys
    from faraday_manufacturing_benchmark.cli import main
    t=task(condition='fault');packet=tmp_path/'packet';startup=tmp_path/'startup.json';artifact=tmp_path/'run.json'
    assert main(['export-sensor-data','--task',t['id'],'--output-dir',str(packet)])==0
    index=json.loads((packet/'index.json').read_text())
    for name,sha in index['files'].items():assert hashlib.sha256((packet/name).read_bytes()).hexdigest()==sha
    assert main(['export-agent','--task',t['id'],'--output',str(startup)])==0
    value=json.loads(startup.read_text());assert value['track']=='sensors'
    assert not set(value['payload']['task'])&{'seed','family','condition','reference_answer'}
    command=shlex.quote(sys.executable)+' '+shlex.quote(str(Path(__file__).parents[1]/'examples/vibration_agent.py'))
    assert main(['sensors','--task',t['id'],'--agent-command',command,'--output',str(artifact)])==0
    result=json.loads(artifact.read_text());assert result['summary']['strict_successes']==1
    assert main(['replay',str(artifact)])==0
    result['summary']['strict_successes']=0;artifact.write_text(json.dumps(result))
    with pytest.raises(SystemExit):main(['replay',str(artifact)])


def test_frozen_sensor_catalog_matches_authored_generator():
    from importlib.resources import files
    assert json.loads(files('faraday_manufacturing_benchmark').joinpath('data/sensor_tasks.json').read_text())==catalog()


def test_synthetic_censored_followups_are_shorter_than_complete_horizon():
    data=build(task('cohort_failure_risk','missing'))
    rows=list(csv.DictReader(io.StringIO(data['stream']['csv'])))
    assert {r['followup_hours'] for r in rows if r['complete']=='1'}=={'1000'}
    assert all(int(r['followup_hours'])<1000 and r['failed']=='' for r in rows if r['complete']=='0')
