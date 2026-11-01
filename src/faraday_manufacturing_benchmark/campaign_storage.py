"""Append-only durable checkpoints for long manufacturing agent sessions."""
from copy import deepcopy
import json
import os
from pathlib import Path


class CampaignJournal:
    def __init__(self, output, replace=False):
        self.path = Path(str(output) + '.journal')
        self.replace = replace
        self.handle = None

    def _write(self, value):
        self.handle.write(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n')
        self.handle.flush()
        os.fsync(self.handle.fileno())

    def start(self, artifact):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        target = Path(str(self.path) + '.pending') if self.replace else self.path
        self.handle = target.open('w' if self.replace else 'x')
        self._write(dict(type='checkpoint', artifact=artifact))
        if self.replace:
            self.close()
            target.replace(self.path)
            self.handle = self.path.open('a')

    def append(self, record, public):
        self._write(dict(type='step', record=record, public=public))

    def close(self):
        if self.handle is not None:
            self.handle.close()
            self.handle = None


def load_checkpoint(path, task):
    """Recover complete durable steps, verifying the evaluator and public transport."""
    from .campaign import restore
    path = Path(path)
    journal = Path(str(path) + '.journal')
    if not journal.exists():
        artifact = json.loads(path.read_text())
        restore(task, artifact)
        return artifact
    with journal.open('rb') as handle:
        header = handle.readline()
        if not header.endswith(b'\n'):
            raise ValueError('incomplete campaign journal header')
        header = json.loads(header)
        if set(header) != {'type', 'artifact'} or header['type'] != 'checkpoint':
            raise ValueError('invalid campaign journal header')
        artifact = header['artifact']
        world, view = restore(task, artifact)
        history = deepcopy(artifact['agent_trace'])
        for line in handle:
            # A crash can leave one partial write; only complete records are durable.
            if not line.endswith(b'\n'):
                break
            entry = json.loads(line)
            if set(entry) != {'type', 'record', 'public'} or entry['type'] != 'step':
                raise ValueError('invalid campaign journal record')
            record, public = entry['record'], entry['public']
            decision = public['decision']
            if decision['tool'] != record['tool'] or view.decode(decision['arguments']) != record['arguments']:
                raise ValueError('campaign journal decision mismatch')
            result = world.call(record['tool'], record['arguments'], view)
            if world.trace[-1] != record or result != public['result']:
                raise ValueError('campaign journal transition mismatch')
            history.append(public)
    return dict(artifact, trace=deepcopy(world.trace), agent_trace=history, result=world.grade(), error_type=None)
