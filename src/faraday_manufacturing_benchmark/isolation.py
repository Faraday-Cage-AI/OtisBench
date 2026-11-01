"""Verified local macOS isolation for standalone, standard-library Python agents.

No provider credentials or network are exposed. This is a bounded local runner,
not a portable container or a claim of protection against kernel exploits.
"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import platform
import shlex
import sys
import tempfile
from .agents import DecisionAgent

SANDBOX=Path('/usr/bin/sandbox-exec')
POLICY_VERSION='macos-stdlib-offline/1'
BOOTSTRAP='''import os,resource,runpy,sys
resource.setrlimit(resource.RLIMIT_CPU,(60,60))
resource.setrlimit(resource.RLIMIT_FSIZE,(4*1024*1024,4*1024*1024))
resource.setrlimit(resource.RLIMIT_NOFILE,(64,64))
os.chdir(sys.argv[2])
runpy.run_path(sys.argv[1],run_name="__main__")
'''


def profile(stage,runtime):
    """Default-deny policy: only public staged code, scratch and Python runtime."""
    stage=Path(stage).resolve();runtime=Path(runtime).resolve()
    package=Path(__file__).resolve().parent
    private=package.parent.parent if package.parent.name=='src' else package
    site_packages=runtime/'lib'/f'python{sys.version_info.major}.{sys.version_info.minor}'/'site-packages'
    if (private.is_relative_to(runtime) and not private.is_relative_to(site_packages)) or runtime==Path('/'):
        raise ValueError('Python runtime allowlist would expose evaluator files')
    if stage.is_relative_to(private):raise ValueError('agent staging must be outside evaluator tree')
    # JSON string escaping is compatible with these Sandbox Profile strings.
    q=lambda path:json.dumps(str(path))
    ancestors=sorted({str(p) for path in (stage,runtime) for p in path.parents if p!=Path('/')})
    metadata=' '.join('(literal '+q(p)+')' for p in ancestors)
    return f'''(version 1)
(deny default)
(allow process-exec (subpath {q(runtime)}))
(allow sysctl-read)
(allow file-read-metadata {metadata})
(allow file-read* (literal "/") (subpath "/System") (subpath "/usr/lib")
    (require-all (subpath {q(runtime)}) (require-not (subpath {q(site_packages)}))) (subpath {q(stage)})
    (literal "/dev/null") (literal "/dev/urandom") (literal "/dev/random"))
(allow file-write* (subpath {q(stage)}) (literal "/dev/null"))
'''


@contextmanager
def isolated_agent(source,timeout=120,max_reply_bytes=100000):
    if platform.system()!='Darwin' or not SANDBOX.is_file():
        raise ValueError('macOS sandbox-exec unavailable; isolation will not fall back to an ordinary subprocess')
    code=Path(source).read_bytes()
    if not code or len(code)>1024*1024:raise ValueError('standalone agent must be 1 byte to 1 MiB')
    runtime=Path(sys.base_prefix).resolve();python=Path(sys._base_executable).resolve()
    if not python.is_relative_to(runtime):raise ValueError('Python executable outside runtime allowlist')
    with tempfile.TemporaryDirectory(prefix='faraday-agent-',dir='/tmp') as directory:
        stage=Path(directory).resolve();agent=stage/'agent.py';agent.write_bytes(code)
        policy=profile(stage,runtime);policy_file=stage/'policy.sb';policy_file.write_text(policy)
        scratch=stage/'scratch';scratch.mkdir()
        command=shlex.join(['/usr/bin/env','-i',f'HOME={scratch}',f'TMPDIR={scratch}','LANG=C','LC_ALL=C',str(SANDBOX),'-f',str(policy_file),str(python),'-I','-S','-u','-c',BOOTSTRAP,str(agent),str(scratch)])
        with DecisionAgent(command,timeout,max_reply_bytes) as process:
            process.isolation=dict(policy_version=POLICY_VERSION,platform=platform.platform(),python=sys.version,agent_sha256=hashlib.sha256(code).hexdigest(),policy_sha256=hashlib.sha256(policy.encode()).hexdigest(),network='denied',environment='empty except HOME/TMPDIR/LANG/LC_ALL',runtime='base Python with -I -S; no evaluator venv or installed agent dependencies',resource_limits=dict(cpu_seconds=60,file_bytes=4*1024*1024,open_files=64),limitations=['macOS only; not a container or cross-platform claim.','Standard-library standalone Python agents only; no hosted provider access.','Memory and total scratch-space limits are not enforced.','Public training data or memorized solutions are not prevented by filesystem isolation.'])
            yield process
