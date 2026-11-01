# OtisBench benchmark card

OtisBench evaluates manufacturing problem solving through executable task environments and checked outputs. Version **1.4.1** includes ten outcome-scored tracks, twelve staged judgment workshops, and source-run advanced tiers.

## Task catalogs

| Track | Cases | Structure | Metric |
|---|---:|---|---|
| Campaign | 128 | 32 routes × 4 horizons; 12–96 orders | Strict campaign completion; mean order outcome; treasury reconciliation |
| Workflow | 1,024 | 32 routes × 16 disruptions × 2 draws | Strict completion; 0–100 outcome score; route/disruption breakdowns |
| Engineering | 84 | 42 families × 2 conditions | Exact-schema accuracy; numerical tolerances; family-macro success |
| Supply chain | 96 | 24 families × 4 conditions | Reconciliation, approval, posting, read-back; family-macro success |
| Procure to pay | 48 | 12 contracts × 4 draws | Physical/financial end state; contract-macro success |
| Sensors | 48 | 12 families × 4 conditions | Diagnosis, evidence, action, uncertainty; family-macro success |
| Documents | 32 | 8 contracts × 2 draws × 2 PDF modes | Decision and source-page evidence |
| CAD | 72 | 12 families × 3 modes × 2 draws | Solid validity, Boolean difference, datum and volume |
| Execution | 58 | 18 enterprise workflow families | Criteria, economics, timeliness, authorization |
| Factory seasons | 12 | 26 weekly decisions per season | Profit/demand margin, fill rate, cash and cost decomposition |

Advanced tiers: 64 temporal workflow variants, 48 material-network cases, and 128 replenishment cases. Catalog dimensions describe route, contract, evidence mode, and parameter variation separately. Track metrics retain their own units.

## Manufacturing judgment workshops

Twelve distinct workflows contain three decision rounds each. The participant commits a recommendation before the next fixed evidence update is revealed. The workshop tool checks submission structure and visible citation identifiers; it does not automatically assess the quality of a recommendation or execute proposed factory actions. Six rubric dimensions receive explicit reviewer ratings bound to the exact session. Report these separately from deterministic outcome scores. No reference plan or live rating is supplied to the participant. [Workshop interface and reviewer rubric](docs/manufacturing-judgment.md).

## Sustained production contract

Production campaigns keep 12, 24, 48, or 96 work orders in one persistent episode. The four profiles permit 2,880, 5,760, 11,520, or 23,040 manufacturing minutes and the same respective decision budgets. Equipment, personnel, fixtures, wear, qualifications, maintenance stock, supplier dispatch capacity, and cash are shared.

Supplier allocations lock 20% deposits and bind quantity, work order, dispatch window, and service level. Purchasing approvals bind the exact allocation. Cancellation fees and expired-deposit costs persist. Preventive service trades downtime, cash, and repair kits for temporary condition-trip coverage. Tool changes and repairs consume finite spares; replenishment requires packs, funds, and delivery time. Actual customer shipments generate delayed receivables. Each order retains its 240-call limit and manufacturing checks.

Strict success requires all orders, resolved supplier commitments, explicit campaign finish, financial and spare-inventory reconciliation, and the horizon. Per-decision journals and source-verified resume preserve ongoing plant state. [Campaign contract](docs/production-campaigns.md).

## Primary workflow contract

The goal is to fulfill customer orders with conforming, released, serialized product. Agents use ERP, PLM, MES, WMS, QMS, CMMS, personnel, and supplier tools. Reads and writes advance the clock. Production books resources, consumes reserved material, and creates WIP. Scheduled changes can invalidate evidence or interrupt work.

Each workflow permits at most 240 tool calls and 2,400 manufacturing minutes. The public startup payload contains an opaque task handle, neutral fulfillment goal, system list, limits, and tool contracts. The agent obtains business facts through tools, derives process settings, and submits its own actions. Reference calculations and grading metadata remain evaluator-side.

## Workflow score

| Outcome | Points |
|---|---:|
| Customer units shipped | 40, proportional to required quantity |
| Conforming quality release | 20 |
| Route completion | 10 |
| Serial genealogy | 10 |
| All customer orders on time and within budget | 10 |
| Current revision, required containment, and final evidence | 10 |

Strict success requires all checks. Critical authorization or product-release violations set the score to zero. Report mean outcome score, strict success, critical failures, route-macro success, and disruption breakdowns.

## Artifacts and reproducibility

Run artifacts retain submitted actions, tool results, event application, state hashes, and terminal checks. Agent-visible and evaluator traces are separate. Replay reconstructs transitions and compares terminal results. The release manifest fingerprints source, catalogs, authored documents, and CAD assets. A new source release receives new fingerprints; model reports should identify the commit, task selection, model, configuration, budgets, and artifacts used.

## Data and lineage

Workflow environments, commercial records, engineering problems, CAD parts, and document packets are authored task content. Optional hydraulic measurements and VisA photographs use the attributed upstream datasets listed in [NOTICE](NOTICE). ERP compatibility loads a pinned upstream catalog into evaluator caches. Internal Faraday Python namespaces and versioned transport names remain stable for integration compatibility.

The public repository includes task generators, evaluation code, tests, and example policies. Evaluation deployments should expose only the public agent contract and tool results to the agent, keeping evaluator code and artifacts in a separate process or environment. [Integration and isolation](docs/agent-isolation.md) describes the provided launcher.

## Track references

[Manufacturing](docs/manufacturing-workflows.md) · [Engineering and factory economics](docs/methodology.md) · [Supply chain](docs/supply-chain.md) · [Procure to pay](docs/procure-to-pay.md) · [Sensors](docs/sensors-and-time-series.md) · [Documents](docs/procurement-documents.md) · [CAD](docs/cad-and-drawings.md) · [Extensions](docs/extensions.md)
