from copy import deepcopy
import importlib.util
from pathlib import Path
import pytest
from faraday_manufacturing_benchmark.shopfloor_cases import catalog,build_records

spec=importlib.util.spec_from_file_location('workflow_lineage',Path(__file__).resolve().parents[1]/'scripts/audit_workflow_lineage.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def test_ids_row_order_material_and_numeric_draws_do_not_create_route_novelty():
    task=catalog()[0];a=m.chain_signature(build_records(task));other=deepcopy(task);other['seed']+=94873
    assert m.chain_signature(build_records(other))==a
    records=build_records(task);names={row['id']:'OPAQUE-'+str(i) for i,row in enumerate(records['PLM']['route'])}
    for row in records['PLM']['route']:
        row['id']=names[row['id']]
        if row['predecessor'] is not None:row['predecessor']=names[row['predecessor']]
        row['fixture']='CHANGED-FIXTURE-ALIAS'
    records['PLM']['instructions']={names[k]:v for k,v in records['PLM']['instructions'].items()}
    records['PLM']['route'].reverse();records['PLM']['material']='ANOTHER-MATERIAL-NAME'
    assert m.chain_signature(records)==a


def test_process_renaming_changes_named_sequence_but_not_topology_or_control_rules():
    records=build_records(catalog()[0]);before=m.chain_signature(records)
    for row in records['PLM']['route']:row['process']='RENAMED-'+row['process']
    after=m.chain_signature(records)
    assert before['process_sha256']!=after['process_sha256']
    assert before['control_sha256']==after['control_sha256']
    assert before['topology_sha256']==after['topology_sha256']


@pytest.mark.parametrize('change',['cycle','branch','missing-predecessor','duplicate-id','missing-instruction'])
def test_unassessed_or_invalid_graphs_fail_closed(change):
    records=build_records(catalog()[0]);route=records['PLM']['route']
    if change=='cycle':route[0]['predecessor']=route[-1]['id']
    elif change=='branch':route[2]['predecessor']=route[0]['id']
    elif change=='missing-predecessor':route[1]['predecessor']='UNKNOWN'
    elif change=='duplicate-id':route[1]['id']=route[0]['id']
    else:records['PLM']['instructions'].pop(route[0]['id'])
    with pytest.raises(ValueError):m.chain_signature(records)


def test_all_public_cases_and_reseeded_cases_are_rejected_as_final_holdouts():
    report=m.inventory()
    assert report['development_cases']==1024 and report['released_route_topologies']==2
    assert report['released_route_control_sequences']==25
    assert not report['private_holdout_established']
    for task in catalog():
        assert not m.overlap(task,report)['final_holdout_admitted']
    task=deepcopy(catalog()[0]);task.update(id='PRIVATE-RENAMED-CANDIDATE',seed=987654321)
    assert m.overlap(task,report)['known_development_control_overlap']


def test_public_partition_keeps_all_control_aliases_faults_and_draws_together():
    report=m.inventory();seen={}
    for row in report['cases']:seen.setdefault(row['control_sha256'],set()).add(row['suggested_public_development_partition'])
    assert all(len(values)==1 for values in seen.values())
    assert sum(v['cases'] for v in report['suggested_public_development_partition'].values())==1024


def test_unknown_generator_cannot_self_certify_novelty():
    task=deepcopy(catalog()[0]);task['family']='NEW-NAME-NOT-AN-IMPLEMENTED-WORKFLOW'
    with pytest.raises(ValueError,match='unsupported'):m.overlap(task,m.inventory())
