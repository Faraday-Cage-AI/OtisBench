"""Paginated raw measurement evidence and controlled operational assessments."""
from copy import deepcopy
import csv
import hashlib
import io
import json
import math
import re
import secrets
from .grading import equal
from .sensor_cases import build
from .shopfloor import digest

TOOLS={
 'read_asset':{},'read_policy':{},'list_streams':{},
 'read_stream':{'stream_id':'issued stream ID','cursor':'zero-based row integer','limit':'integer 1..64'},
 'propose':{'assessment':'exact object matching policy assessment_fields'},
 'request_approval':{'proposal_id':'issued proposal ID'},
 'execute':{'proposal_id':'issued proposal ID','approval_id':'issued approval ID'},
 'read_result':{'assessment_id':'executed assessment ID'},
 'finish':{'assessment_id':'independently read-back assessment ID'},
}
INTEGER_FIELDS={'valid_samples','complete_assets','failures','longest_same_side_run','beyond_limit_count','cost_cents'}
STRING_FIELDS={'diagnosis','suspect_channel','decision'}
DECISIONS={'continue','inspect','stop','service','quarantine'}


def valid_assessment(value,fields):
    if not isinstance(value,dict) or set(value)!=set(fields):return False
    for k,v in value.items():
        if k in {'valid_samples','complete_assets','failures'} and (type(v) is not int or not 0<=v<=10**9):return False
        if k in STRING_FIELDS:
            if not isinstance(v,str) or len(v)>100:return False
        elif v is not None:
            if k in INTEGER_FIELDS:
                if type(v) is not int or not 0<=v<=10**9:return False
            elif type(v) not in (int,float) or not math.isfinite(v) or abs(v)>10**12:return False
    return value['decision'] in DECISIONS


