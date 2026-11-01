"""Two-stage recovery work: reconcile evidence, buy options, then execute recourse.

Business validation accepts any feasible policy; the sealed grader separately
compares its worst-case cost to an exact dynamic-programming optimum. No solver
or optimal assignment is exposed through an agent tool.
"""

from __future__ import annotations

from copy import deepcopy
from itertools import product
from typing import Any

MODES = ("stock", "standard", "express", "defer")
ARTIFACT_TYPES = ("contingent_network_policy", "realized_recovery_ledger")


def reconcile(files: dict) -> dict:
    """Translate the public source records into the mathematical business case."""
    sections = {row["system"]: row["sections"] for row in files.values()}
    events = sections["WMS"]["movements"]
    quality = {r["lot_id"]: r["status"] for r in sections["QMS"]["lot_status"]}
    seen, balances, exceptions = set(), {}, []
    for row in events:
        reason = None
        if row["event_id"] in seen:
            reason = "duplicate_event"
        elif row["status"] == "reversed":
            reason = "reversed_movement"
        elif row["ownership"] != "owned":
            reason = "consigned_inventory"
        elif quality[row["lot_id"]] != "released":
            reason = "quality_hold"
        seen.add(row["event_id"])
        if reason:
            exceptions.append({"record_id": row["id"], "reason_code": reason})
        else:
            balances[row["lot_id"]] = balances.get(row["lot_id"], 0) + row["packs"]
    for row in sections["CRM"]["orders"]:
        if row["status"] == "cancelled":
            exceptions.append({"record_id": row["order_id"], "reason_code": "cancelled_order"})
    for row in sections["SCM"]["offers"]:
        if row["status"] != "confirmed":
            exceptions.append({"record_id": row["id"], "reason_code": "unconfirmed_capacity"})
    for row in sections["TMS"]["lanes"]:
        if row["status"] != "active":
            exceptions.append({"record_id": row["id"], "reason_code": "blocked_lane"})
    return {
        "case_id": sections["GRC"]["mandate"]["case_id"],
        "stock": sum(balances.values()),
        "exceptions": sorted(exceptions, key=lambda r: r["record_id"]),
        "orders": [r for r in sections["CRM"]["orders"] if r["status"] == "open"],
        "offers": {r["mode"]: r for r in sections["SCM"]["offers"] if r["status"] == "confirmed"},
        "lanes": {r["mode"]: r for r in sections["TMS"]["lanes"] if r["status"] == "active"},
        "scenarios": sections["RISK"]["scenarios"],
        "finance": sections["ERP"]["controls"],
        **({"coupling": sections["GRC"]["coupling"]} if "coupling" in sections["GRC"] else {}),
    }


def reservation_fee(case: dict, reservations: dict) -> int:
    return sum(
        case["offers"][mode]["tiers"][tier]["fee_cents"] for mode, tier in reservations.items()
    )


def capacities(case: dict, reservations: dict, scenario: dict) -> tuple[int, int, int]:
    return (
        max(0, case["stock"] - scenario["stock_loss_packs"]),
        max(
            0,
            case["offers"]["standard"]["tiers"][reservations["standard"]]["packs"]
            - scenario["standard_loss_packs"],
        ),
        max(
            0,
            case["offers"]["express"]["tiers"][reservations["express"]]["packs"]
            - scenario["express_loss_packs"],
        ),
    )


def choice(
    case: dict, scenario: dict, order: dict, mode: str
) -> tuple[int, tuple[int, int, int]] | None:
    """Return cost/resource use for one whole-order assignment; None is illegal."""
    fixed = case.get("_firm_modes", {})
    if order["order_id"] in fixed and fixed[order["order_id"]] != mode:
        return None
    quantity = order["packs"]
    if mode == "defer":
        if order["must_serve"]:
            return None
        return quantity * order["penalty_cents_per_pack"] * scenario["penalty_multiplier"], (
            0,
            0,
            0,
        )
    lane = case["lanes"].get(mode)
    if not lane or mode not in order["allowed_modes"] or mode in scenario["closed_modes"]:
        return None
    if lane["arrival_minute"] + scenario["delay_by_mode"].get(mode, 0) > order["due_minute"]:
        return None
    # FX is an exact rational, converted per complete order, rounded half up.
    numerator = quantity * lane["foreign_cents_per_pack"] * lane["fx_numerator"]
    denominator = lane["fx_denominator"]
    cents = (2 * numerator + denominator) // (2 * denominator)
    cents += lane["dispatch_fee_cents"]
    usage = tuple(quantity if index == MODES.index(mode) else 0 for index in range(3))
    return cents, usage


