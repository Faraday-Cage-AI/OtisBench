"""Synthetic event-sourced subcontracting close; not a vendor implementation.

The public contract defines chronology, corrections, units and costing. Supplier
ownership, inspection stock and subsequent consumption adjustments are inspired
by SAP's subcontracting documentation. Posting conventions below are synthetic.
"""

from copy import deepcopy

RULES = (
    "Process events by ascending sequence, preserving input order for ties. Exclude "
    "events after cutoff first, then non-approved events, then duplicate event_id "
    "(first eligible occurrence wins). Rejected business events consume their event_id "
    "but change no balances. All quantities are integer base units after multiplying "
    "by the published uom multiplier. Only buyer-owned, released component lots can "
    "be consumed. A receipt consumes its declared component lines, creates its "
    "finished quantity, and accrues ONLY the subcontracting service. Round the entire "
    "foreign service amount times fx_numerator/fx_denominator half up to cents once. "
    "Receipt service and supplied-component cost are separate; do not accrue the "
    "components again. A correction's delta is an ABSOLUTE signed change from the "
    "original consumption for its document_id, receipt_id and lot_id, not incremental "
    "to its earlier revision. Only a higher approved revision replaces that document's "
    "prior delta; apply the difference atomically. Negative deltas restore components; "
    "positive deltas require eligible available stock. A correction cannot make any "
    "receipt's component consumption negative. Reversal restores all currently consumed "
    "components and reverses service accrual, creates no finished stock, and is allowed "
    "only before any shipment. No correction or shipment may target a reversed receipt. "
    "Quality events set the named component or finished receipt to released or inspection. "
    "Shipments need released finished stock and cannot exceed unshipped quantity. "
    "At cutoff, allocate each active receipt's FINAL total value to COGS as "
    "floor(total_value_cents * shipped / quantity); inventory gets the remainder. "
    "Thus late component corrections also recost earlier shipments. Inspection stock "
    "remains valued but unavailable. Output component and receipt rows sorted by ID, "
    "exclusions in processing order, and a balanced value bridge. Reversed receipts "
    "remain in the audit output with zero value and zero on-hand quantity. Corrections "
    "do not create finished goods. This is a separate subledger: only cogs_cents/100 "
    "enters the incident reserve; service_payable and inventory must not be added again. "
    "Released unshipped finished units cap PLANT-RECOVERY supply together with nominal "
    "MES capacity. This supply cap must flow through production, customer allocations, "
    "freight, shortfalls, reserve and executive brief."
)


