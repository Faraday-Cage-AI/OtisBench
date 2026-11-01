"""Versioned invoice extension of the frozen business gateway.

Adds bounded sales-invoice wizard operations; no credentials or grader data.
The original version-1 source and live catalog campaign remain unchanged.
"""
from copy import deepcopy
import json
import math

VERSION='odoo-json2-business/2-invoices'
# Only business records are reachable. Identity, configuration, server actions,
# arbitrary Python, attachments and mail operations are deliberately excluded.
SPECS={
 'res.partner':('id name ref comment active is_company customer_rank supplier_rank','',()),
 'product.product':('id name default_code description description_sale description_purchase list_price qty_available product_tmpl_id uom_id type','',()),
 'product.supplierinfo':('id partner_id product_id product_tmpl_id min_qty price delay currency_id date_start date_end','',()),
 'sale.order':('id name partner_id state client_order_ref commitment_date note origin payment_term_id order_line amount_untaxed amount_total','partner_id client_order_ref commitment_date date_order note origin payment_term_id order_line',('action_confirm','action_cancel')),
 'sale.order.line':('id order_id product_id product_uom_qty price_unit discount name','order_id product_id product_uom_qty price_unit discount name tax_ids',()),
 'purchase.order':('id name partner_id state origin order_line amount_untaxed amount_total','partner_id origin date_order order_line',('button_confirm','button_cancel')),
 'purchase.order.line':('id order_id product_id product_qty price_unit date_planned product_uom_id product_uom name','order_id product_id product_qty price_unit date_planned product_uom_id product_uom name taxes_id',()),
 'account.payment.term':('id name note','',()),
 'account.tax':('id name amount type_tax_use','',()),
 'mrp.bom':('id product_id product_tmpl_id product_qty product_uom_id bom_line_ids operation_ids type','',()),
 'mrp.bom.line':('id bom_id product_id product_qty product_uom_id','',()),
 'mrp.routing.workcenter':('id name bom_id workcenter_id time_cycle_manual time_mode','',()),
 'mrp.workcenter':('id name code capacity costs_hour time_efficiency resource_calendar_id','',()),
 'mrp.production':('id name state product_id product_qty product_uom_id bom_id date_start date_finished origin workorder_ids','product_id product_qty product_uom_id bom_id date_start date_finished origin',('action_confirm','action_assign','button_plan','button_unplan','button_mark_done','action_cancel')),
 'mrp.workorder':('id name state production_id workcenter_id date_start date_finished duration_expected','workcenter_id date_start date_finished',()),
 'stock.location':('id name complete_name usage','',()),
 'stock.quant':('id product_id location_id quantity reserved_quantity','',()),
 'stock.picking':('id name state origin picking_type_id scheduled_date date_deadline partner_id','scheduled_date date_deadline',('action_confirm','action_assign','button_validate')),
 'stock.move':('id name state product_id product_uom_qty quantity picking_id raw_material_production_id production_id date deadline','',()),
 'account.move':('id name state partner_id move_type invoice_origin invoice_date invoice_date_due amount_untaxed amount_total payment_state invoice_line_ids ref','partner_id move_type invoice_date invoice_date_due ref invoice_line_ids',('action_post','button_cancel')),
 'account.move.line':('id move_id product_id quantity price_unit name account_id','product_id quantity price_unit name account_id',()),
}
# Business invoice relationships are readable; the Odoo wizard creates links.
r,w,a=SPECS['sale.order'];SPECS['sale.order']=(r+' invoice_ids invoice_status',w,a)
r,w,a=SPECS['account.move'];SPECS['account.move']=(r+' invoice_payment_term_id',w+' invoice_payment_term_id',a)
r,w,a=SPECS['account.move.line'];SPECS['account.move.line']=(r+' display_type sale_line_ids',w,a)
SPECS['sale.advance.payment.inv']=('id advance_payment_method amount fixed_amount sale_order_ids','advance_payment_method amount fixed_amount',('create_invoices',))

RELATIONS={('sale.order','order_line'):'sale.order.line',('purchase.order','order_line'):'purchase.order.line',('sale.order.line','tax_ids'):'account.tax',('purchase.order.line','taxes_id'):'account.tax',('account.move','invoice_line_ids'):'account.move.line'}
OPERATORS={'=','!=','>','<','>=','<=','in','not in','like','ilike'}