def branch_cost(
    case: dict, reservations: dict, scenario: dict, assignments: list
) -> tuple[int | None, str]:
    orders = {row["order_id"]: row for row in case["orders"]}
    if not isinstance(assignments, list) or len(assignments) != len(orders):
        return None, "one whole-order assignment is required for every active order"
    if any(not isinstance(r, dict) or set(r) != {"order_id", "mode"} for r in assignments):
        return None, "assignment fields must be order_id and mode"
    ids = [r["order_id"] for r in assignments]
    if (
        any(not isinstance(i, str) for i in ids)
        or set(ids) != set(orders)
        or len(set(ids)) != len(ids)
    ):
        return None, "order set mismatch or duplicate order"
    used = [0, 0, 0]
    total = reservation_fee(case, reservations)
    for row in assignments:
        mode = row["mode"]
        if not isinstance(mode, str) or mode not in MODES:
            return None, "unknown fulfillment mode"
        option = choice(case, scenario, orders[row["order_id"]], mode)
        if option is None:
            return (
                None,
                "assignment violates a service, qualification, lane, or due-date constraint",
            )
        cost, consumption = option
        total += cost
        used = [a + b for a, b in zip(used, consumption)]
    if any(a > b for a, b in zip(used, capacities(case, reservations, scenario))):
        return None, "shared capacity exceeded"
    emissions = sum(a * b for a, b in zip(used, case["finance"]["emissions_per_pack"]))
    if emissions > case["finance"]["emissions_cap"]:
        return None, "portfolio emissions cap exceeded"
    if case.get("coupling"):
        from .coupled import surcharge

        extra = surcharge(case, assignments, scenario)
        if extra is None:
            return None, "customer, kit, carrier, labor, or treasury contract violated"
        total += extra
    return total, "feasible"


def validate_policy(case: dict, policy: Any) -> dict:
    """Public business contract only: never returns the optimum or assignments."""
    invalid = lambda error: {"feasible": False, "error": error}
    if not isinstance(policy, dict):
        return invalid("policy must be an object")
    reservations = policy.get("reservations")
    if not isinstance(reservations, dict) or set(reservations) != {"standard", "express"}:
        return invalid("one common reservation decision is required for both suppliers")
    if any(type(t) is not int or t not in (0, 1, 2) for t in reservations.values()):
        return invalid("reservation tiers must be integers 0, 1, or 2")
    fee = reservation_fee(case, reservations)
    if fee > case["finance"]["reservation_budget_cents"]:
        return invalid("reservation cash budget exceeded")
    branches = policy.get("branches")
    ids = {r["id"] for r in case["scenarios"]}
    if not isinstance(branches, dict) or set(branches) != ids:
        return invalid("one contingent branch is required for each published scenario")
    costs = {}
    for scenario in case["scenarios"]:
        cost, detail = branch_cost(case, reservations, scenario, branches[scenario["id"]])
        if cost is None:
            return invalid(f"{scenario['id']}: {detail}")
        costs[scenario["id"]] = cost
    firm = case.get("coupling", {}).get("firm_releases")
    if firm:
        releases = policy.get("firm_releases")
        if not isinstance(releases, dict) or set(releases) != set(firm["order_ids"]):
            return invalid("firm_releases must contain exactly the disclosed early-release orders")
        if any(not isinstance(mode, str) or mode not in MODES for mode in releases.values()):
            return invalid("unknown firm-release mode")
        for rows in branches.values():
            by_id = {row["order_id"]: row["mode"] for row in rows}
            if any(by_id[oid] != mode for oid, mode in releases.items()):
                return invalid("firm releases cannot change between scenario branches")
    return {
        "feasible": True,
        "branch_costs_cents": costs,
        "worst_case_cost_cents": max(costs.values()),
        "reservation_fee_cents": fee,
    }


def solve_branch(case: dict, reservations: dict, scenario: dict) -> tuple[int, list] | None:
    """Exact DP, retaining cheapest prefix at every shared resource consumption."""
    if case.get("coupling"):
        from .coupled import solve_branch as solve_coupled

        return solve_coupled(case, reservations, scenario)
    limits = capacities(case, reservations, scenario)
    frontier = {(0, 0, 0): (0, [])}
    for order in case["orders"]:
        next_states = {}
        for used, (cost, assignments) in frontier.items():
            for mode in MODES:
                option = choice(case, scenario, order, mode)
                if option is None:
                    continue
                charge, consumption = option
                new = tuple(a + b for a, b in zip(used, consumption))
                if any(a > b for a, b in zip(new, limits)):
                    continue
                if (
                    sum(a * b for a, b in zip(new, case["finance"]["emissions_per_pack"]))
                    > case["finance"]["emissions_cap"]
                ):
                    continue
                if new not in next_states or cost + charge < next_states[new][0]:
                    next_states[new] = (
                        cost + charge,
                        assignments + [{"order_id": order["order_id"], "mode": mode}],
                    )
        frontier = next_states
    if not frontier:
        return None
    cost, rows = min(frontier.values(), key=lambda pair: pair[0])
    return cost + reservation_fee(case, reservations), rows


