"""Staged manufacturing judgment workshops; quality is assessed by reviewers."""
from copy import deepcopy
import hashlib
from importlib.resources import files
import json
from pathlib import Path

PROTOCOL = 'otisbench-manufacturing-judgment/1'
FIELDS = {'recommendation', 'alternatives', 'tradeoffs', 'assumptions', 'next_actions', 'evidence_ids', 'revision_reason'}
DIMENSIONS = ('evidence_use', 'tradeoff_quality', 'operational_feasibility',
              'uncertainty_handling', 'revision_quality', 'communication')


def catalog():
    return json.loads(files('faraday_manufacturing_benchmark').joinpath('data/judgment_cases.json').read_text())


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _task(key):
    return next((t for t in catalog() if t['id'] == key), None)


def start(key):
    task = _task(key)
    if task is None:
        raise ValueError('unknown judgment workflow')
    return dict(protocol=PROTOCOL, task_id=key, source_sha256=_digest(task), submissions=[])


def _records(task, round_index):
    return [deepcopy(r) for stage in task['stages'][:round_index + 1] for r in stage['records']]


def _check_decision(task, index, decision):
    if not isinstance(decision, dict) or set(decision) != FIELDS:
        raise ValueError('decision fields do not match the submission contract')
    for key in ('recommendation', 'tradeoffs', 'revision_reason'):
        if not isinstance(decision[key], str) or not decision[key].strip():
            raise ValueError('decision text must be nonempty')
    for key in ('alternatives', 'assumptions', 'evidence_ids'):
        if not isinstance(decision[key], list) or not decision[key] or any(not isinstance(x, str) or not x.strip() for x in decision[key]):
            raise ValueError('decision lists require nonempty strings')
    known = {r['id'] for r in _records(task, index)}
    if len(set(decision['evidence_ids'])) != len(decision['evidence_ids']) or not set(decision['evidence_ids']) <= known:
        raise ValueError('evidence citations must be unique and already visible')
    if not isinstance(decision['next_actions'], list) or not decision['next_actions']:
        raise ValueError('next_actions requires owner, action, and trigger records')
    for action in decision['next_actions']:
        if not isinstance(action, dict) or set(action) != {'owner', 'action', 'trigger'} or any(not isinstance(v, str) or not v.strip() for v in action.values()):
            raise ValueError('next action requires nonempty owner, action, and trigger')


def validate(state):
    if not isinstance(state, dict) or set(state) != {'protocol', 'task_id', 'source_sha256', 'submissions'} or state['protocol'] != PROTOCOL:
        raise ValueError('invalid workshop state')
    task = _task(state['task_id'])
    if task is None or _digest(task) != state['source_sha256']:
        raise ValueError('judgment source mismatch')
    if not isinstance(state['submissions'], list) or len(state['submissions']) > len(task['stages']):
        raise ValueError('invalid decision history')
    for i, decision in enumerate(state['submissions']):
        _check_decision(task, i, decision)
    return task


def observe(state):
    task = validate(state)
    done = len(state['submissions']) == len(task['stages'])
    i = min(len(state['submissions']), len(task['stages']) - 1)
    return dict(protocol=PROTOCOL, task_id=task['id'], title=task['title'], role=task['role'], goal=task['goal'],
        round=i + 1, total_rounds=len(task['stages']), phase=task['stages'][i]['label'],
        records=_records(task, i), prior_decisions=deepcopy(state['submissions']),
        submission_fields=sorted(FIELDS), action_fields=['owner', 'action', 'trigger'],
        status='awaiting_review' if done else 'awaiting_decision')


def submit(state, decision):
    task = validate(state)
    index = len(state['submissions'])
    if index == len(task['stages']):
        raise ValueError('all rounds already submitted')
    _check_decision(task, index, decision)
    updated = deepcopy(state)
    updated['submissions'].append(deepcopy(decision))
    return updated


