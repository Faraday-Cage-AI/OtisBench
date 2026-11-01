from copy import deepcopy
import json
from unittest.mock import patch
import pytest
from faraday_manufacturing_benchmark.shopfloor_cases import catalog,build_records
from faraday_manufacturing_benchmark.shopfloor_views import AgentView,public_task,PRIVATE_KEYS,CONTROL_FIELDS
from faraday_manufacturing_benchmark.shopfloor_runner import run


def task():
    return next(t for t in catalog() if t['disruption']=='compound_recovery')


def walk(value):
    if isinstance(value,dict):
        for k,v in value.items():yield k;yield from walk(v)
    elif isinstance(value,list):
        for v in value:yield from walk(v)


def test_public_task_is_goal_only_and_ignores_added_solution_fields():
    original=task();poisoned=deepcopy(original)
    poisoned.update(solution={'actions':['do this']},reference_answer=35,expected_controls={'rpm':1000},oracle_plan='secret')
    assert public_task(original)==public_task(poisoned)
    visible=public_task(poisoned)
    assert set(visible)=={'id','title','prompt','systems','max_tool_calls','horizon_minutes'}
    assert original['id'] not in json.dumps(visible)
    assert original['disruption'] not in json.dumps(visible)


def test_every_business_system_excludes_private_and_future_unknown_fields():
    view=AgentView('test-nonce');records=build_records(task())
    for system,rows in records.items():
        rows=deepcopy(rows);rows['expected_controls']={'rpm':1111};rows['future_answer_key']='LEAK'
        visible=view.result(dict(ok=True,system=system,records=rows,version=1))
        assert not set(walk(visible))&PRIVATE_KEYS
        assert 'expected_controls' not in set(walk(visible))
        assert 'future_answer_key' not in set(walk(visible))
        assert 'LEAK' not in json.dumps(visible)


def test_process_inputs_and_schema_are_visible_without_worked_formula():
    view=AgentView('test-nonce');plm=build_records(task())['PLM']
    visible=view.result(dict(ok=True,records=plm))['records']
    assert visible['instructions']
    for instruction in visible['instructions'].values():
        assert instruction['control_fields']
        assert 'rule' not in instruction
        assert 'control_kind' not in instruction
        assert not set(instruction)&{'expected_controls','reference_answer','solution'}
    assert 'rpm=' not in json.dumps(visible)


def test_record_names_do_not_label_correct_and_incorrect_choices():
    view=AgentView('test-nonce');records=build_records(task())
    rendered=json.dumps(view.encode(records['WMS']))+json.dumps(view.encode(records['HR']))+json.dumps(view.encode(records['MES']))
    for label in ('LOT-MAIN','LOT-ALT','LOT-LOOKALIKE','LOT-CONSIGNED','LOT-UNCERTIFIED','EMP-01-Q','M-01-ALT'):
        assert label not in rendered
    assert '-UNAPPROVED' not in rendered


def test_identifier_aliases_round_trip_keys_values_and_approval_payloads():
    view=AgentView('test-nonce')
    original=dict(machine_id='M-01-ALT',operator_id='EMP-01-Q',lot_id='LOT-MAIN',payload={'operation_id':'OP-01','controls':{'rpm':5000}})
    assert view.decode(view.encode(original))==original
    assert AgentView('other-nonce').encode(original)!=view.encode(original)


def test_guessing_private_record_ids_does_not_bypass_investigation():
    with pytest.raises(ValueError,match='unissued identifier'):AgentView().decode({'machine_id':'M-01'})


def test_operation_results_do_not_reveal_correctness_before_inspection():
    view=AgentView()
    raw=dict(ok=True,operation=dict(id='OP-01',status='running',controls={'rpm':777},parameters_ok=False,expected_controls={'rpm':1000}))
    result=view.result(raw)
    assert result['operation']['controls']=={'rpm':777}
    assert 'parameters_ok' not in result['operation']
    assert 'expected_controls' not in result['operation']


def test_measurement_results_remain_real_business_evidence():
    view=AgentView()
    measured=view.result(dict(ok=True,inspection=dict(id='INSP-1',failed_units=3,passed_units=17,revision='B')))
    assert measured['inspection']['failed_units']==3
    assert measured['inspection']['passed_units']==17


def test_error_messages_do_not_return_correct_values_or_next_step_instructions():
    view=AgentView()
    result=view.result(dict(ok=False,error='read current PLM: reference answer is 4277 rpm',clock_minute=10))
    assert result==dict(ok=False,error='source_version_mismatch',clock_minute=10)
    assert '4277' not in json.dumps(result)


def test_runner_never_sends_scores_or_automatically_calls_reference_solver():
    current=task();current['max_tool_calls']=3
    class ReadOnlyAgent:
        def __init__(self):self.payloads=[]
        def decide(self,track,payload):
            self.payloads.append(deepcopy(payload))
            return dict(tool='read',arguments={'system':['ERP','PLM','MES'][len(self.payloads)-1]})
    agent=ReadOnlyAgent()
    with patch('faraday_manufacturing_benchmark.shopfloor.required_controls',side_effect=AssertionError('solver must not answer for agent')):
        episode=run(current,agent)
    assert episode['result']['score']==0
    assert not episode['result']['strict_success']
    assert len(episode['agent_trace'])==3
    for payload in agent.payloads:
        assert not set(walk(payload))&PRIVATE_KEYS
        assert 'evaluator_task_id' not in payload
        assert current['id'] not in json.dumps(payload)


def test_payload_projection_cannot_mutate_evaluator_records():
    records=build_records(task());original=deepcopy(records)
    visible=AgentView().encode(records['WMS']);visible['lots'].clear()
    assert records==original


def test_exported_agent_contract_contains_only_neutral_startup_data(tmp_path):
    from faraday_manufacturing_benchmark.cli import main
    path=tmp_path/'agent-input.json'
    assert main(['export-agent','--task',task()['id'],'--output',str(path)])==0
    value=json.loads(path.read_text())
    assert value['track']=='workflow'
    assert set(value)=={'type','protocol','track','payload'}
    assert not set(walk(value))&PRIVATE_KEYS
    assert task()['id'] not in path.read_text()
    assert task()['disruption'] not in path.read_text()


def test_show_does_not_turn_evaluator_labels_into_an_agent_hint(capsys):
    from faraday_manufacturing_benchmark.cli import main
    assert main(['show',task()['id']])==0
    visible=json.loads(capsys.readouterr().out)
    assert visible==public_task(task())
