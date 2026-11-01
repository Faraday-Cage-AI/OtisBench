"""Executable synthetic multi-input/output manufacturing networks; development only."""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PROTOCOL='manufacturing-material-networks/1'
FAMILIES=('serial_chain','parallel_join','reconvergent_fanout','nested_assembly','shared_subassembly','coproduct','recycling_loop','multisite')
CONDITIONS=('baseline','limited_primary','shared_resource')


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n')


def catalog():return [dict(id=f'network-{family}-{condition}-{draw}',family=family,condition=condition,draw=draw) for family in FAMILIES for condition in CONDITIONS for draw in (1,2)]


def build(task):
    family=task['family'];q=task['draw'];condition=task['condition'];items={};recipes=[];raw={};orders={}
    if family not in FAMILIES or condition not in CONDITIONS or type(q) is not int or q not in (1,2):raise ValueError('unsupported development case')
    def item(name,mass,site='plant'):
        items[name]=dict(mass_grams=mass,site=site,sku=name.split('-')[0]);return name
    def recipe(name,inputs,outputs,limit=None,kind='manufacture',duration=3):
        recipes.append(dict(id=name,inputs=inputs,outputs=outputs,max_batches=limit or q,kind=kind,duration=duration,cost_cents=3,
                            resource='shared' if condition=='shared_resource' else name))
    if family=='serial_chain':
        for n in ('R','A','B','P'):item(n,1000)
        raw={'R':q};orders={'P':q};recipe('cut',{'R':1},{'A':1});recipe('finish',{'A':1},{'B':1});recipe('test',{'B':1},{'P':1})
    elif family=='parallel_join':
        for n in ('R','S','A','B'):item(n,1000)
        item('P',2000);raw={'R':q,'S':q};orders={'P':q}
        recipe('machine_a',{'R':1},{'A':1},duration=4);recipe('machine_b',{'S':1},{'B':1},duration=4);recipe('assemble',{'A':1,'B':1},{'P':1})
    elif family=='reconvergent_fanout':
        for n in ('R','A','B'):item(n,1000)
        item('P',2000);raw={'R':2*q};orders={'P':q}
        recipe('machine_a',{'R':1},{'A':1},duration=4);recipe('machine_b',{'R':1},{'B':1},duration=4);recipe('assemble',{'A':1,'B':1},{'P':1})
    elif family=='nested_assembly':
        for n in ('R','S','T','C'):item(n,1000)
        item('A',2000);item('P',3000);raw={'R':q,'S':q,'T':q};orders={'P':q}
        recipe('subassembly',{'R':1,'S':1},{'A':1},duration=4);recipe('machine_c',{'T':1},{'C':1},duration=4);recipe('final',{'A':1,'C':1},{'P':1})
    elif family=='shared_subassembly':
        for n in ('R','C','P','Q'):item(n,1000)
        raw={'R':2*q};orders={'P':q,'Q':q}
        recipe('common',{'R':1},{'C':1},limit=2*q);recipe('product_p',{'C':1},{'P':1});recipe('product_q',{'C':1},{'Q':1})
    elif family=='coproduct':
        item('R',2000);item('P',1000);item('Q',1000);raw={'R':q};orders={'P':q,'Q':q};recipe('separate',{'R':1},{'P':1,'Q':1},duration=4)
    elif family=='recycling_loop':
        item('R',2000);item('P',1000);item('S',1000);raw={'R':2*q};orders={'P':3*q}
        recipe('process',{'R':1},{'P':1,'S':1},limit=3*q);recipe('reclaim',{'S':2},{'R':1},limit=q,kind='recycle',duration=4)
    elif family=='multisite':
        item('R',1000,'west');item('A-west',1000,'west');item('A-east',1000,'east');item('P',1000,'east');raw={'R':q};orders={'P':q}
        recipe('machine_west',{'R':1},{'A-west':1});recipe('transfer',{'A-west':1},{'A-east':1},kind='transport',duration=4);recipe('finish_east',{'A-east':1},{'P':1})
    else:raise ValueError('unknown family')
    offers=[];minimum_purchase=0
    for index,(name,needed) in enumerate(raw.items()):
        cheap=needed//2 if condition=='limited_primary' else needed
        # Recycling requires the loop: total raw supply is capped at 2*q.
        alternate=needed-cheap if family=='recycling_loop' else needed
        offers.extend([dict(id=f'offer-{index}-primary',item=name,capacity=cheap,price_cents=2,lead=2),
                       dict(id=f'offer-{index}-alternate',item=name,capacity=alternate,price_cents=7,lead=1)])
        minimum_purchase+=cheap*2+(needed-cheap)*7
    cost=minimum_purchase+sum(r['cost_cents']*r['max_batches'] for r in recipes)
    # Stage-by-stage critical-path bound is feasible with distinct resources.
    # Shared resources and the recycling cycle use a serial duration bound.
    if condition=='shared_resource' or family=='recycling_loop':duration=sum(r['duration']*r['max_batches'] for r in recipes)
    else:
        ready={name:0 for name in raw};pending=recipes[:]
        while pending:
            progressed=False
            for r in pending[:]:
                if set(r['inputs'])<=ready.keys():
                    end=max(ready[n] for n in r['inputs'])+r['duration']*r['max_batches']
                    for n in r['outputs']:ready[n]=max(ready.get(n,0),end)
                    pending.remove(r);progressed=True
            if not progressed:raise ValueError('unassessed cycle in critical-path bound')
        duration=max(ready[n] for n in orders)
    config=dict(protocol=PROTOCOL,id=task['id'],items=items,recipes=recipes,offers=offers,orders=orders,
        initial_stock={n:0 for n in items},initial_cash_cents=10000,budget_cents=cost+q,
        due=duration+4,max_calls=150,prompt='Buy, manufacture, transfer/recycle where needed, and ship every order within the cash budget and deadline. Inventory and work-in-progress are conserved; production and purchase arrivals take time. Inspect public recipes, capacities and shared resources. All quantities are indivisible units; recipe input/output quantities are per batch. Commercially bad purchases can be accepted and still fail final grading.')
    validate(config);return config


