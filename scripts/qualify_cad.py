"""CAD reference geometry, timed worker replays and geometric counterexamples.

This is author-reference consistency, never a vision/model leaderboard result.
"""
from copy import deepcopy
from pathlib import Path
import gzip
import hashlib
import importlib.util
import json
from faraday_manufacturing_benchmark.cad_cases import catalog,build,box
from faraday_manufacturing_benchmark.cad_kernel import execute,compare,measure,versions
from faraday_manufacturing_benchmark.cad import public_packet,grade_candidate,replay,summary
from faraday_manufacturing_benchmark.shopfloor import digest
ROOT=Path(__file__).resolve().parents[1]


def main():
    output=ROOT/'runs/qualification/cad';output.mkdir(parents=True,exist_ok=True);episodes=[];rows=[]
    for i,t in enumerate(catalog(),1):
        source=build(t);program=source['program'];packet=public_packet(t);answer=dict(program=program)
        result=grade_candidate(t,answer);episode=dict(evaluator_task_id=t['id'],source_commitment=digest(t),public_input=packet,answer=answer,result=result,status='finished',kernel_timeout_seconds=30)
        replayed=replay(t,episode);episodes.append(episode)
        target=execute(program);bounds=measure(target)['bounds_mm'];size=[bounds[j+3]-bounds[j] for j in range(3)]
        mutants=dict(stale_revision=source['baseline_program'],wrong_datum=dict(op='translate',shape=deepcopy(program),vector=[1,0,0]),bounding_box_only=box(size,bounds[:3]))
        mutation_results={name:compare(target,execute(candidate))['strict_success'] for name,candidate in mutants.items()}
        advanced_omission=None
        if t['family'] in ('rounded_plate','chamfered_pocket','tapered_hub','lofted_adapter'):
            def omit(node):
                node=deepcopy(node);op=node['op']
                if op in ('fillet','chamfer'):return node['shape']
                if op=='cone':return dict(op='cylinder',radius=node['radius1'],height=node['height'],origin=node['origin'],axis=node['axis'])
                if op=='loft_rectangles':
                    first,last=node['sections'][0],node['sections'][-1]
                    return box(first['size']+[last['origin'][2]-first['origin'][2]],first['origin'])
                for key,value in list(node.items()):
                    if isinstance(value,dict) and 'op' in value:node[key]=omit(value)
                    elif isinstance(value,list):node[key]=[omit(v) if isinstance(v,dict) and 'op' in v else v for v in value]
                return node
            advanced_omission=compare(target,execute(omit(program)))['strict_success']
        path=output/(t['id']+'.json.gz');path.write_bytes(gzip.compress(json.dumps(episode,sort_keys=True,allow_nan=False).encode(),mtime=0))
        rows.append(dict(task_id=t['id'],strict_success=result['strict_success'],kernel_replay_strict=replayed['strict_success'],geometric_mutations=mutation_results,
            advanced_operation_omitted_strict_success=advanced_omission,
            receipt=str(path.relative_to(ROOT)),receipt_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        if i%4==0:print(f'{i}/{len(catalog())} CAD cases graded and replayed through supervised workers',flush=True)
    source_paths=list((ROOT/'src').rglob('*.py'))+[Path(__file__).resolve(),ROOT/'examples/cad_plate_agent.py',ROOT/'src/faraday_manufacturing_benchmark/data/cad_assets/manifest.json']
    report=dict(track='manufacturing-cad-qualification',control='Author-reference geometry consistency with real B-rep Boolean grading and supervised-worker replay; NOT independent CAD expertise or image-model performance.',
        source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(source_paths)},kernel_versions=versions(),summary=summary(episodes),
        kernel_replay_successes=sum(r['kernel_replay_strict'] for r in rows),geometric_mutations=sum(len(r['geometric_mutations']) for r in rows),geometric_mutations_rejected=sum(not passed for r in rows for passed in r['geometric_mutations'].values()),cases=rows,
        advanced_operation_omissions=sum(r['advanced_operation_omitted_strict_success'] is not None for r in rows),advanced_operation_omissions_rejected=sum(r['advanced_operation_omitted_strict_success'] is False for r in rows),
        limitations=['Synthetic dimensioned parts and limited CSG grammar; no arbitrary industrial CAD validation.','Image-only and revision inputs are qualified as source/geometry contracts, not solved by a measured vision model.','Revision edits accept a rebuilt matching solid and do not prove feature-history preservation.','Supervised kernel timeouts and input bounds are not complete OS/container isolation.','Public development cases, not contamination-resistant held-outs.'])
    (ROOT/'reports/cad-qualification.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    passed=all(r['strict_success'] and r['kernel_replay_strict'] and all(not value for value in r['geometric_mutations'].values()) and r['advanced_operation_omitted_strict_success'] is not True for r in rows)
    print(json.dumps(dict(passed=passed,cases=len(rows),strict_successes=report['summary']['strict_successes'],kernel_replays=report['kernel_replay_successes'],geometric_mutations=report['geometric_mutations'],geometric_mutations_rejected=report['geometric_mutations_rejected'])))
    return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
