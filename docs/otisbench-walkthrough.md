# Introducing OtisBench

Faraday Research · November 1, 2026 · Version 1.4.2

Testing AI on purchasing, production, quality, and shipping.

[Website](https://faradaycompute.com/research/otisbench) · [Benchmark card](../BENCHMARK_CARD.md)

## What OtisBench tests

OtisBench tests whether an AI agent can complete manufacturing work across connected business systems. An agent reads records, calculates process settings, purchases material, schedules operations, handles disruptions, and ships finished orders.

Version 1.4.2 has ten execution tracks, 32 manufacturing routes, 1,024 individual workflows, 128 production campaigns, and twelve judgment workshops. The tracks test different skills and report separate scores.

The environments represent orders, inventory, machines, people, approvals, and money in software. Actions change the records used by later steps. Production consumes material; inspection controls release; shipments create receivables. The evaluator checks whether the required work was completed.

## Connected business systems

OtisBench models eight system roles. The records are authored benchmark content. These roles do not imply connections to eight live vendor products.

A drawing revision can invalidate process settings and approvals. A quality hold can block reserved material. Moving work to another machine still requires a qualified operator and an available fixture. The agent has to check these dependencies before acting.

| System | What the agent must coordinate |
| --- | --- |
| ERP | Customer orders, quantities, dates, budgets, and commercial commitments |
| MES | Routes, machines, resource bookings, operations, and work in progress |
| SCM | Supplier purchases, lead times, dispatch capacity, and certificates |
| WMS | Material lots, reservations, finished stock, serials, and shipments |
| PLM | Drawing revisions, process instructions, and engineering changes |
| QMS | Inspection, nonconformance, rework, containment, and release |
| CMMS | Condition alerts, repairs, calibration, tooling, and maintenance stock |
| HR | Operator availability, qualifications, and work assignments |

## What the catalog covers

The manufacturing routes include machining, fabrication, casting, molding, electronics, batteries, surface treatment, assembly, chemicals, food, textiles, glass, and ceramics. Other tracks test calculations, purchasing, documents, geometry, sensors, and factory economics.

The 1,024 workflows come from 32 routes × 16 disruption contracts × two parameter draws. The 128 campaigns use the same routes under four operating profiles. Route, disruption, and parameter counts are reported separately.

Additional source-run tiers contain 64 temporal recovery variants, 48 material-network cases, and 128 replenishment cases. These test changing evidence schedules, shared subassemblies, recycling, inter-site transfers, supplier capacity, minimum order quantities, pack sizes, and component allocation. They have separate catalogs and entry points.

| Track | Catalog | What is checked |
| --- | --- | --- |
| Production campaigns | 128; 12–96 orders each | Order completion, shared resources, treasury and spare-stock reconciliation |
| Manufacturing workflows | 1,024; 32 routes | Conforming production, traceability, release, shipment, time and budget |
| Engineering | 84; 42 families | Exact outputs and numerical tolerances |
| Supply chain | 96; 24 families | Reconciliation, approval, posting and read-back |
| Procure to pay | 48; 12 contracts | Linked purchasing, receipt, quality, invoice and payment state |
| Sensor analysis | 48; 12 families | Diagnosis, evidence, recommended action and uncertainty |
| Procurement documents | 32 packets; 8 contracts | Decisions with document and page evidence |
| CAD and drawings | 72; 12 part families | Executable solids, geometry, datums and volume |
| Enterprise execution | 58; 18 families | Completed criteria, authorization, economics and timeliness |
| Factory seasons | 12; 26 weeks each | Profit, demand margin, fill rate, cash and cost decomposition |

## Example: recovering a disrupted order

In a pump-assembly workflow, the agent reads the order, engineering instructions, material lots, and resource records. It calculates the required process settings, reserves eligible material, and schedules the machine, operator, and fixture. The first operation consumes the reserved input. Later operations process the same work in progress.

A late material hold requires a disposition or replacement supply. A drawing change requires updated instructions and recalculated settings. A breakdown requires a qualified alternate or recovery of interrupted work. A failed inspection requires disposition, authorized rework, and new measurements before release.

This is an example of the task design. Compound-recovery cases combine several disruptions. Other cases test calibration, expiring qualifications, tool life, outside processing, recalls, batch capacity, overtime, shared fixtures, split lots, customer allocation, and late deliveries.

Each workflow allows up to 240 tool calls and 2,400 manufacturing minutes. Reads and attempted actions consume time. The agent must finish within the delivery window and budget.

## Running multiple orders in one plant

Campaigns keep the same plant state across 12, 24, 48, or 96 orders. Horizons and global tool-call budgets range from 2,880 to 23,040. Each order also has a 240-call limit. Manufacturing minutes are simulated time, not model runtime.

Orders share equipment, staff, fixtures, tooling, supplier capacity, cash, and maintenance stock. Spending on one order reduces the funds available for the next. A machine trip can interrupt running work. Tool changes and repairs consume kits that must be replenished.

Supplier reservations require 20% deposits. Cancellations incur charges; expired unused bookings lose their deposits. Shipments create receivables collected 240 manufacturing minutes later. Preventive service uses time, cash, and a repair kit to provide temporary protection against condition trips.

A campaign passes only when all orders pass, supplier commitments are resolved, cash and spare-stock ledgers reconcile, and the agent explicitly finishes within the horizon.

## How execution is scored

The primary workflow score awards 40 points for shipped units, 20 for conforming quality release, 10 for route completion, 10 for serial genealogy, 10 for delivery within time and budget, and 10 for current revision, required containment, and final evidence. Strict success requires every check. Critical authorization or release violations set the score to zero.

Approvals are tied to an exact action and the current revision. Material consumption, work in progress, inspections, and shipped serials are checked against the stored state. A written claim of completion earns no shipment credit.

Each track uses its own contract. CAD checks solid geometry. Document tasks check decisions and page evidence. Engineering tasks check output fields and numerical tolerances. Factory seasons measure economic outcomes. Scores remain separate across tracks.

## Decisions that need reviewer judgment

Some tasks have several reasonable answers. A supplier-recovery decision may trade delivery speed against source qualification and commercial risk. Maintenance may require choosing an outage date from uncertain condition evidence. Customer allocation requires deciding who receives limited capacity.

The twelve judgment workflows cover supplier recovery, defect investigation, maintenance strategy, customer allocation, engineering change, customer escalation, capacity investment, supplier development, shift handover, cross-site transfer, process trial, and supplier negotiation. Each has three rounds: twelve cases, 36 decision stages.

The agent submits a recommendation before receiving the next evidence update. It records alternatives, tradeoffs, assumptions, citations, owners, next actions, and reasons for changing or retaining its decision.

Software checks the submission fields and whether cited records were available. Reviewers judge evidence use, tradeoffs, feasibility, uncertainty handling, revisions, and communication on 1–5 scales. A valid citation ID does not prove that the record supports the claim.

Reviewer ratings are reported separately from execution scores. Recommendations do not execute factory actions. Evidence updates are fixed rather than generated by the recommendation’s consequences. Independent blinded review and reviewer calibration are needed to assess decision quality consistently.

## Model results

The table below contains the current maintainer-reported results. Opus 5 has the highest task pass rate at 38%, followed by GPT-5.6 Sol at 36%. Their cross-system completion rates are 25% and 24%.

The figures show completion rates, not why tasks failed. Explaining failures requires reviewing the task traces.

The published summary does not yet include task counts, track mix, aggregation formulas, model snapshots, run settings, repeated runs, or linked artifacts. Those details are needed to reproduce the results and interpret small differences. Weighted requirements is a separate reported metric; it is not established as equivalent to the workflow score. The table contains no judgment-workshop ratings.

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

## Run logs and replay

Runs save actions, tool results, applied events, state hashes, and final checks. Replay reconstructs transitions and compares results. Campaign journals let interrupted runs resume after verifying source fingerprints and rebuilding plant state.

Agents receive task instructions, tool contracts, observations, and their own history. Reference calculations, future event schedules, scores, and evaluator traces are withheld. A deployment must also prevent access to evaluator files on the host.

Reproducible reports need the benchmark commit, manifest, task selection, model snapshot, prompts, settings, budgets, retries, costs, and run artifacts. Replay checks consistency with the software’s rules; validating those rules against manufacturing practice requires separate review.

## Limits and remaining work

The core workflows, records, parts, and documents are authored. Optional measurement and visual-inspection extensions use attributed external datasets. Results from these environments do not establish performance on a live plant or across all commercial systems.

Public tasks may become familiar through repeated use. Parameter variation does not replace structurally different held-out tasks. Judgment ratings depend on reviewer expertise and calibration. Independent practitioner review, held-out workflows, repeated model runs, and task-level failure analysis would strengthen the evaluation.

The catalog does not establish physical handling capability, unrestricted negotiation with people, or long-term adoption inside an organization. OtisBench measures the tasks and rules it implements. Its execution results and reviewer assessments should be read within that scope.

## Run OtisBench

The repository includes task catalogs, evaluation code, the benchmark card, agent integration instructions, and replay tools. Start with an individual workflow and inspect its trace and final checks before running a campaign. Report execution outcomes and reviewer ratings separately.

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