def solve(case: dict) -> dict:
    """Reference computation from visible inputs, accepting all optimum ties."""
    if case.get("coupling", {}).get("firm_releases") and "_firm_modes" not in case:
        from .firm_release import solve_firm

        return solve_firm(case)
    best = None
    best_objective = None
    for standard, express in product(range(3), repeat=2):
        reservations = {"standard": standard, "express": express}
        if reservation_fee(case, reservations) > case["finance"]["reservation_budget_cents"]:
            continue
        results = {s["id"]: solve_branch(case, reservations, s) for s in case["scenarios"]}
        if any(value is None for value in results.values()):
            continue
        worst = max(value[0] for value in results.values())
        objective = (
            worst,
            sum(value[0] for value in results.values()) if case.get("coupling") else 0,
        )
        if best_objective is None or objective < best_objective:
            best_objective = objective
            best = (
                worst,
                {
                    "reservations": reservations,
                    "branches": {key: value[1] for key, value in results.items()},
                },
            )
    if best is None:
        raise ValueError("no feasible contingent policy")
    policy = best[1]
    if "_firm_modes" in case:
        policy["firm_releases"] = dict(case["_firm_modes"])
    assessment = validate_policy(case, policy)
    policy.update(
        inventory_packs=case["stock"],
        exceptions=deepcopy(case["exceptions"]),
        branch_costs_cents=assessment["branch_costs_cents"],
        worst_case_cost_cents=best[0],
    )
    return policy


def assess(world) -> dict:
    record = world.state.get("network_commitment")
    if not record:
        return {"feasible": False}
    policy = world.state["structured_artifacts"][record["artifact_id"]]["content"]
    case = world.state["network_truth"]["case"]
    report = validate_policy(case, policy)
    report["reconciliation"] = (
        type(policy.get("inventory_packs")) is int and policy["inventory_packs"] == case["stock"]
    )
    rows = policy.get("exceptions", [])
    report["exceptions"] = (
        isinstance(rows, list)
        and all(isinstance(r, dict) and isinstance(r.get("record_id"), str) for r in rows)
        and sorted(rows, key=lambda r: r["record_id"]) == case["exceptions"]
    )
    if "annotated-decision-v2" in world.task.tags:
        from .decision_annotations import exception_values_match

        report["exceptions"] = exception_values_match(rows, case["exceptions"])
    report["cost_reporting"] = policy.get("branch_costs_cents") == report.get(
        "branch_costs_cents"
    ) and policy.get("worst_case_cost_cents") == report.get("worst_case_cost_cents")
    optimum = world.state["network_truth"]["optimum"]
    report["near_optimal"] = (
        report["feasible"] and report["worst_case_cost_cents"] * 100 <= optimum * 102
    )
    report["optimal"] = report["feasible"] and report["worst_case_cost_cents"] == optimum
    if case.get("coupling"):
        report["near_optimal"] = (
            report["optimal"]
            and sum(report["branch_costs_cents"].values())
            == world.state["network_truth"]["optimal_aggregate_cost"]
        )
    report["executed"] = world.state["incident"]["status"] == "recovered"
    return report


