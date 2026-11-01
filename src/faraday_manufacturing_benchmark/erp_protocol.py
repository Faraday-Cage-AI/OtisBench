"""Public constrained JSON-2 contract. No task truths or grader data."""
from copy import deepcopy
import json
import math

VERSION='odoo-json2-business/1'
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


def validate(request):
    if not isinstance(request,dict) or set(request)!={'model','method','kwargs'}:raise ValueError('rpc requires model, method and kwargs')
    model=request['model'];method=request['method'];kw=request['kwargs']
    if model not in SPECS:raise PolicyDenied('model outside business allowlist')
    if not isinstance(kw,dict):raise ValueError('kwargs must be an object')
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
    return dict(protocol=VERSION,max_calls=300,models={model:dict(readable_fields=r.split(),writable_fields=w.split(),actions=list(a),methods=['fields_get','search_read','read']+(['create','write'] if w else [])) for model,(r,w,a) in SPECS.items()},limits='Queries return at most 200 records; no credentials, configuration, server actions, arbitrary code, mail or attachment endpoints. Relations use only declared business models.')


def worker():
    import sys
    import urllib.request,urllib.error
    key=open('/etc/odoo/api_key').read().strip()
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for line in sys.stdin:
        try:
            request=json.loads(line)['payload'];kwargs=validate(request)
            req=urllib.request.Request('http://127.0.0.1:8069/json/2/'+request['model']+'/'+request['method'],data=json.dumps(kwargs,allow_nan=False).encode(),headers={'Content-Type':'application/json','Authorization':'bearer '+key,'X-Odoo-Database':'bench','User-Agent':'Faraday-ERP-compat/1'})
            try:
                with opener.open(req,timeout=30) as response:result=dict(ok=True,value=json.loads(response.read(1_000_001)))
            except urllib.error.HTTPError as exc:
                body=json.loads(exc.read(100000));result=dict(ok=False,error='odoo_rejected',error_type=body.get('name','RPCError'),message=str(body.get('message','Operation rejected'))[:1000])
        except PolicyDenied as exc:result=dict(ok=False,error='policy_denied',message=str(exc))
        except (ValueError,TypeError,KeyError,OSError) as exc:result=dict(ok=False,error='invalid_rpc',error_type=type(exc).__name__)
        print(json.dumps(result,allow_nan=False),flush=True)

if __name__=='__main__':worker()
