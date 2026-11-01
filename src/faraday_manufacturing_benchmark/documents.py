"""Raw PDF/page tools and evidence-grounded procurement assessment grading."""
from copy import deepcopy
from functools import lru_cache
from importlib.resources import files
from io import BytesIO
import base64
import hashlib
import json
from pathlib import Path
import subprocess
from .document_cases import build,reference,POLICY,unique
from .grading import equal
from .shopfloor import digest

FACTS=('ordered_ea','delivered_ea','accepted_ea','shortfall_ea','net_invoice_cents','supported_payable_cents','approve_payment','release_lots','quarantine_lots','hold_reasons')
GROUPS=('purchase','receiving','quality','invoice')
TOOLS={'list_documents':{},'read_page':{'document_id':'issued document ID','page':'one-based integer','method':'text | ocr | image'},'finish':{'answer':'exact assessment object described by task answer_schema'}}


def answer_schema():
    lot=dict(type='object',properties={'lot_id':{'type':'string'},'units':{'type':'integer','minimum':1}},required=['lot_id','units'],additionalProperties=False)
    cite=dict(type='object',properties={'document_id':{'type':'string'},'page':{'type':'integer','minimum':1}},required=['document_id','page'],additionalProperties=False)
    fields={k:{'type':'integer','minimum':0} for k in FACTS[:6]};fields.update(line_id=dict(type='integer',enum=[1,2,3,4]),approve_payment=dict(type='boolean'),release_lots=dict(type='array',items=lot),quarantine_lots=dict(type='array',items=lot),hold_reasons=dict(type='array',items=dict(type='string',enum=['drawing_mismatch','short_receipt','damage','grade_deviation','certificate_mismatch','customs_hold','invoice_variance']),uniqueItems=True),evidence=dict(type='object',properties={g:dict(type='array',items=cite,minItems=1,uniqueItems=True) for g in GROUPS},required=list(GROUPS),additionalProperties=False))
    return dict(type='object',properties={'lines':dict(type='array',items=dict(type='object',properties=fields,required=list(fields),additionalProperties=False),minItems=4,maxItems=4)},required=['lines'],additionalProperties=False)


def assets(task):
    root=files('faraday_manufacturing_benchmark').joinpath('data/document_assets');manifest=json.loads(root.joinpath('manifest.json').read_text());entry=manifest['cases'][task['id']]
    if entry['spec_sha256']!=digest(build(task)):raise ValueError('document asset specification mismatch')
    return root.joinpath(task['id']),entry


def public_task(task):
    return dict(id='procurement-document-reconciliation',goal='Reconcile all four purchase lines using raw business documents and cite their pages. Return the required assessment through finish. This is document assessment, not execution of POs or payments.',evidence_mode=task['mode'],policy=POLICY,answer_schema=answer_schema(),max_tool_calls=120)


def normalized_fact(key,value):
    if key=='hold_reasons' and isinstance(value,list):return sorted(value)
    if key in ('release_lots','quarantine_lots') and isinstance(value,list):return sorted(value,key=lambda r:json.dumps(r,sort_keys=True))
    return value


def grade(task,answer,read_pages=None):
    expected,rules=reference(task)
    result=dict(task_id=task['id'],family=task['family'],domain='procurement_documents',mode=task['mode'],score=0.0,strict_success=False)
    from jsonschema import validate
    from jsonschema.exceptions import ValidationError
    try:
        validate(answer,answer_schema())
        rows={r['line_id']:r for r in answer['lines']}
        if set(rows)!={1,2,3,4}:return dict(result,error_type='InvalidLineCoverage')
    except (ValueError,TypeError,KeyError,ValidationError):return dict(result,error_type='InvalidAnswerSchema')
    facts=0;citations=0;diagnostics=[]
    for target in expected['lines']:
        i=target['line_id'];row=rows[i];matched={k:equal(normalized_fact(k,row[k]),normalized_fact(k,target[k]),0,0) for k in FACTS};facts+=sum(matched.values());evidence={}
        for group in GROUPS:
            provided=row['evidence'][group];got={(r['document_id'],r['page']) for r in provided};valid=len(got)==len(provided)
            if read_pages is not None:valid=valid and got<=read_pages
            if group!='invoice':required={(r['document_id'],r['page']) for r in rules[i]['required'][group]};valid=valid and got==required
            else:
                needed={(r['document_id'],r['page']) for r in rules[i]['invoice_required']};alternatives={(r['document_id'],r['page']) for r in rules[i]['invoice_alternatives']}
                valid=valid and needed<=got and bool(got&alternatives) and got<=needed|alternatives
            evidence[group]=valid;citations+=valid
        diagnostics.append(dict(line_id=i,facts=matched,evidence=evidence))
    result.update(score=round(70*facts/(4*len(FACTS))+30*citations/(4*len(GROUPS)),6),strict_success=facts==4*len(FACTS) and citations==4*len(GROUPS),line_diagnostics=diagnostics)
    return result


@lru_cache(maxsize=512)
def extracted(pdf,page):
    from pypdf import PdfReader
    return PdfReader(BytesIO(pdf)).pages[page-1].extract_text() or ''


