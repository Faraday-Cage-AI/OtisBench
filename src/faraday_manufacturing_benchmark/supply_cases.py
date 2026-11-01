"""Synthetic procurement/supply-chain contracts. No customer or provider data.

Each family has four explicitly different operating conditions, not just renamed
records. Public contracts specify business rules; reference solutions live in a
separate evaluator module and are never sent to an agent.
"""
from copy import deepcopy
import hashlib
import random

FAMILIES={}

def register(family,domain,goal,policy,fields,builder):
    FAMILIES[family]=dict(domain=domain,goal=goal,policy=policy,fields=fields,builder=builder)

def suppliers(rng):
    return [dict(id=f'SUP-{i}',unit_cents=p,capacity_units=c,lead_days=d,approved=True,blocked=False)
            for i,p,c,d in [(1,90,120,4),(2,110,180,2),(3,70,200,8)]]

def sourcing(rng,v):
    rows=suppliers(rng);n=[100,200,140,120][v]
    if v==2:rows[0]['blocked']=True;rows[2]['lead_days']=3
    if v==3:rows[0]['capacity_units']=80;rows[2]['approved']=False
    return dict(required_units=n,due_day=5,suppliers=rows)
register('source_award','sourcing','Award the complete requirement to one eligible supplier or record no feasible award.',
 'Supplier must be approved, unblocked, have enough capacity and arrive by due_day. Minimize quantity*unit_cents; break ties by supplier ID. If none qualifies, supplier_id and total_cents are null and units is zero.',
 {'supplier_id':'nullable_string','units':'integer','total_cents':'nullable_integer'},sourcing)

def split(rng,v):
    x=sourcing(rng,0);x['required_units']=[200,270,350,180][v];x['maximum_share_percent']=70
    x['suppliers'][2]['lead_days']=3
    if v==2:x['suppliers'][1]['blocked']=True
    if v==3:x['suppliers'][0]['unit_cents']=70
    return x
register('dual_source_allocation','sourcing','Allocate an exact requirement across suppliers under a concentration limit.',
 'Use only approved, unblocked, on-time suppliers. Integer allocations in supplier list order must sum to required_units, fit capacities, and each be <= floor(required_units*maximum_share_percent/100). Minimize cost, then lexicographically smallest allocation vector. Return [] and null cost if infeasible.',
 {'allocation_units':'integer_array','total_cents':'nullable_integer'},split)

def landed(rng,v):
    return dict(required_units=[120,250,80,300][v],fx_microusd_per_currency=[1100000,1300000,900000,1100000][v],
                domestic_unit_cents=130,import_unit_foreign_cents=80,freight_cents=2000,insurance_cents=300,duty_basis_points=500,
                importer_qualified=v!=3)
register('landed_cost_award','sourcing','Choose the less expensive qualified domestic or imported purchase.',
 'Convert the total foreign goods value to USD cents, rounding up once. Duty is ceil(converted goods*duty_basis_points/10000). Import landed cost adds freight and insurance; domestic cost is units*domestic_unit_cents. Compare only qualified options; domestic wins ties. Report goods_usd_cents and duty_cents for the selected source; domestic duty is zero.',
 {'source':'string','goods_usd_cents':'integer','duty_cents':'integer','total_cents':'integer'},landed)

def breaks(rng,v):
    return dict(required_units=[95,101,190,51][v],minimum_units=50,pack_units=10,maximum_units=[250,250,200,90][v],
        excess_unit_cost_cents=[0,40,90,25][v],tiers=[dict(minimum_units=0,unit_cents=120),dict(minimum_units=100,unit_cents=100),dict(minimum_units=200,unit_cents=85)])
register('quantity_break_buy','purchasing','Choose a pack-multiple purchase quantity accounting for all-units discounts and excess stock.',
 'Buy at least demand and MOQ, at most maximum_units. All units receive the tier with the greatest applicable minimum_units. Minimize invoice cost plus (buy-required)*excess_unit_cost_cents, then smaller quantity. If infeasible return null quantities and costs.',
 {'buy_units':'nullable_integer','invoice_cents':'nullable_integer','objective_cents':'nullable_integer'},breaks)

