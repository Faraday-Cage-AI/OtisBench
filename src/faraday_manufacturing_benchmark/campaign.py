"""Persistent multi-order manufacturing campaigns with shared plant resources."""
from __future__ import annotations
from copy import deepcopy
import argparse
import hashlib
import json
import math
from pathlib import Path
import random

from .shopfloor import ManufacturingWorkflow, TOOLS, digest, overlap
from .shopfloor_cases import ROUTES, SYSTEMS
from .shopfloor_views import AgentView
from .campaign_logistics import CampaignLogistics

PROTOCOL = 'otisbench-production-campaign/2'
PROFILES = {'six_shift': (12, 2880), 'twelve_shift': (24, 5760),
            'twenty_four_shift': (48, 11520), 'forty_eight_shift': (96, 23040)}
CONTRACTS = ('compound_recovery', 'late_quality_hold', 'drawing_effectivity',
             'failed_final_inspection', 'split_material_lots', 'customer_allocation',
             'serial_recall', 'late_inbound_material')
CAMPAIGN_TOOLS = {
    'read_campaign': {},
    'act': {'work_order_id': 'issued work-order handle', 'action': 'manufacturing tool name',
            'parameters': 'arguments matching that manufacturing tool'},
    'wait': {'minutes': 'integer 1..300'},
    'service_machine': {'machine_id': 'issued equipment handle'},
    'repair_machine': {'machine_id': 'issued equipment handle'},
    'renew_qualification': {'operator_id': 'issued employee handle'},
    'reserve_supply': {'work_order_id': 'issued work-order handle', 'units': 'positive integer',
                       'window_start': 'dispatch-window start minute', 'expedited': 'boolean'},
    'cancel_supply': {'allocation_id': 'issued supply reservation handle'},
    'order_spares': {'kind': 'tooling_kit | repair_kit', 'quantity': 'positive pack multiple, at most 32', 'expedited': 'boolean'},
    'finish_campaign': {},
}


MANUFACTURING_TOOLS = deepcopy(TOOLS)
MANUFACTURING_TOOLS['purchase']['allocation_id'] = 'confirmed supply reservation ID; also include in approval payload'


def catalog():
    return [dict(id=f'campaign-{family}-{profile}', family=family, profile=profile,
                 order_count=count, horizon_minutes=horizon, max_tool_calls=count * 240,
                 release_cadence_minutes=216 if count >= 48 else 180,
                 seed=int.from_bytes(hashlib.sha256(f'{family}:{profile}:campaign-v1'.encode()).digest()[:8], 'big'))
            for family in ROUTES for profile, (count, horizon) in PROFILES.items()]


