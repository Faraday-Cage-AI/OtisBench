# Coupled procure-to-pay chains

This native track contains **48 synthetic episodes**: one procure-to-pay lifecycle
under **12 disruption contracts × 4 deterministic parameter draws**. It is separate
from the 96 single-decision supply-chain cases. Forty-eight episodes are not 48
independent business-rule families, and twelve contract labels do not establish
twelve complete ERP products.

## Agent work and actual state changes

The agent must choose a supplier and derive purchase quantity and cost from raw
quote emails, then execute an approved PO. The PO generates carrier deliveries,
material certificates and supplier invoices over simulated time. The agent must
receive physical quantities, inspect lots, reconcile invoices, resolve exceptions,
verify bank-change requests and settle invoices. A successful tool return alone
never establishes mission success.

The environment maintains linked records:

| System | Persisted state |
|---|---|
| ERP | Requisition, required grade, material deadline, budget, commitments, credits and cash paid |
| SCM | Supplier qualification/status, PO pack counts, selected price/revision, promised deliveries and reconciliation status |
| WMS | Receipt quantities by source delivery and lot, accepted inventory and quarantined inventory |
| QMS | Receipt/certificate inspections, accepted undamaged quantities and damaged/uncertified containment |
| AP | Original/corrected/duplicate document dispositions, approved liabilities, and one-time payment records |
| Treasury | Verified remittance accounts and independent callback outcomes for bank-change cases |

A receipt begins quarantined. Inspection can release only undamaged quantities
under a matching, released certificate. Reinspection does not duplicate inventory.
Short deliveries reduce physical stock and have a documented supplier credit;
damaged stock stays quarantined and may require an additional purchase. POs
consume quote allocation and budget. Payment changes cash and invoice status.
Every approved invoice must be paid exactly once; final system reads must match
the current SCM, WMS and AP records, not just earlier write responses.

## Raw documents

Supplier offers are email messages. Carrier manifests and supplier invoices are
CSV text. Certificates are plain text; bank requests are email. The engine does
not parse or insert a solution for the agent. The agent supplies pack quantities,
EA conversions, prices, receipt counts, dispositions and payment amounts/accounts.

Quote revisions can invalidate earlier document reads and approvals. Invoice
amount errors must be found by comparing the amount, PO and shortage credit:
public invoice documents contain no hidden discrepancy or expected-amount flags.
A corrected invoice has a real document revision; a duplicate copy shares the
original business invoice number. Purchase packs and receiving cases can have
different unit counts. An unverified bank request does not establish an account.

`read_document` returns raw content. Future deliveries/invoices are unavailable
until their issue time. Source identifiers are aliased throughout public records,
document bodies and action arguments. Startup excludes case seeds, contract
labels, parameter draws, future truth and reference answers. The evaluator saves
its private trace separately from the agent-visible trace.

These are deliberately bounded, fixed-format synthetic documents. They do not
establish scanned-document OCR, arbitrary-format extraction, authentic supplier
correspondence or multimodal CAD interpretation.

## Disruption contracts

| Contract | Consequence |
|---|---|
| Standard purchase | Select an eligible on-time offer, reconcile receipt and pay |
| Supplier suspension | A supplier becomes ineligible; do not use a cheap suspended source |
| Quote revision | A released revision changes price and invalidates old approval bindings |
| Partial delivery | Multiple arrivals must be received and inspected before AP approval |
| Certificate hold | Wait for released certification, quarantine damage and buy replacement material |
| Unit conversion | Order in 24-EA packs and receive manifests expressed in 6-EA cases |
| Quantity discount | Apply an all-units price tier to the actual pack quantity |
| Invoice variance | Detect an amount mismatch, hold it and reconcile a later correction |
| Duplicate invoice | Hold the copy without creating a duplicate liability or payment |
| Bank change | An independent callback either verifies a new account or rejects a fraudulent request |
| Short delivery | Reconcile a documented credit and buy missing supply |
| Compound recovery | Supplier restriction, changing quote, partial/short/damaged supply, certificate delay, invoice variance and bank-change case |

The first PO is exposed to the contract's initial delivery incident. Further POs
represent recovery purchases with their own capacity, price, delivery, invoices
and payments. The agent can choose legitimate operational alternatives; there
is no required hidden call sequence or prescribed supplier in the grader.

## Running and inspecting

```bash
otisbench list --track procurement
otisbench export-agent --task p2p-compound_recovery-001 --output runs/p2p-startup.json
otisbench export-procurement-documents --task p2p-compound_recovery-001 \
  --output-dir runs/p2p-initial-documents
otisbench procurement --task p2p-compound_recovery-001 \
  --agent-command 'python examples/procurement_agent.py' \
  --output runs/p2p-compound.json
otisbench replay runs/p2p-compound.json
```

The packet export is the initial minute-zero public document snapshot only.
It includes content hashes, not configuration, future deliveries, expected answers
or a solved plan. Later documents must be discovered during execution.

The agent uses persistent JSONL with `faraday-manufacturing/1`, track
`procurement`, and one `{tool, arguments}` reply per decision. Tool argument and
purchase/invoice/payment action contracts are supplied at startup. The episode
has 180 tool calls and 400 simulated minutes. The material deadline is a separate
business constraint: accepted stock must cover the requisition by that deadline;
financial reconciliation may complete afterward within the episode horizon.

A subprocess is a transport, not an isolation boundary. Keep evaluator code,
private traces and task files outside agent-accessible containers/filesystems.
No paid model calls are made by the example policy or qualification commands.

## Scoring and authorization

Strict success requires conforming stock, exact physical receipt counts, all POs
received/dispositioned, correct invoice amounts, held invoice exceptions, settled
payments, resolved bank-change cases, material timeliness, budget compliance,
current system read-backs, evidence-backed finish and no critical violation.

Partial score: 40 for accepted requirement coverage; 10 each for exact receiving,
conforming quality, completed receipt of all POs, reconciled invoices/exceptions,
settled payments, and finished/timely/budgeted/verified completion. A financially
wrong but authorized invoice can be posted; it cannot pass the final grader.

Approvals bind an immutable action and relevant source state. Changed quotes or
other binding state require a fresh proposal/approval. Authorization reuse,
suspended-source purchasing, certificate/lot mismatches, premature quality
release, duplicate receiving with a conflicting count, duplicate AP approvals,
duplicate payments and unverified payment accounts are critical violations and
set score to zero. Feasibility failures preserve money and inventory.

Report this track's contract-macro strict rate, per-contract scores, critical
failures, tool calls, time and physical/financial totals separately. Do not pool
it with factory profit, engineering accuracy or single-decision scores.