def packs(rng,v):
    return dict(gross_need_units=[135,240,80,340][v],released_onhand_units=40,held_units=100,confirmed_inbound_units=[20,0,60,20][v],safety_units=15,minimum_units=50,pack_units=24)
register('moq_pack_netting','purchasing','Net a material requirement and create a minimum-order, pack-compliant buy.',
 'Net=max(0,gross need+safety-released onhand-confirmed inbound). Held stock cannot offset need. If net is zero buy zero; otherwise round max(net,MOQ) up to packs.',
 {'net_units':'integer','buy_units':'integer','packs':'integer'},packs)

def blanket(rng,v):
    return dict(required_units=[80,220,100,60][v],contract_units=500,released_units=[350,350,450,440][v],contract_spend_cents=50000,spent_cents=35000,unit_cents=100,expiry_day=20,release_day=[10,10,10,21][v],pack_units=10)
register('blanket_release','purchasing','Release against a blanket agreement only within remaining quantity, value and validity.',
 'Required quantity is indivisible. Release only if it is pack compliant, the release day is no later than expiry, and remaining units and spend both cover it. Otherwise release zero and set escalate true. Report remaining contract units after this action.',
 {'release_units':'integer','cost_cents':'integer','remaining_units':'integer','escalate':'boolean'},blanket)

def amend(rng,v):
    return dict(original_units=200,received_units=[80,120,80,80][v],requested_total_units=[150,100,240,150][v],unit_cents=100,change_fee_cents=1500,approval_limit_cents=[25000,25000,25000,10000][v])
register('po_amendment','purchasing','Amend a purchase order without canceling already received units or exceeding delegated value.',
 'A new total below received quantity is invalid. Commitment=new total*unit price+change fee, including sunk receipts. Approve only within approval_limit_cents. On rejection retain original quantity, open quantity and original commitment with no change fee.',
 {'approved':'boolean','total_units':'integer','open_units':'integer','commitment_cents':'integer'},amend)

def expedite(rng,v):
    return dict(required_units=[100,130,100,100][v],due_day=[5,3,5,5][v],stock_units=20,options=[dict(id='LANE-1',arrival_day=7,capacity_units=200,unit_cents=90,fixed_cents=0,qualified=True),dict(id='LANE-2',arrival_day=3,capacity_units=100,unit_cents=110,fixed_cents=2000,qualified=v!=2),dict(id='LANE-3',arrival_day=4,capacity_units=150,unit_cents=120,fixed_cents=1000,qualified=True)],budget_cents=[20000,20000,20000,8000][v])
register('expedite_recovery','supply_planning','Recover a material shortage using a qualified on-time lane within the recovery budget.',
 'Shortage=max(0,required-stock). Choose one qualified lane with enough capacity and arrival<=due; cost=shortage*unit_cents+fixed_cents must fit budget. Minimize cost then lane ID. If none, lane_id null and cost null; report unresolved shortage.',
 {'lane_id':'nullable_string','purchase_units':'integer','cost_cents':'nullable_integer','unresolved_units':'integer'},expedite)

def transfer(rng,v):
    return dict(required_units=[60,120,40,180][v],destination_stock=10,due_day=4,plants=[dict(id='PLANT-1',released_units=80,reserved_units=20,safety_units=10,transit_days=2,transfer_cents_unit=30),dict(id='PLANT-2',released_units=100,reserved_units=10,safety_units=20,transit_days=[3,3,5,3][v],transfer_cents_unit=20)])
register('interplant_transfer','network_planning','Transfer stock without consuming donor reservations or safety stock.',
 'Available donor units=max(0,released-reserved-safety); ignore donors arriving after due_day. In integer units minimize unresolved shortage first, then transfer cost, then lexicographic allocation in plant order. Never exceed destination shortage.',
 {'transfer_units':'integer_array','cost_cents':'integer','unresolved_units':'integer'},transfer)

def reorder(rng,v):
    return dict(mean_units_day=20,sigma_units_day=[4,12,4,4][v],lead_days=[5,5,10,5][v],service_z=1.65,onhand_units=70,open_po_units=[100,0,100,100][v],backorder_units=[0,0,0,120][v],order_up_to_units=300,pack_units=20)
