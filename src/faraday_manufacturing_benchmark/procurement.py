"""Procure-to-pay simulator: raw documents, physical inventory and cash settlement.

The tested agent supplies quantities, prices, dispositions and accounts. Parsing
and solving stay in the agent; the engine checks authorization and physical/
financial invariants and grades final records. No external services are called.
"""
from copy import deepcopy
import csv
import hashlib
import io
import json
import math
import re
import secrets
from .procurement_cases import build,document,quote_document
from .shopfloor import digest

TOOLS={
 'read':{'system':'ERP | SCM | WMS | QMS | AP | TREASURY'},
 'list_documents':{},'read_document':{'document_id':'issued document ID'},
 'wait':{'minutes':'integer 1..20'},
 'propose':{'kind':'purchase | invoice | payment','payload':'exact fields from action_contracts'},
 'request_approval':{'proposal_id':'issued proposal ID'},
 'execute':{'proposal_id':'issued proposal ID','approval_id':'issued approval ID'},
 'receive':{'po_id':'PO ID','delivery_document_id':'delivery CSV ID','units':'physical EA integer','damaged_units':'damaged EA integer'},
 'inspect':{'receipt_id':'receipt ID','certificate_document_id':'certificate document ID','decision':'accept | quarantine'},
 'verify_bank':{'supplier_id':'supplier ID; requests independent treasury callback'},
 'finish':{'evidence_ids':'all receipt and payment IDs'},
}
CONTRACTS={
 'purchase':dict(supplier_id='string',quote_document_id='string',quote_revision='integer',packs='positive_integer',total_cents='positive_integer'),
 'invoice':dict(invoice_document_id='string',decision='approve | hold',amount_cents='nonnegative_integer',reason='matched | amount_mismatch | duplicate | superseded'),
 'payment':dict(invoice_id='string',account='string',amount_cents='positive_integer'),
}


def csv_text(header,row):
    stream=io.StringIO();writer=csv.writer(stream);writer.writerow(header);writer.writerow(row);return stream.getvalue()


def valid_payload(kind,payload):
    if kind not in CONTRACTS or not isinstance(payload,dict) or set(payload)!=set(CONTRACTS[kind]):return False
    for key,spec in CONTRACTS[kind].items():
        value=payload[key]
        if spec in ('integer','positive_integer','nonnegative_integer'):
            if type(value) is not int or abs(value)>10**9:return False
            if spec=='positive_integer' and value<=0:return False
            if spec=='nonnegative_integer' and value<0:return False
        elif spec=='string':
            if not isinstance(value,str) or not 0<len(value)<=200:return False
        elif value not in spec.split(' | '):return False
    return True


