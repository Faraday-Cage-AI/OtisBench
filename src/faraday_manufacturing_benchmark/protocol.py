"""JSON Schemas expose answer structure, never computed answers."""
BOOLS=set('guaranteed meets_demand capable acceptable accept stop feasible release within_window rotate machine_suitable service_now indivisible_task_exceeds_takt overloaded within_limit'.split())
INTS=set('blanks cost_cents minimum_price_cents good_capacity_units ndc shortage_units parts_per_sheet sheets_required layers feeder_shortage gross_dies parts_per_edge edges_required cards authorized_units theoretical_operators start_slot total_cents bars units_carton cartons last_carton_units stations'.split())
NULLABLE=set('cost_cents sheets_required edges_required start_slot total_cents peak_kw bars waste_mm cartons last_carton_units stations balance_efficiency'.split())


def object_schema(properties):
    return dict(type='object',properties=properties,required=list(properties),additionalProperties=False)


def answer_schema(task):
    props={}
    for key in task['output_fields']:
        if key in BOOLS:s={'type':'boolean'}
        elif key in ('fit','bottleneck','diagnosis'):s={'type':'string'}
        elif key in ('projected_units','allocation_kg'):s={'type':'array','items':{'type':'integer'}}
        elif key in ('affected_lots','affected_shipments','action_ids'):s={'type':'array','items':{'type':'string'}}
        elif key in ('planned_receipts','planned_releases'):s={'type':'array','items':object_schema({'day':{'type':'integer'},'units':{'type':'integer'}})}
        elif key=='allocations':s={'type':'array','items':object_schema({'lot':{'type':'string'},'units':{'type':'integer'}})}
        elif key=='schedule':s={'type':'array','items':object_schema({'job':{'type':'string'},'start_minute':{'type':'integer'},'finish_minute':{'type':'integer'}})}
        elif key in ('gross_requirements_units','planned_starts_units','release_day'):s=object_schema({k:{'type':'integer'} for k in task['inputs']['items']})
        elif key=='rpn':s=object_schema({r['id']:{'type':'integer'} for r in task['inputs']['risks']})
        else:s={'type':'integer' if key in INTS else 'number'}
        if key in NULLABLE:s['type']=[s['type'],'null']
        props[key]=s
    return object_schema(props)
