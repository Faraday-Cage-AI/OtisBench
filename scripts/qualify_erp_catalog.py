"""Resumable full-catalog upstream ERP controls, with every attempt retained.

One representative per pinned pattern runs before remaining parameter instances.
This is compatibility qualification of upstream oracles, not native/model counts.
"""
from __future__ import annotations
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import threading
import time
import tomllib
import uuid
from faraday_manufacturing_benchmark import erp_compat as erp

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / 'runs/comparator-audit/2026-11-01'
IMAGE = 'sha256:a139de727cd008529c7448a807bbb64ebef4a0bde424c140efec23534d825d09'
LOCK = threading.Lock()
STOP = threading.Event()
PROTOCOL = 'erp-full-catalog-controls/2-fixtures'


def utc(): return datetime.now(timezone.utc).isoformat()


def read(path): return json.loads(Path(path).read_text())


def atomic(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)


def blob_sha(value): return hashlib.sha1(b'blob ' + str(len(value)).encode() + b'\0' + value).hexdigest()


def catalog(tree, config):
    paths = {r['path']: r for r in tree['tree'] if r['type'] == 'blob'}
    if tree.get('truncated') is not False: raise ValueError('truncated source tree')
    source = 'erp_bench/procurement/examples/diverse_300_dataset.toml'
    config_blob = (CACHE / 'erp-dataset.source').read_bytes()
    if source not in paths or blob_sha(config_blob) != paths[source]['sha']: raise ValueError('dataset config is not the pinned Git blob')
    tasks = sorted(p.split('/')[1] for p in paths if p.startswith('tasks/') and p.endswith('/task.toml'))
    if len(tasks) != 300 or len(set(tasks)) != 300: raise ValueError('unexpected upstream catalog coverage')
    rows = []; offset = 0
    for entry in config['entries']:
        pattern = Path(entry['config']).stem; count = entry['count']; selected = tasks[offset:offset + count]
        if type(count) is not int or count <= 0 or len(selected) != count or any(not t.endswith('_' + pattern) for t in selected): raise ValueError('pattern config/task directory mismatch')
        for index, task in enumerate(selected):
            if int(task[:4]) != config['start_number'] + offset + index: raise ValueError('noncontiguous task numbering')
            rows.append(dict(task_id=task, pattern=pattern, representative=index == 0))
        offset += count
    if offset != len(tasks) or len(config['entries']) != 29: raise ValueError('pattern counts do not cover catalog')
    return sorted(rows, key=lambda row: (not row['representative'],not row['pattern'].startswith('repair_plan_'),row['task_id']))


def fingerprints():
    files = [Path(__file__), CACHE / 'erp-dataset.source', CACHE / 'erp-tree.json']
    files += [ROOT / 'src/faraday_manufacturing_benchmark' / name for name in ['erp_compat.py', 'erp_protocol.py', 'agents.py', 'isolation.py']]
    return {str(path.relative_to(ROOT)): erp.sha(path) for path in files}


def plan():
    tree = read(CACHE / 'erp-tree.json'); config = tomllib.loads((CACHE / 'erp-dataset.source').read_text())
    rows = catalog(tree, config)
    dockerfiles = {r['sha'] for r in tree['tree'] if r['type'] == 'blob' and r['path'].startswith('tasks/') and r['path'].endswith('/environment/Dockerfile')}
    if len(dockerfiles) != 1: raise ValueError('catalog requires more than the declared shared runtime recipe')
    return dict(protocol=PROTOCOL, upstream_revision=erp.REVISION, upstream_catalog_cases=300, upstream_patterns=29,
        image_id=IMAGE, selected_cases=rows, source_sha256=fingerprints(), native_case_count_added=0,
        ordering='Repair representatives first, then one representative of every other pattern, then remaining instances with repair variants first.',
        fixture_contract='odoo-baseline/2 captures declared private repair metadata; known legacy nonrepair snapshots remain projection-checked.',
        control='Pinned private upstream oracle versus no-op on separate fresh restored baselines. No public agent/model inference.',
        runtime='Previously captured local immutable Odoo compatibility image; per-case unmodified fixture initialization, network none, 3 CPU/4 GiB each. Cron disabled. Clock not virtualized.',
        source_tree_sha256=erp.sha(CACHE / 'erp-tree.json'), dataset_config_sha256=erp.sha(CACHE / 'erp-dataset.source'))


