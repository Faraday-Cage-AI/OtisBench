"""Manufacturing route × disruption contracts with two fixed parameter draws."""
from copy import deepcopy
import hashlib
import random
import math

ROUTES = {
 'precision_cnc':('aerospace bracket','6061-T6',('mill','deburr','cmm')),
 'turned_shaft':('precision shaft','4140',('turn','heat','grind','cmm')),
 'sheet_fabrication':('formed enclosure','5052-H32',('laser','bend','cmm')),
 'welded_structure':('structural frame','A36',('laser','weld','ndt')),
 'sand_casting':('pump casting','EN-GJL-250',('melt','pour','heat','cmm')),
 'die_casting':('die-cast housing','A380',('cast','trim','xray')),
 'injection_molding':('molded connector','PA66-GF30',('mold','deflash','vision')),
 'extrusion':('extruded profile','6063-T5',('extrude','cut','cmm')),
 'rubber_molding':('elastomer seal','FKM-75',('mix','mold','cure','test')),
 'composite_layup':('composite panel','CFRP-prepreg',('layup','autoclave','ultrasonic')),
 'pcb_assembly':('control board','FR4-TG170',('solder','aoi','ict','test')),
 'cable_harness':('wiring harness','UL1015-18AWG',('cut','crimp','hipot')),
 'battery_module':('battery module','LFP-prismatic',('weld','assemble','test')),
 'semiconductor':('sensor wafer','Si-200mm',('etch','deposit','probe')),
 'metal_additive':('printed manifold','Ti6Al4V',('build','stress_relieve','depowder','cmm')),
 'heat_treatment':('hardened tooling','D2',('furnace','quench','hardness')),
 'electroplating':('plated contact','C110',('clean','plate','thickness')),
 'anodizing':('anodized panel','6061-T6',('clean','anodize','seal','thickness')),
 'powder_coating':('coated cabinet','CRS',('blast','coat','cure','thickness')),
 'gear_manufacturing':('transmission gear','8620',('hob','heat','grind','cmm')),
 'bearing_assembly':('bearing cartridge','52100',('turn','grind','assemble','test')),
 'pump_assembly':('industrial pump','316L',('mill','assemble','pressure','run')),
 'motor_assembly':('electric motor','Cu-ETP',('wind','impregnate','balance','test')),
 'valve_assembly':('control valve','316L',('turn','lap','assemble','pressure')),
 'hydraulic_cylinder':('hydraulic actuator','ST52',('hone','assemble','pressure')),
 'packaging':('folded carton','SBS-350',('print','diecut','glue','vision')),
 'food_processing':('packed food batch','food-grade-base',('mix','cook','fill','microbiology')),
 'chemical_blending':('industrial coating batch','resin-A',('weigh','mix','filter','assay')),
 'tablet_manufacturing':('compressed tablet lot','granulate-A',('granulate','compress','coat','assay')),
 'textile':('technical textile','PET-600D',('weave','dye','cut','vision')),
 'glass_fabrication':('optical glass panel','borosilicate',('form','anneal','cut','optical')),
 'ceramic_manufacturing':('technical ceramic','Al2O3-96',('press','sinter','grind','cmm')),
}
DISRUPTIONS = (
 'split_material_lots','late_quality_hold','machine_breakdown','expired_calibration',
 'drawing_effectivity','late_inbound_material','failed_final_inspection','certification_gap',
 'outside_processing','tool_life_exhaustion','customer_allocation','serial_recall',
 'batch_capacity','overtime_window','shared_fixture','compound_recovery',
)
SYSTEMS=('ERP','PLM','WMS','MES','QMS','CMMS','HR','SCM')


