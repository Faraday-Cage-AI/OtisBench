"""Evaluator-only calculations over serialized raw samples, never agent outputs."""
import cmath
import csv
import io
import math


def number(row,key):
    try:
        value=float(row[key]);return value if math.isfinite(value) else None
    except (ValueError,TypeError,KeyError):return None


def good(row,fields):return row.get('quality','good')=='good' and all(number(row,k) is not None for k in fields)


def fit(x,y):
    n=len(x);mx=sum(x)/n;my=sum(y)/n;sxx=sum((a-mx)**2 for a in x)
    if n<3 or sxx<=0:raise ValueError('regression needs distinct samples')
    slope=sum((a-mx)*(b-my) for a,b in zip(x,y))/sxx;intercept=my-slope*mx
    variance=sum((b-intercept-slope*a)**2 for a,b in zip(x,y))/(n-2)
    return slope,intercept,variance,sxx,mx


def solve(policy,csv_text):
    f=policy['analysis_type'];p=policy['parameters'];rows=list(csv.DictReader(io.StringIO(csv_text)))
    def insufficient(n,fields):
        return dict(valid_samples=n,**{k:None for k in fields},decision='inspect')
    if f=='vibration_order':
        valid=[r for r in rows if good(r,['time_s','velocity_mm_s'])];n=len(valid)
        times=[number(r,'time_s') for r in valid]
        uniform=n>1 and all(math.isclose(times[i]-times[i-1],1/p['sample_hz'],abs_tol=1e-7,rel_tol=1e-7) for i in range(1,n))
        if n!=len(rows) or not uniform:return dict(valid_samples=n,rms_mm_s=None,dominant_hz=None,dominant_order=None,diagnosis='unknown',decision='inspect')
        x=[number(r,'velocity_mm_s') for r in valid];mean=sum(x)/n
        amplitudes=[abs(sum((value-mean)*cmath.exp(-2j*math.pi*k*i/n) for i,value in enumerate(x))) for k in range(1,n//2+1)]
        k=max(range(len(amplitudes)),key=lambda i:(amplitudes[i],-i))+1;frequency=k*p['sample_hz']/n;order=frequency/(p['shaft_rpm']/60);rms=math.sqrt(sum(v*v for v in x)/n)
        diagnosis='imbalance' if abs(order-1)<=p['order_tolerance'] else 'misalignment' if abs(order-2)<=p['order_tolerance'] else 'other'
        return dict(valid_samples=n,rms_mm_s=rms,dominant_hz=frequency,dominant_order=order,diagnosis=diagnosis,decision='stop' if rms>=p['stop_rms_mm_s'] else 'inspect' if diagnosis=='other' else 'continue')
    if f=='bearing_impulsiveness':
        valid=[number(r,'acceleration_g') for r in rows if good(r,['acceleration_g'])];n=len(valid)
        if n<p['minimum_samples'] or n/len(rows)<p['minimum_valid_fraction']:return insufficient(n,['rms_g','crest_factor','kurtosis'])
        rms=math.sqrt(sum(v*v for v in valid)/n);mean=sum(valid)/n;m2=sum((v-mean)**2 for v in valid)/n;m4=sum((v-mean)**4 for v in valid)/n
        crest=max(abs(v) for v in valid)/rms if rms else 0;kurt=m4/m2**2 if m2 else 0
        return dict(valid_samples=n,rms_g=rms,crest_factor=crest,kurtosis=kurt,decision='service' if kurt>=p['kurtosis_service'] and crest>=p['crest_warning'] else 'inspect' if crest>=p['crest_warning'] else 'continue')
    if f in ('thermal_soak_trace','cold_chain_trace'):
        valid=[number(r,'temperature_c') for r in rows if good(r,['temperature_c'])];maximum=max(valid) if valid else None
        known=unknown=longest=run=above=0
        for a,b in zip(rows,rows[1:]):
            dt=number(b,'time_min')-number(a,'time_min')
            if not good(a,['temperature_c']) or not good(b,['temperature_c']) or not 0<dt<=p['maximum_gap_minutes']:unknown+=max(0,dt);run=0;continue
            known+=dt;temp=number(a,'temperature_c')
            if f=='thermal_soak_trace':
                run=run+dt if p['minimum_c']<=temp<=p['maximum_c'] else 0;longest=max(longest,run)
            elif temp>p['limit_c']:above+=dt
        if f=='thermal_soak_trace':
            decision='quarantine' if maximum is not None and maximum>p['absolute_maximum_c'] else 'inspect' if unknown or not valid else 'quarantine' if longest<p['required_soak_minutes'] else 'continue'
            return dict(known_minutes=known,longest_soak_minutes=longest,maximum_c=maximum,decision=decision)
        decision='quarantine' if above>p['maximum_above_minutes'] else 'inspect' if unknown or not valid else 'continue'
        return dict(known_minutes=known,above_limit_minutes=above,maximum_c=maximum,decision=decision)
    if f=='pressure_decay':
        valid=[r for r in rows if good(r,['time_min','pressure_kpa','temperature_c']) and number(r,'temperature_c')>-273.15];n=len(valid)
        if n<p['minimum_samples'] or n/len(rows)<p['minimum_valid_fraction']:return insufficient(n,['leak_kpa_min','uncertainty_lower','uncertainty_upper'])
        x=[number(r,'time_min') for r in valid];y=[number(r,'pressure_kpa')*p['reference_kelvin']/(number(r,'temperature_c')+273.15) for r in valid]
        slope,_,var,sxx,_=fit(x,y);leak=-slope;spread=p['multiplier']*math.sqrt(var/sxx);lo=leak-spread;hi=leak+spread
        return dict(valid_samples=n,leak_kpa_min=leak,uncertainty_lower=lo,uncertainty_upper=hi,decision='stop' if lo>p['maximum_leak_kpa_min'] else 'continue' if hi<=p['maximum_leak_kpa_min'] else 'inspect')
    if f=='motor_phase_current':
        keys=['current_a','current_b','current_c'];valid=[r for r in rows if good(r,keys)];n=len(valid)
        if n/len(rows)<p['minimum_valid_fraction']:return insufficient(n,['rms_a','rms_b','rms_c','imbalance_percent'])
        rms=[math.sqrt(sum(number(r,k)**2 for r in valid)/n) for k in keys];avg=sum(rms)/3;imbalance=100*max(abs(v-avg) for v in rms)/avg if avg else 0
        return dict(valid_samples=n,rms_a=rms[0],rms_b=rms[1],rms_c=rms[2],imbalance_percent=imbalance,decision='stop' if imbalance>=p['stop_percent'] else 'inspect' if imbalance>=p['warning_percent'] else 'continue')
    if f=='tool_wear_prediction':
        valid=[r for r in rows if good(r,['time_hour','wear_mm'])];n=len(valid)
        if n<p['minimum_samples'] or n/len(rows)<p['minimum_valid_fraction']:return insufficient(n,['slope_mm_hour','predicted_wear_mm','prediction_lower_mm','prediction_upper_mm','remaining_hours'])
        x=[number(r,'time_hour') for r in valid];y=[number(r,'wear_mm') for r in valid];slope,intercept,var,sxx,mx=fit(x,y);last=max(x);future=last+p['forecast_hours'];prediction=intercept+slope*future
        spread=p['multiplier']*math.sqrt(var*(1+1/n+(future-mx)**2/sxx));lo=prediction-spread;hi=prediction+spread
        remaining=max(0,(p['wear_limit_mm']-intercept)/slope-last) if slope>0 else None
        return dict(valid_samples=n,slope_mm_hour=slope,predicted_wear_mm=prediction,prediction_lower_mm=lo,prediction_upper_mm=hi,remaining_hours=remaining,decision='service' if lo>=p['wear_limit_mm'] else 'continue' if hi<p['wear_limit_mm'] else 'inspect')
    if f=='spc_trace':
        z=[(number(r,'dimension_mm')-p['reference_mean'])/p['reference_sigma'] if good(r,['dimension_mm']) else None for r in rows];n=sum(v is not None for v in z)
        if n/len(rows)<p['minimum_valid_fraction']:return insufficient(n,['maximum_abs_z','longest_same_side_run','beyond_limit_count'])
        longest=run=side=0
        for value in z:
            new=0 if value is None or value==0 else 1 if value>0 else -1
            run=run+1 if new and new==side else 1 if new else 0;side=new;longest=max(longest,run)
        beyond=sum(v is not None and abs(v)>p['z_limit'] and not math.isclose(abs(v),p['z_limit'],rel_tol=0,abs_tol=1e-9) for v in z)
        return dict(valid_samples=n,maximum_abs_z=max(abs(v) for v in z if v is not None),longest_same_side_run=longest,beyond_limit_count=beyond,decision='stop' if beyond or longest>=p['run_length'] else 'continue')
    if f=='energy_meter_trace':
        energy=unknown=cost=0;good_units=sum(number(r,'good_units_interval') or 0 for r in rows[1:])
        for a,b in zip(rows,rows[1:]):
            start=number(a,'time_min');end=number(b,'time_min');dt=end-start
            if not good(a,['meter_kwh']) or not good(b,['meter_kwh']):unknown+=dt;continue
            delta=number(b,'meter_kwh') if b['reset_at_previous']=='1' else number(b,'meter_kwh')-number(a,'meter_kwh')
            if delta<0:unknown+=dt;continue
            energy+=delta
            cuts=sorted({start,end}|{t['start_minute'] for t in p['tariffs'] if start<t['start_minute']<end})
            for left,right in zip(cuts,cuts[1:]):
                rate=max((t for t in p['tariffs'] if t['start_minute']<=left),key=lambda t:t['start_minute'])['cents_kwh'];cost+=delta*(right-left)/dt*rate
        specific=energy/good_units if not unknown and good_units else None
        return dict(known_kwh=energy,unknown_minutes=unknown,cost_cents=math.ceil(cost) if not unknown else None,kwh_per_good_unit=specific,decision='inspect' if unknown or specific is None else 'service' if specific>p['maximum_kwh_per_good_unit'] else 'continue')
    if f=='redundant_sensor_bias':
        valid=[r for r in rows if good(r,['sensor_a','sensor_b','reference'])];n=len(valid)
        if n<p['minimum_samples'] or n/len(rows)<p['minimum_valid_fraction']:return dict(valid_samples=n,mean_bias_a=None,mean_bias_b=None,maximum_pair_delta=None,suspect_channel='unknown',decision='inspect')
        a=sum(number(r,'sensor_a')-number(r,'reference') for r in valid)/n;b=sum(number(r,'sensor_b')-number(r,'reference') for r in valid)/n;delta=max(abs(number(r,'sensor_a')-number(r,'sensor_b')) for r in valid);af=abs(a)>p['bias_limit'];bf=abs(b)>p['bias_limit']
        return dict(valid_samples=n,mean_bias_a=a,mean_bias_b=b,maximum_pair_delta=delta,suspect_channel='both' if af and bf else 'A' if af else 'B' if bf else 'none',decision='stop' if af and bf else 'service' if af or bf else 'continue')
    if f=='flow_mass_balance':
        net=known=unknown=0
        for a,b in zip(rows,rows[1:]):
            dt=number(b,'time_min')-number(a,'time_min')
            if not good(a,['inlet_l_min','outlet_l_min']) or not good(b,['inlet_l_min','outlet_l_min']) or not 0<dt<=p['maximum_gap_minutes']:unknown+=max(0,dt);continue
            known+=dt;net+=(number(a,'inlet_l_min')-number(a,'outlet_l_min'))*dt
        if unknown or not good(rows[0],['tank_liters']) or not good(rows[-1],['tank_liters']):return dict(known_minutes=known,unknown_minutes=unknown,leak_liters=None,uncertainty_lower_liters=None,uncertainty_upper_liters=None,decision='inspect')
        leak=net-(number(rows[-1],'tank_liters')-number(rows[0],'tank_liters'));spread=2*p['flow_absolute_error_l_min']*known;lo=leak-spread;hi=leak+spread
        return dict(known_minutes=known,unknown_minutes=0,leak_liters=leak,uncertainty_lower_liters=lo,uncertainty_upper_liters=hi,decision='stop' if lo>p['maximum_loss_liters'] else 'continue' if hi<=p['maximum_loss_liters'] else 'inspect')
    if f=='cohort_failure_risk':
        valid=[r for r in rows if r['complete']=='1' and r['failed'] in ('0','1')];n=len(valid);k=sum(r['failed']=='1' for r in valid)
        if n<p['minimum_complete_assets']:return dict(complete_assets=n,failures=k,risk_fraction=None,wilson_lower=None,wilson_upper=None,decision='inspect')
        fraction=k/n;z=p['z'];denom=1+z*z/n;center=(fraction+z*z/(2*n))/denom;half=z*math.sqrt(fraction*(1-fraction)/n+z*z/(4*n*n))/denom;lo=center-half;hi=center+half
        return dict(complete_assets=n,failures=k,risk_fraction=fraction,wilson_lower=lo,wilson_upper=hi,decision='service' if lo>p['risk_limit'] else 'continue' if hi<=p['risk_limit'] else 'inspect')
    raise ValueError('unknown sensor analysis type')
