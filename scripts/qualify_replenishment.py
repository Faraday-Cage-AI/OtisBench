"""Qualify and freeze public synthetic replenishment controls; no model calls."""
from __future__ import annotations

from copy import deepcopy
import argparse
import json
from pathlib import Path
import subprocess
import sys

from replenishment_benchmark import ROOT, FAMILIES, World, build, catalog, digest, landed, plan_checks, replay, save, sha, startup

SOURCES = ['scripts/replenishment_benchmark.py', 'scripts/qualify_replenishment.py', 'examples/replenishment_agent.py']


def exact_award(public, ignore=()):
    """Separate evaluator enumerates all subsets; it does not call policy code."""
    feasible = []
    lots = public['lots']
    for mask in range(1 << len(lots)):
        selected = [lot['id'] for index, lot in enumerate(lots) if mask & (1 << index)]
        if all(plan_checks(public, selected, ignore=ignore).values()):
            feasible.append((sum(landed(lot) for lot in lots if lot['id'] in selected), tuple(sorted(selected))))
    if not feasible: raise ValueError('generated fixture has no feasible award')
    cost, ids = min(feasible)
    return dict(lots=list(ids), cost_cents=cost, subsets_examined=1 << len(lots), feasible_awards=len(feasible))


def call_policy(observation):
    result = subprocess.run([sys.executable, '-I', str(ROOT/'examples/replenishment_agent.py')],
        input=json.dumps(observation), text=True, capture_output=True, timeout=15,
        cwd=ROOT, env={'LANG': 'C.UTF-8'})
    if result.returncode: raise ValueError(f'public policy failed: {result.stderr[-1000:]}')
    return json.loads(result.stdout)


def prepare(config):
    world = World(config)
    # Fixed observation cadence in every case; policy receives only revealed state.
    world.act(dict(tool='advance', arguments=dict(to=1)))
    return world


def ignored_rule(family):
    return dict(quality_yield='coverage', safety_stock='coverage', demand_surge='coverage', landed_cost=None).get(family, family)


def rule_witness(task, config, public, exact):
    family=task['family']; relaxed_public=deepcopy(public); rule=ignored_rule(family)
    if family=='demand_surge': relaxed_public['demand']=config['initial_demand']; rule=None
    elif family=='safety_stock': relaxed_public['reserve']=0; rule=None
    elif family=='quality_yield':
        for lot in relaxed_public['lots']: lot['yield_units']=lot['quantity']
        rule=None
    elif family=='landed_cost':
        for lot in relaxed_public['lots']: lot.update(fx_numerator=100,freight_cents=0,duty_cents=0)
        rule=None
    relaxed=exact_award(relaxed_public,ignore=(rule,) if rule else ())
    checks=plan_checks(public,relaxed['lots'])
    cost=sum(landed(lot) for lot in config['lots'] if lot['id'] in relaxed['lots'])
    witness=dict(relaxed=relaxed,original_checks=checks,original_cost_cents=cost,
        rejected_by_original_constraints=not all(checks.values()),more_expensive_under_true_landed_cost=cost>exact['cost_cents'])
    if not (witness['rejected_by_original_constraints'] or witness['more_expensive_under_true_landed_cost']):
        raise ValueError(f'named rule has no separating witness: {task}')
    return witness


def negative_trace(config, actions, label):
    broken=prepare(config); changed=False
    for original in actions:
        action=deepcopy(original)
        if label=='no_purchase' and action['tool']=='award': continue
        if label=='skip_ship' and action['tool']=='ship': continue
        if label=='skip_pay' and action['tool']=='pay': continue
        if not changed and label=='short_receipt' and action['tool']=='receive':
            action['arguments']['quantity']-=1; changed=True
        if not changed and label=='wrong_payment' and action['tool']=='pay':
            action['arguments']['amount_cents']+=1; changed=True
        broken.act(action)
    return dict(rejected=not broken.grade()['strict_success'],verdict=broken.grade(),trace=broken.trace)