def generate_subcontracting(rng):
    def event(n, kind, **fields):
        return {
            "record_id": f"SC-ROW-{n}",
            "event_id": f"SC-EVT-{n}",
            "sequence": n,
            "status": "approved",
            "kind": kind,
            **fields,
        }

    def receipt(n, rid, qty):
        return event(
            n,
            "receipt",
            receipt_id=rid,
            quantity=qty,
            service_foreign_cents=qty * rng.randint(180, 360),
            components=[
                {"lot_id": "COMP-A", "quantity": qty * 2, "uom": "each"},
                {"lot_id": "COMP-B", "quantity": qty, "uom": "each"},
            ],
        )

    events = [
        receipt(1, "SC-R1", rng.randint(18, 28)),
        event(2, "ship", receipt_id="SC-R1", quantity=rng.randint(4, 8)),
        event(
            3,
            "correction",
            receipt_id="SC-R1",
            lot_id="COMP-A",
            document_id="ADJ-A",
            revision=1,
            delta=1,
            uom="pack10",
        ),
        event(
            4,
            "correction",
            receipt_id="SC-R1",
            lot_id="COMP-A",
            document_id="ADJ-A",
            revision=2,
            delta=-rng.randint(1, 4),
            uom="each",
        ),
        receipt(5, "SC-R2", rng.randint(12, 18)),
        event(6, "quality", target_type="finished", target_id="SC-R2", quality="inspection"),
        receipt(7, "SC-R3", rng.randint(5, 8)),
        event(8, "reverse", receipt_id="SC-R3"),
    ]
    events += [
        {**deepcopy(events[3]), "record_id": "SC-DUP", "sequence": 9},
        {**deepcopy(events[2]), "record_id": "SC-STALE", "event_id": "SC-STALE", "sequence": 10},
        event(11, "ship", receipt_id="SC-R2", quantity=2),
        event(12, "reverse", receipt_id="SC-R1"),
        event(
            13,
            "correction",
            receipt_id="SC-R3",
            lot_id="COMP-A",
            document_id="ADJ-VOID",
            revision=1,
            delta=2,
            uom="each",
        ),
    ]
    for n, lot in ((14, "COMP-CONSIGNED"), (15, "COMP-INSPECTION")):
        bad = receipt(n, f"SC-INVALID-{n}", 3)
        bad["components"][1]["lot_id"] = lot
        events.append(bad)
    events += [
        {
            **deepcopy(events[3]),
            "record_id": "SC-DRAFT",
            "event_id": "SC-DRAFT",
            "sequence": 16,
            "revision": 3,
            "status": "draft",
            "delta": 25,
        },
        {
            **deepcopy(events[3]),
            "record_id": "SC-FUTURE",
            "event_id": "SC-FUTURE",
            "sequence": 60,
            "revision": 4,
            "delta": 30,
        },
    ]
    rng.shuffle(events)
    return {
        "cutoff": 50,
        "fx_numerator": rng.choice([3, 5, 7]),
        "fx_denominator": 4,
        "uom_multipliers": {"each": 1, "pack10": 10},
        "rules": RULES,
        "opening_lots": [
            {
                "lot_id": lid,
                "quantity": quantity,
                "unit_cents": rng.randint(80, 500),
                "owner": owner,
                "quality": quality,
            }
            for lid, quantity, owner, quality in (
                ("COMP-A", 200, "buyer", "released"),
                ("COMP-B", 100, "buyer", "released"),
                ("COMP-CONSIGNED", 100, "supplier", "released"),
                ("COMP-INSPECTION", 100, "buyer", "inspection"),
            )
        ],
        "events": events,
    }


def add_lifecycle_variant(contract, variant):
    """Different causal histories, rather than only different numeric amounts."""
    contract = deepcopy(contract)

    def event(n, kind, **fields):
        return {
            "record_id": f"LATE-ROW-{n}",
            "event_id": f"LATE-EVT-{n}",
            "sequence": n,
            "status": "approved",
            "kind": kind,
            **fields,
        }

    events = contract["events"]
    if variant == "quality_release":
        events += [
            event(17, "quality", target_type="finished", target_id="SC-R2", quality="released"),
            event(18, "ship", receipt_id="SC-R2", quantity=3),
        ]
    elif variant == "reversal_not_approved":
        next(e for e in events if e["sequence"] == 8)["status"] = "draft"
        events += [
            event(
                17,
                "correction",
                receipt_id="SC-R3",
                lot_id="COMP-A",
                document_id="ADJ-VOID",
                revision=2,
                delta=-1,
                uom="each",
            ),
            event(18, "ship", receipt_id="SC-R3", quantity=2),
        ]
    elif variant == "hold_release_retry":
        correction = {
            "receipt_id": "SC-R1",
            "lot_id": "COMP-A",
            "document_id": "ADJ-A",
            "revision": 3,
            "delta": 5,
            "uom": "each",
        }
        events += [
            event(17, "quality", target_type="component", target_id="COMP-A", quality="inspection"),
            event(18, "correction", **correction),
            event(19, "quality", target_type="component", target_id="COMP-A", quality="released"),
            event(20, "correction", **correction),
        ]
    elif variant == "reversal_after_correction":
        next(e for e in events if e["sequence"] == 8)["sequence"] = 19
        events += [
            event(
                18,
                "quality",
                target_type="component",
                target_id="COMP-INSPECTION",
                quality="released",
            ),
            event(
                20,
                "receipt",
                receipt_id="SC-R4",
                quantity=5,
                service_foreign_cents=1001,
                components=[
                    {"lot_id": "COMP-INSPECTION", "quantity": 5, "uom": "each"},
                    {"lot_id": "COMP-A", "quantity": 10, "uom": "each"},
                ],
            ),
        ]
    else:
        raise ValueError("unknown lifecycle variant")
    contract["lifecycle_variant"] = variant
    return contract