register('reorder_safety_stock','inventory_planning','Compute safety stock, reorder point and a pack-compliant replenishment.',
 'Assume independent daily demand and constant lead time. Safety=ceil(z*sigma*sqrt(lead days)); ROP=ceil(mean*lead+safety). Position=onhand+open POs-backorders. Reorder if position<=ROP, up to order_up_to rounded to packs; otherwise zero.',
 {'safety_units':'integer','reorder_point_units':'integer','inventory_position_units':'integer','buy_units':'integer'},reorder)

def mrp(rng,v):
    return dict(opening_units=30,demand_units=[[40,10,60,20],[0,90,0,90],[20,20,20,20],[100,0,0,0]][v],scheduled_receipts_units=[0,40,0,0],safety_units=10,pack_units=25,lead_periods=[1,2,1,3][v])
register('time_phased_netting','supply_planning','Create time-phased replenishment without treating late receipts as opening stock.',
 'At each zero-based period receive scheduled supply, then consume demand. If below safety, add the smallest pack-multiple receipt restoring safety. Release period=receipt period-lead; retain negative periods to expose past-due releases. Return release_periods only for nonzero planned receipts, in receipt-period order.',
 {'projected_units':'integer_array','receipts_units':'integer_array','release_periods':'integer_array'},mrp)

def receive(rng,v):
    return dict(ordered_units=100,previously_received_units=[20,20,20,90][v],arrival_units=[75,90,75,15][v],damaged_units=[5,5,0,0][v],certificate_valid=v!=2,overreceipt_tolerance_units=5)
register('receiving_disposition','receiving','Post accepted and quarantined quantities without inflating conforming stock.',
 'If arrival exceeds remaining PO plus tolerance, reject the entire arrival with zero accepted and quarantine units. Otherwise physical receipt=arrival; if certificate invalid quarantine all, else quarantine damaged units. Accept remaining; open PO=max(0,ordered-previous-physical receipt).',
 {'accept_units':'integer','quarantine_units':'integer','reject_units':'integer','open_po_units':'integer'},receive)

def fefo(rng,v):
    return dict(required_units=[60,100,30,60][v],use_day=[10,10,16,10][v],minimum_remaining_days=[3,3,3,8][v],lots=[dict(id='LOT-1',units=40,expiry_day=15,status='released'),dict(id='LOT-2',units=80,expiry_day=30,status='hold'),dict(id='LOT-3',units=35,expiry_day=20,status='released')])
register('shelf_life_allocation','inventory_execution','Allocate eligible inventory by expiry while meeting customer remaining-life rules.',
 'Eligible lots are released with expiry_day-use_day>=minimum_remaining_days. Allocate by earliest expiry then lot ID. Each allocation is an object with lot_id and units. Return allocations in that order, omitting zeros, and the shortage.',
 {'allocations':'allocation_array','shortage_units':'integer'},fefo)

def count(rng,v):
    return dict(book_units=120,count_one_units=[110,110,110,110][v],count_two_units=[110,109,110,110][v],unit_cents=[100,100,300,100][v],adjustment_limit_cents=1500,transactions_open=v==3)
register('cycle_count_adjustment','inventory_execution','Reconcile a blind cycle count under financial and transaction-freeze controls.',
 'Post counted-book only when both counts agree, no transactions remain open, and absolute adjustment value<=limit. Otherwise post zero, keep book quantity, escalate true.',
 {'adjustment_units':'integer','adjustment_value_cents':'integer','ending_units':'integer','escalate':'boolean'},count)

def match(rng,v):
    return dict(po_units=100,po_unit_cents=100,accepted_units=[80,80,100,80][v],previously_invoiced_units=20,invoice_units=[60,70,80,60][v],invoice_unit_cents=[100,100,103,100][v],price_tolerance_basis_points=200,freight_cents=500,authorized_freight_cents=[500,500,500,0][v])
register('three_way_match','payables','Validate an invoice against accepted receipts, PO pricing and authorized freight.',
 'Hold if invoice quantity exceeds accepted less previously invoiced; if abs(invoice unit-PO unit)*10000 exceeds PO unit*price tolerance bps; or freight exceeds authorization. Report sorted reason codes freight, price, quantity. Pay zero when held; else units*invoice price+freight.',
 {'hold':'boolean','reasons':'string_array','pay_cents':'integer'},match)

