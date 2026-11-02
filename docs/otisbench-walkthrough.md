# OtisBench: AI evaluation for manufacturing

Faraday Research · November 1, 2026 · Version 1.4.2

A comprehensive benchmark for AI in manufacturing.

[Website](https://faradaycompute.com/research/otisbench) · [Benchmark card](../BENCHMARK_CARD.md)

## Manufacturing work from order to shipment

OtisBench evaluates whether AI models can fulfill manufacturing orders across engineering, purchasing, production, quality, and shipping. Models inspect business records, calculate process settings, secure material, schedule resources, and recover when conditions change. Completion depends on the resulting production and business records.

Version 1.4.2 includes ten execution tracks, 32 manufacturing routes, 1,024 individual workflows, 128 production campaigns, and twelve judgment workshops. Together, they cover both work with explicit completion criteria and decisions that require a reviewer to assess the evidence and tradeoffs.

Each environment maintains operational state throughout the task. Production consumes reserved material and creates work in progress. Quality release determines which units can ship. In campaigns, shipments generate receivables that help fund subsequent orders. These dependencies carry the consequences of an action into later decisions.

## Eight systems, connected through the order

OtisBench models the roles of ERP, MES, SCM, WMS, PLM, QMS, CMMS, and HR systems. Their records describe the same orders, materials, equipment, and people, so a change in one area can affect work elsewhere.

A drawing revision can invalidate process settings and approvals. A quality hold can prevent consumption of reserved material. Moving an operation to another machine still requires a qualified operator and an available fixture. Models must reconcile these dependencies as the records change.

| System | What the model must coordinate |
| --- | --- |
| ERP | Customer orders, quantities, dates, budgets, and commercial commitments |
| MES | Routes, machines, resource bookings, operations, and work in progress |
| SCM | Supplier purchases, lead times, dispatch capacity, and certificates |
| WMS | Material lots, reservations, finished stock, serials, and shipments |
| PLM | Drawing revisions, process instructions, and engineering changes |
| QMS | Inspection, nonconformance, rework, containment, and release |
| CMMS | Condition alerts, repairs, calibration, tooling, and maintenance stock |
| HR | Operator availability, qualifications, and work assignments |

## Ten evaluation tracks

Manufacturing coverage spans machining, fabrication, casting, molding, electronics, batteries, surface treatment, assembly, and process industries including chemicals, food, textiles, glass, and ceramics. Dedicated tracks extend the evaluation to engineering calculations, commercial transactions, sensor analysis, procurement documents, CAD geometry, and factory economics.

The workflow catalog combines 32 routes with 16 disruption contracts and two parameter draws, yielding 1,024 cases. Campaigns apply four operating profiles to each route, yielding 128 persistent episodes. Route, disruption, and parameter counts remain distinct measures of coverage.

Additional catalogs available from the source checkout include 64 temporal recovery variants, 48 material-network cases, and 128 replenishment cases. They test evidence arriving at different times, shared subassemblies, recycling, inter-site transfers, supplier capacity, minimum order quantities, pack sizes, and component allocation.

| Track | Cases and structure | Evaluation criteria |
| --- | --- | --- |
| Production campaigns | 128 · 12–96 orders each | Order completion, shared-resource use, cash and spare-stock reconciliation |
| Manufacturing workflows | 1,024 · 32 routes | Conforming production, traceability, release, shipment, time and budget |
| Engineering | 84 · 42 families | Required output fields and numerical tolerances |
| Supply chain | 96 · 24 families | Reconciliation, approval, posting and read-back |
| Procure to pay | 48 · 12 contracts | Linked purchasing, receipt, quality, invoice and payment state |
| Sensor analysis | 48 · 12 families | Diagnosis, evidence, recommended action and uncertainty |
| Procurement documents | 32 packets · 8 contracts | Decisions with document and page evidence |
| CAD and drawings | 72 · 12 part families | Executable solids, geometry, datums and volume |
| Enterprise execution | 58 · 18 families | Task completion, authorization, economic outcomes, and timeliness |
| Factory seasons | 12 · 26 weeks each | Profit, demand margin, fill rate, cash, and itemized costs |

## Example: a pump order under disruption

A pump-assembly task begins with a customer order, released engineering instructions, material lots, and resource availability. The model derives the process settings, reserves eligible stock, and schedules a machine, operator, and fixture. The first operation consumes the reserved input; subsequent operations carry that work in progress toward inspection and shipment.

If a quality hold affects the material, production must wait for an acceptable disposition or replacement supply. A drawing change requires current instructions and revised settings. A machine failure requires a qualified alternate or recovery of interrupted work. Failed inspection requires a disposition, authorized rework, and new measurements before release.

This example describes the task structure. Compound-recovery cases combine several disruptions within an episode. Other cases focus on calibration, expiring qualifications, tool life, outside processing, recalls, batch capacity, overtime, shared fixtures, split lots, customer allocation, or late receipts.

Each workflow permits up to 240 tool calls and 2,400 manufacturing minutes. Reads and attempted actions advance the clock, making investigation and recovery part of the delivery schedule. Success requires completing the order within its time and budget constraints.

## Production campaigns with shared resources

Campaigns extend the same plant state across 12, 24, 48, or 96 orders. The four profiles allow 2,880 to 23,040 simulated manufacturing minutes and the same respective number of tool calls. Each order retains a separate 240-call limit.

All orders draw on shared equipment, staff, fixtures, tooling, supplier capacity, cash, and maintenance stock. A purchase reduces the funds available for other orders. A machine trip can interrupt scheduled production. Repairs and tool changes consume kits that must be replenished before later work needs them.

Commercial commitments persist across the campaign. Supplier reservations require 20% deposits; cancellations incur charges, and unused bookings forfeit their deposits when they expire. Shipments create receivables collected 240 manufacturing minutes later. Preventive service consumes time, cash, and a repair kit in exchange for temporary protection against condition trips.

Strict campaign success requires every order to pass, all supplier commitments to be resolved, and cash and spare-stock ledgers to reconcile. The model must also finish explicitly within the campaign horizon. These horizons describe simulated operating time rather than model runtime.

## Completion criteria and scoring

The primary workflow score assigns 40 points to shipped customer units, 20 to conforming quality release, 10 to route completion, 10 to serial genealogy, 10 to delivery within time and budget, and 10 to the current revision, required containment, and final evidence. Strict success requires every check to pass. Critical authorization or release violations set the score to zero.

The evaluator checks actions against the stored state, including material consumption, work in progress, inspections, and shipped serials. Approvals bind to an exact action and the current engineering revision. Shipment credit requires a valid shipment record.

Other tracks use criteria suited to their outputs. CAD tasks check solid geometry; procurement-document tasks check decisions and page evidence; engineering tasks check required fields and numerical tolerances. Factory seasons measure economic outcomes. Scores remain separate because the tracks measure different results.

## Evaluating decisions with several defensible answers

Many operational decisions cannot be settled by an exact output check. Supplier recovery may require balancing delivery speed, source qualification, and commercial exposure. Maintenance decisions depend on uncertain condition evidence and the cost of an outage. Customer allocation requires choosing how to use limited capacity.

Twelve judgment workflows cover supplier recovery, defect investigation, maintenance strategy, customer allocation, engineering change, customer escalation, capacity investment, supplier development, shift handover, cross-site transfer, process trials, and supplier negotiation. Each contains three rounds, for twelve cases and 36 decision stages.

At each round, the model commits a recommendation before receiving new evidence. Submissions include alternatives, tradeoffs, assumptions, citations, responsible owners, next actions, and reasons for retaining or revising the decision. Reviewers can then assess how the recommendation responds to changing information.

Automated checks validate the submission fields and confirm that cited records were available. Reviewers assess evidence use, tradeoffs, feasibility, uncertainty handling, revisions, and communication on 1–5 scales. Assessing whether a citation actually supports a claim remains part of the review.

Judgment ratings are reported separately from execution scores. Workshop recommendations do not execute factory actions, and evidence updates follow a fixed sequence. Independent blinded review and reviewer calibration are needed to assess decision quality consistently.

## Reported model performance

In the current maintainer-reported results, Opus 5 records the highest task pass rate at 38%, followed by GPT-5.6 Sol at 36%. Their cross-system completion rates are 25% and 24%, respectively. The chart and table show all ten models across the three reported metrics.

Task traces are needed to explain the failures behind these rates. The aggregate results alone do not distinguish errors in calculation, planning, authorization, or execution.

| Model | Task pass rate | Weighted requirements | Cross-system completion |
| --- | --- | --- | --- |
| Opus 5 | 38% | 44% | 25% |
| GPT-5.6 Sol | 36% | 42% | 24% |
| GPT-5.5 | 33% | 39% | 22% |
| Opus 4.8 | 32% | 38% | 21% |
| Grok 4.5 | 31% | 37% | 20% |
| Opus 4.7 | 28% | 34% | 18% |
| GPT-5.4 | 26% | 32% | 17% |
| Gemini 3.1 Pro | 25% | 31% | 16% |
| GLM-5.2 | 23% | 29% | 14% |
| Sonnet 4.6 | 21% | 27% | 13% |

## Recorded actions and reproducible runs

Run artifacts preserve submitted actions, tool results, applied events, state hashes, and final checks. Replay reconstructs the transitions and compares the resulting state and scores. Campaign journals support resuming interrupted episodes after source fingerprints and the recorded history have been verified.

Models receive task instructions, tool contracts, observations, and their own history. Reference calculations, future event schedules, scores, and evaluator traces remain outside their context. Evaluation deployments must also restrict access to evaluator files on the host.

A reproducible model report identifies the benchmark commit, manifest, selected tasks, exact model version, prompts, settings, budgets, retries, costs, and run artifacts. Replay verifies consistency with the implemented rules. Separate practitioner review is needed to assess how well those rules represent manufacturing work.

## Scope and limitations

The core environments use authored workflows, commercial records, parts, and documents. Optional measurement and visual-inspection extensions use attributed external datasets. The results measure performance in these environments; they do not establish reliability in a live plant or compatibility with every commercial system.

Public tasks can become familiar through repeated exposure. New parameter draws do not replace structurally different held-out workflows. Judgment ratings also depend on reviewer expertise and calibration. Independent practitioner review, held-out tasks, repeated runs, and task-level failure analysis would strengthen the evidence.

Physical handling, open-ended negotiation with people, and long-term organizational adoption are outside the demonstrated scope. Execution scores and reviewer assessments describe performance under the specific task rules and evidence provided.

## Run an evaluation

The repository includes task catalogs, evaluation code, scoring contracts, model integration instructions, and replay tools. An individual workflow provides a bounded starting point for inspecting actions and final checks before moving to a full campaign. Execution outcomes and reviewer ratings should be reported separately.

```bash
git clone https://github.com/Faraday-Cage-AI/OtisBench.git
cd OtisBench
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
otisbench list --track workflow
otisbench export-agent --task mfg-flow-pump_assembly-16-01 --output agent-input.json
# Supply your own agent implementation.
otisbench workflow --task mfg-flow-pump_assembly-16-01 \
  --agent-command 'python /absolute/path/to/my_agent.py' --output runs/pump.json
otisbench replay runs/pump.json
```

## Documentation

[Benchmark card](../BENCHMARK_CARD.md) · [Workflows](manufacturing-workflows.md) · [Campaigns](production-campaigns.md) · [Judgment workshops](manufacturing-judgment.md) · [Scoring](methodology.md) · [Agent isolation](agent-isolation.md)
