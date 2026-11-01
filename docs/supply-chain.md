# Procurement and supply-chain benchmark

This track contains **96 synthetic cases across 24 business-rule families**, with
four authored operating conditions per family. These are not 96 independently
validated real-world workflows. The cases add a procurement decision and posting
track alongside the manufacturing engine; their score is reported separately.
No actual supplier, customer, price, bank account or personal data is used.

## Coverage

| Area | Families |
|---|---|
| Strategic sourcing | Single-source award, constrained dual sourcing, FX/duty/freight landed cost, carbon-constrained award |
| Purchase management | MOQ/pack netting, all-units price breaks, blanket releases, PO amendments |
| Supply and network planning | Expedite recovery, interplant transfers, safety-stock replenishment, time-phased netting |
| Receiving and inventory | Accepted/quarantined/rejected receipt, shelf-life/FEFO allocation, blind-count adjustment |
| Payables and recovery | Three-way invoice matching, duplicate/conflicting invoices, freight claims, supplier returns |
| Traceability and logistics | Transitive supplier recall, transport mode selection, weight/volume container capacity |
| Supplier and engineering control | Order-level OTIF, alternate-part qualification/effectivity |

Conditions change feasibility, constraint binding, authorization scope, available
resources, or required action. Cases include no feasible award, insufficient
capacity, blocked suppliers, concentration limits, below-receipt PO reductions,
expired agreements, stock on hold, inadequate shelf life, overreceipts, missing
certificates, count disagreement, invoice price/quantity/freight exceptions,
conflicting invoice amounts, missed claims deadlines, and unavailable cold lanes.

The `variant == 2` condition in every family also has a pending source amendment.
It releases at minute 6, modifies an authoritative input, and invalidates all
older source reads. The new value is not sent before release. This is a bounded
late-evidence contract, not arbitrary real-time supplier messaging.

## What the agent does

1. Read facts from ERP, SCM, WMS, QMS, AP and TMS, as applicable.
2. Resolve pending SCM evidence and refresh stale sources.
3. Compute and submit its own structured action under the public business policy.
4. Request delegated approval tied to that exact proposal and source version.
5. Execute the proposal into the synthetic posting ledger.
6. Read the transaction back through a separate tool, then finish with its ID.

Approval grants permission; it does not confirm the answer. Syntactically valid
but commercially wrong actions can be posted and fail the grader. Neither the
approval nor execute operation calls the reference solver. Approval reuse and
wrong-proposal authorization attempts are critical violations. Prose alone,
read-only activity and unposted proposals earn zero completion credit.

The ledger persists the exact selected action, approval and source version. It
is **not a full ERP**: a posted award does not simulate supplier acceptance,
physical transport, bank settlement or subsequent factory production. The primary
manufacturing track supplies a deeper physical-consumption/production/shipment
simulation; this procurement track does not claim that depth for every family.

## Protocol and scoring

```
otisbench list --track supply-chain
otisbench export-agent --task supply-source_award-001 --output runs/supply-contract.json
otisbench supply-chain --task supply-source_award-001 \
  --agent-command 'python examples/supply_award_agent.py' \
  --output runs/supply-award.json
otisbench replay runs/supply-award.json
```

The persistent agent receives `faraday-manufacturing/1` JSONL decisions with
`track: "supply_chain"`. Return `{ "tool": "...", "arguments": {...} }` per line.
The example agent handles the explicitly selected static source-award example;
it is not a solver for the full suite. Each episode has a 40-call and 100-minute
budget. Listing and exporting do not run an agent or make paid model requests.

Startup contains goals, business policies, action-field types, system names and
budgets. It excludes raw cases, family labels, condition labels and answers.
Source facts arrive through read tools. Source/transaction handles are opaque
per episode and preserve the ordering needed by published tie-break contracts.
The runner never inserts answers or supplies live scores to the tested agent.
As with the manufacturing track, the JSONL process is not a filesystem sandbox.
Keep evaluator files outside any agent-accessible filesystem for credible runs.

Strict success requires all action fields to be correct, a posted transaction,
independent read-back, explicit finish and no critical violation. Correct fields
contribute 70 points; a fully correct action earns another 10 for posting, 10 for
read-back and 10 for finish. An incorrect action cannot earn these procedural
points. Critical violations set the episode score to zero. Report family-macro
strict success, field correctness, failures and per-domain breakdowns; do not pool
this score with factory profit or the engineering score.
