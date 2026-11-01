# Manufacturing workflows

The primary suite is a Cartesian design of 32 manufacturing routes × 16
disruption contracts × 2 deterministic parameter draws: **1,024 cases**.
Routes, disruption contracts, and parameter draws are reported separately.

## A manufacturing episode

The environment contains customer orders, a work order, released process
instructions, route operations, material lots and reservations, machines,
operators, fixtures, maintenance rules, inspection records, supplier receipts,
approvals, and serialized finished stock. The evaluator keeps the resulting
state and the entire action trace.

Each successful operation books its machine, employee, and fixture. The first
operation consumes exactly the reserved input quantity. Subsequent operations
process that same WIP. Qualifying an alternate machine does not qualify its
operator or remove fixture conflicts. Starting production uses its actual
scheduled start time; intervening events can invalidate the attempted start.

Purchase, overtime, and rework approvals are bound to an exact action payload
and the current engineering revision. Each approval is single-use. Quality
release is idempotent and preserves the shipped state of existing serials.

## Disruption contracts

| Contract | Required manufacturing reasoning or recovery |
|---|---|
| Split material lots | Combine eligible lots to cover the exact production input quantity |
| Late quality hold | Reconcile supplier disposition before consuming reserved material; obtain replacement supply |
| Machine breakdown | Choose a qualified alternate, or explicitly reroute interrupted WIP without consuming material twice |
| Expired calibration | Schedule instrument calibration before the operation and final inspection |
| Drawing effectivity | Wait for the required revision, reread the process instruction, recalculate controls |
| Late inbound material | Buy the missing supply with authorized spend and account for receipt lead time |
| Failed final inspection | Disposition the nonconformance, authorize exact-quantity rework, then remeasure |
| Certification gap | Distinguish a machine-qualified process from an employee whose certification has expired |
| Outside processing | Carry the work through external completion and match the current supplier certificate |
| Tool-life exhaustion | Replace the exhausted tool or select a feasible alternate within budget |
| Customer allocation | Satisfy distinct customer orders, due dates, and complete-order shipment requirements |
| Serial recall | Contain the recalled lot and keep it outside production and shipped genealogy |
| Batch capacity | Select a resource that can process the complete required lot |
| Overtime window | Obtain exact authorization for operations extending beyond regular machine availability |
| Shared fixture | Honor existing fixture bookings in addition to machine and employee availability |
| Compound recovery | Combine engineering effectivity, held material, a failed machine, and nonconformance recovery |

## Process controls

The route's released PLM record supplies process inputs and the names of the
required control fields. The agent derives the values; worked formulas and
reference control values are withheld from agent observations.
Controls include machining RPM/feed, temperature/soak, welding heat input,
forming clamp force, batch active concentration, residence speed, and unit
energy. Controls must have the right fields and finite positive numeric values.
Values outside the process target tolerance still execute, but contaminate the
quality outcome. A valid control schema is not an answer key.

## Scoring

| Outcome | Points |
|---|---:|
| Customer units actually shipped | 40, proportional to required quantity |
| Conforming quality release | 20 |
| Manufacturing route completed | 10 |
| Serialized shipment genealogy reconciled | 10 |
| Every customer fulfilled on time and within budget | 10 |
| Finished with release/shipment evidence, current revision, and required recall containment | 10 |

Strict success requires every check. Attempting an unauthorized protected action,
accepting known nonconformance, or shipping unreleased/invalid serials creates
a critical violation and sets the episode score to zero. Failed feasibility
checks preserve material and money; they are recorded as unsuccessful actions.
Reading records or submitting a prose plan earns no completion points.

Suite summaries report mean score, strict successes, critical failures, a
family-macro strict rate, and separate manufacturing-family and disruption
breakdowns. Case counts do not substitute for family coverage.

## Route index

