"""Full synthetic network development qualification; author controls, not models."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from manufacturing_networks import ROOT,World,build,catalog,digest,save,sha,PROTOCOL
from network_ledger import audit
from network_topology import canonical
from faraday_manufacturing_benchmark.isolation import isolated_agent
AGENT=ROOT/'examples/network_agent.py'


def sources():
    paths=['scripts/manufacturing_networks.py','scripts/network_ledger.py','scripts/network_topology.py','scripts/qualify_networks.py','examples/network_agent.py',
        'src/faraday_manufacturing_benchmark/isolation.py','src/faraday_manufacturing_benchmark/agents.py']
    return {p:sha(ROOT/p) for p in paths}


def execute(config,plan):
    world=World(config)
    for action in plan:
        result=world.act(action)
        if not result['ok']:raise ValueError('public plan rejected: '+str(result['error']))
    result=world.grade();ledger=audit(config,world.trace,world.state(),result)
    if not ledger['passed']:raise ValueError('separate ledger reconstruction differs')
    return world,result,ledger


def ledger_mutations(config,world,result):
    controls=[]
    def reject(name,trace=None,state=None,score=None):
        r=audit(config,trace if trace is not None else world.trace,state if state is not None else world.state(),score if score is not None else result)
        if r['passed']:raise ValueError('ledger corruption accepted: '+name)
        controls.append(dict(kind=name,rejected=True))
    for name,field in [('cash','cash'),('spent','spent'),('clock','clock')]:
        trace=deepcopy(world.trace);trace[0]['result']['state'][field]+=1;reject(name,trace=trace)
    trace=deepcopy(world.trace);node=next(iter(config['items']));trace[0]['result']['state']['stock'][node]+=1;reject('inventory',trace=trace)
    trace=deepcopy(world.trace);row=next(r for r in trace if r['action']['tool']=='buy');job=row['result']['state']['pending'][-1];node=next(iter(job['outputs']));job['outputs'][node]+=1;reject('pending_output',trace=trace)
    trace=deepcopy(world.trace);row=next(r for r in trace if r['action']['tool']=='start');r=next(x for x in config['recipes'] if x['id']==row['action']['arguments']['recipe_id']);node=next(iter(r['inputs']));row['result']['state']['stock'][node]+=1;reject('consumption',trace=trace)
    state=world.state();node=next(iter(state['shipped']));state['shipped'][node]-=1;reject('shipment',state=state)
    wrong=deepcopy(result);wrong['score']=99.;reject('reward',score=wrong)
    return controls


def bad_business_purchase(config,actions):
    offers={o['id']:o for o in config['offers']};totals={n:0 for n in offers}
    for a in actions:
        if a['tool']=='buy':totals[a['arguments']['offer_id']]+=a['arguments']['quantity']
    for index,a in enumerate(actions):
        if a['tool']!='buy':continue
        old=offers[a['arguments']['offer_id']];quantity=a['arguments']['quantity']
        for new in config['offers']:
            if new['item']!=old['item'] or new['price_cents']<=old['price_cents'] or new['lead']>old['lead'] or totals[new['id']]+quantity>new['capacity']:continue
            changed=deepcopy(actions);changed[index]['arguments']['offer_id']=new['id'];world,result,ledger=execute(config,changed)
            if result['strict_success'] or result['checks']['within_budget']:raise ValueError('commercially worse accepted purchase did not fail budget')
            return dict(exercised=True,all_actions_accepted=True,result=result,ledger=ledger,changed_action=index,old_offer=old['id'],new_offer=new['id'],trace=world.trace)
    return dict(exercised=False,reason='No higher-price, no-later eligible offer can replace a purchased lot within supplier capacity.')


def qualify(output=ROOT/'reports/network-qualification-v2.json',run_dir=ROOT/'runs/network-qualification-v2'):
    output=Path(output).resolve();run_dir=Path(run_dir).resolve()
    if run_dir.exists():raise ValueError('refusing to overwrite network qualification')
    run_dir.mkdir(parents=True);fingerprints=sources();rows=[];topologies={};receipt_paths=[]
    with isolated_agent(AGENT) as agent:
        for task in catalog():
            config=build(task);initial=World(config);payload=initial.public();response=agent.decide('manufacturing_network',payload)
            if 'actions' not in response:raise ValueError('isolated public search failed: '+str(response))
            world,result,ledger=execute(config,response['actions'])
            if not result['strict_success']:raise ValueError('network public control failed: '+task['id'])
            if not all(world.used.values()):raise ValueError('declared recipe not exercised by the public control')
            replay,replay_result,replay_ledger=execute(config,response['actions'])
            if replay.trace!=world.trace or replay.state()!=world.state() or replay_result!=result:raise ValueError('exact runtime replay differs')
            noop=World(config);noop.act(dict(tool='finish',arguments={}))
            if noop.grade()['score']!=0:raise ValueError('no-op should score zero')
            invalid=World(config);before=invalid.state();rejected=invalid.act(dict(tool='start',arguments=dict(recipe_id=config['recipes'][-1]['id'])))
            if rejected['ok'] or invalid.state()!=before:raise ValueError('missing-input control failed')
            offer=config['offers'][0];rejected=invalid.act(dict(tool='buy',arguments=dict(offer_id=offer['id'],quantity=offer['capacity']+1)))
            if rejected['ok'] or invalid.state()!=before:raise ValueError('supplier-capacity control failed')
            mutation_controls=ledger_mutations(config,world,result);bad_purchase=bad_business_purchase(config,response['actions'])
            # Exercise a real in-flight resource rejection on the first eligible state.
            resource_control=dict(exercised=False)
            probe=World(config)
            for action in response['actions']:
                probe.act(action)
                candidates=[r for r in config['recipes'] if probe.used[r['id']]<r['max_batches'] and all(probe.stock[n]>=q for n,q in r['inputs'].items()) and probe.cash>=r['cost_cents'] and any(j.get('resource')==r['resource'] for j in probe.pending)]
                if candidates:
                    r=candidates[0];old=probe.state();attempt=probe.act(dict(tool='start',arguments=dict(recipe_id=r['id'])))
                    if attempt['ok'] or attempt['error']!='resource is busy' or probe.state()!=old:raise ValueError('resource occupation control failed')
                    resource_control=dict(exercised=True,rejected=True);break
            topology=canonical(config);topologies.setdefault(task['family'],set()).add(topology['signature'])
            path=run_dir/(task['id']+'.json')
            save(path,dict(task=task,config=config,config_sha256=digest(config),payload=payload,response=response,trace=world.trace,
                final_state=world.state(),result=result,ledger=ledger,exact_runtime_replay=True,replay_ledger=replay_ledger,
                noop_result=noop.grade(),missing_input_rejected=True,supplier_capacity_rejected=True,resource_control=resource_control,
                ledger_mutations=mutation_controls,bad_business_purchase=bad_purchase,topology=topology))
            receipt_paths.append(path);rows.append(dict(task_id=task['id'],family=task['family'],condition=task['condition'],draw=task['draw'],
                strict_success=True,receipt=str(path.relative_to(ROOT)),receipt_sha256=sha(path),expanded_states=response['expanded_states'],
                actions=len(world.trace),ledger_mutations_rejected=len(mutation_controls),bad_purchase_exercised=bad_purchase['exercised'],resource_control_exercised=resource_control['exercised']))
        isolation=agent.isolation
    # Fresh agent process sees the exact same public configurations; no reference state.
    with isolated_agent(AGENT) as agent:
        for path in receipt_paths:
            receipt=json.loads(path.read_text())
            if agent.decide('manufacturing_network',receipt['payload'])!=receipt['response']:raise ValueError('isolated policy response replay differs')
    # Probe actual evaluator files; positive host reads establish that they exist.
    probe_code='''import json,sys
for line in sys.stdin:
    result={}
    for path in json.loads(line)['payload']['paths']:
        try:
            with open(path,'rb') as stream:stream.read(1)
            result[path]={'readable':True}
        except OSError as error:result[path]={'readable':False,'error_type':type(error).__name__}
    print(json.dumps({'paths':result}),flush=True)
'''
    paths=[ROOT/'scripts/manufacturing_networks.py',ROOT/'scripts/network_ledger.py',receipt_paths[0]]
    for path in paths:
        if not path.read_bytes():raise ValueError('private probe path missing')
    with tempfile.TemporaryDirectory(prefix='network-isolation-probe-') as directory:
        path=Path(directory)/'probe.py';path.write_text(probe_code)
        with isolated_agent(path) as agent:probe_result=agent.decide('probe',dict(paths=[str(p) for p in paths]))
    if any(r.get('readable') or r.get('error_type')!='PermissionError' for r in probe_result['paths'].values()):raise ValueError('network evaluator read boundary failed')
    if fingerprints!=sources():raise ValueError('network implementation changed during qualification')
    if len(topologies)!=8 or any(len(v)!=1 for v in topologies.values()) or len(set(next(iter(v)) for v in topologies.values()))!=8:raise ValueError('structural catalog does not contain eight distinct incidence graphs')
    report=dict(protocol=PROTOCOL,qualification_passed=True,source_sha256=fingerprints,cases=rows,presentations=len(rows),underlying_graph_families=8,
        parameter_draws=2,conditions=3,native_case_count_added=0,exact_runtime_replays=len(rows),exact_isolated_policy_replays=len(rows),
        ledger_mutations_rejected=sum(r['ledger_mutations_rejected'] for r in rows),bad_business_purchases_exercised=sum(r['bad_purchase_exercised'] for r in rows),
        resource_controls_exercised=sum(r['resource_control_exercised'] for r in rows),topology_signatures={k:next(iter(v)) for k,v in topologies.items()},
        isolation=isolation,private_path_probe=probe_result,host_positive_controls=len(paths),
        scope='Public synthetic material-flow network development extension. Exact incidence-graph diversity, integer mass/cash/resource execution, local isolated authored search, separate ledger recurrence and controls. Not a private holdout, calibrated factory physics, independent review, learned-model result or native wheel track.')
    save(output,report);return report


if __name__=='__main__':
    report=qualify();print(json.dumps({k:report[k] for k in ['qualification_passed','presentations','underlying_graph_families','ledger_mutations_rejected','bad_business_purchases_exercised','resource_controls_exercised']}))
