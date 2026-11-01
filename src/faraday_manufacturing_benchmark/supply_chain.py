"""Synthetic cross-system procurement decisions with approvals and persisted writes.

This is a synthetic posting ledger, not an integration with a real ERP. Approval
models delegated permission, not a second agent solving the commercial decision.
"""
from copy import deepcopy
import hashlib
import json
import math
import re
import secrets
from .grading import equal
from .shopfloor import digest

TOOLS={
    'read':{'system':'ERP | SCM | WMS | QMS | AP | TMS'},
    'wait':{'minutes':'integer 1..20'},
    'propose':{'action':'object matching the public action_fields'},
    'request_approval':{'proposal_id':'issued proposal ID'},
    'execute':{'proposal_id':'issued proposal ID','approval_id':'issued approval ID'},
    'read_back':{'transaction_id':'posted transaction ID'},
    'finish':{'transaction_id':'read-back transaction ID'},
}
AP_FIELDS=set('invoice_units invoice_unit_cents price_tolerance_basis_points authorized_freight_cents previously_invoiced_units candidate existing approval_limit_cents contract_spend_cents spent_cents'.split())
WMS_FIELDS=set('released_onhand_units held_units stock_units destination_stock onhand_units book_units count_one_units count_two_units transactions_open lots opening_units onhand'.split())
QMS_FIELDS=set('certificate_valid damaged_units rejected_units authorization_valid within_window suspect_lots edges required_grade alternates minimum_remaining_days'.split())
TMS_FIELDS=set('lanes weight_kg deadline_hours requires_cold container_weight_kg container_volume_liters unit_weight_kg unit_volume_liters maximum_containers container_cents lost_units carrier_cap_cents deductible_cents claim_day deadline_day proof_available return_freight_cents freight_cents insurance_cents'.split())
ERP_FIELDS=set('required_units required_total_units gross_need_units due_day budget_cents orders required_grade build_day demand_units safety_units use_day minimum_otif_fraction'.split())

def source_system(key):
    for system,fields in [('AP',AP_FIELDS),('WMS',WMS_FIELDS),('QMS',QMS_FIELDS),('TMS',TMS_FIELDS),('ERP',ERP_FIELDS)]:
        if key in fields:return system
    return 'SCM'


def action_valid(action,fields):
    if not isinstance(action,dict) or set(action)!=set(fields):return False
    def valid(value,kind):
        if kind.startswith('nullable_'):
            return value is None or valid(value,kind.removeprefix('nullable_'))
        if kind=='boolean':return type(value) is bool
        if kind=='integer':return type(value) is int and abs(value)<=10**12
        if kind=='number':return type(value) in (int,float) and math.isfinite(value) and abs(value)<=10**12
        if kind=='string':return isinstance(value,str) and len(value)<=300
        if kind=='integer_array':return isinstance(value,list) and len(value)<=1000 and all(valid(v,'integer') for v in value)
        if kind=='string_array':return isinstance(value,list) and len(value)<=1000 and all(valid(v,'string') for v in value)
        if kind=='allocation_array':return isinstance(value,list) and len(value)<=1000 and all(isinstance(v,dict) and set(v)=={'lot_id','units'} and valid(v['lot_id'],'string') and valid(v['units'],'integer') and v['units']>0 for v in value)
        return False
    return all(valid(action[k],kind) for k,kind in fields.items())


