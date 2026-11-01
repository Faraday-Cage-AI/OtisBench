"""Shared supplier commitments, deposits and maintenance inventory for campaigns."""
from copy import deepcopy


class CampaignLogistics:
    dispatch_window_minutes = 480
    dispatch_capacity_units = 48
    expedited_capacity_units = 24
    deposit_percent = 20
    cancellation_fee_cents = 500
    spare_catalog = {
        'tooling_kit': dict(unit_cents=1200, pack_units=4),
        'repair_kit': dict(unit_cents=2500, pack_units=2),
    }

    def _init_logistics(self):
        self.prepaid_cents = 0
        self.allocations = {}
        self.initial_spares = {'tooling_kit': 2, 'repair_kit': 1}
        self.spares = deepcopy(self.initial_spares)
        self.spares_used = dict.fromkeys(self.spares, 0)
        self.spare_orders = {}

    def logistics_state(self):
        return dict(prepaid_cents=self.prepaid_cents, allocations=self.allocations,
                    spares=self.spares, spares_used=self.spares_used, spare_orders=self.spare_orders)

    def advance_logistics(self, minute):
        for allocation in self.allocations.values():
            if allocation['status'] == 'booked' and allocation['window_start'] + self.dispatch_window_minutes <= minute:
                # Committed deposits become a cost when an unused dispatch slot expires.
                allocation['status'] = 'expired'
                deposit = allocation['deposit_cents']
                self.prepaid_cents -= deposit
                self.spent_cents += deposit
                self.orders[allocation['work_order']].spent_cents += deposit
        for order in self.spare_orders.values():
            if order['status'] == 'in_transit' and order['due_minute'] <= minute:
                self.spares[order['kind']] += order['quantity']
                order['status'] = 'received'

    def _window_usage(self, start):
        rows = [a for a in self.allocations.values() if a['window_start'] == start and a['status'] in ('booked', 'used')]
        return sum(a['units'] for a in rows), sum(a['units'] for a in rows if a['expedited'])

    def _allocation_public(self, allocation, view):
        return dict(id=view.encode({'id': allocation['id']})['id'],
            work_order_id=view.encode({'id': allocation['work_order']})['id'], units=allocation['units'],
            expedited=allocation['expedited'], window_start=allocation['window_start'],
            window_end=allocation['window_start'] + self.dispatch_window_minutes,
            deposit_cents=allocation['deposit_cents'], status=allocation['status'])

    def _spare_public(self, row, view):
        return dict(id=view.encode({'id': row['id']})['id'], kind=row['kind'], quantity=row['quantity'],
                    due_minute=row['due_minute'], status=row['status'], cost_cents=row['cost_cents'])

    def public_logistics(self, view):
        windows = []
        current = self.clock // self.dispatch_window_minutes * self.dispatch_window_minutes
        for start in range(current, self.task['horizon_minutes'], self.dispatch_window_minutes):
            used, expedited = self._window_usage(start)
            windows.append(dict(start_minute=start, end_minute=start + self.dispatch_window_minutes,
                capacity_units=self.dispatch_capacity_units, allocated_units=used,
                expedited_capacity_units=self.expedited_capacity_units, expedited_allocated_units=expedited))
        orders = []
        for row in self.spare_orders.values():
            orders.append(self._spare_public(row, view))
        return dict(prepaid_cents=self.prepaid_cents, supplier_capacity=dict(windows=windows,
            deposit_percent=self.deposit_percent, cancellation_fee_cents=self.cancellation_fee_cents,
            allocations=[self._allocation_public(a, view) for a in self.allocations.values()]),
            spare_inventory={kind:self.spares[kind] for kind in self.initial_spares}, spare_orders=orders,
            spare_quotes=dict(items={kind:dict(unit_cents=q['unit_cents'],pack_units=q['pack_units']) for kind,q in self.spare_catalog.items()}, standard_lead_minutes=180,
                              expedited_lead_minutes=60, expedite_cents=3500))

    def logistics_call(self, tool, arguments, view):
        def fail(code):
            return dict(ok=False, error=code, clock_minute=self.clock)
        if tool == 'reserve_supply':
            if set(arguments) != {'work_order_id', 'units', 'window_start', 'expedited'}:
                return fail('invalid_arguments')
            key, units, start, expedited = (arguments[k] for k in ('work_order_id', 'units', 'window_start', 'expedited'))
            owner = self.orders.get(key)
            if not owner or owner.finished or type(units) is not int or type(start) is not int or type(expedited) is not bool:
                return fail('invalid_arguments')
            if units < owner.records['SCM']['supplier']['minimum_units'] or units > self.dispatch_capacity_units:
                return fail('supplier_quantity_invalid')
            if start < 0 or start % self.dispatch_window_minutes or start >= self.task['horizon_minutes'] or start + self.dispatch_window_minutes <= self.clock:
                return fail('dispatch_window_invalid')
            used, express = self._window_usage(start)
            if used + units > self.dispatch_capacity_units or (expedited and express + units > self.expedited_capacity_units):
                return fail('supplier_capacity_exceeded')
            deposit = units * owner.records['SCM']['supplier']['unit_cents'] * self.deposit_percent // 100
            if self.cash_cents < deposit:
                return fail('cash_insufficient')
            self.cash_cents -= deposit
            self.prepaid_cents += deposit
            allocation_id = f'RES-SUP-{len(self.allocations) + 1:04}'
            row = dict(id=allocation_id, work_order=key, units=units, window_start=start,
                       expedited=expedited, deposit_cents=deposit, status='booked')
            self.allocations[allocation_id] = row
            return dict(ok=True, allocation=self._allocation_public(row, view), clock_minute=self.clock)
        if tool == 'cancel_supply':
            if set(arguments) != {'allocation_id'}:
                return fail('invalid_arguments')
            row = self.allocations.get(arguments['allocation_id'])
            if not row or row['status'] != 'booked':
                return fail('allocation_state_invalid')
            fee = min(self.cancellation_fee_cents, row['deposit_cents'])
            self.prepaid_cents -= row['deposit_cents']
            self.cash_cents += row['deposit_cents'] - fee
            self.spent_cents += fee
            self.orders[row['work_order']].spent_cents += fee
            row['status'] = 'cancelled'
            row['cancellation_fee_cents'] = fee
            return dict(ok=True, allocation=self._allocation_public(row, view), cost_cents=fee, clock_minute=self.clock)
        if tool == 'order_spares':
            if set(arguments) != {'kind', 'quantity', 'expedited'}:
                return fail('invalid_arguments')
            kind, quantity, expedited = (arguments[k] for k in ('kind', 'quantity', 'expedited'))
            if kind not in self.spare_catalog or type(quantity) is not int or type(expedited) is not bool:
                return fail('invalid_arguments')
            quote = self.spare_catalog[kind]
            if not 1 <= quantity <= 32 or quantity % quote['pack_units']:
                return fail('spare_pack_invalid')
            cost = quantity * quote['unit_cents'] + (3500 if expedited else 0)
            if not self._plant_spend(cost):
                return fail('funds_unavailable')
            key = f'PO-SPARES-{len(self.spare_orders) + 1:04}'
            row = dict(id=key, kind=kind, quantity=quantity, due_minute=self.clock + (60 if expedited else 180),
                       cost_cents=cost, status='in_transit')
            self.spare_orders[key] = row
            public = self._spare_public(row, view)
            return dict(ok=True, spare_order=public, clock_minute=self.clock)
        return None

    def allocation_for_purchase(self, owner, allocation_id, units, expedited):
        row = self.allocations.get(allocation_id) if isinstance(allocation_id, str) else None
        if not row or row['status'] != 'booked':
            return None, 'supply_allocation_required'
        if row['work_order'] != owner.key or row['units'] != units or row['expedited'] != expedited:
            return None, 'supply_allocation_mismatch'
        return row, None

    def logistics_check(self):
        if self.prepaid_cents != sum(a['deposit_cents'] for a in self.allocations.values() if a['status'] == 'booked'):
            return False
        for row in self.allocations.values():
            if row['status'] not in ('booked', 'used', 'cancelled', 'expired'):
                return False
            owner = self.orders.get(row['work_order'])
            if not owner:
                return False
            supplier = owner.records['SCM']['supplier']
            if row['deposit_cents'] != row['units'] * supplier['unit_cents'] * self.deposit_percent // 100:
                return False
            if row['status'] == 'used':
                po = owner.records['SCM']['purchase_orders'].get(row.get('purchase_order'))
                lead = supplier['expedited_lead_minutes' if row['expedited'] else 'standard_lead_minutes']
                if not po or po['units'] != row['units'] or po['due_minute'] != max(row['purchase_minute'], row['window_start']) + lead:
                    return False
            if row['status'] == 'booked' and row['window_start'] + self.dispatch_window_minutes <= self.clock:
                return False
        for start in {a['window_start'] for a in self.allocations.values()}:
            total, expedited = self._window_usage(start)
            if total > self.dispatch_capacity_units or expedited > self.expedited_capacity_units:
                return False
        for kind, opening in self.initial_spares.items():
            received = sum(p['quantity'] for p in self.spare_orders.values() if p['kind'] == kind and p['status'] == 'received')
            if self.spares[kind] < 0 or opening + received != self.spares[kind] + self.spares_used[kind]:
                return False
        return True
