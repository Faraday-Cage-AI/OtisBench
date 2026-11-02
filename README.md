# OtisBench

OtisBench evaluates AI on manufacturing workflows across ERP, MES, SCM, WMS, PLM, QMS, CMMS, and HR. The model reads records, purchases material, schedules production, handles disruptions, inspects output, and ships customer orders.

The benchmark has ten evaluation tracks, 32 manufacturing routes, 1,024 individual workflows, and 128 production campaigns. Campaigns contain 12–96 customer orders and allow up to 23,040 tool calls. Twelve additional judgment workflows assess recommendations and revisions through reviewer ratings.

[Walkthrough](#walkthrough-from-customer-order-to-shipment) · [Results](#model-results) · [Tracks](#evaluation-tracks) · [Systems](#modeled-systems) · [Campaigns](#production-campaigns) · [Setup](#get-started) · [Scoring](BENCHMARK_CARD.md)

## Model results

Current OtisBench results reported by the benchmark maintainers:

| Model | Task pass rate | Weighted requirements | Cross-system completion |
|---|---:|---:|---:|
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

The published summary does not yet include task counts, track mix, aggregation formulas, model snapshots, run settings, repeated runs, or linked artifacts. Those details are needed to reproduce the results and interpret small differences. Weighted requirements is a separate reported metric; it is not established as equivalent to the workflow score. The table contains no judgment-workshop ratings.

## Walkthrough: from customer order to shipment

[Full walkthrough](docs/otisbench-walkthrough.md) · [Website](https://faradaycompute.com/research/otisbench)

### What OtisBench tests

OtisBench tests whether an AI agent can complete manufacturing work across connected business systems. An agent reads records, calculates process settings, purchases material, schedules operations, handles disruptions, and ships finished orders.

Version 1.4.2 has ten execution tracks, 32 manufacturing routes, 1,024 individual workflows, 128 production campaigns, and twelve judgment workshops. The tracks test different skills and report separate scores.

The environments represent orders, inventory, machines, people, approvals, and money in software. Actions change the records used by later steps. Production consumes material; inspection controls release; shipments create receivables. The evaluator checks whether the required work was completed.

### Example: recovering a disrupted order

In a pump-assembly workflow, the agent reads the order, engineering instructions, material lots, and resource records. It calculates the required process settings, reserves eligible material, and schedules the machine, operator, and fixture. The first operation consumes the reserved input. Later operations process the same work in progress.

A late material hold requires a disposition or replacement supply. A drawing change requires updated instructions and recalculated settings. A breakdown requires a qualified alternate or recovery of interrupted work. A failed inspection requires disposition, authorized rework, and new measurements before release.

This is an example of the task design. Compound-recovery cases combine several disruptions. Other cases test calibration, expiring qualifications, tool life, outside processing, recalls, batch capacity, overtime, shared fixtures, split lots, customer allocation, and late deliveries.

Each workflow allows up to 240 tool calls and 2,400 manufacturing minutes. Reads and attempted actions consume time. The agent must finish within the delivery window and budget.

### Running multiple orders in one plant

Campaigns keep the same plant state across 12, 24, 48, or 96 orders. Horizons and global tool-call budgets range from 2,880 to 23,040. Each order also has a 240-call limit. Manufacturing minutes are simulated time, not model runtime.

Orders share equipment, staff, fixtures, tooling, supplier capacity, cash, and maintenance stock. Spending on one order reduces the funds available for the next. A machine trip can interrupt running work. Tool changes and repairs consume kits that must be replenished.

Supplier reservations require 20% deposits. Cancellations incur charges; expired unused bookings lose their deposits. Shipments create receivables collected 240 manufacturing minutes later. Preventive service uses time, cash, and a repair kit to provide temporary protection against condition trips.

A campaign passes only when all orders pass, supplier commitments are resolved, cash and spare-stock ledgers reconcile, and the agent explicitly finishes within the horizon.

### Decisions that need reviewer judgment

Some tasks have several reasonable answers. A supplier-recovery decision may trade delivery speed against source qualification and commercial risk. Maintenance may require choosing an outage date from uncertain condition evidence. Customer allocation requires deciding who receives limited capacity.

The twelve judgment workflows cover supplier recovery, defect investigation, maintenance strategy, customer allocation, engineering change, customer escalation, capacity investment, supplier development, shift handover, cross-site transfer, process trial, and supplier negotiation. Each has three rounds: twelve cases, 36 decision stages.

The agent submits a recommendation before receiving the next evidence update. It records alternatives, tradeoffs, assumptions, citations, owners, next actions, and reasons for changing or retaining its decision.

Software checks the submission fields and whether cited records were available. Reviewers judge evidence use, tradeoffs, feasibility, uncertainty handling, revisions, and communication on 1–5 scales. A valid citation ID does not prove that the record supports the claim.

Reviewer ratings are reported separately from execution scores. Recommendations do not execute factory actions. Evidence updates are fixed rather than generated by the recommendation’s consequences. Independent blinded review and reviewer calibration are needed to assess decision quality consistently.

### Run logs and replay

Runs save actions, tool results, applied events, state hashes, and final checks. Replay reconstructs transitions and compares results. Campaign journals let interrupted runs resume after verifying source fingerprints and rebuilding plant state.

Agents receive task instructions, tool contracts, observations, and their own history. Reference calculations, future event schedules, scores, and evaluator traces are withheld. A deployment must also prevent access to evaluator files on the host.

Reproducible reports need the benchmark commit, manifest, task selection, model snapshot, prompts, settings, budgets, retries, costs, and run artifacts. Replay checks consistency with the software’s rules; validating those rules against manufacturing practice requires separate review.

### Limits and remaining work

The core workflows, records, parts, and documents are authored. Optional measurement and visual-inspection extensions use attributed external datasets. Results from these environments do not establish performance on a live plant or across all commercial systems.

Public tasks may become familiar through repeated use. Parameter variation does not replace structurally different held-out tasks. Judgment ratings depend on reviewer expertise and calibration. Independent practitioner review, held-out workflows, repeated model runs, and task-level failure analysis would strengthen the evaluation.

The catalog does not establish physical handling capability, unrestricted negotiation with people, or long-term adoption inside an organization. OtisBench measures the tasks and rules it implements. Its execution results and reviewer assessments should be read within that scope.

## Evaluation tracks

| Track | Catalog | Required output |
|---|---:|---|
| Production campaigns | 128 campaigns · 12–96 orders each | Completed orders using shared plant resources |
| Manufacturing workflows | 1,024 cases · 32 routes · 16 disruptions | Conforming, traceable customer shipments |
| Engineering | 84 cases · 42 families | Manufacturing calculations and constrained decisions |
| Supply chain | 96 cases · 24 families | Reconciled, approved, posted business decisions |
| Procure to pay | 48 episodes · 12 disruption contracts | Linked purchasing, receipts, quality, invoices, and payments |
| Sensor analysis | 48 cases · 12 families | Diagnoses supported by sensor data |
| Procurement documents | 32 packets · 8 contracts · 2 draws · 2 PDF modes | Reconciliation with document and page evidence |
| CAD and drawings | 72 cases · 12 part families · 3 evidence modes · 2 draws | Executable solids checked with OpenCascade |
| Enterprise execution | 58 tasks · 18 families | Completed changes across connected business systems |
| Factory seasons | 12 seasons · 26 weeks each | Purchasing, production, maintenance, fulfillment, and profit |

Each track keeps its own metrics. [Track contracts and scoring →](BENCHMARK_CARD.md)

## Modeled systems

| System | Records and actions |
|---|---|
| ERP | Customer orders, quantities, delivery dates, and budgets |
| MES | Production routes, operations, machines, resource bookings, and work in progress |
| SCM | Suppliers, purchasing, inbound orders, lead times, and certificates |
| WMS | Material lots, reservations, finished stock, serials, and shipments |
| PLM | Drawings, revisions, process instructions, and engineering changes |
| QMS | Inspections, nonconformance, rework, recalls, and release |
| CMMS | Equipment alerts, repairs, calibration, and tooling |
| HR | Operators, qualifications, availability, and assignments |

Actions update the records used by later steps. Production consumes reserved material. Quality release controls shipment. Campaigns add shared supplier capacity, maintenance stock, cash, and delayed customer payments.

## Production campaigns

Each campaign keeps the same plant state across multiple customer orders.

| Profile | Customer orders | Manufacturing horizon | Maximum tool calls |
|---|---:|---:|---:|
| Six shifts | 12 | 2,880 minutes | 2,880 |
| Twelve shifts | 24 | 5,760 minutes | 5,760 |
| Twenty-four shifts | 48 | 11,520 minutes | 11,520 |
| Forty-eight shifts | 96 | 23,040 minutes | 23,040 |

Orders share machines, staff, fixtures, tooling, material, supplier dispatch slots, and cash. Supply reservations require deposits. Maintenance consumes kits. Customer shipments generate delayed payments. Each order has a separate 240-call limit.

Engineering changes, equipment trips, quality holds, late receipts, and expired qualifications can interrupt work or invalidate earlier records and approvals. The model must recover through the tools and complete the required inspections and shipments.

There are 128 campaigns: 32 manufacturing routes × 4 profiles. [Campaign rules, tools, and recovery](docs/production-campaigns.md).

## Workflow execution and scoring

An individual workflow covers order review, material sourcing, production, inspection, rework when required, quality release, and serialized shipment. The model calculates process settings and selects qualified resources.

Workflow scores check delivered quantity, completed operations, quality release, serial traceability, delivery dates, budget, and final evidence. Critical authorization or product-release violations set the score to zero. Campaign completion also requires all orders to pass and the financial and spare-stock ledgers to reconcile.

The runner retains actions, tool results, state hashes, and final checks. Replay reconstructs the run and verifies those records. [Scoring rules](BENCHMARK_CARD.md).

## Manufacturing coverage

| Process group | Routes |
|---|---|
| Machining and fabrication | Precision CNC, turned shafts, sheet fabrication, weldments, gears, hydraulic cylinders |
| Materials and forming | Sand casting, die casting, injection molding, extrusion, rubber molding, composites |
| Electronics and electrical | PCB assembly, cable harnesses, battery modules, semiconductors, motors |
| Surface and thermal processing | Heat treatment, electroplating, anodizing, powder coating |
| Mechanical assembly | Bearings, pumps, valves |
| Process and batch production | Food, chemical blending, tablets, textiles, glass, ceramics |
| Other production | Metal additive manufacturing, packaging |

[All 32 routes, 16 disruptions, and workflow scoring →](docs/manufacturing-workflows.md)

## Manufacturing judgment

Twelve workflows cover supplier recovery, defect investigation, maintenance, customer allocation, revision cutover, customer escalation, capital investment, supplier development, shift handover, cross-site transfer, process trials, and negotiation.

Each has three rounds. The participant submits a recommendation, receives new evidence, and revises the decision. Reviewers assess evidence use, tradeoffs, feasibility, uncertainty, revisions, and communication. These ratings are reported separately from execution scores. [Workshop instructions and rubric](docs/manufacturing-judgment.md).

## Additional task sets

- **Temporal recovery — 64 workflow variants.** Engineering releases, equipment trips, and quality dispositions arrive on separate schedules. Shared-fixture bookings, expiring qualifications, and tight customer deadlines constrain when actions can execute. [Temporal tier →](challenges/README.md)
- **Material networks — 48 cases across 8 graph families.** Parallel branches, reconvergent flows, nested and shared subassemblies, co-products, recycling, and inter-site transfers execute against stock, mass, cash, and resource ledgers. [Material networks →](docs/manufacturing-networks.md)
- **Replenishment — 128 cases across 16 planning contracts.** Supplier capacity, MOQ, pack sizes, split sourcing, deposits, landed costs, and component-to-shipment allocation. [Replenishment →](docs/replenishment.md)
- **Measurement and document extensions.** Hydraulic condition monitoring, photographed visual inspection, supplier scans, and Odoo-backed ERP compatibility provide additional measurement and document inputs. [Extension guide →](docs/extensions.md)

These tiers have separate catalogs and entry points in the source checkout.

## Model inputs

Models receive the task, tool contracts, and business records. They choose actions and supply all calculated values. The runner does not provide reference plans, expected values, evaluator annotations, or live scores. Workflow identifiers are replaced with opaque identifiers for each episode.

The evaluator calculates reference values only to check submitted controls. It does not insert answers into model actions.

## Get started

```bash
git clone https://github.com/Faraday-Cage-AI/OtisBench.git
cd OtisBench
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'

# Inspect the catalog and export the agent's startup contract.
otisbench list --track workflow
otisbench show mfg-flow-pump_assembly-16-01
otisbench export-agent --task mfg-flow-pump_assembly-16-01 --output agent-input.json
```

Run a long production campaign with your own model:

```bash
otisbench campaign \
  --task campaign-pump_assembly-forty_eight_shift \
  --agent-command 'python /absolute/path/to/my_agent.py' \
  --output runs/pump-campaign.json
```

Run a selected individual workflow:

```bash
otisbench workflow   --task mfg-flow-pump_assembly-16-01   --agent-command 'python /absolute/path/to/my_agent.py'   --output runs/pump-recovery.json

otisbench replay runs/pump-recovery.json
```

The model connects through a persistent JSONL process. Read one decision from stdin and write one action to stdout:

```json
{"tool":"read","arguments":{"system":"ERP"}}
```

Keep logs on stderr. Workflow episodes allow up to 240 tool calls and 2,400 manufacturing minutes. The runner saves transitions and terminal checks; replay verifies recorded actions, results, and state hashes.

For offline standalone Python agents on macOS, `otisbench isolated` stages the agent file and enforces OS restrictions on evaluator-file access, network use, and subprocesses. Ordinary `--agent-command` launches provide the JSONL transport. See [agent integration and isolation](docs/agent-isolation.md).

Optional dependencies: `.[cad]` for solid evaluation, `.[documents]` for document tooling, `.[real-data]` for measurement extensions, and `.[openai]` for provider integration. The `mfg-bench` command and existing `faraday-manufacturing/1` wire protocol remain supported.

## Development

```bash
python -m pytest tests/test_otisbench.py tests/test_agent_boundary.py tests/test_shopfloor.py tests/test_campaign.py tests/test_campaign_logistics.py tests/test_judgment.py -q
python scripts/build_manifest.py --check
```

These commands check package identity, task contracts, action invariants, agent-input boundaries, and release fingerprints. Benchmark episodes and provider calls start only through explicit run commands.

Code: [Apache-2.0](LICENSE). Task content: [CC BY 4.0](DATA_LICENSE). [Methodology](docs/methodology.md) · [Attribution](NOTICE).
