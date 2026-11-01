"""Federate current native/extension evidence without additive scope inflation."""
from __future__ import annotations
from datetime import datetime,timezone
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
NATIVE={'workflow','engineering','supply-chain','procurement','sensors','cad','execution','seasons','documents'}
EXTENSIONS={'supplier_formats','supplier_scans_original','supplier_scan_policy','hydraulic_conditions','material_networks','erp_invoices','replenishment','visual_inspection'}


def read(path):return json.loads(Path(path).read_text())
def sha(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n')
def local(name):
    path=(ROOT/name).resolve()
    if not path.is_relative_to(ROOT):raise ValueError('evidence path escapes checkout')
    return path


def require(ok,message):
    if not ok:raise ValueError(message)


def derive(native,extensions,erp,comparative,lineage,relations):
    """Count/claim policy; inputs must first pass their component validators."""
    require(set(native['tracks'])==NATIVE and native['passed'],'complete nine-track native evidence required')
    require(set(extensions)==EXTENSIONS,'missing or unexpected declared extension')
    require(all(e['evidence_integrity_passed'] is True for e in extensions.values()),'extension evidence integrity failed')
    require(relations['format_source_ids']==relations['scan_source_ids']==relations['native_document_scenario_ids'],'document presentations do not map to the same native scenarios')
    require(len(relations['native_document_scenario_ids'])==16,'unexpected document scenario coverage')
    require(set(relations['invoice_case_ids'])<=set(relations['erp_selected_ids']) and set(relations['compatibility_case_ids'])<=set(relations['erp_selected_ids']),'ERP extension selection is outside pinned catalog')
    require(len(relations['erp_selected_ids'])==len(set(relations['erp_selected_ids']))==300 and erp['selected_cases']==300,'ERP catalog selection incomplete or duplicated')
    require(set(erp['failed_cases'])<=set(relations['erp_selected_ids']),'unknown failed ERP case')
    require(erp['patterns_total']==29 and 0<=erp['patterns_with_qualified_case']<=29,'invalid ERP pattern coverage')
    require(all(type(row['cases']) is int and row['cases']>0 for row in native['tracks'].values()),'invalid native qualification row unit')
    require(0<=erp['qualified_cases']<=erp['resolved_cases']<=300,'inconsistent ERP completion counts')
    require(len(set(erp['failed_cases']))==erp['resolved_cases']-erp['qualified_cases'],'ERP failed count contradicts resolved/qualified')
    require(comparative['conclusion']['world_superlative_established'] is False,'selected-comparator review cannot certify a worldwide superlative')
    require(lineage['private_holdout_established'] is False,'private holdout provenance requires separate evidence')
    # Integrity is distinct from control success: the original scan run has 0
    # passing controls, while its frozen data/results can be fully auditable.
    require(extensions['supplier_scans_original']['strict_successes']==0,'original scan outcomes changed; review the reporting contract')
    require(0<=extensions['supplier_scan_policy']['strict_successes']<=48,'invalid scan policy result')
    for name in ['supplier_formats','supplier_scans_original','supplier_scan_policy','erp_invoices']:
        require(extensions[name]['new_business_scenarios']==0,'matched presentations/upstream subsets cannot add business scenarios')
    require(all(e['native_case_count_added']==0 for e in extensions.values()),'extensions must not be silently promoted into native totals')
    tracks={name:dict(qualification_rows=native['tracks'][name]['cases'],evidence='current-source authored qualification',score_unit='separate track strict success; never pooled') for name in sorted(NATIVE)}
    tracks['documents'].update(underlying_business_scenarios=16,pdf_presentations=32)
    tracks['seasons'].update(factory_templates=12,qualification_policy_episodes=108,parameter_draws=3,policies=3)
    tracks['workflow'].update(named_routes=lineage['named_route_families'],released_route_topologies=lineage['released_route_topologies'],route_control_sequences=lineage['released_route_control_sequences'])
    full_erp=erp['resolved_cases']==300 and erp['qualified_cases']==300 and not erp['failed_cases']
    gates=dict(current_native_evidence='met',current_declared_extension_evidence='met',selected_comparator_evidence='met',
        full_erp_author_qualification='met' if full_erp else 'contradicted_by_retained_failure' if erp['failed_cases'] else 'incomplete',
        matched_budget_full_suite_models='unproven',independent_practitioner_validation='unproven',
        structurally_distinct_private_holdout='unproven',exhaustive_worldwide_comparator_survey='not_established')
    return dict(native_tracks=tracks,extensions=extensions,erp_catalog=erp,completion_gates=gates,comparison_universe=dict(named_resources=comparative.get('expanded_survey',{}).get('named_resources',6),exhaustive_world_survey=False),
        document_overlap=dict(underlying_native_scenarios=16,format_presentations=48,scan_presentations=48,scan_policy_evaluates_same_scan_presentations=True,new_business_scenarios=0),
        erp_overlap=dict(unique_selected_upstream_cases=300,invoice_controls_subset_of_catalog=True,selected_compatibility_subset_of_catalog=True,extra_cases_from_subsets=0),
        count_policy='No additive total: qualification episodes, scenarios, matched presentations, measurement cycles, upstream subsets and graph families have different units.',
        conclusion=dict(evidence_integrity_passed=True,all_control_presentations_successful=False,world_superlative_established=False,
            reason='Current-source integrity is established for the declared collection. Remaining failures, external validation/model/holdout gaps and the selected comparison universe do not establish the requested unqualified superlative.'))


def extension_rows(formats,raw_report,scan_report,hydraulic_qualification,knn_report,network_report,invoice_report):
    replenishment=read(ROOT/'runs/replenishment-development-v1/qualification.json')
    visual=read(ROOT/'runs/visual-inspection-qualification-v1/qualification.json')
    return dict(
        visual_inspection=dict(evidence_integrity_passed=True,unit='public upstream real inspection photographs',source_images=10821,public_test_images=visual['official_public_test_images'],object_categories=visual['categories'],normal_fit_images=6920,normal_calibration_images=1739,baseline_macro_image_auroc=visual['baseline_metrics']['macro_image_auroc'],baseline_macro_resampled_pixel_auroc=visual['baseline_metrics']['macro_resampled_pixel_auroc'],baseline_macro_image_f1=visual['baseline_metrics']['macro_image_f1'],mask_grid_size=64,private_mask_diagnostic_is_model_result=False,new_business_scenarios=0,native_case_count_added=0),
        replenishment=dict(evidence_integrity_passed=True,unit='public synthetic fixed-lot replenishment development cases',development_cases=replenishment['development_cases'],structural_contracts=len(replenishment['structural_contracts']),parameter_draws_per_contract=8,strict_successes=replenishment['strict_successes'],negative_controls_rejected=replenishment['negative_controls_rejected'],new_business_scenarios=replenishment['development_cases'],native_case_count_added=0),
        supplier_formats=dict(evidence_integrity_passed=True,unit='matched PDF presentations',presentations=formats['presentations'],underlying_scenarios=formats['underlying_scenarios'],strict_successes=sum(r['strict_success'] for r in formats['cases']),new_business_scenarios=0,native_case_count_added=0),
        supplier_scans_original=dict(evidence_integrity_passed=True,unit='matched scan presentations',presentations=len(raw_report['cases']),underlying_scenarios=16,strict_successes=sum(r['strict_success'] for r in raw_report['cases']),new_business_scenarios=0,native_case_count_added=0),
        supplier_scan_policy=dict(evidence_integrity_passed=True,unit='policy evaluations of the same scan presentations',presentations=len(scan_report['cases']),underlying_scenarios=16,strict_successes=sum(r['strict_success'] for r in scan_report['cases']),profiles=scan_report['profiles'],new_business_scenarios=0,native_case_count_added=0),
        hydraulic_conditions=dict(evidence_integrity_passed=True,unit='real rig measurement cycles',source_cycles=hydraulic_qualification['source_cycles'],condition_groups=hydraulic_qualification['condition_groups'],test_cycles=hydraulic_qualification['test_cycles'],knn_joint_exact_accuracy=knn_report['metrics']['joint_exact_accuracy'],operational_workflows_added=0,native_case_count_added=0),
        material_networks=dict(evidence_integrity_passed=True,unit='public synthetic network development cases',development_cases=len(network_report['cases']),incidence_graph_families=network_report['underlying_graph_families'],strict_successes=sum(r['strict_success'] for r in network_report['cases']),new_business_scenarios=len(network_report['cases']),native_case_count_added=0),
        erp_invoices=dict(evidence_integrity_passed=True,unit='selected upstream public invoice controls',selected_upstream_cases=len(invoice_report['cases']),strict_successes=sum(r['result']['adapter_passed'] for r in invoice_report['cases']),posted_customer_invoices=sum(r['posted_invoices'] for r in invoice_report['cases']),new_business_scenarios=0,native_case_count_added=0))


def relations_from_files():
    from faraday_manufacturing_benchmark.document_cases import catalog as document_catalog
    fmt=read(ROOT/'output/pdf/supplier-formats-v1/manifest.json');raw=read(ROOT/'output/pdf/supplier-scans-v2/manifest.json')
    invoice=read(ROOT/'reports/erp-invoice-qualification.json');compat=read(ROOT/'reports/erp-compatibility-qualification.json');plan=read(ROOT/'runs/erp-catalog-v2/plan.json')
    return dict(format_source_ids=sorted({e['evaluator_task_id'] for e in fmt['cases']}),scan_source_ids=sorted({e['evaluator_task_id'] for e in raw['cases']}),
        native_document_scenario_ids=sorted(t['id'] for t in document_catalog() if t['mode']=='searchable_pdf'),invoice_case_ids=[r['task'] for r in invoice['cases']],
        compatibility_case_ids=[r['source_task'] for r in compat['selection']],erp_selected_ids=[r['task_id'] for r in plan['selected_cases']])


def checkpoint_summary(report,path):
    return dict(selected_cases=report['selected_cases'],resolved_cases=report['resolved_cases'],qualified_cases=report['qualified_cases'],failed_cases=report['failed_cases'],
        patterns_total=report['patterns_total'],patterns_with_qualified_case=report['patterns_with_qualified_case'],checkpoint_reported_status=report['status'],
        checkpoint=str(Path(path).resolve().relative_to(ROOT)),liveness_claim=False,scope='Pinned upstream private-oracle control checkpoint; selected catalog is not completed catalog or public-model performance.')


def evidence_paths(destination):
    """Reconstruct mandatory transitive paths; callers cannot omit child bindings."""
    paths=set()
    def add(path):
        path=Path(path).resolve();require(path.is_relative_to(ROOT),'artifact outside checkout');paths.add(str(path.relative_to(ROOT)))
    def tree(path):
        for child in Path(path).rglob('*'):
            if child.is_file():add(child)
    fixed=['manifest.json','reports/release-audit.json','reports/comparative-audit.json','reports/workflow-lineage.json',
        'reports/isolation-qualification.json','reports/erp-compatibility-qualification.json','runs/erp-catalog-v2/plan.json',
        'reports/wheel-verification.json','reports/comparator-source-inventory.json','reports/hydraulic-qualification.json',
        'reports/hydraulic-knn-baseline.json','reports/hydraulic-prior-baseline.json','reports/openai-smoke.json',
        'reports/document-formats-qualification.json','reports/supplier-scans-qualification-v2.json','reports/scan-agent-v2.json',
        'reports/network-qualification-v2.json','reports/erp-invoice-qualification.json','reports/scan-agent-v2-replay.json',
        'reports/scan-agent-v2-audit-controls.json','reports/network-public-bundle-integrity.json',
        'output/networks/manufacturing-network-development-v1.zip']
    for name in fixed:add(ROOT/name)
    add(ROOT/'runs/replenishment-development-v1/qualification.json');add(ROOT/'reports/replenishment-audit.json')
    add(ROOT/'reports/replenishment-public-bundle.json');add(ROOT/'output/replenishment/replenishment-public-development-v1.zip')
    tree(ROOT/'runs/replenishment-development-v1/public');tree(ROOT/'runs/replenishment-development-v1/receipts')
    add(ROOT/'reports/erp-origin-counterfactual-audit.json');add(ROOT/'reports/erp-2283-origin-flow-certificate.json')
    tree(ROOT/'runs/erp-control-reproductions/2283-origin-counterfactual-v1')
    add(ROOT/'reports/visual-inspection-audit.json')
    tree(ROOT/'runs/visual-inspection-data-v1');tree(ROOT/'runs/visual-inspection-development-v1')
    tree(ROOT/'runs/visual-inspection-source-v1');tree(ROOT/'runs/visual-inspection-qualification-v1')
    for name in read(ROOT/'manifest.json')['sha256']:add(ROOT/name)
    for track in NATIVE:
        path=ROOT/'reports'/f'{track}-qualification.json';add(path)
        for row in read(path)['cases']:add(local(row['receipt']))
    for directory in ['output/pdf/supplier-formats-v1','output/pdf/supplier-scans-v2','output/review/practitioner-v2/public','output/networks/development-v1']:
        add(ROOT/directory/'manifest.json')
        for name in read(ROOT/directory/'manifest.json')['files']:add(ROOT/directory/name)
    for name in ['document-formats-qualification','supplier-scans-qualification-v2','scan-agent-v2','network-qualification-v2']:
        for row in read(ROOT/'reports'/(name+'.json'))['cases']:add(local(row['receipt']))
    inv=read(ROOT/'reports/erp-invoice-qualification.json')
    for row in inv['cases']+list(inv['controls'].values()):
        episode=local(row['episode']);add(episode);tree(episode.parent/(episode.stem+'-evidence'))
        data=read(episode);snapshot=Path(data['snapshot_path']);tree(snapshot)
        if row in inv['cases']:tree(ROOT/'runs/invoice-extension'/(row['task']+'-replay'))
    tree(ROOT/'runs/invoice-extension/negative-policies')
    checkpoint=Path(destination)/'erp-checkpoint.json';add(checkpoint);add(Path(destination)/'erp-checkpoint-audit.json');add(Path(destination)/'networks.json')
    for row in read(checkpoint)['rows']:
        receipt=ROOT/'runs/erp-catalog-v2/cases'/row['task_id']/'receipt.json';add(receipt)
        for name in read(receipt)['artifacts']:add(local(name))
        if read(receipt).get('snapshot_manifest'):
            manifest_path=local(read(receipt)['snapshot_manifest']);manifest=read(manifest_path)
            source=Path(manifest['case_dir']);tree(source)
    hydraulic=ROOT/'runs/hydraulic-development-v1';add(hydraulic/'manifest.json');manifest=read(hydraulic/'manifest.json')
    for folder,key in [('public','public_files'),('evaluator','evaluator_files')]:
        for name in manifest[key]:add(hydraulic/folder/name)
    for row in read(ROOT/'reports/comparator-source-inventory.json')['sources']:
        if row['status']=='available':add(local(row['cache_path']))
    add(ROOT/'reports/expanded-comparator-audit.json')
    for name in read(ROOT/'reports/expanded-comparator-audit.json')['bindings']:add(local(name))
    add(local(read(ROOT/'reports/wheel-verification.json')['wheel']))
    return paths


def validate_added_development_evidence():
    import qualify_replenishment
    import audit_erp_origin_counterfactual
    import export_replenishment
    import qualify_visual_inspection
    replenishment=qualify_replenishment.audit(ROOT/'runs/replenishment-development-v1/qualification.json')
    require(replenishment==read(ROOT/'reports/replenishment-audit.json'),'replenishment audit stale')
    require(export_replenishment.verify(ROOT/'output/replenishment/replenishment-public-development-v1.zip',ROOT/'runs/replenishment-development-v1/public')==read(ROOT/'reports/replenishment-public-bundle.json'),'replenishment public archive changed')
    require(qualify_visual_inspection.audit(ROOT/'runs/visual-inspection-qualification-v1/qualification.json')==read(ROOT/'reports/visual-inspection-audit.json'),'visual inspection audit stale')
    origin=audit_erp_origin_counterfactual.audit()
    require(origin==read(ROOT/'reports/erp-origin-counterfactual-audit.json'),'assisted origin diagnostic audit stale')
    return dict(erp_origin_counterfactual=dict(evidence_integrity_passed=True,
        control_kind='private-reference-assisted single-field counterfactual diagnostic',
        original_score=origin['original_score'],assisted_score=origin['assisted_counterfactual_score'],reverted_score=origin['reverted_score'],
        initial_state_public_agent_result=False,native_case_count_added=0,original_campaign_failure_preserved=True))


def validate_scan_sidecars():
    from manufacturing_networks import digest
    qualification=read(ROOT/'reports/scan-agent-v2.json');replay=read(ROOT/'reports/scan-agent-v2-replay.json');controls=read(ROOT/'reports/scan-agent-v2-audit-controls.json')
    expected={r['packet']:r for r in qualification['cases']}
    require(replay['exact_replay'] and replay['report_sha256']==sha(ROOT/'reports/scan-agent-v2.json') and replay['auditor_sha256']==sha(ROOT/'scripts/audit_scan_agent.py'),'scan replay provenance changed')
    require(len(replay['cases'])==len(expected) and {r['packet'] for r in replay['cases']}==set(expected),'scan replay coverage incomplete')
    for row in replay['cases']:
        original=expected[row['packet']];receipt=read(local(original['receipt']))
        require(row['receipt_sha256']==original['receipt_sha256'] and row['payload_sha256']==digest(receipt['payload']) and row['recorded_response_sha256']==row['fresh_response_sha256']==digest(receipt['response']),'scan replay differs from retained observations')
    required={'fake_profile_successes','duplicate_case','payload_reference_injection','changed_ocr_metric','wrong_business_grade','private_path_probe_claim'}
    require(controls['integrity_controls_passed'] and controls['report_sha256']==sha(ROOT/'reports/scan-agent-v2.json') and controls['auditor_sha256']==sha(ROOT/'scripts/audit_scan_agent.py') and controls['control_runner_sha256']==sha(ROOT/'scripts/check_scan_audit_controls.py'),'scan control provenance changed')
    require(len(controls['controls'])==6 and {r['control'] for r in controls['controls']}==required and all(r['rejected'] is True for r in controls['controls']),'scan audit controls incomplete')


def validate_network_bundle():
    from manufacturing_networks import catalog,build
    root=ROOT/'output/networks/development-v1';manifest=read(root/'manifest.json');proof=read(ROOT/'reports/network-public-bundle-integrity.json')
    require(proof['passed'] and proof['manifest_sha256']==sha(root/'manifest.json') and proof['zip_sha256']==sha(ROOT/'output/networks/manufacturing-network-development-v1.zip'),'public network bundle commitment changed')
    require(manifest['source_generator_sha256']==sha(ROOT/'scripts/manufacturing_networks.py') and manifest['public_agent_sha256']==sha(ROOT/'examples/network_agent.py'),'public network bundle source changed')
    actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}-{'manifest.json'}
    require(actual==set(manifest['files']),'public network file inventory changed')
    for name,expected in manifest['files'].items():require(sha(root/name)==expected,'public network file changed')
    require(len(list((root/'cases').glob('*.json')))==len(catalog()),'public network case coverage changed')
    for task in catalog():require(read(root/'cases'/(task['id']+'.json'))==build(task),'public network case differs from generator')