def run(output):
    output = Path(output)
    if output.exists(): raise ValueError('refusing to overwrite retained development evidence')
    output.mkdir(parents=True)
    cases = []
    public_files = {}
    for task in catalog():
        config = build(task); world = prepare(config); observation = world.observe()
        solved = call_policy(observation); exact = exact_award(observation['public'])
        if solved['selection'] != {key: exact[key] for key in ('lots', 'cost_cents')}:
            raise ValueError('independent exact award and public policy differ')
        for action in solved['actions']:
            response = world.act(action)
            if not response['ok']: raise ValueError(f'control action failed {task}: {response}')
        verdict = world.grade()
        if not verdict['strict_success'] or verdict['landed_cost_cents'] != exact['cost_cents']:
            raise ValueError(f'control did not qualify {task}')
        if replay(config, world.trace) != verdict: raise ValueError('fresh exact replay differs')
        # Public policy is invoked again from an identical observation, not assumed deterministic.
        repeat = call_policy(observation)
        if repeat != solved: raise ValueError('policy output replay differs')
        negative = {}
        for label in ('no_purchase', 'short_receipt', 'wrong_payment', 'skip_ship', 'skip_pay'):
            negative[label]=negative_trace(config,solved['actions'],label)
            if not negative[label]['rejected']: raise ValueError(f'negative control accepted: {label}')
        # Is the named commercial rule operational in this fixture? A cheaper
        # relaxed solution must fail the original constraints. Dynamic demand,
        # yield/reserve and landed-cost objectives use explicit alternatives.
        family=task['family']; witness=rule_witness(task,config,observation['public'],exact)
        receipt = dict(task=task, config_sha256=digest(config), config=config, initial_public=startup(config),
                       policy_observation=observation, policy_output=solved, exact=exact, trace=world.trace,
                       result=verdict, exact_replay=True, policy_replay=True, negative_controls=negative, rule_witness=witness)
        receipt_path=output/'receipts'/f"{task['id']}.json"; save(receipt_path,receipt)
        case_dir=output/'public'/task['id']; save(case_dir/'initial.json', startup(config))
        save(case_dir/'epoch-1.json',observation)
        for path in (case_dir/'initial.json',case_dir/'epoch-1.json'):
            public_files[str(path.relative_to(output/'public'))] = sha(path)
        cases.append(dict(task=task['id'], family=family, draw=task['draw'], receipt=str(receipt_path.relative_to(ROOT)),
                          strict_success=True, cost_cents=verdict['landed_cost_cents'], negative_controls_rejected=len(negative)))
    save(output/'public/manifest.json',dict(protocol='synthetic-replenishment-public/1',files=public_files,
        development_only=True,case_count=len(cases),structural_contracts=len(FAMILIES),native_case_count_added=0,
        note='Public initial and observed epoch-1 states. No solutions or private future-event records. All cases are public development, not private holdout.'))
    report=dict(protocol='synthetic-replenishment-qualification/1', passed=True, cases=cases,
        development_cases=len(cases), structural_contracts=list(FAMILIES), draws_per_contract=8,
        strict_successes=len(cases), exact_replays=len(cases), public_policy_replays=len(cases),
        negative_controls_rejected=sum(row['negative_controls_rejected'] for row in cases),
        native_case_count_added=0, source_sha256={name:sha(ROOT/name) for name in SOURCES},
        public_manifest=str((output/'public/manifest.json').relative_to(ROOT)),
        public_manifest_sha256=sha(output/'public/manifest.json'),
        scope='Author controls in a synthetic fixed-lot, two-component, single-plant development extension. No learned-model evaluation, OS isolation claim, authentic supplier data, calibrated economics, multi-echelon optimizer, private holdout or independent validation.')
    save(output/'qualification.json',report)
    return report


