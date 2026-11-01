"""Authored manufacturing cases; each pair exercises a different operating condition."""
from copy import deepcopy

TASKS=[]


def cases(family, domain, prompt, fields, base, change, titles):
    for i, (inputs,title) in enumerate(((base,titles[0]),({**deepcopy(base),**change},titles[1])),1):
        TASKS.append(dict(id=f'mfg-{family}-{i:03}',family=family,domain=domain,title=title,
                          prompt=prompt+' Return only the requested JSON fields. Do not round intermediate values.',
                          output_fields=fields.split(),inputs=inputs,absolute_tolerance=1e-6,relative_tolerance=1e-5))


cases('quote_cost','quoting','Quote a make-to-order job. Round required blanks up. Conversion applies to good units. Price must achieve gross margin on revenue; round total selling price up to whole cents.',
      'blanks cost_cents minimum_price_cents',dict(good_units=120,yield_fraction=.96,blank_cents=1380,setup_cents=45000,conversion_cents=720,margin_fraction=.3),
      dict(good_units=31,yield_fraction=.87,margin_fraction=.42),('Price a repeat machined bracket','Price a low-yield first article'))
cases('milling','machining','Calculate spindle speed from surface speed, cap at machine maximum, then feed from chip load. Ignore acceleration and tool changes.',
      'rpm feed_mm_min cut_minutes',dict(surface_m_min=180,diameter_mm=12,max_rpm=9000,teeth=4,chip_mm_tooth=.05,travel_mm=2480),
      dict(diameter_mm=3,max_rpm=12000,chip_mm_tooth=.015),('Program an aluminum pocket','Handle a spindle-limited small cutter'))
cases('tolerance_stack','metrology','Use signed nominal dimensions, sum absolute bilateral tolerances for worst case and root sum squares for RSS. Guarantee requires the entire worst-case interval inside the allowed interval.',
      'nominal_mm worst_min_mm worst_max_mm rss_mm guaranteed',dict(dimensions=[dict(sign=1,nominal_mm=30,tolerance_mm=.1),dict(sign=-1,nominal_mm=12,tolerance_mm=.05),dict(sign=-1,nominal_mm=17.5,tolerance_mm=.08)],allowed_min_mm=.2,allowed_max_mm=.8),
      dict(allowed_min_mm=.3,allowed_max_mm=.7),('Accept a spacer stack','Detect a worst-case interference risk'))
cases('shaft_fit','metrology','Find minimum and maximum diametral clearance. Classify positive-only clearance, negative-only interference, or transition when the range touches or crosses zero.',
      'min_clearance_mm max_clearance_mm fit',dict(hole_min_mm=25,hole_max_mm=25.021,shaft_min_mm=24.980,shaft_max_mm=24.993),
      dict(shaft_min_mm=25.010,shaft_max_mm=25.025),('Select a running fit','Evaluate a transition fit'))
cases('mrp','material_planning','At the start of each zero-based day receive scheduled stock, then subtract demand. Add the smallest lot-multiple planned receipt restoring safety stock. Offset planned release day by lead time, retaining negative days as expedite signals.',
      'projected_units planned_receipts planned_releases',dict(opening_units=25,demand_units=[10,30,10,45,0],scheduled_receipts_units=[0,20,0,0,40],safety_units=10,lot_multiple_units=20,lead_days=2),
      dict(opening_units=5,scheduled_receipts_units=[0,0,40,0,0],lead_days=3),('Explode daily shortage timing','Expose releases already past due'))
cases('bottleneck','capacity','For each station floor parallel-machine available time divided by cycle, then multiply by station yield. Treat each station capacity as good output at that station; identify minimum, floor final line capacity. Demand comparison uses unrounded capacity.',
      'good_capacity_units bottleneck meets_demand',dict(stations=[dict(id='mill',parallel=2,available_minutes=420,cycle_minutes=4,yield_fraction=.98),dict(id='wash',parallel=1,available_minutes=400,cycle_minutes=2,yield_fraction=.95)],demand_units=180),
      dict(demand_units=195),('Identify the wash constraint','Evaluate an overloaded shift'))
