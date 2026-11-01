"""Read-only current-source manifest and qualification evidence integrity audit."""
from pathlib import Path
import json
import subprocess
import sys
from faraday_manufacturing_benchmark.release_audit import audit
ROOT=Path(__file__).resolve().parents[1]

if __name__=='__main__':
    checked=subprocess.run([sys.executable,str(ROOT/'scripts/build_manifest.py'),'--check'],cwd=ROOT,capture_output=True,text=True)
    result=audit(ROOT);result['manifest_current']=checked.returncode==0
    if checked.returncode:result['manifest_error']=checked.stdout+checked.stderr
    result['passed']=result['passed'] and result['manifest_current']
    print(json.dumps(result,indent=2,sort_keys=True))
    raise SystemExit(0 if result['passed'] else 1)
