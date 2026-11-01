"""Explicit track selection: listing never starts an evaluation."""
from __future__ import annotations
import argparse
from dataclasses import asdict
from importlib.resources import files
import json
from pathlib import Path
from .catalog import TASKS
from .grading import grade,summarize
from .season import CASES,FactorySeason,idle_policy,rule_policy,replay
from . import __version__



def workflow_catalog():
    return json.loads(files('faraday_manufacturing_benchmark').joinpath('data/manufacturing_workflows.json').read_text())


def workflows():
    return json.loads(files('faraday_manufacturing_benchmark').joinpath('data/workflows.json').read_text())


def save(path,value):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n')


def main(argv=None):
    parser=argparse.ArgumentParser(prog='otisbench',description='OtisBench: manufacturing workflows for AI agents')
    sub=parser.add_subparsers(dest='command',required=True)
    from .judgment import configure as configure_judgment
    configure_judgment(sub.add_parser('judgment', help='Staged manufacturing judgment workshops'))
    isolated=sub.add_parser('isolated');isolated.add_argument('--track',choices=['workflow','supply-chain','procurement','sensors','cad','documents'],required=True);isolated.add_argument('--task',action='append',required=True);isolated.add_argument('--agent-file',required=True);isolated.add_argument('--timeout',type=float,default=120);isolated.add_argument('--kernel-timeout',type=float,default=30);isolated.add_argument('--output',required=True)
    ls=sub.add_parser('list');ls.add_argument('--track',choices=['workflow','engineering','execution','season','supply-chain','procurement','sensors','cad','documents','campaign'])
    campaign=sub.add_parser('campaign')
    campaign.add_argument('--task',required=True)
    campaign_agent=campaign.add_mutually_exclusive_group(required=True)
    campaign_agent.add_argument('--agent-command');campaign_agent.add_argument('--agent-file')
    campaign.add_argument('--timeout',type=float,default=120);campaign.add_argument('--stop-after',type=int);campaign.add_argument('--resume');campaign.add_argument('--output',required=True)
    documents=sub.add_parser('documents');documents.add_argument('--task',action='append',required=True);documents.add_argument('--agent-command',required=True);documents.add_argument('--output',required=True);documents.add_argument('--timeout',type=float,default=120)
    document_export=sub.add_parser('export-document-packet');document_export.add_argument('--task',required=True);document_export.add_argument('--output-dir',required=True)
    cad=sub.add_parser('cad');cad.add_argument('--task',action='append',required=True);cad.add_argument('--agent-command',required=True);cad.add_argument('--output',required=True);cad.add_argument('--timeout',type=float,default=120);cad.add_argument('--kernel-timeout',type=float,default=30)
    cad_export=sub.add_parser('export-cad');cad_export.add_argument('--task',required=True);cad_export.add_argument('--output-dir',required=True)
    cad_grade=sub.add_parser('grade-cad');cad_grade.add_argument('--task',required=True);cad_choice=cad_grade.add_mutually_exclusive_group(required=True);cad_choice.add_argument('--program');cad_choice.add_argument('--step');cad_grade.add_argument('--output',required=True);cad_grade.add_argument('--export-step');cad_grade.add_argument('--kernel-timeout',type=float,default=30)
    sensors=sub.add_parser('sensors');sensors.add_argument('--task',action='append',required=True);sensors.add_argument('--agent-command',required=True);sensors.add_argument('--output',required=True);sensors.add_argument('--timeout',type=float,default=120)
    sensor_export=sub.add_parser('export-sensor-data');sensor_export.add_argument('--task',required=True);sensor_export.add_argument('--output-dir',required=True)
    procurement=sub.add_parser('procurement');procurement.add_argument('--task',action='append',required=True);procurement.add_argument('--agent-command',required=True);procurement.add_argument('--output',required=True);procurement.add_argument('--timeout',type=float,default=120)
    packet=sub.add_parser('export-procurement-documents');packet.add_argument('--task',required=True);packet.add_argument('--output-dir',required=True)
    supply=sub.add_parser('supply-chain');supply.add_argument('--task',action='append',required=True);supply.add_argument('--agent-command',required=True);supply.add_argument('--output',required=True);supply.add_argument('--timeout',type=float,default=120)
    flow=sub.add_parser('workflow');flow.add_argument('--task',action='append',required=True);flow.add_argument('--agent-command',required=True);flow.add_argument('--output',required=True);flow.add_argument('--timeout',type=float,default=120)
    export=sub.add_parser('export-agent');export.add_argument('--task',required=True);export.add_argument('--output',required=True)
    show=sub.add_parser('show');show.add_argument('task_id')
    engineering=sub.add_parser('engineering');engineering.add_argument('--task',action='append',required=True);engineering.add_argument('--agent-command',required=True);engineering.add_argument('--output',required=True);engineering.add_argument('--timeout',type=float,default=120)
    compare=sub.add_parser('compare');compare.add_argument('--candidate',nargs='+',required=True);compare.add_argument('--baseline',nargs='+',required=True);compare.add_argument('--output',required=True)
    grading=sub.add_parser('grade');grading.add_argument('answers');grading.add_argument('--task',action='append',required=True);grading.add_argument('--output',required=True)
    run=sub.add_parser('execute');run.add_argument('--task',action='append',required=True);run.add_argument('--agent-command',required=True);run.add_argument('--output',required=True);run.add_argument('--timeout',type=float,default=120)
    season=sub.add_parser('season');season.add_argument('--case',choices=[c.id for c in CASES],required=True);season.add_argument('--draw',type=int,default=0);choice=season.add_mutually_exclusive_group(required=True);choice.add_argument('--policy',choices=['idle','rule']);choice.add_argument('--agent-command');season.add_argument('--timeout',type=float,default=120);season.add_argument('--output',required=True)
    replay_parser=sub.add_parser('replay');replay_parser.add_argument('run')
    args=parser.parse_args(argv)
    try:
        if args.command=='judgment':
            from .judgment import execute
            return execute(args)
        elif args.command=='campaign':
            from .campaign import execute
            return execute(args)
        elif args.command=='isolated':
            from .isolation_runner import contracts,run_task
            catalog,_,_,summarizer=contracts(args.track);byid={t['id']:t for t in catalog()}
            if len(set(args.task))!=len(args.task) or any(k not in byid for k in args.task):raise ValueError('unknown or duplicate isolated task ID')
            artifact=dict(track={'supply-chain':'supply-chain','procurement':'procurement-chain'}.get(args.track,'manufacturing-'+args.track),manufacturing_version=__version__,agent_transport='macos-stdlib-offline/1',episodes=[])
            for key in args.task:
                def checkpoint(episode):
                    artifact['current_episode']=episode;save(args.output,artifact)
                episode=run_task(args.track,byid[key],args.agent_file,args.timeout,args.kernel_timeout,checkpoint)
                artifact['episodes'].append(episode);artifact.pop('current_episode',None)
                artifact['summary']=summarizer(artifact['episodes'] if args.track=='cad' else [e['result'] for e in artifact['episodes']]);save(args.output,artifact)
        elif args.command=='list':
            if args.track in (None,'campaign'):
                from .campaign import catalog as campaign_catalog
                for t in campaign_catalog():print(f"campaign\t{t['id']}\t{t['order_count']} work orders\t{t['horizon_minutes']} minutes\t{t['max_tool_calls']} calls")
            if args.track in (None,'documents'):
                from .document_cases import catalog as document_catalog
                for t in document_catalog():print(f"documents\t{t['id']}\t{t['family']}\t{t['mode']}")
            if args.track in (None,'cad'):
                from .cad_cases import catalog as cad_catalog
                for t in cad_catalog():print(f"cad\t{t['id']}\t{t['family']}\t{t['mode']}\tdraw {t['draw']}")
            if args.track in (None,'sensors'):
                from .sensor_cases import catalog as sensor_catalog
                for t in sensor_catalog():print(f"sensors\t{t['id']}\t{t['domain']}\t{t['family']}\t{t['condition']}")
            if args.track in (None,'procurement'):
                from .procurement_cases import catalog as procurement_catalog
                for t in procurement_catalog():print(f"procurement\t{t['id']}\t{t['contract']}\tdraw {t['draw']}")
            if args.track in (None,'supply-chain'):
                from .supply_cases import catalog
                for t in catalog():print(f"supply-chain\t{t['id']}\t{t['domain']}\t{t['family']}")
            if args.track in (None,'workflow'):
                for t in workflow_catalog():print(f"workflow\t{t['id']}\t{t['family']}\t{t['disruption']}")
            if args.track in (None,'engineering'):
                for t in TASKS:print(f"engineering\t{t['id']}\t{t['domain']}\t{t['title']}")
            if args.track in (None,'execution'):
                for t in workflows():print(f"execution\t{t['id']}\t{t['family']}\t{t['title']}")
            if args.track in (None,'season'):
                for c in CASES:print(f'season\t{c.id}\t{c.weeks} weeks\t{c.mode}')
        elif args.command=='show':
            from .supply_cases import catalog
            from .procurement_cases import catalog as procurement_catalog
            from .sensor_cases import catalog as sensor_catalog
            from .cad_cases import catalog as cad_catalog
            from .document_cases import catalog as document_catalog
            from .campaign import catalog as campaign_catalog
            task=next((t for t in workflow_catalog()+TASKS+workflows()+catalog()+procurement_catalog()+sensor_catalog()+cad_catalog()+document_catalog()+campaign_catalog() if t['id']==args.task_id),None)
            if task is None:raise ValueError('unknown task ID')
            if task['id'].startswith('campaign-'):
                from .campaign import startup
                from .shopfloor_views import AgentView
                task=startup(task,AgentView())
            elif task['id'].startswith('doc-'):
                from .documents import public_task
                task=public_task(task)
            elif task['id'].startswith('cad-'):
                from .cad import public_packet
                task=public_packet(task)['task']
            elif task['id'].startswith('sensor-'):
                from .sensors import public_task
                task=public_task(task)
            elif task['id'].startswith('p2p-'):
                from .procurement import public_task
                task=public_task(task)
            elif task['id'].startswith('supply-'):
                from .supply_chain import public_task
                task=public_task(task)
            elif task['id'].startswith('mfg-flow-'):
                from .shopfloor_views import public_task
                task=public_task(task)
            else:task={k:v for k,v in task.items() if k!='seed'}
            print(json.dumps(task,indent=2))
        elif args.command=='export-agent':
            if args.task.startswith('campaign-'):
                from .campaign import catalog as campaign_catalog,startup,CAMPAIGN_TOOLS,MANUFACTURING_TOOLS
                from .shopfloor import TOOLS
                from .shopfloor_views import AgentView
                byid={t['id']:t for t in campaign_catalog()}
                if args.task not in byid:raise ValueError('unknown campaign task ID')
                save(args.output,dict(type='decision',protocol='faraday-manufacturing/1',track='campaign',payload=dict(clock_minute=0,calls_remaining=byid[args.task]['max_tool_calls'],last_result=None,task=startup(byid[args.task],AgentView()),tools=CAMPAIGN_TOOLS,manufacturing_tools=MANUFACTURING_TOOLS)))
                return 0
            if args.task.startswith('doc-'):
                from .document_cases import catalog
                from .documents import public_task,TOOLS
                byid={t['id']:t for t in catalog()}
                if args.task not in byid:raise ValueError('unknown document task ID')
                save(args.output,dict(type='decision',protocol='faraday-manufacturing/1',track='documents',payload=dict(calls_remaining=120,last_result=None,task=public_task(byid[args.task]),tools=TOOLS)))
                return 0
            if args.task.startswith('cad-'):
                from .cad_cases import catalog as cad_catalog
                from .cad import public_packet
                byid={t['id']:t for t in cad_catalog()}
                if args.task not in byid:raise ValueError('unknown CAD task ID')
                save(args.output,dict(type='decision',protocol='faraday-manufacturing/1',track='cad',payload=public_packet(byid[args.task])))
                return 0
            if args.task.startswith('sensor-'):
                from .sensor_cases import catalog as sensor_catalog
                from .sensors import public_task,TOOLS
                byid={t['id']:t for t in sensor_catalog()}
                if args.task not in byid:raise ValueError('unknown sensor task ID')
                task=byid[args.task]
                save(args.output,dict(type='decision',protocol='faraday-manufacturing/1',track='sensors',payload=dict(clock_minute=0,calls_remaining=task['max_tool_calls'],last_result=None,task=public_task(task),tools=TOOLS)))
                return 0
            if args.task.startswith('p2p-'):
                from .procurement_cases import catalog as procurement_catalog
                from .procurement import public_task,TOOLS
                byid={t['id']:t for t in procurement_catalog()}
                if args.task not in byid:raise ValueError('unknown procurement task ID')
                task=byid[args.task]
                save(args.output,dict(type='decision',protocol='faraday-manufacturing/1',track='procurement',payload=dict(clock_minute=0,calls_remaining=task['max_tool_calls'],last_result=None,task=public_task(task),tools=TOOLS)))
                return 0
            if args.task.startswith('supply-'):
                from .supply_cases import catalog
                from .supply_chain import public_task,TOOLS
                byid={t['id']:t for t in catalog()}
                if args.task not in byid:raise ValueError('unknown supply-chain task ID')
                task=byid[args.task]
                save(args.output,dict(type='decision',protocol='faraday-manufacturing/1',track='supply_chain',payload=dict(clock_minute=0,calls_remaining=task['max_tool_calls'],last_result=None,task=public_task(task),tools=TOOLS)))
                return 0
            from .shopfloor import TOOLS
            from .shopfloor_views import public_task
            byid={t['id']:t for t in workflow_catalog()}
            if args.task not in byid:raise ValueError('unknown manufacturing workflow ID')
            task=byid[args.task]
            save(args.output,dict(type='decision',protocol='faraday-manufacturing/1',track='workflow',payload=dict(clock_minute=0,calls_remaining=task['max_tool_calls'],last_result=None,task=public_task(task),tools=TOOLS)))
        elif args.command in ('export-cad','cad','grade-cad'):
            from .cad_cases import catalog as cad_catalog
            from .cad import export_packet,run,summary,public_packet,grade_candidate
            from .shopfloor import digest
            byid={t['id']:t for t in cad_catalog()}
            if args.command=='export-cad':
                if args.task not in byid:raise ValueError('unknown CAD task ID')
                export_packet(byid[args.task],args.output_dir)
            elif args.command=='cad':
                from .agents import DecisionAgent
                if len(set(args.task))!=len(args.task) or any(k not in byid for k in args.task):raise ValueError('unknown or duplicate CAD task ID')
                artifact=dict(track='manufacturing-cad',version=__version__,episodes=[])
                for key in args.task:
                    with DecisionAgent(args.agent_command,args.timeout,max_reply_bytes=7100000) as agent:episode=run(byid[key],agent,args.kernel_timeout)
                    artifact['episodes'].append(episode);save(args.output,artifact)
                artifact['summary']=summary(artifact['episodes']);save(args.output,artifact)
            else:
                import base64
                if args.task not in byid:raise ValueError('unknown CAD task ID')
                task=byid[args.task]
                if args.program:
                    value=json.loads(Path(args.program).read_text());answer=dict(program=value) if isinstance(value,dict) and 'op' in value else value
                else:
                    path=Path(args.step)
                    if path.stat().st_size>5_000_000:raise ValueError('STEP exceeds five MB')
                    answer=dict(step_base64=base64.b64encode(path.read_bytes()).decode())
                result=grade_candidate(task,answer,args.kernel_timeout,args.export_step)
                episode=dict(evaluator_task_id=task['id'],source_commitment=digest(task),public_input=public_packet(task),answer=answer,result=result,status='finished',kernel_timeout_seconds=args.kernel_timeout)
                artifact=dict(track='manufacturing-cad',version=__version__,episodes=[episode],summary=summary([episode]));save(args.output,artifact)
        elif args.command=='export-sensor-data':
            import hashlib
            from .sensor_cases import catalog as sensor_catalog,build as build_sensor
            byid={t['id']:t for t in sensor_catalog()}
            if args.task not in byid:raise ValueError('unknown sensor task ID')
            source=build_sensor(byid[args.task]);out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
            (out/'observations.csv').write_text(source['stream']['csv'])
            save(out/'policy.json',source['policy']);save(out/'asset.json',source['asset'])
            save(out/'index.json',dict(provenance='synthetic-generated',files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (out/'observations.csv',out/'policy.json',out/'asset.json')},stream={k:v for k,v in source['stream'].items() if k!='csv'}))
        elif args.command=='sensors':
            from .agents import DecisionAgent
            from .sensor_cases import catalog as sensor_catalog
            from .sensors import run
            byid={t['id']:t for t in sensor_catalog()}
            if len(set(args.task))!=len(args.task) or any(k not in byid for k in args.task):raise ValueError('unknown or duplicate sensor task ID')
            artifact=dict(track='manufacturing-sensors',version=__version__,episodes=[])
            def checkpoint(episode):
                artifact['current_episode']=episode;save(args.output,artifact)
            for key in args.task:
                with DecisionAgent(args.agent_command,args.timeout) as agent:episode=run(byid[key],agent,checkpoint)
                artifact['episodes'].append(episode)
            artifact.pop('current_episode',None);artifact['summary']=summarize([e['result'] for e in artifact['episodes']]);save(args.output,artifact)
        elif args.command=='export-procurement-documents':
            import hashlib
            from .procurement_cases import catalog as procurement_catalog,build
            from .procurement import public_task
            byid={t['id']:t for t in procurement_catalog()}
            if args.task not in byid:raise ValueError('unknown procurement task ID')
            task=byid[args.task];out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True);index=[]
            for doc in build(task)['documents'].values():
                if doc['available_minute']!=0:continue
                extension={'message/rfc822':'eml','text/csv':'csv','text/plain':'txt'}[doc['mime_type']]
                path=out/(doc['id']+'.'+extension);blob=doc['body'].encode();path.write_bytes(blob)
                index.append(dict(document_id=doc['id'],filename=path.name,mime_type=doc['mime_type'],sha256=hashlib.sha256(blob).hexdigest()))
            save(out/'index.json',dict(snapshot_minute=0,provenance='synthetic-generated',task=public_task(task),documents=index,limitation='Initial source snapshot only; subsequent deliveries, invoices, corrections and bank callbacks are generated during execution.'))
        elif args.command=='procurement':
            from .agents import DecisionAgent
            from .procurement_cases import catalog as procurement_catalog
            from .procurement import run,summary
            byid={t['id']:t for t in procurement_catalog()}
            if len(set(args.task))!=len(args.task) or any(k not in byid for k in args.task):raise ValueError('unknown or duplicate procurement task ID')
            artifact=dict(track='procurement-chain',version=__version__,episodes=[])
            def checkpoint(episode):
                artifact['current_episode']=episode;save(args.output,artifact)
            for key in args.task:
                with DecisionAgent(args.agent_command,args.timeout) as agent:episode=run(byid[key],agent,checkpoint)
                artifact['episodes'].append(episode)
            artifact.pop('current_episode',None);artifact['summary']=summary([e['result'] for e in artifact['episodes']]);save(args.output,artifact)
        elif args.command=='supply-chain':
            from .agents import DecisionAgent
            from .supply_cases import catalog
            from .supply_chain import run
            byid={t['id']:t for t in catalog()}
            if len(set(args.task))!=len(args.task) or any(k not in byid for k in args.task):raise ValueError('unknown or duplicate supply-chain task ID')
            artifact=dict(track='supply-chain',version=__version__,episodes=[])
            def checkpoint(episode):
                artifact['current_episode']=episode;save(args.output,artifact)
            for key in args.task:
                with DecisionAgent(args.agent_command,args.timeout) as agent:episode=run(byid[key],agent,checkpoint)
                artifact['episodes'].append(episode)
            artifact.pop('current_episode',None)
            artifact['summary']=summarize([e['result'] for e in artifact['episodes']]);save(args.output,artifact)
        elif args.command=='workflow':
            from .agents import DecisionAgent
            from .shopfloor_runner import run,summary
            byid={t['id']:t for t in workflow_catalog()}
            if len(set(args.task))!=len(args.task) or any(k not in byid for k in args.task):raise ValueError('unknown or duplicate manufacturing workflow ID')
            artifact=dict(track='manufacturing-workflow',version=__version__,episodes=[])
            def checkpoint(episode):
                artifact['current_episode']=episode;save(args.output,artifact)
            for key in args.task:
                with DecisionAgent(args.agent_command,args.timeout) as agent:episode=run(byid[key],agent,checkpoint)
                artifact['episodes'].append(episode)
            artifact.pop('current_episode',None);artifact['summary']=summary([e['result'] for e in artifact['episodes']]);save(args.output,artifact)
        elif args.command=='export-document-packet':
            from .document_cases import catalog
            from .documents import export_packet
            byid={t['id']:t for t in catalog()}
            if args.task not in byid:raise ValueError('unknown document task ID')
            export_packet(byid[args.task],args.output_dir)
        elif args.command=='documents':
            from .document_cases import catalog
            from .documents import run
            from .agents import DecisionAgent
            byid={t['id']:t for t in catalog()}
            if len(set(args.task))!=len(args.task) or any(k not in byid for k in args.task):raise ValueError('unknown or duplicate document task ID')
            artifact=dict(track='manufacturing-documents',version=__version__,episodes=[])
            for key in args.task:
                with DecisionAgent(args.agent_command,args.timeout) as agent:artifact['episodes'].append(run(byid[key],agent))
                artifact['summary']=summarize([e['result'] for e in artifact['episodes']]);save(args.output,artifact)
        elif args.command=='engineering':
            from .agents import DecisionAgent
            byid={t['id']:t for t in TASKS}
            if len(set(args.task))!=len(args.task) or any(k not in byid for k in args.task):raise ValueError('unknown or duplicate engineering task ID')
            results=[]
            with DecisionAgent(args.agent_command,args.timeout) as agent:
                for key in args.task:
                    answer=agent.decide('engineering',byid[key]);row=grade(byid[key],answer);row['answer']=answer;results.append(row)
            save(args.output,dict(track='engineering',results=results,summary=summarize(results)))
        elif args.command=='compare':
            from .statistics import paired_comparison
            def read_results(paths):
                rows=[]
                for path in paths:
                    run=json.loads(Path(path).read_text())
                    if run['track']!='manufacturing-season':raise ValueError('comparison requires factory-season run artifacts')
                    rows.append(run['result'])
                return rows
            save(args.output,paired_comparison(read_results(args.candidate),read_results(args.baseline)))
        elif args.command=='grade':
            answers=json.loads(Path(args.answers).read_text());byid={t['id']:t for t in TASKS}
            if len(set(args.task))!=len(args.task):raise ValueError('duplicate selected task ID')
            if any(k not in byid for k in args.task):raise ValueError('unknown engineering task ID')
            if not isinstance(answers,dict) or set(answers)!=set(args.task):raise ValueError('answers must contain exactly the selected task IDs')
            results=[grade(byid[k],answers[k]) for k in args.task]
            save(args.output,dict(track='engineering',results=results,summary=summarize(results)))
        elif args.command=='execute':
            from faraday_industrial_benchmark.models import IncidentTask
            from faraday_industrial_benchmark.runner import BenchmarkRunner,CommandAgent
            byid={t['id']:t for t in workflows()}
            if len(set(args.task))!=len(args.task):raise ValueError('duplicate selected task ID')
            if any(k not in byid for k in args.task):raise ValueError('unknown manufacturing execution task ID')
            selected=[IncidentTask.from_dict(byid[k]) for k in args.task]
            result=BenchmarkRunner().run_suite(selected,CommandAgent(args.agent_command,timeout_seconds=args.timeout))
            result['track']='manufacturing-execution';result['manufacturing_version']=__version__;save(args.output,result)
        elif args.command=='season':
            case=next(c for c in CASES if c.id==args.case);world=FactorySeason(case,args.draw)
            if args.agent_command:
                from .agents import DecisionAgent
                with DecisionAgent(args.agent_command,args.timeout) as agent:
                    while world.week<case.weeks:world.step(agent.decide('factory',world.observe()))
            else:
                policy={'idle':idle_policy,'rule':rule_policy}[args.policy]
                while world.week<case.weeks:world.step(policy(world.observe()))
            save(args.output,dict(track='manufacturing-season',case=asdict(case),draw=args.draw,policy=args.policy or 'external-agent',trace=world.trace,result=world.result()))
        elif args.command=='replay':
            value=json.loads(Path(args.run).read_text())
            if value.get('track')=='production-campaign':
                from .campaign import catalog as campaign_catalog,replay as replay_campaign
                byid={t['id']:t for t in campaign_catalog()}
                replay_campaign(byid[value['evaluator_task_id']],value)
            elif value['track']=='manufacturing-documents':
                from .document_cases import catalog
                from .documents import replay as replay_documents
                byid={t['id']:t for t in catalog()}
                if not value.get('episodes'):raise ValueError('document replay requires nonempty episodes')
                for episode in value['episodes']:replay_documents(byid[episode['evaluator_task_id']],episode)
                if value.get('summary')!=summarize([e['result'] for e in value['episodes']]):raise ValueError('document summary mismatch')
            elif value['track']=='manufacturing-workflow':
                from .shopfloor import replay as replay_workflow
                from .shopfloor_runner import public_task
                byid={t['id']:t for t in workflow_catalog()}
                if not value.get('episodes'):raise ValueError('workflow replay requires nonempty episodes')
                for episode in value['episodes']:
                    task=byid[episode.get('evaluator_task_id',episode['task']['id'])]
                    if episode['task']!=public_task(task,episode['task']['id']):raise ValueError('workflow task contract mismatch')
                    actual=replay_workflow(task,episode['trace'])
                    if actual!=episode['result']:raise ValueError('workflow terminal result mismatch')
            elif value['track']=='manufacturing-cad':
                from .cad_cases import catalog as cad_catalog
                from .cad import replay as replay_cad,summary as cad_summary
                byid={t['id']:t for t in cad_catalog()}
                if not value.get('episodes'):raise ValueError('CAD replay requires nonempty episodes')
                for episode in value['episodes']:replay_cad(byid[episode['evaluator_task_id']],episode)
                if value.get('summary')!=cad_summary(value['episodes']):raise ValueError('CAD summary mismatch')
            elif value['track']=='manufacturing-sensors':
                from .sensor_cases import catalog as sensor_catalog
                from .sensors import replay as replay_sensor
                byid={t['id']:t for t in sensor_catalog()}
                if not value.get('episodes'):raise ValueError('sensor replay requires nonempty episodes')
                for episode in value['episodes']:
                    actual=replay_sensor(byid[episode['evaluator_task_id']],episode['trace'])
                    if actual!=episode['result']:raise ValueError('sensor terminal result mismatch')
                if value.get('summary')!=summarize([e['result'] for e in value['episodes']]):raise ValueError('sensor summary mismatch')
            elif value['track']=='procurement-chain':
                from .procurement_cases import catalog as procurement_catalog
                from .procurement import replay as replay_procurement,summary as procurement_summary
                byid={t['id']:t for t in procurement_catalog()}
                if not value.get('episodes'):raise ValueError('procurement replay requires nonempty episodes')
                for episode in value['episodes']:
                    actual=replay_procurement(byid[episode['evaluator_task_id']],episode['trace'])
                    if actual!=episode['result']:raise ValueError('procurement terminal result mismatch')
                if value.get('summary')!=procurement_summary([e['result'] for e in value['episodes']]):raise ValueError('procurement summary mismatch')
            elif value['track']=='supply-chain':
                from .supply_cases import catalog
                from .supply_chain import replay as replay_supply
                byid={t['id']:t for t in catalog()}
                if not value.get('episodes'):raise ValueError('supply-chain replay requires nonempty episodes')
                for episode in value['episodes']:
                    actual=replay_supply(byid[episode['evaluator_task_id']],episode['trace'])
                    if actual!=episode['result']:raise ValueError('supply-chain terminal result mismatch')
                if 'summary' in value and value['summary']!=summarize([e['result'] for e in value['episodes']]):raise ValueError('supply-chain summary mismatch')
            elif value['track']=='manufacturing-season':
                from .season import SeasonCase
                actual=replay(SeasonCase(**value['case']),value['draw'],value['trace'])
                if actual!=value['result']:raise ValueError('terminal season result mismatch')
            elif value['track']=='manufacturing-execution':
                from faraday_industrial_benchmark.models import IncidentTask
                from faraday_industrial_benchmark.runner import BenchmarkRunner
                byid={t['id']:t for t in workflows()}
                for result in value['results']:
                    actual=BenchmarkRunner().replay(IncidentTask.from_dict(byid[result['task']['id']]),result['trace'])
                    if not actual['exact_match'] or any(actual[k]!=result[k] for k in ('score','initial_state_hash','final_state_hash','final_answer','applied_events')):raise ValueError('execution replay mismatch')
            else:raise ValueError('unsupported replay track')
            print('Replay matches every transition and terminal result.')
    except (ValueError,KeyError,OSError) as exc:
        parser.error(str(exc))
    return 0
