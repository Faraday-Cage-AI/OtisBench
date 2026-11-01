# Scoring and protocol

Each track uses its own output contract and metrics. Workflow scoring is defined in [the manufacturing guide](manufacturing-workflows.md); geometry in [CAD](cad-and-drawings.md); source evidence in [documents](procurement-documents.md); operational assessment in [sensors](sensors-and-time-series.md); business posting in [supply chain](supply-chain.md); and linked material/payment state in [procure to pay](procure-to-pay.md).

## Engineering

Each task publishes inputs, units, operating assumptions, required output fields,
and numerical tolerances. Reference calculations remain outside the agent payload.
Integer counts and money require exact numeric values, including equivalent JSON
numbers such as 11 and 11.0. Booleans require booleans;
strings, nulls, object keys, and ordered lists match exactly. Floating-point
results use absolute tolerance 1e-6 and relative tolerance 1e-5. NaN, infinity,
stringified numbers, missing fields, and extra fields cannot pass.

Strict success requires every requested field. Partial credit is the fraction
of correct output fields for an answer with the exact required object shape.
Family-macro strict success gives each manufacturing problem family equal weight.
Reports also break out domain and family performance. Two cases in a family
exercise different conditions; they contribute within that family's weight.

Optimization contracts include deterministic tie-breaks. Scheduling minimizes
weighted tardiness, then makespan, then job ID sequence. Blending minimizes cost
then the allocation vector. Energy dispatch minimizes total energy and peak
charges then start time. Cutting stock minimizes bar count, accounting for kerf.
The sheet-layout problem explicitly uses uniform grids with optional global
rotation. These operating assumptions appear in the corresponding task prompts.

## Manufacturing execution

A task starts with connected ERP, MES, QMS, inventory, engineering, or maintenance
records. Reads and actions advance time, and scheduled evidence can change.
The engine grades evidence discovery, exact entity scope, holds, plans, approvals,
execution, notifications, and final evidence. Protected actions require an approval
bound to the action and payload. A critical authorization violation sets score to
zero. Strict success requires all workflow criteria, completed finishing action,
full economics/timeliness credit, and no critical violation.

Task criteria account for 80 points, economics/timeliness for 10, and efficiency
for 10. Saved results contain per-criterion outcomes, calls, state hashes,
applied events, and a final answer. Replay reconstructs the state transitions
and compares terminal state and score.

## Factory season

A week follows this order:

1. Purchase material in supplier packs subject to available cash and weekly budget.
2. Receive due inbound orders.
3. Perform selected maintenance, consuming cash and machine time.
4. Process ordered jobs sequentially, consuming components, work-center time, and conversion cost.
5. Apply realized production yield, add customer demand, and ship oldest demand first.
6. Cancel sufficiently old backlog and charge remaining backlog and inventory holding costs.

Rejected orders do not partly consume inputs or conversion cost. Jobs must fit
every required center and all components. Good output is floor(starts * realized
yield); material and conversion cost apply to starts. Changeovers depend on the
last product run at each center, including the preceding week. A serviced mill
retains its restored-capacity window for four weeks.

Purchases debit cash immediately; receipts do not debit cash again. Sales credit
cash when shipped. Production debits conversion cost once. Starting equity is
cash plus raw stock and finished goods valued at standard manufacturing cost.
Terminal equity is cash plus recovery value of remaining raw stock, finished
goods, and paid inbound orders. Profit is terminal equity minus starting equity.
This captures production scrap and unsold purchases without double-counting COGS.
Backlog penalties are charged as incurred; unsold demand also stays in the
score denominator.

```
season score = 100 * profit / demand margin
suite score  = 100 * sum(profit) / sum(demand margin)
```

Demand margin is demand quantity times selling price minus standard manufacturing
cost. Scores can be negative or exceed 100. Reports retain raw profit, demand
margin, fill rate, cancelled/backlogged units, scrap, and each cash-cost category.
Engineering, execution, and season scores remain separate because they measure
different outcomes.

Run policies on identical case/draw pairs. The exogenous commitment hashes all
future demand, receipt-delay, and yield draws before the first decision. Agent
observations contain current records and observed history. The paired comparison
utility requires matching case/draw IDs, exogenous commitments, factory configurations, and rules, resamples entire factory
cases with their draws together, and reports a 95% percentile interval for the
score difference. Use at least two independent factory cases for this interval.

## Agent boundaries

Manufacturing execution uses the `faraday-industrial-jsonl/1` transport retained
by the execution engine. The external process receives public task fields without
the scenario seed. Tool results have the engine's explicit JSON contracts.
The process returns one final JSON answer and the runner closes its pipes.

Engineering agents receive the task JSON and return its required answer object.
The OpenAI adapter constructs a strict response schema from public field names
and input record IDs; it never derives that schema from reference answer values.
The adapter disables provider storage and automatic retries. Factory agents
receive `observe()` and return the four action fields `purchase_packs`, `expedite`,
`maintain`, and `jobs`.

Engineering and factory agents use a persistent JSONL process. For each decision,
the runner writes `{type: "decision", protocol: "faraday-manufacturing/1",
track: "engineering" | "factory", payload: {...}}`. The process replies with one
JSON answer object followed by a newline. Every decision has a wall-clock
timeout and a 100,000-byte reply cap. The process can retain its own memory
across factory weeks. Evaluation closes the process after the selected work.

## Release qualification and accounting reconstruction

Release 0.8.0 freezes the execution scoring fork
`manufacturing-execution/2-outcome-gated-efficiency`. An efficiency bonus requires
all workflow criteria plus a final answer. Discovery-only partial credit remains
possible. Older unmodified execution scores are not directly comparable.

The season verifier in `season_audit.py` separately reconstructs opening stock,
pack purchases, due receipts, routing/setup time, service windows, production
yield, shipments, backlog cancellation, cash costs and terminal recovery values.
It does not call simulator step, valuation, capacity or scoring methods. It uses
the same declared authored rules and committed draws, so this is independent code
reconstruction, not independently validated economic or physical ground truth.
The qualification runs idle, rule and notice-driven maintenance policies on all
12 factories with three paired draws. Cash, receipts, purchases, yields, shipments,
capacity and terminal-accounting corruptions must be detected.

The maintenance policy services the mill using its published future-capacity
notice and reserves the service cash/time before planning jobs. It has no access
to the committed future demand/yield/delay sequence. Policy scores and paired
case-cluster intervals are reported separately from replay/accounting validity.

`audit_release.py` validates source/receipt integrity and case coverage across all
nine native tracks plus the declared isolation controls. It does not rerun agents,
independently certify operational isolation, or
establish a comprehensive benchmark ranking. Hashes detect accidental drift and
receipt changes; they do not establish independent authorship or trusted signing.
