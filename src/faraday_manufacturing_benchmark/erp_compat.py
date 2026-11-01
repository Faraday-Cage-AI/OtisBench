"""Separate real-Odoo compatibility adapter over pinned upstream ERP-Bench tasks.

Upstream cases keep their own provenance and grader. They are not native case
counts. All credentials, SQL snapshots and graders stay evaluator-side.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime,timezone
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import time
import uuid
from .agents import DecisionAgent
from .erp_protocol import VERSION,contract,validate,PolicyDenied
from .isolation import isolated_agent

UPSTREAM='https://github.com/agentic-labs/erp-bench'
REVISION='ceba3880af555129b5278e056a0c20f2fb5a0ba9'
LABEL='faraday.erp-compat.owner'
LEGACY_RESTORE='''#!/bin/bash
set -euo pipefail
pg_ctlcluster 18 main start
su postgres -s /bin/bash -c 'psql -v ON_ERROR_STOP=1' <<'SQL'
DO $$ BEGIN
IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='odoo') THEN
CREATE ROLE odoo LOGIN PASSWORD 'odoo' SUPERUSER CREATEDB CREATEROLE;
END IF;
END $$;
ALTER ROLE odoo WITH LOGIN PASSWORD 'odoo' SUPERUSER CREATEDB CREATEROLE;
SQL
su postgres -s /bin/bash -c 'createdb --owner=odoo bench'
su postgres -s /bin/bash -c 'pg_restore --exit-on-error --single-transaction --dbname=bench /bridge/baseline.dump'
mkdir -p "$(cat /bridge/data-dir)/filestore"
tar -xzf /bridge/filestore.tar.gz -C "$(cat /bridge/data-dir)/filestore"
odoo shell --config /etc/odoo/odoo.conf -d bench --no-http >/tmp/bridge-key.log 2>&1 <<'PYCODE'
from datetime import date,timedelta
admin=env.ref('base.user_admin')
key=env['res.users.apikeys'].sudo().with_user(admin.id)._generate('rpc','faraday-compat',date.today()+timedelta(days=90))
env.cr.commit()
print('BRIDGEKEY:'+key)
PYCODE
umask 077
grep '^BRIDGEKEY:' /tmp/bridge-key.log | cut -d: -f2- > /etc/odoo/api_key
rm /tmp/bridge-key.log
test -s /etc/odoo/api_key
touch -d "@$(cat /bridge/anchor-epoch)" /tmp/saas_setup_complete
rm -rf /setup /solution /tests
exec odoo --config /etc/odoo/odoo.conf --http-port=8069
'''
RESTORE=LEGACY_RESTORE.replace('test -s /etc/odoo/api_key\n', '''test -s /etc/odoo/api_key
if [ -f /bridge/repair_seeded_records.json ]; then
  install -m 600 /bridge/repair_seeded_records.json /tmp/repair_seeded_records.json
fi
''')
FIXTURE_PATH='/tmp/repair_seeded_records.json'
FIXTURE_NAME='repair_seeded_records.json'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False,separators=(',',':')).encode()).hexdigest()

def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n')


def command(args,*,timeout=120,input=None):
    result=subprocess.run(args,input=input,capture_output=True,timeout=timeout)
    if result.returncode:raise ValueError('Command '+str(args[0:2])+' failed: '+result.stderr.decode(errors='replace')[-1500:])
    return result


def fetch(url,path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    command(['curl','--fail','--silent','--show-error','--location','--proto','=https','--proto-redir','=https','--max-time','40','--max-filesize','15000000',url,'--output',str(path)],timeout=45)


def materialize(task_id,cache):
    if not re.fullmatch(r'\d{4}_[a-z0-9_]+',task_id):raise ValueError('invalid ERP task identifier')
    cache=Path(cache).resolve();index=cache/'upstream-tree.json'
    if not index.is_file():fetch(f'https://api.github.com/repos/agentic-labs/erp-bench/git/trees/{REVISION}?recursive=1',index)
    tree=json.loads(index.read_text())
    if tree.get('truncated') is not False:raise ValueError('upstream tree is incomplete')
    prefix='tasks/'+task_id+'/';rows=[r for r in tree['tree'] if r['type']=='blob' and r['path'].startswith(prefix)]
    if not rows:raise ValueError('task not found in pinned upstream catalog')
    root=cache/task_id;root.mkdir(parents=True,exist_ok=True);hashes={}
    for row in rows:
        relative=row['path'][len(prefix):];path=root/relative
        if not path.resolve().is_relative_to(root):raise ValueError('unsafe upstream file path')
        if not path.is_file():fetch(f'https://raw.githubusercontent.com/agentic-labs/erp-bench/{REVISION}/'+row['path'],path)
        blob=path.read_bytes()
        if hashlib.sha1(b'blob '+str(len(blob)).encode()+b'\0'+blob).hexdigest()!=row['sha']:raise ValueError('pinned task file mismatch: '+relative)
        hashes[relative]=sha(path)
    save(root/'source-manifest.json',dict(upstream=UPSTREAM,commit=REVISION,task_id=task_id,files=hashes));return root


def check_source(root):
    root=Path(root).resolve();source=json.loads((root/'source-manifest.json').read_text())
    if source['commit']!=REVISION:raise ValueError('unsupported upstream revision')
    for name,value in source['files'].items():
        path=(root/name).resolve()
        if not path.is_relative_to(root) or sha(path)!=value:raise ValueError('changed upstream task source')
    return source


def requires_repair_metadata(source):
    return '_repair_plan_' in source['task_id']


def validate_fixture_metadata(payload,state,required=False):
    if not isinstance(payload,dict) or set(payload)!={'purchase_orders','manufacturing_orders'}:raise ValueError('invalid repair fixture metadata schema')
    count=0
    for key,model,id_field in [('purchase_orders','purchase.order','po_id'),('manufacturing_orders','mrp.production','mo_id')]:
        entries=payload[key]
        if not isinstance(entries,dict) or len(entries)>10000 or not isinstance(state.get(model),list):raise ValueError('invalid repair fixture record inventory')
        records={row['id']:row for row in state[model]}
        for ref,row in entries.items():
            if not isinstance(ref,str) or not ref or not isinstance(row,dict) or set(row)!={id_field,'name','plan_ref'}:raise ValueError('invalid repair fixture record')
            identity=row[id_field]
            if type(identity) is not int or identity<=0 or identity not in records or row['name']!=records[identity]['name']:raise ValueError('repair fixture metadata disagrees with database identities')
            if row['plan_ref'] is not None and not isinstance(row['plan_ref'],str):raise ValueError('invalid repair plan reference')
            count+=1
    if required and not count:raise ValueError('repair task requires nonempty fixture metadata')
    return count


def snapshot_contract(manifest):
    version=manifest['format'];required=requires_repair_metadata(manifest['upstream'])
    expected=hashlib.sha256((LEGACY_RESTORE if version=='odoo-baseline/1' else RESTORE).encode()).hexdigest()
    if version not in ('odoo-baseline/1','odoo-baseline/2') or manifest.get('protocol')!=VERSION or manifest['protocol_sha256']!=sha(Path(__file__).with_name('erp_protocol.py')) or manifest['restore_sha256']!=expected:raise ValueError('snapshot protocol differs from current adapter')
    if version=='odoo-baseline/1' and required:raise ValueError('legacy repair snapshot omits required fixture metadata; recapture as odoo-baseline/2')
    fixtures=manifest.get('fixture_metadata',{})
    if not isinstance(fixtures,dict) or set(fixtures)-{FIXTURE_PATH}:raise ValueError('unsupported fixture metadata paths')
    if required and FIXTURE_PATH not in fixtures:raise ValueError('required repair fixture metadata missing')
    for target,row in fixtures.items():
        if not isinstance(row,dict) or set(row)!={'filename','sha256'} or row['filename']!=FIXTURE_NAME or manifest['files'].get(FIXTURE_NAME)!=row['sha256']:raise ValueError('fixture metadata commitment mismatch')
    return fixtures


class Container:
    def __init__(self,image,entrypoint=None,command_args=()):self.image=image;self.token=uuid.uuid4().hex;self.name='faraday-erp-'+self.token[:12];self.cid=None;self.entrypoint=entrypoint;self.command_args=list(command_args)
    def __enter__(self):
        if not re.fullmatch(r'sha256:[a-f0-9]{64}',self.image):raise ValueError('container image must be the captured immutable image ID')
        args=['docker','create','--name',self.name,'--label',LABEL+'='+self.token,'--cpus','3','--memory','4g','--pids-limit','256','--network','none']
        if self.entrypoint:args+=['--entrypoint',self.entrypoint]
        self.cid=command(args+[self.image]+self.command_args).stdout.decode().strip();return self
    def run(self,args,*,input=None,timeout=120):return command(['docker','exec']+(['-i'] if input is not None else [])+[self.cid]+args,input=input,timeout=timeout)
    def copy_in(self,source,destination):command(['docker','cp',str(source),self.cid+':'+destination])
    def copy_out(self,source,destination):Path(destination).parent.mkdir(parents=True,exist_ok=True);command(['docker','cp',self.cid+':'+source,str(destination)])
    def start(self):command(['docker','start',self.cid])
    def inspect(self):return json.loads(command(['docker','inspect',self.cid]).stdout)[0]
    def ready(self,marker=True,timeout=240):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            args=['docker','exec',self.cid,'bash','-c',('test -f /tmp/saas_setup_complete && ' if marker else '')+'curl -sf http://127.0.0.1:8069/web/database/selector >/dev/null']
            p=subprocess.run(args,capture_output=True,timeout=10)
            if p.returncode==0:return
            if not self.inspect()['State']['Running']:
                logs=subprocess.run(['docker','logs','--tail','50',self.cid],capture_output=True).stdout.decode(errors='replace')
                raise ValueError('ERP container stopped before readiness: '+logs[-4000:])
            time.sleep(1)
        raise ValueError('ERP readiness deadline exceeded')
    def __exit__(self,*args):
        if self.cid:
            obj=self.inspect()
            if obj['Config']['Labels'].get(LABEL)!=self.token:raise ValueError('refusing to remove an unowned container')
            subprocess.run(['docker','stop','--timeout','10',self.cid],capture_output=True,timeout=20)
            command(['docker','rm','--volumes',self.cid],timeout=30)


def install_gateway(container):
    path=Path(__file__).with_name('erp_protocol.py');container.run(['mkdir','-p','/bridge']);container.copy_in(path,'/bridge/gateway.py')


def gateway(container):return DecisionAgent(shlex.join(['docker','exec','-i',container.cid,'python3','/bridge/gateway.py']),timeout=40,max_reply_bytes=1100000)


def probe(bridge):
    from .erp_protocol import SPECS
    result={}
    for model in SPECS:
        fields=bridge.decide('erp_gateway',dict(model=model,method='fields_get',kwargs={}))
        if not fields['ok']:result[model]=fields;continue
        selected=sorted(set(fields['value'])&set(SPECS[model][0].split()));rows=[];offset=0
        while True:
            page=bridge.decide('erp_gateway',dict(model=model,method='search_read',kwargs=dict(domain=[],fields=selected,limit=200,offset=offset)))
            if not page['ok']:rows=page;break
            rows.extend(page['value'])
            if len(page['value'])<200:break
            offset+=200
            if offset>10000:raise ValueError('probe row budget exceeded')
        result[model]=rows
    return result


def prepare(case_dir,out,image):
    root=Path(case_dir).resolve();source=check_source(root);out=Path(out).resolve()
    if out.exists() and any(out.iterdir()):raise ValueError('snapshot output is not empty; use a new directory')
    out.mkdir(parents=True,exist_ok=True);fixtures={}
    image_info=json.loads(command(['docker','image','inspect',image]).stdout)[0];image_id=image_info['Id']
    config=(root/'environment/odoo.conf').read_text()+'\nmax_cron_threads = 0\n'
    with tempfile.TemporaryDirectory() as directory,Container(image_id) as container:
        config_file=Path(directory)/'odoo.conf';config_file.write_text(config)
        for name in ('setup_scenario.py','scenario_data.json'):container.copy_in(root/'environment'/name,'/setup/'+name)
        entrypoint=Path(directory)/'entrypoint.sh';entrypoint.write_bytes((root/'environment/entrypoint.sh').read_bytes());entrypoint.chmod(0o755)
        container.copy_in(entrypoint,'/usr/local/bin/harbor-entrypoint.sh');container.copy_in(config_file,'/etc/odoo/odoo.conf');container.start();container.ready();install_gateway(container)
        epoch=float(container.run(['stat','-c','%Y','/tmp/saas_setup_complete']).stdout)
        code="import json;from odoo.tools import config;config.parse_config(['-c','/etc/odoo/odoo.conf']);print(json.dumps({'data_dir':config['data_dir']}))"
        data_dir=json.loads(container.run(['python3','-c',code]).stdout)['data_dir']
        if not str(data_dir).startswith('/') or data_dir=='/':raise ValueError('invalid Odoo data directory')
        with (out/'baseline.dump').open('wb') as file:subprocess.run(['docker','exec',container.cid,'su','postgres','-s','/bin/sh','-c','pg_dump --format=custom bench'],stdout=file,stderr=subprocess.PIPE,check=True,timeout=120)
        # Empty filestores are represented explicitly; all SQL-backed files stay
        # within the copied application's data directory.
        container.run(['mkdir','-p',data_dir+'/filestore/bench'])
        with (out/'filestore.tar.gz').open('wb') as file:subprocess.run(['docker','exec',container.cid,'tar','-czf','-','-C',data_dir+'/filestore','bench'],stdout=file,stderr=subprocess.PIPE,check=True,timeout=120)
        exists=container.run(['python3','-c',f'from pathlib import Path; print(int(Path({FIXTURE_PATH!r}).is_file()))']).stdout.strip()==b'1'
        if requires_repair_metadata(source) and not exists:raise ValueError('upstream repair initialization did not produce required fixture metadata')
        if exists:
            container.copy_out(FIXTURE_PATH,out/FIXTURE_NAME);(out/FIXTURE_NAME).chmod(0o600)
            if (out/FIXTURE_NAME).stat().st_size>1024*1024:raise ValueError('fixture metadata exceeds one MiB')
            fixtures[FIXTURE_PATH]=dict(filename=FIXTURE_NAME,sha256=sha(out/FIXTURE_NAME))
        with gateway(container) as bridge:state=probe(bridge)
        if exists:validate_fixture_metadata(json.loads((out/FIXTURE_NAME).read_text()),state,requires_repair_metadata(source))
    (out/'odoo.conf').write_text(config);(out/'anchor-epoch').write_text(str(int(epoch)));(out/'data-dir').write_text(data_dir)
    save(out/'baseline-state.json',state)
    manifest=dict(format='odoo-baseline/2',upstream=source,case_dir=str(root),image_id=image_id,image_architecture=image_info['Architecture'],anchor_date=datetime.fromtimestamp(epoch,timezone.utc).date().isoformat(),cron_disabled=True,protocol=VERSION,protocol_sha256=sha(Path(__file__).with_name('erp_protocol.py')),restore_sha256=hashlib.sha256(RESTORE.encode()).hexdigest(),baseline_state_digest=digest(state),fixture_metadata=fixtures,files={p.name:sha(p) for p in out.iterdir() if p.is_file()},runtime_overlay='Existing immutable compatibility image plus cron disabled; restores SQL, filestore and declared private fixture metadata. Credentials regenerated evaluator-side.')
    save(out/'manifest.json',manifest);return manifest


@contextmanager
def restored(snapshot):
    root=Path(snapshot).resolve();manifest=json.loads((root/'manifest.json').read_text())
    fixtures=snapshot_contract(manifest)
    for name,value in manifest['files'].items():
        path=(root/name).resolve()
        if not path.is_relative_to(root) or sha(path)!=value:raise ValueError('snapshot artifact hash mismatch')
    check_source(manifest['case_dir'])
    with tempfile.TemporaryDirectory() as directory,Container(manifest['image_id'],entrypoint='/bin/bash',command_args=['/bridge/restore.sh']) as container:
        stage=Path(directory);stage.chmod(0o755);(stage/'restore.sh').write_text(RESTORE);container.copy_in(stage,'/bridge')
        for name in ['baseline.dump','filestore.tar.gz','anchor-epoch','data-dir']+[row['filename'] for row in fixtures.values()]:container.copy_in(root/name,'/bridge/'+name)
        container.copy_in(root/'odoo.conf','/etc/odoo/odoo.conf');container.start();container.ready();install_gateway(container)
        with gateway(container) as bridge:
            actual=probe(bridge)
            if digest(actual)!=manifest['baseline_state_digest']:raise ValueError('restored ERP baseline differs from captured business records')
            for target,row in fixtures.items():
                blob=container.run(['cat',target]).stdout
                if hashlib.sha256(blob).hexdigest()!=row['sha256']:raise ValueError('restored fixture metadata bytes differ')
                validate_fixture_metadata(json.loads(blob),actual,requires_repair_metadata(manifest['upstream']))
            runtime=deepcopy(manifest);runtime['restoration']=dict(executed_restore_sha256=hashlib.sha256(RESTORE.encode()).hexdigest(),snapshot_restore_sha256=manifest['restore_sha256'],legacy_nonrepair_compatibility=manifest['format']=='odoo-baseline/1',private_fixture_paths=sorted(fixtures))
            yield container,bridge,runtime


def grade(container,case_dir,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True);case=Path(case_dir)
    container.copy_in(case/'tests','/tests')
    result=container.run(['bash','/tests/test.sh'],timeout=300);(out/'verifier.log').write_bytes(result.stdout+result.stderr)
    container.copy_out('/logs/verifier/.',out/'verifier')
    value=json.loads((out/'verifier/reward.json').read_text());return dict(upstream_score=value['overall_score'],upstream_passed=value['passed'],verifier=value)


def run_agent(snapshot,agent_file,output,timeout=120):
    output=Path(output);trace=[];finished=False;error=None;critical=[]
    with restored(snapshot) as (container,bridge,manifest):
        goal=(Path(manifest['case_dir'])/'instruction.md').read_text().split('# Odoo Environment')[0].strip()
        try:
            with isolated_agent(agent_file,timeout) as agent:
                last=None
                for _ in range(300):
                    payload=dict(last_result=last,calls_remaining=300-len(trace))
                    if not trace:payload.update(task=dict(id='erp-business-task',goal=goal,anchor_date=manifest['anchor_date']),tools=contract())
                    reply=agent.decide('erp_compat',payload)
                    if reply=={'tool':'finish','arguments':{}}:trace.append(dict(decision=reply,result=dict(ok=True,finished=True)));finished=True;break
                    if set(reply)!={'tool','arguments'} or reply['tool']!='rpc':raise ValueError('expected rpc or finish decision')
                    try:validate(reply['arguments']);last=bridge.decide('erp_gateway',reply['arguments'])
                    except PolicyDenied as exc:critical.append(str(exc));last=dict(ok=False,error='policy_denied')
                    except (ValueError,TypeError,KeyError):last=dict(ok=False,error='invalid_rpc')
                    trace.append(dict(decision=deepcopy(reply),result=deepcopy(last)))
                isolation=agent.isolation
        except (ValueError,OSError) as exc:error=type(exc).__name__;isolation=None
        final=probe(bridge);result=grade(container,manifest['case_dir'],output.parent/(output.stem+'-evidence'))
        result['adapter_passed']=finished and not critical and result['upstream_passed']
        result['adapter_score']=0.0 if critical else result['upstream_score']
        episode=dict(track='erp-compatibility',protocol=VERSION,snapshot_manifest_sha256=sha(Path(snapshot)/'manifest.json'),snapshot_path=str(Path(snapshot).resolve()),source_task=manifest['upstream']['task_id'],upstream_revision=REVISION,fixture_restoration=manifest['restoration'],agent_isolation=isolation,status='stopped' if error else 'finished' if finished else 'budget_exhausted',error_type=error,critical_violations=critical,trace=trace,final_business_state_digest=digest(final),result=result)
        save(output,episode);return episode


def replay_episode(episode,output):
    snapshot=Path(episode['snapshot_path'])
    if sha(snapshot/'manifest.json')!=episode['snapshot_manifest_sha256']:raise ValueError('ERP snapshot changed')
    with restored(snapshot) as (container,bridge,manifest):
        for index,row in enumerate(episode['trace']):
            decision=row['decision']
            if decision=={'tool':'finish','arguments':{}}:
                if index!=len(episode['trace'])-1:raise ValueError('ERP finish must be the final trace action')
                actual=dict(ok=True,finished=True)
            else:
                try:validate(decision['arguments']);actual=bridge.decide('erp_gateway',decision['arguments'])
                except PolicyDenied:actual=dict(ok=False,error='policy_denied')
                except (ValueError,TypeError,KeyError):actual=dict(ok=False,error='invalid_rpc')
            if actual!=row['result']:raise ValueError(f'ERP replay response mismatch at {index}')
        state=probe(bridge)
        if digest(state)!=episode['final_business_state_digest']:raise ValueError('ERP replay business-state mismatch; wall-clock defaults are not normalized away')
        result=grade(container,manifest['case_dir'],Path(output))
        if result['verifier']!=episode['result']['verifier']:raise ValueError('ERP replay verifier mismatch')
        return dict(exact_responses=True,exact_business_state=True,exact_verifier=True,upstream_passed=result['upstream_passed'])


def main(argv=None):
    parser=argparse.ArgumentParser(prog='mfg-erp');sub=parser.add_subparsers(dest='command',required=True)
    fetcher=sub.add_parser('fetch');fetcher.add_argument('--task',required=True);fetcher.add_argument('--cache',required=True)
    prep=sub.add_parser('prepare');prep.add_argument('--case-dir',required=True);prep.add_argument('--output-dir',required=True);prep.add_argument('--image',required=True)
    run=sub.add_parser('run');run.add_argument('--snapshot',required=True);run.add_argument('--agent-file',required=True);run.add_argument('--output',required=True);run.add_argument('--timeout',type=float,default=120)
    replay=sub.add_parser('replay');replay.add_argument('episode');replay.add_argument('--output-dir',required=True)
    args=parser.parse_args(argv)
    try:
        if args.command=='fetch':print(materialize(args.task,args.cache))
        elif args.command=='prepare':print(json.dumps(prepare(args.case_dir,args.output_dir,args.image)))
        elif args.command=='run':print(json.dumps(run_agent(args.snapshot,args.agent_file,args.output,args.timeout)['result']))
        else:print(json.dumps(replay_episode(json.loads(Path(args.episode).read_text()),args.output_dir)))
    except (ValueError,OSError,subprocess.SubprocessError) as exc:parser.error(str(exc))
    return 0

if __name__=='__main__':raise SystemExit(main())
