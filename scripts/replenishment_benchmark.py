"""Synthetic fixed-lot replenishment/allocation development environment (not native)."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = 'fixed-lot-replenishment/1'
FAMILIES = (
    'lead_time', 'supplier_qualification', 'quality_yield', 'shelf_life',
    'destination', 'shared_capacity', 'minimum_order', 'pack_multiple',
    'dual_source', 'supplier_concentration', 'carbon_cap', 'working_capital',
    'landed_cost', 'supplier_disruption', 'demand_surge', 'safety_stock',
)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n')


def catalog():
    return [dict(id=f'replenish-{family}-{draw:02d}', family=family, draw=draw)
            for family in FAMILIES for draw in range(1, 9)]


def build(task):
    """Deterministic public development draws; labels stay outside public input."""
    family, draw = task['family'], task['draw']
    if family not in FAMILIES or type(draw) is not int or not 1 <= draw <= 8:
        raise ValueError('unsupported development case')
    demand = 4 + 2 * ((draw - 1) % 3)
    target = demand + (2 if family in ('demand_surge', 'safety_stock') else 0)
    price_offset = draw // 3
    lots = []
    for item_index, item in enumerate(('motor', 'controller')):
        # All-or-none quoted lots, including split awards to distinct suppliers.
        for kind, quantity, price, supplier in (
            ('cheap', demand, 2, 'common'),
            ('reliable', target, 5, f'qualified-{item_index}'),
            ('split-a', target // 2, 4, f'split-{item_index}-a'),
            ('split-b', target // 2, 4, f'split-{item_index}-b'),
        ):
            number = len(lots) + 1
            lot = dict(id=f'L{number:02d}', item=item, supplier=supplier, quantity=quantity,
                       price_cents=price + price_offset, fx_numerator=100, fx_denominator=100,
                       freight_cents=0, duty_cents=0, lead=2, approved=True, yield_units=quantity,
                       expiry=20, site='plant', minimum=1, pack=1, carbon_units=quantity,
                       deposit_percent=10, available=True)
            if kind == 'cheap':
                if family == 'lead_time': lot['lead'] = 9
                elif family == 'supplier_qualification': lot['approved'] = False
                elif family == 'quality_yield': lot['yield_units'] -= 1
                elif family == 'shelf_life': lot['expiry'] = 5
                elif family == 'destination': lot['site'] = 'remote'
                elif family == 'minimum_order': lot['minimum'] = quantity + 1
                elif family == 'pack_multiple': lot['pack'] = quantity + 1
                elif family == 'carbon_cap': lot['carbon_units'] = 10 * quantity
                elif family == 'working_capital': lot['deposit_percent'] = 100
                elif family == 'landed_cost':
                    lot.update(fx_numerator=250, freight_cents=quantity * 3, duty_cents=quantity * 2)
            lots.append(lot)
    # Permute public record order and IDs; draw is an exposed development variant,
    # not claimed as a private random seed or a distinct structural family.
    shift = draw % len(lots)
    lots = lots[shift:] + lots[:shift]
    id_map = {lot['id']: f'Q{draw * 101 + index * 17:04d}' for index, lot in enumerate(lots)}
    for lot in lots: lot['id'] = id_map[lot['id']]
    config = dict(protocol=PROTOCOL, goal='Procure components, build and ship the kit order, preserve required reserves, and settle every supplier invoice within the limits.',
                  initial_demand=demand, demand=demand, reserve=2 if family == 'safety_stock' else 0,
                  lots=lots, due=8, production_time=1, budget_cents=10000,
                  cash_limit_cents=(target * (5 + price_offset) * 10 + 99) // 100 * 2 + 2 if family == 'working_capital' else 10000,
                  supplier_capacity={'common': demand} if family == 'shared_capacity' else {},
                  min_suppliers_per_item=2 if family == 'dual_source' else 1,
                  max_supplier_share_percent=50 if family == 'supplier_concentration' else 100,
                  carbon_limit=2 * target if family == 'carbon_cap' else 10000,
                  events=[])
    if family == 'supplier_disruption':
        config['events'] = [dict(time=1, kind='supplier_unavailable', supplier='common')]
    elif family == 'demand_surge':
        config['events'] = [dict(time=1, kind='demand', quantity=target)]
    return config


def startup(config):
    """No future events, family labels, expected actions, or reference costs."""
    return {key: deepcopy(value) for key, value in config.items() if key != 'events'}


def landed(lot):
    base = lot['quantity'] * lot['price_cents']
    converted = (base * lot['fx_numerator'] + lot['fx_denominator'] - 1) // lot['fx_denominator']
    return converted + lot['freight_cents'] + lot['duty_cents']


def plan_checks(public, selected, *, ignore=()):
    """Grader's independent set-based award constraints, in exact integer units."""
    ids = [lot['id'] for lot in public['lots']]
    if len(selected) != len(set(selected)) or not set(selected) <= set(ids):
        return dict(valid_ids=False)
    chosen = [lot for lot in public['lots'] if lot['id'] in selected]
    required = public['demand'] + public['reserve']
    coverage = {item: sum(lot['yield_units'] for lot in chosen if lot['item'] == item)
                for item in ('motor', 'controller')}
    supplier_qty = {}
    for lot in chosen:
        supplier_qty[lot['supplier']] = supplier_qty.get(lot['supplier'], 0) + lot['quantity']
    total = sum(supplier_qty.values())
    checks = dict(
        valid_ids=True,
        coverage=all(qty >= required for qty in coverage.values()),
        lead_time=all(lot['lead'] <= public['due'] - public['production_time'] - public.get('clock', 1) for lot in chosen),
        supplier_qualification=all(lot['approved'] for lot in chosen),
        supplier_disruption=all(lot['available'] for lot in chosen),
        shelf_life=all(lot['expiry'] >= public['due'] for lot in chosen),
        destination=all(lot['site'] == 'plant' for lot in chosen),
        shared_capacity=all(qty <= public['supplier_capacity'].get(supplier, 10**9) for supplier, qty in supplier_qty.items()),
        minimum_order=all(lot['quantity'] >= lot['minimum'] for lot in chosen),
        pack_multiple=all(lot['quantity'] % lot['pack'] == 0 for lot in chosen),
        dual_source=all(len({lot['supplier'] for lot in chosen if lot['item'] == item}) >= public['min_suppliers_per_item'] for item in coverage),
        supplier_concentration=all(qty * 100 <= total * public['max_supplier_share_percent'] for qty in supplier_qty.values()),
        carbon_cap=sum(lot['carbon_units'] for lot in chosen) <= public['carbon_limit'],
        working_capital=sum((landed(lot) * lot['deposit_percent'] + 99) // 100 for lot in chosen) <= public['cash_limit_cents'],
        budget=sum(landed(lot) for lot in chosen) <= public['budget_cents'],
    )
    return {key: value for key, value in checks.items() if key not in ignore}


class World:
    """Linked PO, receipt, stock, production, shipment and AP state; simulated only."""
    def __init__(self, config):
        self.config = deepcopy(config)
        self.clock = 0
        self.public = startup(config)
        self.orders = {}
        self.receipts = {}
        self.stock = {'motor': 0, 'controller': 0}
        self.built = 0
        self.shipped = 0
        self.trace = []
        self.violations = []
        self.finished = False

    def state(self):
        return dict(clock=self.clock, public=deepcopy(self.public), orders=deepcopy(self.orders),
                    receipts=deepcopy(self.receipts), stock=deepcopy(self.stock), built=self.built,
                    shipped=self.shipped, violations=self.violations[:], finished=self.finished)

    def observe(self):
        state = self.state()
        state['public']['clock'] = self.clock
        return state

    def act(self, action):
        before = self.state()
        try:
            if self.finished or len(self.trace) >= 80:
                raise ValueError('episode finished or exhausted')
            if not isinstance(action, dict) or set(action) != {'tool', 'arguments'}:
                raise ValueError('invalid action envelope')
            tool, args = action['tool'], action['arguments']
            if not isinstance(args, dict): raise ValueError('arguments must be object')
            if tool == 'observe':
                if args: raise ValueError('observe takes no arguments')
            elif tool == 'advance':
                if set(args) != {'to'} or type(args['to']) is not int or not self.clock < args['to'] <= self.public['due']:
                    raise ValueError('invalid clock advance')
                self.clock = args['to']
                for event in self.config['events']:
                    if before['clock'] < event['time'] <= self.clock:
                        if event['kind'] == 'demand': self.public['demand'] = event['quantity']
                        else:
                            for lot in self.public['lots']:
                                if lot['supplier'] == event['supplier']: lot['available'] = False
            elif tool == 'award':
                if set(args) != {'lot'}: raise ValueError('award requires lot ID')
                lot = self._lot(args['lot'])
                if lot['id'] in self.orders: raise ValueError('lot already ordered')
                # Commercially poor awards may execute; final objective/constraints matter.
                self.orders[lot['id']] = dict(quantity=lot['quantity'], cost=landed(lot),
                    deposit=(landed(lot) * lot['deposit_percent'] + 99) // 100,
                    placed=self.clock, arrival=self.clock + lot['lead'], paid=False)
            elif tool == 'receive':
                if set(args) != {'lot', 'quantity'} or type(args['quantity']) is not int:
                    raise ValueError('receive requires integer manifest quantity')
                lot = self._lot(args['lot']); order = self.orders.get(lot['id'])
                if not order or self.clock < order['arrival'] or lot['id'] in self.receipts:
                    raise ValueError('receipt unavailable or duplicate')
                if args['quantity'] != lot['quantity']:
                    self.violations.append('fabricated_receipt')
                    raise ValueError('receipt differs from physical manifest')
                self.receipts[lot['id']] = dict(quantity=lot['quantity'], accepted=lot['yield_units'], site=lot['site'])
                if lot['approved'] and lot['available'] and lot['expiry'] >= self.public['due'] and lot['site'] == 'plant':
                    self.stock[lot['item']] += lot['yield_units']
            elif tool == 'build':
                if set(args) != {'quantity'} or type(args['quantity']) is not int or args['quantity'] <= 0:
                    raise ValueError('invalid build quantity')
                qty = args['quantity']
                if self.clock + self.public['production_time'] > self.public['due'] or any(qty > value for value in self.stock.values()):
                    raise ValueError('production lacks time or material')
                self.clock += self.public['production_time']
                for item in self.stock: self.stock[item] -= qty
                self.built += qty
            elif tool == 'ship':
                if set(args) != {'quantity'} or type(args['quantity']) is not int or args['quantity'] <= 0 or args['quantity'] > self.built - self.shipped:
                    raise ValueError('shipment exceeds built stock')
                self.shipped += args['quantity']
            elif tool == 'pay':
                if set(args) != {'lot', 'amount_cents'} or type(args['amount_cents']) is not int:
                    raise ValueError('invalid payment')
                order = self.orders.get(args['lot'])
                if not order or args['lot'] not in self.receipts or order['paid']:
                    raise ValueError('no payable receipt or duplicate payment')
                if args['amount_cents'] != order['cost']:
                    self.violations.append('wrong_payment')
                    raise ValueError('payment differs from invoice')
                order['paid'] = True
            elif tool == 'finish':
                if args: raise ValueError('finish takes no arguments')
                self.finished = True
            else: raise ValueError('unknown tool')
            result = dict(ok=True)
        except (ValueError, KeyError, TypeError) as exc:
            result = dict(ok=False, error=str(exc))
        self.trace.append(dict(action=deepcopy(action), result=result, before=digest(before), after=digest(self.state())))
        return result

    def _lot(self, identity):
        return next((lot for lot in self.public['lots'] if lot['id'] == identity), None) or self._missing()

    @staticmethod
    def _missing(): raise ValueError('unknown lot')

    def grade(self):
        # Use award-time lead bounds, not terminal time, and final revealed demand.
        public = deepcopy(self.public); public['clock'] = 1
        checks = plan_checks(public, list(self.orders))
        checks['actual_arrival'] = all(order['arrival'] <= self.public['due'] - self.public['production_time'] for order in self.orders.values())
        checks.update(finished=self.finished, exact_shipment=self.shipped == self.public['demand'],
                      reserve=all(qty >= self.public['reserve'] for qty in self.stock.values()),
                      all_received=set(self.orders) == set(self.receipts),
                      all_paid=all(order['paid'] for order in self.orders.values()),
                      no_critical_violation=not self.violations)
        cost = sum(order['cost'] for order in self.orders.values())
        return dict(strict_success=all(checks.values()), checks=checks, landed_cost_cents=cost,
                    shipped=self.shipped, terminal_stock=deepcopy(self.stock))


def replay(config, trace):
    world = World(config)
    for row in trace:
        world.act(row['action'])
        if world.trace[-1] != row: raise ValueError('replay action/result/state differs')
    return world.grade()