class CampaignOrder(ManufacturingWorkflow):
    def local_state(self):
        shared_fields = {'MES': {'machines'}, 'HR': {'operators'}, 'QMS': {'instruments'}}
        records = {system: {key: value for key, value in rows.items() if key not in shared_fields.get(system, ())}
                   for system, rows in self.records.items()}
        return dict(records=records, versions=self.versions, read_versions=self.read_versions,
            approvals=self.approvals, approval_uses=sorted(self.approval_uses), spent=self.spent_cents,
            violations=self.violations, events=self.events, parameters_ok=self.parameters_ok,
            consumed=self.consumed, finished=self.finished, rework_completed=self.rework_completed,
            inspection_counter=self.inspection_counter, release_minute=self.release_minute,
            contract_value_cents=getattr(self, 'contract_value_cents', None))

    def state_hash(self):
        if not hasattr(self, 'campaign'):
            return super().state_hash()
        return digest(dict(clock=self.clock, order=self.local_state(), shared=self.campaign._shared_hashes()))

    def _advance(self, minutes):
        self.campaign.advance(minutes)

    def _spend(self, cents):
        plant = self.campaign
        allocation = getattr(self, '_purchase_allocation', None)
        deposit = allocation['deposit_cents'] if allocation else 0
        if plant.cash_cents < cents - deposit:
            plant.spend_error = 'cash_insufficient'
            return False
        if plant.spent_cents + cents > plant.budget_cents:
            plant.spend_error = 'campaign_budget_exceeded'
            return False
        if not super()._spend(cents):
            return False
        plant.cash_cents -= cents - deposit
        plant.prepaid_cents -= deposit
        plant.spent_cents += cents
        return True

    def _do_purchase(self, units, expedited, approval_id, allocation_id=None):
        supplier = self.records['SCM']['supplier']
        if type(units) is not int or units < supplier['minimum_units'] or type(expedited) is not bool:
            return self._error('invalid supplier order')
        allocation, error = self.campaign.allocation_for_purchase(self, allocation_id, units, expedited)
        if error:
            self.campaign.spend_error = error
            return self._error(error)
        payload = dict(units=units, expedited=expedited, allocation_id=allocation_id)
        if not self._authorized(approval_id, 'purchase', payload, consume=False):
            return self._error('purchase authorization mismatch', critical=True)
        cost = units * supplier['unit_cents'] + (supplier['expedite_cents'] if expedited else 0)
        self._purchase_allocation = allocation
        try:
            paid = self._spend(cost)
        finally:
            self._purchase_allocation = None
        if not paid:
            return self._error('purchase exceeds available funds or budget')
        self.approval_uses.add(approval_id)
        key = f'PO-{len(self.records["SCM"]["purchase_orders"]) + 1}'
        due = max(self.clock, allocation['window_start']) + supplier['expedited_lead_minutes' if expedited else 'standard_lead_minutes']
        po = dict(id=key, units=units, lot_id='LOT-' + key, status='in_transit', due_minute=due)
        self.records['SCM']['purchase_orders'][key] = po
        allocation.update(status='used', purchase_order=key, purchase_minute=self.clock)
        self._bump('SCM')
        return dict(ok=True, purchase_order=deepcopy(po), cost_cents=cost)

    def _do_start_operation(self, **arguments):
        result = super()._do_start_operation(**arguments)
        if result.get('ok'):
            op = result['operation']
            # Local route IDs may repeat; shared bookings are work-order scoped.
            for pool in (self.records['MES']['machines'], self.records['HR']['operators'], self.records['QMS']['instruments']):
                for resource in pool.values():
                    for booking in resource['busy']:
                        if booking['source'] == op['id'] and booking['start'] == op['start'] and booking['finish'] == op['finish']:
                            booking['source'] = self.key + ':' + op['id']
        return result

    def _do_reroute_interrupted_operation(self, operation_id):
        op = next((o for o in self.records['MES']['operations'] if o['id'] == operation_id), None)
        if not op or op['status'] != 'interrupted':
            return self._error('only interrupted operations can be rerouted')
        if not self._current('MES', 'WMS'):
            return self._error('reconcile interrupted WIP before rerouting')
        for pool in (self.records['MES']['machines'], self.records['HR']['operators'], self.records['QMS']['instruments']):
            for resource in pool.values():
                resource['busy'] = [b for b in resource['busy'] if b['source'] != self.key + ':' + operation_id]
        op.update(status='pending', machine=None, operator=None, start=None, finish=None)
        self._bump('MES', 'HR', 'QMS')
        return dict(ok=True, operation_id=operation_id, wip_preserved=True)

    def _do_replace_tool(self, machine_id):
        if self.campaign.spares['tooling_kit'] < 1:
            self.campaign.spend_error = 'spare_unavailable'
            return self._error('spare unavailable')
        result = super()._do_replace_tool(machine_id)
        if result.get('ok'):
            self.campaign.spares['tooling_kit'] -= 1
            self.campaign.spares_used['tooling_kit'] += 1
            self.records['MES']['machines'][machine_id]['tool_remaining_units'] = self.campaign.tool_capacity
            result['tool_remaining_units'] = self.campaign.tool_capacity
        return result

    def _do_complete_operation(self, operation_id, certificate_id=None):
        result = super()._do_complete_operation(operation_id, certificate_id)
        if result.get('ok') and all(o['status'] == 'finished' for o in self.records['MES']['operations']):
            serials = self.records['WMS']['serials']
            for old in list(serials):
                serial = serials.pop(old)
                serial['id'] = f"SN-{self.key[3:]}-{old[3:]}"
                serials[serial['id']] = serial
        return result


