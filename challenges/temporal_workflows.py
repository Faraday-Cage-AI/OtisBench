"""Temporal manufacturing stress tier; source-run extension of the shop-floor engine.

64 cases: the 32 existing route families with two staggered-calendar draws.
These are harder temporal variants, not 64 new workflow structures or a heldout.
No policy or reference answer is inserted into the agent transport.
"""
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path
import random

from faraday_manufacturing_benchmark.shopfloor import ManufacturingWorkflow,TOOLS,digest
from faraday_manufacturing_benchmark.shopfloor_cases import catalog as native_catalog
from faraday_manufacturing_benchmark.shopfloor_views import AgentView,public_task


def catalog():
    rows=[]
    for base in native_catalog():
        if base['disruption']!='compound_recovery':continue
        task=deepcopy(base);task['source_task_id']=base['id']
        task['id']=f"temporal-{base['family']}-{base['draw']+1:02}"
        task['seed']=int.from_bytes(hashlib.sha256(task['id'].encode()).digest()[:8],'big')
        rows.append(task)
    return rows


class TemporalWorkflow(ManufacturingWorkflow):
    def __init__(self,task):
        super().__init__(task)
        rng=random.Random(f"temporal-calendar-v1:{task['seed']}")
        self.calendar=[dict(kind='engineering_release',at=rng.randint(28,66)),
                       dict(kind='quality_disposition',at=rng.randint(78,132)),
                       dict(kind='machine_trip',at=rng.randint(43,100))]
        self.calendar.sort(key=lambda e:(e['at'],e['kind']));self.fired=set()
        r=self.records
        for change in r['PLM']['change_requests']:
            change['review_due_minute']=next(e['at'] for e in self.calendar if e['kind']=='engineering_release')
        for investigation in r['QMS']['supplier_investigations']:
            investigation['review_due_minute']=next(e['at'] for e in self.calendar if e['kind']=='quality_disposition')
        # Another work order occupies a real shared fixture. Booking data are observable.
        self.booking_end=rng.randint(120,170)
        r['QMS']['instruments']['FIX-02']['busy'].append(dict(start=80,finish=self.booking_end,source='other-work-order'))
        # Qualification is time-bounded, not just a static machine/process match.
        r['HR']['operators']['EMP-02']['certified_until_minute']=rng.randint(90,150)
        # A blind wait to minute 300 is strictly later than this feasible-window
        # envelope even before adding any subsequent read/inspection/rework calls.
        self.planning_epoch=max(self.booking_end,max(e['at'] for e in self.calendar))
        self.routing_minutes=0
        for index,operation in enumerate(r['MES']['operations']):
            machine=r['MES']['machines'][f"M-{index+1:02}"+('-ALT' if index==0 else '')]
            import math
            self.routing_minutes+=math.ceil(machine['setup_minutes']+machine['minutes_per_unit']*r['ERP']['required_units'])
        self.deadline=self.planning_epoch+self.routing_minutes+125
        for order in r['ERP']['orders']:order['due_minute']=self.deadline
        self.source_commitment=digest(dict(task=task,records=r,calendar=self.calendar))
        self.initial_state_hash=self.state_hash()

    def state_hash(self):
        return digest(dict(core=super().state_hash(),calendar=getattr(self,'calendar',[]),fired=sorted(getattr(self,'fired',set()))))

    def _core_advance(self,minutes):
        # Preserve the established receipt/certificate engine while suppressing
        # the parent generator's one fixed minute-18 compound event.
        actual=self.events
        self.events=actual+['disruption']
        try:super()._advance(minutes)
        finally:self.events=actual

    def _advance(self,minutes):
        target=self.clock+minutes
        for event in getattr(self,'calendar',[]):
            if event['kind'] in self.fired or event['at']>target:continue
            self._core_advance(max(0,event['at']-self.clock))
            self._apply_event(event)
            self.fired.add(event['kind'])
        self._core_advance(target-self.clock)

    def _apply_event(self,event):
        r=self.records;kind=event['kind']
        if kind=='engineering_release':
            r['PLM']['revision']='B'
            for change in r['PLM']['change_requests']:change['status']='released'
            for instruction in r['PLM']['instructions'].values():
                instruction['revision']='B'
                key=next(k for k in ('surface_m_min','target_temperature_c','amps','projected_area_cm2','ingredient_a_kg','zone_length_mm','energy_kwh_batch') if k in instruction)
                instruction[key]+=12
            self._bump('PLM')
        elif kind=='quality_disposition':
            r['WMS']['lots']['LOT-MAIN']['status']='hold'
            for investigation in r['QMS']['supplier_investigations']:investigation.update(status='closed',disposition='hold')
            self._bump('WMS','QMS')
        elif kind=='machine_trip':
            r['MES']['machines']['M-01']['status']='down'
            for operation in r['MES']['operations']:
                if operation['status']=='running' and operation['machine']=='M-01' and operation['finish']>event['at']:operation['status']='interrupted'
            self._bump('MES','CMMS')

    def _do_wait(self,minutes):
        if type(minutes) is not int or not 1<=minutes<=300:return self._error('invalid wait interval')
        self._advance(minutes)
        return dict(ok=True,clock_minute=self.clock)