def review(state, assessment):
    task = validate(state)
    if len(state['submissions']) != len(task['stages']):
        raise ValueError('complete all decisions before workshop review')
    if not isinstance(assessment, dict) or set(assessment) != {'reviewer', 'relationship', 'dimensions'}:
        raise ValueError('review requires identity, relationship, and dimension ratings')
    if any(not isinstance(assessment[k], str) or not assessment[k].strip() for k in ('reviewer', 'relationship')):
        raise ValueError('reviewer declarations must be nonempty')
    dimensions = assessment['dimensions']
    if not isinstance(dimensions, dict) or set(dimensions) != set(DIMENSIONS):
        raise ValueError('all review dimensions are required')
    known = {r['id'] for r in _records(task, len(task['stages']) - 1)}
    for value in dimensions.values():
        if not isinstance(value, dict) or set(value) != {'rating', 'rationale', 'evidence_ids', 'rounds'}:
            raise ValueError('rating requires rationale, evidence citations, and submission rounds')
        if type(value['rating']) is not int or not 1 <= value['rating'] <= 5:
            raise ValueError('review rating must be an integer from 1 to 5')
        if not isinstance(value['rationale'], str) or not value['rationale'].strip():
            raise ValueError('review rationale is required')
        if not isinstance(value['evidence_ids'], list) or not value['evidence_ids'] or any(not isinstance(x, str) or x not in known for x in value['evidence_ids']):
            raise ValueError('review citations must resolve')
        if not isinstance(value['rounds'], list) or not value['rounds'] or any(type(x) is not int or not 1 <= x <= len(task['stages']) for x in value['rounds']):
            raise ValueError('review must identify submission rounds')
    return dict(protocol=PROTOCOL, task_id=task['id'], submission_sha256=_digest(state),
        assessment=deepcopy(assessment), mean_rating=sum(v['rating'] for v in dimensions.values()) / len(DIMENSIONS),
        assessment_type='reviewer_judgment', objective_checks=dict(citation_ids_resolve=True, submission_structure_valid=True))


def configure(parser):
    sub = parser.add_subparsers(dest='judgment_command', required=True)
    sub.add_parser('list')
    begin = sub.add_parser('start'); begin.add_argument('--task', required=True); begin.add_argument('--session', required=True)
    show = sub.add_parser('show'); show.add_argument('--session', required=True)
    send = sub.add_parser('submit'); send.add_argument('--session', required=True); send.add_argument('--decision', required=True)
    assess = sub.add_parser('review'); assess.add_argument('--session', required=True); assess.add_argument('--assessment', required=True); assess.add_argument('--output', required=True)


def _write(path, value, exclusive=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation protects earlier sessions and independent review records.
    if exclusive:
        with path.open('x') as handle:
            handle.write(json.dumps(value, indent=2, allow_nan=False) + '\n')
    else:
        pending = path.with_name(path.name + '.pending')
        with pending.open('x') as handle:
            handle.write(json.dumps(value, indent=2, allow_nan=False) + '\n')
        pending.replace(path)


def execute(args):
    command = args.judgment_command
    if command == 'list':
        value = [dict(id=t['id'], title=t['title'], rounds=len(t['stages'])) for t in catalog()]
    elif command == 'start':
        state = start(args.task); _write(args.session, state, exclusive=True); value = observe(state)
    else:
        state = json.loads(Path(args.session).read_text())
        if command == 'submit':
            state = submit(state, json.loads(Path(args.decision).read_text()))
            _write(args.session, state); value = observe(state)
        elif command == 'review':
            value = review(state, json.loads(Path(args.assessment).read_text()))
            if Path(args.output).resolve() == Path(args.session).resolve():
                raise ValueError('review output must be separate from session')
            _write(args.output, value, exclusive=True)
        else:
            value = observe(state)
    print(json.dumps(value, indent=2, allow_nan=False))
    return 0