class PolicyDenied(ValueError):pass


def ids(value):
    if not isinstance(value,list) or not value or len(value)>200 or any(type(i) is not int or i<=0 for i in value):raise ValueError('ids must be 1..200 positive integer IDs')


def values(model,record,depth=0):
    if depth>4 or not isinstance(record,dict) or not record:raise ValueError('invalid record values')
    allowed=set(SPECS[model][1].split())
    if set(record)-allowed:raise PolicyDenied('field not writable through gateway')
    for field,value in record.items():
        child=RELATIONS.get((model,field))
        if child:
            if not isinstance(value,list) or len(value)>200:raise ValueError('invalid relation commands')
            for command in value:
                if not isinstance(command,list) or len(command)!=3 or type(command[0]) is not int:raise ValueError('invalid relation command')
                op,target,data=command
                if op==0:
                    if target!=0:raise ValueError('invalid create command')
                    values(child,data,depth+1)
                elif op==1:
                    ids([target]);values(child,data,depth+1)
                elif op==6:
                    if target!=0:raise ValueError('invalid set command')
                    if data:ids(data)
                    elif data!=[]:raise ValueError('invalid relation IDs')
                elif op in (3,4):
                    ids([target])
                    if data!=0:raise ValueError('invalid link command')
                else:raise PolicyDenied('relation command not allowed')
        elif not isinstance(value,(str,int,float,bool,type(None))):raise ValueError('scalar field requires scalar JSON value')
        elif isinstance(value,float) and not math.isfinite(value):raise ValueError('nonfinite value')
        elif isinstance(value,str) and len(value)>10000:raise ValueError('oversized field')


def invoice_context(value):
    if not isinstance(value,dict) or set(value)!={'active_model','active_ids'} or value['active_model']!='sale.order':
        raise PolicyDenied('invoice context is limited to one sales order')
    ids(value['active_ids'])
    if len(value['active_ids'])!=1:raise ValueError('one active sales order required')
    return deepcopy(value)


def invoice_wizard(method,kw):
    if not isinstance(kw,dict):raise ValueError('kwargs must be an object')
    if method in ('create','create_invoices'):
        context=invoice_context(kw.get('context'))
        if method=='create':
            if set(kw)!={'vals_list','context'} or not isinstance(kw['vals_list'],list) or len(kw['vals_list'])!=1:raise ValueError('create one bounded invoice wizard')
            row=kw['vals_list'][0]
            if not isinstance(row,dict):raise ValueError('invalid invoice wizard values')
            mode=row.get('advance_payment_method')
            expected={'delivered':{'advance_payment_method'},'percentage':{'advance_payment_method','amount'},'fixed':{'advance_payment_method','fixed_amount'}}
            if not isinstance(mode,str) or mode not in expected or set(row)!=expected[mode]:raise PolicyDenied('invoice wizard fields/method outside declared modes')
            if mode!='delivered':
                value=row['amount' if mode=='percentage' else 'fixed_amount']
                if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=(100 if mode=='percentage' else 10**12):raise ValueError('invalid down payment amount')
        else:
            if set(kw)!={'ids','context'}:raise PolicyDenied('invoice action accepts wizard ID and bounded order context only')
            ids(kw['ids'])
            if len(kw['ids'])!=1:raise ValueError('one invoice wizard required')
        return deepcopy(kw)
    if method not in ('fields_get','read'):raise PolicyDenied('invoice wizard exposes fields_get, read, create and create_invoices only')
    return None


