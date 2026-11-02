# OtisBench

OtisBench evaluates AI on manufacturing workflows across ERP, MES, SCM, WMS, PLM, QMS, CMMS, and HR. The model reads records, purchases material, schedules production, handles disruptions, inspects output, and ships customer orders.

The benchmark has ten evaluation tracks, 32 manufacturing routes, 1,024 individual workflows, and 128 production campaigns. Campaigns contain 12–96 customer orders and allow up to 23,040 tool calls. Twelve additional judgment workflows assess recommendations and revisions through reviewer ratings.

[Walkthrough](#walkthrough-from-customer-order-to-customer-shipment) · [Results](#model-results) · [Tracks](#evaluation-tracks) · [Systems](#modeled-systems) · [Campaigns](#production-campaigns) · [Setup](#get-started) · [Scoring](BENCHMARK_CARD.md)

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

This summary does not include its task denominator, track mix, metric aggregation formulas, exact model snapshots, agent configuration, repeat count, uncertainty intervals, or linked run artifacts. Those details are needed to reproduce the figures and assess small differences. The weighted-requirements column should not be equated with the primary workflow outcome score without its aggregation specification. Judgment-workshop ratings are not presented in this table.

## Walkthrough: from customer order to customer shipment

[Full walkthrough](docs/otisbench-walkthrough.md) · [Website edition](https://faradaycompute.com/research/otisbench)

### What we set out to measure

A customer order is a promise that crosses departments. Engineering defines what must be built. Purchasing secures the right material. Production needs qualified people, available machines, and workable process settings. Quality decides what can be released. Shipping must deliver the correct serialized units before the customer window closes.

OtisBench evaluates whether an AI can carry that promise through a modeled manufacturing operation. It combines engineering problems, operational tools, changing evidence, and persistent plant state. A plausible plan is only the beginning: execution tracks check the records and physical or financial outcomes represented by the environment.

We built OtisBench 1.4.2 with ten outcome-scored tracks, 32 manufacturing routes, 1,024 individual manufacturing workflows, 128 production campaigns, and twelve staged judgment workshops. Its breadth comes from connecting different kinds of work, while retaining separate measures for what each task actually tests.

### A short example: recovering a disrupted order

Consider a pump-assembly order. The agent reads the customer commitment, released engineering instructions, material lots, and resource records. It derives the process controls required by the route, reserves eligible material, and schedules the equipment, operator, and fixture. Production consumes that reserved input and carries the resulting work in progress through later operations.

The catalog introduces sixteen disruption contracts. A late material hold requires a disposition or replacement supply. A drawing change requires current instructions and recalculated settings. A breakdown requires qualified alternate capacity or recovery of interrupted work. A failed inspection requires disposition, exact authorization for rework, and new measurements before release.

This walkthrough illustrates the task design, not an observed model trajectory. Compound-recovery cases combine engineering effectivity, held material, machine failure, and nonconformance. Other contracts exercise expiring certifications, tool life, calibration, outside processing, customer allocation, serial recalls, batch capacity, overtime, shared fixtures, split lots, and late inbound material.

An individual workflow permits up to 240 tool calls and 2,400 manufacturing minutes. Reads and attempted actions consume time. An agent must obtain current evidence and execute within the remaining window; waiting for perfect information can itself make delivery infeasible.

### From one completed job to a plant that keeps running

Production campaigns keep one plant state across 12, 24, 48, or 96 customer orders. Their horizons and global decision budgets range from 2,880 to 23,040 manufacturing minutes and tool calls. Each order also retains its own 240-call limit. These are simulated operating horizons and decision limits, not measured wall-clock model runtimes.

Orders share machines, employees, fixtures, tooling, supplier dispatch capacity, cash, and maintenance stock. A locally convenient purchase can consume the cash needed for the next order. A machine trip can interrupt work already in progress elsewhere. A replacement tool or repair consumes finite kits that must themselves be replenished.

Supplier reservations lock 20% deposits. Unused bookings can incur cancellation charges or lose deposits when they expire. Actual customer shipments produce receivables collected 240 manufacturing minutes later. Preventive service trades present downtime, cash, and a repair kit for temporary condition-trip coverage. These rules make commitments persist beyond the action that created them.

Strict campaign completion requires every order to pass, supplier commitments to be resolved, an explicit campaign finish, and reconciled financial and spare-stock ledgers within the horizon. Completing an early order is useful progress; it does not establish that the agent can sustain the whole campaign.

### The work without one provably correct answer

Some consequential manufacturing decisions admit several defensible answers. Should a team expedite a fragile supplier or qualify another source? Which customer receives constrained capacity? Does uncertain condition evidence justify a maintenance outage? When should a process trial become a production change?

OtisBench includes twelve judgment workflows: supplier recovery, defect investigation, maintenance strategy, customer allocation, engineering change, customer escalation, capacity investment, supplier development, shift handover, cross-site transfer, process trial, and supplier negotiation. Each contains three decision rounds, giving twelve cases and 36 stages, rather than 36 independent cases.

The participant commits a recommendation before the next evidence update appears. Submissions record alternatives, tradeoffs, assumptions, evidence citations, next actions with owners and triggers, and reasons for revising or retaining the decision. Reviewers can inspect whether new evidence changes the recommendation and whether downstream commitments remain coherent.

Software verifies the submission structure and whether cited record IDs were visible. It does not establish that a citation supports the claim, that the recommendation is feasible, or that its tradeoffs are sound. Reviewers assess evidence use, tradeoff quality, operational feasibility, uncertainty handling, revision quality, and communication on separate 1–5 scales.

These ratings remain separate from deterministic strict success. A submitted recommendation does not execute a purchase, obtain approval, or demonstrate business value. The workshops currently release fixed evidence updates; they do not simulate action-dependent consequences of the recommendation. Independent, blinded review and preserved disagreements are needed to support stronger claims about decision quality.

### An operational record that can be inspected

Run artifacts retain submitted actions, tool results, applied events, state hashes, and terminal checks. Replay reconstructs the transitions and checks the final results. Campaign journals support recovery from interruptions; source fingerprints identify the environment used.

The participant receives public tasks, tool contracts, observations, and its own history. Reference calculations, future event schedules, live scores, and evaluator traces belong outside its context. Public source availability makes process isolation important: a tool interface alone does not prevent an agent with host access from reading evaluator files.

A complete model report should bind the benchmark commit and manifest to the task selection, model snapshot, prompts, reasoning settings, budgets, retries, costs, and replayable artifacts. Replay tests consistency with the implemented environment. It does not independently validate the realism of the environment or establish industrial safety.

### What the benchmark establishes—and what remains open

OtisBench offers broad, executable coverage of connected manufacturing work. Its strongest design feature is that material, capacity, engineering revisions, approvals, quality, and cash can constrain the same episode. The judgment workshops extend that scope to decisions whose quality cannot be reduced to a single exact output.

The core commercial records, workflows, parts, and documents are authored task content. Optional measurement and visual-inspection extensions use attributed external datasets; that does not make the core suite observed customer operations. Passing a modeled process is evidence about that process contract, not proof of performance on a live plant, a certified control system, or every commercial ERP.

Public tasks can become familiar through repeated use. More parameter draws do not substitute for structurally different held-out workflows. Reviewer preference, domain expertise, and calibration affect judgment scores. Independent practitioner review, held-out task designs, repeated model runs, and failure analysis would strengthen the evidence.

The scope is intentionally described in concrete terms rather than as a claim of universal comprehensiveness. Physical handling, every vendor integration, unconstrained human negotiation, and long-term organizational adoption are not established by the catalog. The research question remains practical: which parts of an industrial commitment can an agent execute reliably, and where does it still need human judgment or intervention?

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
