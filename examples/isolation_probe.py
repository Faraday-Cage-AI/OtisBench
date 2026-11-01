"""Adversarial offline isolation checks. Never returns probed file contents."""
import errno
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys


def attempt(fn):
    try:fn();return dict(allowed=True,errno=None)
    except OSError as exc:return dict(allowed=False,errno=exc.errno)


def inspect(payload):
    result={}
    for label,path in payload['read_paths'].items():
        result[label]=attempt(lambda path=path:Path(path).read_bytes())
    result['outside_write']=attempt(lambda:Path(payload['outside_write']).write_text('unexpected sandbox write'))
    link=Path('source-link');os.symlink(payload['read_paths']['evaluator_source'],link)
    result['symlink_read']=attempt(link.read_bytes)
    result['hardlink']=attempt(lambda:os.link(payload['read_paths']['evaluator_source'],'hard-link'))
    result['network']=attempt(lambda:socket.create_connection(('127.0.0.1',payload['port']),timeout=1).close())
    result['process_spawn']=attempt(lambda:subprocess.run([sys.executable,'-I','-S','-c','pass'],check=True,timeout=2))
    result['benchmark_import_visible']=importlib.util.find_spec('faraday_manufacturing_benchmark') is not None
    result['environment_canary_visible']='FARADAY_ISOLATION_CANARY' in os.environ
    result['environment_keys']=sorted(os.environ)
    result['own_code_readable']=Path(__file__).is_file()
    Path('scratch.txt').write_text('public scratch')
    result['scratch_usable']=Path('scratch.txt').read_text()=='public scratch'
    return result


if __name__=='__main__':
    for line in sys.stdin:print(json.dumps(inspect(json.loads(line)['payload'])),flush=True)