cases('spc_capability','quality','Calculate sample standard deviation with n-1 denominator, Cp and Cpk. Capability requires Cpk at least the stated minimum.',
      'mean_mm sample_sigma_mm cp cpk capable',dict(measurements_mm=[10.01,10.02,9.99,10.00,10.01,9.98,10.02,10.00],lsl_mm=9.9,usl_mm=10.1,minimum_cpk=1.33),
      dict(measurements_mm=[10.06,10.07,10.08,10.05,10.09,10.07,10.06,10.08]),('Assess a centered process','Detect loss of capability from mean shift'))
cases('oee','production','Availability is runtime/planned time, performance is ideal cycle times total count/runtime, quality is good/total. OEE is their product.',
      'availability performance quality oee',dict(planned_minutes=450,downtime_minutes=65,ideal_cycle_minutes=.5,total_units=690,good_units=671),
      dict(downtime_minutes=140,total_units=510,good_units=450),('Reconcile a daily OEE report','Separate breakdown and scrap losses'))
cases('gauge_rr','metrology','Combine repeatability and reproducibility sigmas by RSS, combine GRR and part sigma by RSS. Percent study variation is 100*GRR/total; ndc=floor(1.41*part/GRR). Acceptance uses max_percent.',
      'grr_sigma_mm percent_study_variation ndc acceptable',dict(repeat_sigma_mm=.004,reproduce_sigma_mm=.003,part_sigma_mm=.08,max_percent=10),
      dict(reproduce_sigma_mm=.025),('Qualify an inspection gauge','Reject excessive operator variation'))
cases('acceptance_sampling','quality','Accept the observed sample when defect count is at most acceptance number. Compute probability of acceptance under sampling without replacement using the given lot defect count (hypergeometric).',
      'accept probability_accept',dict(lot_units=200,lot_defects=8,sample_units=20,accept_number=1,observed_defects=1),
      dict(lot_defects=25,observed_defects=2),('Accept an incoming casting sample','Reject an incoming sample above Ac'))
cases('fefo_issue','inventory','Issue released, unexpired stock by earliest expiry then lot ID, using inclusive expiry on use day. Return ordered allocations as objects with lot and units; report unfilled demand.',
      'allocations shortage_units',dict(required_units=75,use_day=20,lots=[dict(id='L1',units=40,expiry_day=19,released=True),dict(id='L2',units=50,expiry_day=21,released=False),dict(id='L3',units=60,expiry_day=25,released=True),dict(id='L4',units=30,expiry_day=30,released=True)]),
      dict(required_units=110),('Issue adhesive without consuming held stock','Expose shortage behind available gross stock'))
cases('vibration_diagnosis','maintenance','Compute uncentered RMS velocity. Find the largest spectral amplitude and divide its frequency by shaft Hz. Classify within 0.05 of order 1 as imbalance, order 2 as misalignment, otherwise other; stop at or above RMS threshold.',
      'rms_mm_s dominant_order diagnosis stop',dict(velocity_mm_s=[3,-3,4,-4,3,-3,4,-4],spectrum=[dict(frequency_hz=30,amplitude=4),dict(frequency_hz=60,amplitude=1)],rpm=1800,stop_rms_mm_s=4.5),
      dict(velocity_mm_s=[6,-6,5,-5],spectrum=[dict(frequency_hz=30,amplitude=2),dict(frequency_hz=60,amplitude=7)]),('Diagnose shaft imbalance','Escalate high RMS and second-order vibration'))
cases('batch_balance','process_manufacturing','Active material is nonvolatile. Evaporation removes solvent only. Sum input mass, subtract evaporation, calculate final active concentration and packaged good mass.',
      'output_kg active_kg active_fraction good_kg',dict(ingredients=[dict(kg=80,assay_fraction=.9),dict(kg=120,assay_fraction=.1)],evaporation_kg=15,pack_yield_fraction=.98),
      dict(evaporation_kg=40,pack_yield_fraction=.93),('Close a resin batch mass balance','Account for elevated solvent loss'))
cases('blend_optimization','process_manufacturing','Choose available materials in increment_kg amounts for exact batch mass and inclusive assay bounds. Minimize cost; tie-break by lexicographically smallest allocation vector in material order. Return empty vector and null cost if infeasible.',
      'feasible cost_cents allocation_kg',dict(materials=[dict(available_kg=40,assay_fraction=.9,cents_kg=800),dict(available_kg=60,assay_fraction=.2,cents_kg=200),dict(available_kg=30,assay_fraction=.6,cents_kg=450)],increment_kg=5,batch_kg=50,min_assay=.5,max_assay=.55),
      dict(min_assay=.96,max_assay=1),('Minimize blend cost at target assay','Recognize an infeasible blend'))