def contract_from_sections(sections):
    """Join current WMS balances, QMS statuses, SCM history and ERP valuation rules."""
    contract = deepcopy(sections["ERP-GL"]["reserve_policy"]["subcontract_contract"])
    quality = sections["QMS"]["subcontract_quality"]
    lots = sections["WMS"]["subcontract_stock"]
    if len({r["lot_id"] for r in lots}) != len(lots) or {r["lot_id"] for r in lots} != set(quality):
        raise ValueError("subcontract source keys do not reconcile")
    contract["opening_lots"] = [
        {**deepcopy(row), "quality": quality[row["lot_id"]]} for row in lots
    ]
    contract["events"] = deepcopy(sections["SCM"]["subcontract_events"])
    return contract


def _apply(state, event, contract):
    lots, receipts, revisions = state
    kind = event["kind"]
    if kind == "quality":
        collection = lots if event["target_type"] == "component" else receipts
        if event["target_id"] not in collection:
            raise ValueError("unknown_quality_target")
        if event["quality"] not in ("released", "inspection"):
            raise ValueError("invalid_quality_status")
        collection[event["target_id"]]["quality"] = event["quality"]
        return
    rid = event["receipt_id"]
    if kind == "receipt":
        if rid in receipts:
            raise ValueError("receipt_already_exists")
        consumed = {}
        for line in event["components"]:
            lid = line["lot_id"]
            amount = line["quantity"] * contract["uom_multipliers"][line["uom"]]
            if amount <= 0:
                raise ValueError("nonpositive_consumption")
            consumed[lid] = consumed.get(lid, 0) + amount
        if event["quantity"] <= 0:
            raise ValueError("nonpositive_receipt")
        for lid, amount in consumed.items():
            _withdraw(lots, lid, amount)
        n = event["service_foreign_cents"] * contract["fx_numerator"]
        d = contract["fx_denominator"]
        if n < 0 or d <= 0:
            raise ValueError("invalid_service_amount")
        receipts[rid] = {
            "quantity": event["quantity"],
            "shipped": 0,
            "quality": "released",
            "consumed": consumed,
            "service": (2 * n + d) // (2 * d),
            "reversed": False,
        }
        return
    if rid not in receipts:
        raise ValueError("unknown_receipt")
    receipt = receipts[rid]
    if receipt["reversed"]:
        raise ValueError("receipt_reversed")
    if kind == "correction":
        lid = event["lot_id"]
        if lid not in receipt["consumed"]:
            raise ValueError("component_not_on_receipt")
        key = event["document_id"]
        old = revisions.get(key)
        if old and (old["receipt_id"], old["lot_id"]) != (rid, lid):
            raise ValueError("correction_identity_changed")
        if old and event["revision"] <= old["revision"]:
            raise ValueError("stale_correction_revision")
        delta = event["delta"] * contract["uom_multipliers"][event["uom"]]
        change = delta - (old["delta"] if old else 0)
        if receipt["consumed"][lid] + change < 0:
            raise ValueError("negative_receipt_consumption")
        _withdraw(lots, lid, change)
        receipt["consumed"][lid] += change
        revisions[key] = {
            "receipt_id": rid,
            "lot_id": lid,
            "revision": event["revision"],
            "delta": delta,
        }
    elif kind == "ship":
        if receipt["quality"] != "released":
            raise ValueError("finished_stock_on_inspection")
        if not 0 < event["quantity"] <= receipt["quantity"] - receipt["shipped"]:
            raise ValueError("invalid_shipment_quantity")
        receipt["shipped"] += event["quantity"]
    elif kind == "reverse":
        if receipt["shipped"]:
            raise ValueError("cannot_reverse_shipped_receipt")
        for lid, amount in receipt["consumed"].items():
            lots[lid]["quantity"] += amount
        receipt["reversed"] = True
    else:
        raise ValueError("unknown_event_kind")


