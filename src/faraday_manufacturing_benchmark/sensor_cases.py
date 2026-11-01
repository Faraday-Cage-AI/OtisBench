"""Synthetic raw industrial observations; analysis targets are not precomputed."""
import csv
import hashlib
import io
import math
import random
from copy import deepcopy

CONDITIONS=('normal','fault','missing','boundary')
SPECS={
 'vibration_order':dict(domain='rotating_equipment',fields=['valid_samples','rms_mm_s','dominant_hz','dominant_order','diagnosis','decision'],
  parameters=dict(sample_hz=128,shaft_rpm=600,minimum_valid_fraction=.9,stop_rms_mm_s=4,order_tolerance=.1),
  rule='Use only good nonmissing samples. Spectral analysis requires all samples valid and uniform timestamps. Otherwise report valid_samples and null RMS/frequency/order, diagnosis unknown, decision inspect. For complete data, RMS is uncentered; find largest mean-centered rectangular-window DFT magnitude at bins 1..N/2 inclusive (lowest bin wins ties). Frequency=k*sample_hz/N. Order=frequency/(shaft_rpm/60). Diagnose order 1 as imbalance, order 2 as misalignment, otherwise other using order_tolerance. Stop if RMS>=stop threshold; otherwise inspect for other, continue for order 1 or 2.'),
 'bearing_impulsiveness':dict(domain='rotating_equipment',fields=['valid_samples','rms_g','crest_factor','kurtosis','decision'],
  parameters=dict(minimum_valid_fraction=.9,minimum_samples=32,crest_warning=3,kurtosis_service=6),
  rule='Use good nonmissing acceleration_g. Insufficient coverage/count: null all metrics and inspect. RMS is uncentered. Crest=max(abs(x))/RMS (zero if RMS=0). Kurtosis=mean((x-mean)^4)/mean((x-mean)^2)^2 (zero for constant data), not excess kurtosis. Service if kurtosis>=kurtosis_service and crest>=crest_warning; inspect if only crest>=warning; otherwise continue.'),
 'thermal_soak_trace':dict(domain='thermal_quality',fields=['known_minutes','longest_soak_minutes','maximum_c','decision'],
  parameters=dict(minimum_c=190,maximum_c=210,absolute_maximum_c=230,required_soak_minutes=45,maximum_gap_minutes=6),
  rule='Rows are temperature observations at time_min. Zero-order hold the left reading until the next timestamp. An interval is known only if both endpoints are good/nonmissing and duration<=maximum_gap_minutes. Unknown intervals break soak. Report known minutes, longest contiguous in-band soak and maximum valid observed temperature. Quarantine if any valid observation exceeds absolute maximum. Otherwise inspect if any interval unknown, quarantine if soak is too short, else continue.'),
 'pressure_decay':dict(domain='test_engineering',fields=['valid_samples','leak_kpa_min','uncertainty_lower','uncertainty_upper','decision'],
  parameters=dict(minimum_samples=8,minimum_valid_fraction=.8,reference_kelvin=293.15,multiplier=2,maximum_leak_kpa_min=.08),
  rule='Use complete good rows; normalize ABSOLUTE pressure_kpa by reference_kelvin/(temperature_c+273.15). Fit normalized pressure against time_min by OLS with intercept. Leak=-slope. Slope SE=sqrt(SSE/(n-2)/Sxx). Bounds=leak +/- multiplier*SE (do not clamp). These are declared approximate uncertainty bounds, not exact confidence coverage. If count/coverage insufficient report null metrics and inspect. Stop if lower>maximum leak; continue if upper<=maximum leak; otherwise inspect.'),
 'motor_phase_current':dict(domain='electrical_condition',fields=['valid_samples','rms_a','rms_b','rms_c','imbalance_percent','decision'],
  parameters=dict(minimum_valid_fraction=.9,warning_percent=3,stop_percent=10),
  rule='A valid row has good quality and all three phase currents. If valid coverage<minimum, null all metrics and inspect. Compute uncentered RMS for each phase. Imbalance=100*max(abs(phaseRMS-averageRMS))/averageRMS, or zero when all RMS zero. Stop at or above stop_percent; inspect at or above warning_percent; otherwise continue.'),
 'tool_wear_prediction':dict(domain='predictive_maintenance',fields=['valid_samples','slope_mm_hour','predicted_wear_mm','prediction_lower_mm','prediction_upper_mm','remaining_hours','decision'],
  parameters=dict(minimum_samples=8,minimum_valid_fraction=.8,forecast_hours=6,multiplier=2,wear_limit_mm=.35),
  rule='Fit wear_mm vs time_hour with OLS/intercept on good complete rows. Forecast at largest VALID observed time plus forecast_hours. Use predictive SE=sqrt(SSE/(n-2)*(1+1/n+(future-mean_time)^2/Sxx)); bounds=prediction +/- multiplier*SE. These are approximate linear-model prediction bounds, not a validated RUL distribution. Remaining hours=max(0,(wear_limit-intercept)/slope-last_valid_time) when slope>0, otherwise null. Insufficient count/coverage: all metrics null and inspect. Service if lower>=limit, continue if upper<limit, otherwise inspect.'),
 'spc_trace':dict(domain='process_quality',fields=['valid_samples','maximum_abs_z','longest_same_side_run','beyond_limit_count','decision'],
  parameters=dict(reference_mean=10,reference_sigma=.05,minimum_valid_fraction=.8,run_length=8,z_limit=3),
  rule='Use the stated fixed reference mean/sigma, not estimates from this sample. Bad/missing samples break runs; observations equal to reference mean also break runs. Count points with abs(z)>z_limit, not >=; values within 1e-9 of the limit compare equal. Report longest contiguous run strictly on one side. Insufficient coverage: metrics null and inspect. Stop on any beyond-limit point or run>=run_length; otherwise continue. This is a disclosed two-rule synthetic OCAP, not the full WECO/Nelson rule set.'),
 'energy_meter_trace':dict(domain='energy_operations',fields=['known_kwh','unknown_minutes','cost_cents','kwh_per_good_unit','decision'],
  parameters=dict(maximum_kwh_per_good_unit=.2,tariffs=[dict(start_minute=0,cents_kwh=20),dict(start_minute=15,cents_kwh=30)]),
  rule='For each interval use cumulative meter delta when endpoints are good/nonmissing. If reset_at_previous is 1, reset occurred exactly at the LEFT endpoint; the RIGHT reading is interval consumption. Negative unexplained delta makes interval unknown. Energy is uniform within each interval; split tariff exposure at tariff boundaries. known_kwh sums known intervals; unknown_minutes sums unknown durations. If any unknown, cost and specific energy null and inspect. Otherwise cost=ceil(total tariff-weighted cents), specific=energy/sum good_units_interval over RIGHT endpoints; if denominator zero specific null and inspect. Service if specific>maximum; else continue.'),
 'cold_chain_trace':dict(domain='storage_quality',fields=['known_minutes','above_limit_minutes','maximum_c','decision'],
  parameters=dict(limit_c=8,maximum_above_minutes=15,maximum_gap_minutes=6),
  rule='Zero-order hold left temperature until next timestamp. An interval is known only if both endpoints are good/nonmissing and duration<=maximum_gap_minutes. Sum known duration and known duration with left temperature>limit. Report maximum valid observed temperature. Quarantine when known above-limit duration>maximum; inspect when any interval unknown; otherwise continue. Inspect holds the lot pending investigation; it is not a release.'),
 'redundant_sensor_bias':dict(domain='instrumentation',fields=['valid_samples','mean_bias_a','mean_bias_b','maximum_pair_delta','suspect_channel','decision'],
  parameters=dict(minimum_valid_fraction=.8,minimum_samples=8,bias_limit=1),
  rule='Use good rows with A, B and independent calibrated reference. Compute mean(A-reference), mean(B-reference), and max abs(A-B). If count/coverage insufficient, null metrics, suspect unknown and inspect. A channel fails when abs(mean bias)>bias_limit. Both fail: suspect both and stop; one fails: suspect A or B and service; neither: suspect none and continue. Reference is assumed valid for this synthetic snapshot.'),
 'flow_mass_balance':dict(domain='process_integrity',fields=['known_minutes','unknown_minutes','leak_liters','uncertainty_lower_liters','uncertainty_upper_liters','decision'],
  parameters=dict(maximum_gap_minutes=6,flow_absolute_error_l_min=.1,maximum_loss_liters=20),
  rule='Zero-order hold left inlet/outlet flow on intervals whose endpoints are good/complete and gap<=maximum. Accumulate (in-out)*minutes. Subtract final-minus-initial tank_liters. If any unknown interval or missing endpoint tank value, leak/bounds null and inspect. Otherwise leak is the net balance, bounds=leak +/- 2*flow_absolute_error_l_min*known_minutes (do not clamp); tank error assumed zero. Stop if lower>maximum loss, continue if upper<=maximum, otherwise inspect.'),
 'cohort_failure_risk':dict(domain='predictive_maintenance',fields=['complete_assets','failures','risk_fraction','wilson_lower','wilson_upper','decision'],
  parameters=dict(minimum_complete_assets=30,z=1.96,risk_limit=.2),
  rule='Each row is a separate asset over the same follow-up horizon. Exclude censored/incomplete rows entirely; missing outcomes are not survivors. Complete rows have complete=1 and failed either 0 or 1. Report complete count and failure count. Below minimum, risk/bounds null and inspect. Else p=k/n; Wilson center=(p+z^2/(2n))/(1+z^2/n), half=z*sqrt(p*(1-p)/n+z^2/(4n^2))/(1+z^2/n). Service if lower>risk_limit, continue if upper<=risk_limit, otherwise inspect. Assumes representative independent complete follow-up; not a lifetime survival model.'),
}


