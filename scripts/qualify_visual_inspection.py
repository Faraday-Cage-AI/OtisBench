"""Freeze/regrade real photographed VisA development evidence without model APIs."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import argparse
import csv
import json
from pathlib import Path
import subprocess
import sys

from fetch_visual_inspection import ROOT, sha, save, verify as verify_source
from visual_inspection_benchmark import ARCHIVE_SHA, SIZE, PROTOCOL, digest, read, partition, mask_grid, evaluate, validate_predictions

DATA=ROOT/'runs/visual-inspection-development-v1'
SOURCE_FILES=('scripts/fetch_visual_inspection.py','scripts/visual_inspection_benchmark.py',
    'scripts/qualify_visual_inspection.py','examples/visual_inspection_agent.py')


def verify_prepared(destination,reconstruct=False):
    import numpy as np
    from PIL import Image
    destination=Path(destination);manifest=read(destination/'manifest.json');source_root=ROOT/manifest['source'];source=read(source_root/'manifest.json')
    check=verify_source(source_root)
    if check['manifest_sha256']!=manifest['source_manifest_sha256'] or source['archive_sha256']!=ARCHIVE_SHA or source['fetcher_sha256']!=sha(ROOT/'scripts/fetch_visual_inspection.py'):
        raise ValueError('acquisition source commitment differs')
    if manifest['protocol']!=PROTOCOL or manifest['generator_sha256']!=sha(ROOT/'scripts/visual_inspection_benchmark.py') or manifest['size']!=SIZE or manifest['native_case_count_added']!=0:
        raise ValueError('preparation scope/source differs')
    expected_files={'public/images.npy','public/index.json','evaluator/masks.npy','evaluator/truth.json'}
    if set(manifest['files'])!=expected_files:raise ValueError('derived asset closure incomplete')
    for name,expected in manifest['files'].items():
        if sha(destination/name)!=expected:raise ValueError('prepared image/mask/index bytes changed')
    rows=list(csv.DictReader((ROOT/source['repository']/'split_csv/1cls.csv').open()))
    splits=partition(rows,source);index=read(destination/'public/index.json');truth=read(destination/'evaluator/truth.json')
    images=np.load(destination/'public/images.npy',allow_pickle=False,mmap_mode='r');masks=np.load(destination/'evaluator/masks.npy',allow_pickle=False,mmap_mode='r')
    if images.shape!=(10821,SIZE,SIZE,3) or images.dtype!=np.uint8 or masks.shape!=(2162,SIZE,SIZE) or masks.dtype!=np.bool_:
        raise ValueError('derived image/mask geometry differs')
    if len(index['records'])!=len(rows) or len(truth)!=len(rows):raise ValueError('derived row inventory differs')
    test_index=0;counts=Counter();pixel_counts=Counter()
    for array_index,(row,split,entry,label) in enumerate(zip(rows,splits,index['records'],truth,strict=True)):
        identity='photo-'+digest(['visa-development-v1',row['image'],source['raw_files'][row['image']]['sha256']])[:24]
        expected=dict(id=identity,category=row['object'],split=split,array_index=array_index)
        if split=='test':expected['test_index']=test_index
        if entry!=expected or label['id']!=identity or label['label']!=int(row['label']=='anomaly') or label['source_image']!=row['image'] or label['source_mask']!=row['mask'] or label['split']!=split:
            raise ValueError('derived ID/partition/annotation alignment differs')
        counts[(row['object'],split)]+=1
        pixel_counts['source_annotated_pixels']+=label['original_defect_pixels']
        if split=='test':
            grid=masks[test_index]
            if bool(grid.any())!=bool(label['label']) or int(grid.sum())!=label['resampled_defect_pixels']:raise ValueError('test label/mask differs')
        if reconstruct:
            with Image.open(source_root/'raw'/row['image']) as original:
                if list(original.size)!=label['original_size'] or not np.array_equal(images[array_index],np.asarray(original.convert('RGB').resize((SIZE,SIZE),Image.Resampling.BILINEAR))):
                    raise ValueError('RGB round trip differs')
            if row['mask']:
                with Image.open(source_root/'raw'/row['mask']) as original:
                    if list(original.size)!=label['original_size'] or int((np.asarray(original)>0).sum())!=label['original_defect_pixels'] or (split=='test' and not np.array_equal(mask_grid(original),masks[test_index])):
                        raise ValueError('mask round trip differs')
            elif label['original_defect_pixels']!=0:raise ValueError('normal image has nonzero mask')
        if split=='test':test_index+=1
    if {':'.join(key):value for key,value in sorted(counts.items())}!=manifest['partition_counts'] or dict(pixel_counts)!=manifest['pixel_counts']:
        raise ValueError('derived aggregates differ')
    if [manifest[key] for key in ('source_images','source_masks','official_test_images','normal_fit_images','normal_calibration_images')]!=[10821,1200,2162,6920,1739]:
        raise ValueError('split counts differ')
    return dict(passed=True,source_images=10821,source_masks=1200,official_test_images=2162,
        manifest_sha256=sha(destination/'manifest.json'),all_rgb_and_mask_roundtrips=reconstruct)


def call_baseline(destination,output):
    result=subprocess.run([sys.executable,'-I',str(ROOT/'examples/visual_inspection_agent.py'),
        '--public',str(destination/'public'),'--output',str(output)],cwd=ROOT,
        env={'LANG':'C.UTF-8','OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1'},capture_output=True,text=True,timeout=300)
    if result.returncode:raise ValueError('baseline process failed: '+result.stderr[-2000:])


def normalized_prediction(path):
    metadata=read(Path(path)/'predictions.json');metadata.pop('elapsed_seconds');return metadata


def diagnostic_predictions(destination,output,kind,template):
    import numpy as np
    output=Path(output);output.mkdir()
    truth=np.load(destination/'evaluator/masks.npy',allow_pickle=False,mmap_mode='r')
    maps=np.lib.format.open_memmap(output/'maps.npy',mode='w+',dtype=np.float32,shape=truth.shape)
    maps[:]=0 if kind=='constant' else truth
    maps.flush();del maps
    metadata=deepcopy(template)
    metadata['thresholds']={key:dict(image=0.,pixel=.5) for key in metadata['thresholds']}
    metadata['method']='constant zero diagnostic' if kind=='constant' else 'PRIVATE mask-derived metric diagnostic; not a public agent/model result'
    save(output/'predictions.json',metadata)
    return evaluate(destination,output)


def malformed_controls(index,template):
    controls=[]
    for label in ('missing_id','reordered_ids','missing_threshold','nonfinite_threshold'):
        changed=deepcopy(template)
        if label=='missing_id':changed['ids'].pop()
        elif label=='reordered_ids':changed['ids'][0],changed['ids'][1]=changed['ids'][1],changed['ids'][0]
        elif label=='missing_threshold':changed['thresholds'].pop(next(iter(changed['thresholds'])))
        else:changed['thresholds'][next(iter(changed['thresholds']))]['image']=float('nan')
        try:validate_predictions(index,changed)
        except ValueError as error:controls.append(dict(control=label,rejected=True,error=str(error)))
        else:raise ValueError('malformed prediction accepted')
    return controls


def run(destination,output):
    import numpy as np
    destination=Path(destination);output=Path(output)
    if output.exists():raise ValueError('refusing to overwrite retained visual qualification')
    output.mkdir(parents=True)
    source_hashes={name:sha(ROOT/name) for name in SOURCE_FILES}
    check=verify_prepared(destination,reconstruct=True)
    call_baseline(destination,output/'baseline');call_baseline(destination,output/'baseline-replay')
    if normalized_prediction(output/'baseline')!=normalized_prediction(output/'baseline-replay') or sha(output/'baseline/maps.npy')!=sha(output/'baseline-replay/maps.npy'):
        raise ValueError('fresh baseline prediction replay differs')
    with np.load(output/'baseline/model.npz',allow_pickle=False) as a,np.load(output/'baseline-replay/model.npz',allow_pickle=False) as b:
        if a.files!=b.files or any(not np.array_equal(a[key],b[key]) for key in a.files):raise ValueError('fitted model replay differs')
    measured=evaluate(destination,output/'baseline');template=read(output/'baseline/predictions.json')
    constant=diagnostic_predictions(destination,output/'constant','constant',template)
    oracle=diagnostic_predictions(destination,output/'private-mask-diagnostic','mask',template)
    if constant['macro_image_auroc']!=.5 or constant['macro_resampled_pixel_auroc']!=.5 or oracle['macro_image_auroc']!=1 or oracle['macro_resampled_pixel_auroc']!=1:
        raise ValueError('metric controls did not separate chance and private oracle')
    malformed=malformed_controls(read(destination/'public/index.json'),template)
    if {name:sha(ROOT/name) for name in SOURCE_FILES}!=source_hashes:raise ValueError('implementation changed during qualification')
    artifacts={str(path.relative_to(output)):sha(path) for path in output.rglob('*') if path.is_file()}
    report=dict(protocol='visual-inspection-qualification/1',integrity_passed=True,source_sha256=source_hashes,
        development_manifest=str((destination/'manifest.json').relative_to(ROOT)),development_manifest_sha256=check['manifest_sha256'],
        source_roundtrip=check,baseline_metrics=measured,constant_metrics=constant,private_mask_diagnostic_metrics=oracle,
        exact_fresh_prediction_replay=True,malformed_prediction_controls=malformed,artifacts=artifacts,
        model_api_calls=0,native_case_count_added=0,official_public_test_images=2162,categories=12,
        scope='A learned normal-appearance RGB baseline plus data/grader checks on public real photographs. Not an LLM/agent leaderboard, full-resolution official VisA evaluation, private holdout, completed industrial workflow or operational release validation. Private-mask diagnostic is metric validation only.')
    save(output/'qualification.json',report);return report


def audit(report_path):
    import numpy as np
    report_path=Path(report_path);report=read(report_path);output=report_path.parent
    if report['native_case_count_added']!=0 or report['model_api_calls']!=0 or report['categories']!=12 or report['official_public_test_images']!=2162 or not report['integrity_passed'] or report['exact_fresh_prediction_replay'] is not True:
        raise ValueError('visual evaluation scope promoted or changed')
    if set(report['source_sha256'])!=set(SOURCE_FILES):raise ValueError('implementation closure incomplete')
    for name,expected in report['source_sha256'].items():
        if sha(ROOT/name)!=expected:raise ValueError('visual implementation changed')
    development=ROOT/report['development_manifest']
    if sha(development)!=report['development_manifest_sha256']:raise ValueError('development manifest differs')
    prepared=verify_prepared(development.parent)
    if report['source_roundtrip']!=dict(prepared,all_rgb_and_mask_roundtrips=True):raise ValueError('qualification roundtrip record differs')
    expected={str(path.relative_to(output)) for path in output.rglob('*') if path.is_file()}-{'qualification.json'}
    if set(report['artifacts'])!=expected:raise ValueError('visual artifact closure differs')
    for name,expected_sha in report['artifacts'].items():
        if sha(output/name)!=expected_sha:raise ValueError('retained prediction/model changed')
    for folder,key in [('baseline','baseline_metrics'),('constant','constant_metrics'),('private-mask-diagnostic','private_mask_diagnostic_metrics')]:
        if evaluate(development.parent,output/folder)!=report[key]:raise ValueError('retained metric regrade differs')
    if normalized_prediction(output/'baseline')!=normalized_prediction(output/'baseline-replay') or sha(output/'baseline/maps.npy')!=sha(output/'baseline-replay/maps.npy'):
        raise ValueError('baseline replay differs')
    constant=report['constant_metrics'];oracle=report['private_mask_diagnostic_metrics']
    if constant['macro_image_auroc']!=.5 or constant['macro_resampled_pixel_auroc']!=.5 or oracle['macro_image_auroc']!=1. or oracle['macro_resampled_pixel_auroc']!=1.:
        raise ValueError('metric diagnostic expectation differs')
    if np.any(np.load(output/'constant/maps.npy',allow_pickle=False,mmap_mode='r')) or not np.array_equal(np.load(output/'private-mask-diagnostic/maps.npy',allow_pickle=False,mmap_mode='r'),np.load(development.parent/'evaluator/masks.npy',allow_pickle=False,mmap_mode='r')):
        raise ValueError('constant or private-mask diagnostic construction differs')
    controls=report['malformed_prediction_controls']
    if len(controls)!=4 or {row['control'] for row in controls}!={'missing_id','reordered_ids','missing_threshold','nonfinite_threshold'} or not all(row['rejected'] is True for row in controls):raise ValueError('malformed prediction controls incomplete')
    if controls!=malformed_controls(read(development.parent/'public/index.json'),read(output/'baseline/predictions.json')):raise ValueError('malformed prediction recheck differs')
    return dict(integrity_passed=True,source_images=10821,official_public_test_images=2162,categories=12,
        baseline_macro_image_auroc=report['baseline_metrics']['macro_image_auroc'],
        baseline_macro_resampled_pixel_auroc=report['baseline_metrics']['macro_resampled_pixel_auroc'],
        native_case_count_added=0,model_api_calls=0,report_sha256=sha(report_path),
        scope='Current-source original bytes, cached RGB/mask/index commitments, retained predictions/replays and metric regrade. This offline audit does not refit, regenerate all RGB inputs, establish an untrusted-agent sandbox or turn the private-mask diagnostic into a model result.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['run','audit'])
    parser.add_argument('--destination',default='runs/visual-inspection-development-v1');parser.add_argument('--output-dir',default='runs/visual-inspection-qualification-v1');parser.add_argument('--report')
    args=parser.parse_args()
    if args.command=='run':
        result=run(ROOT/args.destination,ROOT/args.output_dir)
        print(json.dumps(dict(integrity_passed=result['integrity_passed'],metrics=result['baseline_metrics'])))
    else:
        result=audit(ROOT/(args.report or f'{args.output_dir}/qualification.json'));save(ROOT/'reports/visual-inspection-audit.json',result);print(json.dumps(result))
