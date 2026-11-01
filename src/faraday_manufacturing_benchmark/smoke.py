"""A hard-bounded OpenAI smoke test; no full benchmark evaluation is dispatched."""
from __future__ import annotations
import argparse
from dataclasses import asdict,replace
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import time
from .catalog import TASKS
from .grading import grade,summarize
from .protocol import answer_schema,object_schema
from .season import CASES,FactorySeason
from .cli import save

SELECTED=['mfg-mrp-002','mfg-heat_treatment-002','mfg-gdt_position-001','mfg-production_schedule-002']


def action_schema():
    return object_schema(dict(
        purchase_packs=object_schema({m:{'type':'integer','minimum':0,'maximum':1000} for m in ['CAST','MOTOR','SEAL','PCB']}),
        expedite={'type':'array','items':{'type':'string','enum':['CAST','MOTOR','SEAL','PCB']}},
        maintain={'type':'array','items':{'type':'string','enum':['mill','assembly','test']}},
        jobs={'type':'array','maxItems':12,'items':object_schema({'product':{'type':'string','enum':['PUMP','VALVE','DRIVE','KIT']},'units':{'type':'integer','minimum':1,'maximum':1000}})}))


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--env-file');p.add_argument('--model',default='gpt-4.1-mini-2025-04-14');p.add_argument('--output',default='runs/smoke.json')
    args=p.parse_args(argv)
    if args.env_file:
        from dotenv import load_dotenv
        load_dotenv(args.env_file,override=False)
    from openai import OpenAI
    client=OpenAI(max_retries=0,timeout=45)
    report=dict(kind='smoke',started_at=datetime.now(timezone.utc).isoformat(),model=args.model,
                limits=dict(max_requests=8,max_output_tokens_per_request=2000,max_prompt_chars=20000),requests=[],engineering=[],season=None)
    # Commit implementation and cases before the first request.
    source=Path(__file__).parent
    report['source_sha256']=hashlib.sha256(b''.join(p.read_bytes() for p in sorted(source.rglob('*.py')))).hexdigest()
    save(args.output,report)
    def request(label,prompt,schema):
        if len(report['requests'])>=8:raise ValueError('smoke request cap reached')
        if len(prompt)>20000:raise ValueError('prompt exceeds smoke size cap')
        start=time.monotonic();row=dict(label=label,status='started');report['requests'].append(row);save(args.output,report)
        try:
            response=client.responses.create(model=args.model,store=False,max_output_tokens=2000,
                instructions='Complete this manufacturing task. Return precisely the requested JSON object. Use the provided operating rules and units.',
                input=prompt,text={'format':{'type':'json_schema','name':'manufacturing_answer','strict':True,'schema':schema}})
            row.update(status=response.status,response_id=response.id,model=response.model,
                       usage=response.usage.model_dump() if response.usage else None,elapsed_seconds=round(time.monotonic()-start,3))
            if response.status!='completed':raise ValueError('response did not complete')
            answer=json.loads(response.output_text);row['answer']=answer;save(args.output,report);return answer
        except Exception as exc:
            row.update(status='error',error_type=type(exc).__name__,status_code=getattr(exc,'status_code',None),elapsed_seconds=round(time.monotonic()-start,3))
            save(args.output,report);raise
    try:
        byid={t['id']:t for t in TASKS}
        for task_id in SELECTED:
            task=byid[task_id];answer=request(task_id,json.dumps(task),answer_schema(task))
            report['engineering'].append(grade(task,answer));save(args.output,report)
        report['engineering_summary']=summarize(report['engineering'])
        case=replace(CASES[0],id='smoke-four-weeks',weeks=4);world=FactorySeason(case,0)
        for week in range(case.weeks):
            answer=request(f'factory-week-{week}',json.dumps(world.observe()),action_schema());world.step(answer)
        report['season']=dict(case=asdict(case),draw=0,trace=world.trace,result=world.result())
        report['status']='completed'
    except Exception as exc:
        report['status']='stopped';report['error_type']=type(exc).__name__
    report['finished_at']=datetime.now(timezone.utc).isoformat();save(args.output,report)
    print(json.dumps({k:report.get(k) for k in ['status','model','engineering_summary','error_type']},indent=2))
    print('Requests:',len(report['requests']),'Saved:',args.output)
    return 0 if report['status']=='completed' else 1


if __name__=='__main__':raise SystemExit(main())
