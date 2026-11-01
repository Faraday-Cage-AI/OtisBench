"""Public-page procurement baseline using supplied PDF/OCR tools; no evaluator imports.

Handles the benchmark's disclosed synthetic forms, not arbitrary supplier formats.
"""
from decimal import Decimal
import json
import re
import sys


def key(text):return re.sub('[^a-z]','',text.lower().replace('0','o'))


def parse(text,page):
    header={};records=[];current=None
    for raw in text.splitlines():
        if ':' not in raw:continue
        k,value=raw.split(':',1);k=key(k);value=value.strip().replace('\u2014','-').replace('\u2013','-')
        if k=='record':current={'_page':page};records.append(current)
        elif current is None:header[k]=value
        else:current[k]=value
    return header,records


def number(value):return int(value.strip().replace('O','0').replace('I','1').replace('l','1'))

def cents(value):return int(Decimal(value.replace(',','').replace('O','0'))*100)


def cites(doc,rows):return [dict(document_id=doc['id'],page=p) for p in sorted({r['_page'] for r in rows})]


def unique(rows):return [dict(document_id=d,page=p) for d,p in sorted({(r['document_id'],r['page']) for r in rows})]


def reconcile(documents):
    selected={}
    for d in documents:
        h=d['header']
        if h['status']!='RELEASED':continue
        form=h['form']
        if form not in selected or number(h['revision'])>number(selected[form]['header']['revision']):selected[form]=d
    def rows(form,line):return [r for r in selected[form]['records'] if number(r['line'])==line]
    answer=[]
    for order in selected['PO']['records']:
        line=number(order['line']);req=rows('RFQ',line)[0];ack=rows('ACK',line)[0];certificate=rows('CERT',line)[0]
        ordered=number(order['quantity'])*number(order['eaperuom']);unit=cents(order['priceusd'])//number(order['eaperuom']);physical=accepted=0;reasons=set();released={};quarantined={};waiver_used={}
        current_drawing=ack['drawing']==req['drawing']
        if not current_drawing:reasons.add('drawing_mismatch')
        pod={r['shipment']:r for r in rows('POD',line)};logistics={r['shipment']:r for r in rows('LOGISTICS',line)}
        for shipment in rows('PACKING',line):
            event=pod.get(shipment['shipment'])
            if not event or event['delivery']!='DELIVERED' or event['destination']!='PLANT-A':continue
            quantity=number(shipment['quantity'])*number(shipment['eaperuom']);physical+=quantity;lot=shipment['lot'];damaged=number(shipment['damagedea']);good=quantity-damaged
            if damaged:reasons.add('damage')
            if certificate['lot']!=lot or certificate['item']!=shipment['item'] or certificate['release']!='RELEASED':good=0;reasons.add('certificate_mismatch')
            if logistics[shipment['shipment']]['clearance']!='RELEASED':good=0;reasons.add('customs_hold')
            if certificate['grade']!=req['grade']:
                eligible=[r for r in rows('DEVIATION',line) if r['item']==shipment['item'] and r['lot']==lot and r['grade']==certificate['grade'] and r['release']=='RELEASED' and r['validthrough']>='2026-10-31']
                cap=max([number(r['maxea']) for r in eligible]+[0]);allowed=min(good,max(0,cap-waiver_used.get(lot,0)));waiver_used[lot]=waiver_used.get(lot,0)+allowed
                if allowed<good:reasons.add('grade_deviation')
                good=allowed
            if not current_drawing:good=0
            accepted+=good;released[lot]=released.get(lot,0)+good;quarantined[lot]=quarantined.get(lot,0)+quantity-good
        if physical<ordered:reasons.add('short_receipt')
        bill=rows('INVOICE',line)[0];credits=[r for r in rows('CREDIT',line) if r['po']==selected['PO']['header']['business'] and r['invoice']==selected['INVOICE']['header']['business'] and r['release']=='RELEASED']
        net=number(bill['quantity'])*cents(bill['priceusd'])-sum(cents(c['amountusd']) for c in credits);supported=accepted*unit
        if net!=supported:reasons.add('invoice_variance')
        evidence={
            'purchase':unique(sum((cites(selected[f],rows(f,line)) for f in ('RFQ','PO','ACK')),[])),
            'receiving':unique(cites(selected['PACKING'],rows('PACKING',line))+cites(selected['POD'],rows('POD',line))),
            'quality':unique(cites(selected['CERT'],rows('CERT',line))+cites(selected['LOGISTICS'],rows('LOGISTICS',line))+(cites(selected['DEVIATION'],rows('DEVIATION',line)) if certificate['grade']!=req['grade'] else [])),
            'invoice':unique(cites(selected['INVOICE'],[bill])+cites(selected['CREDIT'],credits))}
        answer.append(dict(line_id=line,ordered_ea=ordered,delivered_ea=physical,accepted_ea=accepted,shortfall_ea=max(0,ordered-accepted),net_invoice_cents=net,supported_payable_cents=supported,approve_payment=accepted>0 and net==supported and current_drawing,release_lots=[dict(lot_id=l,units=n) for l,n in sorted(released.items()) if n],quarantine_lots=[dict(lot_id=l,units=n) for l,n in sorted(quarantined.items()) if n],hold_reasons=sorted(reasons),evidence=evidence))
    return dict(lines=answer)


class DocumentAgent:
    def __init__(self):self.generator=self.plan();self.started=False
    def decide(self,track,payload):
        if not self.started:self.started=True;return next(self.generator)
        return self.generator.send(payload['last_result'])

    def plan(self):
        response=yield dict(tool='list_documents',arguments={});documents=[]
        for d in response['documents']:
            merged=dict(id=d['id'],header={},records=[])
            for page in range(1,d['pages']+1):
                response=yield dict(tool='read_page',arguments=dict(document_id=d['id'],page=page,method='text'))
                text=response['text']
                if not text.strip():
                    response=yield dict(tool='read_page',arguments=dict(document_id=d['id'],page=page,method='ocr'));text=response['text']
                header,records=parse(text,page);merged['header'].update(header);merged['records'].extend(records)
            documents.append(merged)
        yield dict(tool='finish',arguments=dict(answer=reconcile(documents)))


if __name__=='__main__':
    agent=DocumentAgent()
    for line in sys.stdin:
        message=json.loads(line);print(json.dumps(agent.decide(message['track'],message['payload'])),flush=True)