def catalog():
    rows=[]
    for family,spec in SPECS.items():
        for condition in CONDITIONS:
            tid=f'sensor-{family}-{condition}'
            rows.append(dict(id=tid,family=family,domain=spec['domain'],condition=condition,provenance='synthetic-generated',seed=int.from_bytes(hashlib.sha256(tid.encode()).digest()[:8],'big'),max_tool_calls=80,horizon_minutes=120))
    return rows


def build(task):
    rng=random.Random(task['seed']);f=task['family'];c=task['condition'];fault=c=='fault';missing=c=='missing';boundary=c=='boundary';rows=[]
    if f=='vibration_order':
        for i in range(128):
            freq=30 if boundary else 20 if fault else 10;amp=8 if fault else 2
            rows.append(dict(time_s=i/128,velocity_mm_s=amp*math.sin(2*math.pi*freq*i/128)+.05*math.sin(2*math.pi*3*i/128),quality='good'))
        units=dict(time_s='s',velocity_mm_s='mm/s')
    elif f=='bearing_impulsiveness':
        for i in range(128):
            value=.5*math.sin(2*math.pi*10*i/128)
            if fault and i%32==0:value+=8
            if boundary and i==30:value+=1.4
            rows.append(dict(time_s=i/128,acceleration_g=value,quality='good'))
        units=dict(time_s='s',acceleration_g='g')
    elif f in ('thermal_soak_trace','cold_chain_trace'):
        for t in range(0,61,5):
            temp=200 if f=='thermal_soak_trace' else 4
            if fault:temp=240 if f=='thermal_soak_trace' and t==25 else 12 if f=='cold_chain_trace' and t>=25 else temp
            if boundary:temp=180 if f=='thermal_soak_trace' and t==30 else 10 if f=='cold_chain_trace' and 30<=t<40 else temp
            rows.append(dict(time_min=t,temperature_c=temp,quality='good'))
        units=dict(time_min='min',temperature_c='C')
    elif f=='pressure_decay':
        for i in range(16):
            temperature=20+i*.4;rate=.15 if fault else .075 if boundary else .005
            normalized=100-rate*i+(rng.uniform(-.2,.2) if boundary else rng.uniform(-.002,.002))
            rows.append(dict(time_min=i,pressure_kpa=normalized*(temperature+273.15)/293.15,temperature_c=temperature,quality='good'))
        units=dict(time_min='min',pressure_kpa='kPa absolute',temperature_c='C')
    elif f=='motor_phase_current':
        for i in range(128):
            angle=2*math.pi*10*i/128;b=8 if fault else 5.5 if boundary else 5
            rows.append(dict(time_s=i/128,current_a=5*math.sin(angle),current_b=b*math.sin(angle-2*math.pi/3),current_c=5*math.sin(angle+2*math.pi/3),quality='good'))
        units=dict(time_s='s',current_a='A',current_b='A',current_c='A')
    elif f=='tool_wear_prediction':
        for i in range(16):
            slope=.025 if fault else .012 if boundary else .01
            rows.append(dict(time_hour=i,wear_mm=.1+slope*i+rng.uniform(-.02 if boundary else -.001,.02 if boundary else .001),quality='good'))
        units=dict(time_hour='h',wear_mm='mm')
    elif f=='spc_trace':
        for i in range(24):
            value=10+rng.uniform(-.025,.025)
            if fault and i>=14:value=10.04
            if boundary:value=10+(.01 if i%2 else -.01)
            if boundary and i==12:value=10.145
            rows.append(dict(time_min=i,dimension_mm=value,quality='good'))
        units=dict(time_min='min',dimension_mm='mm')
    elif f=='energy_meter_trace':
        meter=100
        for i in range(7):
            delta=6 if fault else 2
            if i:meter+=delta
            reset=boundary and i==3
            if reset:meter=delta
            rows.append(dict(time_min=i*5,meter_kwh=meter,good_units_interval=0 if i==0 else 20,reset_at_previous=1 if reset else 0,quality='good'))
        units=dict(time_min='min',meter_kwh='kWh',good_units_interval='EA')
    elif f=='redundant_sensor_bias':
        for i in range(16):
            ref=50+math.sin(i/3);a=ref+(5 if fault or boundary else 0)+rng.uniform(-.05,.05);b=ref+(5 if boundary else 0)+rng.uniform(-.05,.05)
            rows.append(dict(time_min=i,sensor_a=a,sensor_b=b,reference=ref,quality='good'))
        units=dict(time_min='min',sensor_a='kPa',sensor_b='kPa',reference='kPa')
    elif f=='flow_mass_balance':
        for i in range(13):
            diff=3 if fault else .3 if boundary else .05
            rows.append(dict(time_min=i*5,inlet_l_min=10,outlet_l_min=10-diff,tank_liters=100,quality='good'))
        units=dict(time_min='min',inlet_l_min='L/min',outlet_l_min='L/min',tank_liters='L')
    elif f=='cohort_failure_risk':
        failures=45 if fault else 15 if boundary else 5
        for i in range(100):rows.append(dict(asset_id=f'UNIT-{i+1:03}',complete=0 if missing and i>=20 else 1,failed='' if missing and i>=20 else 1 if i<failures else 0,followup_hours=250 if missing and i>=20 else 1000))
        units=dict(followup_hours='h',complete='boolean 0/1',failed='boolean 0/1')
    if missing and f!='cohort_failure_risk':
        if f in ('thermal_soak_trace','cold_chain_trace','energy_meter_trace','flow_mass_balance'):
            for key in rows[len(rows)//2]:
                if key not in ('time_min','quality','good_units_interval','reset_at_previous'):rows[len(rows)//2][key]=''
        else:
            for row in rows[4:]:row['quality']='bad'
    # The evaluator derives answers from these serialized observations, not the
    # unrounded generator values. Export and streamed readings share these bytes.
    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader()
    for row in rows:writer.writerow({k:format(v,'.8f') if isinstance(v,float) else v for k,v in row.items()})
    spec=SPECS[f]
    return dict(asset=dict(id='ASSET-1',status='operating',quality_status='pending_assessment',work_orders={},assessment=None),
        policy=dict(analysis_type=f,parameters=deepcopy(spec['parameters']),rule=spec['rule'],assessment_fields=list(spec['fields']),
            evidence_policy='Read the entire frozen stream. Do not impute missing or bad samples unless the analysis rule explicitly permits it. An inspect decision holds the asset or lot for investigation. Propose your own complete assessment, obtain exact approval, execute it, read the result back and finish.'),
        stream=dict(id='STREAM-1',name='Recorded measurements',mime_type='text/csv',units=units,row_count=len(rows),csv=stream.getvalue()))
