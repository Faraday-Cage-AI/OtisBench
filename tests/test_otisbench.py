"""Public release identity and passive CLI contract checks."""
import json
from pathlib import Path
import subprocess
import sys
import pytest
import otisbench
from faraday_manufacturing_benchmark import __version__
from faraday_manufacturing_benchmark.cli import main

ROOT = Path(__file__).resolve().parents[1]


def test_public_version_and_distribution_agree():
    import tomllib
    project = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']
    assert project['name'] == 'otisbench'
    assert project['version'] == otisbench.__version__ == __version__ == '1.4.0'
    assert project['scripts']['otisbench'] == 'otisbench.cli:main'


def test_help_exposes_identity_without_starting_an_episode():
    result = subprocess.run([sys.executable, '-m', 'otisbench', '--help'], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0
    assert 'OtisBench' in result.stdout
    assert 'workflow' in result.stdout


def test_no_command_requires_explicit_selection(capsys):
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2
    assert 'required' in capsys.readouterr().err


def test_public_export_is_startup_data_without_answers(tmp_path):
    path = tmp_path / 'agent.json'
    main(['export-agent', '--task', 'mfg-flow-pump_assembly-16-01', '--output', str(path)])
    data = json.loads(path.read_text())
    assert data['type'] == 'decision'
    assert data['track'] == 'workflow'
    assert data['payload']['last_result'] is None
    assert set(data['payload']['task']) == {'id', 'title', 'prompt', 'systems', 'max_tool_calls', 'horizon_minutes'}
    assert 'mfg-flow-pump_assembly' not in json.dumps(data)
    assert not any(key in json.dumps(data) for key in ('expected_controls', 'reference_answer', 'oracle_plan', 'solution'))
