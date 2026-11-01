"""Regression for the observed stock/PO-origin scheduling interaction."""
import importlib.util
import pytest
from pathlib import Path

spec=importlib.util.spec_from_file_location('invoice_agent',Path(__file__).resolve().parents[1]/'examples/erp_invoice_agent.py')
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)


@pytest.mark.parametrize('late_moq',[1,8])
@pytest.mark.parametrize('singular',[False,True])
def test_po_origins_have_enough_demand_and_feasible_dates(late_moq,singular):
    goal='''All orders below for Test Widget need confirmed supply coverage and scheduling.
- Early Customer: 2 units due in 2 days (pretax budget cap $100)
- Later Customer: 6 units due in 5 days (pretax budget cap $300)
Across new purchasing keep margin at or above 30%. Use Immediate Payment terms on retained sales orders and all linked customer invoices.
Link Sales Orders to the related Purchase Orders for traceability. In the end the lineage must be SO -> PO.'''
    if singular:goal=goal.replace('2 units due','1 unit due').replace('6 units due','7 units due')
    agent=a.Buyer();payload=dict(task=dict(goal=goal,anchor_date='2026-11-01'));orders=[]
    for _ in range(40):
        decision=agent.decide('erp_invoice',payload);args=decision['arguments'];model,method,kw=args['model'],args['method'],args['kwargs']
        if model=='purchase.order' and method=='create':
            row=kw['vals_list'][0];line=row['order_line'][0][2]
            assert row['partner_id']==(52 if late_moq==1 else 51)
            assert line['product_qty']==3
            assert len(orders)==2
            demand={'S001':(1 if singular else 2,'2026-11-03 00:00:00'),'S002':(7 if singular else 6,'2026-11-06 00:00:00')}
            origins=set(row['origin'].split(', '))
            assert origins and line['product_qty']<=sum(demand[name][0] for name in origins)
            assert all(line['date_planned']<=demand[name][1] for name in origins)
            return
        if model=='product.product':value=[dict(id=1,name='Test Widget',default_code='P1',product_tmpl_id=[15,'Widget'],qty_available=5,list_price=30,description='Synthetic test stock')]
        elif model=='account.payment.term':value=[dict(id=1,name='Immediate Payment',note='Pay now')]
        elif model=='product.supplierinfo':value=[dict(id=31,partner_id=[51,'Early Vendor'],min_qty=1,price=12,delay=2),dict(id=32,partner_id=[52,'Late Vendor'],min_qty=late_moq,price=10,delay=4)]
        elif model=='res.partner':
            if kw['domain'][0][0]=='name':value=[dict(id=5,name='Early Customer',ref='C1',comment='Synthetic customer'),dict(id=6,name='Later Customer',ref='C2',comment='Synthetic customer')]
            else:value=[dict(id=51,name='Early Vendor',ref='V1',comment='Maximum order quantity for P1: 20 units'),dict(id=52,name='Late Vendor',ref='V2',comment='Maximum order quantity for P1: 20 units')]
        elif model=='sale.order' and method=='create':
            identity=100+len(orders);orders.append(dict(id=identity,name='S00'+str(len(orders)+1),state='sale'));value=[identity]
        elif model=='sale.order' and method=='action_confirm':value=True
        elif model=='sale.order' and method=='read':value=orders
        else:raise AssertionError((model,method))
        payload=dict(last_result=dict(ok=True,value=value))
    raise AssertionError('baseline never proposed a purchase order')
