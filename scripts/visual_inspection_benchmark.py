"""VisA public visual-inspection development extension; no native task inflation."""
from __future__ import annotations

from collections import Counter, defaultdict
import argparse
import csv
import hashlib
import json
from pathlib import Path
import platform

from fetch_visual_inspection import ROOT, REPOSITORY_SHA, sha, save, verify as verify_source

SIZE=64
ARCHIVE_SHA='2eb8690c803ab37de0324772964100169ec8ba1fa3f7e94291c9ca673f40f362'
PROTOCOL='visa-visual-inspection-development/1'


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def read(path):return json.loads(Path(path).read_text())


def mask_grid(image,size=SIZE):
    """Float area resampling keeps any nonzero contributing defect occupancy."""
    import numpy as np
    from PIL import Image
    binary=np.asarray(image)>0
    if binary.ndim!=2:raise ValueError('annotation must be a single-channel mask')
    return np.asarray(Image.fromarray(binary.astype(np.float32)).resize((size,size),Image.Resampling.BOX))>0


def partition(rows,source):
    """Official test is unchanged; only normal training is grouped into fit/cal."""
    labels={row['label'] for row in rows}
    if labels!={'normal','anomaly'}:raise ValueError('unknown image label')
    groups=defaultdict(set)
    for row in rows:
        if row['split'] not in ('train','test') or (row['split']=='train' and row['label']!='normal'):
            raise ValueError('official one-class split is invalid')
        groups[source['raw_files'][row['image']]['sha256']].add(row['split'])
    if any(len(value)>1 for value in groups.values()):
        raise ValueError('identical image content crosses official train/test split')
    result=[]
    for row in rows:
        content=source['raw_files'][row['image']]['sha256']
        split='test' if row['split']=='test' else 'calibration' if int(digest(['normal-calibration-v1',content])[:8],16)%5==0 else 'fit'
        result.append(split)
    return result


