"""Review intake must never promote a declaration into independent validation."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('review_kit', Path(__file__).resolve().parents[1] / 'scripts/review_kit.py')
kit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kit)


@pytest.fixture
def packet(tmp_path):
    public = tmp_path / 'public'
    kit.save(public / 'task.json', {'prompt': 'Synthetic task'})
    kit.save(public / 'manifest.json', {'protocol': kit.PROTOCOL, 'cases': [{'review_case_id': 'R001'}], 'files': {'task.json': kit.sha(public / 'task.json')}})
    data = dict(protocol=kit.PROTOCOL, public_manifest_sha256=kit.sha(public / 'manifest.json'),
        reviewer=dict(name='Test fixture, not an actual reviewer', role='fixture', relevant_experience='fixture',
                      relationship_to_authors='test only', prior_exposure_to_references='test only', assistance_and_tools_used='test only'),
        cases=[dict(review_case_id='R001', disposition='solved', answer={'units': 5}, reasoning='Test fixture reasoning', findings=[])])
    submission = tmp_path / 'submission.json'
    kit.save(submission, data)
    return public, submission, data, tmp_path / 'receipt.json'


def test_frozen_receipt_retains_exact_original_but_certifies_nothing(packet):
    public, submission, _, receipt = packet
    original = submission.read_bytes()
    kit.freeze(public, submission, receipt)
    result = kit.read(receipt)
    assert result['original_submission_utf8'].encode() == original
    assert result['submission_sha256'] == kit.sha(submission)
    assert result['status'] == 'frozen-unverified-submission'
    assert all(result[k] is False for k in ('identity_verified', 'independence_verified', 'expertise_verified', 'correctness_verified'))
    submission.write_text('{}')
    with pytest.raises(ValueError, match='already exists'):
        kit.freeze(public, submission, receipt)
    assert kit.read(receipt) == result


@pytest.mark.parametrize('change', ['tamper', 'extra', 'missing', 'symlink'])
def test_packet_inventory_and_content_are_verified(packet, change):
    public, submission, _, receipt = packet
    path = public / 'task.json'
    if change == 'tamper': path.write_text('{}')
    elif change == 'extra': (public / 'unexpected.json').write_text('{}')
    elif change == 'missing': path.unlink()
    else:
        target = public.parent / 'target.json'; target.write_bytes(path.read_bytes())
        path.unlink(); path.symlink_to(target)
    with pytest.raises(ValueError): kit.freeze(public, submission, receipt)
    assert not receipt.exists()


@pytest.mark.parametrize('change', ['source', 'identity', 'duplicate', 'unknown', 'not-reviewed', 'no-reason', 'no-answer', 'unresolved-no-finding'])
def test_incomplete_or_mismatched_submissions_fail_closed(packet, change):
    public, submission, data, receipt = packet
    case = data['cases'][0]
    if change == 'source': data['public_manifest_sha256'] = '0' * 64
    elif change == 'identity': data['reviewer']['name'] = ''
    elif change == 'duplicate': data['cases'].append(deepcopy(case))
    elif change == 'unknown': case['review_case_id'] = 'R999'
    elif change == 'not-reviewed': case['disposition'] = 'not-reviewed'
    elif change == 'no-reason': case['reasoning'] = ''
    elif change == 'no-answer': case['answer'] = None
    else: case['disposition'] = 'ambiguous'
    kit.save(submission, data)
    with pytest.raises(ValueError): kit.freeze(public, submission, receipt)
    assert not receipt.exists()


def test_disagreement_can_be_preserved_without_reference_answer(packet):
    public, submission, data, receipt = packet
    case = data['cases'][0]
    case.update(disposition='insufficient-input', answer=None, findings=['A required unit conversion is missing.'])
    kit.save(submission, data)
    kit.freeze(public, submission, receipt)
    assert json.loads(kit.read(receipt)['original_submission_utf8'])['cases'][0]['findings'] == case['findings']


def test_prepared_archive_contains_public_inputs_only_across_nine_tracks(tmp_path):
    destination = tmp_path / 'kit'
    archive = kit.build(destination)
    public = destination / 'public'
    manifest = kit.verify(public)
    assert len(manifest['cases']) == 18
    assert len({c['track'] for c in manifest['cases']}) == 9
    assert kit.read(destination / 'status.json')['independent_reviews_verified'] == 0
    assert kit.read(destination / 'status.json')['messages_sent'] == 0
    with kit.zipfile.ZipFile(archive) as bundle:
        assert set(bundle.namelist()) == set(manifest['files']) | {'manifest.json'}
        assert not any('coordinator-private' in p or 'case-map' in p for p in bundle.namelist())
    # Full source catalog and reference solver are never copied into the packet.
    assert not list(public.rglob('*.py'))
    assert not list(public.rglob('*qualification*'))
    assert (destination / 'coordinator-private/case-map.json').exists()
    with pytest.raises(ValueError, match='already exists'): kit.build(destination)
