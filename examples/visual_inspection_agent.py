"""Label-free spatial RGB normal-appearance baseline, not a vision-language agent.

This script reads ONLY public image arrays/index records. It never opens source
filenames, evaluator masks, labels, or reference code. NumPy/Pillow versions and
source hashes are retained by the caller; no pretrained weights or paid API.
"""
import argparse
import json
from pathlib import Path
import time

import numpy as np


def score(images,mean,variance):
    return np.mean((images.astype(np.float32)/255.-mean)**2/(variance+.05**2),axis=-1,dtype=np.float32)


def run(public,output):
    start=time.perf_counter();public=Path(public);output=Path(output)
    if output.exists():raise ValueError('refusing to overwrite baseline outputs')
    output.mkdir(parents=True)
    index=json.loads((public/'index.json').read_text());records=index['records'];images=np.load(public/'images.npy',allow_pickle=False,mmap_mode='r')
    tests=[row for row in records if row['split']=='test'];size=images.shape[1]
    maps=np.lib.format.open_memmap(output/'maps.npy',dtype=np.float32,mode='w+',shape=(len(tests),size,size))
    thresholds={};fitted={};models={}
    for category in sorted({row['category'] for row in records}):
        fit=[row['array_index'] for row in records if row['category']==category and row['split']=='fit']
        calibration=[row['array_index'] for row in records if row['category']==category and row['split']=='calibration']
        if not fit or not calibration:raise ValueError('fit/calibration partition missing')
        train=images[fit].astype(np.float32)/255.;mean=train.mean(axis=0,dtype=np.float64).astype(np.float32);variance=train.var(axis=0,dtype=np.float64).astype(np.float32);del train
        normal_scores=score(images[calibration],mean,variance)
        thresholds[category]=dict(image=float(np.quantile(normal_scores.mean(axis=(1,2)),.95)),pixel=float(np.quantile(normal_scores,.995)))
        models[category+'__mean']=mean;models[category+'__variance']=variance
        positions=[(i,row['array_index']) for i,row in enumerate(tests) if row['category']==category]
        for position,array_index in positions:maps[position]=score(images[array_index],mean,variance)
        fitted[category]=dict(fit_images=len(fit),normal_calibration_images=len(calibration))
    maps.flush();del maps
    np.savez(output/'model.npz',**models)
    metadata=dict(ids=[row['id'] for row in tests],thresholds=thresholds,fit_counts=fitted,
        method='spatial RGB diagonal Gaussian squared residual; variance floor .05^2; mean channel/pixel image score',
        calibration='normal-only image quantile .95 and pixel quantile .995; no anomalous training/calibration data',
        elapsed_seconds=time.perf_counter()-start,model_calls=0)
    (output/'predictions.json').write_text(json.dumps(metadata,indent=2,sort_keys=True,allow_nan=False)+'\n')
    return metadata


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--public',required=True);parser.add_argument('--output',required=True);args=parser.parse_args()
    result=run(args.public,args.output);print(json.dumps(dict(test_images=len(result['ids']),elapsed_seconds=result['elapsed_seconds'])))
