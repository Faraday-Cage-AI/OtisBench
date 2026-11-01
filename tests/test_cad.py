from copy import deepcopy
import base64
import importlib.util
import io
import json
import math
from pathlib import Path
import pytest
cq=pytest.importorskip('cadquery')
pytest.importorskip('PIL')
from faraday_manufacturing_benchmark.cad_cases import catalog,build,box,cylinder,cut,union
from faraday_manufacturing_benchmark.cad_kernel import execute,measure,compare,validate,export_step,import_step
from faraday_manufacturing_benchmark.cad_drawings import drawing_png
from faraday_manufacturing_benchmark.cad import public_packet,grade_candidate,run,replay


def task(family='drilled_plate',mode='text_and_drawing',draw=0):return next(t for t in catalog() if t['family']==family and t['mode']==mode and t['draw']==draw)

@pytest.mark.parametrize('t',catalog(),ids=lambda t:t['id'])
def test_every_reference_part_is_one_valid_solid_and_baseline_revision_differs(t):
    source=build(t);target=execute(source['program']);baseline=execute(source['baseline_program'])
    result=measure(target)
    assert result['valid'] and result['solids']==1 and result['volume_mm3']>0
    assert compare(target,target)['strict_success']
    assert not compare(target,baseline)['strict_success']


def test_catalog_is_deterministic_and_reports_modes_and_draws_separately():
    assert len(catalog())==72 and catalog()==catalog()
    assert len({t['id'] for t in catalog()})==72
    for t in catalog():assert build(t)==build(t)


def test_kernel_matches_independent_analytic_volumes():
    drilled=execute(cut(box((40,30,8)),cylinder(3,10,(12,12,-1))))
    assert drilled.Volume()==pytest.approx(40*30*8-math.pi*3**2*8)
    ring=execute(cut(cylinder(10,12,(10,10,0)),cylinder(4,14,(10,10,-1))))
    assert ring.Volume()==pytest.approx(math.pi*(100-16)*12)
    pocket=execute(cut(box((40,30,20)),box((20,10,8),(5,5,12))))
    assert pocket.Volume()==pytest.approx(40*30*20-20*10*8)


def test_geometric_equivalence_accepts_different_program_structure():
    reference=execute(box((20,10,5)))
    alternative=execute(union(box((10,10,5)),box((10,10,5),(10,0,0))))
    assert compare(reference,alternative)['strict_success']


def test_equal_volume_equal_bounds_but_wrong_hole_location_fails():
    reference=execute(cut(box((40,30,8)),cylinder(3,10,(12,12,-1))))
    wrong=execute(cut(box((40,30,8)),cylinder(3,10,(25,12,-1))))
    r=compare(reference,wrong)
    assert r['checks']['volume'] and r['checks']['datum_bounds']
    assert not r['checks']['symmetric_difference'] and not r['strict_success']


def test_tiny_missing_hole_cannot_hide_behind_a_loose_volume_iou_threshold():
    full=box((100,100,100));reference=execute(cut(full,cylinder(.5,102,(50,50,-1))))
    r=compare(reference,execute(full))
    assert r['volume_iou']>.999 and not r['strict_success']
    assert r['symmetric_difference_mm3']>r['symmetric_difference_tolerance_mm3']


def test_wrong_datum_disconnected_solids_and_empty_shape_fail():
    original=execute(box((20,10,5)))
    moved=execute(dict(op='translate',shape=box((20,10,5)),vector=[1,0,0]))
    assert not compare(original,moved)['strict_success']
    disconnected=execute(union(box((10,10,5)),box((10,10,5),(30,0,0))))
    r=compare(original,disconnected)
    assert not r['checks']['valid_solid'] and not r['strict_success']


def test_program_validation_rejects_code_nonfinite_types_extra_fields_and_excess_depth():
    for value in (dict(op='python',source='print(1)'),dict(box((1,1,1)),extra=1),box((True,1,1)),box((float('nan'),1,1)),box((0,1,1)),box((1001,1,1))):
        with pytest.raises(ValueError):validate(value)
    program=box((1,1,1))
    for _ in range(14):program=dict(op='translate',shape=program,vector=[0,0,0])
    with pytest.raises(ValueError):validate(program)

@pytest.mark.parametrize('family',['drilled_plate','counterbore_plate','slotted_plate','pocket_block','stepped_shaft','flanged_bushing','angle_bracket','open_housing'])
def test_raster_drawing_contains_no_hidden_program_or_text_metadata(family):
    from PIL import Image
    t=task(family,'drawing_only');png=drawing_png(t)
    image=Image.open(io.BytesIO(png))
    assert image.size==(1700,1250) and image.format=='PNG' and not image.info
    assert png==drawing_png(t)
    packet=public_packet(t)
    assert 'description' not in packet['task'] and 'baseline_step' not in packet
    assert not set(packet['task'])&{'seed','program','parameters','family','expected_volume'}