| Family | Product | Material | Operation route | Cases |
|---|---|---|---|---:|
| precision_cnc | aerospace bracket | 6061-T6 | mill → deburr → cmm | 32 |
| turned_shaft | precision shaft | 4140 | turn → heat → grind → cmm | 32 |
| sheet_fabrication | formed enclosure | 5052-H32 | laser → bend → cmm | 32 |
| welded_structure | structural frame | A36 | laser → weld → ndt | 32 |
| sand_casting | pump casting | EN-GJL-250 | melt → pour → heat → cmm | 32 |
| die_casting | die-cast housing | A380 | cast → trim → xray | 32 |
| injection_molding | molded connector | PA66-GF30 | mold → deflash → vision | 32 |
| extrusion | extruded profile | 6063-T5 | extrude → cut → cmm | 32 |
| rubber_molding | elastomer seal | FKM-75 | mix → mold → cure → test | 32 |
| composite_layup | composite panel | CFRP-prepreg | layup → autoclave → ultrasonic | 32 |
| pcb_assembly | control board | FR4-TG170 | solder → aoi → ict → test | 32 |
| cable_harness | wiring harness | UL1015-18AWG | cut → crimp → hipot | 32 |
| battery_module | battery module | LFP-prismatic | weld → assemble → test | 32 |
| semiconductor | sensor wafer | Si-200mm | etch → deposit → probe | 32 |
| metal_additive | printed manifold | Ti6Al4V | build → stress_relieve → depowder → cmm | 32 |
| heat_treatment | hardened tooling | D2 | furnace → quench → hardness | 32 |
| electroplating | plated contact | C110 | clean → plate → thickness | 32 |
| anodizing | anodized panel | 6061-T6 | clean → anodize → seal → thickness | 32 |
| powder_coating | coated cabinet | CRS | blast → coat → cure → thickness | 32 |
| gear_manufacturing | transmission gear | 8620 | hob → heat → grind → cmm | 32 |
| bearing_assembly | bearing cartridge | 52100 | turn → grind → assemble → test | 32 |
| pump_assembly | industrial pump | 316L | mill → assemble → pressure → run | 32 |
| motor_assembly | electric motor | Cu-ETP | wind → impregnate → balance → test | 32 |
| valve_assembly | control valve | 316L | turn → lap → assemble → pressure | 32 |
| hydraulic_cylinder | hydraulic actuator | ST52 | hone → assemble → pressure | 32 |
| packaging | folded carton | SBS-350 | print → diecut → glue → vision | 32 |
| food_processing | packed food batch | food-grade-base | mix → cook → fill → microbiology | 32 |
| chemical_blending | industrial coating batch | resin-A | weigh → mix → filter → assay | 32 |
| tablet_manufacturing | compressed tablet lot | granulate-A | granulate → compress → coat → assay | 32 |
| textile | technical textile | PET-600D | weave → dye → cut → vision | 32 |
| glass_fabrication | optical glass panel | borosilicate | form → anneal → cut → optical | 32 |
| ceramic_manufacturing | technical ceramic | Al2O3-96 | press → sinter → grind → cmm | 32 |

## Agent/evaluator boundary

The runner constructs the agent task from an explicit allowlist. Case family,
disruption, parameter draw, seed, author title, and author recovery instructions
are evaluator metadata. Each episode receives a fresh opaque task handle.
Business record IDs are aliased consistently throughout records, tool results,
action arguments, and approval payloads. Their original names cannot identify
which employee or lot is the intended choice.

Agent observations use an explicit business-field allowlist. Process input facts
and schemas remain visible; worked equations, grading flags, future answer keys,
unknown evaluator fields, and live scores do not. The runner's reference
calculation is used only to evaluate an agent-submitted production control; it
never proposes or inserts a control value. An invalid value can execute and
fail inspection. Error responses use stable codes instead of instructions for
the next action.

Actual measurements, receipts, machine state, certifications, and quality
bulletins remain observable through the normal tools. These are evidence the
agent must investigate. The private action trace and post-episode grade are
saved in evaluation artifacts; the agent receives a separate projected trace.

For agents with code or filesystem tools, run the agent in a separate container
with its own code and public startup contract. Mount agent files only; keep the
evaluator package, task manifests, tests, and evaluation reports on the host.
A JSONL subprocess transports messages and does not itself sandbox host files.
