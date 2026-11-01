"""Offline, source-pinned comparator evidence audit. Never produces a ranking.

A publisher result, inspected implementation, and local execution are different
kinds of evidence. Unknown/unassessed dimensions are not counted as absent.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import tomllib
ROOT=Path(__file__).resolve().parents[1]
CACHE=ROOT/'runs/comparator-audit/2026-11-01'
REPORT=ROOT/'reports/comparative-audit.json'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def model_summary(manifest):
    trials=manifest['trials'];ids=[r['task_id'] for r in trials]
    if not trials or len(set(ids))!=len(ids):raise ValueError('missing or duplicate model trial IDs')
    if any(type(r.get('strict_pass')) is not bool for r in trials):raise ValueError('model strict flag must be Boolean')
    scores=[r['score'] for r in trials]
    if any(type(s) not in (int,float) or not 0<=s<=100 for s in scores):raise ValueError('invalid FactoryScore')
    return dict(tasks=len(trials),mean_factory_score=sum(scores)/len(scores),strict_passes=sum(r['strict_pass'] for r in trials),strict_fraction=sum(r['strict_pass'] for r in trials)/len(trials),strict_percent=100*sum(r['strict_pass'] for r in trials)/len(trials),provenance='Recomputed from publisher manifest entries; paid model/Harbor run was not rerun or independently authenticated.')


def tree_paths(name):
    tree=json.loads((CACHE/(name+'-tree.json')).read_text())
    if tree.get('truncated') is not False:raise ValueError(name+': incomplete repository tree')
    return {r['path']:r for r in tree['tree'] if r['type']=='blob'}


def verified_factory_source():
    tree=tree_paths('factory');root=CACHE/'factory-upstream';required={p for p in tree if p.startswith('factorybench/')};observed={str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    if not required<=observed:raise ValueError('missing upstream package source')
    for name in observed:
        blob=(root/name).read_bytes();git_sha=hashlib.sha1(b'blob '+str(len(blob)).encode()+b'\0'+blob).hexdigest()
        if name not in tree or git_sha!=tree[name]['sha']:raise ValueError('upstream file differs from pinned Git blob: '+name)
    execution=json.loads((CACHE/'factory-local-execution.json').read_text())
    if execution['returncode']!=0 or execution['source_unchanged'] is not True:raise ValueError('upstream qualification process did not finish cleanly')
    for name,digest in execution['source_hashes'].items():
        if sha(root/name)!=digest:raise ValueError('upstream source changed since local execution')
    return dict(files=len(observed),package_files=len(required),git_blobs_match=True,execution=execution)


def erp_smoke():
    path=ROOT/'reports/erp-upstream-smoke.json'
    if not path.is_file():return dict(status='not_collected',selected_tasks=0,full_suite_qualified=False,native_faraday_track=False)
    report=json.loads(path.read_text())
    if report['upstream_commit']!='ceba3880af555129b5278e056a0c20f2fb5a0ba9' or report['selected_tasks']!=1 or report['full_suite_qualified'] is not False or report['native_faraday_track'] is not False:raise ValueError('ERP sample scope/commit mismatch')
    if report['collector_sha256']!=sha(ROOT/'scripts/collect_erp_smoke.py'):raise ValueError('ERP collector changed since smoke collection')
    for name,digest in report['artifacts'].items():
        file=(ROOT/name).resolve()
        if not file.is_relative_to(CACHE.resolve()) or sha(file)!=digest:raise ValueError('ERP artifact missing/changed: '+name)
    raw_verdicts={}
    for name in ('noop','oracle','mutated'):
        verdict=json.loads((CACHE/f'erp-{name}/reward.json').read_text())
        raw_verdicts[name]=verdict
        if verdict['overall_score']!=report['verdicts'][name]['score'] or verdict['passed']!=report['verdicts'][name]['passed']:raise ValueError('ERP verdict differs from retained verifier receipt')
    actual_passed=not raw_verdicts['noop']['passed'] and raw_verdicts['oracle']['passed'] and not raw_verdicts['mutated']['passed'] and bool(report['mutation']['cancelled_purchase_order_ids']) and all(report['container_source_matches'].values())
    if report['controlled_smoke_passed']!=actual_passed:raise ValueError('ERP smoke conclusion differs from retained controls')
    return dict(status='controlled_compatibility_smoke',selected_tasks=1,full_suite_qualified=False,native_faraday_track=False,controlled_smoke_passed=report['controlled_smoke_passed'],verdicts=report['verdicts'],original_build_passed=report['original_build_passed'],runtime_overlay=True,receipt_sha256=sha(path))


def build_report():
    spec=importlib.util.spec_from_file_location('capture_sources',ROOT/'scripts/capture_comparator_sources.py');collector=importlib.util.module_from_spec(spec);spec.loader.exec_module(collector)
    config=collector.validate_sources(json.loads(collector.CONFIG.read_text()));inventory=json.loads(collector.REPORT.read_text());errors=collector.check_inventory(config,inventory)
    if errors:raise ValueError('; '.join(errors))
    sources={r['id']:r for r in inventory['sources']}
    needed={'erp-tree','erp-dataset','erp-runtime','factory-tree','factory-qualification','factory-model-manifest','assetops-readme','assetops-repository','neuralcad-readme','benchcad-readme','lark-article'}
    if not needed<=sources.keys() or any(sources[k]['status']!='available' for k in needed):raise ValueError('required comparator evidence unavailable; capability remains unknown')
    native=json.loads((ROOT/'reports/release-audit.json').read_text())
    if not native['passed'] or len(native['tracks'])!=9 or not native['isolation']['passed']:raise ValueError('native qualification evidence failed')
    pinned=verified_factory_source();qualified=json.loads((CACHE/'factory-local-qualification.json').read_text());published=json.loads((CACHE/'factory-qualification.source').read_text())
    if qualified!=published or not qualified['qualification_passed']:raise ValueError('local upstream qualification differs from publisher release')
    erp_tree=tree_paths('erp');erp_count=sum(bool(re.fullmatch(r'tasks/[^/]+/task.toml',p)) for p in erp_tree)
    dataset=tomllib.loads((CACHE/'erp-dataset.source').read_text());erp_patterns=len(dataset['entries']);configured=sum(e['count'] for e in dataset['entries'])
    if erp_count!=300 or configured!=erp_count or erp_patterns!=29:raise ValueError('ERP source counts changed; review comparison')
    factory_count=sum(bool(re.fullmatch(r'benchmark/factorybench100/tasks/factorybench-\d{3}.json',p)) for p in tree_paths('factory'))
    model=model_summary(json.loads((CACHE/'factory-model-manifest.source').read_text()))
    if factory_count!=qualified['task_count'] or model['tasks']!=factory_count:raise ValueError('Factory task/model coverage mismatch')
    lark=(CACHE/'lark-article.source').read_text();lark_claims=all(k in lark for k in ('160 books','26 simulated weeks','15–30 products'))
    if not lark_claims:raise ValueError('Lark snapshot differs; review current source')
    about=json.loads((CACHE/'assetops-repository.source').read_text())['description'];readme=(CACHE/'assetops-readme.source').read_text()
    mismatch='460+' in about and '141+' in readme
    native_manifest=json.loads((ROOT/'manifest.json').read_text());smoke=erp_smoke()
    from audit_expanded_comparators import check as check_expanded,REPORT as EXPANDED_REPORT
    expanded=check_expanded();expanded_record=json.loads(EXPANDED_REPORT.read_text())
    return dict(schema='comparative-audit/1',assessment_date='2026-11-01',scope='Six selected specialist comparators, not an exhaustive world survey. Evidence review and one locally reproduced upstream qualification; no cross-benchmark model ranking.',
        native=dict(version=native_manifest['version'],manifest_sha256=sha(ROOT/'manifest.json'),release_audit_sha256=sha(ROOT/'reports/release-audit.json'),tracks={k:v['cases'] for k,v in native['tracks'].items()},count_units='Qualification rows per track; seasons are 108 policy episodes across 12 factories. Track counts are not additive independent skills.',isolation_episodes=native['isolation']['episodes'],separate_erp_compatibility=native.get('erp_compatibility'),evidence='Current-source author/reference controls. No full-suite matched-budget learned-model result.'),
        expanded_survey=dict(integrity_passed=expanded['integrity_passed'],named_resources=expanded_record['named_resources_reviewed'],additional_named_resources=expanded_record['additional_named_resources'],semikong_author_qualification_reproduced=expanded_record['semikong']['local_author_qualification_passed'],businessbench_status=expanded_record['businessbench']['status'],report_sha256=sha(EXPANDED_REPORT)),
        repositories=config['repositories'],source_inventory_sha256=sha(collector.REPORT),
        erp_bench=dict(tasks=erp_count,task_patterns=erp_patterns,configured_tasks=configured,runtime='Odoo 19 declared in pinned Dockerfile',local_runtime_qualification=smoke,solver_claim='CP-SAT-backed generation/optimal plans described by publisher and inspected source; all 300 optimality certificates were not independently re-proved.'),
        factorybench=dict(tasks=factory_count,release=qualified['version'],local_qualification_passed=qualified['qualification_passed'],oracle=qualified['oracle'],determinism=qualified['determinism'],executions=qualified['executions'],mutation_omissions=qualified['mutation_omissions'],source_integrity={k:pinned[k] for k in ('files','package_files','git_blobs_match')},local_execution_sha256=sha(CACHE/'factory-local-execution.json'),local_qualification_sha256=sha(CACHE/'factory-local-qualification.json'),publisher_model_manifest=model),
        assetops=dict(publisher_count_scopes_unreconciled=mismatch,readme_count='141+' if '141+' in readme else 'review needed',repository_about_count='460+' if '460+' in about else 'review needed',comparable_scenario_count=None,note='Different/mixed publisher count scopes are not reconciled by this audit; do not select the larger number for ranking. MCP/domain documentation inspected; full environment/model evaluation not rerun.'),
        neuralcad=dict(publisher_requests=192,publisher_expert_edits=384,evidence='Pinned access/harness README plus publisher expert/human evaluation documentation; no full data or human evaluation rerun.'),
        benchcad=dict(publisher_programs=17900,publisher_families=106,evidence='Pinned README and versioned paper; CAD task structure inspected at source level, not full runtime/model reproduction.'),
        larkbench=dict(publisher_books=160,publisher_draws_per_book=3,publisher_weeks=26,publisher_products_per_book=[15,30],evidence='Publisher article retrieved over HTTPS and hashed. Hidden books and model claims were not independently evaluated.'),
        conclusion=dict(world_superlative_established=False,matched_budget_model_comparison=False,independent_practitioner_validation=False,structurally_distinct_private_native_holdout=False,upstream_full_runtime_reproduction=False),
        audit_inputs={str(p.relative_to(ROOT)):sha(p) for p in [Path(__file__).resolve(),ROOT/'docs/comparators/sources.json',ROOT/'scripts/capture_comparator_sources.py',ROOT/'scripts/run_factory_comparator.py',ROOT/'scripts/collect_erp_smoke.py']})


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    try:report=build_report()
    except (OSError,KeyError,TypeError,ValueError) as exc:print(json.dumps(dict(integrity_passed=False,error=str(exc))));return 1
    if args.check:
        if json.loads(REPORT.read_text())!=report:print('Comparative report is stale.');return 1
    else:REPORT.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps(dict(integrity_passed=True,comparators=report['expanded_survey']['named_resources'],locally_reproduced_upstream_qualifications=1+int(report['expanded_survey']['semikong_author_qualification_reproduced']),superlative_established=False)));return 0

if __name__=='__main__':raise SystemExit(main())
