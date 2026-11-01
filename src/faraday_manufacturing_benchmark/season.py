"""Long-horizon factory economics with common random numbers and exact cash accounting."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict,dataclass
import hashlib
import json
import math
import random


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


@dataclass(frozen=True)
class SeasonCase:
    id: str
    seed: int
    weeks: int=26
    demand_scale: float=1.0
    supply_risk: float=.15
    capacity_scale: float=1.0
    budget_cents: int=240000
    opening_cash_cents: int=1100000
    mode: str='mixed_model'


CASES=[
    SeasonCase('balanced-cell',9101),
    SeasonCase('supplier-crunch',9102,supply_risk=.5),
    SeasonCase('capacity-constrained',9103,capacity_scale=.72),
    SeasonCase('working-capital',9104,budget_cents=115000,opening_cash_cents=450000),
    SeasonCase('demand-step',9105,demand_scale=1.3),
    SeasonCase('quality-excursion',9106,mode='quality'),
    SeasonCase('end-of-life',9107,mode='eol'),
    SeasonCase('price-rise',9108,mode='inflation'),
    SeasonCase('maintenance-window',9109,mode='maintenance'),
    SeasonCase('customer-project',9110,mode='project'),
    SeasonCase('unit-conversion',9111,mode='packs'),
    SeasonCase('combined-recovery',9112,supply_risk=.35,capacity_scale=.85,mode='combined'),
]

PRODUCTS={
    'PUMP':dict(price_cents=18000,bom={'CAST':1,'MOTOR':1,'SEAL':2},routing={'mill':18,'assembly':25,'test':12},conversion_cents=2100),
    'VALVE':dict(price_cents=9000,bom={'CAST':1,'SEAL':1},routing={'mill':12,'assembly':15,'test':10},conversion_cents=1100),
    'DRIVE':dict(price_cents=14500,bom={'MOTOR':1,'PCB':1},routing={'assembly':22,'test':20},conversion_cents=1600),
    'KIT':dict(price_cents=4200,bom={'SEAL':3,'PCB':1},routing={'assembly':9,'test':6},conversion_cents=500),
}
MATERIALS={
    'CAST':dict(unit_cents=2400,pack_units=5,lead_weeks=2),
    'MOTOR':dict(unit_cents=3600,pack_units=4,lead_weeks=3),
    'SEAL':dict(unit_cents=180,pack_units=20,lead_weeks=1),
    'PCB':dict(unit_cents=900,pack_units=10,lead_weeks=2),
}
POLICY=dict(holding_bps_week=35,backlog_cents_unit_week=250,cancel_after_weeks=3,
            terminal_raw_recovery_fraction=.7,terminal_fg_recovery_fraction=.6,
            expedited_freight_cents_pack=800,maintenance_cents=18000,
            maintenance_minutes=120,setup_minutes=25,max_jobs_week=12)


def standard_cost(product):
    p=PRODUCTS[product]
    return sum(MATERIALS[k]['unit_cents']*v for k,v in p['bom'].items())+p['conversion_cents']


class FactorySeason:
    """All future demand, receipts and yields are committed before policy decisions."""
    def __init__(self,case:SeasonCase,draw:int=0):
        self.case=case; self.draw=draw
        self.materials=deepcopy(MATERIALS)
        if case.mode=='packs':
            for material,pack in dict(CAST=12,MOTOR=10,SEAL=144,PCB=25).items():self.materials[material]['pack_units']=pack
        rng=random.Random(f'{case.seed}:{draw}')
        self.exogenous=[]
        for w in range(case.weeks):
            demand={k:max(0,round(rng.gauss(mu,mu*.22)*case.demand_scale)) for k,mu in zip(PRODUCTS,[12,20,12,15])}
            if case.mode=='eol' and w>=16: demand['KIT']=0
            if case.id=='demand-step' and w>=10: demand['PUMP']=round(demand['PUMP']*1.6)
            if case.mode=='project' and w==12: demand['VALVE']+=65
            if case.mode=='combined' and 9<=w<=13: demand['DRIVE']+=15
            delayed={k:(2 if rng.random()<case.supply_risk else 0) for k in MATERIALS}
            yields={k:rng.uniform(.94,.995) for k in PRODUCTS}
            if case.mode in ('quality','combined') and 8<=w<=12: yields['PUMP']=.65
            self.exogenous.append(dict(demand=demand,delay=delayed,yields=yields))
        self.commitment=digest(self.exogenous)
        self.environment_commitment=digest(dict(case=asdict(case),products=PRODUCTS,materials=self.materials,policy=POLICY))
        self.week=0; self.cash=case.opening_cash_cents
        self.raw={'CAST':90,'MOTOR':65,'SEAL':250,'PCB':85}
        self.fg={k:10 for k in PRODUCTS}; self.pipeline=[]; self.backlog=[]
        self.history=[]; self.trace=[]; self.last_family={k:None for k in ('mill','assembly','test')}
        self.service_until={k:-1 for k in ('mill','assembly','test')}
        self.costs={k:0 for k in ('procurement','conversion','maintenance','holding','backlog','freight')}
        self.sales=0; self.scrap_units=0; self.shipped_units=0; self.cancelled_units=0
        self.initial_equity=self.cash+self.raw_value()+self.fg_value()

    def raw_value(self):
        return sum(q*MATERIALS[k]['unit_cents'] for k,q in self.raw.items())

    def fg_value(self):
        return sum(q*standard_cost(k) for k,q in self.fg.items())

    def price(self,material):
        increase=1.18 if self.case.mode in ('inflation','combined') and self.week>=10 else 1
        return round(MATERIALS[material]['unit_cents']*increase)

    def capacities(self):
        c={k:round(v*self.case.capacity_scale) for k,v in dict(mill=900,assembly=1250,test=850).items()}
        if self.case.mode in ('maintenance','combined') and 10<=self.week<=12:
            c['mill']=round(c['mill']*(.95 if self.service_until['mill']>=self.week else .45))
        return c

    def observe(self):
        notices=[]
        if self.case.mode in ('inflation','combined') and self.week>=6: notices.append('Material list prices rise 18% at week 10 (zero-based).')
        if self.case.mode=='eol': notices.append('KIT customer program ends at week 16; no new KIT demand after week 15.')
        if self.case.mode=='project' and self.week>=8: notices.append('An additional 65 VALVE units are booked for week 12.')
        if self.case.mode in ('maintenance','combined') and self.week>=7: notices.append('Mill condition will reduce capacity in weeks 10–12 unless serviced. Maintenance restores capacity for four weeks including service week.')
        if self.case.mode in ('quality','combined') and 8<=self.week<=12: notices.append('PUMP first-pass yield alert: process is running near 65%; incoming material remains usable.')
        return dict(week=self.week,weeks_remaining=self.case.weeks-self.week,cash_cents=self.cash,
                    purchase_budget_cents=self.case.budget_cents,raw_units=deepcopy(self.raw),finished_units=deepcopy(self.fg),
                    open_purchase_orders=deepcopy(self.pipeline),backlog=deepcopy(self.backlog),
                    history=deepcopy(self.history[-8:]),capacity_minutes=self.capacities(),
                    material_prices_cents={k:self.price(k) for k in MATERIALS},notices=notices,
                    products=deepcopy(PRODUCTS),materials=deepcopy(self.materials),policy=deepcopy(POLICY),
                    last_product_by_center=deepcopy(self.last_family),service_through_week=deepcopy(self.service_until),
                    normal_weekly_demand=dict(PUMP=12,VALVE=20,DRIVE=12,KIT=15),demand_scale=self.case.demand_scale,
                    action_contract={'purchase_packs':{'material':'nonnegative integer packs'},'expedite':['material IDs'],
                                     'maintain':['work center IDs'],'jobs':[{'product':'product ID','units':'positive integer starts'}]},
                    timing='Decision -> purchase -> inbound receipts (including existing due POs) -> maintenance -> sequential jobs -> customer demand/shipments -> holding/backlog charges. Pipeline balances are unavailable to production until receipt.')

    def _charge(self,category,cents):
        if cents<0 or cents>self.cash: return False
        self.cash-=cents; self.costs[category]+=cents; return True

    def step(self,action):
        if self.week>=self.case.weeks: raise ValueError('season is complete')
        if not isinstance(action,dict): action={}
        w=self.week; event=self.exogenous[w]; log=dict(week=w,purchases=[],jobs=[],rejected=[],receipts=[],shipments=[],maintenance=[])
        unexpected=set(action)-{'purchase_packs','expedite','maintain','jobs'}
        if unexpected: log['rejected'].append('unknown action fields: '+','.join(sorted(unexpected)))
        purchases=action.get('purchase_packs',{}); expedite=action.get('expedite',[])
        if not isinstance(purchases,dict): purchases={}; log['rejected'].append('purchase_packs must be an object')
        if not isinstance(expedite,list): expedite=[]; log['rejected'].append('expedite must be a list')
        spent=0
        for material,packs in purchases.items():
            if material not in MATERIALS or type(packs) is not int or not 0<=packs<=1000:
                log['rejected'].append('invalid material or pack quantity'); continue
            if packs==0: continue
            m=self.materials[material]; units=packs*m['pack_units']; cost=units*self.price(material)
            freight=packs*POLICY['expedited_freight_cents_pack'] if material in expedite else 0
            if spent+cost+freight>self.case.budget_cents or cost+freight>self.cash:
                log['rejected'].append('purchase exceeds weekly budget or available cash'); continue
            self._charge('procurement',cost); self._charge('freight',freight); spent+=cost+freight
            lead=max(1,m['lead_weeks']+event['delay'][material]-(1 if material in expedite else 0))
            po=dict(material=material,units=units,due_week=w+lead,value_cents=cost)
            self.pipeline.append(po); log['purchases'].append(deepcopy(po))
        for po in list(self.pipeline):
            if po['due_week']<=w:
                self.raw[po['material']]+=po['units'];self.pipeline.remove(po);log['receipts'].append(deepcopy(po))
        capacity=self.capacities(); maintain=action.get('maintain',[])
        if not isinstance(maintain,list): maintain=[];log['rejected'].append('maintain must be a list')
        for center in dict.fromkeys(c for c in maintain if isinstance(c,str)):
            if center not in capacity: log['rejected'].append('unknown maintenance center');continue
            if capacity[center]<POLICY['maintenance_minutes'] or not self._charge('maintenance',POLICY['maintenance_cents']):
                log['rejected'].append('maintenance exceeds capacity or cash');continue
            self.service_until[center]=w+3
            capacity[center]=self.capacities()[center]-POLICY['maintenance_minutes'];log['maintenance'].append(center)
        jobs=action.get('jobs',[])
        if not isinstance(jobs,list): jobs=[];log['rejected'].append('jobs must be a list')
        if len(jobs)>POLICY['max_jobs_week']: log['rejected'].append('weekly job limit exceeded')
        for job in jobs[:POLICY['max_jobs_week']]:
            if not isinstance(job,dict): log['rejected'].append('job must be an object');continue
            product=job.get('product');units=job.get('units')
            if not isinstance(product,str) or product not in PRODUCTS or type(units) is not int or not 0<units<=1000:
                log['rejected'].append('invalid production product or units');continue
            p=PRODUCTS[product]; needs={c:units*t+(POLICY['setup_minutes'] if self.last_family[c]!=product else 0) for c,t in p['routing'].items()}
            if any(self.raw[k]<q*units for k,q in p['bom'].items()): log['rejected'].append('insufficient released material');continue
            if any(capacity[c]<minutes for c,minutes in needs.items()): log['rejected'].append('finite capacity exceeded');continue
            if not self._charge('conversion',units*p['conversion_cents']): log['rejected'].append('insufficient cash for production');continue
            for k,q in p['bom'].items(): self.raw[k]-=q*units
            for c,minutes in needs.items(): capacity[c]-=minutes;self.last_family[c]=product
            good=math.floor(units*event['yields'][product]);self.fg[product]+=good;self.scrap_units+=units-good
            log['jobs'].append(dict(product=product,started_units=units,good_units=good,scrap_units=units-good,used_minutes=needs))
        for product,units in event['demand'].items():
            if units:self.backlog.append(dict(product=product,units=units,booked_week=w))
        for order in list(self.backlog):
            product=order['product'];ship=min(order['units'],self.fg[product]);self.fg[product]-=ship;order['units']-=ship
            revenue=ship*PRODUCTS[product]['price_cents'];self.cash+=revenue;self.sales+=revenue;self.shipped_units+=ship
            if ship:log['shipments'].append(dict(product=product,units=ship,booked_week=order['booked_week'],revenue_cents=revenue))
            if order['units']==0:self.backlog.remove(order)
            elif w-order['booked_week']>=POLICY['cancel_after_weeks']:
                self.cancelled_units+=order['units'];self.backlog.remove(order)
        # Charges may make cash negative; the next week then cannot purchase or produce until sales recover it.
        for category,cost in [('holding',round((self.raw_value()+self.fg_value())*POLICY['holding_bps_week']/10000)),
                              ('backlog',sum(o['units'] for o in self.backlog)*POLICY['backlog_cents_unit_week'])]:
            self.cash-=cost;self.costs[category]+=cost
        self.history.append(dict(week=w,demand_units=event['demand'],jobs=deepcopy(log['jobs']),shipments=deepcopy(log['shipments']),rejected=deepcopy(log['rejected'])))
        log['remaining_capacity_minutes']=capacity;log['cash_cents']=self.cash
        log['action']=deepcopy(action);self.week+=1;log['state_hash']=self.state_hash();self.trace.append(log)
        return deepcopy(log)

    def state_hash(self):
        return digest(dict(week=self.week,cash=self.cash,raw=self.raw,fg=self.fg,pipeline=self.pipeline,
                           backlog=self.backlog,last_family=self.last_family,service_until=self.service_until,
                           costs=self.costs,sales=self.sales,scrap=self.scrap_units,history=self.history))

    def result(self):
        if self.week!=self.case.weeks:raise ValueError('cannot score an unfinished season')
        raw_salvage=round(self.raw_value()*POLICY['terminal_raw_recovery_fraction'])
        fg_salvage=round(self.fg_value()*POLICY['terminal_fg_recovery_fraction'])
        pipeline_salvage=round(sum(po['value_cents'] for po in self.pipeline)*POLICY['terminal_raw_recovery_fraction'])
        equity=self.cash+raw_salvage+fg_salvage+pipeline_salvage
        margin=sum(sum(q*(PRODUCTS[k]['price_cents']-standard_cost(k)) for k,q in e['demand'].items()) for e in self.exogenous)
        demand=sum(sum(e['demand'].values()) for e in self.exogenous)
        return dict(case_id=self.case.id,draw=self.draw,weeks=self.week,profit_cents=equity-self.initial_equity,
                    demand_margin_cents=margin,score=100*(equity-self.initial_equity)/margin if margin else 0,
                    shipped_units=self.shipped_units,demand_units=demand,fill_rate=self.shipped_units/demand if demand else 1,
                    cancelled_units=self.cancelled_units,backlog_units=sum(o['units'] for o in self.backlog),scrap_units=self.scrap_units,
                    sales_cents=self.sales,costs_cents=self.costs,terminal_raw_cents=raw_salvage,terminal_fg_cents=fg_salvage,
                    terminal_pipeline_cents=pipeline_salvage,initial_equity_cents=self.initial_equity,
                    final_cash_cents=self.cash,final_state_hash=self.state_hash(),exogenous_commitment=self.commitment,
                    rejected_actions=sum(len(t['rejected']) for t in self.trace),environment_commitment=self.environment_commitment)


def idle_policy(observation):
    return dict(purchase_packs={},jobs=[],maintain=[],expedite=[])


def rule_policy(o):
    """Demand-buffer purchasing and capacity-constrained earliest-backlog production."""
    demand={k:o['normal_weekly_demand'][k]*o['demand_scale'] for k in PRODUCTS}
    if o['history']:
        for k in demand:demand[k]=sum(h['demand_units'][k] for h in o['history'][-4:])/len(o['history'][-4:])
    if any('no new KIT' in n for n in o['notices']) and o['week']>=16:demand['KIT']=0
    backlog={k:sum(b['units'] for b in o['backlog'] if b['product']==k) for k in PRODUCTS}
    target={k:max(0,math.ceil(demand[k]*1.3+backlog[k]-o['finished_units'][k])) for k in PRODUCTS}
    raw_need={m:sum(demand[k]*p['bom'].get(m,0) for k,p in PRODUCTS.items()) for m in MATERIALS}
    packs={};budget=min(o['purchase_budget_cents'],max(0,o['cash_cents']))
    for m,params in o['materials'].items():
        stock=o['raw_units'][m]+sum(po['units'] for po in o['open_purchase_orders'] if po['material']==m)
        shortage=max(0,math.ceil(raw_need[m]*(params['lead_weeks']+1.5)-stock))
        qty=math.ceil(shortage/params['pack_units']); unitpack=o['material_prices_cents'][m]*params['pack_units']
        qty=min(qty,budget//unitpack);budget-=qty*unitpack
        if qty:packs[m]=qty
    capacity=deepcopy(o['capacity_minutes']);raw=deepcopy(o['raw_units'])
    # Existing POs due this week arrive before production.
    for po in o['open_purchase_orders']:
        if po['due_week']<=o['week']:raw[po['material']]+=po['units']
    jobs=[];cash=max(0,o['cash_cents']-sum(packs[m]*o['materials'][m]['pack_units']*o['material_prices_cents'][m] for m in packs))
    priority=sorted(PRODUCTS,key=lambda k:(-backlog[k],-((PRODUCTS[k]['price_cents']-standard_cost(k))/sum(PRODUCTS[k]['routing'].values())),k))
    for k in priority:
        p=PRODUCTS[k]
        units=min([target[k],cash//p['conversion_cents']]+[raw[m]//q for m,q in p['bom'].items()]+[max(0,(capacity[c]-POLICY['setup_minutes'])//t) for c,t in p['routing'].items()])
        if units:
            jobs.append(dict(product=k,units=units));cash-=units*p['conversion_cents']
            for m,q in p['bom'].items():raw[m]-=units*q
            for c,t in p['routing'].items():capacity[c]-=units*t+POLICY['setup_minutes']
    return dict(purchase_packs=packs,jobs=jobs,maintain=[],expedite=[])


def replay(case,draw,trace):
    world=FactorySeason(case,draw)
    for i,record in enumerate(trace):
        actual=world.step(record['action'])
        if actual!=record:raise ValueError(f'replay mismatch at week {i}')
    return world.result()
