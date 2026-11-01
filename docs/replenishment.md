# Manufacturing replenishment

128 cases: 16 planning contracts × 8 deterministic draws.

The setting is a single plant building a kit from a motor and a controller.
Eight all-or-none quoted supply lots provide full or split awards. An agent must
select lots, receive exact manifest quantities, consume components in production,
ship the required kits, retain reserves and pay each invoice once. Final success
checks procurement constraints and the linked physical/financial end state.
Commercially bad awards can execute and still fail the final objective.

| Contract | Operational consequence |
|---|---|
| Lead time | Cheap lots cannot arrive before the production/shipping window |
| Supplier qualification | Unapproved supplier stock cannot satisfy production |
| Quality yield | Purchased units differ from usable component yield |
| Shelf life | Expiring components are ineligible for the specified production window |
| Destination | Stock quoted for a remote location cannot supply the plant |
| Shared capacity | A common vendor's allocation is shared across both components |
| Minimum order | Quoted quantities must satisfy supplier minimums |
| Pack multiple | Award quantity must be an exact package multiple |
| Dual source | Each component requires two distinct supplying vendors |
| Supplier concentration | Vendor shares are bounded across the combined award |
| Carbon cap | Quoted shipment emissions share one order-level allowance |
| Working capital | Combined upfront deposits must fit the available commitment limit |
| Landed cost | Currency conversion, freight and duties change the best award |
| Supplier disruption | A supplier becomes unavailable at the first observation epoch |
| Demand surge | The required kit quantity increases at that epoch |
| Safety stock | Purchasing only production demand leaves insufficient reserve stock |

## Execution and scoring

Agents select whole quoted lots, receive manifest quantities, consume components, ship kits, retain required reserves, and pay invoices exactly once. The public startup excludes future events, family labels, draw IDs, and reference answers. Source records change at the first observation epoch.

The action space contains eight all-or-none lots. The evaluator can enumerate all 256 subsets to check minimum-cost feasible awards. Strict business completion and award cost are separate outcomes. The example policy performs its own constraint and landed-cost calculations from public inputs.

```bash
python scripts/export_replenishment.py --output output/replenishment/public.zip
python -m pytest tests/test_replenishment.py -q
python scripts/qualify_replenishment.py run --output-dir runs/replenishment-new
python scripts/qualify_replenishment.py audit --report runs/replenishment-new/qualification.json
```

Exports contain public states and a manifest. Qualification uses fresh output directories and records replay receipts, exact-award checks, rule witnesses, and negative controls.