def validate(request):
    if not isinstance(request,dict) or set(request)!={'model','method','kwargs'}:raise ValueError('rpc requires model, method and kwargs')
    model=request['model'];method=request['method'];kw=request['kwargs']
    if model not in SPECS:raise PolicyDenied('model outside business allowlist')
    if not isinstance(kw,dict):raise ValueError('kwargs must be an object')
    if model=='sale.advance.payment.inv':
        special=invoice_wizard(method,kw)
        if special is not None:return special
    readable=set(SPECS[model][0].split())
    if method=='fields_get':
        if kw:raise ValueError('fields_get accepts no caller kwargs')
        return dict(allfields=sorted(readable|set(SPECS[model][1].split())),attributes=['string','type','relation'])
    if method in ('search_read','read'):
        if set(kw)-({'domain','fields','limit','offset'} if method=='search_read' else {'ids','fields'}):raise PolicyDenied('unexpected query parameters')
        if not isinstance(kw.get('fields'),list) or not kw['fields'] or len(kw['fields'])>60 or set(kw['fields'])-readable:raise PolicyDenied('field outside readable schema')
        if method=='read':ids(kw.get('ids'));return deepcopy(kw)
        domain=kw.get('domain',[])
        if not isinstance(domain,list) or len(domain)>100:raise ValueError('invalid search domain')
        for term in domain:
            if term in ('&','|','!'):continue
            if not isinstance(term,list) or len(term)!=3 or term[0] not in readable or term[1] not in OPERATORS:raise PolicyDenied('domain field/operator outside readable schema')
            if isinstance(term[2],dict) or (isinstance(term[2],list) and any(isinstance(x,(dict,list)) for x in term[2])):raise ValueError('nested domain values not allowed')
        limit=kw.get('limit',100);offset=kw.get('offset',0)
        if type(limit) is not int or not 1<=limit<=200 or type(offset) is not int or not 0<=offset<=10000:raise ValueError('invalid query bounds')
        return dict(domain=deepcopy(domain),fields=kw['fields'],limit=limit,offset=offset,order='id asc')
    if method=='create':
        if set(kw)!={'vals_list'} or not isinstance(kw['vals_list'],list) or not 1<=len(kw['vals_list'])<=100:raise ValueError('create requires bounded vals_list')
        for row in kw['vals_list']:values(model,row)
    elif method=='write':
        if set(kw)!={'ids','vals'}:raise ValueError('write requires ids and vals')
        ids(kw['ids']);values(model,kw['vals'])
    elif method in SPECS[model][2]:
        if set(kw)!={'ids'}:raise ValueError('business action accepts ids only')
        ids(kw['ids'])
    else:raise PolicyDenied('method outside business allowlist')
    return deepcopy(kw)


def contract():
    result=dict(protocol=VERSION,max_calls=300,models={model:dict(readable_fields=r.split(),writable_fields=w.split(),actions=list(a),methods=['fields_get','search_read','read']+(['create','write'] if w else [])) for model,(r,w,a) in SPECS.items()},limits='Queries return at most 200 records; no credentials, configuration, server actions, arbitrary code, mail or attachment endpoints. Relations use only declared business models.')
    result['models']['sale.advance.payment.inv'].update(methods=['fields_get','read','create'],actions=['create_invoices'],
        context={'active_model':'sale.order','active_ids':'exactly one positive sales order ID'},
        create_modes={'delivered':{},'percentage':{'amount':'0..100'},'fixed':{'fixed_amount':'0..1e12'}},
        limitation='Only the invoice wizard accepts context; no arbitrary defaults, company/user/language overrides or code.')
    return result


def worker():
    import sys
    import urllib.request,urllib.error
    key=open('/etc/odoo/api_key').read().strip()
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for line in sys.stdin:
        try:
            request=json.loads(line)['payload'];kwargs=validate(request)
            req=urllib.request.Request('http://127.0.0.1:8069/json/2/'+request['model']+'/'+request['method'],data=json.dumps(kwargs,allow_nan=False).encode(),headers={'Content-Type':'application/json','Authorization':'bearer '+key,'X-Odoo-Database':'bench','User-Agent':'Faraday-ERP-compat/2-invoices'})
            try:
                with opener.open(req,timeout=30) as response:result=dict(ok=True,value=json.loads(response.read(1_000_001)))
            except urllib.error.HTTPError as exc:
                body=json.loads(exc.read(100000));result=dict(ok=False,error='odoo_rejected',error_type=body.get('name','RPCError'),message=str(body.get('message','Operation rejected'))[:1000])
        except PolicyDenied as exc:result=dict(ok=False,error='policy_denied',message=str(exc))
        except (ValueError,TypeError,KeyError,OSError) as exc:result=dict(ok=False,error='invalid_rpc',error_type=type(exc).__name__)
        print(json.dumps(result,allow_nan=False),flush=True)

if __name__=='__main__':worker()
