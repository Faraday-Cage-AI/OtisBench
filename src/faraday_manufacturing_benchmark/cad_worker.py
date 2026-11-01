"""Dedicated geometry process. Reads JSON data, never candidate Python code."""
import json
from pathlib import Path
import sys
from .cad_cases import build
from .cad_kernel import execute,compare,export_step,import_step,versions


def main():
    request=json.loads(Path(sys.argv[1]).read_text());out=Path(sys.argv[2])
    try:
        target=execute(build(request['task'])['program'])
        candidate=execute(request['program']) if 'program' in request else import_step(request['step_path'])
        result=compare(target,candidate);result['kernel_versions']=versions()
        if request.get('export_step'):export_step(candidate,request['export_step'])
    except Exception as exc:
        result=dict(strict_success=False,score=0,error_type=type(exc).__name__,error=str(exc)[:500])
    out.write_text(json.dumps(result,sort_keys=True,allow_nan=False)+'\n')
    return 0

if __name__=='__main__':raise SystemExit(main())
