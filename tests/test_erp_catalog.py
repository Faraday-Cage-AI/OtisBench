"""Full-catalog selection/count integrity; real Odoo runs are separately retained."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('erp_catalog', ROOT / 'scripts/qualify_erp_catalog.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
pytestmark = pytest.mark.skipif(not (m.CACHE / 'erp-tree.json').exists() or not (m.CACHE / 'erp-dataset.source').exists(), reason='Pinned ERP comparator source cache required for catalog integration checks')


def test_pinned_catalog_covers_all_300_tasks_and_29_patterns_first():
    p = m.plan(); rows = p['selected_cases']
    assert len(rows) == len({r['task_id'] for r in rows}) == 300
    assert len({r['pattern'] for r in rows}) == 29
    assert all(r['representative'] for r in rows[:29])
    assert all(r['pattern'].startswith('repair_plan_') for r in rows[:3])
    assert len({r['pattern'] for r in rows[:29]}) == 29
    assert not any(r['representative'] for r in rows[29:])
    assert p['native_case_count_added'] == 0


def test_partial_and_failed_runs_cannot_become_full_catalog_qualification():
    p = m.plan(); first = dict(p['selected_cases'][0], status='complete', qualified=True)
    partial = m.summary(p, [first], 'partial')
    assert not partial['full_catalog_qualified'] and partial['qualified_cases'] == 1
    rows = [dict(row, status='complete', qualified=True) for row in p['selected_cases']]
    rows[-1]['qualified'] = False
    failed = m.summary(p, rows, 'complete')
    assert not failed['full_catalog_qualified'] and len(failed['failed_cases']) == 1
    assert failed['patterns_with_qualified_case'] == 29


@pytest.mark.parametrize('change', ['duplicate', 'unknown', 'wrong-pattern', 'nonboolean'])
def test_invalid_case_rows_fail_closed(change):
    p = m.plan(); row = dict(p['selected_cases'][0], status='complete', qualified=True); rows = [row]
    if change == 'duplicate': rows.append(deepcopy(row))
    elif change == 'unknown': row['task_id'] = 'unknown'
    elif change == 'wrong-pattern': row['pattern'] = 'unsupported-pattern'
    else: row['qualified'] = 1
    with pytest.raises(ValueError): m.summary(p, rows, 'complete')
