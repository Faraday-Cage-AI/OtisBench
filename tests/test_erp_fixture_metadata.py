from copy import deepcopy
import hashlib
from pathlib import Path
import pytest
from faraday_manufacturing_benchmark import erp_compat as e


def manifest(version='odoo-baseline/2',repair=True):
    return dict(format=version,protocol=e.VERSION,protocol_sha256=e.sha(Path(e.__file__).with_name('erp_protocol.py')),
        restore_sha256=hashlib.sha256((e.LEGACY_RESTORE if version=='odoo-baseline/1' else e.RESTORE).encode()).hexdigest(),
        upstream=dict(task_id='2272_easy_repair_plan_easy' if repair else '2000_easy_01_buy_only_baseline'),
        files={e.FIXTURE_NAME:'a'*64},fixture_metadata={e.FIXTURE_PATH:dict(filename=e.FIXTURE_NAME,sha256='a'*64)} if repair else {})


def test_legacy_recipe_hash_matches_real_frozen_normal_fixture():
    # The exact originally captured recipe remains available for historical checks.
    assert hashlib.sha256(e.LEGACY_RESTORE.encode()).hexdigest()=='ab43be414f25424f0063481693e66b2a386ff4b1979f5fb457307c4c049d4bb1'
    assert not e.snapshot_contract(manifest('odoo-baseline/1',repair=False))
    with pytest.raises(ValueError,match='legacy repair'):e.snapshot_contract(manifest('odoo-baseline/1'))


def test_repair_metadata_must_be_declared_and_hash_bound():
    m=manifest();assert e.snapshot_contract(m)==m['fixture_metadata']
    for change in ['missing','different-hash','different-filename','unknown-path']:
        bad=deepcopy(m)
        if change=='missing':bad['fixture_metadata']={}
        elif change=='different-hash':bad['fixture_metadata'][e.FIXTURE_PATH]['sha256']='b'*64
        elif change=='different-filename':bad['fixture_metadata'][e.FIXTURE_PATH]['filename']='api_key'
        else:bad['fixture_metadata']['/etc/odoo/api_key']=bad['fixture_metadata'].pop(e.FIXTURE_PATH)
        with pytest.raises(ValueError):e.snapshot_contract(bad)


def test_metadata_ids_and_names_must_match_the_restored_business_records():
    payload=dict(purchase_orders={'R1':dict(po_id=12,name='P00012',plan_ref='planned-1')},manufacturing_orders={})
    state={'purchase.order':[dict(id=12,name='P00012')],'mrp.production':[]}
    assert e.validate_fixture_metadata(payload,state,required=True)==1
    for field,value in [('po_id',13),('po_id',True),('name','P-WRONG')]:
        bad=deepcopy(payload);bad['purchase_orders']['R1'][field]=value
        with pytest.raises(ValueError):e.validate_fixture_metadata(bad,state,required=True)
    with pytest.raises(ValueError,match='nonempty'):e.validate_fixture_metadata(dict(purchase_orders={},manufacturing_orders={}),state,required=True)


def test_metadata_is_explicitly_copied_into_private_fixture_path():
    assert 'install -m 600 /bridge/repair_seeded_records.json /tmp/repair_seeded_records.json' in e.RESTORE
    assert 'repair_seeded_records.json' not in e.LEGACY_RESTORE
