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



# Canonical vocabulary of the disclosed synthetic legacy form. Labels alone may
# be repaired by an unambiguous edit distance of one; identifiers are untouched.
LABELS = {'Line #':'line', 'Part no.':'item', 'Drawing rev.':'drawing', 'Grade':'grade',
 'Qty':'quantity', 'Units / UOM':'eaperuom', 'Price / UOM USD':'priceusd',
 'Material lot':'lot', 'Damaged units':'damagedea', 'Maximum units':'maxea',
 'Expiry date':'validthrough', 'Credit USD':'amountusd', 'Release state':'release',
 'UOM':'uom', 'Shipment':'shipment', 'Delivery':'delivery', 'Destination':'destination',
 'Clearance':'clearance', 'PO':'po', 'Invoice':'invoice'}
NUMERIC = {'line','quantity','eaperuom','priceusd','damagedea','maxea','amountusd'}


def label_key(value):return re.sub('[^a-z0-9]','',value.casefold())


def distance_one(a,b):
    if abs(len(a)-len(b))>1:return False
    if len(a)==len(b):return sum(x!=y for x,y in zip(a,b))<=1
    if len(a)>len(b):a,b=b,a
    return any(b[:i]+b[i+1:]==a for i in range(len(b)))


def field_label(value):
    labels={label_key(k):v for k,v in LABELS.items()};value=label_key(value)
    if value in labels:return labels[value]
    matches={target for name,target in labels.items() if len(value)>=3 and distance_one(name,value)}
    if len(matches)!=1:raise ValueError('unknown or ambiguous printed field label: '+value)
    return matches.pop()


def parse_scan(text,page):
    lines=[line.strip() for line in text.splitlines() if line.strip()]
    markers={label_key(s):i for i,s in enumerate(lines)}
    if 'lineitems' not in markers or 'endofitems' not in markers:raise ValueError('missing scan form boundaries')
    start,end=markers['lineitems'],markers['endofitems']
    if end<=start:raise ValueError('reversed scan form boundaries')
    header={}
    for raw in lines[:start]:
        for match in re.finditer(r'(?<!\S)(Form|Business|Revision|Status|PO|As of):\s*(.*?)(?=\s+(?:Form|Business|Revision|Status|PO|As of):|$)',raw):
            name=key(match[1]);value=match[2].strip()
            if name in header:raise ValueError('duplicate scan header')
            header[name]=value
    if set(header)!={'form','business','revision','status','po','asof'}:raise ValueError('incomplete scan header')
    records=[];current=None
    for raw in lines[start+1:end]:
        if re.fullmatch(r'ITEM\s+[0-9OIl]+[.:]*',raw):
            current={'_page':page};records.append(current);continue
        if current is None or '=' not in raw:raise ValueError('invalid printed record structure')
        label,value=raw.split('=',1);name=field_label(label)
        if name in current:raise ValueError('duplicate scan field')
        value=value.strip()
        if name in NUMERIC and re.fullmatch(r'[0-9OIl., ]+',value):
            value=value.replace('O','0').replace('I','1').replace('l','1')
        current[name]=value
    if not records or any('line' not in r for r in records):raise ValueError('missing scan line records')
    return header,records


def decide(payload):
    documents=[]
    for document in payload['documents']:
        merged={'id':document['id'],'header':{},'records':[]}
        for page in document['pages']:
            header,rows=parse_scan(page['text'],page['page'])
            if merged['header'] and merged['header']!=header:raise ValueError('conflicting scan headers')
            merged['header']=header;merged['records'].extend(rows)
        documents.append(merged)
    return reconcile(documents)


if __name__=='__main__':
    for line in sys.stdin:
        request=json.loads(line)
        try:print(json.dumps({'answer':decide(request['payload'])}),flush=True)
        except (ValueError,KeyError,IndexError,ArithmeticError) as error:
            print(json.dumps({'error_type':type(error).__name__,'error':str(error)}),flush=True)
