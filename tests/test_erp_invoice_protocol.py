import importlib.util
from pathlib import Path
import pytest
from faraday_manufacturing_benchmark import erp_protocol as original

spec=importlib.util.spec_from_file_location('erp_invoice_protocol',Path(__file__).resolve().parents[1]/'scripts/erp_invoice_protocol.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)


def request(method='create',values=None,context=None):
    context=context if context is not None else dict(active_model='sale.order',active_ids=[1])
    kw=dict(context=context)
    if method=='create':kw['vals_list']=[values or dict(advance_payment_method='delivered')]
    else:kw['ids']=[1]
    return dict(model='sale.advance.payment.inv',method=method,kwargs=kw)


@pytest.mark.parametrize('values',[dict(advance_payment_method='delivered'),dict(advance_payment_method='fixed',fixed_amount=250),dict(advance_payment_method='percentage',amount=40)])
def test_declared_wizard_modes_are_allowed_without_changing_frozen_protocol(values):
    r=request(values=values)
    assert p.validate(r)==r['kwargs']
    with pytest.raises(original.PolicyDenied):original.validate(r)
    assert 'sale.advance.payment.inv' not in original.SPECS


def test_linked_invoice_fields_are_readable_only_in_versioned_extension():
    r=dict(model='sale.order',method='read',kwargs=dict(ids=[1],fields=['id','invoice_ids']))
    assert p.validate(r)==r['kwargs']
    with pytest.raises(original.PolicyDenied):original.validate(r)


@pytest.mark.parametrize('context',[dict(active_model='res.users',active_ids=[1]),dict(active_model='sale.order',active_ids=[1],allowed_company_ids=[1]),dict(active_model='sale.order',active_ids=[1],default_user_id=1)])
def test_context_cannot_select_nonbusiness_models_or_override_environment(context):
    with pytest.raises(p.PolicyDenied):p.validate(request(context=context))


@pytest.mark.parametrize('context',[dict(active_model='sale.order',active_ids=[]),dict(active_model='sale.order',active_ids=[True]),dict(active_model='sale.order',active_ids=[1,2])])
def test_wizard_context_binds_exactly_one_positive_order_id(context):
    with pytest.raises(ValueError):p.validate(request(context=context))


@pytest.mark.parametrize('values',[dict(advance_payment_method='percentage',amount=float('nan')),dict(advance_payment_method='percentage',amount=101),dict(advance_payment_method='fixed',fixed_amount=-1),dict(advance_payment_method='fixed',fixed_amount=True)])
def test_nonfinite_or_invalid_downpayment_amounts_are_rejected(values):
    with pytest.raises(ValueError):p.validate(request(values=values))


@pytest.mark.parametrize('method',['write','unlink','sudo','with_context','action_send_mail'])
def test_wizard_cannot_be_used_as_a_generic_model_escape(method):
    with pytest.raises(p.PolicyDenied):p.validate(request(method=method))


def test_invoice_action_requires_bounded_context_and_generic_models_reject_context():
    r=request(method='create_invoices');assert p.validate(r)==r['kwargs']
    r['kwargs']['context']['force_company']=1
    with pytest.raises(p.PolicyDenied):p.validate(r)
    with pytest.raises(p.PolicyDenied):p.validate(dict(model='sale.order',method='read',kwargs=dict(ids=[1],fields=['id'],context={'active_model':'sale.order','active_ids':[1]})))