def _withdraw(lots, lid, amount):
    if lid not in lots:
        raise ValueError("unknown_component_lot")
    lot = lots[lid]
    if lot["owner"] != "buyer":
        raise ValueError("supplier_owned_component")
    if amount > 0 and lot["quality"] != "released":
        raise ValueError("component_on_inspection")
    if amount > lot["quantity"]:
        raise ValueError("component_shortage")
    lot["quantity"] -= amount


def reconcile_subcontracting(contract):
    lots = {row["lot_id"]: deepcopy(row) for row in contract["opening_lots"]}
    opening_value = sum(
        r["quantity"] * r["unit_cents"] for r in lots.values() if r["owner"] == "buyer"
    )
    state = (lots, {}, {})
    seen, exclusions = set(), []
    for event in sorted(contract["events"], key=lambda r: r["sequence"]):
        reason = None
        if event["sequence"] > contract["cutoff"]:
            reason = "after_cutoff"
        elif event["status"] != "approved":
            reason = "not_approved"
        elif event["event_id"] in seen:
            reason = "duplicate_event"
        else:
            seen.add(event["event_id"])
            candidate = deepcopy(state)
            try:
                _apply(candidate, event, contract)
            except ValueError as exc:
                reason = str(exc)
            else:
                state = candidate
        if reason:
            exclusions.append({"record_id": event["record_id"], "reason": reason})
    lots, receipts, _ = state
    component_rows = [
        {
            "lot_id": lid,
            "quantity": r["quantity"],
            "owned_value_cents": r["quantity"] * r["unit_cents"] if r["owner"] == "buyer" else 0,
            "eligible_quantity": r["quantity"]
            if r["owner"] == "buyer" and r["quality"] == "released"
            else 0,
        }
        for lid, r in sorted(lots.items())
    ]
    receipt_rows = []
    for rid, r in sorted(receipts.items()):
        component_value = (
            sum(lots[lid]["unit_cents"] * q for lid, q in r["consumed"].items())
            if not r["reversed"]
            else 0
        )
        payable = r["service"] if not r["reversed"] else 0
        total = component_value + payable
        cogs = total * r["shipped"] // r["quantity"]
        on_hand = r["quantity"] - r["shipped"] if not r["reversed"] else 0
        receipt_rows.append(
            {
                "receipt_id": rid,
                "reversed": r["reversed"],
                "on_hand": on_hand,
                "available_quantity": on_hand if r["quality"] == "released" else 0,
                "component_value_cents": component_value,
                "service_payable_cents": payable,
                "inventory_cents": total - cogs,
                "cogs_cents": cogs,
            }
        )
    result = {
        "components": component_rows,
        "receipts": receipt_rows,
        "exclusions": exclusions,
        "opening_owned_component_value_cents": opening_value,
        "closing_owned_component_value_cents": sum(r["owned_value_cents"] for r in component_rows),
        "finished_inventory_cents": sum(r["inventory_cents"] for r in receipt_rows),
        "cogs_cents": sum(r["cogs_cents"] for r in receipt_rows),
        "service_payable_cents": sum(r["service_payable_cents"] for r in receipt_rows),
        "available_finished_quantity": sum(r["available_quantity"] for r in receipt_rows),
    }
    assert (
        result["closing_owned_component_value_cents"]
        + result["finished_inventory_cents"]
        + result["cogs_cents"]
        == opening_value + result["service_payable_cents"]
    )
    return result
