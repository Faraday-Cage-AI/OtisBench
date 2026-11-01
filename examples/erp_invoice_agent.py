"""Public Odoo-record invoicing control for three disclosed easy purchasing patterns.

Uses public prompt/records only. Not a learned model or a general ERP planner.
"""
from datetime import datetime,timedelta
import json
import math
import re
import sys
from decimal import Decimal


class Buyer:
    def __init__(self):self.plan=None
    def decide(self,track,payload):
        if self.plan is None:self.plan=self.actions(payload['task']);return next(self.plan)
        last=payload['last_result']
        if not last['ok']:raise ValueError('business RPC rejected: '+str(last))
        return self.plan.send(last)
    def actions(self,task):
        def rpc(model,method,**kwargs):return (yield dict(tool='rpc',arguments=dict(model=model,method=method,kwargs=kwargs)))
        def search(model,domain,fields):
            rows=[];offset=0
            while True:
                reply=yield from rpc(model,'search_read',domain=domain,fields=fields,limit=200,offset=offset);rows.extend(reply['value'])
                if len(reply['value'])<200:return rows
                offset+=200
        goal=task['goal'];match=re.search(r'fulfill each outstanding (.*?) customer order listed',goal) or re.search(r'orders below for (.*?) need confirmed supply',goal) or re.search(r'customer orders for (.*?) require confirmed supply',goal)
        if not match:raise ValueError('example supports the simple outstanding-order prompt only')
        product=(yield from search('product.product',[['name','=',match.group(1)]],['id','name','default_code','product_tmpl_id','qty_available','list_price','description']))[0]
        demands=[(name,int(n),int(days),float(cap.replace(',',''))) for name,n,days,cap in re.findall(r'- ([^\n:]+): (\d+) units? due in (\d+) days \(pretax budget cap \$([\d,]+)\)',goal)]
        term_match=re.search(r'Use (.*?) terms on retained sales orders',goal)
        if not term_match:raise ValueError('public invoice payment-term policy required')
        terms=yield from search('account.payment.term',[['name','=',term_match.group(1)]],['id','name','note'])
        if len(terms)!=1:raise ValueError('unique public payment term required')
        payment_term=terms[0]['id']
        customers=yield from search('res.partner',[['name','in',[r[0] for r in demands]]],['id','name','ref','comment'])
        customers={r['name']:r for r in customers};offers=yield from search('product.supplierinfo',[['product_tmpl_id','=',product['product_tmpl_id'][0]]],['id','partner_id','min_qty','price','delay'])
        vendors=yield from search('res.partner',[['id','in',[o['partner_id'][0] for o in offers]]],['id','name','ref','comment']);vendors={v['id']:v for v in vendors}
        total=sum(n for _,n,_,_ in demands);short=max(0,total-product['qty_available']);margin=re.search(r'at or above ([\d.]+)%',goal);minimum=float(margin.group(1))/100 if margin else 0
        choices=[]
        for offer in offers:
            note=vendors[offer['partner_id'][0]]['comment'] or '';cap=re.search(r'Maximum order quantity for '+re.escape(product['default_code'])+r': ([\d.]+) units',note)
            if not cap:continue
            quantity=max(math.ceil(short),math.ceil(offer['min_qty']))
            eligible={name for name,n,days,cap in demands if days>=offer['delay']}
            eligible_units=sum(n for name,n,days,cap in demands if name in eligible)
            early_units=sum(n for name,n,days,cap in demands if days<offer['delay'])
            if quantity<=float(cap.group(1)) and quantity<=eligible_units and early_units<=product['qty_available'] and offer['price']<=product['list_price']*(1-minimum):choices.append((quantity*offer['price'],offer['id'],quantity,offer,eligible))
        if short and not choices:raise ValueError('example found no single feasible supplier')
        when=lambda days:(datetime.fromisoformat(task['anchor_date'])+timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
        order_ids=[];sale_customer={}
        for name,n,days,cap in demands:
            customer=customers[name]
            if product['list_price']*n>cap:raise ValueError('example cannot accept an over-budget customer')
            reply=yield from rpc('sale.order','create',vals_list=[dict(partner_id=customer['id'],payment_term_id=payment_term,client_order_ref=customer['ref'],date_order=when(0),commitment_date=when(days),order_line=[[0,0,dict(product_id=product['id'],product_uom_qty=n,price_unit=product['list_price'])]])]);oid=reply['value'][0];order_ids.append(oid);sale_customer[oid]=name
            yield from rpc('sale.order','action_confirm',ids=[oid])
        sales=yield from rpc('sale.order','read',ids=order_ids,fields=['id','name','state'])
        if short:
            _,_,quantity,offer,eligible=min(choices,key=lambda r:(r[0],r[1]));origin=', '.join(row['name'] for row in sales['value'] if sale_customer[row['id']] in eligible)
            po=yield from rpc('purchase.order','create',vals_list=[dict(partner_id=offer['partner_id'][0],origin=origin,date_order=when(0),order_line=[[0,0,dict(product_id=product['id'],product_qty=quantity,price_unit=offer['price'],date_planned=when(offer['delay']))]])]);pid=po['value'][0]
            yield from rpc('purchase.order','button_confirm',ids=[pid])
            yield from rpc('purchase.order','read',ids=[pid],fields=['id','name','state','origin','amount_untaxed'])
        deposit=re.search(r'untaxed totals of \$([\d,.]+) or more, first create and post a down payment invoice for (\$[\d,.]+|[\d.]+%)',goal)
        async_orders=yield from rpc('sale.order','read',ids=order_ids,fields=['id','name','amount_untaxed','payment_term_id','invoice_ids'])
        for order in async_orders['value']:
            if order['payment_term_id'][0]!=payment_term:raise ValueError('sales payment-term readback mismatch')
            methods=[]
            if deposit and Decimal(str(order['amount_untaxed']))>=Decimal(deposit.group(1).replace(',','')):
                value=deposit.group(2)
                methods.append(dict(advance_payment_method='fixed',fixed_amount=float(Decimal(value[1:].replace(',','')))) if value.startswith('$') else dict(advance_payment_method='percentage',amount=float(Decimal(value[:-1]))))
            methods.append(dict(advance_payment_method='delivered'))
            for values in methods:
                current=yield from rpc('sale.order','read',ids=[order['id']],fields=['id','invoice_ids']);before=set(current['value'][0]['invoice_ids'])
                context=dict(active_model='sale.order',active_ids=[order['id']])
                created=yield from rpc('sale.advance.payment.inv','create',vals_list=[values],context=context)
                if not isinstance(created['value'],list) or len(created['value'])!=1:raise ValueError('one wizard ID expected')
                yield from rpc('sale.advance.payment.inv','create_invoices',ids=created['value'],context=context)
                current=yield from rpc('sale.order','read',ids=[order['id']],fields=['id','invoice_ids']);new=set(current['value'][0]['invoice_ids'])-before
                if len(new)!=1:raise ValueError('exactly one new linked invoice required')
                iid=next(iter(new))
                invoice=yield from rpc('account.move','read',ids=[iid],fields=['id','state','invoice_payment_term_id','amount_untaxed','amount_total'])
                if invoice['value'][0]['invoice_payment_term_id'][0]!=payment_term:
                    yield from rpc('account.move','write',ids=[iid],vals=dict(invoice_payment_term_id=payment_term))
                if invoice['value'][0]['state']!='posted':yield from rpc('account.move','action_post',ids=[iid])
                invoice=yield from rpc('account.move','read',ids=[iid],fields=['id','name','state','invoice_origin','invoice_payment_term_id','amount_untaxed','amount_total'])
                if invoice['value'][0]['state']!='posted':raise ValueError('invoice posting readback failed')
        yield dict(tool='finish',arguments={})


if __name__=='__main__':
    agent=Buyer()
    for line in sys.stdin:
        message=json.loads(line);print(json.dumps(agent.decide(message['track'],message['payload'])),flush=True)
