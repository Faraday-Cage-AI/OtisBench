"""Versioned public invoice gateway over immutable version-1 ERP fixtures.

Does not modify the frozen adapter, snapshots or running catalog campaign.
"""
from contextlib import contextmanager
from copy import deepcopy
import argparse
import json
from pathlib import Path
import shlex
from faraday_manufacturing_benchmark import erp_compat as base
from faraday_manufacturing_benchmark.agents import DecisionAgent
from faraday_manufacturing_benchmark.isolation import isolated_agent
import erp_invoice_protocol as protocol

ROOT=Path(__file__).resolve().parents[1]
PROTOCOL_FILE=Path(protocol.__file__).resolve()


def sources():
    paths=[Path(__file__),PROTOCOL_FILE]+[ROOT/'src/faraday_manufacturing_benchmark'/name for name in ('erp_compat.py','erp_protocol.py','agents.py','isolation.py')]
    return {str(path.relative_to(ROOT)):base.sha(path) for path in paths}


@contextmanager
def restored(snapshot):
    with base.restored(snapshot) as (container,legacy,manifest):
        # A separate worker file/connection keeps the version-1 fixture boundary intact.
        container.copy_in(PROTOCOL_FILE,'/bridge/invoice-gateway.py')
        command=shlex.join(['docker','exec','-i',container.cid,'python3','/bridge/invoice-gateway.py'])
        with DecisionAgent(command,timeout=40,max_reply_bytes=1100000) as bridge:
            before=base.probe(bridge)
            if base.digest(before)!=manifest['baseline_state_digest']:raise ValueError('invoice extension changed initial business projection')
            yield container,bridge,manifest


def probe(bridge):
    result={}
    for model,(readable,_,_) in protocol.SPECS.items():
        if model=='sale.advance.payment.inv':continue # Transient wizard IDs are transport state, not ledger outcomes.
        metadata=bridge.decide('invoice_gateway',dict(model=model,method='fields_get',kwargs={}))
        if not metadata['ok']:raise ValueError('business fields unavailable: '+model)
        selected=sorted(set(metadata['value'])&set(readable.split()));rows=[];offset=0
        while True:
            reply=bridge.decide('invoice_gateway',dict(model=model,method='search_read',kwargs=dict(domain=[],fields=selected,limit=200,offset=offset)))
            if not reply['ok']:raise ValueError('business projection unavailable: '+model)
            rows.extend(reply['value'])
            if len(reply['value'])<200:break
            offset+=200
            if offset>10000:raise ValueError('business projection row limit')
        result[model]=rows
    return result


def run(snapshot,agent_file,output,timeout=120):
    output=Path(output)
    if output.exists():raise ValueError('episode already exists; retain each development attempt under a new filename')
    frozen_sources=sources()
    snapshot=Path(snapshot).resolve();trace=[];critical=[];finished=False;error=None;isolation=None
    with restored(snapshot) as (container,bridge,manifest):
        goal=(Path(manifest['case_dir'])/'instruction.md').read_text().split('# Odoo Environment')[0].strip()
        public_task=dict(id='erp-linked-invoice-task',goal=goal,anchor_date=manifest['anchor_date'])
        before=probe(bridge)
        try:
            with isolated_agent(agent_file,timeout) as agent:
                isolation=agent.isolation;last=None
                for _ in range(300):
                    payload=dict(last_result=last,calls_remaining=300-len(trace))
                    if not trace:payload.update(task=public_task,tools=protocol.contract())
                    reply=agent.decide('erp_invoice',payload)
                    if reply==dict(tool='finish',arguments={}):
                        trace.append(dict(decision=reply,result=dict(ok=True,finished=True)));finished=True;break
                    if set(reply)!={'tool','arguments'} or reply['tool']!='rpc':raise ValueError('expected rpc or finish')
                    try:
                        protocol.validate(reply['arguments']);last=bridge.decide('invoice_gateway',reply['arguments'])
                    except protocol.PolicyDenied as exc:critical.append(str(exc));last=dict(ok=False,error='policy_denied')
                    except (ValueError,TypeError,KeyError):last=dict(ok=False,error='invalid_rpc')
                    trace.append(dict(decision=deepcopy(reply),result=deepcopy(last)))
        except (ValueError,OSError) as exc:error=type(exc).__name__
        final=probe(bridge)
        # Agent process is closed before any verifier files are staged.
        result=base.grade(container,manifest['case_dir'],output.parent/(output.stem+'-evidence'))
        result.update(adapter_passed=finished and not critical and result['upstream_passed'],adapter_score=0.0 if critical else result['upstream_score'])
        linked=[dict(id=row['id'],name=row['name'],invoice_ids=row.get('invoice_ids',[])) for row in final['sale.order'] if row.get('invoice_ids')]
        episode=dict(track='erp-public-invoice-extension',protocol=protocol.VERSION,fixture_protocol=manifest['protocol'],
            source_sha256=frozen_sources,snapshot_path=str(snapshot),snapshot_manifest_sha256=base.sha(snapshot/'manifest.json'),
            source_task=manifest['upstream']['task_id'],upstream_revision=base.REVISION,
            public_task_sha256=base.digest(public_task),contract_sha256=base.digest(protocol.contract()),
            agent_sha256=base.sha(agent_file),agent_isolation=isolation,
            status='stopped' if error else 'finished' if finished else 'budget_exhausted',error_type=error,critical_violations=critical,
            trace=trace,initial_business_digest=base.digest(before),final_business_digest=base.digest(final),
            result=result,linked_sales_invoices=linked,
            posted_customer_invoices=[row for row in final['account.move'] if row['move_type']=='out_invoice' and row['state']=='posted'],
            scope='Hand-coded public prompt/record control under a separate invoice gateway; not a learned model, full-catalog public agent or native case count.')
        if frozen_sources!=sources():raise ValueError('invoice implementation changed during execution')
        base.save(output,episode);return episode


