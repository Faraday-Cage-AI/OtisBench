"""Pinned real hydraulic test-rig compatibility extension; no native case inflation.

UCI 447 / DOI 10.24432/C5CW21, CC BY 4.0. Public grouped development evaluation,
not a private workflow holdout or a claim of operational maintenance execution.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import io
import json
import math
from pathlib import Path
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
URL = 'https://archive.ics.uci.edu/static/public/447/condition+monitoring+of+hydraulic+systems.zip'
ARCHIVE_SHA = '24128aad2ee45eea7e6b63ebbd9992cdf25d0483a2cebefbfc13bc69079af1f2'
PROTOCOL = 'hydraulic-condition-development/1'
SENSORS = {**{f'PS{i}': dict(hz=100, units='bar') for i in range(1, 7)},
    'EPS1': dict(hz=100, units='W'), 'FS1': dict(hz=10, units='l/min'), 'FS2': dict(hz=10, units='l/min'),
    **{f'TS{i}': dict(hz=1, units='degC') for i in range(1, 5)}, 'VS1': dict(hz=1, units='mm/s')}
TARGETS = {'cooler': [3, 20, 100], 'valve': [73, 80, 90, 100], 'pump_leakage': [0, 1, 2], 'accumulator': [90, 100, 115, 130]}
STATS = ['mean', 'std', 'min', 'max', 'q25', 'median', 'q75', 'late_minus_early_mean']
FEATURE_NAMES = [sensor + ':' + stat for sensor in SENSORS for stat in STATS]


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''): h.update(chunk)
    return h.hexdigest()


def digest(value): return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def save(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n')


def read(path): return json.loads(Path(path).read_text())


def fetch(path):
    path = Path(path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.download')
        try:
            subprocess.run(['curl', '--fail', '--location', '--proto', '=https', '--tlsv1.2', '--max-time', '180', '--output', str(temp), URL], check=True)
            if sha(temp) != ARCHIVE_SHA: raise ValueError('upstream archive differs from pinned source')
            temp.replace(path)
        finally: temp.unlink(missing_ok=True)
    if sha(path) != ARCHIVE_SHA: raise ValueError('archive hash mismatch')
    return path


def partition(profiles):
    """All repeated occurrences of a four-component setting stay together."""
    groups = sorted({tuple(int(v) for v in row[:4]) for row in profiles}, key=lambda g: digest(['condition-combination-v1', list(g)]))
    train_end = int(len(groups) * .6); validation_end = train_end + int(len(groups) * .2)
    assignment = {group: 'train' if i < train_end else 'validation' if i < validation_end else 'test' for i, group in enumerate(groups)}
    return [assignment[tuple(int(v) for v in row[:4])] for row in profiles], assignment


def features(array):
    import numpy as np
    if array.ndim != 2 or not np.isfinite(array).all(): raise ValueError('nonfinite or invalid sensor matrix')
    half = array.shape[1] // 2
    return np.column_stack([array.mean(1), array.std(1), array.min(1), array.max(1),
        *np.quantile(array, [.25, .5, .75], axis=1), array[:, half:].mean(1) - array[:, :half].mean(1)])


def prepare(archive, destination):
    import numpy as np
    archive = fetch(archive); destination = Path(destination)
    if destination.exists(): raise ValueError('destination already exists; frozen splits are not overwritten')
    destination.mkdir(parents=True); public = destination / 'public'; private = destination / 'evaluator'; raw = private / 'raw'; raw.mkdir(parents=True)
    members = {}; matrices = []
    with zipfile.ZipFile(archive) as source:
        if len(set(source.namelist())) != len(source.namelist()): raise ValueError('duplicate archive members')
        profile_blob = source.read('profile.txt'); profiles = np.loadtxt(io.BytesIO(profile_blob), dtype=int)
        if profiles.shape != (2205, 5): raise ValueError('unexpected profile shape')
        for col, levels in enumerate(TARGETS.values()):
            if not set(profiles[:, col]).issubset(levels): raise ValueError('unknown source condition')
        if not set(profiles[:, 4]).issubset([0, 1]): raise ValueError('unknown stability annotation')
        members['profile.txt'] = hashlib.sha256(profile_blob).hexdigest()
        for name, spec in SENSORS.items():
            filename = name + '.txt'; blob = source.read(filename); members[filename] = hashlib.sha256(blob).hexdigest()
            array = np.loadtxt(io.BytesIO(blob), dtype=np.float64)
            if array.shape != (2205, spec['hz'] * 60): raise ValueError('sensor shape mismatch: ' + name)
            matrices.append(features(array))
            # Preserve source float64 values for raw read_stream calls; no downsampling.
            np.save(raw / (name + '.npy'), array, allow_pickle=False)
            del array, blob
        for name in ('description.txt', 'documentation.txt'):
            blob = source.read(name); members[name] = hashlib.sha256(blob).hexdigest(); (private / name).write_bytes(blob)
    x = np.column_stack(matrices); splits, groups = partition(profiles)
    public_rows = {name: [] for name in ('train', 'validation', 'test')}; truth = {}; counts = {}
    for index, (row, split, profile) in enumerate(zip(x, splits, profiles, strict=True)):
        key = 'cycle-' + digest(['hydraulic-public-development-v1', index])[:20]
        label = {target: int(profile[i]) for i, target in enumerate(TARGETS)}
        item = dict(id=key, features=row.tolist())
        if split != 'test': item['labels'] = label
        public_rows[split].append(item)
        truth[key] = dict(source_cycle_one_based=index + 1, labels=label, stability_flag=int(profile[4]), split=split)
    for split, rows in public_rows.items():
        rows.sort(key=lambda r: r['id']); save(public / (split + '.json'), rows)
        for target, levels in TARGETS.items():
            covered = {truth[r['id']]['labels'][target] for r in rows}
            if covered != set(levels): raise ValueError('split lacks target class: ' + split + '/' + target)
        counts[split] = dict(cycles=len(rows), groups=sum(v == split for v in groups.values()),
            stable_cycles=sum(truth[r['id']]['stability_flag'] == 0 for r in rows))
    policy = dict(protocol=PROTOCOL, dataset='UCI Condition monitoring of hydraulic systems', doi='10.24432/C5CW21',
        license='CC-BY-4.0', attribution='Helwig, Pignanelli and Schuetze (2015), UCI Machine Learning Repository; original hydraulic test-rig measurements.',
        task='Predict the four recorded component condition levels for each 60-second test-rig cycle. These are experiment condition annotations, not remaining-life labels or maintenance decisions.',
        target_levels=TARGETS, feature_names=FEATURE_NAMES, sensors=SENSORS,
        feature_definition='Per sensor: population mean/std, min/max, 25/50/75 percentiles and last-half minus first-half mean. Computed without labels or fitted preprocessing.',
        exclusions=['CE, CP and SE virtual/derived channels', 'stability flag as a predictor or target', 'cycle index and condition combination as predictors'],
        split_policy='All cycles with the same four-component condition combination share one partition. Group hashes determine 60/20/remaining percent group counts; class coverage checked, never tuned on scores.',
        limits=dict(calls_per_cycle=150, raw_samples_per_page=512, agent_cpu_seconds_total=60),
        limitations=['One publicly available hydraulic test rig; no plant/site generalization or private holdout claim.',
                     'Condition grouping reduces same-setting leakage but does not establish independent experiments or remove temporal drift.',
                     'Feature extraction uses a complete 60-second cycle; this is retrospective condition assessment, not early failure prediction.',
                     'Public source profiles permit lookup/memorization outside the local sandbox; not a contamination-proof benchmark.'])
    save(public / 'task.json', policy); save(private / 'truth.json', truth)
    save(private / 'split-groups.json', [{'condition': list(g), 'split': split} for g, split in groups.items()])
    manifest = dict(protocol=PROTOCOL, native_case_count_added=0, archive_sha256=ARCHIVE_SHA, source_url=URL,
        source_member_sha256=members, source_rows=2205, source_stable_rows=int((profiles[:, 4] == 0).sum()),
        physical_channels=len(SENSORS), features=len(FEATURE_NAMES), counts=counts,
        builder_sha256=sha(__file__), benchmark_release_manifest_sha256=sha(ROOT / 'manifest.json'),
        public_files={p.relative_to(public).as_posix(): sha(p) for p in sorted(public.rglob('*')) if p.is_file()},
        evaluator_files={p.relative_to(private).as_posix(): sha(p) for p in sorted(private.rglob('*')) if p.is_file()})
    save(destination / 'manifest.json', manifest); return manifest


def verify(destination):
    destination = Path(destination); manifest = read(destination / 'manifest.json')
    if manifest['protocol'] != PROTOCOL or manifest['archive_sha256'] != ARCHIVE_SHA: raise ValueError('source commitment mismatch')
    if manifest['builder_sha256'] != sha(__file__): raise ValueError('evaluator source changed')
    for directory, key in [('public', 'public_files'), ('evaluator', 'evaluator_files')]:
        root = destination / directory
        actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
        if actual != set(manifest[key]): raise ValueError('file inventory mismatch')
        for name, expected in manifest[key].items():
            path = (root / name).resolve()
            if not path.is_relative_to(root.resolve()) or sha(path) != expected: raise ValueError('file hash mismatch')
    return manifest


def validate_probabilities(probabilities):
    if not isinstance(probabilities, dict) or set(probabilities) != set(TARGETS): raise ValueError('target coverage mismatch')
    for target, levels in TARGETS.items():
        row = probabilities[target]
        if not isinstance(row, dict) or set(row) != {str(v) for v in levels}: raise ValueError('class coverage mismatch')
        if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in row.values()): raise ValueError('invalid probability')
        if not math.isclose(sum(row.values()), 1, rel_tol=0, abs_tol=1e-9): raise ValueError('probabilities do not sum to one')
    return probabilities


def metrics(truth, predictions):
    if not truth or set(predictions) != set(truth): raise ValueError('missing, extra or duplicate cycle coverage')
    result = {}; joint = 0
    for key, probabilities in predictions.items(): validate_probabilities(probabilities)
    for target, levels in TARGETS.items():
        confusion = {str(y): {str(p): 0 for p in levels} for y in levels}; loss = brier = correct = 0; bins = [[] for _ in range(10)]
        for key, expected in truth.items():
            row = predictions[key][target]; actual = expected['labels'][target]
            predicted = max(levels, key=lambda level: (row[str(level)], -level))
            confidence = row[str(predicted)]; hit = predicted == actual
            confusion[str(actual)][str(predicted)] += 1; correct += hit
            loss -= math.log(max(row[str(actual)], 1e-15))
            brier += sum((row[str(level)] - int(level == actual)) ** 2 for level in levels)
            bins[min(9, int(confidence * 10))].append((confidence, hit))
        recall = []; f1 = []; supports = {}
        for level in levels:
            k = str(level); tp = confusion[k][k]; support = sum(confusion[k].values()); predicted_count = sum(row[k] for row in confusion.values()); supports[k] = support
            if support: recall.append(tp / support)
            f1.append(2 * tp / (support + predicted_count) if support + predicted_count else 0)
        ece = sum(len(bucket) / len(truth) * abs(sum(c for c, _ in bucket) / len(bucket) - sum(hit for _, hit in bucket) / len(bucket)) for bucket in bins if bucket)
        result[target] = dict(accuracy=correct / len(truth), balanced_accuracy=sum(recall) / len(recall), macro_f1=sum(f1) / len(f1),
            log_loss=loss / len(truth), multiclass_brier=brier / len(truth), ece_10_bins=ece, support=supports, confusion=confusion)
    for key, expected in truth.items():
        joint += all(max(levels, key=lambda level: (predictions[key][target][str(level)], -level)) == expected['labels'][target] for target, levels in TARGETS.items())
    return dict(cycles=len(truth), joint_exact_accuracy=joint / len(truth), targets=result)


def run(destination, agent_file, output, method='knn', timeout=120):
    import numpy as np
    from faraday_manufacturing_benchmark.isolation import isolated_agent
    destination = Path(destination); manifest = verify(destination); public = destination / 'public'
    policy = read(public / 'task.json'); train = read(public / 'train.json'); test = read(public / 'test.json')
    # Labels, source cycle order and source raw arrays remain host-side throughout agent execution.
    all_truth = read(destination / 'evaluator/truth.json'); truth = {r['id']: all_truth[r['id']] for r in test}
    arrays = {sensor: np.load(destination / 'evaluator/raw' / (sensor + '.npy'), mmap_mode='r', allow_pickle=False) for sensor in SENSORS}
    predictions = {}; trace = []; started = time.monotonic()
    try:
        with isolated_agent(agent_file, timeout=timeout) as agent:
            ready = agent.decide('hydraulic_condition', dict(phase='fit', method=method, task=policy, training_rows=train))
            if ready != {'ready': True}: raise ValueError('agent failed training acknowledgement')
            isolation = agent.isolation
            for item in test:
                payload = dict(phase='predict', case=item, tools=dict(read_stream=dict(sensor='issued physical channel', cursor='zero-based integer', limit='1..512'), predict=dict(probabilities='all four class probability dictionaries')))
                for call in range(policy['limits']['calls_per_cycle']):
                    decision = agent.decide('hydraulic_condition', payload)
                    if set(decision) != {'tool', 'arguments'} or not isinstance(decision['arguments'], dict): raise ValueError('invalid decision schema')
                    if decision['tool'] == 'predict':
                        if set(decision['arguments']) != {'probabilities'}: raise ValueError('invalid prediction arguments')
                        probabilities = validate_probabilities(decision['arguments']['probabilities']); predictions[item['id']] = probabilities
                        trace.append(dict(case_id=item['id'], decision=decision)); break
                    elif decision['tool'] == 'read_stream':
                        args = decision['arguments']
                        if set(args) != {'sensor', 'cursor', 'limit'}: raise ValueError('invalid stream arguments')
                        sensor, cursor, limit = args['sensor'], args['cursor'], args['limit']
                        if not isinstance(sensor, str) or sensor not in arrays or type(cursor) is not int or type(limit) is not int or not 0 <= cursor < 60 * SENSORS[sensor]['hz'] or not 1 <= limit <= 512: raise ValueError('invalid stream page')
                        row = arrays[sensor][truth[item['id']]['source_cycle_one_based'] - 1]; end = min(len(row), cursor + limit)
                        observation = dict(sensor=sensor, cursor=cursor, samples=row[cursor:end].tolist(), next_cursor=end if end < len(row) else None, **SENSORS[sensor])
                        trace.append(dict(case_id=item['id'], decision=decision, observation=observation))
                        payload = dict(phase='predict', case=item, last_result=observation, calls_remaining=policy['limits']['calls_per_cycle'] - call - 1)
                    else: raise ValueError('unknown tool')
                else: raise ValueError('cycle call budget exhausted')
    except Exception as exc:
        save(output, dict(protocol=PROTOCOL, status='failed-no-complete-score', error_type=type(exc).__name__,
            source_manifest_sha256=sha(destination / 'manifest.json'), evaluator_sha256=sha(__file__),
            agent_sha256=sha(agent_file), expected_test_cycles=len(test), completed_test_cycles=len(predictions),
            predictions=predictions, trace=trace, wall_seconds=time.monotonic() - started,
            limitation='Unanswered cycles cannot be excluded to report a complete evaluation score.'))
        raise
    # No per-cycle ground truth, grading signal or test feedback is sent to the agent.
    elapsed = time.monotonic() - started; score = metrics(truth, predictions)
    strata = {}
    for flag, label in [(0, 'stable'), (1, 'possibly_unstable')]:
        selected = {key: value for key, value in truth.items() if value['stability_flag'] == flag}
        if selected: strata[label] = metrics(selected, {key: predictions[key] for key in selected})
    report = dict(protocol=PROTOCOL, status='complete', method=method, source_manifest_sha256=sha(destination / 'manifest.json'),
        evaluator_sha256=sha(__file__), agent_sha256=sha(agent_file), isolation=isolation,
        public_input_sha256=manifest['public_files'], benchmark_scope='Separate real test-rig condition classification extension; not an LLM or native-track score.',
        wall_seconds=elapsed, provider_cost_usd=0, train_cycles=len(train), test_cycles=len(test), metrics=score, stability_strata=strata,
        predictions=predictions, trace=trace, limitations=policy['limitations'])
    save(output, report); return report


def replay(destination, episode):
    import numpy as np
    destination = Path(destination); manifest = verify(destination); report = read(episode)
    if report['source_manifest_sha256'] != sha(destination / 'manifest.json') or report['evaluator_sha256'] != sha(__file__): raise ValueError('episode source mismatch')
    truth = {k: v for k, v in read(destination / 'evaluator/truth.json').items() if v['split'] == 'test'}
    if metrics(truth, report['predictions']) != report['metrics']: raise ValueError('prediction grading mismatch')
    predicted_rows = [row for row in report['trace'] if row['decision']['tool'] == 'predict']
    if len(predicted_rows) != len(truth): raise ValueError('duplicate or missing prediction trace')
    predicted = {row['case_id']: row['decision']['arguments']['probabilities'] for row in predicted_rows}
    if predicted != report['predictions']: raise ValueError('trace predictions mismatch')
    for flag, label in [(0, 'stable'), (1, 'possibly_unstable')]:
        selected = {key: value for key, value in truth.items() if value['stability_flag'] == flag}
        if selected and metrics(selected, {key: report['predictions'][key] for key in selected}) != report['stability_strata'][label]:
            raise ValueError('stability stratum grading mismatch')
    arrays = {}
    for row in report['trace']:
        if row['case_id'] not in truth: raise ValueError('unknown trace cycle')
        if row['decision']['tool'] == 'predict': continue
        if row['decision']['tool'] != 'read_stream': raise ValueError('unknown trace tool')
        args = row['decision']['arguments']; sensor = args['sensor']
        if sensor not in arrays: arrays[sensor] = np.load(destination / 'evaluator/raw' / (sensor + '.npy'), mmap_mode='r', allow_pickle=False)
        raw = arrays[sensor][truth[row['case_id']]['source_cycle_one_based'] - 1]
        cursor, limit = args['cursor'], args['limit']; end = min(len(raw), cursor + limit)
        expected = dict(sensor=sensor, cursor=cursor, samples=raw[cursor:end].tolist(), next_cursor=end if end < len(raw) else None, **SENSORS[sensor])
        if row['observation'] != expected: raise ValueError('raw stream observation mismatch')
    return dict(passed=True, test_cycles=len(truth), scope='Retained-prediction metric regrade and source integrity; not an agent rerun.')


def main():
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='command', required=True)
    get = sub.add_parser('fetch'); get.add_argument('--archive', default='runs/hydraulic-uci-447.zip')
    prep = sub.add_parser('prepare'); prep.add_argument('--archive', default='runs/hydraulic-uci-447.zip'); prep.add_argument('--output', required=True)
    execute = sub.add_parser('run'); execute.add_argument('--input', required=True); execute.add_argument('--agent-file', required=True); execute.add_argument('--method', choices=['knn', 'majority'], default='knn'); execute.add_argument('--output', required=True)
    check = sub.add_parser('regrade'); check.add_argument('--input', required=True); check.add_argument('--episode', required=True)
    args = parser.parse_args()
    if args.command == 'fetch': print(fetch(args.archive))
    elif args.command == 'prepare': print(json.dumps(prepare(args.archive, args.output)['counts']))
    elif args.command == 'regrade': print(json.dumps(replay(args.input, args.episode)))
    else:
        report = run(args.input, args.agent_file, args.output, args.method)
        print(json.dumps(dict(method=report['method'], test_cycles=report['test_cycles'], joint_exact_accuracy=report['metrics']['joint_exact_accuracy'], wall_seconds=report['wall_seconds'])))


if __name__ == '__main__': main()
