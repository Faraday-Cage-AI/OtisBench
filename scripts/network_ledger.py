"""Separate action-ledger reconstruction; does not import World or its grader."""
from copy import deepcopy


def audit(config,trace,claimed_state,claimed_result):
    stock=deepcopy(config['initial_stock']);clock=0;cash=config['initial_cash_cents'];spent=0;pending=[]
    used={r['id']:0 for r in config['recipes']};bought={o['id']:0 for o in config['offers']};shipped={n:0 for n in config['orders']};finished=False;errors=[]
    recipes={r['id']:r for r in config['recipes']};offers={o['id']:o for o in config['offers']}
    mass=lambda values:sum(config['items'][n]['mass_grams']*q for n,q in values.items())
    def state():return dict(clock=clock,stock=deepcopy(stock),cash=cash,spent=spent,pending=deepcopy(pending),used=deepcopy(used),bought=deepcopy(bought),shipped=deepcopy(shipped),finished=finished)
    for i,row in enumerate(trace):
        try:
            if row['result']['ok']:
                if finished or i>=config['max_calls']:raise ValueError('accepted action after termination')
                tool=row['action']['tool'];a=row['action'].get('arguments',{})
                keys={'buy':{'offer_id','quantity'},'start':{'recipe_id'},'wait':{'until'},'ship':{'item','quantity'},'read_state':set(),'finish':set()}
                if tool not in keys or set(a)!=keys[tool]:raise ValueError('invalid accepted argument contract')
                if tool=='buy':
                    o=offers[a['offer_id']];q=a['quantity'];price=q*o['price_cents']
                    if type(q) is not int or q<=0 or bought[o['id']]+q>o['capacity'] or price>cash:raise ValueError('invalid accepted purchase')
                    cash-=price;spent+=price;bought[o['id']]+=q
                    pending.append(dict(kind='purchase',id=o['id'],finish=clock+o['lead'],outputs={o['item']:q},mass_grams=q*config['items'][o['item']]['mass_grams']))
                elif tool=='start':
                    r=recipes[a['recipe_id']]
                    if used[r['id']]>=r['max_batches'] or any(j.get('resource')==r['resource'] for j in pending):raise ValueError('invalid recipe/resource capacity')
                    if any(stock[n]<q for n,q in r['inputs'].items()) or cash<r['cost_cents']:raise ValueError('production used unavailable inputs/cash')
                    for n,q in r['inputs'].items():stock[n]-=q
                    cash-=r['cost_cents'];spent+=r['cost_cents'];used[r['id']]+=1
                    pending.append(dict(kind=r['kind'],id=r['id'],resource=r['resource'],finish=clock+r['duration'],outputs=deepcopy(r['outputs']),mass_grams=mass(r['inputs'])))
                elif tool=='wait':
                    t=a['until']
                    if type(t) is not int or not clock<t<=config['due']:raise ValueError('invalid time advance')
                    clock=t;remaining=[]
                    for j in pending:
                        if j['finish']>clock:remaining.append(j)
                        else:
                            for n,q in j['outputs'].items():stock[n]+=q
                    pending=remaining
                elif tool=='ship':
                    n=a['item'];q=a['quantity']
                    if type(q) is not int or q<=0 or n not in shipped or shipped[n]+q>config['orders'][n] or stock[n]<q:raise ValueError('invalid accepted shipment')
                    stock[n]-=q;shipped[n]+=q
                elif tool=='finish':finished=True
                elif tool!='read_state':raise ValueError('unknown accepted tool')
            if row['result']['state']!=state():raise ValueError('recorded state differs from action reconstruction')
            owned=mass(config['initial_stock'])+sum(bought[o['id']]*config['items'][o['item']]['mass_grams'] for o in offers.values())
            actual=mass(stock)+mass(shipped)+sum(j['mass_grams'] for j in pending)
            if owned!=actual or cash+spent!=config['initial_cash_cents'] or any(q<0 for q in stock.values()):raise ValueError('intermediate conservation failure')
        except (ValueError,KeyError,TypeError) as error:
            errors.append(f'action {i}: {error}');break
    expected_state=state()
    checks=dict(orders_fulfilled=shipped==config['orders'],on_time=clock<=config['due'],within_budget=spent<=config['budget_cents'],
        cash_conserved=cash+spent==config['initial_cash_cents'] and spent==sum(bought[o['id']]*o['price_cents'] for o in offers.values())+sum(used[r['id']]*r['cost_cents'] for r in recipes.values()),
        mass_conserved=mass(config['initial_stock'])+sum(bought[o['id']]*config['items'][o['item']]['mass_grams'] for o in offers.values())==mass(stock)+mass(shipped)+sum(j['mass_grams'] for j in pending),
        nonnegative_stock=all(type(q) is int and q>=0 for q in stock.values()),finished=finished,no_pending_jobs=not pending)
    expected_result=dict(strict_success=all(checks.values()),score=100. if all(checks.values()) else 0.,checks=checks,clock=clock,spent=spent,
        owned_mass_grams=mass(config['initial_stock'])+sum(bought[o['id']]*config['items'][o['item']]['mass_grams'] for o in offers.values()),
        accounted_mass_grams=mass(stock)+mass(shipped)+sum(j['mass_grams'] for j in pending))
    if claimed_state!=expected_state:errors.append('final state differs from action reconstruction')
    if claimed_result!=expected_result:errors.append('final grading differs from reconstructed outcome')
    return dict(passed=not errors,errors=errors,actions=len(trace))