class ProductionCampaign(CampaignLogistics):
    """One clock, treasury, machine fleet, workforce and fixture inventory."""
    tool_capacity = 120
    service_minutes = 30
    service_cost_cents = 6500
    service_coverage_minutes = 960
    repair_minutes = 45
    repair_cost_cents = 9000
    renewal_minutes = 30
    renewal_cost_cents = 3500
    qualification_minutes = 1440
    payment_terms_minutes = 240

    def __init__(self, task):
        self.task = deepcopy(task)
        self.clock = 0
        self.trace = []
        self.finished = False
        self.spend_error = None
        self.orders = {}
        self.calendar = []
        self.fired = set()
        self.services = []
        self.receivables = []
        self.received_cents = 0
        self.spent_cents = 0
        self.plant_spent_cents = 0
        self._init_logistics()
        rng = random.Random(task['seed'])
        contracts = list(CONTRACTS)
        rng.shuffle(contracts)
        for index in range(task['order_count']):
            release = index * task.get('release_cadence_minutes', 180) + (rng.randint(0, 25) if index else 0)
            contract = contracts[index % len(contracts)]
            if task['order_count'] >= 12 and index == task['order_count'] - 1:
                contract = 'compound_recovery'
            child = dict(id=f"{task['id']}-order-{index + 1}", family=task['family'], disruption=contract,
                         draw=index, seed=rng.getrandbits(64), systems=list(SYSTEMS),
                         max_tool_calls=240, horizon_minutes=task['horizon_minutes'])
            world = CampaignOrder(child)
            world.campaign = self
            world.key = f'WO-{index + 1:04}'
            world.release_minute = release
            world.records['ERP']['work_order'] = world.key
            for n, order in enumerate(world.records['ERP']['orders']):
                order['id'] = f'SO-{index + 1:04}-{n + 1}'
            for lot in world.records['WMS']['lots'].values():
                lot['expiry_minute'] += release
            for po in world.records['SCM']['purchase_orders'].values():
                po['due_minute'] += release
            # Events are dated per order and distributed throughout the campaign.
            if contract in ('drawing_effectivity', 'compound_recovery'):
                at = release + rng.randint(28, 85)
                self.calendar.append(dict(kind='engineering_release', at=at, work_order=world.key))
                for row in world.records['PLM']['change_requests']:
                    row['review_due_minute'] = at
            if contract in ('late_quality_hold', 'compound_recovery'):
                at = release + rng.randint(90, 160)
                self.calendar.append(dict(kind='quality_disposition', at=at, work_order=world.key))
                for row in world.records['QMS']['supplier_investigations']:
                    row['review_due_minute'] = at
            if contract == 'compound_recovery':
                stage = rng.randint(1, len(ROUTES[task['family']][2]))
                machine = f'M-{stage:02}'
                self.calendar.append(dict(kind='machine_trip', at=release + rng.randint(100, 240),
                                          work_order=world.key, machine=machine))
                world.records['CMMS']['equipment_alerts'] = [dict(machine_id=machine, severity='high',
                    reading='condition limit exceeded', status='open')]
            self.orders[world.key] = world
        self.machines = deepcopy(next(iter(self.orders.values())).records['MES']['machines'])
        self.operators = deepcopy(next(iter(self.orders.values())).records['HR']['operators'])
        self.fixtures = deepcopy(next(iter(self.orders.values())).records['QMS']['instruments'])
        maximum_quantity = max(w.records['ERP']['required_units'] for w in self.orders.values())
        for machine in self.machines.values():
            machine.update(status='available', batch_limit=maximum_quantity,
                           tool_remaining_units=maximum_quantity * 2, regular_until_minute=task['horizon_minutes'])
        for key, person in self.operators.items():
            person['certified_until_minute'] = task['horizon_minutes'] + 500 if key.endswith('-Q') else 900
        for fixture in self.fixtures.values():
            fixture['calibrated_until_minute'] = 1100
        for world in self.orders.values():
            r = world.records
            r['MES']['machines'] = self.machines
            r['HR']['operators'] = self.operators
            r['QMS']['instruments'] = self.fixtures
            quantity = r['ERP']['required_units']
            primary_cost = 0
            route_minutes = 0
            for i, _ in enumerate(r['MES']['operations']):
                machine = self.machines[f'M-{i + 1:02}']
                duration = math.ceil(machine['setup_minutes'] + machine['minutes_per_unit'] * quantity)
                primary_cost += duration * machine['cents_per_minute']
                route_minutes += duration
            first = self.machines['M-01']
            alternate = self.machines['M-01-ALT']
            premium = math.ceil(alternate['setup_minutes'] + alternate['minutes_per_unit'] * quantity) * alternate['cents_per_minute']
            premium -= math.ceil(first['setup_minutes'] + first['minutes_per_unit'] * quantity) * first['cents_per_minute']
            budget = math.ceil(primary_cost * 1.08) + 20000
            if world.task['disruption'] == 'compound_recovery':
                budget += premium
            if world.task['disruption'] in ('compound_recovery', 'late_quality_hold', 'late_inbound_material'):
                budget += math.ceil(quantity / 2) * 1800 + 8000
            r['ERP']['budget_cents'] = budget
            world.contract_value_cents = math.ceil(budget * 1.12)
            world.deadline = min(task['horizon_minutes'] - 30, world.release_minute + route_minutes + 480)
            for order in r['ERP']['orders']:
                order['due_minute'] = world.deadline
            world.source_commitment = digest(dict(task=world.task, records=r))
            world.initial_state_hash = world.state_hash()
        self.calendar.sort(key=lambda e: (e['at'], e['work_order'], e['kind']))
        self.budget_cents = sum(w.records['ERP']['budget_cents'] for w in self.orders.values()) + task['order_count'] * 4000
        self.opening_cash_cents = math.ceil(max(w.records['ERP']['budget_cents'] for w in self.orders.values()) * 2.5)
        self.cash_cents = self.opening_cash_cents
        self.shared_hashes = self._shared_hashes()
        self.source_commitment = digest(dict(task=task, calendar=self.calendar,
            orders={k: w.source_commitment for k, w in self.orders.items()}, opening_cash=self.opening_cash_cents,
            logistics=self.logistics_state()))
        self.initial_state_hash = self.state_hash()

    def _shared_hashes(self):
        return {'MES': digest(self.machines), 'HR': digest(self.operators), 'QMS': digest(self.fixtures)}

    def _sync_shared(self, exclude=None):
        current = self._shared_hashes()
        for system in current:
            if current[system] != self.shared_hashes[system]:
                for world in self.orders.values():
                    if world is not exclude:
                        world._bump(system)
        self.shared_hashes = current

    def state_hash(self):
        return digest(dict(clock=self.clock, orders={k: w.local_state() for k, w in self.orders.items()}, shared=self._shared_hashes(),
                           cash=self.cash_cents, spent=self.spent_cents, plant_spent=self.plant_spent_cents,
                           received=self.received_cents, receivables=self.receivables, fired=sorted(self.fired), finished=self.finished,
                           logistics=self.logistics_state(), services=self.services))

    def _move_to(self, minute):
        self.clock = minute
        for world in self.orders.values():
            world.clock = minute
            r = world.records
            for po in r['SCM']['purchase_orders'].values():
                if po['status'] == 'in_transit' and po['due_minute'] <= minute:
                    certificate = 'CERT-' + po['id']
                    r['WMS']['lots'][po['lot_id']] = dict(id=po['lot_id'], material=r['PLM']['material'],
                        units=po['units'], reserved=0, status='released', expiry_minute=po['due_minute'] + 1800,
                        certificate=certificate, ownership='owned')
                    r['SCM']['certificates'][certificate] = dict(id=certificate, lot_id=po['lot_id'], status='accepted')
                    po['status'] = 'received'
                    world._bump('WMS', 'SCM')
        for row in self.receivables:
            if row['status'] == 'pending' and row['due_minute'] <= minute:
                self.cash_cents += row['amount_cents']
                self.received_cents += row['amount_cents']
                row['status'] = 'received'

        self.advance_logistics(minute)

    def _apply_event(self, event):
        world = self.orders[event['work_order']]
        r = world.records
        if event['kind'] == 'engineering_release':
            r['PLM']['revision'] = 'B'
            for row in r['PLM']['change_requests']:
                row['status'] = 'released'
            for instruction in r['PLM']['instructions'].values():
                instruction['revision'] = 'B'
                key = next(k for k in ('surface_m_min', 'target_temperature_c', 'amps', 'projected_area_cm2',
                    'ingredient_a_kg', 'zone_length_mm', 'energy_kwh_batch') if k in instruction)
                instruction[key] += 12
            world._bump('PLM')
        elif event['kind'] == 'quality_disposition':
            r['WMS']['lots']['LOT-MAIN']['status'] = 'hold'
            for row in r['QMS']['supplier_investigations']:
                row.update(status='closed', disposition='hold')
            world._bump('WMS', 'QMS')
        else:
            machine = self.machines[event['machine']]
            if any(row['machine_id'] == machine['id'] and row['started_minute'] <= self.clock < row['covered_until_minute']
                   for row in self.services):
                for alert in r['CMMS']['equipment_alerts']:
                    if alert['machine_id'] == machine['id']:
                        alert['status'] = 'service_covered'
                world._bump('CMMS')
                self._sync_shared()
                return
            machine['status'] = 'down'
            for alert in r['CMMS']['equipment_alerts']:
                if alert['machine_id'] == machine['id']:
                    alert['status'] = 'triggered'
            world._bump('CMMS')
            for other in self.orders.values():
                for operation in other.records['MES']['operations']:
                    if operation['status'] == 'running' and operation['machine'] == event['machine'] and operation['finish'] > self.clock:
                        operation['status'] = 'interrupted'
                        other._bump('MES', 'CMMS')
        self._sync_shared()

    def advance(self, minutes):
        target = self.clock + minutes
        for index, event in enumerate(self.calendar):
            if index not in self.fired and event['at'] <= target:
                self._move_to(event['at'])
                self._apply_event(event)
                self.fired.add(index)
        self._move_to(target)

    def public_records(self, view):
        rows = []
        for key, world in self.orders.items():
            erp = world.records['ERP']
            row = view.encode(dict(id=key, product=erp['product'], required_units=erp['required_units'],
                shipped=sum(o['shipped'] for o in erp['orders']), due_minute=world.deadline,
                budget_cents=erp['budget_cents'], status='closed' if world.finished else 'scheduled' if self.clock < world.release_minute else 'open'))
            row.update(release_minute=world.release_minute, contract_value_cents=world.contract_value_cents,
                       calls_remaining=world.task['max_tool_calls'] - len(world.trace), spent_cents=world.spent_cents)
            rows.append(row)
        return dict(ok=True, clock_minute=self.clock, work_orders=rows, cash_cents=self.cash_cents,
            spent_cents=self.spent_cents, budget_cents=self.budget_cents,
            receivables=[dict(work_order_id=view.encode({'id': row['work_order']})['id'],
                amount_cents=row['amount_cents'], due_minute=row['due_minute'], status=row['status']) for row in self.receivables],
            maintenance=dict(service_minutes=self.service_minutes, service_cost_cents=self.service_cost_cents,
                service_coverage_minutes=self.service_coverage_minutes,
                services=[dict(machine_id=view.encode({'id': row['machine_id']})['id'],
                    started_minute=row['started_minute'], completed_minute=row['completed_minute'],
                    covered_until_minute=row['covered_until_minute']) for row in self.services], repair_minutes=self.repair_minutes, repair_cost_cents=self.repair_cost_cents,
                tool_capacity_units=self.tool_capacity, renewal_minutes=self.renewal_minutes,
                renewal_cost_cents=self.renewal_cost_cents, qualification_minutes=self.qualification_minutes),
            payment_terms_minutes=self.payment_terms_minutes, **self.public_logistics(view))

    def _plant_spend(self, cents):
        if self.cash_cents < cents:
            return False
        if self.spent_cents + cents > self.budget_cents:
            return False
        self.cash_cents -= cents
        self.spent_cents += cents
        self.plant_spent_cents += cents
        return True

    def call(self, tool, arguments, view):
        if self.finished or len(self.trace) >= self.task['max_tool_calls'] or self.clock >= self.task['horizon_minutes']:
            raise ValueError('campaign closed or limit reached')
        self.spend_error = None
        before = self.state_hash()
        # Validate the outer schema before dispatch; rejected attempts still cost time.
        result = None
        try:
            if tool == 'act':
                if set(arguments) != {'work_order_id', 'action', 'parameters'} or not isinstance(arguments['parameters'], dict):
                    raise ValueError('invalid arguments')
                key = arguments['work_order_id']
                world = self.orders.get(key)
                if not world or self.clock < world.release_minute or world.finished or len(world.trace) >= world.task['max_tool_calls']:
                    self.advance(1)
                    result = dict(ok=False, error='work_order_unavailable', clock_minute=self.clock)
                else:
                    old_shipped = sum(o['shipped'] for o in world.records['ERP']['orders'])
                    native = world.call(arguments['action'], **arguments['parameters'])
                    self._sync_shared(exclude=world)
                    result = view.result(native)
                    if not native.get('ok') and self.spend_error:
                        result['error'] = self.spend_error
                    if arguments['action'] == 'ship' and native.get('ok'):
                        new_shipped = sum(o['shipped'] for o in world.records['ERP']['orders'])
                        quantity = world.records['ERP']['required_units']
                        amount = world.contract_value_cents * new_shipped // quantity - world.contract_value_cents * old_shipped // quantity
                        self.receivables.append(dict(work_order=key, shipment=native['shipment']['id'], amount_cents=amount,
                            due_minute=self.clock + self.payment_terms_minutes, status='pending'))
                    result.update(work_order_id=view.encode({'id': key})['id'])
            else:
                self.advance(1)
                if tool == 'read_campaign' and not arguments:
                    result = self.public_records(view)
                elif tool == 'wait' and set(arguments) == {'minutes'} and type(arguments['minutes']) is int and 1 <= arguments['minutes'] <= 300:
                    self.advance(arguments['minutes'])
                    result = dict(ok=True, clock_minute=self.clock)
                elif tool in ('reserve_supply', 'cancel_supply', 'order_spares'):
                    result = self.logistics_call(tool, arguments, view)
                elif tool == 'service_machine' and set(arguments) == {'machine_id'}:
                    machine = self.machines.get(arguments['machine_id'])
                    if not machine or machine['status'] != 'available':
                        result = dict(ok=False, error='machine_state_invalid', clock_minute=self.clock)
                    elif overlap(self.clock, self.clock + self.service_minutes, machine['busy']) or any(
                            o['machine'] == machine['id'] and o['status'] in ('running', 'interrupted')
                            for w in self.orders.values() for o in w.records['MES']['operations']):
                        result = dict(ok=False, error='resource_conflict', clock_minute=self.clock)
                    elif self.spares['repair_kit'] < 1:
                        result = dict(ok=False, error='spare_unavailable', clock_minute=self.clock)
                    elif not self._plant_spend(self.service_cost_cents):
                        result = dict(ok=False, error='funds_unavailable', clock_minute=self.clock)
                    else:
                        self.spares['repair_kit'] -= 1
                        self.spares_used['repair_kit'] += 1
                        self.services.append(dict(machine_id=machine['id'], started_minute=self.clock,
                            completed_minute=self.clock + self.service_minutes,
                            covered_until_minute=self.clock + self.service_minutes + self.service_coverage_minutes))
                        self.advance(self.service_minutes)
                        result = dict(ok=True, machine_id=view.encode({'id': machine['id']})['id'],
                            covered_until_minute=self.services[-1]['covered_until_minute'], clock_minute=self.clock)
                elif tool == 'repair_machine' and set(arguments) == {'machine_id'}:
                    machine = self.machines.get(arguments['machine_id'])
                    if not machine or machine['status'] != 'down':
                        result = dict(ok=False, error='machine_state_invalid', clock_minute=self.clock)
                    elif overlap(self.clock, self.clock + self.repair_minutes, machine['busy']) or any(o['machine'] == machine['id'] and o['status'] in ('running', 'interrupted')
                             for w in self.orders.values() for o in w.records['MES']['operations']):
                        result = dict(ok=False, error='resource_conflict', clock_minute=self.clock)
                    elif self.spares['repair_kit'] < 1:
                        result = dict(ok=False, error='spare_unavailable', clock_minute=self.clock)
                    elif not self._plant_spend(self.repair_cost_cents):
                        result = dict(ok=False, error='funds_unavailable', clock_minute=self.clock)
                    else:
                        self.spares['repair_kit'] -= 1
                        self.spares_used['repair_kit'] += 1
                        self.advance(self.repair_minutes)
                        machine['status'] = 'available'
                        for owner in self.orders.values():
                            for alert in owner.records['CMMS']['equipment_alerts']:
                                if alert['machine_id'] == machine['id'] and alert['status'] == 'triggered':
                                    alert['status'] = 'resolved'
                                    owner._bump('CMMS')
                        self._sync_shared()
                        result = view.encode(dict(ok=True, machine_id=machine['id'], status='available', clock_minute=self.clock))
                elif tool == 'renew_qualification' and set(arguments) == {'operator_id'}:
                    person = self.operators.get(arguments['operator_id'])
                    if not person or overlap(self.clock, self.clock + self.renewal_minutes, person['busy']):
                        result = dict(ok=False, error='resource_conflict', clock_minute=self.clock)
                    elif not self._plant_spend(self.renewal_cost_cents):
                        result = dict(ok=False, error='funds_unavailable', clock_minute=self.clock)
                    else:
                        self.advance(self.renewal_minutes)
                        person['certified_until_minute'] = self.clock + self.qualification_minutes
                        self._sync_shared()
                        result = view.encode(dict(ok=True, operator_id=person['id'], certified_until_minute=person['certified_until_minute'], clock_minute=self.clock))
                elif tool == 'finish_campaign' and not arguments:
                    if any(a['status'] == 'booked' for a in self.allocations.values()):
                        result = dict(ok=False, error='supply_commitments_open', clock_minute=self.clock)
                    elif not all(w.finished and w.trace and w.trace[-1]['tool'] == 'finish' and w.trace[-1]['result'].get('ok') and sum(o['shipped'] for o in w.records['ERP']['orders']) == w.records['ERP']['required_units'] for w in self.orders.values()):
                        result = dict(ok=False, error='orders_incomplete', clock_minute=self.clock)
                    else:
                        self.finished = True
                        result = dict(ok=True, finished=True, clock_minute=self.clock)
                else:
                    result = dict(ok=False, error='invalid_arguments', clock_minute=self.clock)
        except (TypeError, KeyError, ValueError):
            if self.state_hash() == before:
                self.advance(1)
            result = dict(ok=False, error='invalid_arguments', clock_minute=self.clock)
        record = dict(index=len(self.trace), tool=tool, arguments=deepcopy(arguments), result=deepcopy(result),
                      state_hash=self.state_hash())
        self.trace.append(record)
        return deepcopy(result)

    def grade(self):
        grades = [world.grade() for world in self.orders.values()]
        ledger_ok = (self.cash_cents == self.opening_cash_cents + self.received_cents - self.spent_cents - self.prepaid_cents
                     and self.spent_cents == self.plant_spent_cents + sum(w.spent_cents for w in self.orders.values())
                     and self.cash_cents >= 0 and self.received_cents == sum(r['amount_cents'] for r in self.receivables if r['status'] == 'received'))
        expected = {}
        for key, world in self.orders.items():
            erp = world.records['ERP']
            cumulative = 0
            for shipment in world.records['WMS']['shipments'].values():
                previous = cumulative
                cumulative += shipment['units']
                amount = (world.contract_value_cents * cumulative // erp['required_units']
                          - world.contract_value_cents * previous // erp['required_units'])
                due = shipment['minute'] + self.payment_terms_minutes
                expected[(key, shipment['id'])] = (amount, due, 'received' if due <= self.clock else 'pending')
        observed = {(r['work_order'], r['shipment']): (r['amount_cents'], r['due_minute'], r['status'])
                    for r in self.receivables}
        ledger_ok = ledger_ok and len(observed) == len(self.receivables) and observed == expected
        ledger_ok = ledger_ok and self.spent_cents <= self.budget_cents and self.logistics_check()
        quantity = sum(g['required_units'] for g in grades)
        delivered = sum(g['delivered_units'] for g in grades)
        strict = self.finished and ledger_ok and self.clock <= self.task['horizon_minutes'] and all(g['strict_success'] for g in grades)
        critical = any(g['critical_violations'] for g in grades)
        return dict(task_id=self.task['id'], strict_success=strict, score=0 if critical or not ledger_ok else sum(g['score'] for g in grades) / len(grades),
            orders_completed=sum(g['strict_success'] for g in grades), order_count=len(grades), delivered_units=delivered,
            required_units=quantity, elapsed_minutes=self.clock, tool_calls=len(self.trace), spent_cents=self.spent_cents,
            cash_cents=self.cash_cents, prepaid_cents=self.prepaid_cents, receivable_cents=sum(r['amount_cents'] for r in self.receivables if r['status'] == 'pending'),
            ledger_ok=ledger_ok, critical_violation=critical, orders=grades)


def startup(task, view):
    return dict(id=view.episode_id, title='Run the manufacturing production campaign',
        prompt='You are the plant operations lead. Take ownership of the backlog and carry every customer work order through to conforming delivery. Make decisions from the available business evidence, execute them through the tools, and adapt as conditions change. Manage shared production resources, supplier dispatch commitments, maintenance spares, qualifications, material eligibility, quality release, and cash. Keep working toward completion within the delivery windows, plant budget, horizon, and decision limits. Respect all required approvals. Finish each order with its evidence, then finish the campaign.',
        order_count=task['order_count'], horizon_minutes=task['horizon_minutes'], max_tool_calls=task['max_tool_calls'])


def source_fingerprints():
    root = Path(__file__).parent
    names = ('campaign.py', 'campaign_logistics.py', 'campaign_storage.py', 'shopfloor.py', 'shopfloor_cases.py', 'shopfloor_views.py', 'agents.py', 'isolation.py', '__init__.py')
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}


