"""Cash, capacity and maintenance consequences in sustained campaigns."""
from copy import deepcopy
import json
from pathlib import Path
import pytest

from test_campaign import plant, act, micro_task, ReadOnly
from faraday_manufacturing_benchmark.campaign import run, replay, catalog
from faraday_manufacturing_benchmark.campaign_storage import CampaignJournal, load_checkpoint


def book(world, view, owner='WO-0001', units=4, window=0, expedited=False):
    result = world.call('reserve_supply', dict(work_order_id=owner, units=units, window_start=window, expedited=expedited), view)
    assert result['ok'], result
    return next(reversed(world.allocations))


def approve_purchase(world, view, owner, allocation, units, expedited=False):
    for system in ('ERP', 'PLM'):
        act(world, view, owner, 'read', system=system)
    payload = dict(units=units, expedited=expedited, allocation_id=allocation)
    result = act(world, view, owner, 'request_approval', kind='purchase', payload=payload)
    assert result['approval']['payload']['allocation_id'] == view.encode({'id': allocation})['id']
    return next(reversed(world.orders[owner].approvals))


def test_largest_campaign_has_four_times_the_previous_order_and_action_budget():
    largest = next(t for t in catalog() if t['profile'] == 'forty_eight_shift')
    assert largest['order_count'] == 96
    assert largest['max_tool_calls'] == largest['horizon_minutes'] == 23040
    assert largest['release_cadence_minutes'] == 216


def test_shared_dispatch_capacity_rejects_overbooking_without_taking_a_deposit():
    world, view = plant()
    book(world, view, units=24)
    book(world, view, owner='WO-0002', units=24)
    before = (world.cash_cents, world.prepaid_cents, deepcopy(world.allocations))
    result = world.call('reserve_supply', dict(work_order_id='WO-0001', units=4, window_start=0, expedited=False), view)
    assert result['error'] == 'supplier_capacity_exceeded'
    assert (world.cash_cents, world.prepaid_cents, world.allocations) == before
    assert world.grade()['ledger_ok']


def test_expedited_capacity_is_shared_and_tighter_than_total_capacity():
    world, view = plant()
    book(world, view, units=16, expedited=True)
    result = world.call('reserve_supply', dict(work_order_id='WO-0002', units=16, window_start=0, expedited=True), view)
    assert result['error'] == 'supplier_capacity_exceeded'
    book(world, view, owner='WO-0002', units=16, expedited=False)
    assert world._window_usage(0) == (32, 16)


def test_purchase_consumes_its_deposit_once_and_obeys_booked_dispatch_time():
    world, view = plant()
    initial = world.cash_cents
    allocation = book(world, view, units=4, window=480)
    assert world.prepaid_cents == 1440
    assert initial - world.cash_cents == 1440
    approval = approve_purchase(world, view, 'WO-0001', allocation, 4)
    result = act(world, view, 'WO-0001', 'purchase', units=4, expedited=False,
                 approval_id=approval, allocation_id=allocation)
    assert result['purchase_order']['due_minute'] == 680
    assert world.prepaid_cents == 0
    assert initial - world.cash_cents == world.spent_cents == 7200
    assert world.allocations[allocation]['status'] == 'used'
    assert world.grade()['ledger_ok']
    world.advance(680 - world.clock)
    assert world.orders['WO-0001'].records['SCM']['purchase_orders']['PO-1']['status'] == 'received'
    assert world._window_usage(480) == (4, 0)
    result = world.call('cancel_supply', dict(allocation_id=allocation), view)
    assert not result['ok']


@pytest.mark.parametrize('wrong_owner,wrong_quantity', [(True, False), (False, True)])
def test_allocation_cannot_be_rebound_to_another_order_or_quantity(wrong_owner, wrong_quantity):
    world, view = plant()
    world.orders['WO-0002'].release_minute = 0
    allocation = book(world, view, units=8)
    owner = 'WO-0002' if wrong_owner else 'WO-0001'
    units = 4 if wrong_quantity else 8
    approval = approve_purchase(world, view, owner, allocation, units)
    before = (world.cash_cents, world.prepaid_cents, world.spent_cents)
    result = world.call('act', dict(work_order_id=owner, action='purchase', parameters=dict(
        units=units, expedited=False, approval_id=approval, allocation_id=allocation)), view)
    assert result['error'] == 'supply_allocation_mismatch'
    assert (world.cash_cents, world.prepaid_cents, world.spent_cents) == before
    assert not world.orders[owner].approval_uses


