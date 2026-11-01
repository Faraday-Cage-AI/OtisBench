"""Selected public-record invoice controls plus replay and policy/business mutants.

Requires retained development episodes; never runs a learned model or contacts a provider.
"""
from pathlib import Path
import json
from erp_invoice_runner import ROOT,run,replay,sources,base,protocol

CASES={
 '2008_easy_02_buy_only_immediate_invoicing':'2008-attempt05.json',
 '2016_easy_03_buy_only_fixed_downpayment':'2016-attempt02.json',
 '2024_easy_04_buy_only_percentage_downpayment':'2024-attempt02.json',
}


def main():
    out=ROOT/'runs/invoice-extension';agent=ROOT/'examples/erp_invoice_agent.py';rows=[]
    for task,filename in CASES.items():
        path=out/filename
        if not path.is_file():raise ValueError('required completed development episode missing: '+filename)
        episode=json.loads(path.read_text())
        if episode['source_task']!=task or episode['source_sha256']!=sources() or episode['agent_sha256']!=base.sha(agent) or episode['agent_isolation']['agent_sha256']!=episode['agent_sha256']:raise ValueError('public control source/agent commitment mismatch')
        if not episode['result']['adapter_passed']:raise ValueError('public control is not a complete passing result: '+task)
        checked=replay(episode,out/(task+'-replay'))
        rows.append(dict(task=task,episode=str(path.relative_to(ROOT)),episode_sha256=base.sha(path),result=episode['result'],replay=checked,
                         linked_sales=len(episode['linked_sales_invoices']),posted_invoices=len(episode['posted_customer_invoices'])))
        print(task,'public control and exact replay passed',flush=True)
    prefix=agent.read_text().split("if __name__=='__main__':")[0];policies=out/'negative-policies';policies.mkdir(exist_ok=True)
    wrong=policies/'wrong-downpayment.py';wrong.write_text(prefix+'''agent=Buyer()
for line in sys.stdin:
    message=json.loads(line);decision=agent.decide(message['track'],message['payload'])
    if decision.get('tool')=='rpc' and decision['arguments']['model']=='sale.advance.payment.inv' and decision['arguments']['method']=='create':
        row=decision['arguments']['kwargs']['vals_list'][0]
        if row['advance_payment_method']=='fixed':row['fixed_amount']+=1
    print(json.dumps(decision),flush=True)
''')
    unsafe=policies/'context-override.py';unsafe.write_text(prefix+'''agent=Buyer();pending=False;active=None
for line in sys.stdin:
    message=json.loads(line)
    if pending:decision=dict(tool='finish',arguments={})
    else:
        decision=agent.decide(message['track'],message['payload'])
        if decision.get('tool')=='rpc' and decision['arguments']['model']=='sale.advance.payment.inv':active=decision['arguments']['kwargs'].get('context',active)
        if decision['tool']=='finish':
            decision=dict(tool='rpc',arguments=dict(model='sale.advance.payment.inv',method='create',kwargs=dict(vals_list=[dict(advance_payment_method='delivered')],context=dict(active,allowed_company_ids=[1]))));pending=True
    print(json.dumps(decision),flush=True)
''')
    controls={}
    for name,policy,task in [('wrong_downpayment',wrong,'2016_easy_03_buy_only_fixed_downpayment'),('forbidden_context',unsafe,'2008_easy_02_buy_only_immediate_invoicing')]:
        path=out/(name+'-control.json')
        episode=json.loads(path.read_text()) if path.exists() else run(ROOT/'runs/erp-catalog-v1/baselines'/task,policy,path)
        if episode['source_sha256']!=sources() or episode['agent_sha256']!=base.sha(policy):raise ValueError('negative-control source changed')
        exercised=True
        if name=='wrong_downpayment':
            exercised=episode['status']=='finished' and any(row['decision'].get('arguments',{}).get('model')=='sale.advance.payment.inv' and row['decision']['arguments']['method']=='create' and row['decision']['arguments']['kwargs']['vals_list'][0].get('fixed_amount')==251 and row['result'].get('ok') for row in episode['trace']) and any(abs(row['amount_untaxed']-251)<.001 for row in episode['posted_customer_invoices'])
        controls[name]=dict(episode=str(path.relative_to(ROOT)),episode_sha256=base.sha(path),result=episode['result'],critical=episode['critical_violations'],status=episode['status'],exercised=exercised)
        print(name,episode['result']['upstream_score'],episode['result']['adapter_passed'],flush=True)
    passed=all(row['result']['adapter_passed'] and all(row['replay'][key] for key in ('exact_responses','exact_business_state','exact_verifier')) for row in rows)
    passed=passed and controls['wrong_downpayment']['exercised'] and not controls['wrong_downpayment']['result']['upstream_passed'] and not controls['wrong_downpayment']['critical']
    passed=passed and controls['forbidden_context']['result']['upstream_passed'] and not controls['forbidden_context']['result']['adapter_passed'] and controls['forbidden_context']['result']['adapter_score']==0 and bool(controls['forbidden_context']['critical'])
    history=[]
    for path in sorted(out.glob('*-attempt*.json')):
        e=json.loads(path.read_text());history.append(dict(episode=str(path.relative_to(ROOT)),sha256=base.sha(path),status=e['status'],score=e['result']['upstream_score'],passed=e['result']['adapter_passed']))
    report=dict(qualification_passed=passed,protocol=protocol.VERSION,selected_upstream_cases=3,native_case_count_added=0,
        source_sha256=sources()|{str(Path(__file__).relative_to(ROOT)):base.sha(__file__),str(agent.relative_to(ROOT)):base.sha(agent)},
        cases=rows,controls=controls,retained_development_attempts=history,
        limitations=['Hand-coded control developed on public prompts/records and diagnostic feedback, not a learned-model or held-out result.',
            'Three easy purchasing/invoice patterns only; no claim of full-catalog public-agent solvability.',
            'Uses validated version-1 nonrepair fixtures under the documented version-2 restoration recipe; private repair metadata is never supplied to the agent.',
            'Invoice posting is actual local synthetic Odoo accounting, not customer fulfillment, payment collection or bank execution.',
            'Exact replay remains clock-dependent; no date normalization or full clock virtualization.'])
    base.save(ROOT/'reports/erp-invoice-qualification.json',report)
    print(json.dumps(dict(qualification_passed=passed,selected_public_invoice_cases=3)));return 0 if passed else 1


if __name__=='__main__':raise SystemExit(main())