def run(task, agent, checkpoint=None, stop_after=None, resume=None, journal=None):
    if stop_after is not None and (type(stop_after) is not int or stop_after < 1):
        raise ValueError('stop_after must be a positive integer')
    if resume is None:
        world, view = ProductionCampaign(task), AgentView()
        transport = []
    else:
        world, view = restore(task, resume)
        if world.finished:
            raise ValueError('campaign already completed')
        transport = deepcopy(resume['agent_trace'])
    last = deepcopy(transport[-1]['result']) if transport else None
    starting_calls = len(world.trace)
    first_decision = True
    artifact = dict(protocol=PROTOCOL, track='production-campaign', evaluator_task_id=task['id'], task=startup(task, view),
                    source_hashes=source_fingerprints(), error_type=None)
    def snapshot():
        return dict(artifact, trace=deepcopy(world.trace), agent_trace=deepcopy(transport), result=world.grade(),
                    alias_nonce=view.nonce)
    if journal is not None:
        journal.start(snapshot())
    try:
        while not world.finished and len(world.trace) < task['max_tool_calls'] and world.clock < task['horizon_minutes']:
            if stop_after is not None and len(world.trace) - starting_calls >= stop_after:
                break
            payload = dict(clock_minute=world.clock, calls_remaining=task['max_tool_calls'] - len(world.trace), last_result=last)
            if first_decision:
                payload.update(task=startup(task, view), tools=deepcopy(CAMPAIGN_TOOLS), manufacturing_tools=deepcopy(MANUFACTURING_TOOLS))
                if resume is not None:
                    payload['history'] = deepcopy(transport)
                first_decision = False
            decision = agent.decide('campaign', payload)
            if not isinstance(decision, dict) or set(decision) != {'tool', 'arguments'} or not isinstance(decision['tool'], str) or not isinstance(decision['arguments'], dict):
                raise ValueError('invalid decision')
            arguments = view.decode(decision['arguments'])
            last = world.call(decision['tool'], arguments, view)
            transport.append(dict(decision=deepcopy(decision), result=deepcopy(last)))
            if journal is not None:
                journal.append(world.trace[-1], transport[-1])
            if checkpoint:
                checkpoint(snapshot())
    except (ValueError, OSError) as exc:
        artifact['error_type'] = type(exc).__name__
    return snapshot()