def test_purchase_approval_is_bound_to_the_exact_supply_commitment():
    world, view = plant()
    a = book(world, view)
    b = book(world, view)
    approval = approve_purchase(world, view, 'WO-0001', a, 4)
    result = world.call('act', dict(work_order_id='WO-0001', action='purchase', parameters=dict(
        units=4, expedited=False, approval_id=approval, allocation_id=b)), view)
    assert not result['ok']
    assert world.grade()['critical_violation']
    assert world.grade()['score'] == 0
    assert world.spent_cents == 0


def test_cancellation_frees_capacity_and_refunds_only_the_unforfeited_deposit():
    world, view = plant()
    initial = world.cash_cents
    allocation = book(world, view, units=48)
    result = world.call('cancel_supply', dict(allocation_id=allocation), view)
    assert result['ok']
    assert world.prepaid_cents == 0
    assert initial - world.cash_cents == world.spent_cents == 500
    assert world._window_usage(0) == (0, 0)
    book(world, view, owner='WO-0002', units=48)
    assert world.grade()['ledger_ok']
    assert not world.call('cancel_supply', dict(allocation_id=allocation), view)['ok']


def test_unused_dispatch_deposit_becomes_cost_at_expiry_without_double_debit():
    world, view = plant()
    allocation = book(world, view, units=4)
    cash = world.cash_cents
    world.advance(480 - world.clock)
    assert world.cash_cents == cash
    assert world.prepaid_cents == 0
    assert world.spent_cents == world.orders['WO-0001'].spent_cents == 1440
    assert world.allocations[allocation]['status'] == 'expired'
    world.advance(20)
    assert world.spent_cents == 1440
    assert world.grade()['ledger_ok']


def test_campaign_cannot_finish_with_unresolved_supply_commitments():
    world, view = plant()
    book(world, view)
    result = world.call('finish_campaign', {}, view)
    assert result['error'] == 'supply_commitments_open'
    assert not world.finished


def test_spares_need_pack_compliance_cash_and_actual_receipt():
    world, view = plant()
    cash = world.cash_cents
    result = world.call('order_spares', dict(kind='tooling_kit', quantity=3, expedited=False), view)
    assert result['error'] == 'spare_pack_invalid'
    assert world.cash_cents == cash
    result = world.call('order_spares', dict(kind='tooling_kit', quantity=4, expedited=False), view)
    assert result['ok']
    assert world.spares['tooling_kit'] == 2
    assert cash - world.cash_cents == 4800
    due = result['spare_order']['due_minute']
    world.advance(due - world.clock - 1)
    assert world.spares['tooling_kit'] == 2
    world.advance(1)
    assert world.spares['tooling_kit'] == 6
    world.advance(1)
    assert world.spares['tooling_kit'] == 6
    assert world.grade()['ledger_ok']
    world.spares['tooling_kit'] += 1
    assert not world.grade()['ledger_ok']


def test_repair_waits_for_a_real_kit_and_consumes_it_once():
    world, view = plant()
    world.machines['M-01']['status'] = 'down'
    world.spares['repair_kit'] = 0
    world.spares_used['repair_kit'] = 1
    before = world.cash_cents
    result = world.call('repair_machine', {'machine_id': 'M-01'}, view)
    assert result['error'] == 'spare_unavailable'
    assert world.cash_cents == before
    result = world.call('order_spares', dict(kind='repair_kit', quantity=2, expedited=True), view)
    assert result['ok']
    world.advance(result['spare_order']['due_minute'] - world.clock)
    assert world.spares['repair_kit'] == 2
    assert world.call('repair_machine', {'machine_id': 'M-01'}, view)['ok']
    assert world.spares['repair_kit'] == 1
    assert world.spares_used['repair_kit'] == 2
    assert world.grade()['ledger_ok']


