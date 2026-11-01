"""Independent trace ledger for the factory-season simulator.

Reconstructs stock, pipeline, backlog, capacity and cash from posted trace rows.
It does not call FactorySeason.step/result/value/capacity helpers. Constants and
committed exogenous observations are explicit verifier inputs, not agent inputs.
"""
from copy import deepcopy
from decimal import Decimal,ROUND_HALF_EVEN
import math


def rounded(value):return int(Decimal(str(value)).quantize(Decimal('1'),rounding=ROUND_HALF_EVEN))


def _audit_trace(case,draw,trace,reported,*,products,materials,policy,exogenous):
    errors=[]
    def check(passed,label):
        if not passed:errors.append(label)
    def standard(product):
        p=products[product]
        return p['conversion_cents']+sum(materials[m]['unit_cents']*n for m,n in p['bom'].items())
    def raw_value(raw):return sum(materials[m]['unit_cents']*n for m,n in raw.items())
    def fg_value(fg):return sum(standard(p)*n for p,n in fg.items())
    raw=dict(CAST=90,MOTOR=65,SEAL=250,PCB=85);fg={p:10 for p in products};cash=case.opening_cash_cents;pipeline=[];backlog=[]
    costs={k:0 for k in ('procurement','conversion','maintenance','holding','backlog','freight')};sales=shipped=cancelled=scrap=0
    last={c:None for c in ('mill','assembly','test')};service={c:-1 for c in last}
    initial=cash+raw_value(raw)+fg_value(fg)
    check(len(trace)==case.weeks,'complete season length')
    check(len(exogenous)==case.weeks,'complete committed exogenous horizon')
    for week,row in enumerate(trace):
        check(row['week']==week,f'week {week}: chronology')
        event=exogenous[week];action=deepcopy(row['action']);spent=0
        if not isinstance(action,dict):action={}
        for key,kind in [('purchase_packs',dict),('expedite',list),('maintain',list)]:
            if not isinstance(action.get(key,kind()),kind):action[key]=kind()
        for po in row['purchases']:
            material=po['material'];units=po['units'];pack=materials[material]['pack_units'];packs=units//pack
            check(units>0 and units%pack==0,f'week {week}: whole purchase packs')
            expected_packs=action.get('purchase_packs',{}).get(material)
            check(type(expected_packs) is int and packs==expected_packs,f'week {week}: purchase action quantity')
            increase=Decimal('1.18') if case.mode in ('inflation','combined') and week>=10 else Decimal(1)
            price=rounded(Decimal(materials[material]['unit_cents'])*increase)
            amount=units*price;freight=packs*policy['expedited_freight_cents_pack'] if material in action.get('expedite',[]) else 0
            check(po['value_cents']==amount,f'week {week}: purchase valuation')
            check(spent+amount+freight<=case.budget_cents and amount+freight<=cash,f'week {week}: purchasing cash/budget')
            lead=max(1,materials[material]['lead_weeks']+event['delay'][material]-(1 if material in action.get('expedite',[]) else 0))
            check(po['due_week']==week+lead,f'week {week}: purchase lead time')
            spent+=amount+freight;cash-=amount+freight;costs['procurement']+=amount;costs['freight']+=freight;pipeline.append(deepcopy(po))
        for receipt in row['receipts']:
            check(receipt in pipeline and receipt['due_week']<=week,f'week {week}: receipt provenance/due date')
            if receipt in pipeline:pipeline.remove(receipt)
            raw[receipt['material']]+=receipt['units']
        check(all(p['due_week']>week for p in pipeline),f'week {week}: all due receipts posted')
        def capacities():
            capacity={c:rounded(Decimal(n)*Decimal(str(case.capacity_scale))) for c,n in dict(mill=900,assembly=1250,test=850).items()}
            if case.mode in ('maintenance','combined') and 10<=week<=12:
                factor=Decimal('.95') if service['mill']>=week else Decimal('.45')
                capacity['mill']=rounded(Decimal(capacity['mill'])*factor)
            return capacity
        capacity=capacities()
        check(len(set(row['maintenance']))==len(row['maintenance']),f'week {week}: maintenance posted once per center')
        for center in row['maintenance']:
            check(center in action.get('maintain',[]) and cash>=policy['maintenance_cents'] and capacity[center]>=policy['maintenance_minutes'],f'week {week}: maintenance authorization/cash/capacity')
            cash-=policy['maintenance_cents'];costs['maintenance']+=policy['maintenance_cents'];service[center]=week+3
            capacity[center]=capacities()[center]-policy['maintenance_minutes']
        requested=action.get('jobs',[])
        if not isinstance(requested,list):requested=[]
        cursor=0
        for job in row['jobs']:
            product=job['product'];n=job['started_units'];p=products[product]
            check(type(n) is int and 0<n<=1000,f'week {week}: positive integer production starts')
            matched=next((i for i in range(cursor,min(len(requested),policy['max_jobs_week'])) if requested[i]==dict(product=product,units=n)),None)
            check(matched is not None,f'week {week}: job action provenance/order')
            if matched is not None:cursor=matched+1
            expected_use={c:n*minutes+(policy['setup_minutes'] if last[c]!=product else 0) for c,minutes in p['routing'].items()}
            check(job['used_minutes']==expected_use,f'week {week}: setup/routing minutes')
            check(all(capacity[c]>=n for c,n in expected_use.items()),f'week {week}: finite capacity')
            check(all(raw[m]>=n*need for m,need in p['bom'].items()),f'week {week}: material sufficiency')
            check(cash>=n*p['conversion_cents'],f'week {week}: conversion cash')
            good=math.floor(n*event['yields'][product]);check(job['good_units']==good and job['scrap_units']==n-good,f'week {week}: physical yield')
            for m,need in p['bom'].items():raw[m]-=n*need
            for center,minutes in expected_use.items():capacity[center]-=minutes;last[center]=product
            cash-=n*p['conversion_cents'];costs['conversion']+=n*p['conversion_cents'];fg[product]+=good;scrap+=n-good
        check(capacity==row['remaining_capacity_minutes'],f'week {week}: remaining capacity')
        for product,n in event['demand'].items():
            if n:backlog.append(dict(product=product,units=n,booked_week=week))
        expected_shipments=[]
        for order in list(backlog):
            product=order['product'];n=min(order['units'],fg[product]);fg[product]-=n;order['units']-=n
            revenue=n*products[product]['price_cents'];cash+=revenue;sales+=revenue;shipped+=n
            if n:expected_shipments.append(dict(product=product,units=n,booked_week=order['booked_week'],revenue_cents=revenue))
            if not order['units']:backlog.remove(order)
            elif week-order['booked_week']>=policy['cancel_after_weeks']:cancelled+=order['units'];backlog.remove(order)
        check(row['shipments']==expected_shipments,f'week {week}: oldest-order fulfillment/revenue')
        holding=rounded(Decimal(raw_value(raw)+fg_value(fg))*Decimal(policy['holding_bps_week'])/10000)
        backlog_charge=sum(o['units'] for o in backlog)*policy['backlog_cents_unit_week']
        costs['holding']+=holding;costs['backlog']+=backlog_charge;cash-=holding+backlog_charge
        check(cash==row['cash_cents'],f'week {week}: cash conservation')
        check(all(n>=0 for n in raw.values()) and all(n>=0 for n in fg.values()),f'week {week}: nonnegative stock')
    raw_salvage=rounded(Decimal(raw_value(raw))*Decimal(str(policy['terminal_raw_recovery_fraction'])))
    fg_salvage=rounded(Decimal(fg_value(fg))*Decimal(str(policy['terminal_fg_recovery_fraction'])))
    pipe_salvage=rounded(Decimal(sum(p['value_cents'] for p in pipeline))*Decimal(str(policy['terminal_raw_recovery_fraction'])))
    profit=cash+raw_salvage+fg_salvage+pipe_salvage-initial
    margin=sum(n*(products[p]['price_cents']-standard(p)) for event in exogenous for p,n in event['demand'].items())
    demand=sum(sum(event['demand'].values()) for event in exogenous)
    expected=dict(case_id=case.id,draw=draw,weeks=case.weeks,profit_cents=profit,demand_margin_cents=margin,score=100*profit/margin if margin else 0,
        shipped_units=shipped,demand_units=demand,fill_rate=shipped/demand if demand else 1,cancelled_units=cancelled,backlog_units=sum(o['units'] for o in backlog),scrap_units=scrap,
        sales_cents=sales,costs_cents=costs,terminal_raw_cents=raw_salvage,terminal_fg_cents=fg_salvage,terminal_pipeline_cents=pipe_salvage,initial_equity_cents=initial,final_cash_cents=cash,
        rejected_actions=sum(len(row['rejected']) for row in trace))
    for key,value in expected.items():check(reported.get(key)==value,'terminal '+key)
    check(shipped+cancelled+sum(o['units'] for o in backlog)==demand,'demand unit conservation')
    check(cash==case.opening_cash_cents+sales-sum(costs.values()),'season cash conservation')
    return dict(passed=not errors,errors=errors,reconstructed=expected)


def audit_trace(*args,**kwargs):
    try:return _audit_trace(*args,**kwargs)
    except (KeyError,TypeError,ValueError,IndexError,ZeroDivisionError) as exc:
        return dict(passed=False,errors=['invalid trace or accounting input: '+type(exc).__name__],reconstructed=None)
