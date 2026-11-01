"""Manufacturing reference calculations. All dimensions are explicit in field names."""
from __future__ import annotations

import itertools
import math
import statistics
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

SOLVERS = {}


def calculation(name):
    def register(fn):
        SOLVERS[name] = fn
        return fn
    return register


def money(value):
    return int(Decimal(str(value)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


@calculation('quote_cost')
def quote(x):
    blanks = math.ceil(x['good_units'] / x['yield_fraction'])
    total = blanks * x['blank_cents'] + x['setup_cents'] + x['good_units'] * x['conversion_cents']
    price = math.ceil(Decimal(total) / (Decimal('1') - Decimal(str(x['margin_fraction']))))
    return dict(blanks=blanks, cost_cents=total, minimum_price_cents=price)


@calculation('milling')
def milling(x):
    rpm = 1000 * x['surface_m_min'] / (math.pi * x['diameter_mm'])
    rpm = min(rpm, x['max_rpm'])
    feed = rpm * x['teeth'] * x['chip_mm_tooth']
    return dict(rpm=rpm, feed_mm_min=feed, cut_minutes=x['travel_mm'] / feed)


@calculation('tolerance_stack')
def tolerance(x):
    nominal = sum(a['sign'] * a['nominal_mm'] for a in x['dimensions'])
    worst = sum(a['tolerance_mm'] for a in x['dimensions'])
    rss = math.sqrt(sum(a['tolerance_mm'] ** 2 for a in x['dimensions']))
    return dict(nominal_mm=nominal, worst_min_mm=nominal-worst, worst_max_mm=nominal+worst, rss_mm=rss,
                guaranteed=x['allowed_min_mm'] <= nominal-worst and nominal+worst <= x['allowed_max_mm'])


@calculation('shaft_fit')
def fit(x):
    low=x['hole_min_mm']-x['shaft_max_mm']; high=x['hole_max_mm']-x['shaft_min_mm']
    return dict(min_clearance_mm=low, max_clearance_mm=high,
                fit='clearance' if low>0 else 'interference' if high<0 else 'transition')


@calculation('mrp')
def mrp(x):
    available=x['opening_units']; receipts=[]; releases=[]; projected=[]
    for day,demand in enumerate(x['demand_units']):
        available+=x['scheduled_receipts_units'][day]-demand
        needed=max(0,x['safety_units']-available)
        receipt=math.ceil(needed/x['lot_multiple_units'])*x['lot_multiple_units']
        available+=receipt; projected.append(available)
        if receipt:
            receipts.append({'day':day,'units':receipt})
            releases.append({'day':day-x['lead_days'],'units':receipt})
    return dict(projected_units=projected, planned_receipts=receipts, planned_releases=releases)


@calculation('bottleneck')
def bottleneck(x):
    capacities={s['id']:math.floor(s['parallel']*s['available_minutes']/s['cycle_minutes'])*s['yield_fraction'] for s in x['stations']}
    return dict(good_capacity_units=math.floor(min(capacities.values())), bottleneck=min(capacities,key=capacities.get),
                meets_demand=min(capacities.values())>=x['demand_units'])


@calculation('spc_capability')
def capability(x):
    mean=statistics.mean(x['measurements_mm']); sigma=statistics.stdev(x['measurements_mm'])
    cp=(x['usl_mm']-x['lsl_mm'])/(6*sigma)
    cpk=min(x['usl_mm']-mean,mean-x['lsl_mm'])/(3*sigma)
    return dict(mean_mm=mean, sample_sigma_mm=sigma, cp=cp, cpk=cpk, capable=cpk>=x['minimum_cpk'])


@calculation('oee')
def oee(x):
    runtime=x['planned_minutes']-x['downtime_minutes']
    a=runtime/x['planned_minutes']; p=x['ideal_cycle_minutes']*x['total_units']/runtime; q=x['good_units']/x['total_units']
    return dict(availability=a,performance=p,quality=q,oee=a*p*q)


@calculation('gauge_rr')
def gauge(x):
    grr=math.hypot(x['repeat_sigma_mm'],x['reproduce_sigma_mm'])
    total=math.hypot(grr,x['part_sigma_mm'])
    return dict(grr_sigma_mm=grr, percent_study_variation=100*grr/total,
                ndc=math.floor(1.41*x['part_sigma_mm']/grr),acceptable=100*grr/total<=x['max_percent'])


@calculation('acceptance_sampling')
def sampling(x):
    n=x['lot_units']; d=x['lot_defects']; sample=x['sample_units']; c=x['accept_number']
    probability=sum(math.comb(d,k)*math.comb(n-d,sample-k) for k in range(max(0,sample-(n-d)),min(c,d,sample)+1))/math.comb(n,sample)
    return dict(accept=x['observed_defects']<=c, probability_accept=probability)


@calculation('fefo_issue')
def fefo(x):
    remaining=x['required_units']; allocations=[]
    for lot in sorted(x['lots'],key=lambda l:(l['expiry_day'],l['id'])):
        if lot['released'] and lot['expiry_day']>=x['use_day']:
            take=min(remaining,lot['units'])
            if take: allocations.append({'lot':lot['id'],'units':take}); remaining-=take
    return dict(allocations=allocations, shortage_units=remaining)


@calculation('vibration_diagnosis')
def vibration(x):
    samples=x['velocity_mm_s']; rms=math.sqrt(sum(v*v for v in samples)/len(samples))
    peak=max(x['spectrum'],key=lambda p:p['amplitude'])
    order=peak['frequency_hz']/(x['rpm']/60)
    diagnosis='imbalance' if abs(order-1)<=.05 else 'misalignment' if abs(order-2)<=.05 else 'other'
    return dict(rms_mm_s=rms,dominant_order=order,diagnosis=diagnosis,stop=rms>=x['stop_rms_mm_s'])


@calculation('batch_balance')
def batch(x):
    active=sum(a['kg']*a['assay_fraction'] for a in x['ingredients']); mass=sum(a['kg'] for a in x['ingredients'])
    out=mass-x['evaporation_kg']
    return dict(output_kg=out,active_kg=active,active_fraction=active/out,good_kg=out*x['pack_yield_fraction'])


@calculation('blend_optimization')
def blend(x):
    best=None
    for amounts in itertools.product(*(range(0,a['available_kg']+1,x['increment_kg']) for a in x['materials'])):
        if sum(amounts)!=x['batch_kg']: continue
        assay=sum(q*a['assay_fraction'] for q,a in zip(amounts,x['materials']))/x['batch_kg']
        if not x['min_assay']<=assay<=x['max_assay']: continue
        cost=sum(q*a['cents_kg'] for q,a in zip(amounts,x['materials']))
        candidate=(cost,amounts)
        if best is None or candidate<best: best=candidate
    if best is None: return dict(feasible=False,cost_cents=None,allocation_kg=[])
    return dict(feasible=True,cost_cents=best[0],allocation_kg=list(best[1]))


@calculation('heat_treatment')
def heat(x):
    dwell=sum(s['minutes'] for s in x['segments'] if x['min_c']<=s['temperature_c']<=x['max_c'])
    over=any(s['temperature_c']>x['absolute_max_c'] for s in x['segments'])
    # Contract requires one uninterrupted in-band soak, not accumulated fragments.
    longest=0; current=0
    for s in x['segments']:
        current=current+s['minutes'] if x['min_c']<=s['temperature_c']<=x['max_c'] else 0
        longest=max(longest,current)
    return dict(in_band_minutes=dwell,continuous_soak_minutes=longest,release=longest>=x['required_minutes'] and not over)


@calculation('weld_heat_input')
def weld(x):
    heat=x['volts']*x['amps']*60*x['efficiency']/(1000*x['travel_mm_min'])
    return dict(heat_kj_mm=heat,within_window=x['minimum_kj_mm']<=heat<=x['maximum_kj_mm'])


@calculation('sheet_layout')
def sheet(x):
    def count(w,h):
        return max(0,math.floor((x['sheet_width_mm']-2*x['edge_mm']+x['kerf_mm'])/(w+x['kerf_mm'])))*max(0,math.floor((x['sheet_height_mm']-2*x['edge_mm']+x['kerf_mm'])/(h+x['kerf_mm'])))
    a=count(x['part_width_mm'],x['part_height_mm']); b=count(x['part_height_mm'],x['part_width_mm']) if x['rotation_allowed'] else -1
    n=max(a,b)
    return dict(parts_per_sheet=n,rotate=b>a,sheets_required=math.ceil(x['quantity']/n) if n else None)


@calculation('press_brake')
def bend(x):
    ba=math.radians(x['angle_deg'])*(x['inside_radius_mm']+x['k_factor']*x['thickness_mm'])
    setback=(x['inside_radius_mm']+x['thickness_mm'])*math.tan(math.radians(x['angle_deg']/2))
    deduction=2*setback-ba
    return dict(bend_allowance_mm=ba,bend_deduction_mm=deduction,flat_mm=sum(x['outside_flange_mm'])-deduction)


@calculation('injection_molding')
def molding(x):
    force=x['projected_area_cm2']*100*x['cavity_mpa']*x['cavities']/1000*x['safety_factor']
    return dict(tool_dimension_mm=x['finished_dimension_mm']/(1-x['shrink_fraction']),clamp_kn=force,
                parts_hour=3600*x['cavities']*x['yield_fraction']/x['cycle_seconds'],machine_suitable=force<=x['machine_clamp_kn'])


@calculation('casting_charge')
def casting(x):
    net=x['part_volume_cm3']*x['density_g_cm3']/1000*x['quantity']
    pour=net/x['casting_yield_fraction']; charge=pour/(1-x['melt_loss_fraction'])
    return dict(net_kg=net,pour_kg=pour,charge_kg=charge)


@calculation('additive_build')
def additive(x):
    volume=(x['part_volume_mm3']+x['support_volume_mm3'])*x['quantity']
    layers=math.ceil(x['height_mm']/x['layer_mm'])
    return dict(layers=layers,feedstock_g=volume*x['density_g_cm3']/1000,
                build_minutes=volume/x['deposition_mm3_min']+layers*x['recoat_seconds']/60)


@calculation('smt_line')
def smt(x):
    placement=x['placements_board']/x['placements_hour']*3600
    bottleneck=max(placement,x['printer_seconds'],x['oven_pitch_seconds'],x['aoi_seconds'])
    return dict(cycle_seconds=bottleneck,good_boards_hour=3600/bottleneck*x['yield_fraction'],
                feeder_shortage=max(0,x['distinct_parts']-x['feeder_slots']))


@calculation('wafer_yield')
def wafer(x):
    area=x['die_area_mm2']; diameter=x['wafer_diameter_mm']
    gross=math.floor(math.pi*(diameter/2)**2/area-math.pi*diameter/math.sqrt(2*area))
    yield_fraction=math.exp(-x['defects_cm2']*area/100)
    return dict(gross_dies=gross,yield_fraction=yield_fraction,expected_good_dies=gross*yield_fraction)


@calculation('tool_life')
def tool_life(x):
    life=(x['taylor_c']/x['speed_m_min'])**(1/x['taylor_n'])
    parts=math.floor(life/x['cut_minutes_part'])
    return dict(tool_life_minutes=life,parts_per_edge=parts,edges_required=math.ceil(x['quantity']/parts) if parts else None)


@calculation('pump_performance')
def pump(x):
    hydraulic=x['density_kg_m3']*9.80665*(x['flow_m3_hour']/3600)*x['head_m']/1000
    return dict(hydraulic_kw=hydraulic,wire_to_water_efficiency=hydraulic/x['input_kw'],
                cavitation_margin_m=x['npsh_available_m']-x['npsh_required_m'],
                acceptable=x['npsh_available_m']-x['npsh_required_m']>=x['required_margin_m'])


@calculation('weibull_maintenance')
def reliability(x):
    survival=math.exp(-((x['age_hours']+x['next_hours'])/x['eta_hours'])**x['beta']+(x['age_hours']/x['eta_hours'])**x['beta'])
    return dict(conditional_failure_probability=1-survival,service_now=1-survival>x['maximum_failure_probability'])


@calculation('lot_genealogy')
def genealogy(x):
    affected=set(x['suspect_lots']); changed=True
    while changed:
        changed=False
        for edge in x['consumption']:
            if edge['input'] in affected and edge['output'] not in affected:
                affected.add(edge['output']); changed=True
    shipments=sorted(s['id'] for s in x['shipments'] if set(s['lots'])&affected)
    return dict(affected_lots=sorted(affected),affected_shipments=shipments)


@calculation('fmea_priority')
def fmea(x):
    rpn={r['id']:r['severity']*r['occurrence']*r['detection'] for r in x['risks']}
    # Explicit customer rule: severity 9+ always requires action, independently of RPN.
    action=sorted(r['id'] for r in x['risks'] if r['severity']>=9 or rpn[r['id']]>=x['action_rpn'])
    return dict(rpn=rpn,action_ids=action)


@calculation('kanban')
def kanban(x):
    cards=math.ceil(x['demand_units_day']*x['replenishment_days']*(1+x['safety_fraction'])/x['container_units'])
    return dict(cards=cards,authorized_units=cards*x['container_units'])


@calculation('takt_staffing')
def takt(x):
    takt=x['net_minutes_shift']*60/x['demand_units']
    return dict(takt_seconds=takt,theoretical_operators=math.ceil(sum(x['task_seconds'])/takt),
                indivisible_task_exceeds_takt=max(x['task_seconds'])>takt)


@calculation('gdt_position')
def position(x):
    actual=2*math.hypot(x['actual_x_mm']-x['basic_x_mm'],x['actual_y_mm']-x['basic_y_mm'])
    bonus=max(0,x['actual_hole_mm']-x['mmc_hole_mm']) if x['mmc_applies'] else 0
    return dict(position_error_mm=actual,allowed_mm=x['position_tolerance_mm']+bonus,accept=actual<=x['position_tolerance_mm']+bonus)


@calculation('thermal_compensation')
def thermal(x):
    reference=x['measured_mm']/(1+x['cte_per_c']*(x['temperature_c']-x['reference_c']))
    return dict(reference_length_mm=reference,accept=x['lsl_mm']<=reference<=x['usl_mm'])


@calculation('bolt_preload')
def bolt(x):
    preload=x['torque_nm']/(x['nut_factor']*x['diameter_mm']/1000)
    proof=x['stress_area_mm2']*x['proof_mpa']
    return dict(preload_n=preload,proof_load_n=proof,proof_fraction=preload/proof,
                accept=x['minimum_fraction']<=preload/proof<=x['maximum_fraction'])


@calculation('energy_dispatch')
def energy(x):
    best=None
    for start in range(len(x['base_kw'])-x['duration_slots']+1):
        if start<x['earliest_slot'] or start+x['duration_slots']>x['latest_finish_slot']: continue
        loads=[v+(x['job_kw'] if start<=i<start+x['duration_slots'] else 0) for i,v in enumerate(x['base_kw'])]
        if max(loads)>x['limit_kw']: continue
        energy=sum(v*r*x['slot_hours'] for v,r in zip(loads,x['cents_kwh']))
        cost=money(energy+max(loads)*x['demand_cents_kw'])
        candidate=(cost,start,max(loads))
        if best is None or candidate<best: best=candidate
    return dict(feasible=best is not None,start_slot=best[1] if best else None,total_cents=best[0] if best else None,peak_kw=best[2] if best else None)


@calculation('production_schedule')
def schedule(x):
    best=None
    for sequence in itertools.permutations(x['jobs']):
        clock=0; last=x['initial_family']; late=0; rows=[]
        for j in sequence:
            setup=x['changeover_minutes'].get(last+'>'+j['family'],0)
            start=max(clock,j['release_minute']); end=start+setup+j['run_minutes']
            late+=max(0,end-j['due_minute'])*j['late_cents_minute']
            rows.append({'job':j['id'],'start_minute':start,'finish_minute':end})
            clock=end; last=j['family']
        candidate=(late,clock,tuple(j['id'] for j in sequence),rows)
        if best is None or candidate[:3]<best[:3]: best=candidate
    return dict(tardiness_cents=best[0],makespan_minutes=best[1],schedule=best[3])


@calculation('cutting_stock')
def cutting(x):
    pieces=sorted(x['pieces_mm'],reverse=True); best=None
    def visit(i,bars):
        nonlocal best
        if best is not None and len(bars)>len(best): return
        if i==len(pieces):
            canonical=sorted((sorted(b,reverse=True) for b in bars),reverse=True)
            if best is None or (len(canonical),canonical)<(len(best),best): best=canonical
            return
        p=pieces[i]; seen=set()
        for b in bars:
            used=sum(b)+max(0,len(b)-1)*x['kerf_mm']
            if used in seen: continue
            seen.add(used)
            if used+x['kerf_mm']+p<=x['bar_mm']:
                b.append(p); visit(i+1,bars); b.pop()
        if p<=x['bar_mm']: visit(i+1,bars+[[p]])
    visit(0,[])
    return dict(feasible=best is not None,bars=len(best) if best is not None else None,
                waste_mm=len(best)*x['bar_mm']-sum(pieces)-sum(max(0,len(b)-1)*x['kerf_mm'] for b in best) if best is not None else None)


@calculation('pressure_test')
def pressure(x):
    # Ideal-gas correction with absolute pressure and Kelvin temperature.
    corrected=(x['end_gauge_bar']+x['atmosphere_bar'])*(x['start_c']+273.15)/(x['end_c']+273.15)-x['atmosphere_bar']
    loss=x['start_gauge_bar']-corrected
    return dict(corrected_end_bar=corrected,loss_bar=loss,accept=loss<=x['maximum_loss_bar'])


@calculation('motor_drive')
def motor(x):
    shaft=x['torque_nm']*x['rpm']*2*math.pi/60/1000
    input_kw=shaft/x['motor_efficiency']/x['drive_efficiency']
    amps=input_kw*1000/(math.sqrt(3)*x['line_volts']*x['power_factor'])
    return dict(shaft_kw=shaft,input_kw=input_kw,current_amps=amps,overloaded=amps>x['rated_amps'])


@calculation('wastewater_balance')
def wastewater(x):
    kg_day=x['flow_m3_day']*x['inlet_mg_l']/1000
    outlet=x['inlet_mg_l']*(1-x['removal_fraction'])
    return dict(inlet_kg_day=kg_day,removed_kg_day=kg_day*x['removal_fraction'],outlet_mg_l=outlet,within_limit=outlet<=x['limit_mg_l'])


@calculation('packout')
def packout(x):
    by_weight=math.floor((x['max_gross_kg']-x['tare_kg'])/x['unit_kg'])
    per_carton=min(by_weight,x['volume_limit_units'])
    return dict(units_carton=per_carton,cartons=math.ceil(x['quantity']/per_carton) if per_carton>0 else None,
                last_carton_units=(x['quantity']-1)%per_carton+1 if per_carton>0 else None)


@calculation('multilevel_bom')
def bom_explosion(x):
    nodes=x['items'];reachable=set();active=set();order=[]
    def walk(item):
        if item in active:raise ValueError('cyclic BOM')
        if item in reachable:return
        active.add(item)
        for component in nodes[item]['components']:walk(component)
        active.remove(item);reachable.add(item);order.append(item)
    for item in x['demand_units']:walk(item)
    gross={k:0 for k in reachable};due={k:x['due_day'] for k in reachable};starts={};release={}
    for k,v in x['demand_units'].items():gross[k]+=v
    for item in reversed(order):
        p=nodes[item];net=max(0,gross[item]-p['on_hand_units'])
        required=math.ceil(Decimal(net)/Decimal(str(p['yield_fraction'])))
        starts[item]=math.ceil(required/p['lot_multiple_units'])*p['lot_multiple_units']
        release[item]=due[item]-p['lead_days']
        for component,quantity in p['components'].items():
            gross[component]+=starts[item]*quantity
            due[component]=min(due[component],release[item])
    return dict(gross_requirements_units=dict(sorted(gross.items())),planned_starts_units=dict(sorted(starts.items())),release_day=dict(sorted(release.items())))


@calculation('assembly_line_balance')
def line_balance(x):
    tasks=x['tasks'];n=len(tasks);index={t['id']:i for i,t in enumerate(tasks)}
    if n>12:raise ValueError('exact line-balance contract supports at most 12 tasks')
    if len(index)!=n:raise ValueError('duplicate task IDs')
    pred=[sum(1<<index[k] for k in t['predecessors']) for t in tasks]
    full=(1<<n)-1;best={0:0}
    for mask in range(full+1):
        if mask not in best:continue
        remaining=full^mask;subset=remaining
        while subset:
            chosen=[i for i in range(n) if subset&(1<<i)]
            work=sum(tasks[i]['seconds'] for i in chosen)
            if work<=x['takt_seconds'] and all(pred[i]&~(mask|subset)==0 for i in chosen):
                # Feasible same-station tasks must themselves admit a topological order.
                done=mask
                for _ in chosen:
                    ready=next((i for i in chosen if not done&(1<<i) and pred[i]&~done==0),None)
                    if ready is None:break
                    done|=1<<ready
                if done==mask|subset:
                    new=mask|subset;best[new]=min(best.get(new,n+1),best[mask]+1)
            subset=(subset-1)&remaining
    count=best.get(full)
    return dict(feasible=count is not None,stations=count,balance_efficiency=sum(t['seconds'] for t in tasks)/(count*x['takt_seconds']) if count else None)