def apply_action(world, action: str, target: str, payload: dict) -> tuple[bool, str]:
    if target != world.state["incident"]["id"]:
        return False, "wrong_case"
    case = world.state["network_truth"]["case"]
    artifact = world.state["structured_artifacts"].get(payload.get("artifact_id"))
    if not artifact:
        return False, "artifact_required"
    if action == "reserve_network_capacity":
        if world.state.get("network_commitment"):
            return False, "reservation_already_committed"
        if world.minute > world.state["incident"].get("reservation_deadline", 60):
            return False, "reservation_window_closed"
        if artifact["artifact_type"] != ARTIFACT_TYPES[0]:
            return False, "policy_artifact_required"
        report = validate_policy(case, artifact["content"])
        if not report["feasible"]:
            return False, report["error"]
        required = {
            (f["id"], section, f["version"])
            for f in world.state["case_files"].values()
            if f["system"] != "LIVE"
            for section in f["sections"]
        }
        cited = {(r["file_id"], r["section_id"], r["version"]) for r in artifact["citations"]}
        if not required <= cited:
            return False, "current_source_citations_required"
        world.state["network_commitment"] = {
            "id": "NETWORK-RESERVATION",
            "artifact_id": artifact["id"],
            "minute": world.minute,
            "fee_cents": report["reservation_fee_cents"],
        }
        artifact["status"] = "committed"
        world.state["incident"]["status"] = "capacity_reserved"
        return True, "reserved"
    if world.state["incident"]["status"] == "recovered":
        return False, "recovery_already_executed"
    if not world.state.get("network_commitment"):
        return False, "reservation_required"
    live = next(f for f in world.state["case_files"].values() if f["system"] == "LIVE")
    scenario_id = live["sections"]["outcome"].get("scenario_id")
    if not scenario_id:
        return False, "outcome_not_revealed"
    if artifact["artifact_type"] != ARTIFACT_TYPES[1]:
        return False, "realized_ledger_required"
    commitment = world.state["network_commitment"]
    policy = world.state["structured_artifacts"][commitment["artifact_id"]]["content"]
    report = validate_policy(case, policy)
    cost = report["branch_costs_cents"][scenario_id]
    expected = {
        "scenario_id": scenario_id,
        "reservation_id": commitment["id"],
        "allocations": sorted(policy["branches"][scenario_id], key=lambda r: r["order_id"]),
        "reservation_fee_cents": commitment["fee_cents"],
        "operating_cost_cents": cost - commitment["fee_cents"],
        "total_cost_cents": cost,
        "debit_account": case["finance"]["debit_account"],
        "credit_account": case["finance"]["credit_account"],
    }
    content = deepcopy(artifact["content"])
    if isinstance(content.get("allocations"), list) and all(
        isinstance(r, dict) and isinstance(r.get("order_id"), str) for r in content["allocations"]
    ):
        content["allocations"].sort(key=lambda r: r["order_id"])
    if "public-decision-contract-v3" in world.task.tags:
        from .decision_contract import ledger_errors

        errors = ledger_errors(content, expected, world.state["incident"]["id"], commitment["artifact_id"])
        if errors:
            return False, "ledger_validation_failed: " + "; ".join(errors)
    elif content != expected:
        return False, "ledger_does_not_reconcile_with_committed_policy"
    if {"file_id": live["id"], "section_id": "outcome", "version": 2} not in artifact["citations"]:
        return False, "realized_outcome_citation_required"
    world.state["network_ledger"] = {"id": "NETWORK-LEDGER", **expected}
    world.state["incident"]["status"] = "recovered"
    artifact["status"] = "posted"
    return True, "recovered"


