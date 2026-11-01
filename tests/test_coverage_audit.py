from copy import deepcopy
import importlib.util
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('coverage_audit',ROOT/'scripts/audit_coverage.py');audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)


@pytest.fixture
def inputs():
    native=dict(passed=True,tracks={n:dict(cases=1) for n in audit.NATIVE})
    extensions={n:dict(evidence_integrity_passed=True,native_case_count_added=0,new_business_scenarios=0) for n in audit.EXTENSIONS}
    extensions['supplier_scans_original']['strict_successes']=0
    extensions['supplier_scan_policy']['strict_successes']=28
    extensions['material_networks']['new_business_scenarios']=48
    relations=dict(format_source_ids=[f'doc-{i}' for i in range(16)],scan_source_ids=[f'doc-{i}' for i in range(16)],native_document_scenario_ids=[f'doc-{i}' for i in range(16)],
        invoice_case_ids=['erp-0'],compatibility_case_ids=['erp-1'],erp_selected_ids=[f'erp-{i}' for i in range(300)])
    erp=dict(selected_cases=300,resolved_cases=73,qualified_cases=72,failed_cases=['erp-2'],patterns_total=29,patterns_with_qualified_case=29)
    comparative=dict(conclusion=dict(world_superlative_established=False))
    lineage=dict(private_holdout_established=False,named_route_families=32,released_route_topologies=2,released_route_control_sequences=25)
    return native,extensions,erp,comparative,lineage,relations


def test_integrity_does_not_promote_failed_controls_or_global_claim(inputs):
    result=audit.derive(*inputs)
    assert result['conclusion']['evidence_integrity_passed']
    assert not result['conclusion']['all_control_presentations_successful']
    assert not result['conclusion']['world_superlative_established']
    assert result['completion_gates']['full_erp_author_qualification']=='contradicted_by_retained_failure'
    assert result['document_overlap']['new_business_scenarios']==0
    assert result['erp_overlap']['extra_cases_from_subsets']==0
    assert 'total_cases' not in result


def test_full_erp_selection_is_not_full_runtime_qualification(inputs):
    result=audit.derive(*inputs)
    assert result['erp_catalog']['selected_cases']==300
    assert result['completion_gates']['full_erp_author_qualification']!='met'


def test_even_full_erp_control_success_does_not_close_models_experts_or_holdout(inputs):
    inputs[2].update(resolved_cases=300,qualified_cases=300,failed_cases=[])
    result=audit.derive(*inputs)
    assert result['completion_gates']['full_erp_author_qualification']=='met'
    for key in ['matched_budget_full_suite_models','independent_practitioner_validation','structurally_distinct_private_holdout']:
        assert result['completion_gates'][key]=='unproven'
    assert not result['conclusion']['world_superlative_established']


@pytest.mark.parametrize('name',sorted(audit.EXTENSIONS))
def test_missing_extension_fails_closed(inputs,name):
    del inputs[1][name]
    with pytest.raises(ValueError,match='missing or unexpected'):audit.derive(*inputs)


def test_extension_integrity_failure_cannot_be_ignored(inputs):
    inputs[1]['material_networks']['evidence_integrity_passed']=False
    with pytest.raises(ValueError,match='extension evidence'):audit.derive(*inputs)


@pytest.mark.parametrize('name',['supplier_formats','supplier_scans_original','supplier_scan_policy','erp_invoices'])
def test_presentations_and_upstream_subsets_cannot_add_business_scenarios(inputs,name):
    inputs[1][name]['new_business_scenarios']=48
    with pytest.raises(ValueError,match='cannot add business'):audit.derive(*inputs)


def test_relabeling_document_parents_does_not_establish_distinct_scope(inputs):
    inputs[5]['scan_source_ids'][0]='new-doc-claim'
    with pytest.raises(ValueError,match='same native scenarios'):audit.derive(*inputs)


def test_invoice_case_outside_catalog_rejected(inputs):
    inputs[5]['invoice_case_ids']=['unknown']
    with pytest.raises(ValueError,match='outside pinned'):audit.derive(*inputs)


def test_extension_not_silently_promoted_to_native(inputs):
    inputs[1]['material_networks']['native_case_count_added']=48
    with pytest.raises(ValueError,match='promoted into native'):audit.derive(*inputs)


def test_failed_case_count_and_unknown_identity_are_rejected(inputs):
    inputs[2]['failed_cases']=[]
    with pytest.raises(ValueError,match='failed count'):audit.derive(*inputs)
    inputs[2]['failed_cases']=['not-selected']
    with pytest.raises(ValueError,match='unknown failed'):audit.derive(*inputs)


def test_selected_comparator_review_is_not_global_certification(inputs):
    inputs[3]['conclusion']['world_superlative_established']=True
    with pytest.raises(ValueError,match='worldwide superlative'):audit.derive(*inputs)
