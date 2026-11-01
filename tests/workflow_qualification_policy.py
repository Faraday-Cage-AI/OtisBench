"""Deterministic observation-only feasibility control, NOT a model result.

No evaluator world, private IDs, task seeds, disruption labels or reference
solver imports. Uses only projected business records. Conservative initial
settling time is fixed across all episodes and is disclosed in the report.
"""
import math


def controls(x):
    fields=x['control_fields']
    if 'rpm' in fields:
        rpm=min(x['max_rpm'],x['surface_m_min']*1000/(math.pi*x['diameter_mm']))
        return dict(rpm=rpm,feed_mm_min=rpm*x['teeth']*x['chip_mm_tooth'])
    if 'temperature_c' in fields:return dict(temperature_c=x['target_temperature_c'],soak_minutes=x['base_soak_minutes']+x['minutes_per_section_mm']*x['section_mm'])
    if 'heat_kj_mm' in fields:return dict(heat_kj_mm=.06*x['volts']*x['amps']*x['efficiency']/x['travel_mm_min'])
    if 'clamp_kn' in fields:return dict(clamp_kn=x['projected_area_cm2']*x['cavity_mpa']*x['cavities']*x['safety_factor']/10)
    if 'active_fraction' in fields:return dict(active_fraction=(x['ingredient_a_kg']*x['assay_a']+x['ingredient_b_kg']*x['assay_b'])/(x['ingredient_a_kg']+x['ingredient_b_kg']-x['solvent_loss_kg']))
    if 'conveyor_mm_min' in fields:return dict(conveyor_mm_min=x['zone_length_mm']/(x['residence_seconds']/60))
    return dict(energy_kwh_per_unit=x['energy_kwh_batch']/x['batch_units'])


