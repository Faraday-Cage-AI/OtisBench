"""The agent sees business observations, never evaluator annotations or solutions."""
from copy import deepcopy
import hashlib
import re
import secrets

# This is a schema registry, not a reference-answer registry.
CONTROL_FIELDS={
    'cutting':['rpm','feed_mm_min'],
    'thermal':['temperature_c','soak_minutes'],
    'welding':['heat_kj_mm'],
    'forming':['clamp_kn'],
    'batch':['active_fraction'],
    'residence':['conveyor_mm_min'],
    'energy':['energy_kwh_per_unit'],
}
PRIVATE_KEYS=frozenset({'seed','draw','disruption','parameters_ok','reference_answer',
    'expected_answer','solution','optimal_plan','oracle','criteria','checks','score',
    'strict_success','source_commitment','state_hash','initial_state_hash',
    'final_state_hash','recall_required','recall_notice','rule','control_kind'})
# New evaluator fields are private unless deliberately added to this contract.
BUSINESS_FIELDS=frozenset("""
ok error clock_minute system version records
product work_order orders required_revision required_units allow_partial_shipments budget_cents
id quantity shipped due_minute priority revision material route instructions rework change_requests
operation_id process predecessor fixture status machine operator start finish units external controls
operation reservation reservation_id reservations lot_id lots reserved expiry_minute certificate ownership
shipments shipment shipment_id finished_stock serials source_lots order_id minute inspection_id
operations machines rework_status setup_minutes minutes_per_unit cents_per_minute busy batch_limit
certificate_required external_lead_minutes tool_remaining_units regular_until_minute source
operators certified_until_minute instruments calibrated_until_minute inspections release
supplier_investigations recall_bulletins recall_holds inspection_result_available failed_units
case_id review_due_minute document_id affected_lots disposition passed_units fixture_id inspection
calibration_minutes calibration_cost_cents tool_change_minutes tool_change_cost_cents equipment_alerts
machine_id severity reading purchase_orders certificates supplier unit_cents minimum_units
standard_lead_minutes expedited_lead_minutes expedite_cents due_minute purchase_order cost_cents
approval kind payload approval_id expedited start_minute operator_id decision reworked_units
finished evidence_ids events wip_preserved
surface_m_min diameter_mm max_rpm teeth chip_mm_tooth tolerance_fraction
target_temperature_c section_mm base_soak_minutes minutes_per_section_mm
volts amps efficiency travel_mm_min projected_area_cm2 cavity_mpa cavities safety_factor
ingredient_a_kg assay_a ingredient_b_kg assay_b solvent_loss_kg zone_length_mm residence_seconds
energy_kwh_batch batch_units rpm feed_mm_min temperature_c soak_minutes heat_kj_mm clamp_kn
active_fraction conveyor_mm_min energy_kwh_per_unit
""".split())

ID_PATTERN=re.compile(r'(?<![A-Za-z0-9-])(?:OSP-CERT|INSP|SHIP|CERT|LOT|EMP|FIX|RES|APR|SO|WO|OP|SN|PO|M)-[A-Za-z0-9-]+')
PREFIX={'M':'EQ','EMP':'EMP','FIX':'FIX','LOT':'LOT','SO':'SO','WO':'WO','OP':'OP',
        'CERT':'CERT','OSP-CERT':'CERT','SN':'SN','RES':'RES','APR':'APR','SHIP':'SHIP','INSP':'INSP','PO':'PO'}


def public_task(task,episode_id='manufacturing-work-order'):
    """Explicit allowlist: author metadata cannot silently reach the tested agent."""
    return dict(id=episode_id,title='Complete the manufacturing work order',
        prompt='Fulfill the customer orders using the manufacturing systems of record. Record the production, quality disposition, and shipments, and finish with their evidence IDs.',
        systems=list(task['systems']),max_tool_calls=task['max_tool_calls'],horizon_minutes=task['horizon_minutes'])


def error_code(message):
    text=message.lower()
    for words,code in [
        (('authorization','approval'),'authorization_mismatch'),
        (('schema','invalid arguments','invalid supplier'),'invalid_arguments'),
        (('read ','reconcile','superseded','stale'),'source_version_mismatch'),
        (('budget',),'budget_exceeded'),
        (('scheduling conflict','occupied'),'resource_conflict'),
        (('qualification','calibration'),'resource_qualification_invalid'),
        (('lot','material','reservation'),'material_not_eligible'),
        (('inspection','nonconform','measure','disposition'),'quality_state_invalid'),
        (('serial','unreleased'),'shipment_state_invalid'),
        (('operation','predecessor','route'),'operation_state_invalid'),
        (('horizon','time','past'),'time_constraint'),
    ]:
        if any(word in text for word in words):return code
    return 'action_not_permitted'


class AgentView:
    """Per-episode opaque identifiers and an allowlisted business-data projection.

    Host traces retain internal IDs for replay. Aliases, projections and decoded
    agent actions are separate from grading and never call a reference solver.
    """
    def __init__(self,nonce=None):
        self.nonce=nonce or secrets.token_hex(24)
        self.forward={};self.reverse={}
        self.episode_id='episode-'+hashlib.sha256(self.nonce.encode()).hexdigest()[:16]

    def _alias(self,match):
        original=match.group(0)
        if original not in self.forward:
            prefix=original.split('-')[0]
            if original.startswith('OSP-CERT-'):prefix='OSP-CERT'
            label=PREFIX[prefix]+'-'+hashlib.sha256((self.nonce+':'+original).encode()).hexdigest()[:16]
            self.forward[original]=label;self.reverse[label]=original
        return self.forward[original]

    def _text(self,value):
        return ID_PATTERN.sub(self._alias,value)

    def encode(self,value):
        if isinstance(value,str):return self._text(value)
        if isinstance(value,list):return [self.encode(v) for v in value]
        if isinstance(value,dict):
            out={}
            for k,v in value.items():
                if k in PRIVATE_KEYS:continue
                if k not in BUSINESS_FIELDS and not ID_PATTERN.fullmatch(k):continue
                if k=='notices':
                    # Scenario-author recovery hints are not business observations.
                    continue
                if k=='warning':continue
                out[self._text(k)]=self.encode(v)
            if 'control_kind' in value:out['control_fields']=list(CONTROL_FIELDS[value['control_kind']])
            return out
        return deepcopy(value)

    def decode(self,value):
        if isinstance(value,str):
            # Known public handles decode exactly; guessed private IDs are rejected.
            if value in self.reverse:return self.reverse[value]
            if ID_PATTERN.search(value):raise ValueError('unissued identifier')
            return value
        if isinstance(value,list):return [self.decode(v) for v in value]
        if isinstance(value,dict):return {self.decode(k):self.decode(v) for k,v in value.items()}
        return deepcopy(value)

    def result(self,result):
        if not result.get('ok'):
            return dict(ok=False,error=error_code(result['error']),clock_minute=result.get('clock_minute'))
        return self.encode(result)