def process_instruction(process,revision,quantity,rng):
    common=dict(revision=revision,tolerance_fraction=.001)
    if process in {'mill','turn','grind','hob','hone','lap','cut'}:
        return dict(**common,control_kind='cutting',surface_m_min=rng.randint(100,180),diameter_mm=rng.randint(10,40),max_rpm=6000,teeth=4,chip_mm_tooth=.04,
                    rule='rpm=min(1000*surface_m_min/(pi*diameter_mm),max_rpm); feed_mm_min=rpm*teeth*chip_mm_tooth. Set both controls.')
    if process in {'heat','cure','autoclave','furnace','stress_relieve','sinter','anneal','cook'}:
        return dict(**common,control_kind='thermal',target_temperature_c=rng.randint(150,350),section_mm=rng.randint(2,8),base_soak_minutes=20,minutes_per_section_mm=5,
                    rule='Set temperature_c to target_temperature_c and soak_minutes to base_soak_minutes+5*section_mm.')
    if process=='weld':
        return dict(**common,control_kind='welding',volts=24,amps=rng.randint(140,200),efficiency=.8,travel_mm_min=rng.randint(200,300),
                    rule='Set heat_kj_mm=volts*amps*60*efficiency/(1000*travel_mm_min).')
    if process in {'mold','cast','press'}:
        return dict(**common,control_kind='forming',projected_area_cm2=rng.randint(20,60),cavity_mpa=40,cavities=2,safety_factor=1.15,
                    rule='Set clamp_kn=projected_area_cm2*100*cavity_mpa*cavities*safety_factor/1000.')
    if process in {'mix','weigh','granulate','filter','assay'}:
        return dict(**common,control_kind='batch',ingredient_a_kg=rng.randint(30,60),assay_a=.8,ingredient_b_kg=60,assay_b=.1,solvent_loss_kg=5,
                    rule='Set active_fraction=(ingredient_a_kg*assay_a+ingredient_b_kg*assay_b)/(ingredient_a_kg+ingredient_b_kg-solvent_loss_kg).')
    if process in {'solder','coat','plate','anodize','deposit','dye','impregnate'}:
        return dict(**common,control_kind='residence',zone_length_mm=rng.randint(800,1600),residence_seconds=120,
                    rule='Set conveyor_mm_min=zone_length_mm*60/residence_seconds.')
    return dict(**common,control_kind='energy',energy_kwh_batch=rng.randint(60,120),batch_units=quantity,
                rule='Set energy_kwh_per_unit=energy_kwh_batch/batch_units.')


def catalog():
    rows=[]
    for family,(product,material,route) in ROUTES.items():
        for variant,disruption in enumerate(DISRUPTIONS):
            for draw in range(2):
                task_id=f'mfg-flow-{family}-{variant+1:02}-{draw+1:02}'
                seed=int.from_bytes(hashlib.sha256(task_id.encode()).digest()[:8],'big')
                rows.append(dict(id=task_id,family=family,disruption=disruption,draw=draw,seed=seed,
                    title=f'{product.capitalize()}: {disruption.replace("_"," ")}',
                    route=list(route),systems=list(SYSTEMS),max_tool_calls=240,horizon_minutes=2400,
                    prompt=f'Complete manufacturing and shipment of the {product} customer orders. Reconcile ERP orders, PLM process revisions, material lots, equipment, personnel qualifications, supplier receipts, and QMS disposition. Manufacture through the released route, recover from the emerging {disruption.replace("_"," ")}, and ship every required serialized unit against its order. Submit the actual inspection and shipment record IDs.'))
    return rows