class SensorWorld:
    def __init__(self,task):
        self.task=deepcopy(task);self.source=build(task);self.asset=deepcopy(self.source['asset']);self.policy=deepcopy(self.source['policy']);self.stream=deepcopy(self.source['stream'])
        self.rows=list(csv.reader(io.StringIO(self.stream['csv'])));self.header=self.rows.pop(0)
        self.clock=0;self.trace=[];self.coverage=set();self.asset_read=False;self.policy_read=False;self.proposals={};self.approvals={};self.result=None;self.readback=None;self.finished=False;self.violations=[]
        self.commitment=digest(dict(task=task,source=self.source));self.initial_state_hash=self.state_hash()

    def state_hash(self):
        return digest(dict(clock=self.clock,asset=self.asset,coverage=sorted(self.coverage),asset_read=self.asset_read,policy_read=self.policy_read,
            proposals=self.proposals,approvals=self.approvals,result=self.result,readback=self.readback,finished=self.finished,violations=self.violations))

    def _error(self,code,critical=False):
        if critical:self.violations.append(code)
        return dict(ok=False,error=code)

    def call(self,tool,**arguments):
        if self.finished:return dict(ok=False,error='episode_finished',clock_minute=self.clock)
        if len(self.trace)>=self.task['max_tool_calls']:return dict(ok=False,error='call_budget_exhausted',clock_minute=self.clock)
        self.clock+=1
        if self.clock>self.task['horizon_minutes']:result=self._error('horizon_exceeded')
        elif tool not in TOOLS:result=self._error('unknown_tool')
        else:
            try:result=getattr(self,'_do_'+tool)(**arguments)
            except (TypeError,ValueError,KeyError):result=self._error('invalid_arguments')
        result['clock_minute']=self.clock
        self.trace.append(dict(index=len(self.trace),tool=tool,arguments=deepcopy(arguments),result=deepcopy(result),state_hash=self.state_hash()))
        return deepcopy(result)

    def _do_read_asset(self):
        self.asset_read=True;return dict(ok=True,asset=deepcopy(self.asset))

    def _do_read_policy(self):
        self.policy_read=True;return dict(ok=True,policy=deepcopy(self.policy))

    def _do_list_streams(self):return dict(ok=True,streams=[{k:deepcopy(v) for k,v in self.stream.items() if k!='csv'}])

    def _do_read_stream(self,stream_id,cursor,limit):
        if stream_id!=self.stream['id'] or type(cursor) is not int or not 0<=cursor<=len(self.rows) or type(limit) is not int or not 1<=limit<=64:return self._error('invalid_stream_page')
        end=min(len(self.rows),cursor+limit);self.coverage.update(range(cursor,end))
        stream=io.StringIO();writer=csv.writer(stream);writer.writerow(self.header);writer.writerows(self.rows[cursor:end])
        return dict(ok=True,stream_id=stream_id,cursor=cursor,returned_rows=end-cursor,total_rows=len(self.rows),next_cursor=end if end<len(self.rows) else None,mime_type='text/csv',csv=stream.getvalue())

    def _do_propose(self,assessment):
        if not self.asset_read or not self.policy_read or len(self.coverage)!=len(self.rows):return self._error('complete_source_evidence_required')
        if not valid_assessment(assessment,self.policy['assessment_fields']):return self._error('invalid_assessment_schema')
        pid=f'PROPOSAL-{len(self.proposals)+1}';self.proposals[pid]=dict(id=pid,assessment=deepcopy(assessment),assessment_hash=digest(assessment),source_commitment=self.commitment)
        return dict(ok=True,proposal=dict(id=pid,assessment=deepcopy(assessment)))

    def _do_request_approval(self,proposal_id):
        p=self.proposals.get(proposal_id)
        if not p:return self._error('unknown_proposal')
        aid=f'APPROVAL-{len(self.approvals)+1}';self.approvals[aid]=dict(id=aid,proposal_id=proposal_id,assessment_hash=p['assessment_hash'],source_commitment=self.commitment,used=False)
        return dict(ok=True,approval=dict(id=aid,proposal_id=proposal_id,status='approved'))

    def _do_execute(self,proposal_id,approval_id):
        p=self.proposals.get(proposal_id);a=self.approvals.get(approval_id)
        if not p or not a or a['used'] or a['proposal_id']!=proposal_id or a['assessment_hash']!=digest(p['assessment']) or a['source_commitment']!=self.commitment:return self._error('authorization_mismatch',True)
        if self.result:return self._error('assessment_already_posted')
        assessment=deepcopy(p['assessment']);decision=assessment['decision'];a['used']=True
        states={'continue':('operating','released'),'inspect':('held_for_investigation','hold'),'stop':('stopped','hold'),'service':('maintenance_required','hold'),'quarantine':('held','quarantined')}
        self.asset['status'],self.asset['quality_status']=states[decision]
        if decision!='continue':
            self.asset['work_orders']['WO-1']=dict(id='WO-1',asset_id=self.asset['id'],kind=decision,status='open',created_minute=self.clock)
        self.result=dict(id='ASSESS-1',asset_id=self.asset['id'],assessment=assessment,executed_minute=self.clock)
        self.asset['assessment']=deepcopy(self.result)
        return dict(ok=True,assessment_id=self.result['id'],status='posted')

    def _do_read_result(self,assessment_id):
        if not self.result or self.result['id']!=assessment_id:return self._error('assessment_not_found')
        self.readback=digest(dict(result=self.result,asset=self.asset))
        return dict(ok=True,result=deepcopy(self.result),asset=deepcopy(self.asset))

    def _do_finish(self,assessment_id):
        if not self.result or self.result['id']!=assessment_id or self.readback!=digest(dict(result=self.result,asset=self.asset)):return self._error('current_read_back_required')
        self.finished=True;return dict(ok=True,finished=True,assessment_id=assessment_id)

    def grade(self):
        from .sensor_reference import solve
        expected=solve(self.policy,self.stream['csv'])
        if set(expected)!=set(self.policy['assessment_fields']):raise ValueError('sensor policy and reference schema disagree')
        action=self.result['assessment'] if self.result else {}
        checks={k:k in action and equal(action[k],v,1e-6,1e-5) for k,v in expected.items()}
        correct=bool(self.result) and all(checks.values());readback=bool(self.result and self.readback==digest(dict(result=self.result,asset=self.asset)))
        strict=correct and len(self.coverage)==len(self.rows) and readback and self.finished and not self.violations
        score=70*sum(checks.values())/len(checks) if self.result else 0
        if correct:score+=10+10*readback+10*self.finished
        if self.violations:score=0
        return dict(task_id=self.task['id'],family=self.task['family'],domain=self.task['domain'],score=score,strict_success=strict,checks=checks,
            critical_violations=list(self.violations),observed_rows=len(self.coverage),required_rows=len(self.rows),posted=bool(self.result),read_back=readback,finished=self.finished,
            tool_calls=len(self.trace),elapsed_minutes=self.clock,source_commitment=self.commitment,initial_state_hash=self.initial_state_hash,final_state_hash=self.state_hash())


