from copy import deepcopy
import importlib.util
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]


def load(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/file);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


diag=load('origin_diag','counterfactual_erp_origins.py');certificate=load('origin_certificate','certify_erp_origin_flow.py')


def state():
    return {'product.product':[dict(id=1,default_code='COMP',uom_id=[1,'Units'],product_tmpl_id=[10,'Component'])],
        'mrp.bom':[dict(id=1,product_qty=1)],'mrp.bom.line':[dict(bom_id=[1,'BOM'],product_id=[1,'Component'],product_qty=1,product_uom_id=[1,'Units'])],
        'mrp.production':[dict(name='MO-A',state='confirmed',bom_id=[1,'BOM'],product_qty=32)],
        'purchase.order':[dict(id=1,name='PO-A',state='purchase',partner_id=[7,'Vendor'],origin='MO-A')],
        'purchase.order.line':[dict(order_id=[1,'PO-A'],product_id=[1,'Component'],product_uom_id=[1,'Units'],product_qty=34,price_unit=20)],
        'product.supplierinfo':[dict(partner_id=[7,'Vendor'],product_tmpl_id=[10,'Component'],min_qty=34,price=20)]}


def test_business_projection_change_inventory_is_explicit():
    before={'purchase.order':[dict(id=1,origin='A, B',amount_total=10)]};after=deepcopy(before);after['purchase.order'][0]['origin']='A'
    assert diag.difference(before,after)==[dict(model='purchase.order',id=1,field='origin',before='A, B',after='A')]
    after['purchase.order'][0]['amount_total']=11
    assert len(diag.difference(before,after))==2


def test_extra_business_record_cannot_be_hidden_in_single_origin_diagnostic():
    with pytest.raises(ValueError,match='created/deleted'):diag.difference({'purchase.order':[dict(id=1)]},{'purchase.order':[dict(id=1),dict(id=2)]})


def test_ambiguous_supplier_moq_is_unassessed_instead_of_certified():
    records=state();records['product.supplierinfo'].append(deepcopy(records['product.supplierinfo'][0]))
    with pytest.raises(ValueError,match='not uniquely resolved'):certificate.projection(records,'COMP',{})


@pytest.mark.parametrize('model,field',[('mrp.bom.line','product_uom_id'),('purchase.order.line','product_uom_id')])
def test_mixed_units_fail_closed_without_unimplemented_conversion(model,field):
    records=state();records[model][0][field]=[2,'Boxes']
    with pytest.raises(ValueError,match='UOM conversion'):certificate.projection(records,'COMP',{})


def test_missing_upstream_pure_checker_functions_cannot_certify(tmp_path):
    source=tmp_path/'checks.py';source.write_text('def _scaled_qty(value): return value\n')
    with pytest.raises(ValueError,match='structure changed'):certificate.checker_functions(source)


@pytest.mark.parametrize('kind,count',[('public model result',0),('private-reference-assisted single-field counterfactual diagnostic',1)])
def test_assisted_diagnostic_cannot_be_laundered_into_public_or_native_result(kind,count,monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT/'scripts'))
    auditor=load('origin_audit','audit_erp_origin_counterfactual.py')
    with pytest.raises(ValueError,match='promoted'):
        auditor.scope(dict(control_kind=kind,native_case_count_added=count))
