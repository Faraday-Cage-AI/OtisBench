"""Bounded component and transport checks for persistent production campaigns."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import random
from unittest.mock import patch

import pytest

from faraday_manufacturing_benchmark.campaign import (
    CONTRACTS, ProductionCampaign, catalog, run, replay, source_fingerprints,
)
from faraday_manufacturing_benchmark.cli import main
from faraday_manufacturing_benchmark.shopfloor_views import AgentView, PRIVATE_KEYS


def micro_task(count=2):
    # Two uncomplicated orders form a small integration fixture, not a catalog run.
    for seed in range(1000):
        contracts = list(CONTRACTS)
        random.Random(seed).shuffle(contracts)
        if set(contracts[:2]) == {'split_material_lots', 'customer_allocation'}:
            task = deepcopy(catalog()[0])
            task.update(id='component-fixture', order_count=count, seed=seed)
            return task
    raise AssertionError('fixture seed unavailable')


def plant():
    return ProductionCampaign(micro_task()), AgentView('component-test')


def act(world, view, key, action, **parameters):
    result = world.call('act', dict(work_order_id=key, action=action, parameters=parameters), view)
    assert result['ok'], result
    return result


def ready(world, view, key):
    child = world.orders[key]
    # Hand-controlled unit-test inputs independently specify the expected setting.
    for instruction in child.records['PLM']['instructions'].values():
        instruction.clear()
        instruction.update(revision=child.records['ERP']['required_revision'], control_kind='energy',
                           energy_kwh_batch=100, batch_units=20, tolerance_fraction=.001)
    for system in ('PLM', 'WMS'):
        act(world, view, key, 'read', system=system)
    remaining = child.records['ERP']['required_units']
    for lot in child.records['WMS']['lots'].values():
        if lot['material'] == child.records['PLM']['material'] and lot['ownership'] == 'owned' and lot['certificate'] and lot['status'] == 'released':
            n = min(remaining, lot['units'])
            if n:
                act(world, view, key, 'read', system='WMS')
                act(world, view, key, 'reserve_material', lot_id=lot['id'], units=n)
                remaining -= n
        if not remaining:
            break
    assert not remaining
    reconcile(world, view, key)
    return dict(operation_id='OP-01', machine_id='M-01', operator_id='EMP-01-Q',
                start_minute=world.clock + 1, units=child.records['ERP']['required_units'], controls={'energy_kwh_per_unit': 5})


def reconcile(world, view, key):
    for system in ('PLM', 'MES', 'HR', 'QMS', 'WMS'):
        act(world, view, key, 'read', system=system)


def test_catalog_has_four_sustained_profiles_for_every_route():
    tasks = catalog()
    assert len(tasks) == 128
    assert len({t['family'] for t in tasks}) == 32
    assert {t['order_count'] for t in tasks} == {12, 24, 48, 96}
    assert {t['horizon_minutes'] for t in tasks} == {2880, 5760, 11520, 23040}
    assert {t['max_tool_calls'] for t in tasks} == {2880, 5760, 11520, 23040}
    assert len({t['id'] for t in tasks}) == len(tasks)


def test_long_profiles_distribute_changes_and_deadlines_across_the_episode():
    for task in catalog():
        world = ProductionCampaign(task)
        orders = list(world.orders.values())
        assert len(orders) == task['order_count']
        assert len({o.task['disruption'] for o in orders}) == 8
        assert orders[0].deadline < orders[-1].release_minute
        assert max(e['at'] for e in world.calendar) > task['horizon_minutes'] / 2
        assert all(w.release_minute < w.deadline < task['horizon_minutes'] for w in orders)
        assert world.opening_cash_cents < world.budget_cents / 2
        assert world.state_hash() == ProductionCampaign(task).state_hash()


def test_resources_and_clock_are_shared_but_customer_material_is_order_scoped():
    world, view = plant()
    a, b = world.orders.values()
    assert a.records['MES']['machines'] is b.records['MES']['machines']
    assert a.records['HR']['operators'] is b.records['HR']['operators']
    assert a.records['QMS']['instruments'] is b.records['QMS']['instruments']
    assert a.records['WMS']['lots'] is not b.records['WMS']['lots']
    world.call('wait', {'minutes': 200}, view)
    assert world.clock == a.clock == b.clock == 201


def test_future_work_order_cannot_be_used_before_release():
    world, view = plant()
    result = world.call('act', dict(work_order_id='WO-0002', action='read', parameters={'system': 'PLM'}), view)
    assert result['error'] == 'work_order_unavailable'
    assert not world.orders['WO-0002'].trace
    assert world.clock == 1


def test_next_order_cannot_double_book_the_machine_or_fixture():
    world, view = plant()
    world.orders['WO-0002'].release_minute = 0
    a = ready(world, view, 'WO-0001')
    b = ready(world, view, 'WO-0002')
    reconcile(world, view, 'WO-0001')
    a['start_minute'] = world.clock + 1
    act(world, view, 'WO-0001', 'start_operation', **a)
    reconcile(world, view, 'WO-0002')
    before = deepcopy(world.orders['WO-0002'].records['WMS'])
    b['start_minute'] = world.clock + 1
    result = world.call('act', dict(work_order_id='WO-0002', action='start_operation', parameters=b), view)
    assert result['error'] == 'resource_conflict'
    assert world.orders['WO-0002'].records['WMS'] == before
    assert not world.orders['WO-0002'].consumed


def test_different_route_stages_can_run_concurrently():
    world, view = plant()
    world.orders['WO-0002'].release_minute = 0
    a = ready(world, view, 'WO-0001')
    b = ready(world, view, 'WO-0002')
    reconcile(world, view, 'WO-0001')
    a['start_minute'] = world.clock + 1
    act(world, view, 'WO-0001', 'start_operation', **a)
    first = world.orders['WO-0001'].records['MES']['operations'][0]
    world.advance(first['finish'] - world.clock)
    act(world, view, 'WO-0001', 'complete_operation', operation_id='OP-01', certificate_id=None)
    reconcile(world, view, 'WO-0001')
    second = dict(a, operation_id='OP-02', machine_id='M-02', operator_id='EMP-02-Q', start_minute=world.clock + 1)
    act(world, view, 'WO-0001', 'start_operation', **second)
    reconcile(world, view, 'WO-0002')
    b['start_minute'] = world.clock + 1
    act(world, view, 'WO-0002', 'start_operation', **b)
    assert world.orders['WO-0001'].records['MES']['operations'][1]['status'] == 'running'
    assert world.orders['WO-0002'].records['MES']['operations'][0]['status'] == 'running'


def test_trip_from_another_order_interrupts_shared_wip_and_repair_requires_recovery():
    world, view = plant()
    args = ready(world, view, 'WO-0001')
    act(world, view, 'WO-0001', 'start_operation', **args)
    world.calendar.append(dict(kind='machine_trip', at=world.clock + 2, work_order='WO-0002', machine='M-01'))
    world.advance(2)
    op = world.orders['WO-0001'].records['MES']['operations'][0]
    assert op['status'] == 'interrupted'
    result = world.call('repair_machine', {'machine_id': 'M-01'}, view)
    assert result['error'] == 'resource_conflict'
    consumed = deepcopy(world.orders['WO-0001'].consumed)
    world.machines['M-01']['busy'].append(dict(start=400, finish=450, source='WO-0002:OP-01'))
    reconcile(world, view, 'WO-0001')
    act(world, view, 'WO-0001', 'reroute_interrupted_operation', operation_id='OP-01')
    assert world.orders['WO-0001'].consumed == consumed
    assert world.machines['M-01']['busy'] == [dict(start=400, finish=450, source='WO-0002:OP-01')]
    before = world.cash_cents
    result = world.call('repair_machine', {'machine_id': 'M-01'}, view)
    assert result['ok']
    assert before - world.cash_cents == world.repair_cost_cents
    assert world.machines['M-01']['status'] == 'available'
    assert world.grade()['ledger_ok']


def test_shared_tool_wear_is_not_reset_for_next_customer_order():
    world, view = plant()
    args = ready(world, view, 'WO-0001')
    initial = world.machines['M-01']['tool_remaining_units']
    act(world, view, 'WO-0001', 'start_operation', **args)
    assert world.orders['WO-0002'].records['MES']['machines']['M-01']['tool_remaining_units'] == initial - args['units']


def test_tool_replacement_restores_rated_capacity_and_invalidates_other_reads():
    world, view = plant()
    world.orders['WO-0002'].release_minute = 0
    act(world, view, 'WO-0002', 'read', system='MES')
    for system in ('CMMS', 'MES'):
        act(world, view, 'WO-0001', 'read', system=system)
    before = world.cash_cents
    act(world, view, 'WO-0001', 'replace_tool', machine_id='M-01')
    assert world.machines['M-01']['tool_remaining_units'] == 120
    assert not world.orders['WO-0002']._current('MES')
    assert before > world.cash_cents


def test_cash_shortage_rejects_purchase_without_consuming_approval_or_stock():
    world, view = plant()
    reservation = world.call('reserve_supply', dict(work_order_id='WO-0001', units=4, window_start=0, expedited=False), view)
    assert reservation['ok']
    world.cash_cents = 0
    world.opening_cash_cents = world.prepaid_cents
    child = world.orders['WO-0001']
    for system in ('ERP', 'PLM', 'SCM'):
        act(world, view, child.key, 'read', system=system)
    payload = dict(units=4, expedited=False, allocation_id='RES-SUP-0001')
    act(world, view, child.key, 'request_approval', kind='purchase', payload=payload)
    before = deepcopy(child.records['SCM']['purchase_orders'])
    result = world.call('act', dict(work_order_id=child.key, action='purchase', parameters=dict(payload, approval_id='APR-1')), view)
    assert result['error'] == 'cash_insufficient'
    assert child.records['SCM']['purchase_orders'] == before
    assert not child.approval_uses
    assert world.spent_cents == 0
    assert world.grade()['ledger_ok']


def test_delayed_cash_receipt_is_applied_once_at_its_due_time():
    world, _ = plant()
    initial = world.cash_cents
    world.receivables.append(dict(work_order='WO-0001', shipment='SHIP-1', amount_cents=12345, due_minute=100, status='pending'))
    world.advance(99)
    assert world.cash_cents == initial
    world.advance(1)
    assert world.cash_cents == initial + 12345
    world.advance(100)
    assert world.cash_cents == initial + 12345


def test_renewal_cost_time_and_qualification_persist_across_orders():
    world, view = plant()
    before = world.cash_cents
    result = world.call('renew_qualification', {'operator_id': 'EMP-01'}, view)
    assert result['ok']
    assert world.clock == world.renewal_minutes + 1
    assert before - world.cash_cents == world.renewal_cost_cents
    assert world.orders['WO-0002'].records['HR']['operators']['EMP-01']['certified_until_minute'] == world.clock + world.qualification_minutes
    assert world.grade()['ledger_ok']


class ReadOnly:
    def __init__(self):
        self.messages = []
    def decide(self, track, payload):
        assert track == 'campaign'
        self.messages.append(deepcopy(payload))
        return dict(tool='read_campaign', arguments={})


def partial():
    agent = ReadOnly()
    with patch('faraday_manufacturing_benchmark.shopfloor.required_controls', side_effect=AssertionError('no automatic answers')):
        artifact = run(micro_task(), agent, stop_after=3)
    return agent, artifact


def test_partial_run_exposes_only_business_data_and_replays_exactly():
    agent, artifact = partial()
    assert len(artifact['trace']) == 3
    assert not artifact['result']['strict_success']
    assert artifact['error_type'] is None
    assert replay(micro_task(), artifact) == artifact['result']
    def keys(value):
        if isinstance(value, dict):
            for key, item in value.items():
                yield key
                yield from keys(item)
        elif isinstance(value, list):
            for item in value:
                yield from keys(item)
    assert not set(keys(agent.messages)) & PRIVATE_KEYS
    assert 'component-fixture' not in json.dumps(agent.messages)
    assert 'alias_nonce' not in json.dumps(agent.messages)
    assert 'calendar' not in json.dumps(agent.messages)
    assert artifact['result']['score'] == 0


@pytest.mark.parametrize('target', ['state', 'public', 'decision', 'source', 'terminal'])
def test_replay_rejects_transition_transport_source_and_grade_tampering(target):
    _, artifact = partial()
    if target == 'state': artifact['trace'][0]['state_hash'] = 'bad'
    if target == 'public': artifact['agent_trace'][0]['result']['cash_cents'] += 1
    if target == 'decision': artifact['agent_trace'][0]['decision']['tool'] = 'wait'
    if target == 'source': artifact['source_hashes']['campaign.py'] = 'bad'
    if target == 'terminal': artifact['result']['score'] = 100
    with pytest.raises(ValueError):
        replay(micro_task(), artifact)


def test_checkpoints_capture_stopped_episode_without_inserting_decisions():
    snapshots = []
    result = run(micro_task(), ReadOnly(), checkpoint=snapshots.append, stop_after=2)
    assert [len(s['trace']) for s in snapshots] == [1, 2]
    assert snapshots[-1] == result
    assert result['error_type'] is None
    assert source_fingerprints() == result['source_hashes']


def test_finish_requires_completed_orders_and_clock_or_call_limits_cannot_be_bypassed():
    world, view = plant()
    result = world.call('finish_campaign', {}, view)
    assert result['error'] == 'orders_incomplete'
    assert not world.grade()['strict_success']
    world.task['max_tool_calls'] = 1
    with pytest.raises(ValueError): world.call('read_campaign', {}, view)
    world.task['max_tool_calls'] = 100
    world.clock = world.task['horizon_minutes']
    with pytest.raises(ValueError): world.call('wait', {'minutes': 1}, view)


def test_export_and_show_keep_case_labels_and_event_outcomes_private(tmp_path, capsys):
    task = catalog()[0]
    path = tmp_path / 'input.json'
    main(['export-agent', '--task', task['id'], '--output', str(path)])
    data = json.loads(path.read_text())
    assert data['track'] == 'campaign'
    assert data['payload']['task']['order_count'] == 12
    assert not set(data['payload']['task']) & {'seed', 'family', 'profile'}
    assert task['id'] not in path.read_text()
    main(['show', task['id']])
    assert task['id'] not in capsys.readouterr().out


class TwoOrderControl:
    """Test-only control that reads business data and computes its own settings."""
    def __init__(self, wrong_controls=False):
        spec = importlib.util.spec_from_file_location('campaign_component_policy', Path(__file__).with_name('workflow_qualification_policy.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.policy_type = module.FeasibilityPolicy
        self.orders = None
        self.index = 0
        self.policy = None
        self.wrong_controls = wrong_controls

    def decide(self, track, payload):
        last = payload['last_result']
        if self.orders is None:
            if last is None:
                return dict(tool='read_campaign', arguments={})
            self.orders = last['work_orders']
        if self.policy is not None and last and last.get('finished'):
            self.index += 1
            self.policy = None
        if self.index == len(self.orders):
            return dict(tool='finish_campaign', arguments={})
        order = self.orders[self.index]
        if payload['clock_minute'] < order['release_minute']:
            return dict(tool='wait', arguments=dict(minutes=min(300, order['release_minute'] - payload['clock_minute'])))
        if self.policy is None:
            self.policy = self.policy_type()
        decision = self.policy.decide('workflow', payload)
        if self.wrong_controls and decision['tool'] == 'start_operation':
            decision['arguments']['controls'] = {k: v * 2 for k, v in decision['arguments']['controls'].items()}
        return dict(tool='act', arguments=dict(work_order_id=order['id'], action=decision['tool'], parameters=decision['arguments']))


def test_two_order_component_control_completes_without_resets_and_wrong_settings_fail():
    task = micro_task()
    positive = run(task, TwoOrderControl())
    assert positive['error_type'] is None, positive['error_type']
    assert positive['result']['strict_success'], positive['result']
    assert positive['result']['orders_completed'] == 2
    assert positive['result']['tool_calls'] > 100
    assert len({s for order in positive['result']['orders'] for s in [order['task_id']]}) == 2
    serials = [serial for row in positive['trace'] if row['tool'] == 'act' and row['arguments']['action'] == 'ship'
               for serial in row['arguments']['parameters']['serials']]
    assert len(serials) == len(set(serials))
    assert replay(task, positive) == positive['result']
    negative = run(task, TwoOrderControl(wrong_controls=True))
    assert not negative['result']['strict_success']
    assert negative['result']['orders_completed'] == 0


def test_resume_reconstructs_state_and_exposes_only_public_history():
    _, first = partial()
    agent = ReadOnly()
    resumed = run(micro_task(), agent, stop_after=2, resume=first)
    assert len(resumed['trace']) == 5
    assert len(agent.messages) == 2
    assert agent.messages[0]['clock_minute'] == first['result']['elapsed_minutes']
    assert agent.messages[0]['history'] == first['agent_trace']
    serialized = json.dumps(agent.messages)
    assert all(key not in serialized for key in ('state_hash', 'source_hashes', 'alias_nonce', 'strict_success', 'calendar'))
    assert replay(micro_task(), resumed) == resumed['result']


def test_resume_rejects_corrupted_checkpoint_before_calling_agent():
    _, first = partial()
    first['result']['cash_cents'] += 1
    agent = ReadOnly()
    with pytest.raises(ValueError):
        run(micro_task(), agent, stop_after=1, resume=first)
    assert not agent.messages


def test_financial_checker_rejects_fabricated_or_duplicate_receivables():
    world, _ = plant()
    assert world.grade()['ledger_ok']
    world.receivables.append(dict(work_order='WO-0001', shipment='SHIP-1', amount_cents=100,
                                  due_minute=200, status='pending'))
    assert not world.grade()['ledger_ok']
    assert world.grade()['score'] == 0


def test_cli_checkpoint_resume_and_replay_use_the_supplied_process(tmp_path):
    import subprocess
    import sys
    source = tmp_path / 'reader.py'
    source.write_text('import json,sys\nfor line in sys.stdin:\n json.loads(line)\n print(json.dumps({"tool":"read_campaign","arguments":{}}),flush=True)\n')
    path = tmp_path / 'checkpoint.json'
    args = [sys.executable, '-m', 'otisbench', 'campaign', '--task', catalog()[0]['id'],
            '--agent-command', f'{sys.executable} {source}', '--stop-after', '2', '--output', str(path)]
    for extra, count in (([], 2), (['--resume', str(path)], 4)):
        result = subprocess.run(args + extra, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        artifact = json.loads(path.read_text())
        assert len(artifact['trace']) == count
        assert artifact['error_type'] is None
        result = subprocess.run([sys.executable, '-m', 'otisbench', 'replay', str(path)], capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr


def test_frozen_campaign_catalog_matches_authored_tasks():
    root = Path(__file__).resolve().parents[1]
    frozen = root / 'src/faraday_manufacturing_benchmark/data/campaign_tasks.json'
    assert json.loads(frozen.read_text()) == catalog()
    manifest = json.loads((root / 'manifest.json').read_text())
    assert manifest['campaign_cases'] == 128
    assert manifest['campaign_route_families'] == 32


@pytest.mark.skipif(not Path('/usr/bin/sandbox-exec').exists(), reason='requires macOS offline boundary')
def test_cli_stages_offline_agent_and_records_boundary_for_partial_campaign(tmp_path):
    import subprocess
    import sys
    source = tmp_path / 'offline.py'
    source.write_text('import json,sys\nfor line in sys.stdin:\n json.loads(line)\n print(json.dumps({"tool":"read_campaign","arguments":{}}),flush=True)\n')
    path = tmp_path / 'isolated.json'
    result = subprocess.run([sys.executable, '-m', 'otisbench', 'campaign', '--task', catalog()[0]['id'],
        '--agent-file', str(source), '--stop-after', '2', '--output', str(path)],
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    artifact = json.loads(path.read_text())
    assert len(artifact['trace']) == 2
    assert artifact['error_type'] is None
    assert artifact['isolation']['network'] == 'denied'
    assert replay(catalog()[0], artifact) == artifact['result']