def collect(destination):
    from faraday_manufacturing_benchmark.release_audit import audit as native_audit
    import audit_comparators as comparators
    import audit_workflow_lineage as lineage_module
    import document_formats
    import supplier_scans
    import audit_scan_agent
    import audit_networks
    import audit_erp_invoices
    import audit_erp_catalog
    import hydraulic_benchmark as hydraulic
    import review_kit
    from manufacturing_networks import digest
    destination=Path(destination).resolve();require(not destination.exists(),'coverage run directory already exists; preserve prior checkpoint')
    require(destination.is_relative_to(ROOT),'coverage artifacts must remain in checkout');destination.mkdir(parents=True)
    subprocess.run([sys.executable,'scripts/build_manifest.py','--check'],cwd=ROOT,check=True,capture_output=True,text=True)
    bindings={}
    def bind(path):
        path=Path(path).resolve();require(path.is_relative_to(ROOT),'bound artifact outside checkout');bindings[str(path.relative_to(ROOT))]=sha(path)
    native=native_audit(ROOT);require(native['passed'],'native evidence failed');native['manifest_current']=True
    save(ROOT/'reports/release-audit.json',native);bind(ROOT/'reports/release-audit.json')
    comparative=comparators.build_report();save(ROOT/'reports/comparative-audit.json',comparative);bind(ROOT/'reports/comparative-audit.json')
    lineage=lineage_module.inventory();require(lineage==read(ROOT/'reports/workflow-lineage.json'),'lineage inventory stale');bind(ROOT/'reports/workflow-lineage.json')
    fmt=document_formats.check(ROOT/'output/pdf/supplier-formats-v1',ROOT/'reports/document-formats-qualification.json')
    raw=supplier_scans.check(ROOT/'output/pdf/supplier-scans-v2',ROOT/'reports/supplier-scans-qualification-v2.json')
    scan_report,_,scan=audit_scan_agent.validate(ROOT/'reports/scan-agent-v2.json')
    network=audit_networks.audit(ROOT/'reports/network-qualification-v2.json',destination/'networks.json')
    invoices=audit_erp_invoices.audit()
    qualification=read(ROOT/'reports/hydraulic-qualification.json')
    for name,expected in qualification['sources'].items():require(sha(local(name))==expected,'hydraulic qualification source changed')
    hydraulic.verify(ROOT/'runs/hydraulic-development-v1')
    knn=hydraulic.replay(ROOT/'runs/hydraulic-development-v1',ROOT/'reports/hydraulic-knn-baseline.json')
    prior=hydraulic.replay(ROOT/'runs/hydraulic-development-v1',ROOT/'reports/hydraulic-prior-baseline.json')
    require(knn['passed'] and prior['passed'],'hydraulic retained-prediction regrade failed')
    hydraulic_qualification=read(ROOT/'reports/hydraulic-qualification.json');knn_report=read(ROOT/'reports/hydraulic-knn-baseline.json')
    for method,path in [('knn','reports/hydraulic-knn-baseline.json'),('majority','reports/hydraulic-prior-baseline.json')]:
        require(sha(local(path))==hydraulic_qualification['baselines'][method]['episode_sha256'],'hydraulic qualification baseline commitment changed')
    # Atomic live-driver JSON is captured once and audited as an immutable
    # checkpoint. No report-status/lock file is treated as process-liveness proof.
    checkpoint=destination/'erp-checkpoint.json';checkpoint.write_bytes((ROOT/'reports/erp-catalog-qualification.json').read_bytes())
    erp_audit=audit_erp_catalog.audit(ROOT/'runs/erp-catalog-v2',checkpoint);save(destination/'erp-checkpoint-audit.json',erp_audit)
    erp_report=read(checkpoint);erp_plan=read(ROOT/'runs/erp-catalog-v2/plan.json')
    bind(checkpoint);bind(destination/'erp-checkpoint-audit.json');bind(destination/'networks.json')
    formats=read(ROOT/'reports/document-formats-qualification.json');raw_report=read(ROOT/'reports/supplier-scans-qualification-v2.json');network_report=read(ROOT/'reports/network-qualification-v2.json');invoice_report=read(ROOT/'reports/erp-invoice-qualification.json')
    require(fmt['integrity_passed'] and raw['integrity_passed'] and scan['integrity_passed'] and network['passed'] and invoices['integrity_passed'],'extension component audit failed')
    extensions=extension_rows(formats,raw_report,scan_report,hydraulic_qualification,knn_report,network_report,invoice_report)
    relations=relations_from_files();erp=checkpoint_summary(erp_report,checkpoint)
    summary=derive(native,extensions,erp,comparative,lineage,relations)
    summary['assisted_diagnostics']=validate_added_development_evidence()
    packet=ROOT/'output/review/practitioner-v2/public';review=review_kit.verify(packet)
    summary['review_packet']=dict(artifact_integrity_passed=True,packet_benchmark_version=review['benchmark_version'],source_release_manifest_matches_current=review['source_release_manifest_sha256']==sha(ROOT/'manifest.json'),
        verified_practitioner_review_evidence_supplied=False,scope='Frozen historical preparation packet. File integrity does not verify reviewer identity, independence, adjudication or completed review.')
    summary['historical_model_smoke']=dict(artifact='reports/openai-smoke.json',sha256=sha(ROOT/'reports/openai-smoke.json'),scope='Historical partial smoke, not revalidated here against current release source or treated as matched-budget full-suite model evidence.')
    artifacts=['reports/document-formats-qualification.json','reports/supplier-scans-qualification-v2.json','reports/scan-agent-v2.json','reports/network-qualification-v2.json','reports/erp-invoice-qualification.json',
        'reports/hydraulic-qualification.json','reports/hydraulic-knn-baseline.json','reports/hydraulic-prior-baseline.json','reports/openai-smoke.json',
        'output/pdf/supplier-formats-v1/manifest.json','output/pdf/supplier-scans-v2/manifest.json','runs/hydraulic-development-v1/manifest.json','output/review/practitioner-v2/public/manifest.json']
    for name in artifacts:bind(ROOT/name)
    bind(ROOT/'manifest.json');bind(Path(__file__))
    for name in ['scripts/audit_networks.py','scripts/audit_scan_agent.py','scripts/audit_erp_catalog.py','scripts/audit_erp_invoices.py','scripts/audit_comparators.py','scripts/document_formats.py','scripts/supplier_scans.py','scripts/hydraulic_benchmark.py','scripts/review_kit.py']:bind(ROOT/name)
    validate_scan_sidecars();validate_network_bundle()
    wheel=read(ROOT/'reports/wheel-verification.json')
    require(wheel['passed'] and wheel['release_manifest_sha256']==sha(ROOT/'manifest.json') and wheel['wheel_sha256']==sha(local(wheel['wheel'])),'wheel evidence stale')
    for name in evidence_paths(destination):bind(local(name))
    summary.update(schema='manufacturing-coverage-evidence/1',assessed_at_utc=datetime.now(timezone.utc).isoformat(),bindings=bindings,
        extension_source_reports={'supplier_formats':'reports/document-formats-qualification.json','supplier_scans_original':'reports/supplier-scans-qualification-v2.json','supplier_scan_policy':'reports/scan-agent-v2.json',
            'hydraulic_conditions':'reports/hydraulic-qualification.json','material_networks':'reports/network-qualification-v2.json','erp_invoices':'reports/erp-invoice-qualification.json','replenishment':'runs/replenishment-development-v1/qualification.json','visual_inspection':'runs/visual-inspection-qualification-v1/qualification.json'},
        scope='Federated current-source native/extension evidence with explicit units and overlapping selections. Artifact integrity is not control success, independent review, private holdout or a worldwide ranking.')
    save(destination/'evidence.json',summary);return summary