def audit(report_path):
    report=json.loads(Path(report_path).read_text())
    if report['native_case_count_added'] != 0 or report['structural_contracts'] != list(FAMILIES): raise ValueError('scope promoted or contract changed')
    for name, expected in report['source_sha256'].items():
        if sha(ROOT/name) != expected: raise ValueError('source changed')
    if set(report['source_sha256']) != set(SOURCES): raise ValueError('source closure incomplete')
    manifest_path=ROOT/report['public_manifest']
    if sha(manifest_path) != report['public_manifest_sha256']: raise ValueError('public manifest changed')
    manifest=json.loads(manifest_path.read_text())
    expected_files=set()
    if [row['task'] for row in report['cases']] != [task['id'] for task in catalog()]: raise ValueError('incomplete development catalog')
    for row, task in zip(report['cases'],catalog(),strict=True):
        path=ROOT/row['receipt']; receipt=json.loads(path.read_text()); config=build(task)
        if receipt['task']!=task or receipt['config']!=config or receipt['config_sha256']!=digest(config): raise ValueError('fixture differs')
        observation=prepare(config).observe()
        if receipt['initial_public']!=startup(config) or receipt['policy_observation']!=observation: raise ValueError('public state differs')
        exact=exact_award(observation['public'])
        if receipt['exact']!=exact or receipt['policy_output']['selection']!={k:exact[k] for k in ('lots','cost_cents')}: raise ValueError('exact award differs')
        if call_policy(observation)!=receipt['policy_output'] or receipt['exact_replay'] is not True or receipt['policy_replay'] is not True: raise ValueError('public policy differs')
        if [entry['action'] for entry in receipt['trace'][1:]]!=receipt['policy_output']['actions']: raise ValueError('policy trajectory differs')
        if replay(config,receipt['trace'])!=receipt['result'] or not receipt['result']['strict_success']: raise ValueError('positive replay failed')
        if not row['strict_success'] or row['cost_cents']!=receipt['result']['landed_cost_cents'] or row['negative_controls_rejected']!=5: raise ValueError('summary differs')
        if set(receipt['negative_controls'])!={'no_purchase','short_receipt','wrong_payment','skip_ship','skip_pay'}: raise ValueError('negative control missing')
        for label,negative in receipt['negative_controls'].items():
            if negative!=negative_trace(config,receipt['policy_output']['actions'],label): raise ValueError('targeted negative trajectory differs')
            if replay(config,negative['trace'])!=negative['verdict'] or negative['verdict']['strict_success'] or not negative['rejected']: raise ValueError('negative replay failed')
        if receipt['rule_witness']!=rule_witness(task,config,observation['public'],exact): raise ValueError('commercial witness changed')
        for filename,value in [('initial.json',startup(config)),('epoch-1.json',observation)]:
            relative=f"{task['id']}/{filename}"; expected_files.add(relative); public_path=manifest_path.parent/relative
            if json.loads(public_path.read_text())!=value or sha(public_path)!=manifest['files'][relative]: raise ValueError('public bundle differs')
    if set(manifest['files'])!=expected_files: raise ValueError('public file closure differs')
    n=len(catalog())
    for key,value in dict(passed=True,development_cases=n,strict_successes=n,exact_replays=n,public_policy_replays=n,negative_controls_rejected=n*5,draws_per_contract=8).items():
        if report[key]!=value: raise ValueError('aggregate differs')
    return dict(integrity_passed=True,development_cases=n,structural_contracts=len(FAMILIES),strict_successes=n,
        negative_controls_rejected=n*5,native_case_count_added=0,report_sha256=sha(report_path),scope=report['scope'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('command',choices=['run','audit'])
    p.add_argument('--output-dir',default='runs/replenishment-development-v1');p.add_argument('--report');args=p.parse_args()
    if args.command=='run':
        result=run(ROOT/args.output_dir); print(json.dumps({key:result[key] for key in ('passed','development_cases','strict_successes','negative_controls_rejected')}))
    else:
        result=audit(ROOT/(args.report or f'{args.output_dir}/qualification.json'))
        save(ROOT/'reports/replenishment-audit.json',result);print(json.dumps(result))
