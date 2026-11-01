import pytest
from faraday_industrial_benchmark.agents import OracleAgent,NoopAgent,ReadOnlyAgent,UnsafeAgent
from faraday_industrial_benchmark.models import IncidentTask
from faraday_industrial_benchmark.runner import BenchmarkRunner
from faraday_manufacturing_benchmark.cli import workflows


@pytest.mark.parametrize('spec',workflows(),ids=lambda t:t['id'])
def test_full_execution_criteria_gate_and_replay(spec):
    runner=BenchmarkRunner();t=IncidentTask.from_dict(spec)
    good=runner.run_task(t,OracleAgent());replayed=runner.replay(t,good.to_dict()['trace'])
    assert good.score.strict_success and good.score.score==100
    assert replayed['exact_match'] and replayed['score']==good.score.to_dict()
    idle=runner.run_task(t,NoopAgent()).score
    weak=runner.run_task(t,ReadOnlyAgent()).score
    unsafe=runner.run_task(t,UnsafeAgent()).score
    assert not idle.strict_success and idle.dimensions['efficiency']['score']==0
    assert not weak.strict_success and weak.dimensions['efficiency']['score']==0
    assert unsafe.critical_failure and unsafe.score==0