def positive_int(value):return type(value) is int and value>0


def validate(config):
    items=config['items'];ids=[r['id'] for r in config['recipes']]
    for field in ('initial_cash_cents','budget_cents','due','max_calls'):
        if not positive_int(config[field]):raise ValueError('invalid episode bound')
    if set(config['initial_stock'])!=set(items) or any(type(q) is not int or q<0 for q in config['initial_stock'].values()):raise ValueError('invalid initial stock')
    offer_ids=[o['id'] for o in config['offers']]
    if len(set(offer_ids))!=len(offer_ids):raise ValueError('duplicate offer')
    for offer in config['offers']:
        if offer['item'] not in items or type(offer['capacity']) is not int or offer['capacity']<0 or not positive_int(offer['price_cents']) or not positive_int(offer['lead']):raise ValueError('invalid offer')
    if len(set(ids))!=len(ids) or not items:raise ValueError('invalid recipe inventory')
    for item in items.values():
        if not positive_int(item['mass_grams']):raise ValueError('invalid mass')
    for recipe in config['recipes']:
        for field in ('duration','cost_cents','max_batches'):
            if not positive_int(recipe[field]):raise ValueError('invalid recipe bound')
        for side in ('inputs','outputs'):
            if not recipe[side] or any(n not in items or not positive_int(q) for n,q in recipe[side].items()):raise ValueError('invalid recipe quantity')
        mass=lambda side:sum(items[n]['mass_grams']*q for n,q in recipe[side].items())
        if mass('inputs')!=mass('outputs'):raise ValueError('recipe violates declared mass conservation')
        sites={items[n]['site'] for n in recipe['inputs']|recipe['outputs']}
        if recipe['kind'] not in ('manufacture','recycle','transport'):raise ValueError('invalid recipe kind')
        if recipe['kind']!='transport' and len(sites)!=1:raise ValueError('cross-site manufacture requires explicit transport')
        if recipe['kind']=='transport':
            if len(recipe['inputs'])!=1 or len(recipe['outputs'])!=1:raise ValueError('transport needs one SKU at each site')
            left,right=next(iter(recipe['inputs'])),next(iter(recipe['outputs']))
            if items[left]['sku']!=items[right]['sku'] or recipe['inputs'][left]!=recipe['outputs'][right] or len(sites)!=2:raise ValueError('transport changes SKU or quantity')
    if any(n not in items or not positive_int(q) for n,q in config['orders'].items()):raise ValueError('invalid orders')