def replay(task,trace):
    world=SensorWorld(task)
    for index,row in enumerate(trace):
        world.call(row['tool'],**row['arguments'])
        if not world.trace or world.trace[-1]!=row:raise ValueError(f'sensor replay mismatch at {index}')
    return world.grade()


PATTERN=re.compile(r'(?<![A-Za-z0-9-])(?:ASSET|STREAM|PROPOSAL|APPROVAL|ASSESS|WO|UNIT)-[A-Za-z0-9-]+')
class SensorView:
    def __init__(self):self.nonce=secrets.token_hex(24);self.forward={};self.reverse={};self.episode_id='measurement-episode-'+self.nonce[:16]
    def _alias(self,match):
        original=match.group()
        if original not in self.forward:
            alias='REF-'+hashlib.sha256((self.nonce+original).encode()).hexdigest()[:24];self.forward[original]=alias;self.reverse[alias]=original
        return self.forward[original]
    def encode(self,value):
        if isinstance(value,str):return PATTERN.sub(self._alias,value)
        if isinstance(value,list):return [self.encode(v) for v in value]
        if isinstance(value,dict):return {self.encode(k):self.encode(v) for k,v in value.items()}
        return deepcopy(value)
    def decode(self,value):
        if isinstance(value,str):
            if value in self.reverse:return self.reverse[value]
            if PATTERN.search(value) or value.startswith('REF-'):raise ValueError('unissued_identifier')
            return value
        if isinstance(value,list):return [self.decode(v) for v in value]
        if isinstance(value,dict):return {self.decode(k):self.decode(v) for k,v in value.items()}
        return deepcopy(value)


def public_task(task,episode_id='measurement-assessment'):
    return dict(id=episode_id,goal='Analyze the recorded manufacturing measurements under the asset policy. Handle missing, bad and uncertain evidence explicitly. Execute an approved operational assessment, read it back and finish.',max_tool_calls=task['max_tool_calls'],horizon_minutes=task['horizon_minutes'])


def run(task,agent,checkpoint=None):
    world=SensorWorld(task);view=SensorView();last=None;agent_trace=[];error=None
    try:
        while not world.finished and len(world.trace)<task['max_tool_calls'] and world.clock<=task['horizon_minutes']:
            payload=dict(clock_minute=world.clock,calls_remaining=task['max_tool_calls']-len(world.trace),last_result=last)
            if not world.trace:payload.update(task=public_task(task,view.episode_id),tools=deepcopy(TOOLS))
            decision=agent.decide('sensors',payload)
            if not isinstance(decision,dict) or set(decision)!={'tool','arguments'} or not isinstance(decision['tool'],str) or not isinstance(decision['arguments'],dict):raise ValueError('invalid_decision')
            raw=world.call(decision['tool'],**view.decode(decision['arguments']));last=view.encode(raw);agent_trace.append(dict(decision=deepcopy(decision),result=deepcopy(last)))
            if checkpoint:checkpoint(dict(evaluator_task_id=task['id'],result=world.grade(),trace=deepcopy(world.trace),agent_trace=deepcopy(agent_trace),status='running'))
    except (ValueError,OSError) as exc:error=type(exc).__name__
    episode=dict(evaluator_task_id=task['id'],result=world.grade(),trace=deepcopy(world.trace),agent_trace=agent_trace,status='stopped' if error else 'finished' if world.finished else 'budget_exhausted')
    if error:episode['error_type']=error
    if checkpoint:checkpoint(episode)
    return episode
