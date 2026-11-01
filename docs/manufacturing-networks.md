# Manufacturing material networks

48 cases: 8 network families × 3 supply/resource conditions × 2 quantity draws.

## Executed structures

| Family | Material-flow semantics exercised |
|---|---|
| Serial chain | Three sequential transformations with unavailable work in progress |
| Parallel join | Separately purchased roots feed two branches; final assembly consumes both |
| Reconvergent fanout | Two branches compete for the same raw item, then join into one product |
| Nested assembly | A two-input subassembly joins a separately manufactured component |
| Shared subassembly | Two customer products compete for the same manufactured intermediate |
| Co-product | One batch produces two separately ordered outputs at the same completion event |
| Recycling loop | Two offcuts reclaim one raw unit; reclaimed material is required to satisfy demand under capped raw supply |
| Multiple sites | Intermediate stock must be explicitly transported between sites before finishing |

## Runtime contracts

The public configuration declares item mass in integer grams, SKU and site;
per-batch recipe inputs/outputs, duration, monetary cost, batch capacity and
resource; supplier price, lead time and quantity limits; customer demands, cash,
spend budget and due time. Conditions are baseline, limited cheap-source supply,
and a shared production resource. Draws change required quantities from one to
two, not underlying graph families.

Tools are `read_state`, `buy`, `start`, `wait`, `ship` and `finish`. Purchases spend
cash and create owned inbound inventory with an arrival time. Production consumes
ready inputs immediately, occupies a resource, and creates work in progress.
Only a later time advance makes outputs available. Co-products arrive together.
A transport preserves SKU, quantity and mass across two sites. Recycling consumes
real offcuts and has a finite batch capacity; it cannot create raw stock freely.

At each recorded step, the separate ledger recurrence verifies:

- Initial and purchased material mass equals ready stock plus owned inbound/WIP
  plus shipped mass; purchases awaiting arrival are not ready input stock.
- Initial cash equals remaining cash plus actual supplier/production debits.
- No negative stock, premature consumption, duplicate resource occupation,
  supplier-capacity excess or order over-shipment is accepted.
- Reconstructed clock, pending completions, stock, purchases, recipe usage and
  shipments equal the actual recorded state.

A commercially expensive purchase can be accepted with sufficient cash and
supplier capacity while still causing final budget failure. The runtime does
not prevent every bad business decision before it persists. Strict success
requires every order, deadline, spend budget, conservation check, termination and
empty pending-job queue; all other outcomes receive zero for this extension.

## Use the tier

The runtime and public configuration live in `scripts/manufacturing_networks.py`. The separate ledger recurrence lives in `scripts/network_ledger.py`; graph signatures are in `scripts/network_topology.py`. The standalone example policy consumes public configuration only.

```bash
python -m pytest tests/test_manufacturing_networks.py -q
python scripts/qualify_networks.py
python scripts/audit_networks.py
```

Qualification and audit generate their own reports and replay receipts. Keep generated artifacts with the source commit used to produce them.