class FeasibilityPolicy:
    def __init__(self):self.generator=self.plan();self.started=False
    def decide(self,track,payload):
        if not self.started:self.started=True;return next(self.generator)
        result={**payload['last_result'],'clock_minute':payload['clock_minute']}
        if not result['ok']:raise ValueError('feasibility control rejected: '+str(result))
        return self.generator.send(result)

    def plan(self):
        records={};clock=0
        def action(tool,**arguments):
            nonlocal clock
            r=yield dict(tool=tool,arguments=arguments);clock=r['clock_minute'];return r
        def read(*systems):
            for system in systems:
                r=yield from action('read',system=system);records[system]=r['records']
        def wait_until(minute):
            while minute>clock:
                yield from action('wait',minutes=min(300,minute-clock))
        yield from action('wait',minutes=20)
        yield from read('ERP','PLM','MES','HR','QMS','CMMS','WMS','SCM')
        erp=records['ERP'];qty=erp['required_units']
        for bulletin in records['QMS'].get('recall_bulletins',[]):
            for lot in bulletin['affected_lots']:
                yield from read('QMS','WMS');yield from action('place_recall_hold',lot_id=lot)
        yield from read('PLM','WMS')
        eligible=[l for l in records['WMS']['lots'].values() if l['status']=='released' and l['material']==records['PLM']['material'] and l['ownership']=='owned' and l['certificate'] and l['expiry_minute']>clock+1000]
        shortage=qty-sum(l['units']-l['reserved'] for l in eligible)
        if shortage>0:
            yield from read('ERP','PLM','SCM')
            purchase=dict(units=max(shortage,records['SCM']['supplier']['minimum_units']),expedited=False)
            a=yield from action('request_approval',kind='purchase',payload=purchase)
            po=yield from action('purchase',**purchase,approval_id=a['approval']['id'])
            yield from wait_until(po['purchase_order']['due_minute'])
        yield from read('PLM','WMS');remaining=qty
        for lot in sorted(records['WMS']['lots'].values(),key=lambda l:(l['expiry_minute'],l['id'])):
            if lot['status']!='released' or lot['material']!=records['PLM']['material'] or lot['ownership']!='owned' or not lot['certificate'] or lot['expiry_minute']<clock+1000:continue
            n=min(remaining,lot['units']-lot['reserved'])
            if n:
                yield from read('PLM','WMS');yield from action('reserve_material',lot_id=lot['id'],units=n);remaining-=n
            if not remaining:break
        if remaining:raise ValueError('uncovered input requirement')
        yield from read('PLM','MES')
        route=[o['id'] for o in records['MES']['operations']]
        for oid in route:
            yield from read('PLM','MES','HR','QMS','WMS','CMMS')
            op=next(o for o in records['MES']['operations'] if o['id']==oid)
            fixture=records['QMS']['instruments'][op['fixture']]
            if fixture['calibrated_until_minute']<clock+500:
                yield from action('calibrate',fixture_id=op['fixture']);yield from read('QMS','CMMS')
            candidates=[m for m in records['MES']['machines'].values() if m['process']==op['process'] and m['status']=='available' and m['batch_limit']>=qty]
            if not candidates:raise ValueError('no machine')
            machine=min(candidates,key=lambda m:((math.ceil(m['setup_minutes']+m['minutes_per_unit']*qty)+m.get('external_lead_minutes',0))*m['cents_per_minute']+(records['CMMS']['tool_change_cost_cents'] if m['tool_remaining_units']<qty else 0),m['id']))
            if machine['tool_remaining_units']<qty:
                yield from read('CMMS','MES');yield from action('replace_tool',machine_id=machine['id'])
            yield from read('PLM','MES','HR','QMS','WMS')
            fixture=records['QMS']['instruments'][op['fixture']]
            start=max([clock+1]+[b['finish'] for b in fixture['busy']]+[b['finish'] for b in machine['busy']])
            duration=math.ceil(machine['setup_minutes']+machine['minutes_per_unit']*qty)+machine.get('external_lead_minutes',0)
            people=[p for p in records['HR']['operators'].values() if p['process']==op['process'] and p['certified_until_minute']>=start+duration and not any(start<b['finish'] and b['start']<start+duration for b in p['busy'])]
            if not people:raise ValueError('no certified operator')
            person=min(people,key=lambda p:p['id'])
            args=dict(operation_id=oid,machine_id=machine['id'],operator_id=person['id'],start_minute=start,units=qty,controls=controls(records['PLM']['instructions'][oid]))
            if start+duration>machine.get('regular_until_minute',3000):
                # Approval and the subsequent call each advance simulated time.
                args['start_minute']=max(start,clock+3)
                a=yield from action('request_approval',kind='overtime',payload=args)
                approval=a['approval']['id']
            else:approval=None
            result=yield from action('start_operation',**args,approval_id=approval)
            yield from wait_until(result['operation']['finish'])
            cert=None
            if machine['external']:
                yield from read('SCM')
                cert=next(c['id'] for c in records['SCM']['certificates'].values() if c.get('operation_id')==oid)
            yield from action('complete_operation',operation_id=oid,certificate_id=cert)
        yield from read('QMS','PLM','MES')
        fixture=records['MES']['operations'][-1]['fixture']
        result=yield from action('measure',fixture_id=fixture);inspection=result['inspection']
        if inspection['failed_units']:
            yield from action('disposition',inspection_id=inspection['id'],decision='rework')
            yield from read('ERP','PLM')
            payload=dict(inspection_id=inspection['id'],units=inspection['failed_units'])
            a=yield from action('request_approval',kind='rework',payload=payload)
            yield from action('rework',**payload,approval_id=a['approval']['id'])
            yield from read('QMS','PLM','MES')
            result=yield from action('measure',fixture_id=fixture);inspection=result['inspection']
        yield from action('disposition',inspection_id=inspection['id'],decision='accept')
        yield from read('QMS','PLM','WMS')
        yield from action('release_batch',inspection_id=inspection['id'])
        yield from read('WMS','ERP')
        serials=sorted(records['WMS']['serials']);evidence=[inspection['id']]
        for order in sorted(records['ERP']['orders'],key=lambda o:(o['due_minute'],o['id'])):
            n=order['quantity'];chosen=serials[:n];serials=serials[n:]
            shipment=yield from action('ship',order_id=order['id'],units=n,serials=chosen)
            evidence.append(shipment['shipment']['id'])
        yield from action('finish',evidence_ids=evidence)


if __name__=='__main__':
    import json
    import sys
    policy=FeasibilityPolicy()
    for line in sys.stdin:
        message=json.loads(line)
        print(json.dumps(policy.decide(message['track'],message['payload'])),flush=True)
