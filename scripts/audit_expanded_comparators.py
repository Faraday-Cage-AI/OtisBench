"""Dated additional primary-source survey; no ranking or added native coverage."""
from collections import Counter
import argparse
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlparse
ROOT=Path(__file__).resolve().parents[1]
CACHE=ROOT/'runs/expanded-survey/2026-11-01'
CONFIG=ROOT/'docs/comparators/expanded-survey-2026-11-01.json'
REPORT=ROOT/'reports/expanded-comparator-audit.json'
REPOSITORIES={'iab':'masahirosakae/industrial-agent-benchmark','fieldwork':'FujitsuResearch/FieldWorkArena','semikong':'blobfishai/semiconductor-agent-simulation','businessbench':'erphq/business-bench'}
PRIMARY_HOSTS={'en-documents.research.global.fujitsu.com','arxiv.org','blobfish.ai','www.pallet.com','huggingface.co','robustmad.github.io','www.amazon.science'}
IDS={'iab','fieldwork','semikong','businessbench','agentds','pallet-memory','supchain','industrybench','phmforge','diagnosticiq','robustmad','sopbench'}


def read(path):return json.loads(Path(path).read_text())
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def local(name):
    path=(ROOT/name).resolve()
    if not path.is_relative_to(ROOT):raise ValueError('survey artifact outside checkout')
    return path
def require(ok,message):
    if not ok:raise ValueError(message)


def validate_config(config):
    require(config.get('schema')=='expanded-industrial-comparator-survey/1','unsupported survey schema')
    rows=config['resources'];require(len(rows)==12 and {r['id'] for r in rows}==IDS,'missing, duplicate or extra survey resource')
    require(config['exhaustive_world_survey'] is False and config['common_model_ranking'] is False and config['native_cases_added']==0,'unsupported survey promotion')
    require(config['additional_named_resources']==12 and config['original_selected_comparators']==6,'survey count scope changed')
    require(all(r['relationship'] in ('direct','adjacent') and r['source_ids'] and r['faraday_gap'] for r in rows),'incomplete survey classification')
    return config