def test_starting_step_is_only_supplied_for_revision_edit_and_is_not_the_target(tmp_path):
    t=task(mode='revision_edit');packet=public_packet(t)
    assert 'description' not in packet['task'] and packet['task']['change_request']
    raw=base64.b64decode(packet['baseline_step']['base64']);path=tmp_path/'initial.step';path.write_bytes(raw)
    assert not compare(execute(build(t)['program']),import_step(path))['strict_success']
    assert public_packet(t)==packet


def test_step_round_trip_uses_native_geometry_and_declared_mm_units(tmp_path):
    t=task();shape=execute(build(t)['program']);path=tmp_path/'candidate.step';export_step(shape,path)
    assert 'SI_UNIT(.MILLI.,.METRE.)' in path.read_text()
    assert compare(shape,import_step(path))['strict_success']
    result=grade_candidate(t,dict(step_base64=base64.b64encode(path.read_bytes()).decode()))
    assert result['strict_success']
    path.write_text(path.read_text().replace('SI_UNIT(.MILLI.,.METRE.)','SI_UNIT($,.METRE.)'))
    with pytest.raises(ValueError,match='millimeter'):import_step(path)


def test_supervised_kernel_timeout_and_invalid_answers_do_not_crash_host():
    t=task()
    assert grade_candidate(t,dict(program=build(t)['program']),timeout=.001)['error_type']=='KernelTimeout'
    assert not grade_candidate(t,dict(program=dict(op='python',source='import os')))['strict_success']
    assert not grade_candidate(t,dict(step_base64='not base64'))['strict_success']
    assert not grade_candidate(t,dict(program=box((1,1,1)),extra='reference'))['strict_success']


