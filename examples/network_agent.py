"""Standalone bounded public-state search. No family, grader or reference imports."""
import heapq
import json
import sys


def plan(payload):
    config=payload['config'];observed=payload['state'];items=sorted(config['items']);position={n:i for i,n in enumerate(items)}
    recipes=config['recipes'];offers=config['offers'];maximum_raw={n:config['orders'].get(n,0)+sum(r['inputs'].get(n,0)*r['max_batches'] for r in config['recipes']) for n in items};goal=tuple(config['orders'].get(n,0) for n in items)
    inputs=[tuple(r['inputs'].get(n,0) for n in items) for r in recipes];outputs=[tuple(r['outputs'].get(n,0) for n in items) for r in recipes]
    if observed['pending'] or any(observed['shipped'].values()):raise ValueError('this development control requires an untouched initial state')
    # State: clock, stock, bought, batches started, pending(finish, type, index, quantity).
    initial=(observed['clock'],tuple(observed['stock'][n] for n in items),tuple(observed['bought'][o['id']] for o in offers),tuple(observed['used'][r['id']] for r in recipes),())
    queue=[];serial=0;parents={initial:None};expanded=0
    def spent(state):return sum(q*o['price_cents'] for q,o in zip(state[2],offers))+sum(q*r['cost_cents'] for q,r in zip(state[3],recipes))
    def push(state,parent,action):
        nonlocal serial
        if state in parents or state[0]>config['due'] or spent(state)>config['budget_cents']:return
        parents[state]=(parent,action);serial+=1
        heapq.heappush(queue,((-sum(state[3]),state[0],spent(state)),serial,state))
    heapq.heappush(queue,((0,initial[0],spent(initial)),serial,initial))
    while queue:
        _,_,state=heapq.heappop(queue);expanded+=1
        if expanded>100000:raise ValueError('bounded public search exhausted 100000 states')
        clock,stock,bought,used,pending=state
        if not pending and all(q>=n for q,n in zip(stock,goal)):
            actions=[];cursor=state
            while parents[cursor] is not None:
                previous,action=parents[cursor];actions.append(action);cursor=previous
            actions.reverse()
            for n,qty in config['orders'].items():actions.append(dict(tool='ship',arguments=dict(item=n,quantity=qty)))
            actions.append(dict(tool='finish',arguments={}))
            if len(actions)>config['max_calls']:raise ValueError('plan exceeds public call budget')
            return dict(actions=actions,expanded_states=expanded,planned_spend=spent(state),planned_finish=clock)
        for index,r in enumerate(recipes):
            if used[index]>=r['max_batches'] or any(kind==1 and recipes[j]['resource']==r['resource'] for _,kind,j,_ in pending):continue
            if any(q<need for q,need in zip(stock,inputs[index])):continue
            next_stock=tuple(q-need for q,need in zip(stock,inputs[index]));next_used=list(used);next_used[index]+=1
            jobs=tuple(sorted(pending+((clock+r['duration'],1,index,1),)))
            push((clock,next_stock,bought,tuple(next_used),jobs),state,dict(tool='start',arguments=dict(recipe_id=r['id'])))
        # Under this public contract, earlier purchases cannot harm feasibility:
        # no expiry, holding cost, cash income or changing supply is modeled.
        # All purchases may therefore be moved to the initial clock.
        for index,o in enumerate(offers):
            if clock!=initial[0]:continue
            total_bought=sum(bought[j] for j,offer in enumerate(offers) if offer['item']==o['item'])
            capacity=min(o['capacity']-bought[index],maximum_raw[o['item']]-total_bought)
            for quantity in range(1,capacity+1):
                next_bought=list(bought);next_bought[index]+=quantity;jobs=tuple(sorted(pending+((clock+o['lead'],0,index,quantity),)))
                push((clock,stock,tuple(next_bought),used,jobs),state,dict(tool='buy',arguments=dict(offer_id=o['id'],quantity=quantity)))
        if pending:
            until=pending[0][0];next_stock=list(stock);remaining=[]
            for finish,kind,index,quantity in pending:
                if finish>until:remaining.append((finish,kind,index,quantity));continue
                if kind==0:next_stock[position[offers[index]['item']]]+=quantity
                else:
                    for i,qty in enumerate(outputs[index]):next_stock[i]+=qty
            push((until,tuple(next_stock),bought,used,tuple(remaining)),state,dict(tool='wait',arguments=dict(until=until)))
    raise ValueError('no feasible plan found under public capacities, budget and deadline')


if __name__=='__main__':
    for line in sys.stdin:
        try:print(json.dumps(plan(json.loads(line)['payload'])),flush=True)
        except (ValueError,KeyError,TypeError) as error:print(json.dumps({'error':str(error)}),flush=True)
