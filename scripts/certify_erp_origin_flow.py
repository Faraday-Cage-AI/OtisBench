"""Bounded MOQ traceability explanation of a retained ERP counterfactual."""
import argparse
import ast
from collections import defaultdict,deque
import json
import math
from pathlib import Path
from faraday_manufacturing_benchmark import erp_compat as erp
ROOT=Path(__file__).resolve().parents[1]


def checker_functions(path):
    names={'_scaled_qty','_origin_traceability_requirement','_traceability_capacity_feasible'}
    nodes=[n for n in ast.parse(Path(path).read_text()).body if isinstance(n,ast.FunctionDef) and n.name in names]
    if len(nodes)!=3:raise ValueError('pinned pure checker structure changed')
    namespace=dict(defaultdict=defaultdict,deque=deque)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),namespace)
    return namespace


def projection(state,code,checker):
    product=next(p for p in state['product.product'] if p['default_code']==code);boms={b['id']:b for b in state['mrp.bom']}
    unit=product['uom_id'][0];demand={}
    for mo in state['mrp.production']:
        if mo['state']!='confirmed':continue
        bom=boms[mo['bom_id'][0]];lines=[r for r in state['mrp.bom.line'] if r['bom_id'][0]==bom['id'] and r['product_id'][0]==product['id']]
        if not lines:continue
        if any(r['product_uom_id'][0]!=unit for r in lines):raise ValueError('UOM conversion outside bounded diagnosis')
        demand[mo['name']]=dict(qty=mo['product_qty']*sum(r['product_qty'] for r in lines)/bom['product_qty'])
    orders={p['id']:p for p in state['purchase.order']};supply=[]
    for line in state['purchase.order.line']:
        po=orders[line['order_id'][0]]
        if po['state']!='purchase' or line['product_id'][0]!=product['id']:continue
        if line['product_uom_id'][0]!=unit:raise ValueError('purchase UOM conversion unassessed')
        offers=[o for o in state['product.supplierinfo'] if o['partner_id'][0]==po['partner_id'][0] and o['product_tmpl_id'][0]==product['product_tmpl_id'][0] and o['min_qty']<=line['product_qty'] and math.isclose(o['price'],line['price_unit'],abs_tol=.000001)]
        if len(offers)!=1:raise ValueError('supplier MOQ not uniquely resolved in public records')
        origins=[name.strip() for name in po['origin'].split(',')]
        requirement=checker['_origin_traceability_requirement'](origins,line['product_qty'],demand,min_qty=offers[0]['min_qty'])
        if requirement is None:raise ValueError('invalid per-PO origin requirement')
        supply.append(dict(id=po['name'],qty=line['product_qty'],origin_tokens=origins,required_covered_qty=requirement['required_covered_qty'],
            linked_capacity=requirement['total_capacity'],supplier_min_qty=offers[0]['min_qty'],moq_excess_exempted=line['product_qty']-requirement['required_covered_qty']))
    return dict(demand_by_name=demand,supply_rows=supply,purchased_qty=sum(r['qty'] for r in supply),
        required_coverage=sum(r['required_covered_qty'] for r in supply),consumer_capacity=sum(r['qty'] for r in demand.values()),
        traceability_feasible=checker['_traceability_capacity_feasible'](supply,demand))


def certify(counterfactual,code,output):
    counterfactual=Path(counterfactual).resolve();output=Path(output).resolve()
    if output.exists() or not output.is_relative_to(ROOT):raise ValueError('use a fresh local certificate output')
    report=json.loads(counterfactual.read_text())
    for name,expected in report['artifacts'].items():
        path=(ROOT/name).resolve()
        if not path.is_relative_to(ROOT) or erp.sha(path)!=expected:raise ValueError('counterfactual artifact changed')
    original=json.loads((ROOT/report['original_receipt']).read_text());manifest=json.loads((ROOT/original['snapshot_manifest']).read_text());case=Path(manifest['case_dir']);erp.check_source(case)
    source=case/'tests/checks.py';checker=checker_functions(source)
    before=json.loads((counterfactual.parent/'reference-business-state.json').read_text());after=json.loads((counterfactual.parent/'counterfactual-business-state.json').read_text())
    left=projection(before,code,checker);right=projection(after,code,checker)
    if left['traceability_feasible'] or not right['traceability_feasible'] or left['purchased_qty']!=right['purchased_qty'] or left['demand_by_name']!=right['demand_by_name']:raise ValueError('bounded MOQ explanation not established')
    result=dict(passed=True,task_id=report['task_id'],counterfactual_sha256=erp.sha(counterfactual),checker_sha256=erp.sha(source),certifier_sha256=erp.sha(__file__),
        component=code,before=left,after=right,
        scope='Direct-BOM, same-UOM, uniquely resolved supplier-offer traceability diagnosis. Exact upstream pure functions; no source edits, model, physical production/receipt proof or corrected initial-state public agent.')
    erp.save(output,result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--counterfactual',required=True);p.add_argument('--component',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    r=certify(a.counterfactual,a.component,a.output);print(json.dumps(dict(passed=r['passed'],before_required=r['before']['required_coverage'],after_required=r['after']['required_coverage'],capacity=r['after']['consumer_capacity'])))
