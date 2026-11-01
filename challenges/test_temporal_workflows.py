import importlib.util
from pathlib import Path
from copy import deepcopy
import pytest

SOURCE=Path(__file__).resolve().parents[1]/'challenges/temporal_workflows.py'
spec=importlib.util.spec_from_file_location('temporal_workflows',SOURCE)
temporal=importlib.util.module_from_spec(spec);spec.loader.exec_module(temporal)


def first():return temporal.catalog()[0]


def test_temporal_tier_is_64_variants_not_64_new_structures():
    cases=temporal.catalog()
    assert len(cases)==64
    assert len({c['id'] for c in cases})==64
    assert len({c['family'] for c in cases})==32


def test_fixed_wait_twenty_no_longer_resolves_all_disruptions():
    w=temporal.TemporalWorkflow(first());w.call('wait',minutes=20)
    assert w.records['PLM']['revision']=='A'
    assert w.records['WMS']['lots']['LOT-MAIN']['status']=='released'
    assert not w.fired
    assert not w._current('PLM')


def test_temporal_events_are_staggered_and_not_fixed_by_label():
    calendars=[]
    for case in temporal.catalog():
        w=temporal.TemporalWorkflow(case)
        calendars.append(tuple((e['kind'],e['at']) for e in w.calendar))
        assert len({e['at'] for e in w.calendar})>=2
        assert all(e['at']!=18 for e in w.calendar)
    assert len(set(calendars))==64


def test_observation_includes_business_review_dates_not_evaluator_calendar():
    from faraday_manufacturing_benchmark.shopfloor_views import AgentView
    w=temporal.TemporalWorkflow(first());view=AgentView()
    plm=view.result(w.call('read',system='PLM'))
    assert plm['records']['change_requests'][0]['review_due_minute']>20
    assert 'calendar' not in str(plm)
    assert 'quality_disposition' not in str(plm)
    assert 'reference_answer' not in str(plm)


def test_clock_jump_applies_each_event_once_in_order():
    w=temporal.TemporalWorkflow(first());w.call('wait',minutes=200)
    assert len(w.fired)==3
    assert w.records['PLM']['revision']=='B'
    assert w.records['WMS']['lots']['LOT-MAIN']['status']=='hold'
    assert w.records['MES']['machines']['M-01']['status']=='down'
    source=deepcopy(w.records['PLM']['instructions']);versions=deepcopy(w.versions)
    w.call('wait',minutes=10)
    assert w.records['PLM']['instructions']==source
    assert w.versions==versions


def test_blanket_wait_300_cannot_fit_remaining_required_route():
    # A static timing lower bound, without executing or solving any full episode.
    for case in temporal.catalog():
        w=temporal.TemporalWorkflow(case)
        assert 300+w.routing_minutes>w.deadline
        assert all(o['due_minute']==w.deadline for o in w.records['ERP']['orders'])


def test_temporal_calendar_changes_invalidate_source_reads():
    w=temporal.TemporalWorkflow(first());w.call('read',system='PLM')
    assert w._current('PLM')
    release=next(e['at'] for e in w.calendar if e['kind']=='engineering_release')
    w.call('wait',minutes=release)
    assert not w._current('PLM')


def test_partial_temporal_replay_and_mutation_rejection():
    task=first();w=temporal.TemporalWorkflow(task)
    w.call('read',system='ERP');w.call('wait',minutes=150);w.call('read',system='MES')
    assert temporal.replay(task,w.trace)==w.grade()
    changed=deepcopy(w.trace);changed[1]['result']['clock_minute']+=1
    with pytest.raises(ValueError,match='replay mismatch'):temporal.replay(task,changed)


def test_child_agent_never_receives_solver_or_calendar():
    from unittest.mock import patch
    task=first();task['max_tool_calls']=2
    class Reader:
        def decide(self,track,payload):
            assert not {'calendar','source_task_id','seed','result','score'}&payload.keys()
            return dict(tool='read',arguments={'system':'ERP'})
    with patch('faraday_manufacturing_benchmark.shopfloor.required_controls',side_effect=AssertionError('no automatic answer')):
        result=temporal.run(task,Reader())
    assert result['result']['score']==0
    assert len(result['trace'])==2


def public_policy_source(adaptive):
    # This is only a test control. It is never injected into a tested agent.
    root=Path(__file__).resolve().parents[1]
    source=(root/'tests/workflow_qualification_policy.py').read_text()
    if not adaptive:return source
    source=source.replace("        yield from action('wait',minutes=20)","        yield from read('PLM')\n        release=max([clock]+[r['review_due_minute'] for r in records['PLM']['change_requests'] if r['status']=='pending'])\n        yield from wait_until(release)")
    source=source.replace("        eligible=[", "        blocked={r['lot_id'] for r in records['QMS'].get('supplier_investigations',[]) if r['status']=='pending' or r.get('disposition')=='hold'}\n        eligible=[")
    source=source.replace("if l['status']=='released'", "if l['id'] not in blocked and l['status']=='released'")
    source=source.replace("if lot['status']!='released'", "if lot['id'] in blocked or lot['status']!='released'")
    source=source.replace('expedited=False','expedited=True')
    return source


def test_one_public_observation_policy_can_finish_the_tighter_workflow():
    namespace={'__name__':'temporal_test_control'}
    exec(compile(public_policy_source(True),'public_test_control','exec'),namespace)
    task=first();episode=temporal.run(task,namespace['FeasibilityPolicy']())
    assert episode['result']['strict_success'],episode['result']
    assert episode['result']['score']==100
    assert temporal.replay(task,episode['trace'])==episode['result']


def test_existing_fixed_wait_control_does_not_pass_by_reusing_its_recipe():
    namespace={'__name__':'temporal_test_control'}
    exec(compile(public_policy_source(False),'public_test_control','exec'),namespace)
    episode=temporal.run(first(),namespace['FeasibilityPolicy']())
    assert not episode['result']['strict_success']
    assert episode['result']['score']==0
