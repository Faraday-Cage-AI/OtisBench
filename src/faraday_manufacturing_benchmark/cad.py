"""Public CAD packets, one-shot agent programs, timed kernel grading and replay."""
import base64
from copy import deepcopy
import hashlib
from importlib.resources import files
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
from .cad_cases import build
from .cad_kernel import PROGRAM_SCHEMA,validate,execute,export_step,versions
from .cad_drawings import drawing_png
from .shopfloor import digest


def generate_packet(task):
    source=build(task);png=drawing_png(task)
    packet=dict(task=dict(id='manufacturing-cad-reconstruction',goal='Construct the released revision-B solid shown in the engineering drawing. Return exactly {"program": <CSG node>} or {"step_base64": <millimeter STEP bytes encoded as base64>}.',
        modality=task['mode'],units='mm',datum='Use the drawing global coordinates; no automatic alignment is applied.',
        program_contracts=deepcopy(PROGRAM_SCHEMA),program_budget=dict(maximum_nodes=64,maximum_depth=12,coordinate_limit_mm=1000,maximum_step_bytes=5000000,maximum_reply_bytes=7100000),
        grading_contract='A valid single nonempty solid must match the released geometry and datum. Boolean symmetric-difference volume tolerance is max(1e-5 mm^3, 1e-7*reference volume); bounds tolerance is 1e-4 mm. No target geometry or live correctness feedback is supplied.'),
        drawing=dict(mime_type='image/png',sha256=hashlib.sha256(png).hexdigest(),base64=base64.b64encode(png).decode()))
    if task['mode']=='text_and_drawing':packet['task']['description']='\n'.join(source['notes'])
    if task['mode']=='revision_edit':
        packet['task']['change_request']=source['revision_note']
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'revision-a.step';export_step(execute(source['baseline_program']),path);blob=path.read_bytes()
        packet['baseline_step']=dict(mime_type='model/step',revision='A',sha256=hashlib.sha256(blob).hexdigest(),base64=base64.b64encode(blob).decode())
    return packet


def public_packet(task):
    root=files('faraday_manufacturing_benchmark').joinpath('data/cad_assets')
    manifest=json.loads(root.joinpath('manifest.json').read_text())
    entry=manifest['cases'][task['id']]
    if entry['spec_sha256']!=digest(build(task)):raise ValueError('frozen CAD specification mismatch; regenerate public assets')
    packet=deepcopy(entry['public_metadata'])
    for key in ('drawing','baseline_step'):
        if key not in entry['files']:continue
        asset=entry['files'][key];blob=root.joinpath(task['id'],asset['filename']).read_bytes()
        if hashlib.sha256(blob).hexdigest()!=asset['sha256']:raise ValueError('CAD public asset hash mismatch')
        packet[key]={k:v for k,v in asset.items() if k!='filename'}
        packet[key]['base64']=base64.b64encode(blob).decode()
    return packet


def export_packet(task,directory):
    packet=public_packet(task);out=Path(directory);out.mkdir(parents=True,exist_ok=True)
    (out/'drawing.png').write_bytes(base64.b64decode(packet['drawing']['base64']))
    if 'baseline_step' in packet:(out/'revision-a.step').write_bytes(base64.b64decode(packet['baseline_step']['base64']))
    else:(out/'revision-a.step').unlink(missing_ok=True)
    public={k:v for k,v in packet.items() if k not in ('drawing','baseline_step')}
    public['assets']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.iterdir()) if p.name in ('drawing.png','revision-a.step')}
    (out/'task.json').write_text(json.dumps(public,indent=2,sort_keys=True)+'\n')
    return public


def grade_candidate(task,answer,timeout=30,export_path=None):
    if not isinstance(answer,dict) or set(answer) not in ({'program'},{'step_base64'}):return dict(strict_success=False,score=0,error_type='InvalidAnswerSchema')
    if not math.isfinite(timeout) or timeout<=0:raise ValueError('kernel timeout must be finite and positive')
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory);request=dict(task=task)
        try:
            if 'program' in answer:validate(answer['program']);request['program']=deepcopy(answer['program'])
            else:
                if not isinstance(answer['step_base64'],str) or len(answer['step_base64'])>7_000_000:raise ValueError('oversized STEP encoding')
                blob=base64.b64decode(answer['step_base64'],validate=True)
                if len(blob)>5_000_000:raise ValueError('oversized STEP')
                path=root/'candidate.step';path.write_bytes(blob);request['step_path']=str(path)
        except (ValueError,TypeError) as exc:return dict(strict_success=False,score=0,error_type='InvalidCandidate',error=str(exc))
        if export_path:request['export_step']=str(Path(export_path).resolve())
        input_path=root/'request.json';output_path=root/'result.json';input_path.write_text(json.dumps(request,allow_nan=False))
        try:
            process=subprocess.run([sys.executable,'-m','faraday_manufacturing_benchmark.cad_worker',str(input_path),str(output_path)],capture_output=True,text=True,timeout=timeout)
        except subprocess.TimeoutExpired:return dict(strict_success=False,score=0,error_type='KernelTimeout')
        if process.returncode or not output_path.is_file():return dict(strict_success=False,score=0,error_type='KernelProcessFailure')
        return json.loads(output_path.read_text())


def run(task,agent,kernel_timeout=30):
    packet=public_packet(task)
    try:
        answer=agent.decide('cad',deepcopy(packet));result=grade_candidate(task,answer,kernel_timeout)
        status='finished'
    except (ValueError,OSError) as exc:answer=None;result=dict(strict_success=False,score=0,error_type='InvalidAnswerSchema');status='stopped'
    return dict(evaluator_task_id=task['id'],source_commitment=digest(task),public_input=packet,answer=answer,result=result,status=status,kernel_timeout_seconds=kernel_timeout)


def replay(task,episode,kernel_timeout=None):
    if digest(task)!=episode['source_commitment'] or public_packet(task)!=episode['public_input']:raise ValueError('CAD source/public asset mismatch')
    actual=grade_candidate(task,episode['answer'],kernel_timeout or episode.get('kernel_timeout_seconds',30))
    def same(a,b):
        if isinstance(b,bool):return type(a) is bool and a==b
        if isinstance(b,float):return type(a) in (int,float) and math.isclose(a,b,abs_tol=1e-8,rel_tol=1e-10)
        if isinstance(b,dict):return isinstance(a,dict) and a.keys()==b.keys() and all(same(a[k],v) for k,v in b.items())
        if isinstance(b,list):return isinstance(a,list) and len(a)==len(b) and all(same(x,y) for x,y in zip(a,b))
        return type(a) is type(b) and a==b
    if not same(actual,episode['result']):raise ValueError('CAD geometry replay mismatch')
    return actual


def summary(episodes):
    from collections import defaultdict
    from .cad_cases import catalog
    tasks={t['id']:t for t in catalog()};families=defaultdict(list);modes=defaultdict(list)
    if not episodes or len({e['evaluator_task_id'] for e in episodes})!=len(episodes):raise ValueError('empty or duplicate CAD episodes')
    for e in episodes:
        t=tasks[e['evaluator_task_id']];families[t['family']].append(e);modes[t['mode']].append(e)
    def group(rows):return dict(cases=len(rows),strict_successes=sum(e['result']['strict_success'] for e in rows),mean_score=sum(e['result']['score'] for e in rows)/len(rows))
    return dict(**group(episodes),macro_family_strict_rate=sum(sum(e['result']['strict_success'] for e in rows)/len(rows) for rows in families.values())/len(families),families={k:group(v) for k,v in sorted(families.items())},modes={k:group(v) for k,v in sorted(modes.items())})