def duplicate(rng,v):
    return dict(candidate=dict(supplier='SUP-1',number=[' inv-0042 ','INV0043','INV-0042','INV-0042'][v],amount_cents=[12000,12000,12000,13000][v],currency=['USD','USD','EUR','USD'][v]),existing=[dict(id='BILL-1',supplier='SUP-1',number='INV-0042',amount_cents=12000,currency='USD',status='posted'),dict(id='BILL-2',supplier='SUP-2',number='INV0043',amount_cents=12000,currency='USD',status='posted')])
register('duplicate_invoice','payables','Detect duplicate billing without conflating supplier identities or currencies.',
 'Normalize numbers by stripping whitespace, hyphens and case. Exact duplicate requires same supplier, normalized number, currency and amount on a nonvoid record. Same supplier/number/currency with different amount is a conflict. Return sorted existing IDs; either condition holds payment.',
 {'duplicate_ids':'string_array','conflict_ids':'string_array','hold':'boolean'},duplicate)

def freight(rng,v):
    return dict(lost_units=[12,12,30,12][v],damaged_units=[3,3,5,3][v],unit_value_cents=800,carrier_cap_cents=[20000,6000,20000,20000][v],deductible_cents=1000,claim_day=[10,10,10,40][v],deadline_day=30,proof_available=v!=2)
register('freight_claim','logistics_finance','File a supported loss claim within the contractual deadline.',
 'Loss=(lost+damaged)*unit value. Recoverable=max(0,min(loss,carrier cap)-deductible). File only with proof and claim day<=deadline; otherwise claim zero. Report gross loss regardless.',
 {'file_claim':'boolean','loss_cents':'integer','claim_cents':'integer'},freight)

def returns(rng,v):
    return dict(rejected_units=20,unit_cents=500,authorization_valid=v!=1,within_window=v!=2,restocking_basis_points=[0,0,0,1500][v],return_freight_cents=1200)
register('supplier_return','supplier_quality','Authorize a supplier return and reconcile its net recovery.',
 'Return all rejected units only if authorization is valid and within window. Credit is units*price minus ceil(gross*restocking bps/10000), net recovery=credit-return freight. If not authorized, return and recover zero and escalate.',
 {'return_units':'integer','credit_cents':'integer','net_recovery_cents':'integer','escalate':'boolean'},returns)

def recall(rng,v):
    return dict(suspect_lots=[['RAW-1'],['RAW-2'],['RAW-1','RAW-2'],['RAW-X']][v],edges=[dict(parent='RAW-1',child='WIP-1'),dict(parent='WIP-1',child='FG-1'),dict(parent='RAW-2',child='FG-2'),dict(parent='FG-1',child='KIT-1')],shipments=[dict(id='SHIP-1',lot='KIT-1',units=10),dict(id='SHIP-2',lot='FG-2',units=20),dict(id='SHIP-3',lot='FG-1',units=5)],onhand=[dict(lot='FG-1',units=8),dict(lot='FG-2',units=12)])
register('supplier_recall_scope','traceability','Contain a supplier recall through all downstream transformations and shipments.',
 'Compute transitive closure including suspect sources. Return sorted affected lot IDs, sorted affected shipment IDs, affected shipped units, and affected onhand units. Unconnected lots and shipments must stay outside scope.',
 {'hold_lots':'string_array','notify_shipments':'string_array','shipped_units':'integer','quarantine_units':'integer'},recall)

def mode(rng,v):
    return dict(weight_kg=[120,120,300,120][v],deadline_hours=[24,8,24,24][v],requires_cold=v==2,budget_cents=[20000,20000,20000,4000][v],lanes=[dict(id='LANE-1',hours=48,fixed_cents=1000,cents_kg=10,cold=True,capacity_kg=1000),dict(id='LANE-2',hours=20,fixed_cents=2000,cents_kg=30,cold=False,capacity_kg=500),dict(id='LANE-3',hours=6,fixed_cents=5000,cents_kg=50,cold=True,capacity_kg=250)])
register('transport_mode','transportation','Book a feasible transport mode under delivery, temperature, weight and cost constraints.',
 'Choose a lane arriving by deadline, covering weight, supporting cold if required, and within budget. Cost=fixed+weight*cents_kg. Minimize cost then lane ID. If none return null lane and cost and escalate true.',
 {'lane_id':'nullable_string','cost_cents':'nullable_integer','escalate':'boolean'},mode)

