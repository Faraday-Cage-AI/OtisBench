"""Synthetic insurance recognition contract, using integer cents throughout."""


def reconcile_claims(contract):
    seen = set()
    eligible = 0
    exclusions = []
    for row in contract["rows"]:
        reason = None
        if row["event_id"] in seen:
            reason = "duplicate_event"
        elif row["status"] == "reversed":
            reason = "reversed"
        elif row["status"] != "approved":
            reason = "unapproved"
        elif row["period"] != contract["period"]:
            reason = "outside_period"
        elif row["category"] not in contract["covered_categories"]:
            reason = "excluded_category"
        seen.add(row["event_id"])
        if reason:
            exclusions.append({"row_id": row["row_id"], "reason": reason})
        else:
            eligible += row["amount_cents"]
    after_deductible = max(0, eligible - contract["deductible_cents"])
    numerator = after_deductible * contract["participation_basis_points"]
    participated = (numerator + 5000) // 10000
    capped = min(participated, contract["remaining_limit_cents"])
    receivable = max(0, capped - contract["already_received_cents"])
    return {
        "eligible_cents": eligible,
        "after_deductible_cents": after_deductible,
        "participated_cents": participated,
        "capped_cents": capped,
        "already_received_cents": contract["already_received_cents"],
        "receivable_cents": receivable,
        "exclusions": exclusions,
    }


def generate_claims(rng, period):
    rows = []
    for i in range(9):
        rows.append(
            {
                "row_id": f"CLAIM-ROW-{i}",
                "event_id": f"LOSS-{i}",
                "amount_cents": rng.randrange(150000, 950001, 1000),
                "status": "approved",
                "period": period,
                "category": "property",
            }
        )
    rows[3]["status"] = "reversed"
    rows[4]["status"] = "pending"
    rows[5]["period"] = "prior-period"
    rows[6]["category"] = "customer_penalty"
    rows[8]["event_id"] = rows[0]["event_id"]
    return {
        "period": period,
        "rows": rows,
        "covered_categories": ["property"],
        "deductible_cents": rng.randrange(100000, 400001, 10000),
        "participation_basis_points": rng.choice([6500, 7500, 8500]),
        "remaining_limit_cents": rng.randrange(600000, 1800001, 100000),
        "already_received_cents": rng.randrange(100000, 500001, 10000),
        "rules": "Process source rows in order. First occurrence of an event_id wins, even if excluded. Exclusion precedence: duplicate_event, reversed, unapproved, outside_period, excluded_category. Sum approved, in-period covered losses. Subtract one aggregate deductible (floor zero), apply participation basis points rounded half up to integer cents, cap at remaining_limit_cents, then subtract already_received_cents (floor zero). Only the resulting receivable offsets the reserve. Do not subtract prior cash again. Emit insurance_bridge with eligible_cents, after_deductible_cents, participated_cents, capped_cents, already_received_cents, receivable_cents, and exclusions [{row_id,reason}] in source order.",
    }
