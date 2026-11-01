from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from manufacturing_networks import World,build,catalog,validate
from network_ledger import audit
from network_topology import canonical
spec=importlib.util.spec_from_file_location('network_public_policy',ROOT/'examples/network_agent.py');policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy)


def config(family='parallel_join',draw=1,condition='baseline'):
    return build(dict(id='unit-fixture',family=family,condition=condition,draw=draw))


def buy_all_roots(world):
    for offer in world.config['offers']:
        if offer['id'].endswith('primary') and offer['capacity']:
            assert world.act(dict(tool='buy',arguments=dict(offer_id=offer['id'],quantity=offer['capacity'])))['ok']
    assert world.act(dict(tool='wait',arguments=dict(until=2)))['ok']


def test_join_requires_both_branches_and_wip_is_not_available_inventory():
    w=World(config());buy_all_roots(w)
    assert not w.act(dict(tool='start',arguments=dict(recipe_id='assemble')))['ok']
    assert w.act(dict(tool='start',arguments=dict(recipe_id='machine_a')))['ok']
    assert w.stock['A']==0
    assert w.act(dict(tool='wait',arguments=dict(until=6)))['ok']
    before=w.state();assert not w.act(dict(tool='start',arguments=dict(recipe_id='assemble')))['ok'];assert w.state()==before
    assert w.stock['A']==1 and w.stock['B']==0


def test_coproducts_arrive_together_and_conserve_declared_mass():
    w=World(config('coproduct'));buy_all_roots(w)
    assert w.act(dict(tool='start',arguments=dict(recipe_id='separate')))['ok']
    assert w.stock['P']==w.stock['Q']==0
    assert sum(j['mass_grams'] for j in w.pending)==2000
    assert w.act(dict(tool='wait',arguments=dict(until=6)))['ok']
    assert w.stock['P']==w.stock['Q']==1
    assert w.grade()['owned_mass_grams']==w.grade()['accounted_mass_grams']==2000


def test_resource_gate_is_the_only_failed_precondition():
    w=World(config(draw=2,condition='shared_resource'));buy_all_roots(w)
    assert w.act(dict(tool='start',arguments=dict(recipe_id='machine_a')))['ok']
    assert w.stock['S']>=1 and w.used['machine_b']==0
    before=w.state();r=w.act(dict(tool='start',arguments=dict(recipe_id='machine_b')))
    assert not r['ok'] and r['error']=='resource is busy' and w.state()==before


def test_transfer_must_preserve_sku_quantity_and_requires_two_sites():
    c=config('multisite');r=next(r for r in c['recipes'] if r['kind']=='transport')
    c['items']['A-east']['sku']='different'
    with pytest.raises(ValueError,match='transport changes SKU'):validate(c)


def test_recipe_cannot_create_mass_even_if_item_quantities_look_valid():
    c=config('coproduct');c['recipes'][0]['outputs']['P']=2
    with pytest.raises(ValueError,match='mass conservation'):validate(c)


@pytest.mark.parametrize('quantity',[0,-1,True,1.0,float('nan'),'1'])
def test_invalid_quantities_do_not_mutate_inventory_or_cash(quantity):
    w=World(config());before=w.state()
    assert not w.act(dict(tool='buy',arguments=dict(offer_id=w.config['offers'][0]['id'],quantity=quantity)))['ok']
    assert w.state()==before


def test_pending_purchases_are_owned_mass_not_ready_stock():
    w=World(config('serial_chain'));o=w.config['offers'][0]
    assert w.act(dict(tool='buy',arguments=dict(offer_id=o['id'],quantity=1)))['ok']
    assert w.stock['R']==0 and w.grade()['owned_mass_grams']==1000
    assert w.grade()['accounted_mass_grams']==1000
    assert not w.act(dict(tool='start',arguments=dict(recipe_id='cut')))['ok']


def test_noop_cannot_earn_conservation_points_as_task_success():
    w=World(config());w.act(dict(tool='finish',arguments={}))
    assert w.grade()['score']==0 and not w.grade()['strict_success']


@pytest.mark.parametrize('draw',[1,2])
def test_recycling_analytical_mass_fixture_and_no_free_cycle(draw):
    w=World(config('recycling_loop',draw));response=policy.plan(w.public())
    for action in response['actions']:assert w.act(action)['ok']
    assert w.grade()['strict_success']
    assert w.shipped['P']==3*draw and w.stock['S']==draw
    assert w.used['process']==3*draw and w.used['reclaim']==draw
    assert w.grade()['owned_mass_grams']==w.grade()['accounted_mass_grams']==4000*draw
    assert audit(w.config,w.trace,w.state(),w.grade())['passed']


def test_commercially_bad_purchase_posts_before_final_budget_failure():
    c=config('serial_chain');w=World(c);actions=policy.plan(w.public())['actions']
    a=next(a for a in actions if a['tool']=='buy');a['arguments']['offer_id']=c['offers'][1]['id']
    for action in actions:assert w.act(action)['ok']
    assert not w.grade()['strict_success'] and not w.grade()['checks']['within_budget']
    assert audit(c,w.trace,w.state(),w.grade())['passed']


def test_ledger_rejects_invented_wip_and_forged_success():
    w=World(config('coproduct'));response=policy.plan(w.public())
    for action in response['actions']:w.act(action)
    trace=deepcopy(w.trace);row=next(r for r in trace if r['action']['tool']=='start');row['result']['state']['pending'][-1]['outputs']['P']+=1
    assert not audit(w.config,trace,w.state(),w.grade())['passed']
    claimed=w.grade();claimed['score']=99
    assert not audit(w.config,w.trace,w.state(),claimed)['passed']


def test_catalog_has_eight_exact_incidence_graphs_and_variants_keep_lineage():
    groups={}
    for task in catalog():groups.setdefault(task['family'],set()).add(canonical(build(task))['signature'])
    assert len(groups)==8 and all(len(v)==1 for v in groups.values())
    assert len(set(next(iter(v)) for v in groups.values()))==8


def test_topology_is_invariant_to_row_order_ids_sites_and_numeric_values():
    c=config('parallel_join');original=canonical(c)['signature'];renamed=deepcopy(c)
    names={n:'opaque-'+str(i) for i,n in enumerate(reversed(c['items']))}
    renamed['items']={names[n]:{**v,'site':'anonymous-site','mass_grams':v['mass_grams']*2} for n,v in reversed(list(c['items'].items()))}
    renamed['orders']={names[n]:q*2 for n,q in c['orders'].items()}
    for o in renamed['offers']:o['item']=names[o['item']];o['capacity']*=2
    for i,r in enumerate(renamed['recipes']):
        r['id']='opaque-recipe-'+str(i);r['inputs']={names[n]:q for n,q in r['inputs'].items()};r['outputs']={names[n]:q for n,q in r['outputs'].items()};r['duration']*=3
    renamed['recipes'].reverse()
    assert canonical(renamed)['signature']==original


def test_changing_an_actual_dependency_changes_incidence_graph():
    c=config('parallel_join');original=canonical(c)['signature']
    c['recipes'][1]['inputs']={'R':1}
    assert canonical(c)['signature']!=original
