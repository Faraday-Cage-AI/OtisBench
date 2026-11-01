import hashlib
import importlib.util
import json
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]


def module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/f'scripts/{name}.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def test_model_partial_score_and_strict_units_are_distinct():
    m=module('audit_comparators')
    result=m.model_summary({'trials':[{'task_id':'a','score':100,'strict_pass':True},{'task_id':'b','score':50,'strict_pass':False}]})
    assert result['mean_factory_score']==75 and result['strict_fraction']==.5 and result['strict_percent']==50
    assert result['strict_passes']==1


@pytest.mark.parametrize('trials',[
 [{'task_id':'a','score':100,'strict_pass':True}]*2,
 [{'task_id':'a','score':100,'strict_pass':1}],
 [{'task_id':'a','score':float('nan'),'strict_pass':False}],
])
def test_invalid_model_coverage_and_metrics_fail_closed(trials):
    with pytest.raises(ValueError):module('audit_comparators').model_summary({'trials':trials})


def source():
    pin='a'*40
    return dict(id='source',url=f'https://raw.githubusercontent.com/owner/repo/{pin}/README.md',commit=pin,kind='pinned_repository_file',cache_file='source.txt')


@pytest.mark.parametrize('bad',['../secret','..','/tmp/secret'])
def test_comparator_cache_paths_cannot_escape(bad):
    m=module('capture_comparator_sources');r=source();r['cache_file']=bad
    with pytest.raises(ValueError):m.validate_sources({'sources':[r]})


def test_commit_in_query_does_not_make_mutable_branch_pinned():
    m=module('capture_comparator_sources');r=source();r['url']='https://raw.githubusercontent.com/owner/repo/main/README.md?commit='+r['commit']
    with pytest.raises(ValueError,match='unpinned'):m.validate_sources({'sources':[r]})


def test_offline_inventory_detects_changed_source_bytes(tmp_path,monkeypatch):
    m=module('capture_comparator_sources');cache=tmp_path/'cache';cache.mkdir();file=cache/'source.txt';file.write_bytes(b'original')
    config={'sources':[source()]};config_file=tmp_path/'config.json';config_file.write_text(json.dumps(config))
    monkeypatch.setattr(m,'ROOT',tmp_path);monkeypatch.setattr(m,'CACHE',cache);monkeypatch.setattr(m,'CONFIG',config_file)
    report=dict(config_sha256=m.sha(config_file),collector_sha256=m.sha(Path(m.__file__)),sources=[dict(source(),status='available',cache_path='cache/source.txt',sha256=m.sha(file))])
    assert m.check_inventory(config,report)==[]
    file.write_bytes(b'changed')
    assert m.check_inventory(config,report)==['source: missing/changed cached source']