def run(task,agent):
    world=TemporalWorkflow(task);view=AgentView();last=None;transport=[];error=None
    try:
        while not world.finished and len(world.trace)<task['max_tool_calls']:
            payload=dict(clock_minute=world.clock,calls_remaining=task['max_tool_calls']-len(world.trace),last_result=last)
            if not world.trace:payload.update(task=public_task(task,view.episode_id),tools=deepcopy(TOOLS))
            decision=agent.decide('workflow',payload)
            if not isinstance(decision,dict) or set(decision)!={'tool','arguments'} or not isinstance(decision['tool'],str) or not isinstance(decision['arguments'],dict):raise ValueError('invalid tool decision')
            result=world.call(decision['tool'],**view.decode(decision['arguments']))
            last=view.result(result);transport.append(dict(decision=deepcopy(decision),result=deepcopy(last)))
    except (ValueError,OSError) as exc:error=type(exc).__name__
    return dict(protocol='temporal-manufacturing/1',evaluator_task_id=task['id'],task=public_task(task,view.episode_id),
                result=world.grade(),trace=world.trace,agent_trace=transport,error_type=error)


def replay(task,trace):
    world=TemporalWorkflow(task)
    for i,record in enumerate(trace):
        world.call(record['tool'],**record['arguments'])
        if world.trace[-1]!=record:raise ValueError(f'temporal replay mismatch at call {i}')
    return world.grade()


def source_fingerprints():
    root=Path(__file__).resolve().parents[1]
    names=['challenges/temporal_workflows.py','src/faraday_manufacturing_benchmark/shopfloor.py','src/faraday_manufacturing_benchmark/shopfloor_cases.py','src/faraday_manufacturing_benchmark/shopfloor_views.py','src/faraday_manufacturing_benchmark/isolation.py','src/faraday_manufacturing_benchmark/agents.py']
    return {name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in names}


def main(argv=None):
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('list')
    execute=sub.add_parser('run');execute.add_argument('--task',required=True);execute.add_argument('--agent-file',required=True);execute.add_argument('--output',required=True)
    check=sub.add_parser('replay');check.add_argument('artifact')
    args=p.parse_args(argv);byid={t['id']:t for t in catalog()}
    if args.command=='list':
        for task in byid.values():print(task['id'])
    elif args.command=='run':
        if args.task not in byid:p.error('unknown temporal workflow')
        from faraday_manufacturing_benchmark.isolation import isolated_agent
        with isolated_agent(args.agent_file,timeout=120) as agent:
            artifact=run(byid[args.task],agent);artifact['isolation']=agent.isolation
        artifact['source_hashes']=source_fingerprints()
        path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(artifact,indent=2,sort_keys=True)+'\n')
    else:
        artifact=json.loads(Path(args.artifact).read_text())
        if artifact['source_hashes']!=source_fingerprints():raise ValueError('temporal or base evaluator source changed')
        actual=replay(byid[artifact['evaluator_task_id']],artifact['trace'])
        if actual!=artifact['result']:raise ValueError('terminal temporal result differs')
        print('Every temporal transition and terminal result matches.')
    return 0


if __name__=='__main__':raise SystemExit(main())
