"""Synthetic intercompany expense-destination close, with explicit eliminations."""

from collections import defaultdict

RULES = (
    "All amounts are integer reporting-currency cents. Transfer prices are locked; "
    "late subcontracting consumption corrections change source cost, never transfer "
    "price or the receiving entity's payable. Active transfers for each source receipt "
    "must partition its source_shipped_quantity exactly. Allocate that receipt's final "
    "subcontract_bridge.receipts.cogs_cents to transfers sorted by transfer_id, using "
    "floor(cogs*quantity/source_shipped_quantity) except the last row receives the "
    "rounding remainder. Ignore cancelled transfer rows. Receipt events are processed "
    "by sequence with stable input order for ties. Exclusion priority: after_cutoff, "
    "not_approved, duplicate_event, inactive_transfer, wrong_receipt_channel, "
    "excess_receipt. Manual transfers accept physical events only; logical transfers "
    "accept logical events only. An eligible event_id is consumed even if rejected "
    "by a business rule; no rejection changes received quantity. Each accepted event "
    "must have positive quantity and cannot exceed the remaining transfer quantity. "
    "Receivers expense floor(locked_total_price*received/quantity); the remainder "
    "is their trade-in-transit asset. Group expense is floor(final_source_cost*received/quantity); "
    "the remainder is group trade-in-transit cost. Sender margin=locked price-source cost. "
    "Output signed-debit journal lines: sender IC-receivable +price, source-dispatch-cost "
    "-source_cost, intercompany-margin -(price-source_cost); receiver expense +price_expense, "
    "trade-in-transit +price_transit, IC-payable -price. Elimination entity CONSOL: "
    "IC-payable +price, IC-receivable -price, intercompany-margin +(price-source_cost), "
    "expense -(price_expense-group_expense), trade-in-transit -(price_transit-group_transit). "
    "Emit every line including zeros in this order, within transfers sorted by ID. "
    "Each entity's journal must balance. Internal balances and margin eliminate, and "
    "consolidated expense+transit equals source cost. These are transfer-layer journals, "
    "not additional vendor purchases or another subcontracting receipt. The base reserve "
    "already includes all subcontracting COGS: add reserve_reclassification_cents/100, "
    "which is NEGATIVE group transit cost. Do not add receiver transfer-price expense, "
    "intercompany payable or margin again. The remaining dispatches not listed here "
    "are outside this intercompany bridge. This disclosed allocation policy is synthetic."
)


def generate_intercompany(subcontract_contract, rng):
    shipped = next(
        e["quantity"]
        for e in subcontract_contract["events"]
        if e["kind"] == "ship" and e["receipt_id"] == "SC-R1"
    )
    transfers = [
        {
            "transfer_id": "IC-01",
            "source_receipt_id": "SC-R1",
            "source_shipped_quantity": shipped,
            "quantity": 1,
            "sender": "PLANT",
            "receiver": "SERVICE",
            "receipt_mode": "logical",
            "locked_unit_price_cents": rng.randint(450, 950),
            "status": "active",
        },
        {
            "transfer_id": "IC-02",
            "source_receipt_id": "SC-R1",
            "source_shipped_quantity": shipped,
            "quantity": shipped - 1,
            "sender": "PLANT",
            "receiver": "DISTRIBUTION",
            "receipt_mode": "manual",
            "locked_unit_price_cents": rng.randint(450, 950),
            "status": "active",
        },
    ]
    transfers.append({**transfers[0], "transfer_id": "IC-VOID", "status": "cancelled"})

    def receipt(n, tid, channel, qty, **overrides):
        return {
            "record_id": f"IC-ROW-{n}",
            "event_id": f"IC-EVT-{n}",
            "sequence": n,
            "status": "approved",
            "transfer_id": tid,
            "channel": channel,
            "quantity": qty,
            **overrides,
        }

    received = rng.randint(1, shipped - 2)
    events = [
        receipt(1, "IC-01", "logical", 1),
        receipt(2, "IC-02", "physical", received),
        receipt(3, "IC-01", "physical", 1),
        receipt(4, "IC-02", "logical", shipped - 1),
        receipt(5, "IC-VOID", "logical", 1),
        receipt(6, "IC-02", "physical", shipped),
        receipt(7, "IC-02", "physical", 1, status="draft"),
        receipt(60, "IC-02", "physical", shipped - 1 - received),
    ]
    events.append({**events[1], "record_id": "IC-DUP", "sequence": 8})
    rng.shuffle(events)
    return {"rules": RULES, "cutoff": 50, "transfers": transfers, "receipt_events": events}