def check(path):
    report=read(path);require(report.get('schema')=='manufacturing-coverage-evidence/1','unknown coverage schema')
    require(report['conclusion']['world_superlative_established'] is False,'unsupported superlative')
    require('total_cases' not in report,'heterogeneous counts must not be pooled')
    require(set(report['native_tracks'])==NATIVE and set(report['extensions'])==EXTENSIONS,'coverage collection incomplete')
    require(all(r['native_case_count_added']==0 for r in report['extensions'].values()),'extension counted as native')
    native=read(ROOT/'reports/release-audit.json');lineage=read(ROOT/'reports/workflow-lineage.json');comparative=read(ROOT/'reports/comparative-audit.json')
    source=report['extension_source_reports']
    require(source=={'supplier_formats':'reports/document-formats-qualification.json','supplier_scans_original':'reports/supplier-scans-qualification-v2.json','supplier_scan_policy':'reports/scan-agent-v2.json','hydraulic_conditions':'reports/hydraulic-qualification.json','material_networks':'reports/network-qualification-v2.json','erp_invoices':'reports/erp-invoice-qualification.json','replenishment':'runs/replenishment-development-v1/qualification.json','visual_inspection':'runs/visual-inspection-qualification-v1/qualification.json'},'component report selection changed')
    extensions=extension_rows(read(local(source['supplier_formats'])),read(local(source['supplier_scans_original'])),read(local(source['supplier_scan_policy'])),
        read(ROOT/'reports/hydraulic-qualification.json'),read(ROOT/'reports/hydraulic-knn-baseline.json'),read(local(source['material_networks'])),read(local(source['erp_invoices'])))
    checkpoint=local(report['erp_catalog']['checkpoint']);erp=read(checkpoint)
    expected=derive(native,extensions,checkpoint_summary(erp,checkpoint),comparative,lineage,relations_from_files())
    for key,value in expected.items():require(report[key]==value,'coverage summary differs from committed evidence: '+key)
    require(report['assisted_diagnostics']==validate_added_development_evidence(),'assisted diagnostic promoted or changed')
    subprocess.run([sys.executable,'scripts/build_manifest.py','--check'],cwd=ROOT,check=True,capture_output=True,text=True)
    mandatory=evidence_paths(local(report['erp_catalog']['checkpoint']).parent)
    require(mandatory<=set(report['bindings']),'mandatory child artifact binding omitted')
    for name,expected in report['bindings'].items():require(sha(local(name))==expected,'bound coverage input changed: '+name)
    validate_scan_sidecars();validate_network_bundle()
    require(report['review_packet']['verified_practitioner_review_evidence_supplied'] is False,'unverified review preparation promoted to validation')
    import audit_comparators
    require(audit_comparators.build_report()==comparative,'current primary comparator audit differs')
    return dict(evidence_integrity_passed=True,native_tracks=len(report['native_tracks']),extensions=len(report['extensions']),world_superlative_established=False,
        erp_checkpoint_resolved=erp['resolved_cases'],scope='Bound frozen coverage checkpoint and reporting-policy integrity; not current process liveness or a fresh component runtime/model run.')


