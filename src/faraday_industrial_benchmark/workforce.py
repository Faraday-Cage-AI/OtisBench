"""Cross-functional shared labor and treasury controls for recovery workflows."""

from copy import deepcopy


def resource_limits(case, scenario):
    resources = case.get("coupling", {}).get("shared_resources", [])
    return tuple(
        r.get("scenario_limits", {}).get(scenario.get("id"), r["limit"]) for r in resources
    )


def resource_usage(case, assignments):
    resources = case.get("coupling", {}).get("shared_resources", [])
    return tuple(sum(r["per_order_by_mode"][a["mode"]] for a in assignments) for r in resources)


def harden_workforce(contents, rng):
    contract = contents["GRC"]["coupling"]
    scenarios = contents["RISK"]["scenarios"]
    scenarios.extend(
        [
            {**deepcopy(scenarios[-2]), "id": "port_quality_labor_absence"},
            {**deepcopy(scenarios[-1]), "id": "carrier_quality_cash_freeze"},
        ]
    )
    for group in contract["customers"]:
        overrides = group.setdefault("scenario_overrides", {})
        for base, compound in (
            ("compound_port_quality", "port_quality_labor_absence"),
            ("compound_carrier_quality", "carrier_quality_cash_freeze"),
        ):
            if base in overrides:
                overrides[compound] = deepcopy(overrides[base])
    for base, compound in (
        ("compound_port_quality", "port_quality_labor_absence"),
        ("compound_carrier_quality", "carrier_quality_cash_freeze"),
    ):
        contract["dispatch_overrides"][compound] = deepcopy(contract["dispatch_overrides"][base])
    contract["shared_resources"] = [
        {
            "id": "certified_release_labor",
            "unit": "certified release blocks",
            "limit": 16,
            "scenario_limits": {"port_quality_labor_absence": rng.randint(9, 11)},
            "per_order_by_mode": {"stock": 1, "standard": 2, "express": 1, "defer": 0},
            "reason": "Each released whole order needs a certified worker; standard inbound also needs receiving inspection. Absence reduces available blocks; unqualified overtime is prohibited.",
        },
        {
            "id": "treasury_prepayment",
            "unit": "100000 cents of ring-fenced working capital",
            "limit": 14,
            "scenario_limits": {"carrier_quality_cash_freeze": rng.randint(5, 7)},
            "per_order_by_mode": {"stock": 0, "standard": 1, "express": 2, "defer": 0},
            "reason": "Supplier/carrier deposits consume same-day liquidity. Payroll and tax reserves cannot be borrowed; later customer receipts cannot fund earlier dispatches.",
        },
    ]
    contract["rules"] += (
        " Shared resources are binding across ALL customers in each branch. Sum"
        " per_order_by_mode ONCE per whole order (not per pack). scenario_limits"
        " replaces the base limit only for that outcome. These are separate feasibility"
        " constraints, not added costs: deposits are recoverable and are NOT double"
        " counted in the objective. The published treasury pool is net of supplier"
        " reservation cash and protected payroll/tax reserves. No cross-scenario pooling."
    )
    contents["GRC"]["mandate"]["objective"] = contents["GRC"]["mandate"]["objective"].replace(
        "six", "eight"
    )
    contents["RISK"]["rules"] = contents["RISK"]["rules"].replace("six", "eight")
