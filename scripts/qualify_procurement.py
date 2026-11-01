"""Procure-to-pay feasibility, replay and adversarial controls; no model claims."""
from pathlib import Path
import gzip
import hashlib
import importlib.util
import json
from faraday_manufacturing_benchmark.procurement_cases import catalog
from faraday_manufacturing_benchmark.procurement import ProcurementWorld,run,replay,summary
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('procurement_policy',ROOT/'examples/procurement_agent.py')
policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy)


class MutantPolicy(policy.ProcurementPolicy):
    def __init__(self,mode):super().__init__();self.mode=mode;self.changed=False
    def decide(self,track,payload):
        decision=super().decide(track,payload)
        if not self.changed and self.mode=='physical_quantity' and decision['tool']=='receive':
            decision['arguments']['units']+=1;self.changed=True
        if not self.changed and self.mode=='invoice_amount' and decision['tool']=='propose' and decision['arguments']['kind']=='invoice' and decision['arguments']['payload']['decision']=='approve':
            decision['arguments']['payload']['amount_cents']+=1;self.changed=True
        if self.mode=='missing_ap_readback' and decision['tool']=='read' and decision['arguments']['system']=='AP':
            decision=dict(tool='wait',arguments=dict(minutes=1));self.changed=True
        return decision


def main():
    out=ROOT/'runs/qualification/procurement';out.mkdir(parents=True,exist_ok=True);rows=[];results=[]
    for t in catalog():
        e=run(t,policy.ProcurementPolicy());r=e['result'];exact=replay(t,e['trace'])==r;results.append(r)
        path=out/(t['id']+'.json.gz');path.write_bytes(gzip.compress(json.dumps(e,sort_keys=True,separators=(',',':'),allow_nan=False).encode(),mtime=0))
        weak=ProcurementWorld(t)
        for system in t['systems']:weak.call('read',system=system)
        unsafe=ProcurementWorld(t);unsafe.call('execute',proposal_id='PROP-fake',approval_id='AUTH-fake')
        mutants={}
        for mode in ('physical_quantity','invoice_amount','missing_ap_readback'):
            agent=MutantPolicy(mode);mutation=run(t,agent)
            mutants[mode]=dict(exercised=agent.changed,strict_success=mutation['result']['strict_success'],score=mutation['result']['score'])
        rows.append(dict(task_id=t['id'],strict_success=r['strict_success'],exact_replay=exact,read_only_zero=weak.grade()['score']==0,
            unauthorized_critical_zero=unsafe.grade()['score']==0 and bool(unsafe.grade()['critical_violations']),
            mutations=mutants,receipt=str(path.relative_to(ROOT)),receipt_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    paths=list((ROOT/'src').rglob('*.py'))+[ROOT/'examples/procurement_agent.py',Path(__file__).resolve()]
    report=dict(track='procurement-chain-qualification',control='Hand-coded raw-document/observation-only feasibility policy with a fixed initial seven-minute wait; NOT model performance or independent practitioner validation.',
        source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)},summary=summary(results),
        exact_replays=sum(r['exact_replay'] for r in rows),read_only_zero_scores=sum(r['read_only_zero'] for r in rows),unauthorized_critical_zero_scores=sum(r['unauthorized_critical_zero'] for r in rows),
        mutations=sum(len(r['mutations']) for r in rows),mutations_rejected=sum(m['exercised'] and not m['strict_success'] for r in rows for m in r['mutations'].values()),cases=rows,
        limitations=['Synthetic closed-world physical and financial state; no live ERP, bank or logistics integrations.','Four parameter draws per contract are not independent workflow families.','Fixed-format raw text/CSV is not scanned-document OCR or CAD perception.','Public development cases; held-out generalization is not established.'])
    (ROOT/'reports/procurement-qualification.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    passed=all(r['strict_success'] and r['exact_replay'] and r['read_only_zero'] and r['unauthorized_critical_zero'] and all(m['exercised'] and not m['strict_success'] for m in r['mutations'].values()) for r in rows)
    print(json.dumps(dict(passed=passed,cases=len(rows),strict_successes=report['summary']['strict_successes'],mutations=report['mutations'],mutations_rejected=report['mutations_rejected'])))
    return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
