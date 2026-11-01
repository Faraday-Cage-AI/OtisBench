"""Conservative structural inventory of the native workflow development generator.

Counts dependency topology, named processes and control equations separately.
It can reject known lineage overlap; it cannot certify new industrial semantics,
case secrecy, optimizer isolation or a private held-out evaluation.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from faraday_manufacturing_benchmark.shopfloor_cases import catalog,build_records,ROUTES,DISRUPTIONS

ROOT=Path(__file__).resolve().parents[1]
PROTOCOL='workflow-development-lineage/1'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n')


def chain_signature(records):
    """Exact chain canonicalization, invariant to IDs, row order and numeric draws.

    This deliberately fails closed for non-chain graphs. The current generator
    has one predecessor per operation and at most one child; arbitrary DAG
    isomorphism or physical process equivalence is not claimed.
    """
    route=records['PLM']['route'];instructions=records['PLM']['instructions']
    if not isinstance(route,list) or not 1<=len(route)<=32:raise ValueError('unsupported route size')
    nodes={node['id']:node for node in route}
    if len(nodes)!=len(route) or set(instructions)!=set(nodes):raise ValueError('duplicate or missing operation/instruction identity')
    roots=[];children=defaultdict(list)
    for node in route:
        previous=node['predecessor']
        if previous is None:roots.append(node['id'])
        elif previous not in nodes or previous==node['id']:raise ValueError('invalid predecessor')
        else:children[previous].append(node['id'])
    if len(roots)!=1 or any(len(group)>1 for group in children.values()):raise ValueError('non-chain graph requires a separate structural analysis')
    ordered=[];seen=set();current=roots[0]
    while current is not None:
        if current in seen:raise ValueError('route cycle')
        seen.add(current);ordered.append(current);current=children[current][0] if children[current] else None
    if len(seen)!=len(nodes):raise ValueError('disconnected or cyclic route')
    processes=[nodes[key]['process'] for key in ordered]
    # Both the control archetype and actual authored rule text are retained.
    # Numbers, seed, material/product names and aliases are intentionally absent.
    controls=[dict(control_kind=instructions[key]['control_kind'],rule=instructions[key]['rule']) for key in ordered]
    return dict(topology=dict(nodes=len(ordered),edges=[[i-1,i] for i in range(1,len(ordered))]),
        process_sequence=processes,control_sequence=controls,
        topology_sha256=digest(dict(nodes=len(ordered),edges=[[i-1,i] for i in range(1,len(ordered))])),
        process_sha256=digest(processes),control_sha256=digest(controls))


def inventory():
    groups={name:defaultdict(list) for name in ('topology','process','control','control_disruption')}
    rows=[];controls={};families=defaultdict(set)
    for task in catalog():
        signature=chain_signature(build_records(task));control=signature['control_sha256']
        keys=dict(topology=signature['topology_sha256'],process=signature['process_sha256'],control=control,
                  control_disruption=digest([control,task['disruption']]))
        for name,key in keys.items():groups[name][key].append(task['id'])
        controls[control]=signature['control_sequence'];families[control].add(task['family'])
        rows.append(dict(task_id=task['id'],family=task['family'],disruption=task['disruption'],draw=task['draw'],**{k+'_sha256':v for k,v in keys.items()}))
    # This is a public development partition suggestion, never a secret holdout.
    ordered=sorted(groups['control'],key=lambda key:digest(['control-sequence-development-partition-v1',key]))
    n=len(ordered);a=int(n*.6);b=a+int(n*.2)
    partitions={key:'development_train' if i<a else 'development_validation' if i<b else 'development_test' for i,key in enumerate(ordered)}
    split_counts={name:dict(cases=0,control_sequences=0) for name in ('development_train','development_validation','development_test')}
    for key,split in partitions.items():split_counts[split]['control_sequences']+=1
    for row in rows:row['suggested_public_development_partition']=partitions[row['control_sha256']];split_counts[row['suggested_public_development_partition']]['cases']+=1
    report=dict(protocol=PROTOCOL,source_sha256={str(path.relative_to(ROOT)):sha(path) for path in [Path(__file__),ROOT/'src/faraday_manufacturing_benchmark/shopfloor_cases.py',ROOT/'src/faraday_manufacturing_benchmark/shopfloor.py']},
        development_cases=len(rows),named_route_families=len(ROUTES),declared_disruption_contracts=len(DISRUPTIONS),
        released_route_topologies=len(groups['topology']),named_process_sequences=len(groups['process']),released_route_control_sequences=len(groups['control']),
        control_sequence_disruption_groups=len(groups['control_disruption']),
        three_way_released_route_topology_disjoint_partition_possible=len(groups['topology'])>=3,
        control_alias_groups=[dict(control_sha256=key,families=sorted(families[key]),control_sequence=controls[key],cases=len(groups['control'][key])) for key in sorted(controls)],
        topology_groups=[dict(topology_sha256=key,cases=len(tasks)) for key,tasks in sorted(groups['topology'].items())],
        suggested_public_development_partition=split_counts,cases=rows,
        private_holdout_established=False,
        limitations=['Exact released-production-route topology/control-rule inventory only; not whole-world workflow topology, rework logic, fault causality or full dynamic equivalence.',
            'Disruption names identify authored contracts; their inclusion in a hash does not prove genuinely novel fault semantics.',
            'Named processes/materials are not independently validated process physics. Repeated generic control rules can occur under different industrial route names.',
            'Public development partitions keep all control-sequence aliases, disruption variants and draws together, but are public and reuse known control/fault mechanisms.',
            'Hash separation cannot establish unseen workflows, independent expertise, secrecy or optimizer access separation.'])
    return report


def overlap(candidate,report):
    if not isinstance(candidate,dict) or not isinstance(candidate.get('family'),str) or candidate['family'] not in ROUTES or candidate.get('disruption') not in DISRUPTIONS:
        raise ValueError('unsupported candidate generator/semantics; no novelty certificate is issued')
    if type(candidate.get('seed')) is not int:raise ValueError('candidate requires an integer generator seed')
    task=deepcopy(candidate);task.setdefault('draw',0)
    signature=chain_signature(build_records(task))
    matched=[row['task_id'] for row in report['cases'] if row['control_sha256']==signature['control_sha256']]
    if not matched:raise ValueError('unassessed control sequence; manual review required, not automatic final admission')
    return dict(protocol=PROTOCOL,candidate_commitment=digest(candidate),known_development_control_overlap=True,
        matching_development_cases=len(matched),final_holdout_admitted=False,
        reason='Candidate reuses a disclosed control-equation sequence. Renaming, reseeding or changing quantities does not establish a distinct released-route/control structure.',
        scope='Conservative overlap rejection under the existing generator. No new case, private holdout, model result or independent validation.')


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    audit=sub.add_parser('inventory');audit.add_argument('--output',default='reports/workflow-lineage.json');audit.add_argument('--check',action='store_true')
    candidate=sub.add_parser('overlap');candidate.add_argument('--candidate',required=True);candidate.add_argument('--output',required=True)
    args=p.parse_args();report=inventory()
    if args.command=='inventory':
        if args.check:
            if json.loads(Path(args.output).read_text())!=report:raise ValueError('lineage inventory is stale')
        else:save(args.output,report)
        print(json.dumps({k:report[k] for k in ['development_cases','named_route_families','released_route_topologies','named_process_sequences','released_route_control_sequences','control_sequence_disruption_groups','private_holdout_established']}))
    else:
        result=overlap(json.loads(Path(args.candidate).read_text()),report);save(args.output,result);print(json.dumps(result))


if __name__=='__main__':main()