def build_records(task):
    rng=random.Random(task['seed']);family=task['family'];variant=task['disruption']
    product,material,route=ROUTES[family];quantity=rng.randint(18,32)
    late_revision=variant in ('drawing_effectivity','compound_recovery')
    rev='A' if late_revision else 'C';required_rev='B' if late_revision else rev
    split=variant=='customer_allocation'
    orders=[dict(id='SO-1',quantity=quantity-6 if split else quantity,shipped=0,due_minute=1900,priority=2)]
    if split:orders.append(dict(id='SO-2',quantity=6,shipped=0,due_minute=1000,priority=1))
    operations=[];machines={};operators={};fixtures={};instructions={}
    for i,process in enumerate(route):
        op=f'OP-{i+1:02}';machine=f'M-{i+1:02}';alternate=f'M-{i+1:02}-ALT';operator=f'EMP-{i+1:02}';qualified=f'EMP-{i+1:02}-Q';fixture=f'FIX-{i+1:02}'
        duration=rng.randint(2,5);setup=rng.randint(8,18)
        operations.append(dict(id=op,process=process,predecessor=f'OP-{i:02}' if i else None,
                               fixture=fixture,status='pending',machine=None,operator=None,start=None,finish=None,units=0,revision=None))
        for mid,factor,cost in [(machine,1,180),(alternate,1.3,280)]:
            machines[mid]=dict(id=mid,process=process,status='available',setup_minutes=setup,
                              minutes_per_unit=duration*factor,cents_per_minute=cost,busy=[],
                              batch_limit=quantity,external=False,tool_remaining_units=quantity+20)
        machines[machine]['batch_limit']=max(1,quantity//2) if variant=='batch_capacity' and i==0 else quantity
        if variant=='batch_capacity' and i==0:machines[alternate]['batch_limit']=quantity+10
        if variant=='tool_life_exhaustion' and i==0:machines[machine]['tool_remaining_units']=quantity-1
        if variant=='outside_processing' and i==1:
            machines[machine].update(external=True,certificate_required=True,external_lead_minutes=90)
            machines[alternate]['status']='unavailable'
        if variant=='machine_breakdown' and i==0:machines[machine]['warning']='Spindle vibration alarm exceeded the operating threshold.'
        gap=variant=='certification_gap' and i==0
        operators[operator]=dict(id=operator,process=process,certified_until_minute=0 if gap else 2500,busy=[])
        operators[qualified]=dict(id=qualified,process=process,certified_until_minute=3000,busy=[])
        fixtures[fixture]=dict(id=fixture,calibrated_until_minute=0 if variant=='expired_calibration' and i==len(route)-1 else 2600,busy=[])
        if variant=='shared_fixture' and i==0:fixtures[fixture]['busy']=[dict(start=0,finish=180,source='other-work-order')]
        instructions[op]=process_instruction(process,rev,quantity,rng)
    notices=[]
    if late_revision:notices.append('Released revision B arrives at minute 18 and governs ALL customer shipments. Reconcile B before starting production; A cannot satisfy the order.')
    if variant in ('late_quality_hold','compound_recovery'):notices.append('Supplier quality investigation for LOT-MAIN completes at minute 18; reconcile disposition before consuming that lot.')
    if variant in ('machine_breakdown','compound_recovery'):notices.append('Primary first-operation machine has an active condition warning; reassess its status before starting.')
    if variant=='overtime_window':
        for order in orders:order['due_minute']=1700
        for machine in machines.values():machine['regular_until_minute']=120
        notices.append('Machine operation after minute 120 requires action-bound overtime approval; order deadlines remain binding.')
    if variant=='late_inbound_material':notices.append('Existing PO delivery cannot cover the full order; decide between expedited and standard additional supply.')
    first=quantity//2
    inbound={}
    if variant=='late_inbound_material':
        inbound['PO-DELAYED']=dict(id='PO-DELAYED',units=quantity-first,lot_id='LOT-DELAYED',status='in_transit',due_minute=720)
    lots={
      'LOT-MAIN':dict(id='LOT-MAIN',material=material,units=first if variant in ('split_material_lots','late_inbound_material') else quantity,
                      reserved=0,status='released',expiry_minute=3000,certificate='CERT-MAIN',ownership='owned'),
      'LOT-ALT':dict(id='LOT-ALT',material=material,units=quantity-first if variant=='split_material_lots' else quantity//2,
                     reserved=0,status='released',expiry_minute=2900,certificate='CERT-ALT',ownership='owned'),
      'LOT-LOOKALIKE':dict(id='LOT-LOOKALIKE',material=next(spec[1] for spec in ROUTES.values() if spec[1]!=material),units=quantity*4,reserved=0,status='released',expiry_minute=4000,certificate='CERT-X',ownership='owned'),
      'LOT-CONSIGNED':dict(id='LOT-CONSIGNED',material=material,units=quantity*3,reserved=0,status='released',expiry_minute=4000,certificate='CERT-C',ownership='supplier'),
    }
    if variant=='late_inbound_material':lots['LOT-ALT']['units']=0
    lots['LOT-UNCERTIFIED']=dict(id='LOT-UNCERTIFIED',material=material,units=quantity*2,reserved=0,status='released',expiry_minute=4000,certificate=None,ownership='owned')
    baseline_cost=sum(math.ceil(machines[f'M-{i+1:02}']['setup_minutes']+machines[f'M-{i+1:02}']['minutes_per_unit']*quantity+machines[f'M-{i+1:02}'].get('external_lead_minutes',0))*machines[f'M-{i+1:02}']['cents_per_minute'] for i in range(len(route)))
    if variant=='overtime_window':baseline_cost*=2
    recovery_allowance=14000
    if variant in ('machine_breakdown','compound_recovery','batch_capacity'):
        primary=machines['M-01'];alt=machines['M-01-ALT']
        recovery_allowance+=math.ceil(alt['setup_minutes']+alt['minutes_per_unit']*quantity)*alt['cents_per_minute']-math.ceil(primary['setup_minutes']+primary['minutes_per_unit']*quantity)*primary['cents_per_minute']
    if variant in ('late_inbound_material','late_quality_hold','compound_recovery'):recovery_allowance+=math.ceil(quantity/2)*1800+8000
    budget=math.ceil(baseline_cost*1.08)+recovery_allowance
    if variant=='serial_recall':lots['LOT-RECALL']=dict(id='LOT-RECALL',material=material,units=8,reserved=0,status='released',expiry_minute=3000,certificate='CERT-R',ownership='owned',recall_notice=True)
    change_requests=[dict(document_id='ECO-7',status='pending',required_revision='B',review_due_minute=18)] if late_revision else []
    investigations=[dict(case_id='SQ-4',lot_id='LOT-MAIN',status='pending',review_due_minute=18)] if variant in ('late_quality_hold','compound_recovery') else []
    recall_bulletins=[dict(id='RECALL-1',affected_lots=['LOT-RECALL'],status='active')] if variant=='serial_recall' else []
    equipment_alerts=[dict(machine_id='M-01',severity='high',reading='spindle vibration above operating threshold',status='open')] if variant in ('machine_breakdown','compound_recovery') else []
    return dict(ERP=dict(product=product,work_order='WO-1',orders=orders,required_revision=required_rev,required_units=quantity,
                         allow_partial_shipments=variant!='customer_allocation',budget_cents=budget,notices=notices),
                PLM=dict(revision=rev,material=material,route=operations,instructions=instructions,change_requests=change_requests,
                         rework=dict(process='controlled_rework',minutes=45,unit_cost_cents=350)),
                WMS=dict(lots=lots,reservations={},shipments={},finished_stock=0,serials={}),
                MES=dict(operations=deepcopy(operations),machines=machines,rework_status=None),
                QMS=dict(instruments=fixtures,inspections={},release=None,supplier_investigations=investigations,recall_bulletins=recall_bulletins,recall_required=variant=='serial_recall',recall_holds=[],
                         inspection_result_available=False,failed_units=None),
                CMMS=dict(equipment_alerts=equipment_alerts,calibration_minutes=35,calibration_cost_cents=5000,tool_change_minutes=20,tool_change_cost_cents=4000),
                HR=dict(operators=operators),SCM=dict(purchase_orders=inbound,certificates={},supplier=dict(id='SUP-1',material=material,
                         unit_cents=1800,minimum_units=4,standard_lead_minutes=200,expedited_lead_minutes=60,expedite_cents=8000)))
