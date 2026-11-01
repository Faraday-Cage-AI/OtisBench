from copy import deepcopy
from dataclasses import replace
import pytest
from faraday_manufacturing_benchmark.season import CASES,FactorySeason,PRODUCTS,POLICY,idle_policy,rule_policy
from faraday_manufacturing_benchmark.season_audit import audit_trace
from faraday_manufacturing_benchmark.season_policies import maintenance_policy


def audit(world,trace=None,result=None):
    return audit_trace(world.case,world.draw,world.trace if trace is None else trace,world.result() if result is None else result,products=PRODUCTS,materials=world.materials,policy=POLICY,exogenous=world.exogenous)


def run(case,policy=rule_policy):
    w=FactorySeason(case)
    for _ in range(case.weeks):w.step(policy(w.observe()))
    return w


@pytest.mark.parametrize('case',CASES,ids=lambda c:c.id)
@pytest.mark.parametrize('policy',[idle_policy,rule_policy,maintenance_policy])
def test_separate_ledger_reconciles_full_season(case,policy):
    w=run(case,policy)
    assert audit(w)['passed']


@pytest.mark.parametrize('field',['cash','receipt','yield','shipment','capacity','action'])
def test_ledger_detects_corruption_without_using_state_hashes(field):
    w=run(CASES[0]);t=deepcopy(w.trace)
    if field=='cash':t[0]['cash_cents']+=1
    elif field=='capacity':t[0]['remaining_capacity_minutes']['test']+=1
    elif field=='action':next(r for r in t if r['jobs'])['action']['jobs']=[]
    else:
        key,sub={'receipt':('receipts','units'),'yield':('jobs','good_units'),'shipment':('shipments','revenue_cents')}[field]
        next(r for r in t if r[key])[key][0][sub]+=1
    assert not audit(w,trace=t)['passed']


def test_ledger_is_separate_from_simulator_methods(monkeypatch):
    w=run(CASES[0]);result=deepcopy(w.result())
    def forbidden(*a,**kw):raise AssertionError('simulator called by independent ledger')
    for name in ('step','result','capacities','raw_value','fg_value','price','state_hash'):monkeypatch.setattr(FactorySeason,name,forbidden)
    assert audit(w,result=result)['passed']


@pytest.mark.parametrize('trace',[[],[{}],[None]])
def test_incomplete_and_malformed_traces_fail_closed(trace):
    w=run(CASES[0]);assert not audit(w,trace=trace)['passed']


def test_rejected_actions_do_not_disrupt_accounting():
    w=FactorySeason(replace(CASES[0],weeks=3))
    for a in [dict(purchase_packs=[],jobs=['bad']),dict(jobs=[dict(product='PUMP',units=-1)]),dict(maintain=['missing'],purchase_packs={'CAST':1000})]:w.step(a)
    assert w.result()['rejected_actions']>0
    assert audit(w)['passed']


def test_preventive_maintenance_uses_notice_and_reserves_resources():
    w=run(next(c for c in CASES if c.mode=='maintenance'),maintenance_policy)
    assert w.trace[9]['maintenance']==['mill']
    assert all(not row['rejected'] for row in w.trace)
    assert audit(w)['passed']
    o=FactorySeason(CASES[0]).observe();o['week']=9
    assert maintenance_policy(o)['maintain']==[]