def restore(task, artifact):
    if artifact['protocol'] != PROTOCOL or artifact['source_hashes'] != source_fingerprints() or artifact['evaluator_task_id'] != task['id']:
        raise ValueError('campaign source or task mismatch')
    world = ProductionCampaign(task)
    view = AgentView(artifact['alias_nonce'])
    if artifact['task'] != startup(task, view) or len(artifact['trace']) != len(artifact['agent_trace']):
        raise ValueError('campaign transport mismatch')
    for record, public in zip(artifact['trace'], artifact['agent_trace']):
        if view.decode(public['decision']['arguments']) != record['arguments'] or public['decision']['tool'] != record['tool']:
            raise ValueError('campaign decision mismatch')
        result = world.call(record['tool'], record['arguments'], view)
        if world.trace[-1] != record or result != public['result']:
            raise ValueError('campaign replay mismatch')
    actual = world.grade()
    if actual != artifact['result']:
        raise ValueError('campaign terminal mismatch')
    return world, view


def replay(task, artifact):
    world, _ = restore(task, artifact)
    return world.grade()


def main(argv=None):
    parser = argparse.ArgumentParser(prog='otisbench campaign')
    parser.add_argument('--task', required=True)
    agent = parser.add_mutually_exclusive_group(required=True)
    agent.add_argument('--agent-command')
    agent.add_argument('--agent-file')
    parser.add_argument('--timeout', type=float, default=120)
    parser.add_argument('--stop-after', type=int)
    parser.add_argument('--resume')
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    return execute(args)