def test_tool_change_cannot_create_an_insert_from_empty_inventory():
    world, view = plant()
    world.spares['tooling_kit'] = 0
    world.spares_used['tooling_kit'] = 2
    before = world.cash_cents
    result = world.call('act', dict(work_order_id='WO-0001', action='replace_tool', parameters={'machine_id': 'M-01'}), view)
    assert result['error'] == 'spare_unavailable'
    assert world.cash_cents == before
    assert world.spares['tooling_kit'] == 0
    assert world.grade()['ledger_ok']


def journal_fixture(tmp_path, task=None):
    output = tmp_path / 'campaign.json'
    writer = CampaignJournal(output)
    try:
        artifact = run(task or micro_task(), ReadOnly(), stop_after=2, journal=writer)
    finally:
        writer.close()
    assert not output.exists()
    return output, writer.path, artifact


def test_journal_recovers_without_a_full_checkpoint_and_does_not_repeat_history(tmp_path):
    output, journal, artifact = journal_fixture(tmp_path)
    entries = [json.loads(line) for line in journal.read_text().splitlines()]
    assert entries[0]['artifact']['trace'] == []
    assert len(entries) == 3
    assert all(set(row) == {'type', 'record', 'public'} for row in entries[1:])
    recovered = load_checkpoint(output, micro_task())
    assert recovered == artifact
    continued = run(micro_task(), ReadOnly(), stop_after=1, resume=recovered)
    assert len(continued['trace']) == 3
    assert replay(micro_task(), continued) == continued['result']


def test_journal_recovers_complete_actions_after_a_partial_tail_write(tmp_path):
    output, journal, artifact = journal_fixture(tmp_path)
    with journal.open('ab') as handle:
        handle.write(b'{"type":"step","record":')
    assert load_checkpoint(output, micro_task()) == artifact


def test_journal_rejects_a_complete_but_tampered_record(tmp_path):
    output, journal, _ = journal_fixture(tmp_path)
    entries = [json.loads(line) for line in journal.read_text().splitlines()]
    entries[-1]['record']['state_hash'] = 'bad'
    journal.write_text(''.join(json.dumps(e) + '\n' for e in entries))
    with pytest.raises(ValueError):
        load_checkpoint(output, micro_task())


def test_fresh_run_cannot_overwrite_a_recovery_journal(tmp_path):
    output, journal, _ = journal_fixture(tmp_path)
    original = journal.read_bytes()
    writer = CampaignJournal(output)
    try:
        with pytest.raises(FileExistsError):
            run(micro_task(), ReadOnly(), stop_after=1, journal=writer)
    finally:
        writer.close()
    assert journal.read_bytes() == original