class ProcurementWorld:
    def __init__(self,task):
        self.task=deepcopy(task);source=build(task);self.records=source['records'];self.quotes=source['quotes'];self.documents=source['documents'];self.config=source['configuration']
        self.clock=0;self.trace=[];self.finished=False;self.evidence=[];self.violations=[]
        self.proposals={};self.approvals={};self.document_reads={};self.system_reads={};self.delivery_truth={};self.invoice_truth={};self.spent_cents=0;self.credits_cents=0;self.cash_paid_cents=0;self.update_applied=False
        self.commitment=digest(dict(task=task,source=source));self.initial_state_hash=self.state_hash()

    def state_hash(self):
        return digest(dict(records=self.records,quotes=self.quotes,documents=self.documents,clock=self.clock,finished=self.finished,evidence=self.evidence,
            violations=self.violations,proposals=self.proposals,approvals=self.approvals,document_reads=self.document_reads,system_reads=self.system_reads,
            delivery_truth=self.delivery_truth,invoice_truth=self.invoice_truth,spent=self.spent_cents,credits=self.credits_cents,cash_paid=self.cash_paid_cents,update_applied=self.update_applied))

    def _advance(self,minutes):
        self.clock+=minutes
        update=self.records['SCM']['pending_supplier_update']
        if update and not self.update_applied and self.clock>=6:
            if self.config['supplier_suspension']:self.records['SCM']['suppliers'][0]['status']='suspended'
            if self.config['quote_change']:
                q=self.quotes['DOC-Q1'];q['revision']=2;q['price_cents']+=q['pack_units']*10
                self.documents[q['id']]=quote_document(q['id'],q['supplier_id'],2,q['pack_units'],q['price_cents'],q['lead_minutes'],q['capacity_packs'],q['minimum_packs'],q['freight_cents'],q['tiers'])
            update['status']='released';self.update_applied=True
        for truth in self.delivery_truth.values():
            doc=self.documents[truth['certificate_document_id']]
            if not truth['certificate_released'] and self.clock>=truth['certificate_release_minute']:
                truth['certificate_released']=True
                doc['body']=self._certificate_body(truth,'released')
        for supplier,bank in self.records['TREASURY']['supplier_banks'].items():
            change=bank['pending_change']
            if change and change['status']=='callback_requested' and self.clock>=change['available_minute']:
                verified=self.task['draw']%2==0
                change['status']='verified' if verified else 'rejected'
                change['callback_record_id']='CALLBACK-'+supplier
                if verified:bank['verified_account']=change['requested_account']

    def _error(self,code,critical=False):
        if critical:self.violations.append(code)
        return dict(ok=False,error=code)

    def call(self,tool,**arguments):
        if self.finished:return dict(ok=False,error='episode_finished',clock_minute=self.clock)
        if len(self.trace)>=self.task['max_tool_calls']:return dict(ok=False,error='call_budget_exhausted',clock_minute=self.clock)
        self._advance(1)
        if self.clock>self.task['horizon_minutes']:result=self._error('horizon_exceeded')
        elif tool not in TOOLS:result=self._error('unknown_tool')
        else:
            try:result=getattr(self,'_do_'+tool)(**arguments)
            except (TypeError,KeyError,ValueError):result=self._error('invalid_arguments')
        result['clock_minute']=self.clock
        self.trace.append(dict(index=len(self.trace),tool=tool,arguments=deepcopy(arguments),result=deepcopy(result),state_hash=self.state_hash()))
        return deepcopy(result)

    def _do_read(self,system):
        if system not in self.task['systems']:return self._error('unknown_system')
        self.system_reads[system]=digest(self.records[system])
        record=deepcopy(self.records[system])
        if system=='ERP':record.update(committed_cents=self.spent_cents,credited_cents=self.credits_cents,cash_paid_cents=self.cash_paid_cents,remaining_budget_cents=record['budget_cents']-self.spent_cents+self.credits_cents)
        return dict(ok=True,system=system,records=record)

    def _do_list_documents(self):
        rows=[{k:v for k,v in doc.items() if k!='body'} for doc in self.documents.values() if doc['available_minute']<=self.clock]
        return dict(ok=True,documents=sorted(rows,key=lambda r:r['id']))

    def _do_read_document(self,document_id):
        doc=self.documents.get(document_id)
        if not doc or doc['available_minute']>self.clock:return self._error('document_unavailable')
        self.document_reads[document_id]=digest(doc['body'])
        return dict(ok=True,document=deepcopy(doc))

    def _read_current(self,doc_id):
        return doc_id in self.documents and self.documents[doc_id]['available_minute']<=self.clock and self.document_reads.get(doc_id)==digest(self.documents[doc_id]['body'])

    def _do_wait(self,minutes):
        if type(minutes) is not int or not 1<=minutes<=20:return self._error('invalid_wait')
        self._advance(minutes);return dict(ok=True)

    def _binding(self,kind,payload):
        if kind=='purchase':
            return digest(dict(erp=self.records['ERP'],suppliers=self.records['SCM']['suppliers'],quote=self.quotes.get(payload['quote_document_id'])))
        if kind=='invoice':
            tid=payload['invoice_document_id'];truth=self.invoice_truth.get(tid)
            return digest(dict(invoice=self.documents.get(tid),po=self.records['SCM']['purchase_orders'].get(truth['po_id']) if truth else None,receipts=self.records['WMS']['receipts'],inspections=self.records['QMS']['inspections']))
        invoice=self.records['AP']['invoices'].get(payload['invoice_id'])
        return digest(dict(invoice=invoice,bank=self.records['TREASURY']['supplier_banks'].get(invoice['supplier_id']) if invoice else None))

    def _do_propose(self,kind,payload):
        if not valid_payload(kind,payload):return self._error('invalid_action_schema')
        pid=f'PROP-{len(self.proposals)+1}';self.proposals[pid]=dict(id=pid,kind=kind,payload=deepcopy(payload),binding=self._binding(kind,payload))
        return dict(ok=True,proposal={k:deepcopy(v) for k,v in self.proposals[pid].items() if k!='binding'})

    def _do_request_approval(self,proposal_id):
        p=self.proposals.get(proposal_id)
        if not p:return self._error('unknown_proposal')
        if p['binding']!=self._binding(p['kind'],p['payload']):return self._error('source_version_mismatch')
        aid=f'AUTH-{len(self.approvals)+1}';self.approvals[aid]=dict(id=aid,proposal_id=proposal_id,payload_hash=digest(p['payload']),binding=p['binding'],used=False)
        return dict(ok=True,approval=dict(id=aid,proposal_id=proposal_id,status='approved'))

    def _do_execute(self,proposal_id,approval_id):
        p=self.proposals.get(proposal_id);a=self.approvals.get(approval_id)
        if not p or not a or a['used'] or a['proposal_id']!=proposal_id or a['payload_hash']!=digest(p['payload']):return self._error('authorization_mismatch',True)
        if a['binding']!=self._binding(p['kind'],p['payload']):return self._error('source_version_mismatch')
        result=getattr(self,'_execute_'+p['kind'])(**p['payload'])
        if result['ok']:a['used']=True
        return result

    def _execute_purchase(self,supplier_id,quote_document_id,quote_revision,packs,total_cents):
        if not self.system_reads.get('ERP') or not self.system_reads.get('SCM') or not self._read_current(quote_document_id):return self._error('source_read_required')
        supplier=next((s for s in self.records['SCM']['suppliers'] if s['id']==supplier_id),None);q=self.quotes.get(quote_document_id)
        if not supplier or supplier['status']!='active' or not supplier['approved'] or supplier['approved_grade']!=self.records['ERP']['grade']:return self._error('supplier_not_qualified',True)
        if not q or q['supplier_id']!=supplier_id or q['revision']!=quote_revision or q['status']!='released' or q['valid_until']<self.clock:return self._error('quote_not_effective')
        booked=sum(po['packs'] for po in self.records['SCM']['purchase_orders'].values() if po['quote_document_id']==quote_document_id)
        if packs<q['minimum_packs'] or booked+packs>q['capacity_packs']:return self._error('quote_quantity_constraint')
        price=q['price_cents']
        for minimum,tier_price in sorted(q['tiers']):
            if packs>=minimum:price=tier_price
        actual=packs*price+q['freight_cents']
        if total_cents!=actual:return self._error('commercial_amount_mismatch')
        if self.spent_cents-self.credits_cents+actual>self.records['ERP']['budget_cents']:return self._error('budget_exceeded')
        pid=f'PO-{len(self.records["SCM"]["purchase_orders"])+1}';units=packs*q['pack_units']
        po=dict(id=pid,supplier_id=supplier_id,quote_document_id=quote_document_id,quote_revision=quote_revision,packs=packs,units=units,unit_pack_cents=price,pack_units=q['pack_units'],freight_cents=q['freight_cents'],total_cents=actual,delivery_minute=self.clock+q['lead_minutes'],delivery_document_ids=[],status='open')
        self.records['SCM']['purchase_orders'][pid]=po;self.spent_cents+=actual;self._issue_documents(po)
        return dict(ok=True,purchase_order=deepcopy(po))

    def _certificate_body(self,truth,status):
        return f"Certificate {truth['certificate_document_id']}\nLot: {truth['lot_id']}\nItem: ITEM-1\nGrade: G2\nStatus: {status}\nRelease minute: {truth['certificate_release_minute']}\n"

    def _issue_documents(self,po):
        first=len(self.records['SCM']['purchase_orders'])==1;config=self.config;n=po['units'];pack=po['pack_units']
        short=min(config['short_units'],n) if first else 0;damage=min(config['damaged_units'],n-short) if first else 0;actual=n-short
        chunks=[actual//2,actual-actual//2] if first and config['partial'] else [actual]
        # Split only at complete EA, not necessarily complete purchase packs.
        for i,units in enumerate(chunks,1):
            did=f'DOC-DEL-{po["id"]}-{i}';cid=f'DOC-CERT-{po["id"]}-{i}';lot=f'LOT-{po["id"]}-{i}';due=po['delivery_minute']+(i-1)*5
            damaged=min(damage,units);damage-=damaged
            truth=dict(document_id=did,po_id=po['id'],lot_id=lot,units=units,damaged_units=damaged,certificate_document_id=cid,
                certificate_release_minute=due+(8 if first and config['certificate_delay'] else 0),certificate_released=not(first and config['certificate_delay']))
            self.delivery_truth[did]=truth;po['delivery_document_ids'].append(did)
            carton=6 if self.task['contract']=='unit_conversion' else pack;cases,loose=divmod(units,carton)
            body=csv_text(['delivery_document_id','po_id','lot_id','case_count','each_per_case','loose_each','damaged_each','certificate_document_id'],[did,po['id'],lot,cases,carton,loose,damaged,cid])
            self.documents[did]=document(did,'Carrier delivery manifest','text/csv',body,due)
            self.documents[cid]=document(cid,'Material certificate','text/plain',self._certificate_body(truth,'released' if truth['certificate_released'] else 'pending'),due)
        unit_each=po['unit_pack_cents']//pack;credit=short*unit_each;amount=po['total_cents']-credit
        due=po['delivery_minute']+len(chunks)*5
        iid=f'DOC-BILL-{po["id"]}'
        variance=1000 if first and config['invoice_variance'] else 0
        self._invoice_document(iid,po,amount+variance,due,'superseded' if variance else 'released',amount,credit)
        if variance:self._invoice_document(iid+'-R2',po,amount,due+8,'released',amount,credit)
        if first and config['duplicate']:self._invoice_document(iid+'-COPY',po,amount,due,'duplicate',amount,credit)

    def _invoice_document(self,iid,po,shown_amount,available,status,correct_amount,credit):
        self.invoice_truth[iid]=dict(po_id=po['id'],supplier_id=po['supplier_id'],amount_cents=correct_amount,credit_cents=credit,status=status)
        body=csv_text(['invoice_document_id','invoice_number','po_id','supplier_id','invoice_amount_usd','short_delivery_credit_usd','document_class','revision'],[iid,'BILL-'+po['id'],po['id'],po['supplier_id'],f'{shown_amount/100:.2f}',f'{credit/100:.2f}','copy' if status=='duplicate' else 'invoice',2 if iid.endswith('-R2') else 1])
        self.documents[iid]=document(iid,'Supplier invoice','text/csv',body,available)

    def _do_receive(self,po_id,delivery_document_id,units,damaged_units):
        if type(units) is not int or type(damaged_units) is not int or not 0<=damaged_units<=units or units<=0:return self._error('invalid_receipt_quantity')
        truth=self.delivery_truth.get(delivery_document_id)
        if not truth or truth['po_id']!=po_id or not self._read_current(delivery_document_id):return self._error('delivery_source_required')
        existing=next((r for r in self.records['WMS']['receipts'].values() if r['delivery_document_id']==delivery_document_id),None)
        if existing:
            if existing['units']==units and existing['damaged_units']==damaged_units:return dict(ok=True,receipt=deepcopy(existing),idempotent=True)
            return self._error('duplicate_receipt_mismatch',True)
        rid=f'RCPT-{len(self.records["WMS"]["receipts"])+1}'
        row=dict(id=rid,po_id=po_id,delivery_document_id=delivery_document_id,lot_id=truth['lot_id'],units=units,damaged_units=damaged_units,accepted_units=0,quarantined_units=units,status='pending_inspection',received_minute=self.clock,accepted_minute=None)
        self.records['WMS']['receipts'][rid]=row;self.records['WMS']['quarantined_stock_units']+=units
        return dict(ok=True,receipt=deepcopy(row))

    def _do_inspect(self,receipt_id,certificate_document_id,decision):
        row=self.records['WMS']['receipts'].get(receipt_id)
        if not row or decision not in ('accept','quarantine'):return self._error('invalid_inspection')
        truth=self.delivery_truth[row['delivery_document_id']]
        if not self._read_current(certificate_document_id):return self._error('certificate_source_required')
        if certificate_document_id!=truth['certificate_document_id']:return self._error('certificate_lot_mismatch',True)
        if decision=='accept' and not truth['certificate_released']:return self._error('certificate_not_released',True)
        old=row['accepted_units'];new=row['units']-row['damaged_units'] if decision=='accept' else 0
        self.records['WMS']['accepted_stock_units']+=new-old;self.records['WMS']['quarantined_stock_units']-=new-old
        row.update(accepted_units=new,quarantined_units=row['units']-new,status='accepted_with_damage' if new and row['damaged_units'] else 'accepted' if new else 'quarantined',accepted_minute=self.clock if new else None)
        iid=f'INSPECT-{len(self.records["QMS"]["inspections"])+1}'
        inspection=dict(id=iid,receipt_id=receipt_id,certificate_document_id=certificate_document_id,decision=decision,accepted_units=new,quarantined_units=row['quarantined_units'],minute=self.clock)
        self.records['QMS']['inspections'][iid]=inspection
        return dict(ok=True,inspection=deepcopy(inspection),receipt=deepcopy(row))

    def _po_received(self,po_id):
        po=self.records['SCM']['purchase_orders'][po_id];rows=[r for r in self.records['WMS']['receipts'].values() if r['po_id']==po_id]
        return bool(rows) and set(r['delivery_document_id'] for r in rows)==set(po['delivery_document_ids']) and all(r['status']!='pending_inspection' for r in rows)

    def _execute_invoice(self,invoice_document_id,decision,amount_cents,reason):
        truth=self.invoice_truth.get(invoice_document_id)
        if not truth or not self._read_current(invoice_document_id):return self._error('invoice_source_required')
        if decision=='hold':
            if reason=='matched' or amount_cents!=0:return self._error('invalid_hold')
            self.records['AP']['document_dispositions'][invoice_document_id]=dict(decision='hold',reason=reason)
            return dict(ok=True,document_id=invoice_document_id,status='held')
        if truth['status']!='released':return self._error('invoice_duplicate_or_superseded',True)
        if not self._po_received(truth['po_id']):return self._error('receipts_not_dispositioned')
        if reason!='matched':return self._error('invalid_invoice_decision')
        if any(i['po_id']==truth['po_id'] for i in self.records['AP']['invoices'].values()):return self._error('duplicate_invoice_approval',True)
        iid=f'INVOICE-{len(self.records["AP"]["invoices"])+1}'
        row=dict(id=iid,po_id=truth['po_id'],supplier_id=truth['supplier_id'],source_document_id=invoice_document_id,amount_cents=amount_cents,status='approved',approved_minute=self.clock)
        self.records['AP']['invoices'][iid]=row;self.records['AP']['document_dispositions'][invoice_document_id]=dict(decision='approve',reason='matched')
        self.credits_cents+=truth['credit_cents'];self.records['SCM']['purchase_orders'][truth['po_id']]['status']='reconciled'
        return dict(ok=True,invoice=deepcopy(row))

    def _do_verify_bank(self,supplier_id):
        bank=self.records['TREASURY']['supplier_banks'].get(supplier_id)
        if not bank:return self._error('unknown_supplier')
        change=bank['pending_change']
        if not change:return dict(ok=True,status='no_change',verified_account=bank['verified_account'])
        if not self._read_current(change['request_document_id']):return self._error('bank_request_source_required')
        if change['status']=='unverified':change.update(status='callback_requested',available_minute=self.clock+4)
        return dict(ok=True,callback=deepcopy(change))

    def _execute_payment(self,invoice_id,account,amount_cents):
        invoice=self.records['AP']['invoices'].get(invoice_id)
        if not invoice:return self._error('invoice_not_approved')
        if invoice['status']=='paid':return self._error('duplicate_payment',True)
        bank=self.records['TREASURY']['supplier_banks'][invoice['supplier_id']];change=bank['pending_change']
        if change and change['status'] in ('unverified','callback_requested'):return self._error('bank_verification_pending')
        if account!=bank['verified_account']:return self._error('unverified_payment_account',True)
        if amount_cents!=invoice['amount_cents']:return self._error('payment_amount_mismatch')
        payid=f'PAY-{len(self.records["AP"]["payments"])+1}'
        payment=dict(id=payid,invoice_id=invoice_id,supplier_id=invoice['supplier_id'],account=account,verified_account_at_payment=bank['verified_account'],amount_cents=amount_cents,minute=self.clock)
        self.records['AP']['payments'][payid]=payment;invoice['status']='paid';self.cash_paid_cents+=amount_cents
        return dict(ok=True,payment=deepcopy(payment))

    def _do_finish(self,evidence_ids):
        existing=set(self.records['WMS']['receipts'])|set(self.records['AP']['payments'])
        if not isinstance(evidence_ids,list) or not evidence_ids or any(not isinstance(x,str) for x in evidence_ids) or not set(evidence_ids)<=existing:return self._error('invalid_finish_evidence')
        self.finished=True;self.evidence=list(evidence_ids);return dict(ok=True,finished=True)

    def grade(self):
        wms=self.records['WMS'];ap=self.records['AP'];pos=self.records['SCM']['purchase_orders'];receipts=list(wms['receipts'].values());invoices=list(ap['invoices'].values());payments=list(ap['payments'].values());required=self.records['ERP']['required_units']
        accurate=bool(receipts) and all(r['units']==self.delivery_truth[r['delivery_document_id']]['units'] and r['damaged_units']==self.delivery_truth[r['delivery_document_id']]['damaged_units'] for r in receipts)
        quality=bool(receipts) and all(r['accepted_units']==0 or self.delivery_truth[r['delivery_document_id']]['certificate_released'] and r['accepted_units']==r['units']-r['damaged_units'] for r in receipts)
        all_received=bool(pos) and all(self._po_received(p) for p in pos)
        invoice_correct=bool(pos) and len(invoices)==len(pos) and all(i['amount_cents']==self.invoice_truth[i['source_document_id']]['amount_cents'] for i in invoices)
        pay_correct=bool(invoices) and len(payments)==len(invoices) and all(i['status']=='paid' for i in invoices) and all(p['account']==p['verified_account_at_payment'] and p['amount_cents']==ap['invoices'][p['invoice_id']]['amount_cents'] for p in payments)
        exceptions=all(d in ap['document_dispositions'] and ap['document_dispositions'][d]['decision']=='hold' and ap['document_dispositions'][d]['reason'] in (('duplicate',) if truth['status']=='duplicate' else ('amount_mismatch','superseded')) for d,truth in self.invoice_truth.items() if truth['status']!='released')
        banks=all(not b['pending_change'] or b['pending_change']['status'] in ('verified','rejected') for b in self.records['TREASURY']['supplier_banks'].values())
        ontime=sum(r['accepted_units'] for r in receipts if r['accepted_minute'] is not None and r['accepted_minute']<=self.records['ERP']['need_by_minute'])>=required
        evidence=bool(receipts and payments) and (set(wms['receipts'])|set(ap['payments']))<=set(self.evidence)
        read_back=bool(pos) and all(self.system_reads.get(system)==digest(self.records[system]) for system in ('SCM','WMS','AP'))
        checks=dict(requirement_fulfilled=wms['accepted_stock_units']>=required,physical_receipts_exact=accurate,quality_conforming=quality,all_orders_received=all_received,
            invoices_reconciled=invoice_correct,invoice_exceptions_held=bool(pos) and exceptions,payments_settled=pay_correct,bank_changes_verified=banks,
            within_budget=self.spent_cents-self.credits_cents<=self.records['ERP']['budget_cents'],on_time=ontime,records_read_back=read_back,finished=self.finished and evidence,no_critical_violation=not self.violations)
        score=40*min(1,wms['accepted_stock_units']/required)+10*accurate+10*quality+10*all_received+10*(invoice_correct and exceptions)+10*pay_correct+10*(checks['finished'] and ontime and banks and read_back and checks['within_budget'])
        if self.violations:score=0
        return dict(task_id=self.task['id'],contract=self.task['contract'],score=score,strict_success=all(checks.values()),checks=checks,critical_violations=list(self.violations),
            accepted_units=wms['accepted_stock_units'],quarantined_units=wms['quarantined_stock_units'],required_units=required,purchase_orders=len(pos),receipts=len(receipts),payments=len(payments),
            committed_cents=self.spent_cents,credited_cents=self.credits_cents,cash_paid_cents=self.cash_paid_cents,elapsed_minutes=self.clock,tool_calls=len(self.trace),source_commitment=self.commitment,initial_state_hash=self.initial_state_hash,final_state_hash=self.state_hash())


def replay(task,trace):
    world=ProcurementWorld(task)
    for index,record in enumerate(trace):
        world.call(record['tool'],**record['arguments'])
        if not world.trace or world.trace[-1]!=record:raise ValueError(f'procurement replay mismatch at {index}')
    return world.grade()


PATTERN=re.compile(r'(?<![A-Za-z0-9-])(?:CALLBACK|DOC|SUP|REQ|ITEM|LOT|PO|PROP|AUTH|RCPT|INSPECT|INVOICE|BILL|PAY|ACCT)-[A-Za-z0-9-]+')
class ProcurementView:
    def __init__(self):self.nonce=secrets.token_hex(24);self.forward={};self.reverse={};self.episode_id='procurement-episode-'+self.nonce[:16]
    def _alias(self,match):
        original=match.group()
        if original not in self.forward:
            alias='REF-'+hashlib.sha256((self.nonce+original).encode()).hexdigest()[:24];self.forward[original]=alias;self.reverse[alias]=original
        return self.forward[original]
    def encode(self,value):
        if isinstance(value,str):return PATTERN.sub(self._alias,value)
        if isinstance(value,list):return [self.encode(v) for v in value]
        if isinstance(value,dict):return {self.encode(k):self.encode(v) for k,v in value.items()}
        return deepcopy(value)
    def decode(self,value):
        if isinstance(value,str):
            if value in self.reverse:return self.reverse[value]
            if PATTERN.search(value) or value.startswith('REF-'):raise ValueError('unissued_identifier')
            return value
        if isinstance(value,list):return [self.decode(v) for v in value]
        if isinstance(value,dict):return {self.decode(k):self.decode(v) for k,v in value.items()}
        return deepcopy(value)


def public_task(task,episode_id='procurement-case'):
    return dict(id=episode_id,goal='Procure conforming material to cover the requisition on time. Reconcile source documents, deliveries, quality, invoice exceptions and supplier bank changes; settle approved invoices and finish with receipt and payment evidence.',
        systems=list(task['systems']),action_contracts=deepcopy(CONTRACTS),max_tool_calls=task['max_tool_calls'],horizon_minutes=task['horizon_minutes'])


def run(task,agent,checkpoint=None):
    world=ProcurementWorld(task);view=ProcurementView();last=None;agent_trace=[];error=None
    try:
        while not world.finished and len(world.trace)<task['max_tool_calls'] and world.clock<=task['horizon_minutes']:
            payload=dict(clock_minute=world.clock,calls_remaining=task['max_tool_calls']-len(world.trace),last_result=last)
            if not world.trace:payload.update(task=public_task(task,view.episode_id),tools=deepcopy(TOOLS))
            decision=agent.decide('procurement',payload)
            if not isinstance(decision,dict) or set(decision)!={'tool','arguments'} or not isinstance(decision['tool'],str) or not isinstance(decision['arguments'],dict):raise ValueError('invalid_decision')
            raw=world.call(decision['tool'],**view.decode(decision['arguments']));last=view.encode(raw);agent_trace.append(dict(decision=deepcopy(decision),result=deepcopy(last)))
            if checkpoint:checkpoint(dict(evaluator_task_id=task['id'],result=world.grade(),trace=deepcopy(world.trace),agent_trace=deepcopy(agent_trace),status='running'))
    except (ValueError,OSError) as exc:error=type(exc).__name__
    result=dict(evaluator_task_id=task['id'],result=world.grade(),trace=deepcopy(world.trace),agent_trace=agent_trace,status='stopped' if error else 'finished' if world.finished else 'budget_exhausted')
    if error:result['error_type']=error
    if checkpoint:checkpoint(result)
    return result


def summary(results):
    from collections import defaultdict
    groups=defaultdict(list)
    if not results:raise ValueError('cannot summarize empty procurement results')
    if len({r['task_id'] for r in results})!=len(results):raise ValueError('duplicate procurement result')
    for r in results:groups[r['contract']].append(r)
    def group(rows):
        return dict(cases=len(rows),strict_successes=sum(r['strict_success'] for r in rows),mean_score=sum(r['score'] for r in rows)/len(rows),critical_failures=sum(bool(r['critical_violations']) for r in rows))
    return dict(**group(results),macro_contract_strict_rate=sum(sum(r['strict_success'] for r in rows)/len(rows) for rows in groups.values())/len(groups),contracts={k:group(v) for k,v in sorted(groups.items())})