def materialize(task, destination, tree):
    root = destination / 'source' / task; cache = destination / 'git-blobs'; cache.mkdir(parents=True, exist_ok=True)
    prefix = 'tasks/' + task + '/'; rows = [r for r in tree['tree'] if r['type'] == 'blob' and r['path'].startswith(prefix)]
    hashes = {}
    for row in rows:
        name = row['path'][len(prefix):]; path = root / name
        if Path(name).is_absolute() or '..' in Path(name).parts: raise ValueError('unsafe task path')
        blob = cache / row['sha']
        with LOCK:
            if not blob.exists():
                priors = [ROOT/'runs/erp-compat/source'/task/name,ROOT/'runs/erp-catalog-v1/git-blobs'/row['sha']]
                prior=next((path for path in priors if path.is_file() and blob_sha(path.read_bytes())==row['sha']),None)
                if prior is not None:
                    blob.write_bytes(prior.read_bytes())
                else:
                    temp = blob.with_suffix('.download')
                    try:
                        erp.fetch('https://raw.githubusercontent.com/agentic-labs/erp-bench/' + erp.REVISION + '/' + row['path'], temp)
                        if blob_sha(temp.read_bytes()) != row['sha']: raise ValueError('Git blob mismatch')
                        temp.replace(blob)
                    finally: temp.unlink(missing_ok=True)
            value = blob.read_bytes()
        if blob_sha(value) != row['sha']: raise ValueError('cached Git blob mismatch')
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != value: raise ValueError('changed materialized source')
        if not path.exists(): path.write_bytes(value)
        hashes[name] = erp.sha(path)
    atomic(root / 'source-manifest.json', dict(upstream=erp.UPSTREAM, commit=erp.REVISION, task_id=task, files=hashes))
    return root


def checked_row(path, row, frozen):
    value = read(path)
    if value['task_id'] != row['task_id'] or value['pattern'] != row['pattern'] or value['plan_sha256'] != erp.digest(frozen): raise ValueError('case receipt provenance differs from frozen plan')
    for name, expected in value['artifacts'].items():
        target = (ROOT / name).resolve()
        if not target.is_relative_to(ROOT) or erp.sha(target) != expected: raise ValueError('case receipt artifact changed')
    if value['status'] == 'complete':
        snapshot = read(ROOT / value['snapshot_manifest'])
        erp.check_source(snapshot['case_dir'])
        for label in ('noop', 'reference'):
            reward = read(Path(path).parent / label / 'verifier/reward.json')
            if value[label] != dict(upstream_score=reward['overall_score'], upstream_passed=reward['passed'], verifier=reward):
                raise ValueError('case verdict differs from retained verifier')
        expected_qualified = not value['noop']['upstream_passed'] and value['reference']['upstream_passed'] and value['reference_exit_code'] == 0
        if value['qualified'] is not expected_qualified: raise ValueError('case qualified flag contradicts controls')
    elif value['status'] != 'failed' or value['qualified'] is not False:
        raise ValueError('nonterminal or inconsistent retained case status')
    return value


