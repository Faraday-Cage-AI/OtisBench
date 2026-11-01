from pathlib import Path
import pytest
from faraday_manufacturing_benchmark.release_audit import local_file,validate_row


def test_receipt_paths_cannot_escape_repository(tmp_path):
    with pytest.raises(ValueError):local_file(tmp_path,'../outside.json.gz')
    with pytest.raises(ValueError):local_file(tmp_path,'/tmp/outside.json.gz')
    assert local_file(tmp_path,'runs/receipt.json.gz')==tmp_path/'runs/receipt.json.gz'


def test_geometric_mutations_must_be_present_and_fail():
    row=dict(strict_success=True,kernel_replay_strict=True,geometric_mutations=dict(bounding_box_only=False,stale_revision=False,wrong_datum=False))
    assert validate_row('cad',row)==[]
    row['geometric_mutations'].pop('wrong_datum')
    assert 'geometry mutations' in validate_row('cad',row)


def test_season_qualification_never_uses_profit_as_correctness():
    row=dict(policy='idle',weeks=26,exact_replay=True,ledger_passed=True,ledger_errors=[],score=-1000,mutations=[dict(kind=k,rejected=True) for k in ('cash','capacity','terminal_profit','terminal_holding','shipment')])
    assert validate_row('seasons',row)==[]
    row['ledger_passed']=False
    assert 'independent ledger' in validate_row('seasons',row)


def test_empty_case_controls_do_not_vacuously_pass():
    for track in ('engineering','supply-chain','procurement','sensors','cad','execution','seasons'):
        assert validate_row(track,dict(strict_success=True,exact_replay=True))


def test_document_evidence_mutations_require_every_line_and_group():
    from faraday_manufacturing_benchmark.documents import FACTS,GROUPS
    row=dict(strict_success=True,exact_replay=True,reference_consistent=True,no_read_strict_failure=True,empty_zero=True,line_coverage_controls=True,
        mutations=[dict(line_id=i,field=f,rejected=True) for i in range(1,5) for f in list(FACTS)+['evidence.'+g for g in GROUPS]])
    assert validate_row('documents',row)==[]
    row['mutations'].pop()
    assert 'document field/evidence mutations' in validate_row('documents',row)


def test_advanced_cad_rows_require_a_rejected_feature_omission():
    row=dict(task_id='cad-rounded_plate-text_and_drawing-01',strict_success=True,kernel_replay_strict=True,
             geometric_mutations=dict(bounding_box_only=False,stale_revision=False,wrong_datum=False))
    assert validate_row('cad',row)
    row['advanced_operation_omitted_strict_success']=False
    assert not validate_row('cad',row)
    row['advanced_operation_omitted_strict_success']=True
    assert validate_row('cad',row)