class SupplyChainWorld:
    def __init__(self,task):
        self.task=deepcopy(task);self.inputs=deepcopy(task['inputs']);self.clock=0;self.version=1
        self.read_versions={};self.proposals={};self.approvals={};self.transactions={};self.readbacks=set()
        self.violations=[];self.trace=[];self.finished=False;self.finished_transaction=None
        self.pending=task['variant']==2
        self.source_commitment=digest(task);self.initial_state_hash=self.state_hash()

    def state_hash(self):
        return digest(dict(inputs=self.inputs,clock=self.clock,version=self.version,reads=self.read_versions,
            proposals=self.proposals,approvals=self.approvals,transactions=self.transactions,
            readbacks=sorted(self.readbacks),violations=self.violations,pending=self.pending,
            finished=self.finished,finished_transaction=self.finished_transaction))

    def _advance(self,minutes):
        self.clock+=minutes
        if self.pending and self.clock>=6:
            # Release a source amendment, not an answer. Which field changes is
            # frozen in the evaluator; its value is observable only after release.
            for key in ('required_units','gross_need_units','invoice_units','arrival_units','rejected_units','lost_units','units','book_units','mean_units_day','original_units','opening_units','maximum_carbon_kg'):
                if key in self.inputs:
                    self.inputs[key]+=1;break
            else:
                if 'candidate' in self.inputs:self.inputs['candidate']['amount_cents']+=100
                elif 'suspect_lots' in self.inputs:self.inputs['suspect_lots'].append('RAW-2')
                elif 'orders' in self.inputs:self.inputs['orders'][0]['receipt_day']+=3
            self.pending=False;self.version+=1

    def _error(self,code,critical=False):
        if critical:self.violations.append(code)
        return dict(ok=False,error=code,clock_minute=self.clock)

    def _sources_current(self):
        needed={source_system(k) for k in self.inputs}|{'SCM'}
        return not self.pending and all(self.read_versions.get(s)==self.version for s in needed)

    def call(self,tool,**arguments):
        if self.finished:return self._error('episode_finished')
        if len(self.trace)>=self.task['max_tool_calls']:return self._error('call_budget_exhausted')
        self._advance(1)
        if self.clock>self.task['horizon_minutes']:result=self._error('horizon_exceeded')
        elif tool not in TOOLS:result=self._error('unknown_tool')
        else:
            try:result=getattr(self,'_do_'+tool)(**arguments)
            except (TypeError,ValueError,KeyError):result=self._error('invalid_arguments')
        result['clock_minute']=self.clock
        self.trace.append(dict(index=len(self.trace),tool=tool,arguments=deepcopy(arguments),result=deepcopy(result),state_hash=self.state_hash()))
        return deepcopy(result)

    def _do_read(self,system):
        if system not in self.task['systems']:return self._error('unknown_system')
        self.read_versions[system]=self.version
        record=dict(facts={k:deepcopy(v) for k,v in self.inputs.items() if source_system(k)==system})
        if system=='SCM':record['source_amendment']=dict(status='pending' if self.pending else 'released',available_minute=6)
        return dict(ok=True,system=system,source_version=self.version,records=record)

    def _do_wait(self,minutes):
        if type(minutes) is not int or not 1<=minutes<=20:return self._error('invalid_wait')
        self._advance(minutes);return dict(ok=True)

    def _do_propose(self,action):
        if not self._sources_current():return self._error('source_version_mismatch')
        if not action_valid(action,self.task['fields']):return self._error('invalid_action_schema')
        pid=f'PROP-{len(self.proposals)+1}'
        row=dict(id=pid,action=deepcopy(action),source_version=self.version,action_hash=digest(action))
        self.proposals[pid]=row
        return dict(ok=True,proposal=deepcopy(row))

    def _do_request_approval(self,proposal_id):
        row=self.proposals.get(proposal_id)
        if not row or row['source_version']!=self.version or not self._sources_current():return self._error('source_version_mismatch')
        aid=f'AUTH-{len(self.approvals)+1}';self.approvals[aid]=dict(id=aid,proposal_id=proposal_id,source_version=self.version,action_hash=row['action_hash'],used=False)
        return dict(ok=True,approval=deepcopy(self.approvals[aid]))

    def _do_execute(self,proposal_id,approval_id):
        row=self.proposals.get(proposal_id);approval=self.approvals.get(approval_id)
        if not row or not approval or approval['used'] or approval['proposal_id']!=proposal_id or approval['action_hash']!=digest(row['action']):return self._error('authorization_mismatch',True)
        if not self._sources_current() or row['source_version']!=self.version or approval['source_version']!=self.version:return self._error('source_version_mismatch')
        if self.transactions:return self._error('already_posted')
        tid='TXN-1'
        # Persist exactly what the tested agent chose. No reference solver,
        # corrective filling, optimality gate, or answer-dependent approval.
        self.transactions[tid]=dict(id=tid,status='posted',action=deepcopy(row['action']),source_version=self.version,proposal_id=proposal_id,approval_id=approval_id)
        approval['used']=True
        return dict(ok=True,transaction_id=tid,status='posted')

    def _do_read_back(self,transaction_id):
        row=self.transactions.get(transaction_id)
        if not row:return self._error('transaction_not_found')
        self.readbacks.add(transaction_id)
        return dict(ok=True,transaction=deepcopy(row))

    def _do_finish(self,transaction_id):
        if transaction_id not in self.readbacks:return self._error('read_back_required')
        self.finished=True;self.finished_transaction=transaction_id
        return dict(ok=True,finished=True,transaction_id=transaction_id)

    def grade(self):
        from .supply_reference import solve
        expected=solve(self.task['family'],self.inputs)
        if set(expected)!=set(self.task['fields']):raise ValueError('supply action schema disagrees with evaluator')
        txn=self.transactions.get(self.finished_transaction) or next(iter(self.transactions.values()),None)
        action=txn['action'] if txn else {}
        checks={k:k in action and equal(action[k],v,1e-6,1e-5) for k,v in expected.items()}
        correct=bool(txn) and all(checks.values())
        readback=bool(txn and txn['id'] in self.readbacks)
        strict=correct and readback and self.finished and not self.violations
        # A confidently posted wrong action earns no procedural completion points.
        score=(70*sum(checks.values())/len(checks)+10+10*readback+10*self.finished) if correct else (70*sum(checks.values())/len(checks) if txn else 0)
        if self.violations:score=0
        return dict(task_id=self.task['id'],family=self.task['family'],domain=self.task['domain'],score=score,strict_success=strict,checks=checks,
            posted=bool(txn),read_back=readback,finished=self.finished,critical_violations=list(self.violations),tool_calls=len(self.trace),elapsed_minutes=self.clock,
            source_commitment=self.source_commitment,initial_state_hash=self.initial_state_hash,final_state_hash=self.state_hash())


