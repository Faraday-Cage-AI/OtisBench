from pathlib import Path
import errno
import importlib.util
import json
import platform
import subprocess
import sys
from unittest.mock import patch
import pytest
from faraday_manufacturing_benchmark.isolation import isolated_agent,profile
from faraday_manufacturing_benchmark.isolation_runner import contracts,run_task,replay_episode
ROOT=Path(__file__).resolve().parents[1]
MAC=platform.system()=='Darwin' and Path('/usr/bin/sandbox-exec').is_file()


def test_no_silent_unsandboxed_fallback():
    with patch('faraday_manufacturing_benchmark.isolation.platform.system',return_value='Linux'):
        with pytest.raises(ValueError,match='will not fall back'):
            with isolated_agent(ROOT/'examples/supply_award_agent.py'):pass


def test_allowlist_cannot_include_evaluator_source():
    with pytest.raises(ValueError,match='expose evaluator'):profile('/tmp/stage','/')
    with pytest.raises(ValueError,match='expose evaluator'):profile('/tmp/stage',ROOT)
    with pytest.raises(ValueError,match='outside evaluator'):profile(ROOT/'runs/stage',sys.base_prefix)


@pytest.mark.skipif(not MAC,reason='requires live macOS sandbox-exec')
def test_real_boundary_with_unsandboxed_positive_controls():
    spec=importlib.util.spec_from_file_location('qualify_isolation',ROOT/'scripts/qualify_isolation.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    result=module.boundary_probes()
    assert result['passed']
    assert all(result['unsandboxed'][key]['allowed'] for key in module.DENIED)
    assert all(result['restricted'][key]['errno'] in (errno.EACCES,errno.EPERM) for key in module.DENIED)


@pytest.mark.skipif(not MAC,reason='requires live macOS sandbox-exec')
@pytest.mark.parametrize('track,task_id,source',[
 ('workflow','mfg-flow-precision_cnc-01-01','tests/workflow_qualification_policy.py'),
 *[('supply-chain',f'supply-source_award-{i:03d}','examples/supply_award_agent.py') for i in range(1,5)],
 ('procurement','p2p-compound_recovery-001','examples/procurement_agent.py'),
 ('sensors','sensor-vibration_order-normal','examples/vibration_agent.py'),
])
def test_public_contract_solves_in_restricted_process(track,task_id,source):
    catalog,*_=contracts(track);task=next(t for t in catalog() if t['id']==task_id)
    episode=run_task(track,task,ROOT/source,timeout=10)
    assert episode['result']['strict_success']
    assert replay_episode(track,task,episode)==episode['result']
    assert episode['isolation']['network']=='denied'


@pytest.mark.skipif(not MAC,reason='requires live macOS sandbox-exec')
def test_isolated_cli_artifact_uses_existing_replay_contract(tmp_path):
    path=tmp_path/'run.json'
    result=subprocess.run([sys.executable,'-m','faraday_manufacturing_benchmark','isolated','--track','supply-chain','--task','supply-source_award-001','--agent-file',str(ROOT/'examples/supply_award_agent.py'),'--output',str(path)],capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr
    artifact=json.loads(path.read_text())
    assert artifact['track']=='supply-chain' and artifact['episodes'][0]['isolation']['policy_version']=='macos-stdlib-offline/1'
    replayed=subprocess.run([sys.executable,'-m','faraday_manufacturing_benchmark','replay',str(path)],capture_output=True,text=True,timeout=15)
    assert replayed.returncode==0,replayed.stderr


@pytest.mark.skipif(not MAC,reason='requires live macOS sandbox-exec')
def test_agent_timeout_leaves_no_live_process(tmp_path):
    source=tmp_path/'wait.py';source.write_text('import time\ntime.sleep(20)\n')
    with isolated_agent(source,timeout=.1) as agent:
        with pytest.raises(ValueError,match='timed out'):agent.decide('probe',{})
    assert agent.process.poll() is not None


@pytest.mark.skipif(not MAC,reason='requires live macOS sandbox-exec')
def test_installed_package_layout_does_not_treat_tmp_as_private_root(tmp_path):
    import faraday_manufacturing_benchmark.isolation as module
    installed=tmp_path/'site-packages/faraday_manufacturing_benchmark/isolation.py'
    installed.parent.mkdir(parents=True);installed.write_text('# installed layout marker')
    with patch.object(module,'__file__',str(installed)):
        with isolated_agent(ROOT/'examples/supply_award_agent.py',timeout=5) as agent:
            assert agent.decide('supply_chain',{'last_result':None})['tool']=='wait'


def test_base_runtime_install_is_excluded_by_site_packages_rule(tmp_path):
    import faraday_manufacturing_benchmark.isolation as module
    installed=Path(sys.base_prefix)/'lib'/f'python{sys.version_info.major}.{sys.version_info.minor}'/'site-packages/faraday_manufacturing_benchmark/isolation.py'
    with patch.object(module,'__file__',str(installed)):
        text=profile('/tmp/faraday-public-stage',sys.base_prefix)
    assert 'require-not' in text and 'site-packages' in text