def prepare(source_root,destination):
    import numpy as np
    from PIL import Image, __version__ as pillow_version
    source_root=Path(source_root).resolve();destination=Path(destination).resolve()
    if destination.exists():raise ValueError('refusing to overwrite frozen visual development preparation')
    source_check=verify_source(source_root);source=read(source_root/'manifest.json')
    if source['archive_sha256']!=ARCHIVE_SHA:raise ValueError('official archive SHA differs from acquired pin')
    if source['fetcher_sha256']!=sha(ROOT/'scripts/fetch_visual_inspection.py'):raise ValueError('source acquisition implementation changed')
    rows=list(csv.DictReader((ROOT/source['repository']/'split_csv/1cls.csv').open()))
    splits=partition(rows,source);test_count=splits.count('test')
    destination.mkdir(parents=True);public=destination/'public';evaluator=destination/'evaluator';public.mkdir();evaluator.mkdir()
    images=np.lib.format.open_memmap(public/'images.npy',mode='w+',dtype=np.uint8,shape=(len(rows),SIZE,SIZE,3))
    masks=np.lib.format.open_memmap(evaluator/'masks.npy',mode='w+',dtype=np.bool_,shape=(test_count,SIZE,SIZE))
    index=[];truth=[];test_index=0;ids=set();counts=Counter();pixel_counts=Counter()
    for array_index,(row,split) in enumerate(zip(rows,splits,strict=True)):
        raw=source_root/'raw'/row['image'];identity='photo-'+digest(['visa-development-v1',row['image'],source['raw_files'][row['image']]['sha256']])[:24]
        if identity in ids:raise ValueError('public ID collision')
        ids.add(identity)
        with Image.open(raw) as image:
            image.load();original_size=image.size
            images[array_index]=np.asarray(image.convert('RGB').resize((SIZE,SIZE),Image.Resampling.BILINEAR))
        label=row['label']=='anomaly';original_pixels=0
        if bool(row['mask'])!=label:raise ValueError('anomaly annotation presence differs from image label')
        if row['mask']:
            with Image.open(source_root/'raw'/row['mask']) as mask:
                mask.load()
                if mask.size!=original_size:raise ValueError('mask/image pixel dimensions differ')
                original_pixels=int((np.asarray(mask)>0).sum());grid=mask_grid(mask)
                if not original_pixels or not grid.any():raise ValueError('positive annotation lost or empty')
        else:grid=np.zeros((SIZE,SIZE),dtype=np.bool_)
        record=dict(id=identity,category=row['object'],split=split,array_index=array_index)
        if split=='test':record['test_index']=test_index;masks[test_index]=grid;test_index+=1
        index.append(record);counts[(row['object'],split)]+=1
        pixel_counts['source_annotated_pixels']+=original_pixels
        truth.append(dict(id=identity,label=int(label),source_image=row['image'],source_mask=row['mask'],
            original_size=list(original_size),original_defect_pixels=original_pixels,resampled_defect_pixels=int(grid.sum()),split=split))
        if (array_index+1)%2000==0:print(json.dumps(dict(prepared_images=array_index+1)),flush=True)
    images.flush();masks.flush();del images,masks
    save(public/'index.json',dict(protocol=PROTOCOL,image_size=[SIZE,SIZE],records=index,
        note='RGB image arrays and category/fit/calibration/test partitions only. IDs exclude source label/path. Official public test labels/masks are not in this payload; this is not a private holdout.'))
    save(evaluator/'truth.json',truth)
    files={str(path.relative_to(destination)):sha(path) for folder in (public,evaluator) for path in folder.iterdir() if path.is_file()}
    manifest=dict(protocol=PROTOCOL,source=str(source_root.relative_to(ROOT)),source_manifest_sha256=source_check['manifest_sha256'],
        source_archive_sha256=source['archive_sha256'],source_repository_revision=source['repository_revision'],
        source_images=len(rows),source_masks=source_check['masks'],categories=sorted({row['object'] for row in rows}),
        official_test_images=test_count,normal_fit_images=splits.count('fit'),normal_calibration_images=splits.count('calibration'),
        partition_counts={':'.join(key):value for key,value in sorted(counts.items())},pixel_counts=dict(pixel_counts),
        size=SIZE,image_resize='Pillow RGB bilinear',mask_resize='float binary foreground area average > 0',
        files=files,generator_sha256=sha(__file__),native_case_count_added=0,
        runtime=dict(python=platform.python_version(),numpy=np.__version__,pillow=pillow_version),
        license='VisA images/masks: CC BY 4.0, Zou et al. ECCV 2022. Derived 64x64 RGB arrays/masks resampled here; original source bytes retained.',
        scope='Public-source real photographed inspection development data. Published test is preserved, but is not a private, temporally prospective, customer-site or manufacturing-workflow holdout. Pixel metrics are on resampled 64x64 grids, not official full-resolution VisA results.')
    save(destination/'manifest.json',manifest);return manifest


def auroc(labels,scores):
    """Exact Mann-Whitney AUC with half credit for ties; no sklearn dependency."""
    import numpy as np
    labels=np.asarray(labels);scores=np.asarray(scores,dtype=np.float64)
    if labels.shape!=scores.shape or not np.isfinite(scores).all() or not np.isin(labels,[0,1]).all():raise ValueError('invalid AUC inputs')
    labels=labels.ravel();scores=scores.ravel();positive=int(labels.sum());negative=len(labels)-positive
    if not positive or not negative:raise ValueError('AUC requires both label classes')
    order=np.argsort(scores,kind='stable');ordered=scores[order];ordered_labels=labels[order]
    starts=np.r_[0,np.flatnonzero(ordered[1:]!=ordered[:-1])+1];ends=np.r_[starts[1:],len(scores)]
    group_positive=np.add.reduceat(ordered_labels.astype(np.int64),starts)
    group_negative=(ends-starts)-group_positive
    preceding_negative=np.cumsum(group_negative)-group_negative
    numerator=np.sum(group_positive*(preceding_negative+group_negative*.5),dtype=np.float64)
    return float(numerator/(positive*negative))


