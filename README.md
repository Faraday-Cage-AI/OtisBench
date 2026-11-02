# OtisBench

OtisBench tests AI agents on manufacturing workflows across ERP, MES, SCM, WMS, PLM, QMS, CMMS, and HR. Agents read records, purchase material, schedule production, handle disruptions, inspect output, and ship customer orders.

The benchmark has ten evaluation tracks, 32 manufacturing routes, 1,024 individual workflows, and 128 production campaigns. Campaigns contain 12–96 customer orders and allow up to 23,040 tool calls. Twelve additional judgment workflows assess recommendations and revisions through reviewer ratings.

[Tracks](#evaluation-tracks) · [Systems](#modeled-systems) · [Campaigns](#production-campaigns) · [Setup](#get-started) · [Scoring](BENCHMARK_CARD.md)

## Evaluation tracks

| Track | Catalog | What the agent delivers |
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

Engineering changes, equipment trips, quality holds, late receipts, and expired qualifications can interrupt work or invalidate earlier records and approvals. The agent must recover through the tools and complete the required inspections and shipments.

There are 128 campaigns: 32 manufacturing routes × 4 profiles. [Campaign rules, tools, and recovery](docs/production-campaigns.md).

## Workflow execution and scoring

An individual workflow covers order review, material sourcing, production, inspection, rework when required, quality release, and serialized shipment. The agent calculates process settings and selects qualified resources.

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

## Agent inputs

Agents receive the task, tool contracts, and business records. They choose actions and supply all calculated values. The runner does not provide reference plans, expected values, evaluator annotations, or live scores. Workflow identifiers are replaced with opaque identifiers for each episode.

The evaluator calculates reference values only to check submitted controls. It does not insert answers into agent actions.

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

Run a long production campaign with your own agent:

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

The agent is a persistent JSONL process. Read one decision from stdin and write one action to stdout:

```json
{"tool":"read","arguments":{"system":"ERP"}}
```

Keep logs on stderr. Workflow episodes allow up to 240 tool calls and 2,400 manufacturing minutes. The runner saves transitions and terminal checks; replay verifies recorded actions, results, and state hashes.

For offline standalone Python agents on macOS, `otisbench isolated` stages the agent file and enforces OS restrictions on evaluator-file access, network use, and subprocesses. Ordinary `--agent-command` launches provide the JSONL transport. See [agent integration and isolation](docs/agent-isolation.md).

Optional dependencies: `.[cad]` for solid evaluation, `.[documents]` for document tooling, `.[real-data]` for measurement extensions, and `.[openai]` for provider integration. The `mfg-bench` command and existing `faraday-manufacturing/1` wire protocol remain supported.

## Other benchmarks

[LarkBench](https://larkagents.com/blog/larkbench/article.html) evaluates recurring distributor purchasing. [ICCA Bench](https://oroagents.com/benchmarks/icca-bench) evaluates adaptation to delayed consequences at a wholesale buying desk. OtisBench evaluates manufacturing execution, including material transformation, production resources, work in progress, quality release, and shipment. [Scope comparison](docs/benchmark-landscape.md).

## Development

```bash
python -m pytest tests/test_otisbench.py tests/test_agent_boundary.py tests/test_shopfloor.py tests/test_campaign.py tests/test_campaign_logistics.py tests/test_judgment.py -q
python scripts/build_manifest.py --check
```

These commands check package identity, task contracts, action invariants, agent-input boundaries, and release fingerprints. Benchmark episodes and provider calls start only through explicit run commands.

Code: [Apache-2.0](LICENSE). Task content: [CC BY 4.0](DATA_LICENSE). [Methodology](docs/methodology.md) · [Attribution](NOTICE).