def task_control(row, destination, frozen, tree):
    started = time.monotonic(); key = row['task_id']; out = destination / 'cases' / key; out.mkdir(parents=True, exist_ok=True)
    receipt = out / 'receipt.json'
    if receipt.exists(): return checked_row(receipt, row, frozen)
    if STOP.is_set(): return None
    value = dict(**row, plan_sha256=erp.digest(frozen), started_utc=utc(), status='running', artifacts={})
    atomic(out / 'status.json', value)
    try:
        if shutil.disk_usage(ROOT).free < 1024 ** 3:
            STOP.set()
            raise ValueError('less than 1 GiB free; no further ERP snapshots created')
        case = materialize(key, destination, tree)
        metadata = tomllib.loads((case / 'task.toml').read_text())['metadata']
        if metadata['task_pattern'] != row['pattern']: raise ValueError('task metadata pattern mismatch')
        value['metadata'] = {k: metadata[k] for k in ('scenario_number', 'difficulty', 'task_pattern', 'objective_kind') if k in metadata}
        snapshot = destination / 'baselines' / key
        # Reuse only previously frozen, exact-source snapshots for the original three cases.
        candidates=[ROOT/'runs/erp-compat/baselines'/alias for alias in ('2000-v1','2064-v1','2160-v1')]
        candidates.append(ROOT/'runs/erp-catalog-v1/baselines'/key)
        for candidate in candidates:
            if candidate.joinpath('manifest.json').is_file():
                m = read(candidate / 'manifest.json')
                if m['upstream']['task_id'] == key and m['image_id'] == IMAGE and m['upstream']['files'] == read(case / 'source-manifest.json')['files']:
                    try:erp.snapshot_contract(m)
                    except ValueError:continue
                    snapshot = candidate; case = Path(m['case_dir']); break
        value['stage'] = 'prepare'; atomic(out / 'status.json', value)
        if not (snapshot / 'manifest.json').exists(): erp.prepare(case, snapshot, IMAGE)
        manifest = read(snapshot / 'manifest.json')
        if manifest['image_id'] != IMAGE or manifest['upstream']['task_id'] != key: raise ValueError('snapshot identity mismatch')
        value['snapshot_manifest'] = str((snapshot / 'manifest.json').relative_to(ROOT))
        value['stage'] = 'noop'; atomic(out / 'status.json', value)
        with erp.restored(snapshot) as (container, bridge, loaded):
            before = erp.probe(bridge); noop = erp.grade(container, case, out / 'noop')
            value['noop_restoration']=loaded['restoration']
        value['noop'] = noop
        value['stage'] = 'reference'; atomic(out / 'status.json', value)
        with erp.restored(snapshot) as (container, bridge, loaded):
            container.copy_in(case / 'solution', '/solution')
            execution = subprocess.run(['docker', 'exec', container.cid, 'bash', '/solution/solve.sh'], capture_output=True, timeout=240)
            (out / 'reference-execution.log').write_bytes(execution.stdout + execution.stderr)
            after = erp.probe(bridge); reference = erp.grade(container, case, out / 'reference')
            value['reference_exit_code'] = execution.returncode
            value['reference_restoration']=loaded['restoration']
        value.update(reference=reference,
            baseline_state_digest=manifest['baseline_state_digest'], final_business_digest=erp.digest(after),
            business_row_counts={model: dict(before=len(before[model]), after=len(after[model])) for model in before},
            qualified=not noop['upstream_passed'] and reference['upstream_passed'] and execution.returncode == 0,
            status='complete', stage='terminal')
        erp.save(out / 'before-business-state.json', before); erp.save(out / 'after-business-state.json', after)
        paths = [snapshot / 'manifest.json', case / 'source-manifest.json']
        paths += [snapshot / name for name in manifest['files']]
        paths += [p for p in out.rglob('*') if p.is_file() and p.name not in ('status.json', 'receipt.json')]
        value['artifacts'] = {str(path.relative_to(ROOT)): erp.sha(path) for path in sorted(set(paths))}
    except Exception as exc:
        value.update(status='failed', stage=value.get('stage', 'materialize'), qualified=False, error_type=type(exc).__name__, error=str(exc))
        paths = [p for p in out.rglob('*') if p.is_file() and p.name not in ('status.json', 'receipt.json')]
        value['artifacts'] = {str(path.relative_to(ROOT)): erp.sha(path) for path in paths}
    value['finished_utc'] = utc(); value['wall_seconds'] = time.monotonic() - started
    atomic(receipt, value); atomic(out / 'status.json', value)
    print(json.dumps(dict(task=key, pattern=row['pattern'], status=value['status'], qualified=value['qualified'], noop=value.get('noop', {}).get('upstream_score'), reference=value.get('reference', {}).get('upstream_score'), wall_seconds=round(value['wall_seconds'], 2))), flush=True)
    return value


