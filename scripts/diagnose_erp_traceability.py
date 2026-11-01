"""Read-only direct-BOM component capacity certificate for a failed ERP reference."""
import argparse
import ast
from collections import defaultdict, deque
import json
from pathlib import Path
from faraday_manufacturing_benchmark import erp_compat as erp
ROOT = Path(__file__).resolve().parents[1]


def diagnose(receipt_path, output):
    receipt_path = Path(receipt_path).resolve(); output = Path(output).resolve()
    if output.exists(): raise ValueError('refusing to overwrite diagnosis')
    if not receipt_path.is_relative_to(ROOT) or not output.is_relative_to(ROOT): raise ValueError('artifacts must remain in checkout')
    receipt = json.loads(receipt_path.read_text())
    for name, expected in receipt['artifacts'].items():
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT) or erp.sha(path) != expected: raise ValueError('campaign evidence changed')
    manifest = json.loads((ROOT / receipt['snapshot_manifest']).read_text()); case = Path(manifest['case_dir'])
    erp.check_source(case); checker = case / 'tests/checks.py'
    failures = [r for r in receipt['reference']['verifier']['rules']['failed_rules'] if r['rule'] == 'po_origin_traceability' and r['args'][1] == 'component']
    if len(failures) != 1: raise ValueError('expected exactly one component origin failure')
    code = failures[0]['args'][0]; state_path = receipt_path.parent / 'after-business-state.json'; state = json.loads(state_path.read_text())
    names = {'_scaled_qty', '_origin_traceability_requirement', '_traceability_capacity_feasible'}
    functions = [n for n in ast.parse(checker.read_text()).body if isinstance(n, ast.FunctionDef) and n.name in names]
    if len(functions) != 3: raise ValueError('pinned checker pure-function structure differs')
    namespace = dict(defaultdict=defaultdict, deque=deque)
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(checker), 'exec'), namespace)
    product = next(r for r in state['product.product'] if r['default_code'] == code)
    boms = {r['id']: r for r in state['mrp.bom']}; demand = {}
    for mo in state['mrp.production']:
        if mo['state'] != 'confirmed': continue
        bom = boms[mo['bom_id'][0]]
        quantity = sum(r['product_qty'] for r in state['mrp.bom.line'] if r['bom_id'][0] == bom['id'] and r['product_id'][0] == product['id'])
        if quantity: demand[mo['name']] = dict(qty=mo['product_qty'] * quantity / bom['product_qty'])
    orders = {r['id']: r for r in state['purchase.order']}; supply = []
    for line in state['purchase.order.line']:
        order = orders[line['order_id'][0]]
        if line['product_id'][0] != product['id'] or order['state'] != 'purchase': continue
        origins = [n.strip() for n in order['origin'].split(',')]
        # This certificate covers the no-MOQ-exception case only. It refuses to
        # infer supplier offers or claim a general capacity diagnosis.
        requirement = namespace['_origin_traceability_requirement'](origins, line['product_qty'], demand)
        if requirement is None: raise ValueError('direct capacity certificate cannot assess this row; MOQ/invalid links require separate analysis')
        supply.append(dict(id=order['name'], qty=line['product_qty'], origin_tokens=origins, required_covered_qty=requirement['required_covered_qty']))
    required = sum(r['required_covered_qty'] for r in supply); capacity = sum(r['qty'] for r in demand.values())
    feasible = namespace['_traceability_capacity_feasible'](supply, demand)
    if feasible or required <= capacity: raise ValueError('no total-capacity contradiction established by this bounded diagnosis')
    report = dict(task_id=receipt['task_id'], component=code, original_receipt_sha256=erp.sha(receipt_path),
        source_checker_sha256=erp.sha(checker), state_sha256=erp.sha(state_path), diagnostic_sha256=erp.sha(__file__),
        demand_by_name=demand, supply_rows=supply, total_required_coverage=required,
        total_linked_consumer_capacity=capacity, unchanged_upstream_pure_capacity_check=feasible,
        scope='Read-only direct-BOM, confirmed-order, no-MOQ-exception capacity certificate. Exact three upstream pure checker functions extracted by AST; upstream module not imported. No task mutation, corrected oracle, model score or general upstream defect claim.')
    erp.save(output, report); return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--receipt', required=True); p.add_argument('--output', required=True); a = p.parse_args()
    print(json.dumps(diagnose(a.receipt, a.output)))