cases('heat_treatment','thermal_processing','Each segment has constant temperature. Release requires an uninterrupted in-band soak of required duration and no segment above absolute maximum. Also report total in-band time and longest continuous soak.',
      'in_band_minutes continuous_soak_minutes release',dict(segments=[dict(minutes=15,temperature_c=810),dict(minutes=30,temperature_c=845),dict(minutes=25,temperature_c=850)],min_c=840,max_c=860,absolute_max_c=880,required_minutes=50),
      dict(segments=[dict(minutes=30,temperature_c=845),dict(minutes=2,temperature_c=830),dict(minutes=25,temperature_c=850)]),('Release a valid furnace cycle','Reject an interrupted soak'))
cases('weld_heat_input','welding','Net heat input is volts*amps*60*efficiency/(1000*travel_mm_min). Compare inclusively with the qualified process window.',
      'heat_kj_mm within_window',dict(volts=24,amps=180,efficiency=.8,travel_mm_min=280,minimum_kj_mm=.6,maximum_kj_mm=1.2),
      dict(travel_mm_min=100),('Check a qualified GMAW setting','Detect excessive heat input'))
cases('sheet_layout','sheet_metal','Use a uniform rectangular grid only, with edge margin on all sides and kerf only between parts. Compare unrotated grid with a globally 90-degree rotated grid when allowed; prefer unrotated on ties. Return null sheets if no part fits.',
      'parts_per_sheet rotate sheets_required',dict(sheet_width_mm=1250,sheet_height_mm=2500,part_width_mm=310,part_height_mm=490,edge_mm=10,kerf_mm=3,rotation_allowed=True,quantity=82),
      dict(rotation_allowed=False,part_width_mm=600,part_height_mm=410),('Choose a cutting orientation','Respect sheet grain direction'))
cases('press_brake','sheet_metal','One bend: bend allowance is angle radians*(inside radius+K*thickness); outside setback=(radius+thickness)*tan(angle/2); deduction=2*setback-allowance; flat=sum outside flanges-deduction.',
      'bend_allowance_mm bend_deduction_mm flat_mm',dict(angle_deg=90,inside_radius_mm=3,k_factor=.42,thickness_mm=2,outside_flange_mm=[40,65]),
      dict(angle_deg=60,inside_radius_mm=5,thickness_mm=3),('Develop a right-angle bracket blank','Develop an acute-angle flange'))
cases('injection_molding','plastics','Tool dimension=finished dimension/(1-shrink). Clamp force equals total projected area times cavity pressure times safety factor. 1 cm2=100 mm2 and MPa=N/mm2. Compare required kN to machine rating.',
      'tool_dimension_mm clamp_kn parts_hour machine_suitable',dict(finished_dimension_mm=80,shrink_fraction=.018,projected_area_cm2=45,cavity_mpa=45,cavities=4,safety_factor=1.15,yield_fraction=.97,cycle_seconds=32,machine_clamp_kn=1000),
      dict(cavities=8,machine_clamp_kn=1500),('Size a four-cavity tool and press','Reject insufficient press tonnage'))
cases('casting_charge','foundry','Compute net casting mass from part volume and density; divide by casting yield for poured mass, then divide by one minus melt loss for charged mass.',
      'net_kg pour_kg charge_kg',dict(part_volume_cm3=420,density_g_cm3=7.2,quantity=80,casting_yield_fraction=.68,melt_loss_fraction=.03),
      dict(casting_yield_fraction=.42,melt_loss_fraction=.08),('Plan a gray-iron charge','Account for low-yield gating'))
cases('additive_build','additive','Volume includes all parts and supports. Convert mm3 to cm3 for density. Round layer count up, and add one recoating duration per layer to deposition time.',
      'layers feedstock_g build_minutes',dict(part_volume_mm3=48000,support_volume_mm3=12000,quantity=3,density_g_cm3=4.43,height_mm=84,layer_mm=.04,deposition_mm3_min=900,recoat_seconds=8),
      dict(support_volume_mm3=36000,layer_mm=.06,recoat_seconds=12),('Estimate a titanium powder-bed build','Compare heavier supports and layer height'))
