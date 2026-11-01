"""Fresh-fixture unchanged reference reproduction; preserves campaign verdicts."""
import argparse
import json
from pathlib import Path
import subprocess
import time
from faraday_manufacturing_benchmark import erp_compat as erp
ROOT = Path(__file__).resolve().parents[1]


def reproduce(receipt_path, output):
    receipt_path = Path(receipt_path).resolve(); output = Path(output).resolve()
    if not receipt_path.is_relative_to(ROOT) or not output.is_relative_to(ROOT): raise ValueError('artifacts must be inside checkout')
    if output.exists(): raise ValueError('refusing to overwrite retained reproduction')
    receipt = json.loads(receipt_path.read_text())
    for name, expected in receipt['artifacts'].items():
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT) or erp.sha(path) != expected: raise ValueError('campaign evidence changed')
    snapshot = (ROOT / receipt['snapshot_manifest']).parent
    manifest = json.loads((snapshot / 'manifest.json').read_text()); case = Path(manifest['case_dir'])
    erp.check_source(case); output.mkdir(parents=True); start = time.monotonic()
    source = ROOT / 'src/faraday_manufacturing_benchmark/erp_compat.py'; source_hash = erp.sha(source)
    with erp.restored(snapshot) as (container, bridge, loaded):
        before = erp.probe(bridge); container.copy_in(case / 'solution', '/solution')
        execution = subprocess.run(['docker', 'exec', container.cid, 'bash', '/solution/solve.sh'], capture_output=True, timeout=240)
        (output / 'reference-execution.log').write_bytes(execution.stdout + execution.stderr)
        after = erp.probe(bridge); result = erp.grade(container, case, output / 'reference')
        erp.save(output / 'before-business-state.json', before); erp.save(output / 'after-business-state.json', after)
    if erp.sha(source) != source_hash: raise ValueError('adapter source changed during reproduction')
    report = dict(task_id=receipt['task_id'], original_receipt=str(receipt_path.relative_to(ROOT)), original_receipt_sha256=erp.sha(receipt_path),
        snapshot_manifest_sha256=erp.sha(snapshot / 'manifest.json'), adapter_sha256=source_hash,
        reference_exit_code=execution.returncode, result=result, original_result=receipt['reference'],
        exact_verifier_result=result == receipt['reference'], exact_reference_exit=execution.returncode == receipt['reference_exit_code'],
        exact_initial_business_state=erp.digest(before) == receipt['baseline_state_digest'],
        restoration=loaded['restoration'], wall_seconds=time.monotonic()-start,
        scope='One unchanged private reference on a fresh verified fixture. No new agent score, upstream modification or campaign verdict replacement.',
        artifacts={str(p.relative_to(ROOT)): erp.sha(p) for p in output.rglob('*') if p.is_file()})
    erp.save(output / 'reproduction.json', report)
    return {k: report[k] for k in ('task_id', 'reference_exit_code', 'exact_verifier_result', 'exact_initial_business_state')}


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--receipt', required=True); p.add_argument('--output', required=True); a = p.parse_args()
    print(json.dumps(reproduce(a.receipt, a.output)))

if __name__ == '__main__': main()
