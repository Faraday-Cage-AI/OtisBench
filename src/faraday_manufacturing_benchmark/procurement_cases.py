"""Coherent synthetic procure-to-pay records and raw source documents.

Contracts are disclosed as evaluator metadata only. Parameter draws vary the
commercial quantities and prices; they are not independent workflow families.
"""
from copy import deepcopy
import hashlib
import math
import random

CONTRACTS=('standard_purchase','supplier_suspension','quote_revision','partial_delivery',
 'certificate_hold','unit_conversion','quantity_discount','invoice_variance',
 'duplicate_invoice','bank_change','short_delivery','compound_recovery')
SYSTEMS=('ERP','SCM','WMS','QMS','AP','TREASURY')


def catalog():
    tasks=[]
    for contract in CONTRACTS:
        for draw in range(4):
            tid=f'p2p-{contract}-{draw+1:03}'
            tasks.append(dict(id=tid,contract=contract,draw=draw,
                seed=int.from_bytes(hashlib.sha256(tid.encode()).digest()[:8],'big'),
                provenance='synthetic-generated',systems=list(SYSTEMS),max_tool_calls=180,horizon_minutes=400))
    return tasks


def document(doc_id,title,mime,body,available=0):
    return dict(id=doc_id,title=title,mime_type=mime,body=body,available_minute=available)


def quote_document(qid,supplier,revision,pack,price,lead,capacity,moq,freight,tiers,available=0,status='released'):
    tier_text='; '.join(f'{minimum} or more packs: USD {cents/100:.2f}/pack for ALL packs' for minimum,cents in tiers)
    body=(f'From: purchasing@{supplier.lower()}.example\nTo: buyer@synthetic-factory.example\n'
        f'Subject: Offer {qid}, revision {revision}\n\nSupplier reference: {supplier}\n'
        f'Offer status: {status}. Revision: {revision}.\n'
        f'Article: ITEM-1, grade G2. Unit of purchase: PACK. Each pack contains {pack} EA.\n'
        f'Base price: USD {price/100:.2f} per PACK. Minimum order: {moq} packs. '
        f'Available allocation: {capacity} packs.\n'
        f'Price breaks: {tier_text or "none"}.\n'
        f'Delivery lead: {lead} manufacturing minutes from PO placement. '
        f'Freight per PO: USD {freight/100:.2f}. Quote validity: through minute 300.\n'
        f'Payment: exact approved invoice amount after receiving and quality reconciliation.\n')
    return document(qid,'Supplier offer','message/rfc822',body,available)


def build(task):
    rng=random.Random(task['seed']);contract=task['contract'];pack=24 if contract=='unit_conversion' else 8
    n=rng.randrange(8,13)*pack;price=rng.randrange(85,116)*pack
    shortage=pack if contract in ('short_delivery','compound_recovery') else 0
    damaged=pack if contract in ('certificate_hold','compound_recovery') else 0
    partial=contract in ('partial_delivery','compound_recovery')
    data=dict(required_units=n,pack_units=pack,base_price_cents=price,short_units=shortage,damaged_units=damaged,
        partial=partial,certificate_delay=contract in ('certificate_hold','compound_recovery'),
        invoice_variance=contract in ('invoice_variance','compound_recovery'),
        duplicate=contract=='duplicate_invoice',bank_change=contract in ('bank_change','compound_recovery'),
        quote_change=contract in ('quote_revision','compound_recovery'),
        supplier_suspension=contract in ('supplier_suspension','compound_recovery'))
    # Budget covers a correctly sized primary order, one replacement pack for
    # genuine damage/shortage and fees, while excluding unlimited overbuying.
    base_packs=math.ceil(n/pack);budget=(base_packs+shortage//pack+damaged//pack+2)*(price+pack*35)+2400
    suppliers=[];quotes={};documents={};banks={}
    for i,(premium,lead,capacity) in enumerate(((0,12,base_packs+4),(pack*25,5,base_packs+8),(-pack*15,150,base_packs+4)),1):
        sid=f'SUP-{i}';qid=f'DOC-Q{i}';tiers=[(10,price-pack*15)] if contract=='quantity_discount' and i==1 else []
        q=dict(id=qid,supplier_id=sid,revision=1,pack_units=pack,price_cents=price+premium,lead_minutes=lead,capacity_packs=capacity,minimum_packs=1,freight_cents=600,tiers=tiers,valid_until=300,status='released')
        quotes[qid]=q
        documents[qid]=quote_document(qid,sid,1,pack,q['price_cents'],lead,capacity,1,600,tiers)
        suppliers.append(dict(id=sid,approved=True,status='active',approved_grade='G2',bank_account=f'ACCT-{i}'))
        banks[sid]=dict(supplier_id=sid,verified_account=f'ACCT-{i}',verification_status='verified',pending_change=None)
    erp=dict(requisition_id='REQ-1',item_id='ITEM-1',grade='G2',required_units=n,need_by_minute=120,budget_cents=budget,
        receiving_policy='Receive physical deliveries exactly as stated on the carrier delivery CSV. Inspect every receipt. Accept only undamaged units with a released matching certificate; keep damaged/uncertified units quarantined.',
        purchasing_policy='Buy whole packs from approved active suppliers using an effective released quote. Use all-units price tiers, add freight once per PO, and remain within budget. Quote price/capacity and authorization are enforced; no tool chooses a supplier or order quantity for you.',
        invoice_policy='One current original invoice per PO may be approved. Reconcile it against the PO total and recorded physical receipts, including supplier credit for short-delivered units. Hold superseded, duplicate or discrepant documents; only approve a released corrected version. No AP approvals before all delivery documents for that PO have been received and dispositioned.',
        payment_policy='Pay each approved invoice exactly once to the treasury-verified supplier account. A supplier email is not bank verification. Verify a pending change through the treasury callback tool before using a new account.',
        completion_policy='Cover the requisition with accepted physical stock by need_by_minute, reconcile every PO/invoice, settle every approved invoice exactly once, disposition every issued duplicate/superseded bill, and finish with persisted receipt and payment evidence. Budget counts actual purchase commitments, net of documented shortage credits.')
    records=dict(ERP=erp,SCM=dict(suppliers=suppliers,purchase_orders={},pending_supplier_update=dict(status='pending',available_minute=6) if data['supplier_suspension'] or data['quote_change'] else None),
        WMS=dict(receipts={},accepted_stock_units=0,quarantined_stock_units=0),QMS=dict(inspections={}),
        AP=dict(invoices={},payments={},document_dispositions={}),TREASURY=dict(supplier_banks=banks))
    if data['bank_change']:
        documents['DOC-BANK']=document('DOC-BANK','Supplier remittance request','message/rfc822',
            'From: accounts@sup-1.example\nSubject: New remittance details\n\nSupplier SUP-1 requests payments to ACCT-NEW. This email is not an independent callback confirmation. Contact treasury using the approved callback workflow.\n')
        banks['SUP-1']['pending_change']=dict(request_document_id='DOC-BANK',requested_account='ACCT-NEW',status='unverified')
    return dict(records=records,quotes=quotes,documents=documents,configuration=data)