ID_PATTERN=re.compile(r'(?<![A-Za-z0-9-])(?:SUP|LANE|PLANT|LOT|PART|BILL|RAW|WIP|FG|KIT|SHIP|PO|PROP|AUTH|TXN)-[A-Za-z0-9-]+')
class SupplyView:
    def __init__(self,task=None):
        self.nonce=secrets.token_hex(24);self.forward={};self.reverse={};self.episode_id='supply-episode-'+self.nonce[:16]
        identifiers=sorted(set(ID_PATTERN.findall(json.dumps(task['inputs'] if task else {}))))
        self.ranks={key:i for i,key in enumerate(identifiers)}
    def _alias(self,m):
        original=m.group()
        if original not in self.forward:
            # Preserve the public contract's lexical ordering without exposing
            # semantic internal names. Sorting aliases must not change answers.
            if original not in self.ranks:self.ranks[original]=len(self.ranks)
            alias=f'REF-{self.ranks[original]:06}-'+hashlib.sha256((self.nonce+original).encode()).hexdigest()[:20]
            self.forward[original]=alias;self.reverse[alias]=original
        return self.forward[original]
    def encode(self,value):
        if isinstance(value,str):return ID_PATTERN.sub(self._alias,value)
        if isinstance(value,list):return [self.encode(v) for v in value]
        if isinstance(value,dict):return {self.encode(k):self.encode(v) for k,v in value.items() if k!='action_hash'}
        return deepcopy(value)
    def decode(self,value):
        if isinstance(value,str):
            if value in self.reverse:return self.reverse[value]
            if ID_PATTERN.search(value) or value.startswith('REF-'):raise ValueError('unissued_identifier')
            return value
        if isinstance(value,list):return [self.decode(v) for v in value]
        if isinstance(value,dict):return {self.decode(k):self.decode(v) for k,v in value.items()}
        return deepcopy(value)


def public_task(task,episode_id='supply-chain-decision'):
    return dict(id=episode_id,goal=task['goal'],policy=task['policy'],action_fields=deepcopy(task['fields']),systems=list(task['systems']),
        execution_policy='Read current authoritative facts across systems. Resolve any pending SCM amendment. Propose your action, obtain proposal-bound delegated approval, execute it, read back the posted transaction, then finish. Approval grants permission; it does not validate commercial correctness.',
        max_tool_calls=task['max_tool_calls'],horizon_minutes=task['horizon_minutes'])


def run(task,agent,checkpoint=None):
    world=SupplyChainWorld(task);view=SupplyView(task);last=None;agent_trace=[];status='budget_exhausted';error=None
    try:
        while not world.finished and len(world.trace)<task['max_tool_calls'] and world.clock<=task['horizon_minutes']:
            payload=dict(clock_minute=world.clock,calls_remaining=task['max_tool_calls']-len(world.trace),last_result=last)
            if not world.trace:payload.update(task=public_task(task,view.episode_id),tools=deepcopy(TOOLS))
            decision=agent.decide('supply_chain',payload)
            if not isinstance(decision,dict) or set(decision)!={'tool','arguments'} or not isinstance(decision['tool'],str) or not isinstance(decision['arguments'],dict):raise ValueError('invalid_decision')
            result=world.call(decision['tool'],**view.decode(decision['arguments']));last=view.encode(result)
            agent_trace.append(dict(decision=deepcopy(decision),result=deepcopy(last)))
            if checkpoint:checkpoint(dict(evaluator_task_id=task['id'],result=world.grade(),trace=deepcopy(world.trace),agent_trace=deepcopy(agent_trace),status='running'))
        if world.finished:status='finished'
    except (ValueError,OSError) as exc:status='stopped';error=type(exc).__name__
    episode=dict(evaluator_task_id=task['id'],result=world.grade(),trace=deepcopy(world.trace),agent_trace=agent_trace,status=status)
    if error:episode['error_type']=error
    if checkpoint:checkpoint(episode)
    return episode


def replay(task,trace):
    world=SupplyChainWorld(task)
    for i,row in enumerate(trace):
        world.call(row['tool'],**row['arguments'])
        if not world.trace or world.trace[-1]!=row:raise ValueError(f'supply-chain replay mismatch at {i}')
    return world.grade()
