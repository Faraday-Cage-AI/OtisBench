"""Transactional, event-driven manufacturing work orders and serialized fulfillment."""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
import math
from .shopfloor_cases import build_records,SYSTEMS


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def overlap(start,finish,rows):
    return any(start<r['finish'] and r['start']<finish for r in rows)


def required_controls(instruction):
    x=instruction;kind=x['control_kind']
    if kind=='cutting':
        rpm=min(1000*x['surface_m_min']/(math.pi*x['diameter_mm']),x['max_rpm'])
        return dict(rpm=rpm,feed_mm_min=rpm*x['teeth']*x['chip_mm_tooth'])
    if kind=='thermal':return dict(temperature_c=x['target_temperature_c'],soak_minutes=x['base_soak_minutes']+x.get('minutes_per_section_mm',5)*x['section_mm'])
    if kind=='welding':return dict(heat_kj_mm=x['volts']*x['amps']*60*x['efficiency']/(1000*x['travel_mm_min']))
    if kind=='forming':return dict(clamp_kn=x['projected_area_cm2']*100*x['cavity_mpa']*x['cavities']*x['safety_factor']/1000)
    if kind=='batch':return dict(active_fraction=(x['ingredient_a_kg']*x['assay_a']+x['ingredient_b_kg']*x['assay_b'])/(x['ingredient_a_kg']+x['ingredient_b_kg']-x['solvent_loss_kg']))
    if kind=='residence':return dict(conveyor_mm_min=x['zone_length_mm']*60/x['residence_seconds'])
    return dict(energy_kwh_per_unit=x['energy_kwh_batch']/x['batch_units'])


# Argument contracts are public and are independent of the scenario's answer values.
TOOLS={
 'read':dict(system='ERP | PLM | WMS | MES | QMS | CMMS | HR | SCM'),
 'wait':dict(minutes='integer 1..300'),
 'reserve_material':dict(lot_id='lot ID',units='positive integer'),
 'release_reservation':dict(reservation_id='reservation ID'),
 'request_approval':dict(kind='purchase | overtime | rework',payload='exact action arguments without approval_id'),
 'purchase':dict(units='integer >= supplier minimum',expedited='boolean',approval_id='approved request ID'),
 'place_recall_hold':dict(lot_id='recalled lot ID'),
 'calibrate':dict(fixture_id='instrument ID'),
 'replace_tool':dict(machine_id='machine ID'),
 'start_operation':dict(operation_id='next operation ID',machine_id='qualified available machine ID',operator_id='qualified employee ID',
                         start_minute='integer >= current clock',units='integer',controls='object matching released PLM process controls',approval_id='overtime approval ID or null'),
 'reroute_interrupted_operation':dict(operation_id='interrupted operation ID; retains existing WIP and cancels old resource bookings'),
 'complete_operation':dict(operation_id='running operation ID',certificate_id='outside-processing receipt certificate ID or null'),
 'measure':dict(fixture_id='last route operation fixture ID'),
 'disposition':dict(inspection_id='inspection ID',decision='accept | rework'),
 'rework':dict(inspection_id='failed inspection ID',units='exact failed units',approval_id='approved request ID'),
 'release_batch':dict(inspection_id='accepted current inspection ID'),
 'ship':dict(order_id='customer order ID',units='positive integer',serials='list of previously unshipped serial IDs'),
 'finish':dict(evidence_ids='list of existing inspection and shipment IDs'),
}