def replay(episode,output):
    episode=deepcopy(episode);output=Path(output)
    if episode['protocol']!=protocol.VERSION or episode['source_sha256']!=sources():raise ValueError('invoice episode source/protocol changed')
    snapshot=Path(episode['snapshot_path'])
    if base.sha(snapshot/'manifest.json')!=episode['snapshot_manifest_sha256']:raise ValueError('snapshot changed')
    observed=[];finished=False;critical=[]
    with restored(snapshot) as (container,bridge,manifest):
        before=probe(bridge)
        if base.digest(before)!=episode['initial_business_digest']:raise ValueError('invoice baseline projection changed')
        for row in episode['trace']:
            decision=row['decision']
            if decision==dict(tool='finish',arguments={}):result=dict(ok=True,finished=True);finished=True
            else:
                try:protocol.validate(decision['arguments']);result=bridge.decide('invoice_gateway',decision['arguments'])
                except protocol.PolicyDenied as exc:critical.append(str(exc));result=dict(ok=False,error='policy_denied')
                except (ValueError,TypeError,KeyError):result=dict(ok=False,error='invalid_rpc')
            if result!=row['result']:raise ValueError('invoice RPC replay mismatch')
            observed.append(result)
        final=probe(bridge)
        if base.digest(final)!=episode['final_business_digest']:raise ValueError('invoice final business projection mismatch')
        result=base.grade(container,manifest['case_dir'],output)
        result.update(adapter_passed=finished and not critical and result['upstream_passed'],adapter_score=0.0 if critical else result['upstream_score'])
        if result!=episode['result']:raise ValueError('invoice verifier replay mismatch')
    return dict(exact_responses=True,exact_business_state=True,exact_verifier=True,calls=len(observed))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    execute=sub.add_parser('run');execute.add_argument('--snapshot',required=True);execute.add_argument('--agent-file',default='examples/erp_invoice_agent.py');execute.add_argument('--output',required=True)
    regrade=sub.add_parser('replay');regrade.add_argument('--episode',required=True);regrade.add_argument('--output',required=True)
    args=p.parse_args()
    if args.command=='run':
        r=run(args.snapshot,args.agent_file,args.output);print(json.dumps(dict(task=r['source_task'],status=r['status'],upstream_score=r['result']['upstream_score'],upstream_passed=r['result']['upstream_passed'],adapter_passed=r['result']['adapter_passed'],linked_sales=len(r['linked_sales_invoices']),posted_invoices=len(r['posted_customer_invoices']))))
    else:print(json.dumps(replay(json.loads(Path(args.episode).read_text()),args.output)))
