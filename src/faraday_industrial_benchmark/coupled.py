"""Coupled customer service contracts and exact resource-state optimization."""

from itertools import product


def group_charge(group, modes, scenario=None):
    group = {**group, **group.get("scenario_overrides", {}).get((scenario or {}).get("id"), {})}
    shipped = [mode for mode in modes if mode != "defer"]
    if any(mode in group.get("prohibited_modes", []) for mode in shipped):
        return None
    if len(shipped) < group["minimum_orders"]:
        return None
    # A paired installation kit must arrive together, or both components defer.
    if group["paired_first_two"] and modes[0] != modes[1]:
        return None
    deferred = len(modes) - len(shipped)
    return group["service_credit_cents"][deferred]


def terminal_charge(case, used, scenario=None):
    """Carrier minimum dispatch lots and emergency tariffs apply to total mode use."""
    from .contingent import MODES

    contract = case["coupling"]
    terms = contract.get("dispatch_overrides", {}).get((scenario or {}).get("id"), {})
    minimums = terms.get("minimum_packs", {})
    if any(0 < qty < minimums.get(mode, 0) for mode, qty in zip(MODES[:3], used)):
        return None
    fees = {**contract["activation_fees_cents"], **terms.get("activation_fees_cents", {})}
    return sum(fees[mode] for mode, qty in zip(MODES[:3], used) if qty)


def surcharge(case, assignments, scenario=None):
    from .workforce import resource_limits, resource_usage

    limits = resource_limits(case, scenario or {})
    consumption = resource_usage(case, assignments)
    if any(used > limit for used, limit in zip(consumption, limits)):
        return None
    by_id = {row["order_id"]: row["mode"] for row in assignments}
    total = 0
    for group in case["coupling"]["customers"]:
        charge = group_charge(group, [by_id[oid] for oid in group["orders"]], scenario)
        if charge is None:
            return None
        total += charge
    used = tuple(
        sum(o["packs"] for o in case["orders"] if by_id[o["order_id"]] == mode)
        for mode in ("stock", "standard", "express")
    )
    terminal = terminal_charge(case, used, scenario)
    return None if terminal is None else total + terminal


def solve_branch(case, reservations, scenario):
    from .contingent import MODES, capacities, choice, reservation_fee
    from .workforce import resource_limits, resource_usage

    limits = capacities(case, reservations, scenario) + resource_limits(case, scenario)
    orders = {row["order_id"]: row for row in case["orders"]}
    states = {(0,) * len(limits): (0, [])}
    for group in case["coupling"]["customers"]:
        options = {}
        for modes in product(MODES, repeat=len(group["orders"])):
            credit = group_charge(group, modes, scenario)
            if credit is None:
                continue
            choices = [
                choice(case, scenario, orders[oid], mode)
                for oid, mode in zip(group["orders"], modes)
            ]
            if any(option is None for option in choices):
                continue
            usage = tuple(sum(option[1][i] for option in choices) for i in range(3))
            assignments = [
                {"order_id": oid, "mode": mode} for oid, mode in zip(group["orders"], modes)
            ]
            usage += resource_usage(case, assignments)
            cost = credit + sum(option[0] for option in choices)
            if usage not in options or cost < options[usage][0]:
                options[usage] = (
                    cost,
                    assignments,
                )
        following = {}
        for used, (cost, rows) in states.items():
            for usage, (charge, assignments) in options.items():
                new = tuple(a + b for a, b in zip(used, usage))
                if any(a > b for a, b in zip(new, limits)):
                    continue
                if (
                    sum(a * b for a, b in zip(new, case["finance"]["emissions_per_pack"]))
                    > case["finance"]["emissions_cap"]
                ):
                    continue
                if new not in following or cost + charge < following[new][0]:
                    following[new] = cost + charge, rows + assignments
        states = following
    if not states:
        return None
    final = [
        (cost + terminal, rows)
        for used, (cost, rows) in states.items()
        if (terminal := terminal_charge(case, used, scenario)) is not None
    ]
    if not final:
        return None
    cost, rows = min(final, key=lambda item: item[0])
    return cost + reservation_fee(case, reservations), rows


def harden(contents, rng):
    """All extra constraints are disclosed in authoritative source sections."""
    orders = [r for r in contents["CRM"]["orders"] if r["status"] == "open"]
    # Keep source ordering scrambled: group membership is contractual, not positional.
    orders = sorted(orders, key=lambda row: row["order_id"])
    for index in (10, 11):
        orders.append(
            {
                **orders[-1],
                "order_id": orders[0]["order_id"][:-2] + str(index),
                "packs": rng.randint(2, 4),
                "must_serve": False,
                "penalty_cents_per_pack": rng.randrange(20000, 80001, 5000),
            }
        )
    contents["CRM"]["orders"].extend(orders[-2:])
    customers = []
    for i in range(4):
        customers.append(
            {
                "id": f"customer-{i}",
                "orders": [r["order_id"] for r in orders[i * 3 : i * 3 + 3]],
                "minimum_orders": 1,
                "paired_first_two": i in (0, 2),
                "service_credit_cents": [
                    0,
                    rng.randrange(40000, 90001, 5000),
                    rng.randrange(180000, 320001, 5000),
                    900000,
                ],
            }
        )
    contents["GRC"]["coupling"] = {
        "customers": customers,
        "activation_fees_cents": {
            "stock": 15000,
            "standard": rng.randrange(25000, 70001, 5000),
            "express": rng.randrange(70000, 140001, 5000),
        },
        "rules": "Each customer must receive minimum_orders in EVERY scenario. If paired_first_two, the first two listed orders must use exactly the same mode (including defer); they form an installation kit. Add the service credit indexed by the number of deferred orders ON TOP of individual deferral penalties. Add each used mode's activation fee ONCE per scenario, not per order. Minimize worst-case cost, then break ties by minimizing the sum of all scenario costs. Strict optimality is exact, with no regret allowance.",
    }
    contents["WMS"]["movements"][0]["packs"] += 8
    contents["ERP"]["controls"]["emissions_cap"] += 25
    scenarios = contents["RISK"]["scenarios"]
    scenarios.extend(
        [
            {
                "id": "compound_port_quality",
                "stock_loss_packs": 5,
                "standard_loss_packs": 4,
                "express_loss_packs": 2,
                "delay_by_mode": {"standard": 35},
                "closed_modes": [],
                "penalty_multiplier": 2,
            },
            {
                "id": "compound_carrier_quality",
                "stock_loss_packs": 4,
                "standard_loss_packs": 0,
                "express_loss_packs": 0,
                "delay_by_mode": {"express": 15},
                "closed_modes": ["standard"],
                "penalty_multiplier": 2,
            },
        ]
    )
    contents["GRC"]["mandate"]["objective"] = (
        "Minimize maximum cost over all six scenarios, then minimize the sum of scenario costs among worst-case ties. Strict success requires exact optimality for BOTH objectives. Follow the additional customer coupling contract."
    )
    contents["RISK"]["rules"] = (
        "All six scenarios are mutually exclusive. Commit one common reservation and six feasible contingent branches before revelation. Apply customer coupling, service credits and mode activation fees in every branch."
    )