def controls(report_path,output):
    """Exercise forged coverage summaries without changing original artifacts."""
    from copy import deepcopy
    import tempfile
    report_path=Path(report_path).resolve();output=Path(output).resolve()
    require(not output.exists(),'coverage control output already exists')
    check(report_path);original=sha(report_path);report=read(report_path);rows=[]
    with tempfile.TemporaryDirectory(prefix='coverage-controls-',dir=report_path.parent) as directory:
        def rejected(name,mutate,expected_reason):
            changed=deepcopy(report);mutate(changed);path=Path(directory)/(name+'.json');save(path,changed)
            try:check(path)
            except ValueError as error:
                require(expected_reason in str(error),'control rejected for unexpected reason: '+name+': '+str(error))
                rows.append(dict(control=name,rejected=True,error=str(error)))
            else:raise ValueError('forged coverage evidence accepted: '+name)
        rejected('pooled_total',lambda r:r.update(total_cases=99999),'must not be pooled')
        rejected('erased_original_scan_failures',lambda r:r['extensions']['supplier_scans_original'].update(strict_successes=48),'coverage summary differs')
        rejected('extension_promoted_to_native',lambda r:r['extensions']['material_networks'].update(native_case_count_added=48),'extension counted as native')
        rejected('partial_erp_claimed_complete',lambda r:r['erp_catalog'].update(resolved_cases=300,qualified_cases=300,failed_cases=[]),'coverage summary differs')
        rejected('fake_practitioner_gate',lambda r:r['completion_gates'].update(independent_practitioner_validation='met'),'coverage summary differs')
        rejected('world_superlative',lambda r:r['conclusion'].update(world_superlative_established=True),'unsupported superlative')
        rejected('hydraulic_accuracy_inflated',lambda r:r['extensions']['hydraulic_conditions'].update(knn_joint_exact_accuracy=1.),'coverage summary differs')
        rejected('visual_private_oracle_promoted',lambda r:r['extensions']['visual_inspection'].update(private_mask_diagnostic_is_model_result=True),'coverage summary differs')
        rejected('visual_baseline_accuracy_inflated',lambda r:r['extensions']['visual_inspection'].update(baseline_macro_image_auroc=1.),'coverage summary differs')
        rejected('missing_extension',lambda r:r['extensions'].pop('material_networks'),'collection incomplete')
        rejected('assisted_diagnostic_promoted',lambda r:r['assisted_diagnostics']['erp_origin_counterfactual'].update(initial_state_public_agent_result=True),'assisted diagnostic promoted')
        child=next(name for name in report['bindings'] if name.startswith('runs/') and name.endswith('.json.gz'))
        rejected('child_binding_omitted',lambda r:r['bindings'].pop(child),'mandatory child artifact binding omitted')
        rejected('child_digest_forged',lambda r:r['bindings'].__setitem__(child,'0'*64),'bound coverage input changed')
    require(sha(report_path)==original,'original coverage report changed');check(report_path)
    result=dict(passed=True,report_sha256=original,auditor_sha256=sha(__file__),controls=rows,original_report_unchanged=True,
        scope='Thirteen exercised summary/scope/gate/child-binding forgeries against temporary copies. No original data or case receipt was edited; no new benchmark/model run.')
    save(output,result);return result