class ManufacturingWorkflow:
    def __init__(self,task):
        self.task=deepcopy(task);self.records=build_records(task);self.clock=0;self.trace=[];self.finished=False
        self.versions={s:1 for s in SYSTEMS};self.read_versions={};self.approvals={};self.approval_uses=set()
        self.spent_cents=0;self.violations=[];self.events=[];self.parameters_ok=True;self.consumed=[];self.inspection_counter=0
        self.rework_completed=False;self.source_commitment=digest(dict(task=task,records=self.records))
        self.initial_state_hash=self.state_hash()

    def state_hash(self):
        return digest(dict(clock=self.clock,records=self.records,versions=self.versions,read_versions=self.read_versions,
                           approvals=self.approvals,approval_uses=sorted(self.approval_uses),spent=self.spent_cents,
                           violations=self.violations,events=self.events,parameters_ok=self.parameters_ok,consumed=self.consumed,
                           finished=self.finished,rework_completed=self.rework_completed,inspection_counter=self.inspection_counter))

    def _bump(self,*systems):
        for system in systems:self.versions[system]+=1

    def _current(self,*systems):
        return all(self.read_versions.get(s)==self.versions[s] for s in systems)

    def _advance(self,minutes):
        self.clock+=minutes;variant=self.task['disruption']
        if self.clock>=18 and 'disruption' not in self.events:
            self.events.append('disruption')
            if variant in ('drawing_effectivity','compound_recovery'):
                self.records['PLM']['revision']='B'
                for change in self.records['PLM'].get('change_requests',[]):change['status']='released'
                for instruction in self.records['PLM']['instructions'].values():
                    instruction['revision']='B'
                    key=next(k for k in ('surface_m_min','target_temperature_c','amps','projected_area_cm2','ingredient_a_kg','zone_length_mm','energy_kwh_batch') if k in instruction)
                    instruction[key]+=12
                self._bump('PLM')
            if variant in ('late_quality_hold','compound_recovery'):
                self.records['WMS']['lots']['LOT-MAIN']['status']='hold'
                for investigation in self.records['QMS'].get('supplier_investigations',[]):investigation.update(status='closed',disposition='hold')
                self._bump('WMS','QMS')
            if variant in ('machine_breakdown','compound_recovery'):
                self.records['MES']['machines']['M-01']['status']='down'
                for op in self.records['MES']['operations']:
                    if op['status']=='running' and op['machine']=='M-01' and op['finish']>18:op['status']='interrupted'
                self._bump('MES','CMMS')
        for po in self.records['SCM']['purchase_orders'].values():
            if po['status']=='in_transit' and self.clock>=po['due_minute']:
                lot_id=po['lot_id'];certificate='CERT-'+po['id']
                self.records['WMS']['lots'][lot_id]=dict(id=lot_id,material=self.records['PLM']['material'],units=po['units'],reserved=0,status='released',expiry_minute=4000,certificate=certificate,ownership='owned')
                self.records['SCM']['certificates'][certificate]=dict(id=certificate,lot_id=lot_id,status='accepted');po['status']='received';self._bump('WMS','SCM')
        for operation in self.records['MES']['operations']:
            if operation['status']=='running' and operation.get('external') and self.clock>=operation['finish']:
                certificate='OSP-CERT-'+operation['id']
                if certificate not in self.records['SCM']['certificates']:
                    self.records['SCM']['certificates'][certificate]=dict(id=certificate,operation_id=operation['id'],status='accepted',revision=operation['revision']);self._bump('SCM')

    def _error(self,error,critical=False):
        if critical:self.violations.append(error)
        return dict(ok=False,error=error,clock_minute=self.clock)

    def _spend(self,cents):
        if self.spent_cents+cents>self.records['ERP']['budget_cents']:return False
        self.spent_cents+=cents;return True

    def _authorized(self,approval_id,kind,payload,consume=True):
        request=self.approvals.get(approval_id)
        valid=bool(request and request['kind']==kind and request['payload']==payload and approval_id not in self.approval_uses and request['revision']==self.records['PLM']['revision'])
        if valid and consume:self.approval_uses.add(approval_id)
        return valid

    def call(self,name,**arguments):
        if self.finished:return self._error('workflow already finished')
        if len(self.trace)>=self.task['max_tool_calls']:self.finished=True;return self._error('tool budget exhausted')
        self._advance(1)
        if self.clock>self.task['horizon_minutes']:self.finished=True;result=self._error('workflow horizon exceeded')
        elif name not in TOOLS:result=self._error('unknown tool')
        else:
            try:result=getattr(self,'_do_'+name)(**arguments)
            except (TypeError,KeyError,ValueError) as exc:result=self._error('invalid arguments: '+type(exc).__name__)
        record=dict(index=len(self.trace),tool=name,arguments=deepcopy(arguments),result=deepcopy(result),state_hash=self.state_hash())
        self.trace.append(record);return deepcopy(result)

    def _do_read(self,system):
        if system not in SYSTEMS:return self._error('unknown system')
        self.read_versions[system]=self.versions[system]
        return dict(ok=True,system=system,version=self.versions[system],clock_minute=self.clock,records=deepcopy(self.records[system]))

    def _do_wait(self,minutes):
        if type(minutes) is not int or not 1<=minutes<=300:return self._error('wait requires 1..300 minutes')
        self._advance(minutes)
        return dict(ok=True,clock_minute=self.clock,events=list(self.events))

    def _do_reserve_material(self,lot_id,units):
        if not self._current('PLM','WMS'):return self._error('read current PLM and WMS before reserving')
        if self.records['PLM']['revision']!=self.records['ERP']['required_revision']:return self._error('required drawing revision has not been released')
        lot=self.records['WMS']['lots'].get(lot_id)
        if not lot or type(units) is not int or units<=0:return self._error('invalid lot or units')
        if lot['status']!='released' or lot['material']!=self.records['PLM']['material'] or lot['ownership']!='owned' or not lot['certificate'] or lot['expiry_minute']<self.clock:return self._error('lot is not eligible for this work order')
        if lot['units']-lot['reserved']<units:return self._error('insufficient unreserved lot units')
        rid=f'RES-{len(self.records["WMS"]["reservations"])+1}'
        row=dict(id=rid,lot_id=lot_id,units=units,status='reserved',revision=self.records['PLM']['revision']);lot['reserved']+=units
        self.records['WMS']['reservations'][rid]=row;self._bump('WMS')
        return dict(ok=True,reservation=deepcopy(row))

    def _do_release_reservation(self,reservation_id):
        row=self.records['WMS']['reservations'].get(reservation_id)
        if not row or row['status']!='reserved':return self._error('active reservation required')
        self.records['WMS']['lots'][row['lot_id']]['reserved']-=row['units'];row['status']='cancelled';self._bump('WMS')
        return dict(ok=True,reservation_id=reservation_id)

    def _do_request_approval(self,kind,payload):
        if kind not in ('purchase','overtime','rework') or not isinstance(payload,dict):return self._error('invalid approval kind or payload')
        if not self._current('ERP','PLM'):return self._error('read current ERP and PLM before seeking approval')
        aid=f'APR-{len(self.approvals)+1}'
        self.approvals[aid]=dict(id=aid,kind=kind,payload=deepcopy(payload),revision=self.records['PLM']['revision'])
        return dict(ok=True,approval=deepcopy(self.approvals[aid]))

    def _do_purchase(self,units,expedited,approval_id):
        supplier=self.records['SCM']['supplier'];payload=dict(units=units,expedited=expedited)
        if type(units) is not int or units<supplier['minimum_units'] or type(expedited) is not bool:return self._error('invalid supplier order')
        if not self._authorized(approval_id,'purchase',payload,consume=False):return self._error('purchase authorization mismatch',critical=True)
        cost=units*supplier['unit_cents']+(supplier['expedite_cents'] if expedited else 0)
        if not self._spend(cost):return self._error('purchase exceeds work-order budget')
        self.approval_uses.add(approval_id);pid=f'PO-{len(self.records["SCM"]["purchase_orders"])+1}'
        po=dict(id=pid,units=units,lot_id='LOT-'+pid,status='in_transit',due_minute=self.clock+supplier['expedited_lead_minutes' if expedited else 'standard_lead_minutes'])
        self.records['SCM']['purchase_orders'][pid]=po;self._bump('SCM')
        return dict(ok=True,purchase_order=deepcopy(po),cost_cents=cost)

    def _do_place_recall_hold(self,lot_id):
        lot=self.records['WMS']['lots'].get(lot_id)
        if not self._current('QMS','WMS'):return self._error('read QMS and WMS before containment')
        if not lot or not lot.get('recall_notice'):return self._error('lot is not in recall scope')
        lot['status']='recall_hold'
        if lot_id not in self.records['QMS']['recall_holds']:self.records['QMS']['recall_holds'].append(lot_id)
        self._bump('QMS','WMS');return dict(ok=True,lot_id=lot_id,status='recall_hold')

    def _do_calibrate(self,fixture_id):
        fixture=self.records['QMS']['instruments'].get(fixture_id)
        if not fixture or not self._current('CMMS','QMS'):return self._error('read calibration records and choose valid instrument')
        duration=self.records['CMMS']['calibration_minutes']
        if overlap(self.clock,self.clock+duration,fixture['busy']):return self._error('fixture is occupied during calibration')
        if not self._spend(self.records['CMMS']['calibration_cost_cents']):return self._error('calibration exceeds budget')
        self._advance(duration);fixture['calibrated_until_minute']=self.clock+2500;self._bump('QMS','CMMS')
        return dict(ok=True,fixture_id=fixture_id,calibrated_until_minute=fixture['calibrated_until_minute'])

    def _do_replace_tool(self,machine_id):
        machine=self.records['MES']['machines'].get(machine_id)
        if not machine or not self._current('CMMS','MES'):return self._error('read equipment records and choose a valid machine')
        duration=self.records['CMMS']['tool_change_minutes']
        if overlap(self.clock,self.clock+duration,machine['busy']):return self._error('machine is occupied during tool change')
        if not self._spend(self.records['CMMS']['tool_change_cost_cents']):return self._error('tool change exceeds budget')
        self._advance(duration);machine['tool_remaining_units']=1000;self._bump('MES','CMMS')
        return dict(ok=True,machine_id=machine_id,tool_remaining_units=1000)

    def _do_start_operation(self,operation_id,machine_id,operator_id,start_minute,units,controls,approval_id=None):
        mes=self.records['MES'];plm=self.records['PLM'];erp=self.records['ERP']
        op=next((r for r in mes['operations'] if r['id']==operation_id),None)
        machine=mes['machines'].get(machine_id);operator=self.records['HR']['operators'].get(operator_id)
        if not op or not machine or not operator or type(units) is not int or units!=erp['required_units']:return self._error('invalid operation, resource or complete-lot quantity')
        if type(start_minute) is not int or not self.clock<=start_minute<=self.task['horizon_minutes']:return self._error('operation start is outside current planning horizon')
        self._advance(start_minute-self.clock)
        if not self._current('PLM','MES','HR','QMS','WMS'):return self._error('reconcile current PLM, MES, HR, QMS and WMS before starting')
        if plm['revision']!=erp['required_revision']:return self._error('required process revision is pending')
        if op['status']!='pending' or machine['process']!=op['process'] or operator['process']!=op['process']:return self._error('route operation or qualification mismatch')
        if op['predecessor'] and next(r for r in mes['operations'] if r['id']==op['predecessor'])['status']!='finished':return self._error('predecessor operation is incomplete')
        if type(start_minute) is not int or start_minute<self.clock:return self._error('operation start is in the past')
        duration=math.ceil(machine['setup_minutes']+machine['minutes_per_unit']*units)+(machine.get('external_lead_minutes',0))
        finish=start_minute+duration;fixture=self.records['QMS']['instruments'][op['fixture']]
        if machine['status']!='available' or units>machine['batch_limit'] or units>machine['tool_remaining_units']:return self._error('machine availability, batch size or tool life is insufficient')
        if finish>operator['certified_until_minute'] or finish>fixture['calibrated_until_minute']:return self._error('qualification or calibration expires before completion')
        if any(overlap(start_minute,finish,r['busy']) for r in (machine,operator,fixture)):return self._error('machine, operator or fixture scheduling conflict')
        payload=dict(operation_id=operation_id,machine_id=machine_id,operator_id=operator_id,start_minute=start_minute,units=units,controls=controls)
        overtime=finish>machine.get('regular_until_minute',3000)
        if overtime and not self._authorized(approval_id,'overtime',payload,consume=False):return self._error('overtime requires exact action authorization',critical=True)
        instruction=plm['instructions'][operation_id];targets=required_controls(instruction)
        if not isinstance(controls,dict) or set(controls)!=set(targets):return self._error('process controls do not match the released instruction schema')
        if any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in controls.values()):return self._error('process controls must be finite positive numbers')
        okay=all(math.isclose(controls[k],v,rel_tol=instruction['tolerance_fraction'],abs_tol=1e-8) for k,v in targets.items())
        reservations=[r for r in self.records['WMS']['reservations'].values() if r['status']=='reserved']
        if not op['predecessor'] and not self.consumed:
            if sum(r['units'] for r in reservations)!=units:return self._error('first operation requires exact reserved input quantity')
            if any(r['revision']!=plm['revision'] or self.records['WMS']['lots'][r['lot_id']]['status']!='released' for r in reservations):return self._error('reserved material was held or superseded; replan input')
        cost=duration*machine['cents_per_minute']*(2 if overtime else 1)
        if not self._spend(cost):return self._error('production exceeds work-order budget')
        if overtime:self.approval_uses.add(approval_id)
        if not op['predecessor'] and not self.consumed:
            for reservation in reservations:
                lot=self.records['WMS']['lots'][reservation['lot_id']];lot['units']-=reservation['units'];lot['reserved']-=reservation['units'];reservation['status']='consumed';self.consumed.append(deepcopy(reservation))
            self._bump('WMS')
        booking=dict(start=start_minute,finish=finish,source=op['id'])
        for resource in (machine,operator,fixture):resource['busy'].append(deepcopy(booking))
        machine['tool_remaining_units']-=units
        op.update(status='running',machine=machine_id,operator=operator_id,start=start_minute,finish=finish,units=units,revision=plm['revision'],external=machine['external'],controls=deepcopy(controls),parameters_ok=okay)
        self.parameters_ok=self.parameters_ok and okay;self._bump('MES','HR','QMS')
        return dict(ok=True,operation=deepcopy(op),cost_cents=cost)

    def _do_reroute_interrupted_operation(self,operation_id):
        op=next((o for o in self.records['MES']['operations'] if o['id']==operation_id),None)
        if not op or op['status']!='interrupted':return self._error('only interrupted operations can be rerouted')
        if not self._current('MES','WMS'):return self._error('reconcile interrupted WIP before rerouting')
        for resource in list(self.records['MES']['machines'].values())+list(self.records['HR']['operators'].values())+list(self.records['QMS']['instruments'].values()):
            resource['busy']=[r for r in resource['busy'] if r.get('source')!=operation_id]
        op.update(status='pending',machine=None,operator=None,start=None,finish=None)
        self._bump('MES','HR','QMS');return dict(ok=True,operation_id=operation_id,wip_preserved=True)

    def _do_complete_operation(self,operation_id,certificate_id=None):
        op=next((r for r in self.records['MES']['operations'] if r['id']==operation_id),None)
        if not op or op['status']!='running' or self.clock<op['finish']:return self._error('running operation has not reached completion time')
        if op['external']:
            cert=self.records['SCM']['certificates'].get(certificate_id)
            if not self._current('SCM') or not cert or cert.get('operation_id')!=operation_id or cert.get('revision')!=op['revision']:return self._error('read and reconcile current outside-processing receipt certificate')
        op['status']='finished';self._bump('MES')
        if all(r['status']=='finished' for r in self.records['MES']['operations']):
            self.records['WMS']['finished_stock']=self.records['ERP']['required_units'];self.records['QMS']['inspection_result_available']=True
            for i in range(self.records['ERP']['required_units']):
                serial=f'SN-{i+1:04}';self.records['WMS']['serials'][serial]=dict(id=serial,revision=op['revision'],source_lots=sorted(r['lot_id'] for r in self.consumed),status='unreleased',order_id=None)
            self._bump('QMS','WMS')
        return dict(ok=True,operation_id=operation_id,status='finished')

    def _do_measure(self,fixture_id):
        qms=self.records['QMS'];mes=self.records['MES']
        if qms['release']:return self._error('released batch cannot be remeasured through the production inspection route')
        if not qms['inspection_result_available'] or not all(o['status']=='finished' for o in mes['operations']):return self._error('complete route before final measurement')
        required=mes['operations'][-1]['fixture'];fixture=qms['instruments'].get(fixture_id)
        if fixture_id!=required or not fixture or fixture['calibrated_until_minute']<self.clock:return self._error('use the calibrated route-specified inspection instrument')
        if not self._current('QMS','PLM','MES'):return self._error('read current inspection and route records')
        self.inspection_counter+=1;iid=f'INSP-{self.inspection_counter}'
        failed=0 if self.rework_completed else 3 if self.task['disruption'] in ('failed_final_inspection','compound_recovery') else 0
        if not self.parameters_ok:failed=self.records['ERP']['required_units']
        if any(self.records['WMS']['lots'][r['lot_id']]['status']!='released' for r in self.consumed):failed=self.records['ERP']['required_units']
        row=dict(id=iid,failed_units=failed,passed_units=self.records['ERP']['required_units']-failed,revision=self.records['PLM']['revision'],disposition=None,fixture_id=fixture_id)
        qms['inspections'][iid]=row;qms['failed_units']=failed;self._bump('QMS')
        return dict(ok=True,inspection=deepcopy(row))

    def _do_disposition(self,inspection_id,decision):
        row=self.records['QMS']['inspections'].get(inspection_id)
        if self.records['QMS']['release']:return self._error('released inspection cannot be redispositioned')
        if not row or decision not in ('accept','rework'):return self._error('invalid inspection or disposition')
        if inspection_id!=f'INSP-{self.inspection_counter}' or row['revision']!=self.records['PLM']['revision']:return self._error('inspection is superseded')
        if decision=='accept' and row['failed_units']:return self._error('cannot accept nonconforming product',critical=True)
        if decision=='rework' and not row['failed_units']:return self._error('no failed units require rework')
        row['disposition']=decision;self._bump('QMS');return dict(ok=True,inspection=deepcopy(row))

    def _do_rework(self,inspection_id,units,approval_id):
        row=self.records['QMS']['inspections'].get(inspection_id);payload=dict(inspection_id=inspection_id,units=units)
        if not row or inspection_id!=f'INSP-{self.inspection_counter}' or self.records['QMS']['release'] or row['disposition']!='rework' or type(units) is not int or units!=row['failed_units'] or self.rework_completed:return self._error('rework requires current nonconformance and exact failed quantity')
        if not self._authorized(approval_id,'rework',payload,consume=False):return self._error('rework authorization mismatch',critical=True)
        if not self.parameters_ok or any(self.records['WMS']['lots'][r['lot_id']]['status']!='released' for r in self.consumed):return self._error('material or process-control defect requires a new work order; this rework route cannot repair it')
        process=self.records['PLM']['rework'];cost=units*process['unit_cost_cents']
        if not self._spend(cost):return self._error('rework exceeds budget')
        self.approval_uses.add(approval_id);self._advance(process['minutes']);self.rework_completed=True;self.records['MES']['rework_status']='completed';self._bump('QMS','MES')
        return dict(ok=True,reworked_units=units,clock_minute=self.clock)

    def _do_release_batch(self,inspection_id):
        qms=self.records['QMS'];row=qms['inspections'].get(inspection_id)
        if qms['release']:
            if qms['release']['inspection_id']==inspection_id:return dict(ok=True,release=deepcopy(qms['release']))
            return self._error('batch already released under another inspection')
        if not row or inspection_id!=f'INSP-{self.inspection_counter}' or row['disposition']!='accept' or row['failed_units']:return self._error('current accepted inspection required',critical=True)
        if row['revision']!=self.records['ERP']['required_revision'] or not self._current('QMS','PLM','WMS'):return self._error('reconcile release revision and current quality/material records')
        if qms['recall_required'] and 'LOT-RECALL' not in qms['recall_holds']:return self._error('complete active recall containment before release')
        if any(self.records['WMS']['lots'][r['lot_id']]['status']!='released' for r in self.consumed):return self._error('genealogy contains held material',critical=True)
        qms['release']=dict(inspection_id=inspection_id,revision=row['revision'],minute=self.clock)
        for serial in self.records['WMS']['serials'].values():
            if serial['status']=='unreleased':serial['status']='released'
        self._bump('QMS','WMS');return dict(ok=True,release=deepcopy(qms['release']))

    def _do_ship(self,order_id,units,serials):
        erp=self.records['ERP'];wms=self.records['WMS'];qms=self.records['QMS']
        order=next((o for o in erp['orders'] if o['id']==order_id),None)
        if not qms['release']:return self._error('unreleased product cannot ship',critical=True)
        if not order or type(units) is not int or units<=0 or units>order['quantity']-order['shipped']:return self._error('shipment exceeds remaining order quantity')
        if not isinstance(serials,list) or any(not isinstance(s,str) for s in serials) or len(serials)!=units or len(set(serials))!=units:return self._error('exact unique serial set is required')
        if any(s not in wms['serials'] or wms['serials'][s]['status']!='released' for s in serials):return self._error('serial is absent, held or already shipped',critical=True)
        if not erp['allow_partial_shipments'] and units!=order['quantity']-order['shipped']:return self._error('customer prohibits partial shipment')
        if units>wms['finished_stock']:return self._error('insufficient finished stock')
        sid=f'SHIP-{len(wms["shipments"])+1}'
        row=dict(id=sid,order_id=order_id,units=units,serials=list(serials),source_lots=sorted(r['lot_id'] for r in self.consumed),inspection_id=qms['release']['inspection_id'],revision=qms['release']['revision'],minute=self.clock)
        for s in serials:wms['serials'][s].update(status='shipped',order_id=order_id)
        wms['finished_stock']-=units;order['shipped']+=units;wms['shipments'][sid]=row;self._bump('ERP','WMS')
        return dict(ok=True,shipment=deepcopy(row))

    def _do_finish(self,evidence_ids):
        existing=set(self.records['WMS']['shipments'])|set(self.records['QMS']['inspections'])
        if not isinstance(evidence_ids,list) or any(not isinstance(i,str) for i in evidence_ids) or not evidence_ids or not set(evidence_ids)<=existing:return self._error('finish requires actual inspection and shipment evidence IDs')
        if not set(self.records['WMS']['shipments'])<=set(evidence_ids) or not self.records['QMS']['release'] or self.records['QMS']['release']['inspection_id'] not in evidence_ids:return self._error('cite release inspection and every shipment')
        self.finished=True;return dict(ok=True,finished=True,evidence_ids=list(evidence_ids))

    def grade(self):
        erp=self.records['ERP'];wms=self.records['WMS'];qms=self.records['QMS'];ops=self.records['MES']['operations']
        delivered=sum(o['shipped'] for o in erp['orders']);quantity=erp['required_units']
        checks=dict(orders_fulfilled=delivered==quantity,route_completed=all(o['status']=='finished' for o in ops),
                    conforming_release=bool(qms['release'] and self.parameters_ok and qms['failed_units']==0),
                    traceable_serials=len([s for s in wms['serials'].values() if s['status']=='shipped'])==quantity and bool(self.consumed),
                    on_time=bool(wms['shipments']) and all(s['minute']<=next(o['due_minute'] for o in erp['orders'] if o['id']==s['order_id']) for s in wms['shipments'].values()),
                    within_budget=self.spent_cents<=erp['budget_cents'],recall_contained=not qms['recall_required'] or 'LOT-RECALL' in qms['recall_holds'],
                    finished=self.finished and bool(self.trace) and self.trace[-1]['tool']=='finish' and self.trace[-1]['result'].get('ok',False),
                    current_revision=bool(qms['release'] and qms['release']['revision']==erp['required_revision']),no_critical_violation=not self.violations)
        score=40*delivered/quantity+20*checks['conforming_release']+10*checks['route_completed']+10*checks['traceable_serials']+10*(checks['on_time'] and checks['within_budget'] and delivered==quantity)+10*(checks['finished'] and checks['recall_contained'] and checks['current_revision'])
        if self.violations:score=0
        return dict(task_id=self.task['id'],family=self.task['family'],disruption=self.task['disruption'],score=score,
                    strict_success=all(checks.values()),checks=checks,critical_violations=list(self.violations),
                    delivered_units=delivered,required_units=quantity,elapsed_minutes=self.clock,spent_cents=self.spent_cents,tool_calls=len(self.trace),
                    initial_state_hash=self.initial_state_hash,final_state_hash=self.state_hash(),source_commitment=self.source_commitment)


def replay(task,trace):
    world=ManufacturingWorkflow(task)
    for index,record in enumerate(trace):
        world.call(record['tool'],**record['arguments'])
        if not world.trace or world.trace[-1]!=record:raise ValueError(f'manufacturing workflow replay mismatch at call {index}')
    return world.grade()
