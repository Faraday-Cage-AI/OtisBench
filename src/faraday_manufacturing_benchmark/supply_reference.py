"""Evaluator-only supply-chain reference calculations; never imported by views.

Closed-world arithmetic contracts, not legal/commercial recommendations. Reference
outputs are used after the episode, never to fill an agent's proposed transaction.
"""
import itertools
import math


def ceil_div(a,b):return (a+b-1)//b

def eligible(s,n,due):return s['approved'] and not s['blocked'] and s['capacity_units']>=n and s['lead_days']<=due

def solve(f,x):
    if f in ('source_award','carbon_constrained_award'):
        n=x['required_units'];rows=[s for s in x['suppliers'] if eligible(s,n,x['due_day'])]
        if f=='carbon_constrained_award':rows=[s for s in rows if n*s['carbon_kg_unit']<=x['maximum_carbon_kg']]
        best=min(rows,key=lambda s:(n*s['unit_cents'],s['id'])) if rows else None
        if f=='source_award':return dict(supplier_id=best['id'] if best else None,units=n if best else 0,total_cents=n*best['unit_cents'] if best else None)
        return dict(supplier_id=best['id'] if best else None,total_cents=n*best['unit_cents'] if best else None,carbon_kg=n*best['carbon_kg_unit'] if best else None)
    if f=='dual_source_allocation':
        n=x['required_units'];rows=x['suppliers'];cap=n*x['maximum_share_percent']//100
        limits=[min(cap,s['capacity_units']) if s['approved'] and not s['blocked'] and s['lead_days']<=x['due_day'] else 0 for s in rows]
        best=None
        # Enumerate all but the last allocation; the last is fixed by conservation.
        for prefix in itertools.product(*(range(c+1) for c in limits[:-1])):
            last=n-sum(prefix)
            if not 0<=last<=limits[-1]:continue
            allocation=(*prefix,last);key=(sum(q*s['unit_cents'] for q,s in zip(allocation,rows)),allocation)
            if best is None or key<best:best=key
        return dict(allocation_units=list(best[1]) if best else [],total_cents=best[0] if best else None)
    if f=='landed_cost_award':
        n=x['required_units'];goods=ceil_div(n*x['import_unit_foreign_cents']*x['fx_microusd_per_currency'],1000000)
        duty=ceil_div(goods*x['duty_basis_points'],10000);imported=goods+duty+x['freight_cents']+x['insurance_cents'];domestic=n*x['domestic_unit_cents']
        if x['importer_qualified'] and imported<domestic:return dict(source='import',goods_usd_cents=goods,duty_cents=duty,total_cents=imported)
        return dict(source='domestic',goods_usd_cents=domestic,duty_cents=0,total_cents=domestic)
    if f=='quantity_break_buy':
        choices=[]
        for n in range(ceil_div(max(x['required_units'],x['minimum_units']),x['pack_units'])*x['pack_units'],x['maximum_units']+1,x['pack_units']):
            tier=max((t for t in x['tiers'] if t['minimum_units']<=n),key=lambda t:t['minimum_units']);invoice=n*tier['unit_cents'];objective=invoice+(n-x['required_units'])*x['excess_unit_cost_cents'];choices.append((objective,n,invoice))
        if not choices:return dict(buy_units=None,invoice_cents=None,objective_cents=None)
        objective,n,invoice=min(choices);return dict(buy_units=n,invoice_cents=invoice,objective_cents=objective)
    if f=='moq_pack_netting':
        net=max(0,x['gross_need_units']+x['safety_units']-x['released_onhand_units']-x['confirmed_inbound_units']);packs=ceil_div(max(net,x['minimum_units']),x['pack_units']) if net else 0
        return dict(net_units=net,buy_units=packs*x['pack_units'],packs=packs)
    if f=='blanket_release':
        n=x['required_units'];left=x['contract_units']-x['released_units'];cost=n*x['unit_cents'];ok=n%x['pack_units']==0 and x['release_day']<=x['expiry_day'] and n<=left and cost<=x['contract_spend_cents']-x['spent_cents']
        return dict(release_units=n if ok else 0,cost_cents=cost if ok else 0,remaining_units=left-(n if ok else 0),escalate=not ok)
    if f=='po_amendment':
        commitment=x['requested_total_units']*x['unit_cents']+x['change_fee_cents'];ok=x['requested_total_units']>=x['received_units'] and commitment<=x['approval_limit_cents'];n=x['requested_total_units'] if ok else x['original_units']
        return dict(approved=ok,total_units=n,open_units=n-x['received_units'],commitment_cents=commitment if ok else n*x['unit_cents'])
    if f=='expedite_recovery':
        n=max(0,x['required_units']-x['stock_units']);choices=[(n*s['unit_cents']+s['fixed_cents'],s['id']) for s in x['options'] if s['qualified'] and s['capacity_units']>=n and s['arrival_day']<=x['due_day'] and n*s['unit_cents']+s['fixed_cents']<=x['budget_cents']]
        cost,lane=min(choices) if choices else (None,None)
        return dict(lane_id=lane,purchase_units=n if choices else 0,cost_cents=cost,unresolved_units=0 if choices else n)
    if f=='interplant_transfer':
        shortage=max(0,x['required_units']-x['destination_stock']);plants=x['plants'];caps=[max(0,p['released_units']-p['reserved_units']-p['safety_units']) if p['transit_days']<=x['due_day'] else 0 for p in plants]
        candidates=[]
        for a in itertools.product(*(range(min(c,shortage)+1) for c in caps)):
            if sum(a)<=shortage:candidates.append((shortage-sum(a),sum(q*p['transfer_cents_unit'] for q,p in zip(a,plants)),a))
        unfilled,cost,a=min(candidates);return dict(transfer_units=list(a),cost_cents=cost,unresolved_units=unfilled)
    if f=='reorder_safety_stock':
        safety=math.ceil(x['service_z']*x['sigma_units_day']*math.sqrt(x['lead_days']));rop=math.ceil(x['mean_units_day']*x['lead_days']+safety);position=x['onhand_units']+x['open_po_units']-x['backorder_units'];buy=ceil_div(max(0,x['order_up_to_units']-position),x['pack_units'])*x['pack_units'] if position<=rop else 0
        return dict(safety_units=safety,reorder_point_units=rop,inventory_position_units=position,buy_units=buy)
    if f=='time_phased_netting':
        stock=x['opening_units'];projection=[];receipts=[];releases=[]
        for i,(d,s) in enumerate(zip(x['demand_units'],x['scheduled_receipts_units'])):
            stock+=s-d;n=ceil_div(max(0,x['safety_units']-stock),x['pack_units'])*x['pack_units'];stock+=n
            projection.append(stock);receipts.append(n)
            if n:releases.append(i-x['lead_periods'])
        return dict(projected_units=projection,receipts_units=receipts,release_periods=releases)
    if f=='receiving_disposition':
        arrival=x['arrival_units'];remaining=x['ordered_units']-x['previously_received_units']
        if arrival>remaining+x['overreceipt_tolerance_units']:return dict(accept_units=0,quarantine_units=0,reject_units=arrival,open_po_units=remaining)
        held=x['damaged_units'] if x['certificate_valid'] else arrival
        return dict(accept_units=arrival-held,quarantine_units=held,reject_units=0,open_po_units=max(0,remaining-arrival))
    if f=='shelf_life_allocation':
        left=x['required_units'];a=[]
        for lot in sorted(x['lots'],key=lambda l:(l['expiry_day'],l['id'])):
            if lot['status']!='released' or lot['expiry_day']-x['use_day']<x['minimum_remaining_days']:continue
            n=min(left,lot['units'])
            if n:a.append(dict(lot_id=lot['id'],units=n));left-=n
        return dict(allocations=a,shortage_units=left)
    if f=='cycle_count_adjustment':
        delta=x['count_one_units']-x['book_units'];ok=x['count_one_units']==x['count_two_units'] and not x['transactions_open'] and abs(delta*x['unit_cents'])<=x['adjustment_limit_cents']
        return dict(adjustment_units=delta if ok else 0,adjustment_value_cents=delta*x['unit_cents'] if ok else 0,ending_units=x['count_one_units'] if ok else x['book_units'],escalate=not ok)
    if f=='three_way_match':
        reasons=[]
        if x['freight_cents']>x['authorized_freight_cents']:reasons.append('freight')
        if abs(x['invoice_unit_cents']-x['po_unit_cents'])*10000>x['po_unit_cents']*x['price_tolerance_basis_points']:reasons.append('price')
        if x['invoice_units']>x['accepted_units']-x['previously_invoiced_units']:reasons.append('quantity')
        return dict(hold=bool(reasons),reasons=reasons,pay_cents=0 if reasons else x['invoice_units']*x['invoice_unit_cents']+x['freight_cents'])
    if f=='duplicate_invoice':
        def norm(n):return ''.join(c for c in n.upper() if not c.isspace() and c!='-')
        c=x['candidate'];dups=[];conflicts=[]
        for r in x['existing']:
            if r['status']=='void' or r['supplier']!=c['supplier'] or r['currency']!=c['currency'] or norm(r['number'])!=norm(c['number']):continue
            (dups if r['amount_cents']==c['amount_cents'] else conflicts).append(r['id'])
        return dict(duplicate_ids=sorted(dups),conflict_ids=sorted(conflicts),hold=bool(dups or conflicts))
    if f=='freight_claim':
        loss=(x['lost_units']+x['damaged_units'])*x['unit_value_cents'];ok=x['proof_available'] and x['claim_day']<=x['deadline_day']
        return dict(file_claim=ok,loss_cents=loss,claim_cents=max(0,min(loss,x['carrier_cap_cents'])-x['deductible_cents']) if ok else 0)
    if f=='supplier_return':
        ok=x['authorization_valid'] and x['within_window'];gross=x['rejected_units']*x['unit_cents'];credit=gross-ceil_div(gross*x['restocking_basis_points'],10000)
        return dict(return_units=x['rejected_units'] if ok else 0,credit_cents=credit if ok else 0,net_recovery_cents=credit-x['return_freight_cents'] if ok else 0,escalate=not ok)
    if f=='supplier_recall_scope':
        lots=set(x['suspect_lots'])
        while True:
            expanded=lots|{e['child'] for e in x['edges'] if e['parent'] in lots}
            if expanded==lots:break
            lots=expanded
        shipments=[s for s in x['shipments'] if s['lot'] in lots]
        return dict(hold_lots=sorted(lots),notify_shipments=sorted(s['id'] for s in shipments),shipped_units=sum(s['units'] for s in shipments),quarantine_units=sum(l['units'] for l in x['onhand'] if l['lot'] in lots))
    if f=='transport_mode':
        lanes=[(l['fixed_cents']+x['weight_kg']*l['cents_kg'],l['id']) for l in x['lanes'] if l['hours']<=x['deadline_hours'] and l['capacity_kg']>=x['weight_kg'] and (not x['requires_cold'] or l['cold']) and l['fixed_cents']+x['weight_kg']*l['cents_kg']<=x['budget_cents']]
        cost,lane=min(lanes) if lanes else (None,None);return dict(lane_id=lane,cost_cents=cost,escalate=not bool(lanes))
    if f=='container_capacity':
        cap=min(x['container_weight_kg']//x['unit_weight_kg'],x['container_volume_liters']//x['unit_volume_liters']);need=ceil_div(x['units'],cap) if cap else x['maximum_containers']+1;ok=need<=x['maximum_containers']
        return dict(units_per_container=cap,book_containers=need if ok else 0,cost_cents=need*x['container_cents'] if ok else 0,unshipped_units=0 if ok else x['units'])
    if f=='supplier_otif':
        rows=x['orders'];rate=sum(r['received']>=r['ordered'] and r['receipt_day']<=r['due_day'] for r in rows)/len(rows)
        return dict(otif_fraction=rate,late_units=sum(r['received'] for r in rows if r['receipt_day']>r['due_day']),short_units=sum(max(0,r['ordered']-r['received']) for r in rows),escalate=rate<x['minimum_otif_fraction'])
    if f=='alternate_effectivity':
        rows=[p for p in x['alternates'] if p['grade']==x['required_grade'] and p['customer_approved'] and p['stock']>=x['required_units'] and p['approved_from']<=x['build_day']<=p['approved_until']]
        best=min(rows,key=lambda p:(p['unit_cents'],p['id'])) if rows else None
        return dict(part_id=best['id'] if best else None,cost_cents=x['required_units']*best['unit_cents'] if best else None,shortage_units=0 if best else x['required_units'])
    raise ValueError('unknown supply-chain family: '+f)
