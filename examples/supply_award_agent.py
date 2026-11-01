"""Public-record baseline for source_award only; no evaluator imports.
A fixed six-minute initial settling wait applies to every selected case.

Run with mfg-bench supply-chain --task supply-source_award-001 \
  --agent-command 'python examples/supply_award_agent.py' --output runs/award.json
"""
import json
import sys

systems=['ERP','SCM','WMS','QMS','AP','TMS']
phase='wait';index=0;facts={};proposal=None;approval=None;transaction=None
for line in sys.stdin:
    message=json.loads(line);payload=message['payload'];last=payload.get('last_result')
    if last and not last['ok']:raise RuntimeError(last['error'])
    if phase=='wait':
        decision=dict(tool='wait',arguments=dict(minutes=6));phase='read'
    elif phase=='read':
        if last and 'records' in last:facts.update(last['records']['facts'])
        if index<len(systems):
            decision=dict(tool='read',arguments=dict(system=systems[index]));index+=1
        else:
            n=facts['required_units']
            choices=[s for s in facts['suppliers'] if s['approved'] and not s['blocked'] and s['capacity_units']>=n and s['lead_days']<=facts['due_day']]
            best=min(choices,key=lambda s:(s['unit_cents'],s['id'])) if choices else None
            action=dict(supplier_id=best['id'] if best else None,units=n if best else 0,total_cents=n*best['unit_cents'] if best else None)
            decision=dict(tool='propose',arguments=dict(action=action));phase='approve'
    elif phase=='approve':
        proposal=last['proposal']['id'];decision=dict(tool='request_approval',arguments=dict(proposal_id=proposal));phase='execute'
    elif phase=='execute':
        approval=last['approval']['id'];decision=dict(tool='execute',arguments=dict(proposal_id=proposal,approval_id=approval));phase='readback'
    elif phase=='readback':
        transaction=last['transaction_id'];decision=dict(tool='read_back',arguments=dict(transaction_id=transaction));phase='finish'
    else:decision=dict(tool='finish',arguments=dict(transaction_id=transaction))
    print(json.dumps(decision),flush=True)