def build(task, rng):
    from .scenarios import ScenarioInstance, _base_state, _case_file, _criterion, _event

    case_id = f"NETWORK-{rng.randrange(100000, 999999)}"
    firm_track = "firm-release-v1" in task.tags
    reservation_deadline, reveal_minute = (180, 200) if firm_track else (60, 80)
    prefix = f"{case_id}-"
    stock = rng.randint(10, 16)
    movements = [
        {
            "id": prefix + "M1",
            "event_id": "receipt-A",
            "lot_id": "A",
            "packs": stock,
            "status": "posted",
            "ownership": "owned",
        },
        {
            "id": prefix + "M2",
            "event_id": "receipt-B",
            "lot_id": "B",
            "packs": 5,
            "status": "posted",
            "ownership": "owned",
        },
        {
            "id": prefix + "M3",
            "event_id": "receipt-C",
            "lot_id": "C",
            "packs": 7,
            "status": "reversed",
            "ownership": "owned",
        },
        {
            "id": prefix + "M4",
            "event_id": "receipt-D",
            "lot_id": "D",
            "packs": 6,
            "status": "posted",
            "ownership": "consigned",
        },
    ]
    if rng.choice((True, False)):
        movements.append({**movements[0], "id": prefix + "M5"})
    else:
        movements.append(
            {
                "id": prefix + "M5",
                "event_id": "dispatch-A",
                "lot_id": "A",
                "packs": -2,
                "status": "posted",
                "ownership": "owned",
            }
        )
    orders = [
        {
            "order_id": prefix + f"SO{i:02}",
            "packs": rng.randint(2, 4),
            "status": "open",
            "must_serve": i < 2,
            "allowed_modes": ["stock", "express"] if i == 0 else ["stock", "standard", "express"],
            "due_minute": rng.choice((135, 150, 175, 195)),
            "penalty_cents_per_pack": rng.randrange(20000, 80001, 5000),
        }
        for i in range(10)
    ]
    orders.append({**orders[-1], "order_id": prefix + "SO-CANCEL", "status": "cancelled"})
    rng.shuffle(orders)
    offers = [
        {
            "id": prefix + "SUP-A",
            "mode": "standard",
            "status": "confirmed",
            "tiers": [
                {"packs": 0, "fee_cents": 0},
                {"packs": 8, "fee_cents": rng.randrange(30000, 60001, 5000)},
                {"packs": 16, "fee_cents": rng.randrange(110000, 150001, 5000)},
            ],
        },
        {
            "id": prefix + "SUP-B",
            "mode": "express",
            "status": "confirmed",
            "tiers": [
                {"packs": 0, "fee_cents": 0},
                {"packs": 6, "fee_cents": rng.randrange(70000, 100001, 5000)},
                {"packs": 12, "fee_cents": rng.randrange(170000, 210001, 5000)},
            ],
        },
        {
            "id": prefix + "SUP-PROVISIONAL",
            "mode": "express",
            "status": "provisional",
            "tiers": [{"packs": 40, "fee_cents": 1000}],
        },
    ]
    lanes = [
        {
            "id": prefix + "LANE-STOCK",
            "mode": "stock",
            "status": "active",
            "arrival_minute": 105,
            "foreign_cents_per_pack": 1300,
            "fx_numerator": 1,
            "fx_denominator": 1,
            "dispatch_fee_cents": 500,
        },
        {
            "id": prefix + "LANE-STANDARD",
            "mode": "standard",
            "status": "active",
            "arrival_minute": 130,
            "foreign_cents_per_pack": rng.randrange(4000, 8001, 500),
            "fx_numerator": 109,
            "fx_denominator": 100,
            "dispatch_fee_cents": 1100,
        },
        {
            "id": prefix + "LANE-EXPRESS",
            "mode": "express",
            "status": "active",
            "arrival_minute": 110,
            "foreign_cents_per_pack": rng.randrange(12000, 18001, 500),
            "fx_numerator": 127,
            "fx_denominator": 100,
            "dispatch_fee_cents": 2300,
        },
        {
            "id": prefix + "LANE-CHEAP",
            "mode": "standard",
            "status": "customs_hold",
            "arrival_minute": 90,
            "foreign_cents_per_pack": 1,
            "fx_numerator": 1,
            "fx_denominator": 1,
            "dispatch_fee_cents": 0,
        },
    ]
    scenarios = [
        {
            "id": "normal",
            "stock_loss_packs": 0,
            "standard_loss_packs": 0,
            "express_loss_packs": 0,
            "delay_by_mode": {},
            "closed_modes": [],
            "penalty_multiplier": 1,
        },
        {
            "id": "port_delay",
            "stock_loss_packs": 0,
            "standard_loss_packs": 4,
            "express_loss_packs": 0,
            "delay_by_mode": {"standard": 35},
            "closed_modes": [],
            "penalty_multiplier": 2,
        },
        {
            "id": "quality_expansion",
            "stock_loss_packs": rng.randint(2, 4),
            "standard_loss_packs": 0,
            "express_loss_packs": 2,
            "delay_by_mode": {"express": 10},
            "closed_modes": [],
            "penalty_multiplier": 1,
        },
        {
            "id": "carrier_strike",
            "stock_loss_packs": 0,
            "standard_loss_packs": 0,
            "express_loss_packs": 0,
            "delay_by_mode": {},
            "closed_modes": [rng.choice(("standard", "express"))],
            "penalty_multiplier": rng.choice((1, 2)),
        },
    ]
    finance = {
        "reservation_budget_cents": 260000,
        "emissions_per_pack": [1, 3, 7],
        "emissions_cap": rng.randint(70, 90),
        "debit_account": "6100-recovery",
        "credit_account": "2100-accrual",
    }
    state = _base_state(
        task,
        {
            "id": case_id,
            "type": task.family,
            "status": "open",
            "summary": "Authorize a robust capacity reservation before uncertainty resolves; execute and reconcile the realized branch.",
            "reservation_deadline": reservation_deadline,
            "outcome_reveal_minute": reveal_minute,
            "notification_roles": ["supply_planning", "plant_controller", "customer_operations"],
        },
    )
    contents = {
        "GRC": {
            "mandate": {
                "case_id": case_id,
                "objective": "Minimize the maximum total cost across all four scenarios; strict success requires at most 2% above the exact optimum. Every scenario must be feasible. No probabilities are supplied. Reservation fees are paid once per realized scenario, not summed across mutually exclusive outcomes.",
                "timing": "Reserve by minute 60, before the minute-80 outcome. Execute that exact committed branch afterward. Orders and supplier terms are revised at minutes 5 and 10; read final versions before reserving.",
                "decision_freedom": "Any feasible assignment and any tie in the optimum is accepted. Allocation row order is immaterial.",
            },
            "submission_schema": {
                "contingent_network_policy": {
                    "reservations": "{standard: integer tier 0..2, express: integer tier 0..2}; common across every branch",
                    "branches": "{scenario_id: [{order_id, mode} for each active order exactly once]}; mode stock|standard|express|defer",
                    "inventory_packs": "reconciled eligible physical packs",
                    "exceptions": "[{record_id, reason_code}] for every excluded source row; no false positives",
                    "branch_costs_cents": "{scenario_id: integer total cost including one reservation fee}",
                    "worst_case_cost_cents": "maximum branch cost",
                },
                "realized_recovery_ledger": {
                    "scenario_id": "revealed scenario",
                    "reservation_id": "NETWORK-RESERVATION",
                    "allocations": "same assignments as committed branch",
                    "reservation_fee_cents": "committed fee",
                    "operating_cost_cents": "branch total minus reservation fee",
                    "total_cost_cents": "branch total",
                    "debit_account": "ERP account",
                    "credit_account": "ERP account",
                },
            },
            "evidence_rules": "Cite every pre-decision file section at its current version in the policy. Read back the policy. Cite the LIVE outcome version 2 in the realized ledger. Use reserve_network_capacity and execute_network_recovery with payload {artifact_id}. Both require approval. The grader scores the committed policy, never scattered drafts.",
        },
        "WMS": {
            "movements": movements,
            "rules": "Apply records in listed order. Keep first occurrence of event_id; discard later duplicates. Then exclude reversed movements, non-owned stock, and lots not QMS released, in that priority order. Sum signed packs of remaining movements. packs are already case-pack units; do not multiply by units per pack.",
        },
        "QMS": {
            "lot_status": [
                {"lot_id": lot, "status": "quarantine" if lot == "B" else "released"}
                for lot in "ABCD"
            ]
        },
        "CRM": {
            "orders": orders,
            "rules": "Exclude cancelled orders. Every open order is all-or-nothing from one mode. must_serve prohibits defer. Never split an order. Respect allowed_modes and due_minute. Penalty applies only to deferred packs, multiplied by the scenario penalty multiplier.",
        },
        "SCM": {
            "offers": offers,
            "rules": "Only confirmed offers confer capacity. Choose one tier per mode before uncertainty resolves, unchanged across scenarios. Each scenario subtracts its mode capacity loss, floored at zero. Unused reserved capacity has no refund.",
        },
        "TMS": {
            "lanes": lanes,
            "rules": "Only active lanes are usable. Add scenario delay; arrivals after the order due_minute are ineligible. A closed_mode has no capacity. Per shipped order: round-half-up(packs * foreign_cents_per_pack * fx_numerator / fx_denominator) + dispatch_fee_cents. All outputs are integer USD cents.",
        },
        "ERP": {
            "controls": finance,
            "rules": "Reservation cash budget applies only to tier fees. Total cost is tier fees plus shipment charges plus deferred-order penalties. Emissions use total shipped packs by mode; must satisfy cap in each branch. Ledger must debit and credit total cost once, including the already committed fee once.",
        },
        "RISK": {
            "scenarios": scenarios,
            "rules": "All four scenarios are plausible and mutually exclusive. A single reservation must cover a feasible contingent plan for each. Actual outcome is revealed later; no hindsight-based changes to reservations or branch assignments.",
        },
        "AUDIT": {
            "classification_rules": {
                "duplicate_event": "later repeated WMS event ID",
                "reversed_movement": "WMS status reversed",
                "consigned_inventory": "WMS ownership not owned",
                "quality_hold": "QMS lot status not released",
                "cancelled_order": "CRM order cancelled",
                "unconfirmed_capacity": "SCM offer not confirmed",
                "blocked_lane": "TMS lane not active",
            },
            "rules": "Identify actual exception rows from evidence. Use the first applicable WMS exclusion rule. Record id is the row id, or order_id for CRM. No fixed number of exceptions is promised.",
        },
        "LIVE": {"outcome": {"status": "pending", "reveal_minute": reveal_minute}},
    }
    if "coupled-frontier-v1" in task.tags:
        from .coupled import harden

        harden(contents, rng)
        if "long-tail-contracts-v1" in task.tags:
            from .long_tail import harden_long_tail

            harden_long_tail(contents, rng)
        if "cross-functional-v1" in task.tags:
            from .workforce import harden_workforce

            harden_workforce(contents, rng)
        if firm_track:
            from .firm_release import harden_firm_release

            harden_firm_release(contents)
            contents["GRC"]["mandate"]["timing"] = (
                "Reserve and firm releases by minute 180, before the minute-200 outcome. "
                "Execute that exact committed branch afterward. Orders and supplier terms are "
                "revised at minutes 5 and 10; read final versions before reserving."
            )
    if "annotated-decision-v2" in task.tags:
        contents["GRC"]["annotation_policy"] = {
            "exception_rows": "record_id and reason_code are required and graded exactly. Optional reason and notes strings and metadata object are allowed; other keys are rejected. Row order is immaterial, duplicates are not allowed.",
            "final_evidence": "Evidence entries may contain a bare record ID or explanatory text containing that exact existing ID as a separate token. Unique existing IDs count once; fragments and invented IDs never count.",
        }
    if "public-decision-contract-v3" in task.tags:
        from .decision_contract import artifact_schemas

        contents["GRC"]["structural_schemas"] = artifact_schemas()
        contents["GRC"]["evaluation_contract"] = {}
        contents["GRC"]["annotation_policy"]["ledger"] = (
            "Optional reason/notes strings, metadata/reconciliation objects are explanatory and ungraded. "
            "Optional case_id and policy_artifact_id or committed_policy_artifact_id must reference this "
            "case and the committed policy artifact. Required business values are exact. Allocation row "
            "order is immaterial; all committed orders, including deferred ones, must appear exactly once. "
            "Other fields are rejected at creation with field paths. Read structural_schemas."
        )
    files = {
        prefix + system: _case_file(prefix + system, system + " source extract", system, sections)
        for system, sections in contents.items()
    }
    # Revisions alter substance, not merely version counters.
    final_files = deepcopy(files)
    final_files[prefix + "CRM"]["version"] = 2
    final_files[prefix + "SCM"]["version"] = 2
    provisional_orders = files[prefix + "CRM"]["sections"]["orders"]
    provisional_orders[0]["penalty_cents_per_pack"] //= 2
    files[prefix + "SCM"]["sections"]["offers"][0]["tiers"][2]["fee_cents"] //= 2
    case = reconcile(final_files)
    optimum = solve(case)["worst_case_cost_cents"]
    realized = rng.choice(scenarios)["id"]
    state["case_files"] = files
    state["network_truth"] = {"case": case, "optimum": optimum}
    if case.get("coupling"):
        state["network_truth"]["optimal_aggregate_cost"] = sum(
            solve(case)["branch_costs_cents"].values()
        )
    state["network_artifact_types"] = list(ARTIFACT_TYPES)
    events = []
    for at, system in ((5, "CRM"), (10, "SCM")):
        events.append(
            _event(
                at,
                "case_file_update",
                prefix + system + "-REV",
                file_id=prefix + system,
                version=2,
                status="authoritative",
                sections=final_files[prefix + system]["sections"],
                sender=system,
                message="Final reviewed commercial terms now effective.",
            )
        )
    events.append(
        _event(
            reveal_minute,
            "case_file_update",
            prefix + "REALIZATION",
            file_id=prefix + "LIVE",
            version=2,
            status="authoritative",
            sections={"outcome": {"status": "confirmed", "scenario_id": realized}},
            sender="operations",
            message="Disruption outcome confirmed; execute committed recourse.",
        )
    )
    required_reads = [
        {"file_id": f["id"], "section_id": section, "version": f["version"]}
        for f in final_files.values()
        if f["system"] != "LIVE"
        for section in f["sections"]
    ]
    state["policies"]["approval_requirements"] = {
        "reserve_network_capacity": {
            "section_reads": required_reads,
            "tools": ["get_structured_artifact"],
        },
        "execute_network_recovery": {
            "section_reads": [{"file_id": prefix + "LIVE", "section_id": "outcome", "version": 2}],
            "executed_actions": [{"action": "reserve_network_capacity", "target": case_id}],
        },
    }
    criteria = [
        _criterion("source-" + str(i), "grounding", 1, "case_file_read", **r)
        for i, r in enumerate(required_reads)
    ]
    for key, dimension, weight in (
        ("feasible", "planning", 18),
        ("near_optimal", "optimization", 24),
        ("reconciliation", "accuracy", 8),
        ("exceptions", "exception_handling", 10),
        ("cost_reporting", "artifact_consistency", 8),
        ("executed", "containment", 18),
    ):
        criteria.append(_criterion(key, dimension, weight, "network_assessment", field=key))
    criteria.extend(
        [
            _criterion(
                "reserve-before-reveal",
                "governance",
                8,
                "executed_action",
                action="reserve_network_capacity",
                target=case_id,
            ),
            _criterion(
                "notify",
                "communication",
                4,
                "notification_roles",
                roles=state["incident"]["notification_roles"],
            ),
            _criterion("evidence", "communication", 4, "finish_record_evidence", minimum=5),
        ]
    )
    economics = {
        "unmitigated_cost": optimum / 100 + 100000,
        "best_known_cost": optimum / 100,
        "delay_cost_per_minute": 10,
        "target_minutes": 260 if firm_track else 120,
        "checks": [
            {"check": "network_assessment", "field": "near_optimal", "weight": 1},
            {"check": "network_assessment", "field": "executed", "weight": 1},
        ],
    }
    if "public-decision-contract-v3" in task.tags:
        from .decision_contract import public_scoring_contract

        state["case_files"][prefix + "GRC"]["sections"]["evaluation_contract"] = public_scoring_contract(task, criteria, economics)
        state["incident"]["finish_by_minute_for_full_credit"] = economics["target_minutes"]
    return ScenarioInstance(state, events, criteria, economics)