cases('smt_line','electronics','Placement cycle is placements per board divided by placements per hour, in seconds. Line cycle is the largest station cycle. Apply yield to hourly output and compute feeder shortage.',
      'cycle_seconds good_boards_hour feeder_shortage',dict(placements_board=840,placements_hour=42000,printer_seconds=35,oven_pitch_seconds=60,aoi_seconds=52,yield_fraction=.985,distinct_parts=85,feeder_slots=96),
      dict(aoi_seconds=95,distinct_parts=112),('Balance an SMT line','Expose AOI and feeder constraints'))
cases('wafer_yield','semiconductors','Use gross dies=floor(pi*(wafer_diameter/2)^2/die_area - pi*wafer_diameter/sqrt(2*die_area)). Poisson yield=exp(-defects_cm2*die_area_mm2/100). Expected good dies may be fractional.',
      'gross_dies yield_fraction expected_good_dies',dict(die_area_mm2=80,wafer_diameter_mm=300,defects_cm2=.12),
      dict(die_area_mm2=240,defects_cm2=.35),('Estimate good dies per wafer','Evaluate a larger high-defect die'))
cases('tool_life','machining','Use Taylor V*T^n=C. Parts per edge=floor(life/cut time); round edges required up, or return null if one edge cannot finish a part.',
      'tool_life_minutes parts_per_edge edges_required',dict(taylor_c=350,taylor_n=.25,speed_m_min=180,cut_minutes_part=2.8,quantity=120),
      dict(speed_m_min=240),('Plan insert consumption','Account for aggressive cutting speed'))
cases('pump_performance','utilities','Hydraulic kW=rho*g*flow*head/1000 using g=9.80665 and flow in m3/s. Wire-to-water efficiency=hydraulic/input. NPSH available minus required must meet the minimum margin.',
      'hydraulic_kw wire_to_water_efficiency cavitation_margin_m acceptable',dict(density_kg_m3=998,flow_m3_hour=75,head_m=32,input_kw=11,npsh_available_m=6,npsh_required_m=3.5,required_margin_m=1),
      dict(npsh_available_m=3.8,input_kw=14),('Assess a chilled-water pump','Detect insufficient cavitation margin'))
cases('weibull_maintenance','maintenance','Given survival S(t)=exp(-(t/eta)^beta), compute failure probability over next_hours conditional on survival to current age. Service now if probability strictly exceeds maximum.',
      'conditional_failure_probability service_now',dict(age_hours=2000,next_hours=300,eta_hours=5000,beta=3,maximum_failure_probability=.1),
      dict(age_hours=4800,next_hours=600),('Schedule bearing service from conditional risk','Prioritize an aging spindle bearing'))
cases('lot_genealogy','traceability','Trace all downstream consumption edges to transitive closure, including suspect source lots. A shipment is affected if any shipped lot is affected. Return sorted unique IDs.',
      'affected_lots affected_shipments',dict(suspect_lots=['R1'],consumption=[dict(input='R1',output='W1'),dict(input='W1',output='F1'),dict(input='R2',output='F2'),dict(input='F1',output='KIT1')],shipments=[dict(id='S1',lots=['KIT1']),dict(id='S2',lots=['F2']),dict(id='S3',lots=['F1','F2'])]),
      dict(suspect_lots=['R2']),('Contain a multi-level material recall','Isolate an independent component branch'))
cases('fmea_priority','quality','Compute severity*occurrence*detection per failure mode. Customer rule requires action for every severity>=9 or RPN>=action_rpn. Return RPN object and sorted action IDs.',
      'rpn action_ids',dict(risks=[dict(id='seal',severity=7,occurrence=6,detection=5),dict(id='guard',severity=10,occurrence=1,detection=1),dict(id='label',severity=3,occurrence=3,detection=2)],action_rpn=150),
      dict(risks=[dict(id='seal',severity=7,occurrence=2,detection=3),dict(id='guard',severity=10,occurrence=1,detection=1),dict(id='label',severity=3,occurrence=8,detection=8)]),('Prioritize severity and risk together','Preserve high-severity action after RPN reduction'))
cases('kanban','lean','Cards=ceil(demand per day*replenishment days*(1+safety fraction)/container units). Authorized units equals cards times container units.',
      'cards authorized_units',dict(demand_units_day=240,replenishment_days=1.5,safety_fraction=.2,container_units=40),
      dict(replenishment_days=2.8,container_units=32),('Size a two-bin replenishment loop','Resize after milk-run deterioration'))
