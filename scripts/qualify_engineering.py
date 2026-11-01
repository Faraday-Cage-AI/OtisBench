"""Full engineering reference/schema consistency and field perturbation controls."""
from pathlib import Path
from copy import deepcopy
import gzip
import hashlib
import json
from jsonschema import validate
from faraday_manufacturing_benchmark.catalog import TASKS
from faraday_manufacturing_benchmark.calculations import SOLVERS
from faraday_manufacturing_benchmark.grading import grade,summarize
from faraday_manufacturing_benchmark.protocol import answer_schema
ROOT=Path(__file__).resolve().parents[1]


def changed(value):
    if isinstance(value,bool):return not value
    if value is None:return 0
    if isinstance(value,(int,float)):return value+max(1,abs(value)*.1)
    if isinstance(value,str):return value+'-wrong'
    if isinstance(value,list):return value+['wrong']
    return dict(value,__wrong=True)


def main():
    out=ROOT/'runs/qualification/engineering';out.mkdir(parents=True,exist_ok=True);rows=[];results=[]
    for t in TASKS:
        answer=SOLVERS[t['family']](t['inputs']);validate(answer,answer_schema(t));r=grade(t,answer);results.append(r);mutations=[]
        for key,value in answer.items():
            bad=deepcopy(answer);bad[key]=changed(value);mutations.append(dict(field=key,rejected=not grade(t,bad)['strict_success']))
        schema_controls={}
        for label,bad in [('empty',{}),('extra',dict(answer,__extra=True)),('missing',{k:v for k,v in answer.items() if k!=next(iter(answer))})]:schema_controls[label]=not grade(t,bad)['strict_success']
        receipt=dict(task=t,answer=answer,result=r);path=out/(t['id']+'.json.gz');path.write_bytes(gzip.compress(json.dumps(receipt,sort_keys=True,allow_nan=False).encode(),mtime=0))
        rows.append(dict(task_id=t['id'],strict_success=r['strict_success'],schema_valid=True,field_mutations=mutations,schema_controls=schema_controls,receipt=str(path.relative_to(ROOT)),receipt_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    paths=list((ROOT/'src').rglob('*.py'))+[Path(__file__).resolve()]
    report=dict(track='engineering-qualification',control='Evaluator-reference/schema consistency; not independent engineering ground truth or a model score.',source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)},summary=summarize(results),field_mutations=sum(len(r['field_mutations']) for r in rows),field_mutations_rejected=sum(m['rejected'] for r in rows for m in r['field_mutations']),cases=rows)
    (ROOT/'reports/engineering-qualification.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    passed=all(r['strict_success'] and all(m['rejected'] for m in r['field_mutations']) and all(r['schema_controls'].values()) for r in rows)
    print(json.dumps(dict(passed=passed,cases=len(rows),families=len(report['summary']['families']),field_mutations=report['field_mutations'],field_mutations_rejected=report['field_mutations_rejected'])))
    return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