def execute(args):
    tasks = {t['id']: t for t in catalog()}
    if args.task not in tasks:
        raise ValueError('unknown campaign task')
    path = Path(args.output)
    from .campaign_storage import CampaignJournal, load_checkpoint
    same_output = bool(args.resume and Path(args.resume).resolve() == path.resolve())
    if path.exists() and not same_output:
        raise ValueError('output exists; resume it or choose a fresh output')
    prior = load_checkpoint(args.resume, tasks[args.task]) if args.resume else None
    journal = CampaignJournal(path, replace=same_output)
    if journal.path.exists() and not same_output:
        raise ValueError('recovery journal exists; resume it or choose a fresh output')
    def save(artifact):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + '.pending')
        temporary.write_text(json.dumps(artifact, sort_keys=True, indent=2, allow_nan=False) + '\n')
        temporary.replace(path)
    if args.agent_file:
        from .isolation import isolated_agent
        context = isolated_agent(args.agent_file, timeout=args.timeout)
    else:
        from .agents import DecisionAgent
        context = DecisionAgent(args.agent_command, timeout=args.timeout)
    try:
        with context as selected:
            artifact = run(tasks[args.task], selected, stop_after=args.stop_after, resume=prior, journal=journal)
            if hasattr(selected, 'isolation'):
                artifact['isolation'] = deepcopy(selected.isolation)
        save(artifact)
    finally:
        journal.close()
    journal.path.unlink()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
