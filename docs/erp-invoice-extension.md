# Versioned public sales-invoice extension

The frozen `odoo-json2-business/1` gateway omits Odoo's sales-advance-payment wizard
and sales-order invoice links. A private upstream reference can create invoices
with its broader ORM access, so a passing reference alone cannot establish that
the public gateway supports those invoice workflows.

The separate `odoo-json2-business/2-invoices` script gateway adds regular, fixed-
deposit and percentage-deposit invoice creation and relevant invoice relationships.
It runs over validated existing fixtures through a separate worker/connection;
the version-1 gateway and frozen catalog campaign are not widened in place.
This extension requires the source checkout; the script interface is separate
from the default installed `mfg-erp` transport.

## Bounded business interface

Only `sale.advance.payment.inv` accepts context, and only the exact keys
`active_model='sale.order'` and `active_ids=[one positive order ID]`. Wizard creation
accepts one declared mode: delivered, percentage with amount, or fixed with
fixed_amount. Percentages and amounts are bounded finite numbers. The only
wizard business action is `create_invoices` for one wizard ID under that bounded
order context. Generic writes, deletion, arbitrary methods, company/user/default
context overrides, mail, configuration, credentials and server-code endpoints
remain excluded. Actual Odoo business validation and the task grader still apply;
the gateway never supplies a reference amount or accepts an invoice as correct
merely because its schema is valid.

Sales-order invoice IDs, invoice payment terms and invoice-line sales links can be
read to verify results. The Odoo wizard creates the genuine accounting links;
no host-side simulated invoice replaces it. API keys, private repair metadata,
verifiers and reference plans remain evaluator-side. Agent code is a staged
standard-library file behind the existing macOS filesystem/network boundary.
The agent is closed before verifier files are staged.

## Public development control

`examples/erp_invoice_agent.py` is a hand-coded control for three easy buy-only
invoice patterns. It reads product/customer/vendor/payment-term records and the
public prompt, selects a bounded single-supplier plan where feasible, then creates
and confirms sales/purchase orders. A PO's referenced demand must have enough
quantity and feasible commitment dates. A supplier MOQ can therefore require
linking more than just the final uncovered order. The parser accepts both
"1 unit" and plural "units".

The control sets sales/invoice payment terms, applies prompt deposit thresholds,
creates and posts linked invoices, and reads back posting/linkage. It is not a
general MRP optimizer or learned model. Unsupported single-supplier plans stop;
that outcome is retained rather than counted as solved. Original development
attempts exposed schedule, origin-capacity and singular-unit parsing errors and
are preserved under `runs/invoice-extension/`. Diagnostic feedback was used in
development; these are not blind/held-out policy results.

```sh
python scripts/erp_invoice_runner.py run \
  --snapshot runs/erp-catalog-v1/baselines/2008_easy_02_buy_only_immediate_invoicing \
  --agent-file examples/erp_invoice_agent.py --output runs/invoice-new-attempt.json
python scripts/erp_invoice_runner.py replay \
  --episode runs/invoice-new-attempt.json --output runs/invoice-new-replay
python scripts/qualify_erp_invoices.py
```

`run` refuses to overwrite an episode. Selected qualification requires all three
retained positive cases and exact fresh-fixture RPC/business/verifier replay.
Negative controls change a fixed deposit by one dollar (schema-valid, commercially
wrong) and attempt a forbidden context override after a correct business run
(permission violation). Those outcomes remain separate. The qualification command
fails if a required positive case is missing or incomplete. Until its report
passes, selection of three cases or successful unit tests alone does not establish
three-case runtime qualification.

Invoice posting here is actual **local synthetic Odoo accounting**. It is not
physical delivery, cash collection, bank payment, live customer work, a new native
case count, or full-catalog public-agent solvability. The unchanged upstream
verifier controls task success. Replay rejects differences rather than normalizing
dates; full wall-clock independence remains unestablished.