class World:
    def __init__(self,config):
        validate(config);self.config=deepcopy(config);self.clock=0;self.stock=deepcopy(config['initial_stock']);self.cash=config['initial_cash_cents'];self.spent=0
        self.pending=[];self.used={r['id']:0 for r in config['recipes']};self.bought={o['id']:0 for o in config['offers']};self.shipped={n:0 for n in config['orders']}
        self.trace=[];self.finished=False;self.calls=0
    def state(self):return dict(clock=self.clock,stock=deepcopy(self.stock),cash=self.cash,spent=self.spent,pending=deepcopy(self.pending),used=deepcopy(self.used),bought=deepcopy(self.bought),shipped=deepcopy(self.shipped),finished=self.finished)
    def public(self):return dict(config=deepcopy(self.config),state=self.state())
    def act(self,action):
        self.calls+=1;before=self.state()
        try:
            if self.calls>self.config['max_calls'] or self.finished:raise ValueError('episode finished or call budget exhausted')
            if not isinstance(action,dict) or 'tool' not in action:raise ValueError('invalid action')
            tool=action['tool'];args=action.get('arguments',{})
            if tool=='read_state':
                if args:raise ValueError('read_state takes no arguments')
            elif tool=='buy':
                if set(args)!={'offer_id','quantity'} or not positive_int(args['quantity']):raise ValueError('invalid purchase')
                offer=next((o for o in self.config['offers'] if o['id']==args['offer_id']),None);qty=args['quantity']
                if not offer or self.bought[offer['id']]+qty>offer['capacity']:raise ValueError('supplier capacity exceeded')
                cost=qty*offer['price_cents']
                if cost>self.cash:raise ValueError('insufficient cash')
                self.cash-=cost;self.spent+=cost;self.bought[offer['id']]+=qty
                self.pending.append(dict(kind='purchase',id=offer['id'],finish=self.clock+offer['lead'],outputs={offer['item']:qty},mass_grams=qty*self.config['items'][offer['item']]['mass_grams']))
            elif tool=='start':
                if set(args)!={'recipe_id'}:raise ValueError('invalid production action')
                r=next((r for r in self.config['recipes'] if r['id']==args['recipe_id']),None)
                if not r or self.used[r['id']]>=r['max_batches']:raise ValueError('recipe capacity exceeded')
                if any(j.get('resource')==r['resource'] for j in self.pending):raise ValueError('resource is busy')
                if any(self.stock[n]<q for n,q in r['inputs'].items()):raise ValueError('inputs unavailable')
                if r['cost_cents']>self.cash:raise ValueError('insufficient cash')
                for n,q in r['inputs'].items():self.stock[n]-=q
                self.cash-=r['cost_cents'];self.spent+=r['cost_cents'];self.used[r['id']]+=1
                self.pending.append(dict(kind=r['kind'],id=r['id'],resource=r['resource'],finish=self.clock+r['duration'],outputs=deepcopy(r['outputs']),mass_grams=sum(self.config['items'][n]['mass_grams']*q for n,q in r['inputs'].items())))
            elif tool=='wait':
                if set(args)!={'until'} or type(args['until']) is not int or not self.clock<args['until']<=self.config['due']:raise ValueError('invalid time advance')
                self.clock=args['until'];ready=[j for j in self.pending if j['finish']<=self.clock]
                for job in ready:
                    for n,q in job['outputs'].items():self.stock[n]+=q
                self.pending=[j for j in self.pending if j['finish']>self.clock]
            elif tool=='ship':
                if set(args)!={'item','quantity'} or not positive_int(args['quantity']):raise ValueError('invalid shipment')
                item=args['item'];qty=args['quantity']
                if item not in self.shipped or self.shipped[item]+qty>self.config['orders'][item] or self.stock[item]<qty:raise ValueError('shipment exceeds order or available inventory')
                self.stock[item]-=qty;self.shipped[item]+=qty
            elif tool=='finish':
                if args:raise ValueError('finish takes no arguments')
                self.finished=True
            else:raise ValueError('unknown tool')
            result=dict(ok=True,state=self.state())
        except (ValueError,KeyError,TypeError) as error:
            if self.state()!=before:raise AssertionError('rejected action changed business state')
            result=dict(ok=False,error=str(error),state=self.state())
        self.trace.append(dict(action=deepcopy(action),result=deepcopy(result)))
        return result
    def grade(self):
        mass=lambda inventory:sum(self.config['items'][n]['mass_grams']*q for n,q in inventory.items())
        incoming=sum(o['price_cents']*self.bought[o['id']] for o in self.config['offers'])
        manufacturing=sum(r['cost_cents']*self.used[r['id']] for r in self.config['recipes'])
        owned_mass=mass(self.config['initial_stock'])+sum(self.bought[o['id']]*self.config['items'][o['item']]['mass_grams'] for o in self.config['offers'])
        accounted_mass=mass(self.stock)+sum(j['mass_grams'] for j in self.pending)+mass(self.shipped)
        checks=dict(orders_fulfilled=self.shipped==self.config['orders'],on_time=self.clock<=self.config['due'],within_budget=self.spent<=self.config['budget_cents'],
            cash_conserved=self.cash+self.spent==self.config['initial_cash_cents'] and self.spent==incoming+manufacturing,
            mass_conserved=owned_mass==accounted_mass,nonnegative_stock=all(type(q) is int and q>=0 for q in self.stock.values()),
            finished=self.finished,no_pending_jobs=not self.pending)
        return dict(strict_success=all(checks.values()),score=100. if all(checks.values()) else 0.,checks=checks,clock=self.clock,spent=self.spent,owned_mass_grams=owned_mass,accounted_mass_grams=accounted_mass)
