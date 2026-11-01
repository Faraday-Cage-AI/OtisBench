# OtisBench

**Manufacturing agents, from engineering release to shipped product.**

OtisBench evaluates whether an AI agent can complete a manufacturing order across engineering, purchasing, production, maintenance, quality, and delivery. The agent investigates business records, calculates process settings, commits actions, recovers from disruptions, and ships conforming product with serial traceability.

The primary suite contains **1,024 manufacturing workflows: 32 process routes × 16 disruption contracts × 2 parameter draws.** Every workflow has physical production, resource constraints, changing records, and an end state that the evaluator checks.

## Long-running production campaigns

Keep the plant running across **12 or 24 work orders** in one persistent agent episode. Campaigns cover **six or twelve manufacturing shifts**, with budgets of **2,880 or 5,760 tool calls**. Orders share machines, labor, fixtures, tool life, calibration, and cash. Production can overlap across route stages; spending and delayed customer payments affect the next order.

Engineering releases, supplier dispositions, and equipment trips continue as later orders arrive. A machine trip can interrupt another order's WIP. Agents must preserve state, schedule competing work, maintain resources, recover production, and meet each order's delivery window. Waiting for every future change misses the first deadline.

**64 campaigns = 32 manufacturing routes × 2 operating horizons.** [Campaign tools, scoring, checkpointing, and resume →](docs/production-campaigns.md)

## A complete manufacturing workflow

1. Reconcile the customer order, drawing revision, material specification, quantity, and delivery date.
2. Source and reserve eligible material across lots; account for supplier certificates, ownership, holds, and receipt times.
3. Derive process controls and select machines, operators, tools, and calibrated fixtures.
4. Execute the route with finite capacity, resource bookings, irreversible material consumption, and work in progress.
5. Recover from breakdowns, engineering changes, expired qualifications, delayed supply, and failed inspection.
6. Obtain action-bound approvals, perform authorized rework, release quality, and ship serialized finished goods.

Reading records and writing a plan do not fulfill an order. The score follows the product: completed operations, conforming release, actual shipments, genealogy, deadline, budget, and authorization.

## Built for difficult operational decisions

**Evidence changes while the agent works.** A reserved lot can enter quality hold. A drawing revision can invalidate process settings and approvals. A machine can trip during production, leaving interrupted WIP that must be recovered without consuming material twice.

**Resources interact.** A qualified machine still needs a qualified operator, an available fixture, enough tool life, a feasible batch size, and an operating window. Premium alternatives, replacement material, calibration, and rework compete for one production budget.

**Numerical mistakes have consequences.** Agents derive spindle speed and feed, thermal soak, welding heat input, clamp force, concentration, residence speed, or unit energy. Incorrect settings can execute and produce a failed inspection.

**Recovery requires execution.** A nonconformance needs disposition, exact-quantity rework, approval, and a new measurement. Outside processing needs a matching certificate. Shipment requires released serials allocated to the right customer order.

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

## Ten evaluation tracks

| Track | Catalog | What the agent delivers |
|---|---:|---|
| Production campaigns | 64 campaigns · 12 or 24 orders each | Sustained fulfillment across a shared plant |
| Manufacturing workflows | 1,024 cases · 32 routes · 16 disruptions | Conforming, traceable customer shipments |
| Engineering | 84 cases · 42 families | Manufacturing calculations and constrained decisions |
| Supply chain | 96 cases · 24 families | Reconciled, approved, posted business decisions |
| Procure to pay | 48 episodes · 12 disruption contracts | Linked purchasing, receipts, quality, invoices, and payments |
| Sensor analysis | 48 cases · 12 families | Evidence-based diagnoses and operating decisions |
| Procurement documents | 32 packets · 8 contracts · 2 draws · 2 PDF modes | Reconciliation with document and page evidence |
| CAD and drawings | 72 cases · 12 part families · 3 evidence modes · 2 draws | Executable solids checked with OpenCascade |
| Enterprise execution | 58 tasks · 18 families | Completed changes across connected business systems |
| Factory seasons | 12 seasons · 26 weeks each | Purchasing, production, maintenance, fulfillment, and profit |

Each track keeps its own metrics. [Track contracts and scoring →](BENCHMARK_CARD.md)

## Advanced manufacturing tiers

- **Temporal recovery — 64 workflow variants.** Engineering releases, equipment trips, and quality dispositions arrive on separate schedules. Shared-fixture bookings, expiring qualifications, and tight customer deadlines make timing part of the solution. [Temporal tier →](challenges/README.md)
- **Material networks — 48 cases across 8 graph families.** Parallel branches, reconvergent flows, nested and shared subassemblies, co-products, recycling, and inter-site transfers execute against stock, mass, cash, and resource ledgers. [Material networks →](docs/manufacturing-networks.md)
- **Replenishment — 128 cases across 16 planning contracts.** Supplier capacity, MOQ, pack sizes, split sourcing, deposits, landed costs, and component-to-shipment allocation. [Replenishment →](docs/replenishment.md)
- **Measurement and document extensions.** Hydraulic condition monitoring, photographed visual inspection, supplier scans, and Odoo-backed ERP compatibility connect operational decisions to their source evidence. [Extension guide →](docs/extensions.md)

These tiers have separate catalogs and entry points in the source checkout.

## The agent supplies the solution

Agents receive a neutral fulfillment goal, tool contracts, and observable business records. The agent chooses every action and submits every calculated value. Workflow identifiers are opaque per episode. Worked formulas, scenario labels, reference plans, evaluator annotations, expected values, and live scores stay outside the workflow agent transport.

The evaluator uses reference calculations to check submitted controls; it never fills them in for the agent. Inspection results describe work already performed.

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
  --task campaign-pump_assembly-twelve_shift \
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

## Design comparison

LarkBench centers on recurring distributor purchasing over 26 weeks. OtisBench centers on manufacturing execution: transform material, operate resources, recover WIP, prove conformance, and fulfill the order. Its ten tracks extend that workflow into engineering, geometry, raw measurements, commercial documents, and factory economics. [Scope comparison →](docs/larkbench.md)

## Development

```bash
python -m pytest tests/test_otisbench.py tests/test_agent_boundary.py tests/test_shopfloor.py tests/test_campaign.py -q
python scripts/build_manifest.py --check
```

These commands check package identity, task contracts, action invariants, agent-input boundaries, and release fingerprints. Benchmark episodes and provider calls start only through explicit run commands.

Code: [Apache-2.0](LICENSE). Task content: [CC BY 4.0](DATA_LICENSE). [Methodology](docs/methodology.md) · [Attribution](NOTICE).