@lru_cache(maxsize=128)
def ocr(png):
    result=subprocess.run(['tesseract','stdin','stdout','--psm','6','-l','eng'],input=png,capture_output=True,check=True,timeout=25)
    if len(result.stdout)>300000:raise ValueError('oversized OCR result')
    return result.stdout.decode('utf-8')


@lru_cache(maxsize=1)
def extractor_versions():
    import pypdf
    return dict(pypdf=pypdf.__version__,tesseract=subprocess.run(['tesseract','--version'],capture_output=True,text=True,timeout=5,check=True).stdout.splitlines()[0])


class DocumentWorld:
    def __init__(self,task):
        self.task=deepcopy(task);self.root,self.entry=assets(task);self.docs={d['id']:d for d in self.entry['documents']};self.trace=[];self.reads=set();self.answer=None;self.finished=False

    def call(self,tool,**arguments):
        if self.finished:return dict(ok=False,error='episode_finished')
        if len(self.trace)>=120:return dict(ok=False,error='call_budget_exhausted')
        try:
            if tool=='list_documents' and not arguments:response=dict(ok=True,documents=[dict(id=d['id'],title=d['title'],mime_type=d['mime_type'],sha256=d['sha256'],pages=len(d['pages'])) for d in self.docs.values()])
            elif tool=='read_page':response=self.read_page(**arguments)
            elif tool=='finish' and set(arguments)=={'answer'}:
                # Finishing stores any submitted assessment; semantic correctness
                # is checked only by the terminal grader, not returned to agent.
                self.answer=deepcopy(arguments['answer']);self.finished=True;response=dict(ok=True,submitted=True)
            else:response=dict(ok=False,error='invalid_tool_or_arguments')
        except (ValueError,KeyError,TypeError,IndexError):response=dict(ok=False,error='invalid_document_request')
        self.trace.append(dict(tool=tool,arguments=deepcopy(arguments),result=deepcopy(response)));return deepcopy(response)

    def read_page(self,document_id,page,method):
        d=self.docs[document_id]
        if type(page) is not int or not 1<=page<=len(d['pages']) or method not in ('text','ocr','image'):raise ValueError('invalid page request')
        asset=d['pages'][page-1];png=self.root.joinpath(asset['filename']).read_bytes()
        if hashlib.sha256(png).hexdigest()!=asset['sha256']:raise ValueError('page hash mismatch')
        if method=='image':response=dict(image_base64=base64.b64encode(png).decode(),mime_type='image/png',sha256=asset['sha256'])
        elif method=='ocr':response=dict(text=ocr(png),method='ocr',extractor=extractor_versions(),source_sha256=asset['sha256'])
        else:
            pdf=self.root.joinpath(d['filename']).read_bytes()
            if hashlib.sha256(pdf).hexdigest()!=d['sha256']:raise ValueError('PDF hash mismatch')
            response=dict(text=extracted(pdf,page),method='text',source_sha256=d['sha256'])
        self.reads.add((document_id,page));return dict(ok=True,document_id=document_id,page=page,**response)

    def grade(self):return grade(self.task,self.answer,self.reads)


def run(task,agent):
    world=DocumentWorld(task);last=None;error=None
    try:
        while not world.finished and len(world.trace)<120:
            payload=dict(last_result=last,calls_remaining=120-len(world.trace))
            if not world.trace:payload.update(task=public_task(task),tools=deepcopy(TOOLS))
            reply=agent.decide('documents',payload)
            if set(reply)!={'tool','arguments'} or not isinstance(reply['arguments'],dict):raise ValueError('invalid document agent response')
            last=world.call(reply['tool'],**reply['arguments'])
    except (ValueError,OSError,subprocess.SubprocessError) as exc:error=type(exc).__name__
    result=dict(evaluator_task_id=task['id'],source_commitment=digest(task),trace=world.trace,result=world.grade(),status='stopped' if error else 'finished' if world.finished else 'budget_exhausted')
    if error:result['error_type']=error
    return result


def replay(task,episode):
    if episode['source_commitment']!=digest(task):raise ValueError('document source mismatch')
    world=DocumentWorld(task)
    for row in episode['trace']:
        if world.call(row['tool'],**row['arguments'])!=row['result']:raise ValueError('document trace replay mismatch')
    actual=world.grade()
    if actual!=episode['result']:raise ValueError('document terminal replay mismatch')
    return actual


def export_packet(task,directory):
    root,entry=assets(task);out=Path(directory);out.mkdir(parents=True,exist_ok=True);manifest=[]
    for d in entry['documents']:
        blob=root.joinpath(d['filename']).read_bytes()
        if hashlib.sha256(blob).hexdigest()!=d['sha256']:raise ValueError('PDF hash mismatch')
        (out/d['filename']).write_bytes(blob);manifest.append(dict(id=d['id'],title=d['title'],filename=d['filename'],sha256=d['sha256'],pages=len(d['pages'])))
    (out/'task.json').write_text(json.dumps(dict(task=public_task(task),documents=manifest),indent=2,sort_keys=True)+'\n')
    return manifest
