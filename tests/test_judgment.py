"""Workshop boundaries, staged revisions, and explicit reviewer assessment."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from faraday_manufacturing_benchmark.judgment import (
    catalog, start, observe, submit, review, validate, execute, DIMENSIONS,
)


def decision(state):
    return dict(recommendation='Transport fixture; no manufacturing recommendation is evaluated.',
        alternatives=['A different recommendation may be defensible.'], tradeoffs='Reviewer assessment remains required.',
        assumptions=['This fixture only tests the submission boundary.'],
        next_actions=[dict(owner='Test participant', action='Record this submission', trigger='Current round')],
        evidence_ids=[observe(state)['records'][-1]['id']], revision_reason='Record a new version for the current evidence.')


@pytest.mark.parametrize('task', catalog(), ids=lambda t: t['id'])
def test_each_workshop_reveals_evidence_only_after_a_committed_decision(task):
    state = start(task['id'])
    assert len(task['stages']) == 3
    for index in range(3):
        snapshot = observe(state)
        expected = [r for stage in task['stages'][:index + 1] for r in stage['records']]
        assert snapshot['records'] == expected
        assert snapshot['prior_decisions'] == state['submissions']
        assert 'score' not in snapshot and 'dimensions' not in snapshot and 'stages' not in snapshot
        if index < 2:
            later = {r['id'] for stage in task['stages'][index + 1:] for r in stage['records']}
            assert not later.intersection(r['id'] for r in snapshot['records'])
        candidate = decision(state)
        next_state = submit(state, candidate)
        candidate['recommendation'] = 'mutated outside session'
        assert len(state['submissions']) == index
        assert next_state['submissions'][-1]['recommendation'] != candidate['recommendation']
        state = next_state
    assert observe(state)['status'] == 'awaiting_review'
    assert 'score' not in state
    with pytest.raises(ValueError, match='already submitted'):
        submit(state, decision(state))


def test_future_citations_and_automatic_judging_fields_are_rejected():
    task = catalog()[0]; state = start(task['id']); candidate = decision(state)
    candidate['evidence_ids'] = [task['stages'][1]['records'][0]['id']]
    with pytest.raises(ValueError, match='already visible'):
        submit(state, candidate)
    candidate = decision(state); candidate['score'] = 100
    with pytest.raises(ValueError, match='contract'):
        submit(state, candidate)


def test_history_is_checked_against_evidence_available_at_each_round():
    task = catalog()[0]; state = start(task['id'])
    state = submit(state, decision(state))
    state['submissions'][0]['evidence_ids'] = [task['stages'][2]['records'][0]['id']]
    with pytest.raises(ValueError, match='already visible'):
        validate(state)
    state = start(task['id']); state['source_sha256'] = 'stale'
    with pytest.raises(ValueError, match='source mismatch'):
        observe(state)


def test_review_requires_completed_work_and_records_evidence_bound_human_ratings():
    state = start(catalog()[0]['id'])
    with pytest.raises(ValueError, match='complete all'):
        review(state, {})
    for _ in range(3):
        state = submit(state, decision(state))
    assessment = dict(reviewer='Local reviewer', relationship='Author reviewing a transport fixture', dimensions={
        d:dict(rating=3, rationale='Fixture rating supplied by the test, never inferred by the program.',
               evidence_ids=[observe(state)['records'][0]['id']], rounds=[1, 2, 3]) for d in DIMENSIONS})
    result = review(state, assessment)
    assert result['mean_rating'] == 3
    assert result['assessment_type'] == 'reviewer_judgment'
    assert 'strict_success' not in result
    broken = deepcopy(assessment); broken['dimensions']['evidence_use']['rounds'] = [4]
    with pytest.raises(ValueError, match='submission rounds'):
        review(state, broken)
    broken = deepcopy(assessment); broken['dimensions']['evidence_use']['rating'] = True
    with pytest.raises(ValueError, match='integer'):
        review(state, broken)
    changed = submit(start(catalog()[1]['id']), decision(start(catalog()[1]['id'])))
    assert changed['task_id'] != result['task_id']


def test_cli_preserves_session_and_rejects_accidental_overwrite(tmp_path, capsys):
    path = tmp_path/'session.json'
    args = SimpleNamespace(judgment_command='start', task=catalog()[0]['id'], session=str(path))
    execute(args)
    output = json.loads(capsys.readouterr().out)
    assert output['status'] == 'awaiting_decision'
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        execute(args)
    assert path.read_bytes() == before
    candidate_path = tmp_path/'decision.json'
    candidate_path.write_text(json.dumps(decision(json.loads(before))))
    execute(SimpleNamespace(judgment_command='submit', session=str(path), decision=str(candidate_path)))
    assert json.loads(capsys.readouterr().out)['round'] == 2
    execute(SimpleNamespace(judgment_command='show', session=str(path)))
    assert json.loads(capsys.readouterr().out)['prior_decisions']