def confusion(labels,predicted):
    import numpy as np
    y=np.asarray(labels,dtype=np.bool_);p=np.asarray(predicted,dtype=np.bool_)
    if y.shape!=p.shape:raise ValueError('prediction/label shape mismatch')
    tp=int((y&p).sum());fp=int((~y&p).sum());fn=int((y&~p).sum());tn=int((~y&~p).sum())
    return dict(tp=tp,fp=fp,fn=fn,tn=tn,f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.,
        recall=tp/(tp+fn) if tp+fn else 0.,precision=tp/(tp+fp) if tp+fp else 0.,
        false_positive_rate=fp/(fp+tn) if fp+tn else 0.)


def validate_predictions(index,prediction):
    import numpy as np
    tests=[row for row in index['records'] if row['split']=='test']
    if prediction['ids']!=[row['id'] for row in tests]:raise ValueError('prediction order/ID closure differs')
    if set(prediction['thresholds'])!={row['category'] for row in tests}:raise ValueError('category thresholds missing')
    for value in prediction['thresholds'].values():
        if set(value)!={'image','pixel'} or any(type(v) not in (int,float) or not np.isfinite(v) or v<0 for v in value.values()):
            raise ValueError('invalid normal-calibration threshold')
    return tests


def evaluate(destination,predictions):
    import numpy as np
    destination=Path(destination);predictions=Path(predictions);manifest=read(destination/'manifest.json')
    index=read(destination/'public/index.json');truth=read(destination/'evaluator/truth.json');metadata=read(predictions/'predictions.json')
    tests=validate_predictions(index,metadata);scores=np.load(predictions/'maps.npy',allow_pickle=False,mmap_mode='r')
    masks=np.load(destination/'evaluator/masks.npy',allow_pickle=False,mmap_mode='r')
    if scores.shape!=masks.shape or scores.shape!=(len(tests),SIZE,SIZE) or scores.dtype!=np.float32 or not np.isfinite(scores).all() or (scores<0).any():raise ValueError('invalid anomaly map')
    labels={row['id']:row['label'] for row in truth};categories={}
    for category in manifest['categories']:
        rows=[(i,row) for i,row in enumerate(tests) if row['category']==category];positions=[i for i,_ in rows]
        y=np.array([labels[row['id']] for _,row in rows],dtype=np.uint8);maps=np.asarray(scores[positions])
        gt=np.asarray(masks[positions]);image_scores=maps.reshape(len(rows),-1).mean(axis=1) # fixed mean anomaly score, not tuned on test
        threshold=metadata['thresholds'][category]
        categories[category]=dict(images=len(rows),normal=int((y==0).sum()),anomalous=int(y.sum()),
            image_auroc=auroc(y,image_scores),resampled_pixel_auroc=auroc(gt,maps),
            image_at_normal_calibration=confusion(y,image_scores>threshold['image']),
            pixel_at_normal_calibration=confusion(gt,maps>threshold['pixel']))
    return dict(categories=categories,macro_image_auroc=float(np.mean([row['image_auroc'] for row in categories.values()])),
        macro_resampled_pixel_auroc=float(np.mean([row['resampled_pixel_auroc'] for row in categories.values()])),
        macro_image_f1=float(np.mean([row['image_at_normal_calibration']['f1'] for row in categories.values()])),
        macro_pixel_f1=float(np.mean([row['pixel_at_normal_calibration']['f1'] for row in categories.values()])),
        scope='Equal-weight category macro metrics. Thresholds calibrated only on held-out normal training images. 64x64 area-resampled binary masks; not official full-resolution VisA leaderboard scores or operational quality-release evidence.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare');p.add_argument('--source',default='runs/visual-inspection-data-v1');p.add_argument('--destination',default='runs/visual-inspection-development-v1')
    p=sub.add_parser('evaluate');p.add_argument('--destination',default='runs/visual-inspection-development-v1');p.add_argument('--predictions',required=True)
    args=parser.parse_args()
    if args.command=='prepare':
        result=prepare(ROOT/args.source,ROOT/args.destination);print(json.dumps({key:result[key] for key in ('source_images','official_test_images','normal_fit_images','normal_calibration_images')}))
    else:print(json.dumps(evaluate(ROOT/args.destination,ROOT/args.predictions)))
