"""Deterministic synthetic AP recognition and cash-timing work sample."""


def convert(amount, rate):
    numerator, denominator = rate
    result = (2 * abs(amount) * numerator + denominator) // (2 * denominator)
    return result if amount >= 0 else -result


def reconcile_finance(contract):
    latest = {}
    for row in contract["documents"]:
        if row["status"] == "approved" and (
            row["document_id"] not in latest
            or row["revision"] > latest[row["document_id"]]["revision"]
        ):
            latest[row["document_id"]] = row
    recognized = {
        key
        for key, row in latest.items()
        if row["kind"] == "invoice" and row["service_period"] == contract["period"]
    }
    recognized |= {
        key
        for key, row in latest.items()
        if row["kind"] == "credit"
        and row["service_period"] == contract["period"]
        and row["parent_document_id"] in recognized
    }
    exclusions, ledger = [], []
    for row in contract["documents"]:
        if row["status"] != "approved":
            reason = "unapproved"
        elif latest[row["document_id"]]["row_id"] != row["row_id"]:
            reason = "superseded_revision"
        elif row["service_period"] != contract["period"]:
            reason = "outside_service_period"
        elif row["document_id"] not in recognized:
            reason = "unrecognized_parent"
        else:
            reason = None
        if reason:
            exclusions.append({"row_id": row["row_id"], "reason": reason})
        else:
            amount = convert(row["amount_minor"], contract["fx"][row["currency"]])
            ledger.append(
                {
                    "document_id": row["document_id"],
                    "revision": row["revision"],
                    "recognized_cents": -amount if row["kind"] == "credit" else amount,
                }
            )
    seen, paid, cash_exclusions = set(), 0, []
    for row in contract["payments"]:
        reason = None
        if row["event_id"] in seen:
            reason = "duplicate_payment"
        elif row["status"] != "settled":
            reason = "unsettled"
        elif row["settlement_day"] > contract["cash_cutoff_day"]:
            reason = "after_cash_cutoff"
        elif row["document_id"] not in recognized:
            reason = "unrecognized_document"
        seen.add(row["event_id"])
        if reason:
            cash_exclusions.append({"row_id": row["row_id"], "reason": reason})
        else:
            paid += convert(row["amount_minor"], contract["fx"][row["currency"]])
    expense = sum(row["recognized_cents"] for row in ledger)
    return {
        "ledger": sorted(ledger, key=lambda r: r["document_id"]),
        "exclusions": exclusions,
        "cash_exclusions": cash_exclusions,
        "expense_cents": expense,
        "settled_cash_cents": paid,
        "remaining_payable_cents": expense - paid,
    }


def generate_finance(rng, period):
    base = {
        "document_id": "INV-A",
        "revision": 1,
        "status": "approved",
        "kind": "invoice",
        "service_period": period,
        "currency": "EUR",
        "amount_minor": rng.randint(400001, 900009),
        "parent_document_id": None,
    }
    docs = [
        base,
        {**base, "revision": 2, "amount_minor": base["amount_minor"] + 100003},
        {**base, "revision": 3, "status": "draft", "amount_minor": 1},
        {**base, "document_id": "INV-B", "currency": "USD"},
        {**base, "document_id": "INV-OLD", "service_period": "prior-period"},
        {
            **base,
            "document_id": "CR-A",
            "kind": "credit",
            "parent_document_id": "INV-A",
            "amount_minor": 50003,
        },
        {**base, "document_id": "CR-ORPHAN", "kind": "credit", "parent_document_id": "INV-MISSING"},
    ]
    for i, row in enumerate(docs):
        row["row_id"] = f"AP-ROW-{i}"
    payment = {
        "event_id": "PAY-A",
        "document_id": "INV-A",
        "status": "settled",
        "settlement_day": 30,
        "currency": "EUR",
        "amount_minor": 100001,
    }
    payments = [
        payment,
        {**payment},
        {**payment, "event_id": "PAY-LATE", "settlement_day": 31},
        {**payment, "event_id": "PAY-PENDING", "status": "pending"},
    ]
    for i, row in enumerate(payments):
        row["row_id"] = f"PAY-ROW-{i}"
    return {
        "period": period,
        "documents": docs,
        "payments": payments,
        "fx": {"USD": [1, 1], "EUR": [rng.choice([107, 113, 119]), 100]},
        "cash_cutoff_day": 30,
        "rules": "These are incremental incident expenses NOT included in other reserve components. Select highest APPROVED revision per document (newer draft does not supersede approved). Recognize current service-period invoices; recognize current-period credits only against recognized parent invoices, regardless of parent source order. Exclusion precedence: unapproved, superseded_revision, outside_service_period, unrecognized_parent. Amounts are positive minor units; credits reverse sign. Convert EACH document using supplied rational FX, rounding half up to cents. Add net expense_cents / 100 to reserve; payments do NOT reduce expense. Cash: first event_id occurrence wins; exclude duplicates, unsettled, after_cash_cutoff, unrecognized_document in that order. Include settlement ON cutoff. Convert each included payment separately. remaining_payable_cents = expense_cents - settled_cash_cents (negative means prepaid, do not clamp). Emit finance_bridge {ledger sorted by document_id [{document_id,revision,recognized_cents}], exclusions and cash_exclusions in source order [{row_id,reason}], expense_cents, settled_cash_cents, remaining_payable_cents}.",
    }
