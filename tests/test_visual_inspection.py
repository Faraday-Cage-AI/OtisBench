import hashlib
import importlib.util
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def visual(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT/'scripts'))
    import fetch_visual_inspection as acquisition
    import visual_inspection_benchmark as benchmark
    spec=importlib.util.spec_from_file_location('visual_public_policy',ROOT/'examples/visual_inspection_agent.py')
    policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy)
    return acquisition,benchmark,policy


@pytest.mark.parametrize('labels,scores',[
    ([0,1],[0.,1.]),([0,1],[1.,0.]),([0,1],[1.,1.]),
    ([0,0,1,1],[0.,.5,.5,1.]),([1,0,1,0,0],[1.,1.,2.,3.,0.])])
def test_exact_tied_auc_agrees_with_independent_pairwise_definition(visual,labels,scores):
    _,b,_=visual;pos=[score for y,score in zip(labels,scores) if y];neg=[score for y,score in zip(labels,scores) if not y]
    expected=sum((p>n)+.5*(p==n) for p in pos for n in neg)/(len(pos)*len(neg))
    assert b.auroc(labels,scores)==expected


@pytest.mark.parametrize('labels,scores',[
    ([0,0],[0.,1.]),([1,1],[0.,1.]),([0,1],[0.,float('nan')]),
    ([0,1],[0.,float('inf')]),([0,.5],[0.,1.]),([0,1],[0.])])
def test_invalid_or_undefined_auc_fails_closed(visual,labels,scores):
    with pytest.raises(ValueError):visual[1].auroc(labels,scores)


def test_subpixel_defect_survives_mask_area_resampling(visual):
    _,b,_=visual;mask=np.zeros((1024,1024),dtype=np.uint8);mask[519,519]=1
    resized=b.mask_grid(Image.fromarray(mask))
    assert resized.shape==(64,64) and resized.any()
    assert not b.mask_grid(Image.fromarray(np.zeros_like(mask))).any()


def test_duplicate_normal_training_content_is_kept_together_and_test_overlap_rejected(visual):
    _,b,_=visual
    rows=[dict(image='a',split='train',label='normal'),dict(image='b',split='train',label='normal'),dict(image='c',split='test',label='anomaly')]
    source=dict(raw_files={'a':dict(sha256='same'),'b':dict(sha256='same'),'c':dict(sha256='different')})
    split=b.partition(rows,source);assert split[0]==split[1]
    rows[1]['split']='test'
    with pytest.raises(ValueError,match='crosses official'):b.partition(rows,source)


def test_official_training_defect_cannot_enter_fit_or_calibration(visual):
    with pytest.raises(ValueError):visual[1].partition([dict(image='bad',split='train',label='anomaly')],dict(raw_files={'bad':dict(sha256='a')}))


@pytest.mark.parametrize('name',['../secret.png','/tmp/secret.png','a/../../secret','a\\secret','.'])
def test_archive_members_cannot_escape_raw_root(visual,name):
    with pytest.raises(ValueError,match='unsafe'):visual[0].member_name(name)


def test_archive_hash_includes_tail_after_tar_end(visual):
    reader=visual[0].HashReader(io.BytesIO(b'header-and-image'+b'\0'*2048))
    first=reader.read(3)
    while reader.read(7):pass
    assert first==b'hea' and reader.count==2064
    assert reader.hash.hexdigest()==hashlib.sha256(b'header-and-image'+b'\0'*2048).hexdigest()


@pytest.mark.parametrize('mutation',['missing','order','threshold','nan','boolean'])
def test_prediction_identity_and_calibration_thresholds_cannot_be_forged(visual,mutation):
    _,b,_=visual
    index={'records':[dict(id='x',category='pcb',split='test'),dict(id='y',category='pcb',split='test')]}
    prediction=dict(ids=['x','y'],thresholds={'pcb':dict(image=1.,pixel=1.)})
    if mutation=='missing':prediction['ids'].pop()
    elif mutation=='order':prediction['ids'].reverse()
    elif mutation=='threshold':prediction['thresholds'].clear()
    elif mutation=='boolean':prediction['thresholds']['pcb']['image']=True
    else:prediction['thresholds']['pcb']['image']=float('nan')
    with pytest.raises(ValueError):b.validate_predictions(index,prediction)


def test_baseline_uses_public_only_normal_calibration_and_replays_exactly(visual,tmp_path):
    _,_,policy=visual;public=tmp_path/'public';public.mkdir();size=64
    images=np.zeros((5,size,size,3),dtype=np.uint8);images[4]=255
    np.save(public/'images.npy',images,allow_pickle=False)
    records=[dict(id=f'opaque-{i}',category='pcb',split=split,array_index=i) for i,split in enumerate(['fit','fit','calibration','test','test'])]
    (public/'index.json').write_text(json.dumps(dict(records=records)))
    # No evaluator or source-label files exist in this fixture at all.
    first=policy.run(public,tmp_path/'a');second=policy.run(public,tmp_path/'b')
    a=np.load(tmp_path/'a/maps.npy',allow_pickle=False);b=np.load(tmp_path/'b/maps.npy',allow_pickle=False)
    assert np.array_equal(a,b) and np.all(a[0]==0) and np.allclose(a[1],400)
    assert first['thresholds']=={'pcb':dict(image=0.,pixel=0.)}==second['thresholds']
    assert first['ids']==['opaque-3','opaque-4'] and first['model_calls']==0


def test_confusion_reports_false_positive_rate_and_misses(visual):
    result=visual[1].confusion([0,0,1,1],[0,1,0,1])
    assert [result[key] for key in ('tp','fp','fn','tn')]==[1,1,1,1]
    assert result['f1']==result['false_positive_rate']==.5
