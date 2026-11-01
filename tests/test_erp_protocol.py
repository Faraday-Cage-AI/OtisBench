from copy import deepcopy
import pytest
from faraday_manufacturing_benchmark.erp_protocol import validate,PolicyDenied


def rpc(model='sale.order',method='search_read',**kwargs):return dict(model=model,method=method,kwargs=kwargs)


@pytest.mark.parametrize('model',['res.users','res.users.apikeys','ir.config_parameter','ir.actions.server','mail.mail','ir.attachment'])
def test_identity_code_credentials_and_mail_endpoints_are_unreachable(model):
    with pytest.raises(PolicyDenied):validate(rpc(model,domain=[],fields=['id']))


@pytest.mark.parametrize('method',['_load_records','sudo','with_context','message_post','export_data','unlink','execute_query'])
def test_unlisted_methods_do_not_reach_orm(method):
    with pytest.raises(PolicyDenied):validate(rpc(method=method,ids=[1]))


def test_business_search_is_bounded_and_cannot_follow_private_relations():
    result=validate(rpc(domain=[['state','=','sale']],fields=['id','name']))
    assert result['limit']==100 and result['order']=='id asc'
    for domain in [[['partner_id.user_ids.apikey_ids','!=',False]],[['id','any!',[]]]]:
        with pytest.raises(PolicyDenied):validate(rpc(domain=domain,fields=['id']))
    with pytest.raises(ValueError):validate(rpc(domain=[],fields=['id'],limit=100000))


def test_context_cannot_widen_permissions():
    with pytest.raises(PolicyDenied):validate(rpc(domain=[],fields=['id'],context={'sudo':True}))


def test_nested_order_lines_accept_commercial_values_not_private_model_writes():
    request=rpc(method='create',vals_list=[dict(partner_id=1,order_line=[[0,0,dict(product_id=2,product_uom_qty=10,price_unit=123.45)]])])
    assert validate(request)==request['kwargs']
    bad=deepcopy(request);bad['kwargs']['vals_list'][0]['order_line'][0][2]['user_ids']=[[0,0,dict(login='intruder')]]
    with pytest.raises(PolicyDenied):validate(bad)


@pytest.mark.parametrize('value',[True,-1,0,'1',None])
def test_record_identity_requires_positive_integer(value):
    with pytest.raises(ValueError):validate(rpc(method='action_confirm',ids=[value]))


def test_wrong_but_schema_valid_price_is_not_solved_or_rejected_by_gateway():
    request=rpc(model='purchase.order.line',method='write',ids=[1],vals={'price_unit':999999})
    assert validate(request)==request['kwargs']
