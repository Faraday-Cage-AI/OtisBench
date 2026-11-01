from copy import deepcopy
import importlib.util
import math
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('hydraulic', ROOT / 'scripts/hydraulic_benchmark.py')
h = importlib.util.module_from_spec(spec); spec.loader.exec_module(h)
agent_spec = importlib.util.spec_from_file_location('hydraulic_agent', ROOT / 'examples/hydraulic_knn_agent.py')
a = importlib.util.module_from_spec(agent_spec); agent_spec.loader.exec_module(a)


def oracle(labels): return {target: {str(level): float(level == labels[target]) for level in levels} for target, levels in h.TARGETS.items()}


def test_group_split_never_separates_repeated_conditions_or_stability_variants():
    rows = [[3, 73, 0, 90, 0], [20, 80, 1, 100, 0], [100, 90, 2, 115, 0], [3, 73, 0, 90, 1], [100, 100, 0, 130, 0]]
    splits, _ = h.partition(rows)
    assert splits[0] == splits[3]
    reversed_split, _ = h.partition(list(reversed(rows)))
    assert splits == list(reversed(reversed_split))


def test_oracle_has_perfect_joint_accuracy_and_zero_losses():
    labels = {target: levels[0] for target, levels in h.TARGETS.items()}
    truth = {'a': {'labels': labels}}
    metrics = h.metrics(truth, {'a': oracle(labels)})
    assert metrics['joint_exact_accuracy'] == 1
    for row in metrics['targets'].values():
        assert row['accuracy'] == row['balanced_accuracy'] == 1
        assert row['log_loss'] == row['multiclass_brier'] == row['ece_10_bins'] == 0


def test_wrong_confident_answers_are_penalized_and_joint_requires_every_target():
    labels = {target: levels[0] for target, levels in h.TARGETS.items()}; predicted = oracle(labels)
    predicted['cooler'] = {'3': 0, '20': 0, '100': 1}
    result = h.metrics({'a': {'labels': labels}}, {'a': predicted})
    assert result['joint_exact_accuracy'] == 0
    assert result['targets']['cooler']['multiclass_brier'] == 2
    assert result['targets']['cooler']['ece_10_bins'] == 1
    assert result['targets']['cooler']['log_loss'] > 30
    assert result['targets']['valve']['accuracy'] == 1


@pytest.mark.parametrize('change', ['missing-target', 'extra-target', 'missing-class', 'nan', 'inf', 'negative', 'boolean', 'sum'])
def test_invalid_probability_submissions_fail_closed(change):
    p = oracle({target: levels[0] for target, levels in h.TARGETS.items()})
    if change == 'missing-target': del p['cooler']
    elif change == 'extra-target': p['stability'] = {'0': 1}
    elif change == 'missing-class': del p['cooler']['20']
    else: p['cooler']['3'] = {'nan': math.nan, 'inf': math.inf, 'negative': -.1, 'boolean': True, 'sum': .5}[change]
    with pytest.raises(ValueError): h.validate_probabilities(p)


def test_unanswered_cycles_cannot_disappear_from_metrics():
    labels = {target: levels[0] for target, levels in h.TARGETS.items()}
    with pytest.raises(ValueError, match='coverage'): h.metrics({'a': {'labels': labels}}, {})


def test_agent_fits_on_training_only_and_rejects_refitting():
    agent = a.Agent()
    labels = {target: levels[0] for target, levels in h.TARGETS.items()}
    payload = dict(phase='fit', method='knn', task=dict(target_levels=h.TARGETS, feature_names=['x']),
                   training_rows=[dict(features=[i], labels=labels) for i in range(7)])
    assert agent.decide(payload) == {'ready': True}
    old_mean, old_scale = deepcopy(agent.mean), deepcopy(agent.scale)
    result = agent.decide(dict(phase='predict', case=dict(id='unseen', features=[10000])))
    h.validate_probabilities(result['arguments']['probabilities'])
    assert agent.mean == old_mean and agent.scale == old_scale
    with pytest.raises(ValueError, match='refit'): agent.decide(payload)


def test_raw_feature_fixture_has_declared_population_statistics():
    np = pytest.importorskip('numpy')
    actual = h.features(np.array([[1., 2., 3., 4.], [5., 5., 5., 5.]]))
    assert actual[0].tolist() == pytest.approx([2.5, math.sqrt(1.25), 1, 4, 1.75, 2.5, 3.25, 2])
    assert actual[1].tolist() == [5, 0, 5, 5, 5, 5, 5, 0]
    with pytest.raises(ValueError): h.features(np.array([[math.nan, 1]]))