def run_oracle(tools):
    from .agents import _call

    incident = _call(tools, "get_incident")["incident"]
    _call(tools, "wait", minutes=10)
    files = {}
    for row in _call(tools, "list_case_files")["files"]:
        if row["system"] == "LIVE":
            live_id = row["id"]
            continue
        source = {**row, "sections": {}}
        for section in row["section_ids"]:
            result = _call(tools, "read_case_file", file_id=row["id"], section_id=section)
            source["sections"][section] = result["file"]["content"]
        files[row["id"]] = source
    case = reconcile(files)
    policy = solve(case)
    citations = [
        {"file_id": f["id"], "section_id": s, "version": f["version"]}
        for f in files.values()
        for s in f["sections"]
    ]
    artifact = _call(
        tools,
        "create_structured_artifact",
        artifact_type=ARTIFACT_TYPES[0],
        title="Contingent network policy",
        content=policy,
        citations=citations,
    )["artifact"]
    _call(tools, "get_structured_artifact", artifact_id=artifact["id"])
    approval = _call(
        tools,
        "request_approval",
        action="reserve_network_capacity",
        target=incident["id"],
        reason="Final sources reconciled; common reservation with feasible recourse in every scenario.",
        payload={"artifact_id": artifact["id"]},
    )["approval"]
    _call(
        tools,
        "execute_action",
        action="reserve_network_capacity",
        target=incident["id"],
        approval_id=approval["id"],
    )
    _call(tools, "wait", until_next_event=True)
    outcome = _call(tools, "read_case_file", file_id=live_id, section_id="outcome")["file"][
        "content"
    ]
    realized = outcome["scenario_id"]
    total = policy["branch_costs_cents"][realized]
    fee = reservation_fee(case, policy["reservations"])
    ledger = {
        "scenario_id": realized,
        "reservation_id": "NETWORK-RESERVATION",
        "allocations": policy["branches"][realized],
        "reservation_fee_cents": fee,
        "operating_cost_cents": total - fee,
        "total_cost_cents": total,
        "debit_account": case["finance"]["debit_account"],
        "credit_account": case["finance"]["credit_account"],
    }
    posted = _call(
        tools,
        "create_structured_artifact",
        artifact_type=ARTIFACT_TYPES[1],
        title="Realized cost and fulfillment ledger",
        content=ledger,
        citations=[{"file_id": live_id, "section_id": "outcome", "version": 2}],
    )["artifact"]
    approval = _call(
        tools,
        "request_approval",
        action="execute_network_recovery",
        target=incident["id"],
        reason="Reconcile realized branch with the locked reservation and exact accounting.",
        payload={"artifact_id": posted["id"]},
    )["approval"]
    _call(
        tools,
        "execute_action",
        action="execute_network_recovery",
        target=incident["id"],
        approval_id=approval["id"],
    )
    for role in incident["notification_roles"]:
        _call(
            tools,
            "notify",
            role=role,
            severity="warning",
            message=f"Recovered {incident['id']} using {realized}; total cost {total} cents.",
        )
    return _call(
        tools,
        "finish",
        summary="Committed common capacity before disclosure and executed its reconciled contingent outcome.",
        evidence=[
            incident["id"],
            artifact["id"],
            posted["id"],
            "NETWORK-RESERVATION",
            "NETWORK-LEDGER",
            approval["id"],
        ],
    )["final"]