def test_cli_resumes_from_journal_only_then_compacts_the_completed_checkpoint(tmp_path):
    import subprocess
    import sys
    task = catalog()[0]
    output, journal, _ = journal_fixture(tmp_path, task)
    source = tmp_path / 'reader.py'
    source.write_text('import json,sys\nfor line in sys.stdin:\n json.loads(line)\n print(json.dumps({"tool":"read_campaign","arguments":{}}),flush=True)\n')
    result = subprocess.run([sys.executable, '-m', 'otisbench', 'campaign', '--task', task['id'],
        '--agent-command', f'{sys.executable} {source}', '--resume', str(output), '--output', str(output), '--stop-after', '2'],
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert not journal.exists()
    recovered = json.loads(output.read_text())
    assert len(recovered['trace']) == 4
    assert recovered['error_type'] is None
    assert replay(task, recovered) == recovered['result']


def test_public_control_purchases_replacement_material_then_manufactures_and_ships():
    """One small work-order integration fixture exercises the full deposit lifecycle."""
    import random
    from faraday_manufacturing_benchmark.campaign import CONTRACTS, restore
    task = micro_task(count=1)
    for seed in range(1000):
        contracts = list(CONTRACTS)
        random.Random(seed).shuffle(contracts)
        if contracts[0] == 'late_quality_hold':
            task['seed'] = seed
            break
    # This standalone test policy computes from business observations. Pending
    # supplier investigations are excluded from its material choices.
    source = Path(__file__).with_name('workflow_qualification_policy.py').read_text()
    lines = []
    for line in source.splitlines():
        if line.lstrip().startswith('eligible=['):
            lines.append("        blocked={row['lot_id'] for row in records['QMS']['supplier_investigations']}")
            line = line[:-1] + " and l['id'] not in blocked]"
        if line.lstrip().startswith("if lot['status']"):
            line = line.replace("if lot['status']", "if lot['id'] in blocked or lot['status']", 1)
        lines.append(line)
    namespace = {'__name__': 'public_procurement_component'}
    exec(compile('\n'.join(lines), '<public-procurement-component>', 'exec'), namespace)

    class Control:
        def __init__(self):
            self.owner = None
            self.policy = namespace['FeasibilityPolicy']()
            self.pending = None
            self.allocation = None
        def wrap(self, decision):
            return dict(tool='act', arguments=dict(work_order_id=self.owner,
                action=decision['tool'], parameters=decision['arguments']))
        def decide(self, track, payload):
            last = payload['last_result']
            if self.owner is None:
                if last is None:
                    return dict(tool='read_campaign', arguments={})
                self.owner = last['work_orders'][0]['id']
            if last and last.get('finished'):
                return dict(tool='finish_campaign', arguments={})
            if self.pending is not None:
                self.allocation = last['allocation']['id']
                self.pending['arguments']['payload']['allocation_id'] = self.allocation
                decision, self.pending = self.pending, None
                return self.wrap(decision)
            decision = self.policy.decide('workflow', payload)
            if decision['tool'] == 'request_approval' and decision['arguments']['kind'] == 'purchase':
                self.pending = deepcopy(decision)
                purchase = decision['arguments']['payload']
                return dict(tool='reserve_supply', arguments=dict(work_order_id=self.owner,
                    units=purchase['units'], expedited=purchase['expedited'],
                    window_start=payload['clock_minute'] // 480 * 480))
            if decision['tool'] == 'purchase':
                decision['arguments']['allocation_id'] = self.allocation
            return self.wrap(decision)

    artifact = run(task, Control())
    assert artifact['error_type'] is None, artifact['error_type']
    assert artifact['result']['strict_success'], artifact['result']
    world, _ = restore(task, artifact)
    assert any(row['lot_id'].startswith('LOT-PO-') for row in world.orders['WO-0001'].consumed)
    assert all(row['lot_id'] != 'LOT-MAIN' for row in world.orders['WO-0001'].consumed)
    assert world.prepaid_cents == 0
    assert all(a['status'] == 'used' for a in world.allocations.values())


def test_financial_check_links_a_consumed_allocation_to_its_actual_purchase():
    world, view = plant()
    allocation = book(world, view, units=4)
    approval = approve_purchase(world, view, 'WO-0001', allocation, 4)
    act(world, view, 'WO-0001', 'purchase', units=4, expedited=False, approval_id=approval, allocation_id=allocation)
    assert world.grade()['ledger_ok']
    world.orders['WO-0001'].records['SCM']['purchase_orders']['PO-1']['units'] += 1
    assert not world.grade()['ledger_ok']


def test_logistics_projection_drops_evaluator_annotations_in_new_records():
    from faraday_manufacturing_benchmark.shopfloor_views import PRIVATE_KEYS
    world, view = plant()
    allocation = book(world, view)
    world.call('order_spares', dict(kind='tooling_kit', quantity=4, expedited=False), view)
    world.allocations[allocation]['solution'] = 'private'
    world.spare_orders['PO-SPARES-0001']['reference_answer'] = 3
    world.spare_catalog = deepcopy(world.spare_catalog)
    world.spare_catalog['tooling_kit']['expected_answer'] = 'private'
    world.spares['oracle'] = 1
    public = world.public_records(view)
    def keys(value):
        if isinstance(value, dict):
            for key, item in value.items():
                yield key
                yield from keys(item)
        elif isinstance(value, list):
            for item in value:
                yield from keys(item)
    assert not set(keys(public)) & PRIVATE_KEYS