def summary(frozen, rows, status):
    selected = frozen['selected_cases']; byid = {r['task_id']: r for r in rows}; patterns = {}
    known = {r['task_id']: r['pattern'] for r in selected}
    if len(byid) != len(rows) or any(r['task_id'] not in known or r['pattern'] != known[r['task_id']] or type(r['qualified']) is not bool for r in rows):
        raise ValueError('duplicate, unknown or invalid case verdict')
    for case in selected:
        p = patterns.setdefault(case['pattern'], dict(selected=0, resolved=0, qualified=0, failed_tasks=[])); p['selected'] += 1
        if case['task_id'] in byid:
            r = byid[case['task_id']]; p['resolved'] += 1; p['qualified'] += bool(r['qualified'])
            if not r['qualified']: p['failed_tasks'].append(case['task_id'])
    return dict(protocol=PROTOCOL, status=status, upstream_revision=erp.REVISION,
        plan_sha256=erp.digest(frozen), catalog_cases=300, patterns_total=29,
        selected_cases=len(selected), resolved_cases=len(rows), qualified_cases=sum(bool(r['qualified']) for r in rows),
        failed_cases=[r['task_id'] for r in rows if not r['qualified']],
        patterns_with_qualified_case=sum(p['qualified'] > 0 for p in patterns.values()), patterns=patterns,
        full_catalog_qualified=len(rows) == 300 and all(r['qualified'] for r in rows),
        native_case_count_added=0, model_runs=0, last_updated_utc=utc(),
        rows=[dict(task_id=r['task_id'], pattern=r['pattern'], status=r['status'], qualified=r['qualified'], reference_score=r.get('reference', {}).get('upstream_score')) for r in sorted(rows, key=lambda r: r['task_id'])],
        limitations=['Pinned upstream oracle qualification, not public-information model performance.', 'No claim of native authored cases, independent practitioner review or structurally private holdouts.', 'Clock is not virtualized; fresh baseline projection is checked for every restored control, but no full public-action replay is claimed.', 'Previously built compatibility image and local SQL/filestore/source artifacts must be retained.'])


def execute(destination, report, workers=2, limit=None):
    destination = Path(destination).resolve(); report = Path(report).resolve(); destination.mkdir(parents=True, exist_ok=True)
    if not destination.is_relative_to(ROOT) or not report.is_relative_to(ROOT): raise ValueError('run artifacts must remain in the declared checkout')
    if workers not in (1, 2): raise ValueError('one or two workers supported')
    # An advisory process lock prevents two drivers from owning this same campaign.
    import fcntl
    with (destination / 'driver.lock').open('a+') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise ValueError('campaign already has a live driver lock')
        frozen = plan(); plan_path = destination / 'plan.json'
        if plan_path.exists() and read(plan_path) != frozen: raise ValueError('campaign plan/source changed; preserve this campaign and use a new version')
        if not plan_path.exists(): atomic(plan_path, frozen)
        expected_image = erp.command(['docker', 'image', 'inspect', '--format', '{{.Id}}', IMAGE]).stdout.decode().strip()
        if expected_image != IMAGE: raise ValueError('immutable runtime missing')
        tree = read(CACHE / 'erp-tree.json'); rows = []; pending = []
        for row in frozen['selected_cases']:
            receipt = destination / 'cases' / row['task_id'] / 'receipt.json'
            if receipt.exists(): rows.append(checked_row(receipt, row, frozen))
            else: pending.append(row)
        if limit is not None: pending = pending[:limit]
        atomic(destination / 'driver.json', dict(pid=os.getpid(), started_utc=utc(), workers=workers, plan_sha256=erp.digest(frozen)))
        atomic(report, summary(frozen, rows, 'running'))
        def request_stop(signum, frame): STOP.set()
        signal.signal(signal.SIGTERM, request_stop); signal.signal(signal.SIGINT, request_stop)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(task_control, row, destination, frozen, tree): row for row in pending}
            for future in as_completed(futures):
                row = future.result()
                if row is not None: rows.append(row)
                atomic(report, summary(frozen, rows, 'stopping' if STOP.is_set() else 'running'))
        result = summary(frozen, rows, 'complete' if len(rows) == 300 else 'interrupted' if STOP.is_set() else 'partial')
        atomic(report, result); print(json.dumps({k: result[k] for k in ('status', 'resolved_cases', 'qualified_cases', 'patterns_with_qualified_case', 'full_catalog_qualified')}), flush=True)
        return result


def main():
    p = argparse.ArgumentParser(description=__doc__); sub = p.add_subparsers(dest='command', required=True)
    planning = sub.add_parser('plan'); planning.add_argument('--output', default='reports/erp-catalog-plan.json')
    run = sub.add_parser('run'); run.add_argument('--run-dir', default='runs/erp-catalog-v2'); run.add_argument('--report', default='reports/erp-catalog-qualification.json'); run.add_argument('--workers', type=int, default=2); run.add_argument('--limit', type=int)
    args = p.parse_args()
    if args.command == 'plan':
        value = plan(); atomic(args.output, value); print(json.dumps(dict(cases=300, patterns=29, image_id=IMAGE)))
    else: execute(args.run_dir, args.report, args.workers, args.limit)


if __name__ == '__main__': main()
