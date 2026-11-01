"""Paired case-cluster bootstrap; draws stay grouped with their factory case."""
import random
from collections import defaultdict


def season_score(results):
    denominator=sum(r['demand_margin_cents'] for r in results)
    if not results or denominator<=0:raise ValueError('nonempty results with positive demand margin required')
    return 100*sum(r['profit_cents'] for r in results)/denominator


def paired_comparison(candidate,baseline,resamples=2000,seed=831):
    def index(rows):
        out={}
        for r in rows:
            k=(r['case_id'],r['draw'])
            if k in out:raise ValueError('duplicate case/draw')
            out[k]=r
        return out
    a=index(candidate);b=index(baseline)
    if a.keys()!=b.keys() or not a:raise ValueError('paired runs require exactly matching nonempty case/draw sets')
    grouped=defaultdict(list)
    for key in a:
        if a[key]['exogenous_commitment']!=b[key]['exogenous_commitment']:raise ValueError('different exogenous worlds')
        if not a[key].get('environment_commitment') or a[key]['environment_commitment']!=b[key].get('environment_commitment'):raise ValueError('different factory configuration or operating rules')
        grouped[key[0]].append(key)
    if len(grouped)<2:raise ValueError('at least two independent cases required for a cluster interval')
    if resamples<100:raise ValueError('at least 100 resamples required')
    rng=random.Random(seed);names=sorted(grouped);differences=[]
    for _ in range(resamples):
        keys=[key for name in rng.choices(names,k=len(names)) for key in grouped[name]]
        differences.append(season_score([a[k] for k in keys])-season_score([b[k] for k in keys]))
    differences.sort()
    return dict(candidate_score=season_score(candidate),baseline_score=season_score(baseline),
                difference=season_score(candidate)-season_score(baseline),
                interval_95=[differences[int(.025*(resamples-1))],differences[int(.975*(resamples-1))]],
                cases=len(grouped),draws=len(a),resamples=resamples)