cases('takt_staffing','lean','Takt=net available seconds/demand. Theoretical operators=ceil(total work content/takt). Flag whether any indivisible task exceeds takt.',
      'takt_seconds theoretical_operators indivisible_task_exceeds_takt',dict(net_minutes_shift=420,demand_units=480,task_seconds=[20,35,40,45,25,30]),
      dict(demand_units=720,task_seconds=[20,35,48,45,25,30]),('Staff a manual assembly cell','Expose a task requiring parallelization'))
cases('gdt_position','metrology','Diametral position error=2*hypot(actual-basic). If MMC applies, bonus=max(0,actual hole size-MMC hole size), otherwise zero. Accept inclusively against stated tolerance plus bonus.',
      'position_error_mm allowed_mm accept',dict(actual_x_mm=30.06,actual_y_mm=20.08,basic_x_mm=30,basic_y_mm=20,actual_hole_mm=10.12,mmc_hole_mm=10,mmc_applies=True,position_tolerance_mm=.1),
      dict(mmc_applies=False),('Apply MMC bonus to a hole pattern','Evaluate the same hole at RFS'))
cases('thermal_compensation','metrology','Convert measured length to reference temperature by dividing by 1+CTE*(temperature-reference). Accept inclusively within length limits.',
      'reference_length_mm accept',dict(measured_mm=500.09,cte_per_c=.000023,temperature_c=28,reference_c=20,lsl_mm=499.98,usl_mm=500.02),
      dict(measured_mm=500.15),('Compensate a warm aluminum inspection','Detect a true oversize after compensation'))
cases('bolt_preload','assembly','Use torque=nut factor*preload*nominal diameter in meters. Proof load=stress area in mm2*proof MPa. Accept proof fraction within inclusive limits.',
      'preload_n proof_load_n proof_fraction accept',dict(torque_nm=80,nut_factor=.2,diameter_mm=12,stress_area_mm2=84.3,proof_mpa=580,minimum_fraction=.6,maximum_fraction=.8),
      dict(nut_factor=.12),('Check a dry bolt torque','Detect over-preload after lubrication'))
cases('energy_dispatch','utilities','Schedule one nonpreemptive constant-kW job on zero-based equal-length slots inside the release/deadline window. Reject any slot exceeding site limit. Minimize total energy cents plus peak kW*demand cents/kW; round half-up to cents. Tie-break earliest start. Return null numeric fields if infeasible.',
      'feasible start_slot total_cents peak_kw',dict(base_kw=[80,100,65,50,45,95],cents_kwh=[12,25,28,10,8,14],duration_slots=2,job_kw=40,earliest_slot=0,latest_finish_slot=6,slot_hours=1,demand_cents_kw=35,limit_kw=145),
      dict(limit_kw=80,latest_finish_slot=4),('Shift a furnace load around peak tariff','Recognize an impossible electrical window'))
cases('production_schedule','scheduling','Single machine, all jobs required, no preemption. Setup begins after both preceding job completion and new job release. Changeover map missing keys mean zero. Minimize weighted tardiness cents, then makespan, then lexicographic job ID sequence. Return schedule rows with job, start_minute (setup start), finish_minute.',
      'tardiness_cents makespan_minutes schedule',dict(initial_family='A',jobs=[dict(id='J1',family='A',release_minute=0,run_minutes=40,due_minute=70,late_cents_minute=12),dict(id='J2',family='B',release_minute=0,run_minutes=30,due_minute=65,late_cents_minute=25),dict(id='J3',family='A',release_minute=20,run_minutes=20,due_minute=120,late_cents_minute=8)],changeover_minutes={'A>B':15,'B>A':20}),
      dict(jobs=[dict(id='J1',family='A',release_minute=0,run_minutes=40,due_minute=70,late_cents_minute=12),dict(id='J2',family='B',release_minute=60,run_minutes=30,due_minute=95,late_cents_minute=25),dict(id='J3',family='A',release_minute=0,run_minutes=20,due_minute=50,late_cents_minute=30)]),('Sequence mixed-family work orders','Replan around late material and urgent work'))
cases('cutting_stock','fabrication','Cut indivisible requested pieces from identical bars. Kerf occurs only between adjacent pieces on a bar. Minimize bar count then total waste; report feasible, bars, waste_mm. No end trim. Return null bars/waste if infeasible.',
      'feasible bars waste_mm',dict(pieces_mm=[610,590,410,390,300,300],bar_mm=1200,kerf_mm=3),
      dict(pieces_mm=[1201,400,400]),('Reduce saw stock use with exact packing','Detect an uncuttable requested length'))
