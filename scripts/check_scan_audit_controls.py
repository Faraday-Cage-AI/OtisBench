"""Exercise scan-evidence auditor with forged summaries and changed receipts."""
from copy import deepcopy
import argparse
import json
from pathlib import Path
import tempfile
from audit_scan_agent import validate,ROOT
from supplier_scans import formats


def run(report_path,output):
    report_path=Path(report_path).resolve();report,_,_=validate(report_path);controls=[]
    with tempfile.TemporaryDirectory(prefix='scan-audit-controls-',dir=ROOT/'runs') as temporary:
        directory=Path(temporary)
        def rejected(name,report_change=None,receipt_change=None):
            changed=deepcopy(report)
            if report_change:report_change(changed)
            if receipt_change:
                row=changed['cases'][0];receipt=json.loads((ROOT/row['receipt']).read_text());receipt_change(receipt)
                path=directory/(name+'-receipt.json');formats.save(path,receipt)
                row['receipt']=str(path.relative_to(ROOT));row['receipt_sha256']=formats.sha(path)
            path=directory/(name+'-report.json');formats.save(path,changed)
            try:validate(path)
            except ValueError as error:controls.append(dict(control=name,rejected=True,error=str(error)))
            else:raise ValueError('auditor accepted forged evidence: '+name)
        rejected('fake_profile_successes',lambda r:r['profiles']['photocopy'].update(strict_successes=16))
        rejected('duplicate_case',lambda r:r['cases'].__setitem__(1,deepcopy(r['cases'][0])))
        rejected('payload_reference_injection',receipt_change=lambda r:r['payload'].update(reference_answer={'pay':True}))
        rejected('changed_ocr_metric',receipt_change=lambda r:r['metrics'][0].update(matched_tokens=r['metrics'][0]['matched_tokens']+1))
        rejected('wrong_business_grade',receipt_change=lambda r:r['result'].update(score=99.))
        rejected('private_path_probe_claim',lambda r:r['private_path_probe']['result']['paths'][next(iter(r['private_path_probe']['result']['paths']))].update(readable=True))
    validate(report_path)
    result=dict(integrity_controls_passed=True,report_sha256=formats.sha(report_path),auditor_sha256=formats.sha(ROOT/'scripts/audit_scan_agent.py'),
        control_runner_sha256=formats.sha(__file__),controls=controls,original_report_unchanged=True,
        scope='Six exercised forged-summary/receipt/private-path verdict controls; no original receipts were edited. Not independent validation or new OCR.')
    formats.save(output,result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--report',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    print(json.dumps(run(a.report,a.output)))
