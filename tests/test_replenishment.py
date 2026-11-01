from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT/'scripts'))
    import replenishment_benchmark as environment
    import qualify_replenishment as qualification
    spec=importlib.util.spec_from_file_location('replenishment_public_policy',ROOT/'examples/replenishment_agent.py')
    agent=importlib.util.module_from_spec(spec); spec.loader.exec_module(agent)
    return environment,qualification,agent


@pytest.mark.parametrize('family',[
    'lead_time','supplier_qualification','quality_yield','shelf_life','destination','shared_capacity',
    'minimum_order','pack_multiple','dual_source','supplier_concentration','carbon_cap','working_capital',
    'landed_cost','supplier_disruption','demand_surge','safety_stock'])
def test_each_commercial_rule_has_a_separating_cheaper_or_mispriced_award(modules,family):
    env,q,agent=modules
    config=env.build(dict(id='test',family=family,draw=3)); world=q.prepare(config); observation=world.observe()
    exact=q.exact_award(observation['public']); selected=agent.actions(observation)
    assert selected['selection']=={key:exact[key] for key in ('lots','cost_cents')}
    witness=q.rule_witness(dict(family=family),config,observation['public'],exact)
    assert witness['rejected_by_original_constraints'] or witness['more_expensive_under_true_landed_cost']
    for action in selected['actions']: assert world.act(action)['ok']
    assert world.grade()['strict_success']
    assert env.replay(config,world.trace)==world.grade()


def completed(modules,family='safety_stock'):
    env,q,agent=modules; config=env.build(dict(family=family,draw=1));world=q.prepare(config)
    output=agent.actions(world.observe())
    for action in output['actions']: assert world.act(action)['ok']
    return config,world,output


def test_future_disruption_and_demand_changes_are_not_in_startup(modules):
    env,q,_=modules
    for family in ('supplier_disruption','demand_surge'):
        config=env.build(dict(family=family,draw=1)); public=env.startup(config)
        assert 'events' not in public and 'family' not in public and 'draw' not in public
        assert env.digest(public)!=env.digest(q.prepare(config).observe()['public'])
        assert public | {'clock':0}==env.World(config).observe()['public']


@pytest.mark.parametrize('negative',['no_purchase','short_receipt','wrong_payment','skip_ship','skip_pay'])
def test_linked_physical_and_financial_failures_cannot_pass(modules,negative):
    env,q,_=modules;config,world,output=completed(modules)
    broken=q.negative_trace(config,output['actions'],negative)
    assert broken['rejected'] and not broken['verdict']['strict_success']
    assert env.replay(config,broken['trace'])==broken['verdict']


def test_trace_result_and_action_forgery_rejected(modules):
    env,_,_=modules;config,world,_=completed(modules)
    for field,value in [('result',{'ok':False}),('action',{'tool':'observe','arguments':{}}),('after','0'*64)]:
        forged=deepcopy(world.trace); forged[1][field]=value
        with pytest.raises(ValueError,match='replay'): env.replay(config,forged)


def test_cash_and_shared_capacity_are_joint_across_items(modules):
    env,q,_=modules
    for family,rule in [('working_capital','working_capital'),('shared_capacity','shared_capacity')]:
        config=env.build(dict(family=family,draw=2));public=q.prepare(config).observe()['public']
        cheap=[lot['id'] for lot in public['lots'] if lot['supplier']=='common']
        assert not env.plan_checks(public,cheap)[rule]


def test_duplicate_receipt_and_payment_cannot_create_inventory_or_cash(modules):
    env,q,agent=modules;config=env.build(dict(family='lead_time',draw=1));world=q.prepare(config)
    actions=agent.actions(world.observe())['actions']
    for action in actions:
        assert world.act(action)['ok']
        if action['tool'] in ('receive','pay'):
            before=world.state();assert not world.act(action)['ok'];assert before==world.state()
    assert world.grade()['strict_success']


def test_export_has_exactly_eight_draws_per_contract_and_unique_configs(modules):
    env,_,_=modules; tasks=env.catalog()
    assert len(tasks)==128 and len({task['id'] for task in tasks})==128
    assert len({env.digest(env.build(task)) for task in tasks})==128
    for family in env.FAMILIES: assert len([task for task in tasks if task['family']==family])==8


@pytest.mark.parametrize('value',[True,1.0,-1])
def test_boolean_float_and_negative_physical_quantities_are_rejected(modules,value):
    env,q,_=modules;world=q.prepare(env.build(dict(family='lead_time',draw=1)))
    before=world.state();assert not world.act(dict(tool='build',arguments=dict(quantity=value)))['ok']
    assert before==world.state()
