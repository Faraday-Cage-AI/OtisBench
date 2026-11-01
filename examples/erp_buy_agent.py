"""Public Odoo-record control for a simple buy-only task, not a learned model.

No evaluator imports, files, credentials, scenario tables or reference plan.
"""
from datetime import datetime,timedelta
import json
import math
import re
import sys


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
        goal=task['goal'];match=re.search(r'fulfill each outstanding (.*?) customer order listed',goal)
        if not match:raise ValueError('example supports the simple outstanding-order prompt only')
        product=(yield from search('product.product',[['name','=',match.group(1)]],['id','name','default_code','product_tmpl_id','qty_available','list_price']))[0]
        demands=[(name,int(n),int(days),float(cap.replace(',',''))) for name,n,days,cap in re.findall(r'- ([^\n:]+): (\d+) units? due in (\d+) days \(pretax budget cap \$([\d,]+)\)',goal)]
        customers=yield from search('res.partner',[['name','in',[r[0] for r in demands]]],['id','name','ref','comment'])
        customers={r['name']:r for r in customers};offers=yield from search('product.supplierinfo',[['product_tmpl_id','=',product['product_tmpl_id'][0]]],['id','partner_id','min_qty','price','delay'])
        vendors=yield from search('res.partner',[['id','in',[o['partner_id'][0] for o in offers]]],['id','name','ref','comment']);vendors={v['id']:v for v in vendors}
        total=sum(n for _,n,_,_ in demands);short=max(0,total-product['qty_available']);margin=re.search(r'at or above ([\d.]+)%',goal);minimum=float(margin.group(1))/100 if margin else 0
        stock=product['qty_available'];first_uncovered=max(d for _,_,d,_ in demands)
        for _,n,d,_ in sorted(demands,key=lambda x:x[2]):
            if stock<n:first_uncovered=d;break
            stock-=n
        choices=[]
        for offer in offers:
            note=vendors[offer['partner_id'][0]]['comment'] or '';cap=re.search(r'Maximum order quantity for '+re.escape(product['default_code'])+r': ([\d.]+) units',note)
            if not cap:continue
            quantity=max(math.ceil(short),math.ceil(offer['min_qty']))
            if quantity<=float(cap.group(1)) and offer['delay']<=first_uncovered and offer['price']<=product['list_price']*(1-minimum):choices.append((quantity*offer['price'],offer['id'],quantity,offer))
        if short and not choices:raise ValueError('example found no single feasible supplier')
        when=lambda days:(datetime.fromisoformat(task['anchor_date'])+timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
        order_ids=[]
        for name,n,days,cap in demands:
            customer=customers[name]
            if product['list_price']*n>cap:raise ValueError('example cannot accept an over-budget customer')
            reply=yield from rpc('sale.order','create',vals_list=[dict(partner_id=customer['id'],client_order_ref=customer['ref'],date_order=when(0),commitment_date=when(days),order_line=[[0,0,dict(product_id=product['id'],product_uom_qty=n,price_unit=product['list_price'])]])]);oid=reply['value'][0];order_ids.append(oid)
            yield from rpc('sale.order','action_confirm',ids=[oid])
        sales=yield from rpc('sale.order','read',ids=order_ids,fields=['id','name','state'])
        if short:
            _,_,quantity,offer=min(choices,key=lambda r:(r[0],r[1]));origin=', '.join(row['name'] for row in sales['value'])
            po=yield from rpc('purchase.order','create',vals_list=[dict(partner_id=offer['partner_id'][0],origin=origin,date_order=when(0),order_line=[[0,0,dict(product_id=product['id'],product_qty=quantity,price_unit=offer['price'],date_planned=when(offer['delay']))]])]);pid=po['value'][0]
            yield from rpc('purchase.order','button_confirm',ids=[pid])
            yield from rpc('purchase.order','read',ids=[pid],fields=['id','name','state','origin','amount_untaxed'])
        yield dict(tool='finish',arguments={})


if __name__=='__main__':
    agent=Buyer()
    for line in sys.stdin:
        message=json.loads(line);print(json.dumps(agent.decide(message['track'],message['payload'])),flush=True)