def markdown(report):
    lines=['# Manufacturing coverage evidence checkpoint','',report['scope'],'','## Native tracks','', '| Track | Qualification rows |','|---|---:|']
    for name,row in report['native_tracks'].items():lines.append(f'| {name} | {row["qualification_rows"]} |')
    lines+=['',report['count_policy'],'','## Separate extensions','','| Component | Unit | Result |','|---|---|---|']
    for name,row in report['extensions'].items():
        if 'strict_successes' in row:result=str(row['strict_successes'])+' strict passes / '+str(row.get('presentations',row.get('development_cases',row.get('selected_upstream_cases'))))
        elif name=='visual_inspection':result=f'{row["public_test_images"]} public test images; macro image AUROC {row["baseline_macro_image_auroc"]:.3f}; 64x64 pixel AUROC {row["baseline_macro_resampled_pixel_auroc"]:.3f}; image F1 {row["baseline_macro_image_f1"]:.3f}'
        else:result=f'{row["test_cycles"]} test cycles; KNN joint accuracy {100*row["knn_joint_exact_accuracy"]:.1f}%'
        lines.append(f'| {name} | {row["unit"]} | {result} |')
    lines+=['',f'Selected comparison resources: {report["comparison_universe"]["named_resources"]}. Descriptive/source/schema/local-execution levels remain separate; this is not an exhaustive worldwide survey.']
    e=report['erp_catalog'];lines+=['',f'Frozen ERP checkpoint: {e["qualified_cases"]} qualified / {e["resolved_cases"]} resolved / {e["selected_cases"]} selected. This is not process-liveness evidence.','','## Completion gates','']
    lines += [f'- {name}: {status}' for name,status in report['completion_gates'].items()]
    lines+=['','The requested worldwide superlative remains unproven. All results above retain their authored, synthetic/development or pinned-upstream scope.','']
    return '\n'.join(lines)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    run=sub.add_parser('run');run.add_argument('--output-dir',required=True);verify=sub.add_parser('check');verify.add_argument('--report',required=True)
    negative=sub.add_parser('controls');negative.add_argument('--report',required=True);negative.add_argument('--output',required=True);a=p.parse_args()
    if a.command=='run':
        result=collect(a.output_dir);Path(a.output_dir,'coverage.md').write_text(markdown(result));print(json.dumps(check(Path(a.output_dir,'evidence.json'))))
    elif a.command=='controls':
        result=controls(a.report,a.output);print(json.dumps(dict(passed=result['passed'],rejected_forgeries=len(result['controls']))))
    else:print(json.dumps(check(a.report)))