def reconcile_intercompany(contract, subcontract_bridge):
    active = {r["transfer_id"]: r for r in contract["transfers"] if r["status"] == "active"}
    costs = {
        r["receipt_id"]: r["cogs_cents"]
        for r in subcontract_bridge["receipts"]
        if not r["reversed"]
    }
    groups = defaultdict(list)
    for tid, transfer in sorted(active.items()):
        groups[transfer["source_receipt_id"]].append(tid)
    allocated = {}
    for rid, ids in groups.items():
        quantity = active[ids[0]]["source_shipped_quantity"]
        if (
            quantity <= 0
            or any(
                active[tid]["source_shipped_quantity"] != quantity or active[tid]["quantity"] <= 0
                for tid in ids
            )
            or sum(active[tid]["quantity"] for tid in ids) != quantity
        ):
            raise ValueError("transfer quantities must partition source dispatches")
        remaining = costs[rid]
        for i, tid in enumerate(ids):
            amount = (
                remaining if i == len(ids) - 1 else costs[rid] * active[tid]["quantity"] // quantity
            )
            allocated[tid] = amount
            remaining -= amount
    received = dict.fromkeys(active, 0)
    seen, exclusions = set(), []
    for event in sorted(contract["receipt_events"], key=lambda row: row["sequence"]):
        tid, reason = event["transfer_id"], None
        if event["sequence"] > contract["cutoff"]:
            reason = "after_cutoff"
        elif event["status"] != "approved":
            reason = "not_approved"
        elif event["event_id"] in seen:
            reason = "duplicate_event"
        else:
            seen.add(event["event_id"])
            if tid not in active:
                reason = "inactive_transfer"
            elif event["channel"] != (
                "physical" if active[tid]["receipt_mode"] == "manual" else "logical"
            ):
                reason = "wrong_receipt_channel"
            elif not 0 < event["quantity"] <= active[tid]["quantity"] - received[tid]:
                reason = "excess_receipt"
            else:
                received[tid] += event["quantity"]
        if reason:
            exclusions.append({"record_id": event["record_id"], "reason": reason})
    rows, journals = [], []
    for tid, transfer in sorted(active.items()):
        qty, landed = transfer["quantity"], received[tid]
        price, cost = qty * transfer["locked_unit_price_cents"], allocated[tid]
        expense, group_expense = price * landed // qty, cost * landed // qty
        transit, group_transit = price - expense, cost - group_expense
        rows.append(
            {
                "transfer_id": tid,
                "received_quantity": landed,
                "in_transit_quantity": qty - landed,
                "locked_price_cents": price,
                "source_cost_cents": cost,
                "sender_margin_cents": price - cost,
                "receiver_expense_cents": expense,
                "receiver_transit_cents": transit,
                "group_expense_cents": group_expense,
                "group_transit_cents": group_transit,
            }
        )
        for entity, account, amount in [
            (transfer["sender"], "IC-receivable", price),
            (transfer["sender"], "source-dispatch-cost", -cost),
            (transfer["sender"], "intercompany-margin", cost - price),
            (transfer["receiver"], "expense", expense),
            (transfer["receiver"], "trade-in-transit", transit),
            (transfer["receiver"], "IC-payable", -price),
            ("CONSOL", "IC-payable", price),
            ("CONSOL", "IC-receivable", -price),
            ("CONSOL", "intercompany-margin", price - cost),
            ("CONSOL", "expense", group_expense - expense),
            ("CONSOL", "trade-in-transit", group_transit - transit),
        ]:
            journals.append(
                {
                    "transfer_id": tid,
                    "entity": entity,
                    "account": account,
                    "signed_debit_cents": amount,
                }
            )
    balances = defaultdict(int)
    for row in journals:
        balances[row["entity"]] += row["signed_debit_cents"]
    assert not any(balances.values())
    transit = sum(r["group_transit_cents"] for r in rows)
    return {
        "transfers": rows,
        "journal_lines": journals,
        "exclusions": exclusions,
        "group_transit_cents": transit,
        "group_expense_cents": sum(r["group_expense_cents"] for r in rows),
        "reserve_reclassification_cents": -transit,
    }
