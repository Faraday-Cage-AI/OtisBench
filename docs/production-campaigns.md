# Long-running production campaigns

A production campaign keeps one plant running across many customer work orders. The agent process stays alive for the entire campaign. Orders share a clock, machine fleet, labor pool, inspection fixtures, tooling, and treasury.

## Catalog and duration

128 campaigns cover the existing 32 manufacturing routes under four operating profiles:

| Profile | Work orders | Manufacturing horizon | Agent decision budget |
|---|---:|---:|---:|
| Six shifts | 12 | 2,880 minutes | 2,880 calls |
| Twelve shifts | 24 | 5,760 minutes | 5,760 calls |
| Extended production: 24 shifts | 48 | 11,520 minutes | 11,520 calls |
| Plant marathon: 48 shifts | 96 | 23,040 minutes | 23,040 calls |

Work orders arrive roughly three manufacturing hours apart in the shorter profiles and 3.6 hours apart in the extended profiles. Each has its own quantity, source evidence, drawing revision, production route, delivery window, allocation, approval records, quality state, and serial genealogy. Customer material and local document IDs are scoped to their work order; equipment, people, and fixtures are plant resources.

## Decisions with lasting consequences

- **Pipeline the plant.** Different route stages can run at the same time. Two orders cannot occupy the same machine, employee, or fixture during overlapping intervals.
- **Fund the next order.** Opening cash covers only part of the campaign budget. Production and procurement debit the shared treasury. Actual customer shipments create receivables that become cash 240 manufacturing minutes later.
- **Secure shared dispatch capacity.** Each 480-minute window has 48 supplier units for new bookings, including at most 24 expedited units. Book capacity for the intended order, quantity, and service level. Deposits lock 20% of material value.
- **Manage commercial commitments.** Purchases consume booked deposits once. Cancelling a booking costs 500 cents; unused bookings forfeit their deposits at window expiry. Future bookings compete with current production for cash.
- **Keep spares available.** Tool changes consume tooling kits, and repairs consume kits. Order stock in supplier packs with standard or expedited delivery; inbound stock becomes usable only when it arrives.
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

`act` supports the manufacturing tools: read records, reserve material, seek action-bound approvals, purchase, calibrate, replace tools, execute operations, recover WIP, inspect, rework, release, ship, and finish with evidence. Root tools also provide `reserve_supply`, `cancel_supply`, `order_spares`, `wait`, `repair_machine`, `renew_qualification`, and `finish_campaign`. Every attempted decision consumes time and the global call budget. Order actions also consume that order's 240-call budget.

Future orders expose their commercial backlog fields before release; their operational records become accessible at release. Agents receive business observations and their submitted results. Private event calendars, source seeds, scenario labels, expected controls, reference policies, state hashes, and live scores remain evaluator-side.

## Supplier and maintenance contracts

`read_campaign` publishes dispatch windows, existing allocations, spare inventory, inbound spare orders, prices, pack sizes, and lead times. A supply booking returns an opaque allocation handle. Include that handle as `allocation_id` in both the purchase approval payload and the subsequent `purchase` arguments. The evaluator checks the work order, units, service level, and exact authorization; it does not select a booking for the agent.

A purchase can commit a future dispatch window. Its receipt date is the later of purchase time and booked-window start, plus the supplier lead time. Used slots remain consumed for that window. Cancelling an unused booking frees capacity and refunds the deposit less the cancellation fee. A booking still unused at window end becomes an expired commitment and its deposit becomes cost.

Opening maintenance stock contains two tooling kits and one repair kit. Tooling-kit orders use packs of four at 1,200 cents per kit; kit orders use packs of two at 2,500 cents per kit. Standard delivery takes 180 minutes. Expedited delivery takes 60 minutes and adds 3,500 cents per order. Repair and tool-change labor charges remain separate.

## Run and recover

```bash
otisbench list --track campaign
otisbench export-agent --task campaign-pump_assembly-forty_eight_shift --output agent-input.json

otisbench campaign --task campaign-pump_assembly-forty_eight_shift \
  --agent-command 'python /absolute/path/to/my_agent.py' \
  --output runs/pump-campaign.json

otisbench replay runs/pump-campaign.json
```

`--agent-file` selects the macOS offline standalone-Python boundary instead of an ordinary subprocess. The runner starts only the supplied agent; it has no default solution policy.

The runner durably appends each completed decision to a journal, then compacts the history into an atomic JSON checkpoint when the process stops. Journal writes contain one new action rather than the whole episode history. An interrupted run can resume from the journal even before a full JSON checkpoint exists. Resume a stopped episode with:

```bash
otisbench campaign --task campaign-pump_assembly-forty_eight_shift \
  --agent-command 'python /absolute/path/to/my_agent.py' \
  --resume runs/pump-campaign.json --output runs/pump-campaign.json
```

Resume verifies source fingerprints, replays recorded transitions, and reconstructs plant state before continuing. The new agent process receives the public decision history, current time, and remaining budget. It does not receive the evaluator trace or terminal grade. `--stop-after N` limits newly executed decisions for a bounded integration check.

## Outcomes and replay

Strict campaign success requires every work order to pass its manufacturing checks, an explicit campaign finish, resolved supplier commitments, valid cash and spare-inventory ledgers, and completion within the campaign horizon. The outcome score is the mean order score. A critical manufacturing violation or ledger failure sets the campaign score to zero. Reports also retain strict order completions, actual delivered units, elapsed time, action count, spending, cash, prepaid supplier deposits, and outstanding receivables.

The financial check reconstructs cash from opening funds, production/procurement/maintenance debits, prepaid deposits, and collected shipment receivables. The stock check reconciles opening spares, actual receipts, ready inventory, and consumed maintenance stock. It reconciles each receivable's quantity-based amount, source shipment, payment date, and collection state. Replay checks both agent and evaluator traces, aliases, transitions, and terminal outcomes.