def test_public_text_agent_runs_without_evaluator_imports_and_replays():
    spec=importlib.util.spec_from_file_location('text_plate',Path(__file__).parents[1]/'examples/cad_plate_agent.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    class Agent:
        def decide(self,track,payload):return module.decide(payload)
    t=task();episode=run(t,Agent());assert episode['result']['strict_success'];assert replay(t,episode)['strict_success']
    forged=deepcopy(episode);forged['result']['symmetric_difference_mm3']=10
    with pytest.raises(ValueError,match='replay mismatch'):replay(t,forged)
    forged=deepcopy(episode);forged['public_input']['drawing']['sha256']='0'*64
    with pytest.raises(ValueError,match='source/public asset'):replay(t,forged)


def test_empty_solid_cannot_pass_or_crash_the_parent():
    result=grade_candidate(task(),dict(program=cut(box((1,1,1)),box((2,2,2),(-.5,-.5,-.5)))))
    assert not result['strict_success'] and result['score']==0


def test_frozen_catalog_and_assets_are_complete_and_fingerprinted():
    from importlib.resources import files
    import hashlib
    frozen=json.loads(files('faraday_manufacturing_benchmark').joinpath('data/cad_tasks.json').read_text())
    assert frozen==catalog()
    root=files('faraday_manufacturing_benchmark').joinpath('data/cad_assets');manifest=json.loads(root.joinpath('manifest.json').read_text())
    assert set(manifest['cases'])=={t['id'] for t in catalog()}
    for t in catalog():
        entry=manifest['cases'][t['id']]
        for item in entry['files'].values():assert hashlib.sha256(root.joinpath(t['id'],item['filename']).read_bytes()).hexdigest()==item['sha256']
        assert set(entry['files'])==({'drawing','baseline_step'} if t['mode']=='revision_edit' else {'drawing'})


def test_cli_raw_program_step_export_and_external_text_agent(tmp_path,capsys):
    import shlex,sys
    from faraday_manufacturing_benchmark.cli import main
    t=task();program=tmp_path/'candidate.json';program.write_text(json.dumps(build(t)['program']))
    output=tmp_path/'result.json';step=tmp_path/'candidate.step';packet=tmp_path/'packet'
    assert main(['grade-cad','--task',t['id'],'--program',str(program),'--output',str(output),'--export-step',str(step)])==0
    assert json.loads(output.read_text())['summary']['strict_successes']==1 and step.exists()
    assert main(['replay',str(output)])==0
    assert main(['export-cad','--task',task(mode='revision_edit')['id'],'--output-dir',str(packet)])==0
    assert (packet/'revision-a.step').exists()
    assert main(['export-cad','--task',task(mode='drawing_only')['id'],'--output-dir',str(packet)])==0
    assert not (packet/'revision-a.step').exists()
    assert 'description' not in json.loads((packet/'task.json').read_text())['task']
    command=shlex.quote(sys.executable)+' '+shlex.quote(str(Path(__file__).parents[1]/'examples/cad_plate_agent.py'))
    assert main(['cad','--task',t['id'],'--agent-command',command,'--output',str(output)])==0
    assert json.loads(output.read_text())['summary']['strict_successes']==1
    program.write_text('12')
    assert main(['grade-cad','--task',t['id'],'--program',str(program),'--output',str(output)])==0
    assert not json.loads(output.read_text())['summary']['strict_successes']


def test_cylinder_projection_includes_face_silhouettes_not_just_topological_edges():
    from faraday_manufacturing_benchmark.cad_drawings import projected_edges
    shape=execute(cylinder(10,20,(0,10,10),'x'))
    edges=projected_edges(shape,(0,0,1),(1,0,0))
    horizontal=[]
    for hidden,points in edges:
        if not hidden and max(p[0] for p in points)-min(p[0] for p in points)>19.9 and max(p[1] for p in points)-min(p[1] for p in points)<1e-6:horizontal.append(points[0][1])
    assert any(abs(y)<1e-6 for y in horizontal) and any(abs(y+20)<1e-6 for y in horizontal)


def test_cad_transport_supports_step_payloads_above_the_default_reply_cap(tmp_path):
    import shlex,sys
    from faraday_manufacturing_benchmark.agents import DecisionAgent
    from faraday_manufacturing_benchmark.cli import main
    path=tmp_path/'candidate.step';export_step(execute(build(task())['program']),path)
    text=path.read_text().replace('DATA;',('/* transport padding */\n'*6000)+'DATA;',1)
    encoded=base64.b64encode(text.encode()).decode();script=tmp_path/'large_agent.py'
    script.write_text('import json,sys\nfor line in sys.stdin:\n print(json.dumps({"step_base64":'+repr(encoded)+'}),flush=True)\n')
    command=shlex.join([sys.executable,str(script)])
    with DecisionAgent(command,timeout=5,max_reply_bytes=7100000) as external:
        assert external.decide('cad',{})['step_base64']==encoded
    output=tmp_path/'result.json'
    assert main(['cad','--task',task()['id'],'--agent-command',command,'--output',str(output)])==0
    assert json.loads(output.read_text())['summary']['strict_successes']==1


def test_advanced_kernel_operations_match_independent_volumes_and_reject_omissions():
    from faraday_manufacturing_benchmark.cad_cases import box
    taper=dict(op='cone',radius1=8,radius2=4,height=12,origin=[0,0,0],axis='z')
    assert execute(taper).Volume()==pytest.approx(math.pi*12*(8**2+8*4+4**2)/3)
    loft=dict(op='loft_rectangles',sections=[dict(origin=[0,0,0],size=[20,10]),dict(origin=[3,2,15],size=[12,6])])
    expected=15*(20*10+(20*(-4)+10*(-8))/2+(-8)*(-4)/3)
    assert execute(loft).Volume()==pytest.approx(expected)
    rounded=dict(op='fillet',shape=box((20,16,10)),radius=1)
    a,b,c=18,14,8
    volume=a*b*c+2*(a*b+a*c+b*c)+math.pi*(a+b+c)+4*math.pi/3
    assert execute(rounded).Volume()==pytest.approx(volume)
    for treatment in [rounded,dict(op='chamfer',shape=box((20,16,10)),distance=1)]:
        shape=execute(treatment)
        assert shape.isValid() and len(shape.Solids())==1
        assert not compare(shape,execute(box((20,16,10))))['strict_success']


@pytest.mark.parametrize('program',[
    dict(op='cone',radius1=-1,radius2=2,height=5,origin=[0,0,0],axis='z'),
    dict(op='fillet',shape=dict(op='box',size=[10,10,10],origin=[0,0,0]),radius=float('nan')),
    dict(op='chamfer',shape=dict(op='box',size=[10,10,10],origin=[0,0,0]),distance=1,selector='arbitrary expression'),
    dict(op='loft_rectangles',sections=[dict(origin=[0,0,0],size=[10,10]),dict(origin=[0,0,0],size=[8,8])]),
    dict(op='loft_rectangles',sections=[dict(origin=[0,0,0],size=[10,10]),dict(origin=[0,0,5],size=[-8,8])]),
])
def test_advanced_grammar_rejects_unbounded_or_invalid_data(program):
    with pytest.raises(ValueError):validate(program)


@pytest.mark.parametrize('family',['rounded_plate','chamfered_pocket','tapered_hub','lofted_adapter'])
def test_advanced_parts_survive_step_exchange_without_losing_surface_geometry(tmp_path,family):
    t=task(family);shape=execute(build(t)['program']);path=tmp_path/'advanced.step'
    export_step(shape,path)
    assert compare(shape,import_step(path))['strict_success']
