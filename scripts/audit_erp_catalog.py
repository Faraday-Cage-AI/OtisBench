"""Read-only audit of a frozen ERP catalog campaign checkpoint.

Does not launch Docker, rerun a verifier/model, or infer process liveness.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
from qualify_erp_catalog import ROOT,read,plan,checked_row,summary,atomic,erp


def audit(destination, report_path):
    destination=Path(destination).resolve();report_path=Path(report_path).resolve()
    frozen=read(destination/'plan.json');report=read(report_path)
    if frozen!=plan() or report['plan_sha256']!=erp.digest(frozen):raise ValueError('campaign source or plan changed')
    selected={row['task_id']:row for row in frozen['selected_cases']};rows=[];receipts={}
    for item in report['rows']:
        if item['task_id'] not in selected:raise ValueError('unknown task in campaign checkpoint')
        path=destination/'cases'/item['task_id']/'receipt.json'
        row=checked_row(path,selected[item['task_id']],frozen);rows.append(row)
        receipts[str(path.relative_to(ROOT))]=erp.sha(path)
    rebuilt=summary(frozen,rows,report['status'])
    for key in rebuilt:
        if key=='last_updated_utc':continue
        actual,expected=report[key],rebuilt[key]
        if key=='failed_cases':actual,expected=sorted(actual),sorted(expected)
        if actual!=expected:raise ValueError('campaign checkpoint contradicts retained cases: '+key)
    return dict(integrity_passed=True,checkpoint_report_sha256=erp.sha(report_path),checkpoint_status=report['status'],
        resolved_cases=report['resolved_cases'],qualified_cases=report['qualified_cases'],failed_cases=report['failed_cases'],
        patterns_with_qualified_case=report['patterns_with_qualified_case'],full_catalog_qualified=report['full_catalog_qualified'],
        case_receipt_sha256=receipts,auditor_sha256=erp.sha(Path(__file__)),
        scope='Frozen checkpoint source/artifact/verifier-result integrity. No new Odoo execution, model run, independent review or process-liveness claim.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',default='runs/erp-catalog-v2');p.add_argument('--report',default='reports/erp-catalog-qualification.json');p.add_argument('--output',default='reports/erp-catalog-audit.json');args=p.parse_args()
    result=audit(args.run_dir,args.report);atomic(args.output,result)
    print(json.dumps({k:result[k] for k in ['integrity_passed','checkpoint_status','resolved_cases','qualified_cases','patterns_with_qualified_case','full_catalog_qualified']}))