def containers(rng,v):
    return dict(units=[110,200,30,110][v],unit_weight_kg=12,unit_volume_liters=[40,40,400,40][v],container_weight_kg=1000,container_volume_liters=4000,container_cents=8000,maximum_containers=[4,4,4,1][v])
register('container_capacity','transportation','Book containers respecting both payload and cubic capacity.',
 'No geometry constraint beyond volume. Units per container=min(floor(weight limit/unit weight),floor(volume limit/unit volume)). Containers=ceil(units/capacity). Book only if within maximum_containers; otherwise book zero and expose all units as unshipped.',
 {'units_per_container':'integer','book_containers':'integer','cost_cents':'integer','unshipped_units':'integer'},containers)

def otif(rng,v):
    return dict(orders=[dict(id='PO-1',ordered=100,due_day=10,received=100,receipt_day=9),dict(id='PO-2',ordered=80,due_day=10,received=[80,70,80,0][v],receipt_day=[12,9,10,9][v]),dict(id='PO-3',ordered=50,due_day=12,received=50,receipt_day=12)],minimum_otif_fraction=.8)
register('supplier_otif','supplier_performance','Reconcile supplier on-time/in-full performance at the order level.',
 'An order passes only if received>=ordered and receipt_day<=due_day. OTIF=passing orders/all orders. Late units=sum received on late orders; short units=sum max(0,ordered-received). Escalate if OTIF<minimum.',
 {'otif_fraction':'number','late_units':'integer','short_units':'integer','escalate':'boolean'},otif)

def carbon(rng,v):
    x=sourcing(rng,0);x['required_units']=100;x['maximum_carbon_kg']=[150,80,50,150][v]
    for s,co2 in zip(x['suppliers'],[2,1,.5]):s['carbon_kg_unit']=co2;s['lead_days']=3
    if v==2:x['suppliers'][2]['blocked']=True
    if v==3:x['suppliers'][2]['unit_cents']=140
    return x
register('carbon_constrained_award','sourcing','Award a purchase within an explicit embodied-carbon budget and delivery constraints.',
 'Choose one approved, unblocked, on-time supplier with capacity>=required and required*carbon_kg_unit<=maximum_carbon_kg. Minimize purchase cost, then supplier ID. If infeasible all outputs null.',
 {'supplier_id':'nullable_string','total_cents':'nullable_integer','carbon_kg':'nullable_number'},carbon)

def substitute(rng,v):
    return dict(required_units=80,build_day=[10,10,20,10][v],required_grade='G2',alternates=[dict(id='PART-1',grade='G2',approved_from=5,approved_until=15,stock=100,unit_cents=120,customer_approved=v!=1),dict(id='PART-2',grade='G1',approved_from=0,approved_until=30,stock=200,unit_cents=70,customer_approved=True),dict(id='PART-3',grade='G2',approved_from=5,approved_until=30,stock=[60,100,100,60][v],unit_cents=[130,130,130,100][v],customer_approved=True)])
register('alternate_effectivity','engineering_supply','Select an approved substitute valid for the build date, material grade and quantity.',
 'Use one alternate with matching grade, customer approval, sufficient stock and inclusive effectivity window. Minimize required*unit cost, then part ID. If none, part_id/cost null and shortage=required.',
 {'part_id':'nullable_string','cost_cents':'nullable_integer','shortage_units':'integer'},substitute)


def catalog():
    tasks=[]
    for family,spec in FAMILIES.items():
        for variant in range(4):
            tid=f'supply-{family}-{variant+1:03}'
            seed=int.from_bytes(hashlib.sha256(tid.encode()).digest()[:8],'big')
            inputs=spec['builder'](random.Random(seed),variant)
            tasks.append(dict(id=tid,family=family,domain=spec['domain'],variant=variant,
                provenance='synthetic-authored',goal=spec['goal'],policy=spec['policy'],
                fields=deepcopy(spec['fields']),inputs=inputs,systems=['ERP','SCM','WMS','QMS','AP','TMS'],
                max_tool_calls=40,horizon_minutes=100))
    return tasks