def canonical_database(path):
    """Reconstruct the publisher's replay comparison from retained SQLite bytes."""
    import sqlite3,tempfile
    blob=gzip.decompress(Path(path).read_bytes())
    with tempfile.TemporaryDirectory(prefix='business-db-regrade-') as directory:
        database=Path(directory)/'retained.sqlite';database.write_bytes(blob)
        connection=sqlite3.connect('file:'+str(database)+'?mode=ro',uri=True)
        quoted=lambda name:'"'+name.replace('"','""')+'"'
        tables=[r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        state={}
        for table in tables:
            columns=[r[1] for r in connection.execute('PRAGMA table_info('+quoted(table)+')') if not(table=='audit_events' and r[1]=='wall_time')]
            values=connection.execute('SELECT '+','.join(quoted(c) for c in columns)+' FROM '+quoted(table)).fetchall()
            state[table]=dict(columns=columns,rows=sorted(map(repr,values)))
        connection.close()
    return hashlib.sha256(json.dumps(state,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def build_report():
    from run_semikong_comparator import verified_source
    config=validate_config(read(CONFIG));bindings={}
    def bind(path):
        path=local(path);bindings[str(path.relative_to(ROOT))]=sha(path)
    pins=read(CACHE/'repository-pins.json');require(set(pins)=={'iab','fieldwork','semikong','businessbench'},'repository capture incomplete')
    source_ids=set();repositories={}
    for key,pin in pins.items():
        root=CACHE/key;commit=read(root/'commit.json');tree=read(root/'tree.json')
        require(pin['repository']==REPOSITORIES[key] and read(root/'repository.json')['full_name'].casefold()==pin['repository'].casefold(),'unexpected primary repository identity')
        require(commit['sha']==pin['commit'] and tree.get('truncated') is False and tree['sha'] in {pin['commit'],commit['commit']['tree']['sha']},'repository commit/tree differs')
        entries={r['path']:r for r in tree['tree'] if r['type']=='blob'}
        def git_file(path,name):
            data=Path(path).read_bytes();actual=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
            require(actual==entries[name]['sha'],'pinned source blob differs: '+key+'/'+name);bind(path)
        git_file(root/'README.source','README.md')
        for path in (root/'source').rglob('*'):
            if not path.is_file():continue
            name=path.relative_to(root/'source').as_posix()
            if name in entries:git_file(path,name)
            elif path.suffix=='.py' and '.cache' not in path.parts:raise ValueError('untracked code in partial source checkout: '+name)
        for name in ['commit.json','tree.json','repository.json']:bind(root/name)
        repositories[key]=dict(repository=pin['repository'],commit=pin['commit'],pinned_tree_blobs=len(entries),partial_checkout=True)
        source_ids.add('repo:'+key)
    inventory=read(CACHE/'publication-inventory.json');publications={}
    for row in inventory:
        require(row['id'] not in publications,'duplicate publication record');path=local(row['path'])
        parsed=urlparse(row['url']);require(parsed.scheme=='https' and parsed.hostname in PRIMARY_HOSTS,'non-primary publication URL')
        require(path.parent==CACHE/'publications' and row['status']=='available' and sha(path)==row['sha256'],'publication capture missing or changed')
        publications[row['id']]=dict(url=row['url'],sha256=row['sha256'],bytes=path.stat().st_size);source_ids.add('pub:'+row['id']);bind(path)
    for row in config['resources']:require(set(row['source_ids'])<=source_ids,'referenced primary source unavailable')
    # Executable schema validation only; the source explicitly disclaims its
    # placeholder overlap scorer as an official model-comparison metric.
    iab=CACHE/'iab/source';dataset=iab/'data/v2/test.jsonl';records=[json.loads(line) for line in dataset.read_text().splitlines() if line.strip()]
    require(len(records)==180 and len({r['id'] for r in records})==180,'IAB record coverage changed')
    category=dict(Counter(r['category'] for r in records));require(category==dict(agent=60,knowledge=60,reasoning=60),'IAB layer counts changed')
    readme=(CACHE/'iab/README.source').read_text();require('placeholder' in readme and 'rule_based_token_overlap_v2' in readme,'IAB scoring status requires review')
    validated=subprocess.run([sys.executable,'-I','-S',str(iab/'scripts/validate_hf_dataset_v2.py'),str(dataset)],capture_output=True,text=True,timeout=30)
    require(validated.returncode==0,'unchanged IAB JSONL validator failed')
    # Regrade all retained local SemiKong episodes with unmodified pinned code.
    source,hashes=verified_source();selected=local(config['selected_local_reproductions']['semikong']);semi=read(selected)
    require(semi['passed'] and semi['source_sha256']==hashes and semi['runner_sha256']==sha(ROOT/'scripts/run_semikong_comparator.py'),'SemiKong reproduction source changed')
    require(semi['retained_episode_count']==800,'SemiKong local coverage incomplete')
    for name,expected in semi['files'].items():require(sha(selected.parent/name)==expected,'SemiKong episode artifact changed');bind(selected.parent/name)
    published=read(source/'benchmark/semikongbench100/release/huggingface/qualification.json')
    require(semi['qualification']==published==read(selected.parent/'qualification.json'),'local/publisher qualification differs')
    sys.path.insert(0,str(source))
    try:
        from benchmark.semikongbench100 import evaluation as evaluation
        from benchmark.semikongbench100.spec import build_tasks
        tasks={t['task_id']:t for t in build_tasks()};episodes=read(selected.parent/'episodes.json');coverage=Counter()
        labels={'oracle','oracle_replay','noop','shortcut','state_only','wrong_source','wrong_target','unsafe_release'}
        for row in episodes:
            require(row['task_id'] in tasks and row['policy'] in labels,'unknown SemiKong episode')
            receipt=json.loads(gzip.decompress((selected.parent/row['receipt']).read_bytes()))
            require(receipt['task_id']==row['task_id'] and receipt['verdict']['passed']==row['passed'] and receipt['verdict']['score']==row['score'],'SemiKong episode summary differs')
            policy='oracle' if row['policy']=='oracle_replay' else row['policy']
            expected_steps=evaluation.policy_steps(tasks[row['task_id']],policy)
            actual_steps=[dict(tool=entry['tool'],arguments=entry['arguments']) for entry in receipt['trace']]
            require(actual_steps==[dict(tool=step['tool'],arguments=step.get('arguments',{})) for step in expected_steps],'retained trajectory is not the declared upstream control policy')
            require(evaluation.score_episode(tasks[row['task_id']],receipt['before'],receipt['after'],receipt['trace'])==receipt['verdict'],'retained SemiKong verdict does not regrade')
            coverage[row['task_id'],row['policy']]+=1
        require(len(episodes)==800 and set(coverage)=={(t,label) for t in tasks for label in labels} and all(n==1 for n in coverage.values()),'SemiKong task/policy coverage differs')
        semikong_categories=dict(Counter(t['metadata']['category'] for t in tasks.values()));semikong_fabs=len({t['fab_id'] for t in tasks.values()})
    finally:sys.path.remove(str(source))
    business_paths=[r['path'] for r in read(CACHE/'businessbench/tree.json')['tree'] if r['type']=='blob' and r['path'].startswith('tasks/process/') and r['path'].endswith('/task.yaml')]
    require('7 implemented tasks' in (CACHE/'businessbench/README.source').read_text() and len(business_paths)==9,'Business Bench documented/defined count scopes changed')
    business=dict(publisher_documented_implemented=7,pinned_task_definitions=9,selected_local_reproduction=None,status='not_included_as_completed_in_this_checkpoint')
    selected_business=config['selected_local_reproductions']['businessbench']
    if selected_business:
        path=local(selected_business);record=read(path);bind(path)
        from run_business_comparator import sources as business_sources
        require(record['source_sha256']==business_sources() and record['runner_sha256']==sha(ROOT/'scripts/run_business_comparator.py'),'Business Bench reproduction source changed')
        for name,expected in record['files'].items():require(sha(path.parent/name)==expected,'Business Bench retained artifact changed');bind(path.parent/name)
        validation=record['validation'];expected={(Path(p).parent.name,seed) for p in business_paths for seed in validation['seeds']}
        rows=validation['scenarios'];require(len(rows)==len(expected) and {(r['task'],r['seed']) for r in rows}==expected,'Business Bench scenario coverage incomplete')
        require(validation['status']=='complete' and record['passed']==all(r['passed'] for r in rows),'Business Bench completion verdict inconsistent')
        pairs={};reference_builders=0
        for episode in validation['episodes']:
            result=read(path.parent/episode['receipt'])
            require(result.get('passed')==episode['passed'] and result.get('error')==episode['error'],'Business Bench retained attempt summary differs')
            if episode['reference_build']:reference_builders+=1
            elif episode['harness']=='oracle':pairs.setdefault((episode['task'],episode['seed']),{})[episode['run']]=episode
        for key,pair in pairs.items():
            require(set(pair)=={1,2} and all(pair[n]['database'] for n in (1,2)),'incomplete Business Bench oracle replay pair')
            require(canonical_database(path.parent/pair[1]['database'])==canonical_database(path.parent/pair[2]['database']),'Business Bench retained oracle database replay differs')
        failed=[dict(task=r['task'],seed=r['seed'],problems=r['problems']) for r in rows if not r['passed']]
        business.update(selected_local_reproduction=str(path.relative_to(ROOT)),status='completed_with_failures' if failed else 'completed',passed=record['passed'],
            attempted_task_seed_cells=len(rows),passed_cells=sum(r['passed'] for r in rows),failed_cells=failed,retained_policy_executions=len(validation['episodes']),
            retained_reference_builders=reference_builders,canonical_oracle_replay_pairs=len(pairs),
            retention_scope='Attempt result JSON and compressed final SQLite databases retained. Transient workspace note/deliverable files were not retained, so this does not independently regrade every textual deliverable check.')
    agent_meta=read(CACHE/'publications/agentds-metadata.source');description=(CACHE/'publications/agentds-description.source').read_text()
    require(agent_meta['cardData']['license']=='cc-by-nc-sa-4.0' and description.count('### Challenge ')==3,'AgentDS source scope/license changed')
    require(agent_meta['sha'] in publications['agentds-current-card']['url'] and agent_meta['sha'] in publications['agentds-description']['url'],'AgentDS card/description not pinned to captured metadata')
    levels={r['id']:r['declared_evidence_level'] for r in config['resources']}
    levels['semikong']='author_controls_reproduced';levels['iab']='record_schema_validated'
    if selected_business:levels['businessbench']='author_controls_reproduced' if business['passed'] else 'local_validation_failed'
    for path in [CONFIG,Path(__file__),CACHE/'repository-pins.json',CACHE/'publication-inventory.json',selected,ROOT/'scripts/run_semikong_comparator.py',ROOT/'scripts/run_business_comparator.py']:bind(path)
    report=dict(schema='expanded-comparator-evidence/1',assessment_date=config['assessment_date'],additional_named_resources=12,original_selected_resources=6,named_resources_reviewed=18,
        independent_dataset_count=None,count_policy='Named resources, not additive task coverage or proven independent datasets; adjacent SOP work is labeled and PHM/AssetOps lineage overlap is not assumed absent.',
        current_resource_levels=levels,repositories=repositories,publication_snapshots=publications,resources=config['resources'],
        iab=dict(records=180,categories=category,jsonl_schema_validation_passed=True,validator_stdout=validated.stdout,official_semantic_score_verified=False,placeholder_scoring=True),
        semikong=dict(local_author_qualification_passed=True,task_definitions=100,categories=semikong_categories,fabs=semikong_fabs,retained_episodes=800,
            oracle_passes=published['oracle']['passes'],exact_replays=published['determinism']['exact_episode_matches'],negative_episodes=sum(v['executions'] for v in published['negative_controls'].values()),negative_strict_false_accepts=sum(v['strict_passes'] for v in published['negative_controls'].values()),source_runtime_overlay=semi['runtime']['overlay']),
        businessbench=business,agentds=dict(dataset_commit=agent_meta['sha'],license=agent_meta['cardData']['license'],challenges=3,bulk_data_downloaded=False,redistributed=False,leaderboard_submission=False),
        search_queries=config['search_queries'],selection_rule=config['selection_rule'],exclusions=config['exclusions'],bindings=bindings,
        conclusion=dict(exhaustive_world_survey=False,common_model_ranking=False,independent_faraday_practitioner_validation=False,native_faraday_cases_added=0,world_superlative_established=False),
        scope='Expanded selected primary-resource review, one full unchanged upstream author qualification and IAB record-schema validation. Publisher assertions, code/schema inspection and local execution remain separate.')
    return report


def check(report_path=REPORT):
    report=read(report_path);require(report['schema']=='expanded-comparator-evidence/1','unknown expanded report')
    for name,expected in report['bindings'].items():require(sha(local(name))==expected,'expanded survey artifact changed: '+name)
    fresh=build_report();require(report==fresh,'expanded survey report stale or inconsistent')
    return dict(integrity_passed=True,named_resources=18,semikong_retained_episodes=800,world_superlative_established=False)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--check',action='store_true');a=p.parse_args()
    if not a.check:REPORT.write_text(json.dumps(build_report(),indent=2,sort_keys=True)+'\n')
    print(json.dumps(check()))