cases('pressure_test','test_engineering','Correct end absolute pressure to start temperature using ideal gas law, then subtract atmosphere for gauge pressure. Loss=start gauge-corrected end gauge. Accept if loss at most maximum.',
      'corrected_end_bar loss_bar accept',dict(start_gauge_bar=10,end_gauge_bar=9.8,atmosphere_bar=1.01325,start_c=25,end_c=20,maximum_loss_bar=.1),
      dict(end_gauge_bar=9.5),('Distinguish cooling from a leak','Reject pressure loss after temperature correction'))
cases('motor_drive','automation','Shaft power=torque*rpm*2*pi/60. Divide by motor and drive efficiencies for input. Three-phase current=input watts/(sqrt(3)*line volts*power factor). Flag current strictly above rating.',
      'shaft_kw input_kw current_amps overloaded',dict(torque_nm=65,rpm=1450,motor_efficiency=.91,drive_efficiency=.97,line_volts=400,power_factor=.86,rated_amps=22),
      dict(torque_nm=95),('Check a conveyor drive operating point','Detect drive overload after load increase'))
cases('wastewater_balance','environmental','Compute inlet kg/day as flow m3/day*inlet mg/L/1000. Apply removal fraction to mass and concentration. Compare outlet concentration to discharge limit.',
      'inlet_kg_day removed_kg_day outlet_mg_l within_limit',dict(flow_m3_day=450,inlet_mg_l=320,removal_fraction=.92,limit_mg_l=30),
      dict(removal_fraction=.84),('Close a treatment mass balance','Detect degraded effluent treatment'))
cases('packout','shipping','Units per carton is minimum of volume limit and floor((max gross-tare)/unit mass). Fill all but last carton. Return null carton counts if no unit fits.',
      'units_carton cartons last_carton_units',dict(max_gross_kg=22,tare_kg=1.8,unit_kg=1.3,volume_limit_units=18,quantity=173),
      dict(unit_kg=24),('Pack a finished pump shipment','Reject an overweight shipping configuration'))

cases('multilevel_bom','material_planning','Explode all demand through the acyclic BOM. Aggregate shared-component demand before netting stock. For each item, net stock then round starts up for yield and lot multiple. Component demand is parent starts times quantity, including scrap starts. Item release day is earliest required day minus its lead time; components are required at parent release. Preserve negative release days. Return an integer-valued object for each requested field, keyed by reachable item ID.',
      'gross_requirements_units planned_starts_units release_day',dict(demand_units={'PUMP':12},due_day=10,items={'PUMP':dict(on_hand_units=2,yield_fraction=.95,lot_multiple_units=1,lead_days=2,components={'BODY':1,'ROTOR':1,'SEAL':1}),'BODY':dict(on_hand_units=3,yield_fraction=.9,lot_multiple_units=5,lead_days=3,components={'BLANK':1,'SEAL':2}),'ROTOR':dict(on_hand_units=1,yield_fraction=1,lot_multiple_units=4,lead_days=2,components={'BLANK':1}),'BLANK':dict(on_hand_units=8,yield_fraction=1,lot_multiple_units=10,lead_days=4,components={}),'SEAL':dict(on_hand_units=20,yield_fraction=1,lot_multiple_units=20,lead_days=1,components={})}),
      dict(demand_units={'PUMP':12,'BODY':8},due_day=4),('Explode a pump BOM with shared components','Combine service-body and pump demand before netting'))
cases('assembly_line_balance','lean','Assign indivisible tasks to the minimum number of serial stations. Each station total must fit takt. Every predecessor must be in the same or an earlier station, with feasible task order inside a station. Return station count and total work/(stations*takt); return null count and efficiency if infeasible.',
      'feasible stations balance_efficiency',dict(takt_seconds=60,tasks=[dict(id='A',seconds=35,predecessors=[]),dict(id='B',seconds=30,predecessors=['A']),dict(id='C',seconds=25,predecessors=['A']),dict(id='D',seconds=40,predecessors=['B','C']),dict(id='E',seconds=15,predecessors=['D'])]),
      dict(takt_seconds=30),('Balance precedence-constrained assembly work','Identify an indivisible task above takt'))
