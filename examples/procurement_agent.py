"""Deterministic public-observation feasibility baseline, not a learned model.

Parses quote emails / carrier and invoice CSVs. No evaluator imports or scenario
metadata. A fixed initial settling wait applies to every episode. Business
records remain the source of all selected quantities, accounts and prices.
"""
import csv
from decimal import Decimal
import io
import json
import math
import re
import sys


def money(text):return int(Decimal(text)*100)

def parse_quote(text):
    def find(pattern):
        match=re.search(pattern,text)
        if not match:raise ValueError('unsupported quote format')
        return match.group(1)
    return dict(supplier_id=find(r'Supplier reference: (\S+)'),revision=int(find(r'Revision: (\d+)')),
        pack_units=int(find(r'Each pack contains (\d+) EA')),price_cents=money(find(r'Base price: USD ([0-9]+\.[0-9]{2})')),
        minimum_packs=int(find(r'Minimum order: (\d+)')),capacity_packs=int(find(r'Available allocation: (\d+)')),
        lead_minutes=int(find(r'Delivery lead: (\d+)')),freight_cents=money(find(r'Freight per PO: USD ([0-9]+\.[0-9]{2})')),
        tiers=[(int(n),money(p)) for n,p in re.findall(r'(\d+) or more packs: USD ([0-9]+\.[0-9]{2})/pack',text)])


def parse_csv(text):return next(csv.DictReader(io.StringIO(text)))


class ProcurementPolicy:
    def __init__(self):self.generator=self.plan();self.started=False
    def decide(self,track,payload):
        if not self.started:self.started=True;return next(self.generator)
        result=payload['last_result']
        if not result['ok']:raise ValueError('baseline action rejected: '+result['error'])
        return self.generator.send(result)

    def plan(self):
        clock=0
        def action(tool,**arguments):
            nonlocal clock
            result=yield dict(tool=tool,arguments=arguments);clock=result['clock_minute'];return result
        def wait_until(minute):
            while clock<minute:yield from action('wait',minutes=min(20,minute-clock))
        def post(kind,payload):
            result=yield from action('propose',kind=kind,payload=payload);pid=result['proposal']['id']
            result=yield from action('request_approval',proposal_id=pid);aid=result['approval']['id']
            return (yield from action('execute',proposal_id=pid,approval_id=aid))
        yield from action('wait',minutes=7)
        erp=(yield from action('read',system='ERP'))['records']
        scm=(yield from action('read',system='SCM'))['records']
        treasury=(yield from action('read',system='TREASURY'))['records']
        for sid,bank in treasury['supplier_banks'].items():
            change=bank['pending_change']
            if change:
                yield from action('read_document',document_id=change['request_document_id'])
                result=yield from action('verify_bank',supplier_id=sid)
                if result['callback']['status']=='callback_requested':yield from wait_until(result['callback']['available_minute'])
        treasury=(yield from action('read',system='TREASURY'))['records']
        docs=(yield from action('list_documents'))['documents'];quotes=[]
        for doc in docs:
            if doc['title']=='Supplier offer':
                raw=(yield from action('read_document',document_id=doc['id']))['document']
                quote=parse_quote(raw['body']);quote['document_id']=doc['id'];quotes.append(quote)
        evidence=[];booked={};remaining=erp['required_units']
        while remaining>0:
            scm=(yield from action('read',system='SCM'))['records']
            active={s['id'] for s in scm['suppliers'] if s['approved'] and s['status']=='active' and s['approved_grade']==erp['grade']}
            choices=[]
            for q in quotes:
                packs=max(q['minimum_packs'],math.ceil(remaining/q['pack_units']))
                if q['supplier_id'] not in active or packs+booked.get(q['document_id'],0)>q['capacity_packs'] or clock+q['lead_minutes']+15>erp['need_by_minute']:continue
                price=q['price_cents']
                for minimum,tier in sorted(q['tiers']):
                    if packs>=minimum:price=tier
                choices.append((packs*price+q['freight_cents'],q['lead_minutes'],q['document_id'],packs,q))
            if not choices:raise ValueError('no feasible public offer')
            total,_,_,packs,q=min(choices,key=lambda c:c[:3])
            # Re-read the selected document at the time of the commitment.
            yield from action('read_document',document_id=q['document_id'])
            result=yield from post('purchase',dict(supplier_id=q['supplier_id'],quote_document_id=q['document_id'],quote_revision=q['revision'],packs=packs,total_cents=total))
            po=result['purchase_order'];booked[q['document_id']]=booked.get(q['document_id'],0)+packs
            pending=set(po['delivery_document_ids'])
            yield from wait_until(po['delivery_minute'])
            while pending:
                available={d['id'] for d in (yield from action('list_documents'))['documents']}
                ready=sorted(pending&available)
                if not ready:
                    yield from action('wait',minutes=5);continue
                for did in ready:
                    doc=(yield from action('read_document',document_id=did))['document'];row=parse_csv(doc['body'])
                    units=int(row['case_count'])*int(row['each_per_case'])+int(row['loose_each'])
                    receipt=(yield from action('receive',po_id=po['id'],delivery_document_id=did,units=units,damaged_units=int(row['damaged_each'])))['receipt'];rid=receipt['id'];evidence.append(rid)
                    cid=row['certificate_document_id'];cert=(yield from action('read_document',document_id=cid))['document']
                    if 'Status: pending' in cert['body']:
                        release=int(re.search(r'Release minute: (\d+)',cert['body']).group(1));yield from wait_until(release)
                        yield from action('read_document',document_id=cid)
                    yield from action('inspect',receipt_id=rid,certificate_document_id=cid,decision='accept');pending.remove(did)
            # Read every issued invoice for this PO and hold exceptions before
            # approving the released original/correction. No hidden solver needed.
            seen=set();current=None
            while current is None:
                docs=(yield from action('list_documents'))['documents']
                for doc in docs:
                    if doc['title']!='Supplier invoice' or doc['id'] in seen:continue
                    raw=(yield from action('read_document',document_id=doc['id']))['document'];bill=parse_csv(raw['body'])
                    if bill['po_id']!=po['id']:continue
                    seen.add(doc['id'])
                    amount=money(bill['invoice_amount_usd'])
                    expected=po['total_cents']-money(bill['short_delivery_credit_usd'])
                    if bill['document_class']!='copy' and amount==expected:
                        current=(doc['id'],amount)
                    else:
                        reason='duplicate' if bill['document_class']=='copy' else 'amount_mismatch'
                        yield from post('invoice',dict(invoice_document_id=doc['id'],decision='hold',amount_cents=0,reason=reason))
                if current is None:yield from action('wait',minutes=5)
            result=yield from post('invoice',dict(invoice_document_id=current[0],decision='approve',amount_cents=current[1],reason='matched'))
            invoice=result['invoice']
            bank=treasury['supplier_banks'][invoice['supplier_id']]
            result=yield from post('payment',dict(invoice_id=invoice['id'],account=bank['verified_account'],amount_cents=invoice['amount_cents']))
            evidence.append(result['payment']['id'])
            wms=(yield from action('read',system='WMS'))['records'];remaining=max(0,erp['required_units']-wms['accepted_stock_units'])
        for system in ('SCM','WMS','AP'):
            yield from action('read',system=system)
        yield from action('finish',evidence_ids=evidence)


def main():
    agent=ProcurementPolicy()
    for line in sys.stdin:
        message=json.loads(line);print(json.dumps(agent.decide(message['track'],message['payload'])),flush=True)

if __name__=='__main__':main()
