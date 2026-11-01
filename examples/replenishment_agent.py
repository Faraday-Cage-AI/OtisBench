"""Public-record exhaustive fixed-lot control; no evaluator imports or future events.

Reads one JSON observation on stdin and emits a complete action plan. This small
offline planning interface is development-only, not a production agent sandbox.
"""
from itertools import combinations
import json
import sys


def cost(lot):
    numerator = lot['quantity'] * lot['price_cents'] * lot['fx_numerator']
    return -(-numerator // lot['fx_denominator']) + lot['freight_cents'] + lot['duty_cents']


def choose(observation):
    p = observation['public']
    lots = p['lots']
    candidates = []
    need = p['demand'] + p['reserve']
    for size in range(1, len(lots) + 1):
        for indices in combinations(range(len(lots)), size):
            award = [lots[index] for index in indices]
            if any(not lot['approved'] or not lot['available'] or lot['site'] != 'plant' or lot['expiry'] < p['due']
                   or observation['clock'] + lot['lead'] + p['production_time'] > p['due']
                   or lot['quantity'] < lot['minimum'] or lot['quantity'] % lot['pack'] for lot in award):
                continue
            if any(sum(lot['yield_units'] for lot in award if lot['item'] == item) < need
                   or len({lot['supplier'] for lot in award if lot['item'] == item}) < p['min_suppliers_per_item']
                   for item in ('motor', 'controller')):
                continue
            supplier_units = {}
            for lot in award:
                name = lot['supplier']; supplier_units[name] = supplier_units.get(name, 0) + lot['quantity']
            units = sum(supplier_units.values())
            if any(qty > p['supplier_capacity'].get(name, 10**9) or 100 * qty > p['max_supplier_share_percent'] * units
                   for name, qty in supplier_units.items()):
                continue
            amount = sum(cost(lot) for lot in award)
            if amount > p['budget_cents'] or sum(lot['carbon_units'] for lot in award) > p['carbon_limit']:
                continue
            if sum(-(-(cost(lot) * lot['deposit_percent']) // 100) for lot in award) > p['cash_limit_cents']:
                continue
            candidates.append((amount, tuple(sorted(lot['id'] for lot in award))))
    if not candidates: raise ValueError('no feasible public fixed-lot award')
    amount, selected = min(candidates)
    return dict(lots=list(selected), cost_cents=amount)


def actions(observation):
    selection = choose(observation)
    lots = {lot['id']: lot for lot in observation['public']['lots']}
    plan = [dict(tool='award', arguments=dict(lot=identity)) for identity in selection['lots']]
    arrival = max(observation['clock'] + lots[identity]['lead'] for identity in selection['lots'])
    plan.append(dict(tool='advance', arguments=dict(to=arrival)))
    for identity in selection['lots']:
        plan.append(dict(tool='receive', arguments=dict(lot=identity, quantity=lots[identity]['quantity'])))
    quantity = observation['public']['demand']
    plan.extend([dict(tool='build', arguments=dict(quantity=quantity)), dict(tool='ship', arguments=dict(quantity=quantity))])
    for identity in selection['lots']:
        plan.append(dict(tool='pay', arguments=dict(lot=identity, amount_cents=cost(lots[identity]))))
    plan.append(dict(tool='finish', arguments={}))
    return dict(selection=selection, actions=plan)


if __name__ == '__main__':
    print(json.dumps(actions(json.loads(sys.stdin.read())), sort_keys=True, allow_nan=False))
