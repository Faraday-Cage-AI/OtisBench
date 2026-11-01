"""Collect a completed, controlled one-case Odoo smoke test without new mutations.

Reads retained verifier outputs and the stopped owned container's source files.
This is a compatibility smoke receipt, never full upstream/native qualification.
"""
from pathlib import Path
import hashlib
import json
import re
import subprocess
ROOT=Path(__file__).resolve().parents[1]
CACHE=ROOT/'runs/comparator-audit/2026-11-01'
COMMIT='ceba3880af555129b5278e056a0c20f2fb5a0ba9'
TASK='2000_easy_01_buy_only_baseline'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    cid=(CACHE/'erp-container-id.txt').read_text().strip();inspected=json.loads(subprocess.run(['docker','inspect',cid],capture_output=True,text=True,check=True).stdout)[0]
    if inspected['Config']['Labels'].get('faraday.benchmark.upstream')!='erp-ceba3880af55':raise ValueError('container is not the owned upstream test fixture')
    if inspected['State']['Running']:raise ValueError('collect final evidence after stopping the test fixture')
    tree=json.loads((CACHE/'erp-tree.json').read_text());prefix='tasks/'+TASK+'/';source_hashes={}
    for row in tree['tree']:
        if row['type']!='blob' or not row['path'].startswith(prefix):continue
        relative=row['path'][len(prefix):];path=CACHE/'erp-sample'/relative;blob=path.read_bytes()
        if hashlib.sha1(b'blob '+str(len(blob)).encode()+b'\0'+blob).hexdigest()!=row['sha']:raise ValueError('upstream source drift: '+relative)
        source_hashes[relative]=sha(path)
    original=(CACHE/'erp-sample/environment/Dockerfile').read_text();overlay=(CACHE/'erp-overlay/environment/Dockerfile').read_text()
    if overlay!=original.replace('RUN uv pip install --system --no-cache','ENV UV_BREAK_SYSTEM_PACKAGES=1\n\nRUN uv pip install --system --no-cache'):raise ValueError('unexpected runtime overlay')
    attested=CACHE/'erp-container-source';attested.mkdir(exist_ok=True);checks={}
    paths={'tests/test.sh':'/tests/test.sh','tests/checks.py':'/tests/checks.py','solution/solve.sh':'/solution/solve.sh','solution/solver.py':'/solution/solver.py','solution/optimal_plan.json':'/solution/optimal_plan.json','environment/entrypoint.sh':'/usr/local/bin/harbor-entrypoint.sh','environment/odoo.conf':'/etc/odoo/odoo.conf'}
    for relative,inside in paths.items():
        path=attested/relative;path.parent.mkdir(parents=True,exist_ok=True);subprocess.run(['docker','cp',cid+':'+inside,str(path)],capture_output=True,check=True);checks[relative]=sha(path)==source_hashes[relative]
    if not all(checks.values()):raise ValueError('container business/oracle/verifier code changed')
    verdicts={name:json.loads((CACHE/f'erp-{name}/reward.json').read_text()) for name in ('noop','oracle','mutated')}
    mutation=(CACHE/'erp-mutation.log').read_text();before=json.loads(next(line.split('PRE_MUTATION_RECORDS:',1)[1] for line in mutation.splitlines() if line.startswith('PRE_MUTATION_RECORDS:')));changed=json.loads(next(line.split('MUTATION_RESULT:',1)[1] for line in mutation.splitlines() if line.startswith('MUTATION_RESULT:')))
    passed=not verdicts['noop']['passed'] and verdicts['oracle']['passed'] and not verdicts['mutated']['passed'] and bool(changed['cancelled_purchase_order_ids']) and all(s=='cancel' for s in changed['states'])
    paths=[CACHE/'erp-build.log',CACHE/'erp-overlay-build.log',CACHE/'erp-runtime-overlay.json',CACHE/'erp-runtime-identity.json',CACHE/'erp-runtime-versions.json',CACHE/'erp-mutation.py',CACHE/'erp-mutation.log',CACHE/'erp-post-mutation.dump']+[CACHE/f'erp-{name}/reward.json' for name in verdicts]
    paths.extend(attested.rglob('*'));paths=[p for p in paths if p.is_file()]
    digests=sorted(set(re.findall(r'(?:docker.io/library/odoo:19|ghcr.io/astral-sh/uv:latest)@sha256:[a-f0-9]{64}',(CACHE/'erp-overlay-build.log').read_text())))
    report=dict(schema='erp-upstream-smoke/1',upstream_commit=COMMIT,task_id=TASK,selected_tasks=1,publisher_catalog_tasks=300,full_suite_qualified=False,native_faraday_track=False,controlled_smoke_passed=passed,
        original_build_passed=False,original_build_failure='externally managed Python rejected uv system install',runtime_overlay=json.loads((CACHE/'erp-runtime-overlay.json').read_text()),runtime=json.loads((CACHE/'erp-runtime-identity.json').read_text()),resolved_base_images=digests,container_stopped=not inspected['State']['Running'],
        source_files=source_hashes,container_source_matches=checks,pre_mutation_records=before,mutation=changed,verdicts={name:dict(score=v['overall_score'],passed=v['passed'],constraint=v['constraint'],hygiene=v['hygiene']) for name,v in verdicts.items()},
        artifacts={str(p.relative_to(ROOT)):sha(p) for p in sorted(paths)},collector_sha256=sha(Path(__file__)),limitations=['One easy buy-only case, not all 29 patterns or 300 tasks.','Disclosed container compatibility environment setting; original unmodified Dockerfile failed locally.','Reference controls, not a model run or native ERP adapter.','No claim of complete ERP reset/replay or cross-benchmark model performance.','Source/task/verifier files are pinned; actual runtime image and package identities are recorded.'])
    (ROOT/'reports/erp-upstream-smoke.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps(dict(controlled_smoke_passed=passed,verdicts=report['verdicts'],source_files=len(source_hashes),container_code_matches=all(checks.values()))));return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
