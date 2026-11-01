# Long-running production campaigns

A production campaign keeps one plant running across many customer work orders. The agent process stays alive for the entire campaign. Orders share a clock, machine fleet, labor pool, inspection fixtures, tooling, and treasury.

## Catalog and duration

64 campaigns cover the existing 32 manufacturing routes under two operating profiles:

| Profile | Work orders | Manufacturing horizon | Agent decision budget |
|---|---:|---:|---:|
| Six shifts | 12 | 2,880 minutes | 2,880 calls |
| Twelve shifts | 24 | 5,760 minutes | 5,760 calls |

Work orders arrive roughly three manufacturing hours apart. Each has its own quantity, source evidence, drawing revision, production route, delivery window, allocation, approval records, quality state, and serial genealogy. Customer material and local document IDs are scoped to their work order; equipment, people, and fixtures are plant resources.

## Decisions with lasting consequences

- **Pipeline the plant.** Different route stages can run at the same time. Two orders cannot occupy the same machine, employee, or fixture during overlapping intervals.
- **Fund the next order.** Opening cash covers only part of the campaign budget. Production and procurement debit the shared treasury. Actual customer shipments create receivables that become cash 240 manufacturing minutes later.
- **Maintain equipment.** Every production start consumes shared tool life. Replacement restores a rated 120-unit tool capacity. Calibration validity and operator qualifications persist across orders.
- **Recover shared WIP.** A machine trip can interrupt another order's running operation. Rerouting preserves consumed material and clears only that order's bookings. Repair requires the interrupted work to be recovered first.
- **Reconcile new evidence.** Engineering releases, supplier dispositions, and condition events occur on order-specific schedules throughout the campaign. Later orders introduce fresh changes while earlier orders remain active.
- **Meet each customer window.** Waiting until all orders and changes have arrived misses the first order's deadline in every catalog configuration.

The eight order contracts cover compound recovery, material holds, engineering effectivity, failed inspection, split material, customer allocation, serial recall, and late inbound supply. The final order introduces compound recovery, keeping source changes and production recovery active late in the campaign.

## Agent contract

The first decision contains a neutral goal, campaign limits, campaign tools, and the manufacturing tool schemas. Begin with `read_campaign` to inspect the backlog, cash, receivables, and maintenance terms.

```json
{"tool":"read_campaign","arguments":{}}
```

Use the issued work-order handle to investigate and execute an order:

```json
{"tool":"act","arguments":{"work_order_id":"<issued handle>","action":"read","parameters":{"system":"ERP"}}}
```

`act` supports the manufacturing tools: read records, reserve material, seek action-bound approvals, purchase, calibrate, replace tools, execute operations, recover WIP, inspect, rework, release, ship, and finish with evidence. Root tools also provide `wait`, `repair_machine`, `renew_qualification`, and `finish_campaign`. Every attempted decision consumes time and the global call budget. Order actions also consume that order's 240-call budget.

Future orders expose their commercial backlog fields before release; their operational records become accessible at release. Agents receive business observations and their submitted results. Private event calendars, source seeds, scenario labels, expected controls, reference policies, state hashes, and live scores remain evaluator-side.

## Run and recover

```bash
otisbench list --track campaign
otisbench export-agent --task campaign-pump_assembly-twelve_shift --output agent-input.json

otisbench campaign --task campaign-pump_assembly-twelve_shift \
  --agent-command 'python /absolute/path/to/my_agent.py' \
  --output runs/pump-campaign.json

otisbench replay runs/pump-campaign.json
```

`--agent-file` selects the macOS offline standalone-Python boundary instead of an ordinary subprocess. The runner starts only the supplied agent; it has no default solution policy.

The runner writes an atomic checkpoint after every completed decision. Resume a stopped episode with:

```bash
otisbench campaign --task campaign-pump_assembly-twelve_shift \
  --agent-command 'python /absolute/path/to/my_agent.py' \
  --resume runs/pump-campaign.json --output runs/pump-campaign.json
```

Resume verifies source fingerprints, replays recorded transitions, and reconstructs plant state before continuing. The new agent process receives the public decision history, current time, and remaining budget. It does not receive the evaluator trace or terminal grade. `--stop-after N` limits newly executed decisions for a bounded integration check.

## Outcomes and replay

Strict campaign success requires every work order to pass its manufacturing checks, an explicit campaign finish, a valid financial ledger, and completion within the campaign horizon. The outcome score is the mean order score. A critical manufacturing violation or ledger failure sets the campaign score to zero. Reports also retain strict order completions, actual delivered units, elapsed time, action count, spending, cash, and outstanding receivables.

The financial check reconstructs cash from opening funds, production/procurement/maintenance debits, and collected shipment receivables. It reconciles each receivable's quantity-based amount, source shipment, payment date, and collection state. Replay checks both agent and evaluator traces, aliases, transitions, and terminal outcomes.
