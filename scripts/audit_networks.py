"""Current-source network receipts, fresh runtime/policy replay and ledger controls."""
from collections import Counter
import argparse
import json
from pathlib import Path
from manufacturing_networks import ROOT,PROTOCOL,World,catalog,build,digest,sha,save
from network_topology import canonical
from qualify_networks import sources,execute,ledger_mutations,bad_business_purchase,AGENT
from faraday_manufacturing_benchmark.isolation import isolated_agent,POLICY_VERSION


def audit(report_path,output):
    report_path=Path(report_path).resolve();report=json.loads(report_path.read_text())
    if report['protocol']!=PROTOCOL or report['qualification_passed'] is not True or report['source_sha256']!=sources():raise ValueError('stale or unsupported network qualification')
    tasks={t['id']:t for t in catalog()};rows=report['cases']
    if len(rows)!=len(tasks) or {r['task_id'] for r in rows}!=set(tasks):raise ValueError('case coverage changed')
    if report['isolation']['policy_version']!=POLICY_VERSION or report['isolation']['agent_sha256']!=sha(AGENT) or report['isolation']['network']!='denied':raise ValueError('policy isolation metadata inconsistent')
    paths=report['private_path_probe']['paths']
    if len(paths)!=3 or report['host_positive_controls']!=3 or any(r.get('readable') or r.get('error_type')!='PermissionError' for r in paths.values()):raise ValueError('private-file probe inconsistent')
    audited=[];graphs={};conditions=Counter();corruptions=bad_controls=0
    with isolated_agent(AGENT) as agent:
        for row in rows:
            path=(ROOT/row['receipt']).resolve()
            if not path.is_relative_to(ROOT) or sha(path)!=row['receipt_sha256']:raise ValueError('receipt changed')
            receipt=json.loads(path.read_text());task=tasks[row['task_id']];config=build(task)
            if receipt['task']!=task or receipt['config']!=config or receipt['config_sha256']!=digest(config):raise ValueError('scenario identity changed')
            payload=World(config).public()
            if receipt['payload']!=payload:raise ValueError('public payload inconsistent')
            response=agent.decide('manufacturing_network',payload)
            if response!=receipt['response']:raise ValueError('fresh isolated policy response differs')
            world,result,ledger=execute(config,response['actions'])
            if world.trace!=receipt['trace'] or world.state()!=receipt['final_state'] or result!=receipt['result'] or ledger!=receipt['ledger']:raise ValueError('fresh runtime replay differs')
            if not result['strict_success'] or not all(world.used.values()):raise ValueError('positive control failed or a declared recipe was unexercised')
            if not receipt['exact_runtime_replay'] or receipt['replay_ledger']!=ledger:raise ValueError('retained runtime replay inconsistent')
            mutations=ledger_mutations(config,world,result)
            if mutations!=receipt['ledger_mutations'] or len(mutations)!=8:raise ValueError('ledger corruption coverage inconsistent')
            wrong=bad_business_purchase(config,response['actions'])
            if wrong!=receipt['bad_business_purchase']:raise ValueError('accepted bad-purchase control differs')
            topology=canonical(config)
            if receipt['topology']!=topology:raise ValueError('graph commitment inconsistent')
            graphs.setdefault(task['family'],set()).add(topology['signature']);conditions[task['condition']]+=1
            if row['strict_success'] is not True or row['ledger_mutations_rejected']!=8 or row['bad_purchase_exercised']!=wrong['exercised'] or row['actions']!=len(world.trace) or row['expanded_states']!=response['expanded_states']:raise ValueError('case summary inconsistent')
            # Fresh no-op, dependency and supplier-bound controls, with no state mutation.
            noop=World(config);noop.act(dict(tool='finish',arguments={}))
            if noop.grade()!=receipt['noop_result'] or noop.grade()['score']!=0:raise ValueError('no-op control differs')
            probe=World(config);before=probe.state()
            for action in [dict(tool='start',arguments=dict(recipe_id=config['recipes'][-1]['id'])),dict(tool='buy',arguments=dict(offer_id=config['offers'][0]['id'],quantity=config['offers'][0]['capacity']+1))]:
                if probe.act(action)['ok'] or probe.state()!=before:raise ValueError('rejected business constraint changed state')
            if receipt['missing_input_rejected'] is not True or receipt['supplier_capacity_rejected'] is not True:raise ValueError('recorded constraint controls inconsistent')
            resource_exercised=False;probe=World(config)
            for action in response['actions']:
                probe.act(action)
                candidates=[r for r in config['recipes'] if probe.used[r['id']]<r['max_batches'] and all(probe.stock[n]>=q for n,q in r['inputs'].items()) and probe.cash>=r['cost_cents'] and any(j.get('resource')==r['resource'] for j in probe.pending)]
                if candidates:
                    before=probe.state();attempt=probe.act(dict(tool='start',arguments=dict(recipe_id=candidates[0]['id'])))
                    if attempt['ok'] or attempt['error']!='resource is busy' or probe.state()!=before:raise ValueError('resource-only control failed')
                    resource_exercised=True;break
            if row['resource_control_exercised']!=resource_exercised or receipt['resource_control'].get('exercised')!=resource_exercised:raise ValueError('resource control coverage inconsistent')
            corruptions+=len(mutations);bad_controls+=wrong['exercised']
            audited.append(dict(task_id=task['id'],receipt_sha256=row['receipt_sha256'],fresh_response_sha256=digest(response),
                exact_runtime_replay=True,exact_isolated_policy_replay=True,ledger_passed=True,resource_control_exercised=resource_exercised))
    if any(len(v)!=1 for v in graphs.values()) or len(set(next(iter(v)) for v in graphs.values()))!=8:raise ValueError('structural graph inventory inconsistent')
    signatures={k:next(iter(v)) for k,v in graphs.items()}
    if report['topology_signatures']!=signatures or report['ledger_mutations_rejected']!=corruptions or report['bad_business_purchases_exercised']!=bad_controls or report['resource_controls_exercised']!=sum(r['resource_control_exercised'] for r in audited):raise ValueError('aggregate qualification inconsistent')
    result=dict(passed=True,development_cases=len(audited),incidence_graph_families=len(graphs),condition_cases=dict(conditions),
        exact_runtime_replays=len(audited),exact_fresh_isolated_policy_replays=len(audited),ledger_mutations_rejected=corruptions,
        accepted_bad_purchases_failed=bad_controls,resource_only_controls=sum(r['resource_control_exercised'] for r in audited),
        qualification_sha256=sha(report_path),auditor_sha256=sha(__file__),cases=audited,native_case_count_added=0,
        scope='Fresh local in-memory runtime and isolated authored-policy replay plus separate ledger recurrence/corruption controls. No factory integration, scientific independence, private holdout or learned-model result.')
    save(output,result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--report',default='reports/network-qualification-v2.json');p.add_argument('--output',default='reports/network-audit-v2.json');a=p.parse_args()
    r=audit(a.report,a.output);print(json.dumps({k:r[k] for k in ['passed','development_cases','incidence_graph_families','ledger_mutations_rejected','accepted_bad_purchases_failed','resource_only_controls']}))
