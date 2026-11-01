"""Prepare public-only sampled review inputs and freeze unverified reviewer submissions.

No grading, reference solving, human identity verification, or external messaging.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = 'faraday-practitioner-review/1'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def read(path):
    return json.loads(Path(path).read_text())


def verify(public):
    public = Path(public)
    manifest = read(public / 'manifest.json')
    if manifest['protocol'] != PROTOCOL:
        raise ValueError('unsupported review protocol')
    expected = set(manifest['files'])
    actual = {p.relative_to(public).as_posix() for p in public.rglob('*') if p.is_file()} - {'manifest.json'}
    if actual != expected:
        raise ValueError('public review file inventory mismatch')
    for name, digest in manifest['files'].items():
        path = Path(name)
        if path.is_absolute() or '..' in path.parts or public.joinpath(path).is_symlink():
            raise ValueError('unsafe public path')
        if sha(public / path) != digest:
            raise ValueError('public review file hash mismatch: ' + name)
    return manifest


def build(destination):
    from faraday_manufacturing_benchmark import __version__
    from faraday_manufacturing_benchmark.catalog import TASKS
    from faraday_manufacturing_benchmark.cli import workflow_catalog, workflows
    from faraday_manufacturing_benchmark.protocol import answer_schema
    from faraday_manufacturing_benchmark import cad, cad_cases, documents, document_cases
    from faraday_manufacturing_benchmark import shopfloor, shopfloor_views, supply_chain, supply_cases
    from faraday_manufacturing_benchmark import procurement, procurement_cases, sensors, sensor_cases
    from faraday_manufacturing_benchmark.season import CASES, FactorySeason
    from faraday_industrial_benchmark.models import IncidentTask

    destination = Path(destination)
    if destination.exists():
        raise ValueError('destination already exists; use a new review kit directory')
    public = destination / 'public'
    public.mkdir(parents=True)
    catalogs = {
        'engineering': TASKS, 'workflow': workflow_catalog(), 'supply-chain': supply_cases.catalog(),
        'procurement': procurement_cases.catalog(), 'sensors': sensor_cases.catalog(),
        'cad': cad_cases.catalog(), 'documents': document_cases.catalog(),
        'execution': workflows(), 'season': list(CASES),
    }
    cases, mapping = [], []
    for track, tasks in catalogs.items():
        for task in (tasks[0], tasks[-1]):
            key = f'R{len(cases) + 1:03d}'
            out = public / 'cases' / key
            out.mkdir(parents=True)
            scope = 'opening-snapshot-only'
            if track == 'engineering':
                # Deliberately omit family/domain, seeds, and grading tolerances.
                save(out / 'task.json', {k: task[k] for k in ('title', 'prompt', 'inputs', 'output_fields')})
                save(out / 'answer-schema.json', answer_schema(task))
                scope = 'independent-calculation'
            elif track == 'cad':
                cad.export_packet(task, out)
                scope = 'independent-geometry'
            elif track == 'documents':
                documents.export_packet(task, out)
                scope = 'independent-document-assessment'
            elif track == 'sensors':
                source = sensor_cases.build(task)
                save(out / 'task.json', sensors.public_task(task, key))
                save(out / 'asset.json', source['asset'])
                save(out / 'policy.json', source['policy'])
                save(out / 'stream.json', {k: v for k, v in source['stream'].items() if k != 'csv'})
                (out / 'observations.csv').write_text(source['stream']['csv'])
                scope = 'independent-signal-assessment-no-execution'
            elif track in ('workflow', 'supply-chain', 'procurement'):
                if track == 'workflow':
                    world, view = shopfloor.ManufacturingWorkflow(task), shopfloor_views.AgentView()
                    task_public, tools, project = shopfloor_views.public_task(task, key), shopfloor.TOOLS, view.result
                elif track == 'supply-chain':
                    world, view = supply_chain.SupplyChainWorld(task), supply_chain.SupplyView(task)
                    task_public, tools, project = supply_chain.public_task(task, key), supply_chain.TOOLS, view.encode
                else:
                    world, view = procurement.ProcurementWorld(task), procurement.ProcurementView()
                    task_public, tools, project = procurement.public_task(task, key), procurement.TOOLS, view.encode
                save(out / 'task.json', task_public)
                save(out / 'tools.json', tools)
                # Independent fresh worlds per read: every observation is at the initial clock.
                # Calling read sequentially would advance the simulator and create a mixed-time packet.
                snapshots = {}
                for system in task['systems']:
                    fresh = type(world)(task)
                    snapshots[system] = project(fresh.call('read', system=system))
                save(out / 'opening-observations.json', snapshots)
            elif track == 'execution':
                raw = IncidentTask.from_dict(task).public_dict()
                save(out / 'task.json', {k: raw[k] for k in ('title', 'prompt', 'systems') if k in raw})
                scope = 'task-wording-only-no-world-observations'
            elif track == 'season':
                save(out / 'opening-observation.json', FactorySeason(task, 0).observe())
                scope = 'opening-week-only-no-season-policy-evaluation'
            case = dict(review_case_id=key, track=track, scope=scope, provenance='synthetic-authored')
            cases.append(case)
            mapping.append(dict(**case, evaluator_task_id=task.id if track == 'season' else task['id']))
            (out / 'SCOPE.txt').write_text(
                f"{key}: {track}; scope: {scope}.\n"
                'Record your reasoning, assumptions, ambiguous or missing facts, and practical rule concerns.\n'
                'Only the supplied static assessment is requested. Dynamic track snapshots cannot establish\n'
                'complete episode feasibility, execution correctness, economics, or replay.\n')
    template = dict(protocol=PROTOCOL, public_manifest_sha256='REPLACE_WITH_MANIFEST_SHA256',
        reviewer=dict(name='', role='', relevant_experience='', relationship_to_authors='',
                      prior_exposure_to_references='', assistance_and_tools_used=''),
        cases=[dict(review_case_id=c['review_case_id'], disposition='not-reviewed',
                    answer=None, reasoning='', findings=[]) for c in cases])
    save(public / 'submission-template.json', template)
    (public / 'README.md').write_text((ROOT / 'docs/practitioner-review.md').read_text())
    # Separate compatibility extension; no upstream case data, private snapshots, API keys or oracle.
    (public / 'erp-compatibility-scope.txt').write_text(
        'ERP compatibility is separate from the nine native tracks. No ERP review case is supplied here.\n'
        'Three selected pinned upstream cases have author-run qualification, not independent practitioner validation.\n'
        'A later supervised review requires the offline restored fixture and public business tool gateway.\n')
    manifest = dict(protocol=PROTOCOL, benchmark_version=__version__,
        source_release_manifest_sha256=sha(ROOT / 'manifest.json'),
        builder_sha256=sha(__file__), sampling='First and last catalog entry in each native track; purposive, not representative or random.',
        limitations=['Public development cases; references withheld from this packet, but public source may contain them.',
                     'Reviewer self-report and frozen receipts do not verify identity, independence, expertise or correctness.',
                     'Eighteen samples do not validate the full catalog; dynamic snapshots are explicitly partial.'],
        cases=cases, files={p.relative_to(public).as_posix(): sha(p) for p in sorted(public.rglob('*')) if p.is_file()})
    save(public / 'manifest.json', manifest)
    save(destination / 'coordinator-private' / 'case-map.json', dict(public_manifest_sha256=sha(public / 'manifest.json'), cases=mapping))
    verify(public)
    with zipfile.ZipFile(destination / 'reviewer-packet.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(public.rglob('*')):
            if path.is_file():
                archive.write(path, path.relative_to(public).as_posix())
    save(destination / 'status.json', dict(protocol=PROTOCOL, public_manifest_sha256=sha(public / 'manifest.json'),
        prepared_sample_cases=len(cases), native_tracks_prepared=len(catalogs),
        independent_reviews_verified=0, independent_review_status='not-established',
        reference_disclosure_status='not-recorded', messages_sent=0))
    return destination / 'reviewer-packet.zip'


def freeze(public, submission, receipt):
    public, submission, receipt = Path(public), Path(submission), Path(receipt)
    manifest = verify(public)
    if receipt.exists():
        raise ValueError('receipt already exists; frozen submissions cannot be overwritten')
    original = submission.read_bytes()
    raw = original.decode('utf-8')
    data = json.loads(raw)
    if data.get('protocol') != PROTOCOL or data.get('public_manifest_sha256') != sha(public / 'manifest.json'):
        raise ValueError('submission protocol or public manifest commitment mismatch')
    required = {'name', 'role', 'relevant_experience', 'relationship_to_authors', 'prior_exposure_to_references', 'assistance_and_tools_used'}
    reviewer = data.get('reviewer')
    if not isinstance(reviewer, dict) or set(reviewer) != required or any(not isinstance(v, str) or not v.strip() for v in reviewer.values()):
        raise ValueError('complete reviewer declarations required; declarations are unverified')
    cases = data.get('cases')
    known = {c['review_case_id'] for c in manifest['cases']}
    if not isinstance(cases, list) or not cases:
        raise ValueError('at least one reviewed case is required')
    seen = set()
    for case in cases:
        if not isinstance(case, dict) or set(case) != {'review_case_id', 'disposition', 'answer', 'reasoning', 'findings'}:
            raise ValueError('invalid case review fields')
        key = case['review_case_id']
        if not isinstance(key, str) or key not in known or key in seen:
            raise ValueError('unknown or duplicate review case')
        seen.add(key)
        if case['disposition'] not in ('solved', 'ambiguous', 'insufficient-input', 'rule-defect'):
            raise ValueError('unreviewed cases must be removed from submitted cases')
        if not isinstance(case['reasoning'], str) or not case['reasoning'].strip() or not isinstance(case['findings'], list) or not all(isinstance(v, str) and v.strip() for v in case['findings']):
            raise ValueError('reasoning and textual findings required')
        if case['disposition'] == 'solved' and case['answer'] is None:
            raise ValueError('solved case requires an independently prepared answer')
        if case['disposition'] != 'solved' and not case['findings']:
            raise ValueError('unresolved case requires a finding')
    # Embed the exact original bytes, rather than relying on a mutable external filename.
    value = dict(protocol=PROTOCOL, received_utc=datetime.now(timezone.utc).isoformat(),
        public_manifest_sha256=sha(public / 'manifest.json'), submission_sha256=hashlib.sha256(original).hexdigest(),
        original_submission_utf8=raw, submitted_cases=sorted(seen),
        status='frozen-unverified-submission', identity_verified=False,
        independence_verified=False, expertise_verified=False, correctness_verified=False,
        limitation='Local timestamp and hashes are not an independent timestamp authority or identity attestation.')
    receipt.parent.mkdir(parents=True, exist_ok=True)
    with receipt.open('x') as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('build'); prepare.add_argument('--output', required=True)
    check = commands.add_parser('check'); check.add_argument('--public', required=True)
    submit = commands.add_parser('freeze'); submit.add_argument('--public', required=True); submit.add_argument('--submission', required=True); submit.add_argument('--receipt', required=True)
    args = parser.parse_args()
    if args.command == 'build': print(build(args.output))
    elif args.command == 'check':
        manifest = verify(args.public)
        print(f"Verified {len(manifest['cases'])} sampled public cases; no independent validation inferred.")
    else: print(freeze(args.public, args.submission, args.receipt))


if __name__ == '__main__':
    main()
