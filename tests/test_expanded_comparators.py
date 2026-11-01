from copy import deepcopy
import importlib.util
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('expanded_audit',ROOT/'scripts/audit_expanded_comparators.py');audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)


@pytest.fixture
def config():return audit.read(audit.CONFIG)


def test_selected_primary_review_does_not_claim_global_ranking(config):
    result=audit.validate_config(config)
    assert result['exhaustive_world_survey'] is False
    assert result['common_model_ranking'] is False
    assert result['native_cases_added']==0
    assert len(result['resources'])==12
    assert next(r for r in result['resources'] if r['id']=='sopbench')['relationship']=='adjacent'


@pytest.mark.parametrize('key,value',[('exhaustive_world_survey',True),('common_model_ranking',True),('native_cases_added',100)])
def test_scope_promotions_rejected(config,key,value):
    config[key]=value
    with pytest.raises(ValueError,match='promotion'):audit.validate_config(config)


def test_missing_or_duplicate_resources_rejected(config):
    config['resources'][0]=deepcopy(config['resources'][1])
    with pytest.raises(ValueError,match='missing, duplicate'):audit.validate_config(config)


def test_each_resource_requires_primary_evidence_and_an_explicit_gap(config):
    config['resources'][0]['source_ids']=[]
    with pytest.raises(ValueError,match='classification'):audit.validate_config(config)


def make_db(path,rows,wall_time):
    import sqlite3,gzip
    temporary=path.with_suffix('.sqlite');db=sqlite3.connect(temporary)
    db.executescript('CREATE TABLE orders(id TEXT, amount INTEGER); CREATE TABLE audit_events(id INTEGER, wall_time TEXT, action TEXT);')
    db.executemany('INSERT INTO orders VALUES(?,?)',rows);db.execute('INSERT INTO audit_events VALUES(1,?,?)',(wall_time,'post'));db.commit();db.close()
    path.write_bytes(gzip.compress(temporary.read_bytes(),mtime=0))


def test_canonical_replay_ignores_only_wall_time_and_row_order(tmp_path):
    a=tmp_path/'a.gz';b=tmp_path/'b.gz'
    make_db(a,[('x',10),('y',20)],'first');make_db(b,[('y',20),('x',10)],'later')
    assert audit.canonical_database(a)==audit.canonical_database(b)


def test_canonical_replay_keeps_business_values(tmp_path):
    a=tmp_path/'a.gz';b=tmp_path/'b.gz'
    make_db(a,[('x',10)],'first');make_db(b,[('x',11)],'first')
    assert audit.canonical_database(a)!=audit.canonical_database(b)
