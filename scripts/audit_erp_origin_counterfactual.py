"""Verify a retained reference-assisted ERP diagnostic; no fresh Odoo execution."""
import argparse
import json
from pathlib import Path
from faraday_manufacturing_benchmark import erp_compat as erp
from counterfactual_erp_origins import difference
from certify_erp_origin_flow import checker_functions,projection
ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'runs/erp-control-reproductions/2283-origin-counterfactual-v1/counterfactual.json'
CERTIFICATE=ROOT/'reports/erp-2283-origin-flow-certificate.json'
KIND='private-reference-assisted single-field counterfactual diagnostic'


def scope(report):
    if report['control_kind']!=KIND or report['native_case_count_added']!=0:raise ValueError('assisted diagnostic cannot be promoted to public-agent/native performance')


def audit():
    report=json.loads(REPORT.read_text());scope(report)
    for name,expected in report['source_sha256'].items():
        path=(ROOT/name).resolve()
        if not path.is_relative_to(ROOT) or erp.sha(path)!=expected:raise ValueError('diagnostic source changed')
    for name,expected in report['artifacts'].items():
        path=(ROOT/name).resolve()
        if not path.is_relative_to(ROOT) or erp.sha(path)!=expected:raise ValueError('diagnostic artifact changed')
    original=(ROOT/report['original_receipt']).resolve()
    if not original.is_relative_to(ROOT) or erp.sha(original)!=report['original_receipt_sha256']:raise ValueError('original failure receipt changed')
    receipt=json.loads(original.read_text());manifest_path=ROOT/receipt['snapshot_manifest'];manifest=json.loads(manifest_path.read_text());erp.snapshot_contract(manifest);erp.check_source(manifest['case_dir'])
    if erp.sha(manifest_path)!=report['snapshot_manifest_sha256']:raise ValueError('diagnostic fixture changed')
    for name,expected in manifest['files'].items():
        if erp.sha(manifest_path.parent/name)!=expected:raise ValueError('fixture artifact changed')
    initial=json.loads((REPORT.parent/'initial-business-state.json').read_text())
    before=json.loads((REPORT.parent/'reference-business-state.json').read_text());after=json.loads((REPORT.parent/'counterfactual-business-state.json').read_text());reverted=json.loads((REPORT.parent/'reverted-business-state.json').read_text())
    if erp.digest(initial)!=manifest['baseline_state_digest'] or before!=reverted:raise ValueError('baseline or business reversal differs')
    changes=difference(before,after)
    if changes!=report['business_changes'] or len(changes)!=1 or changes[0]['model']!='purchase.order' or changes[0]['field']!='origin':raise ValueError('not exactly one projected PO origin change')
    for label,key in [('original-reference','original_result'),('counterfactual','counterfactual_result'),('reverted','reverted_result')]:
        reward=json.loads((REPORT.parent/label/'verifier/reward.json').read_text())
        if report[key]!=dict(upstream_score=reward['overall_score'],upstream_passed=reward['passed'],verifier=reward):raise ValueError('retained verifier verdict differs')
    left=report['original_result'];right=report['counterfactual_result'];reverse=report['reverted_result']
    if left!=receipt['reference'] or left!=reverse or left['upstream_passed'] or not right['upstream_passed'] or right['upstream_score']!=100:raise ValueError('failure/pass/failure sequence not established')
    if left['verifier']['spend']!=right['verifier']['spend'] or left['verifier']['optimality_detail']!=right['verifier']['optimality_detail']:raise ValueError('spend or repair objective changed')
    if len(report['rpc_trace'])!=2:raise ValueError('expected exactly the edit and reversal writes')
    change=changes[0]
    for row,value in zip(report['rpc_trace'],[change['after'],change['before']],strict=True):
        expected=dict(model='purchase.order',method='write',kwargs=dict(ids=[change['id']],vals=dict(origin=value)))
        if row['request']!=expected or not row['response']['ok'] or row['response']['value'] is not True:raise ValueError('constrained edit/reversal trace differs')
    flags=['demonstrated','only_requested_origin_changed','exact_business_state_reversal','exact_verdict_reversal','exact_original_campaign_verdict','spend_summary_unchanged']
    if not all(report[key] is True for key in flags):raise ValueError('diagnostic summary contradicts measured result')
    certificate=json.loads(CERTIFICATE.read_text());checker_path=Path(manifest['case_dir'])/'tests/checks.py'
    if not certificate['passed'] or certificate['counterfactual_sha256']!=erp.sha(REPORT) or certificate['checker_sha256']!=erp.sha(checker_path) or certificate['certifier_sha256']!=erp.sha(ROOT/'scripts/certify_erp_origin_flow.py'):raise ValueError('MOQ certificate source changed')
    checker=checker_functions(checker_path)
    if projection(before,certificate['component'],checker)!=certificate['before'] or projection(after,certificate['component'],checker)!=certificate['after']:raise ValueError('MOQ certificate does not recompute')
    return dict(integrity_passed=True,task_id=report['task_id'],original_score=left['upstream_score'],assisted_counterfactual_score=right['upstream_score'],reverted_score=reverse['upstream_score'],
        original_campaign_failure_preserved=True,only_one_projected_origin_changed=True,spend_unchanged=True,repair_objective_unchanged=True,
        initial_state_public_agent_result=False,native_case_count_added=0,report_sha256=erp.sha(REPORT),certificate_sha256=erp.sha(CERTIFICATE),auditor_sha256=erp.sha(__file__),
        scope='Retained unchanged-grader reference-assisted diagnostic plus pure MOQ certificate recheck. No fresh Odoo run, independent review, model score or replacement of the original campaign failure.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',default='reports/erp-origin-counterfactual-audit.json');a=p.parse_args();r=audit();erp.save(a.output,r)
    print(json.dumps({k:r[k] for k in ['integrity_passed','original_score','assisted_counterfactual_score','reverted_score']}))
