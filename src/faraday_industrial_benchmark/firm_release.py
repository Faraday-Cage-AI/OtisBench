"""Joint planning with irreversible early releases, not hindsight per scenario."""

from copy import deepcopy
from itertools import product


def harden_firm_release(contents):
    coupling = contents["GRC"]["coupling"]
    coupling["firm_releases"] = {
        "order_ids": [coupling["customers"][i]["orders"][0] for i in (0, 2)],
        "rules": (
            "These orders cross the firming fence before the disruption is known. Choose a mode "
            "for EACH listed order in policy.firm_releases {order_id: mode}. Every scenario branch "
            "must use that same mode for these orders, including any decision to defer. Other orders "
            "may adapt after revelation. No hindsight changes or cancellation of firm releases. "
            "All kit, customer, capacity, labor, treasury, timing and emission constraints still apply. "
            "Jointly choose supplier reservations, firm releases, and recourse branches to minimize "
            "worst-case total cost, then aggregate scenario cost. Supplier fees remain counted once "
            "per scenario; early releases do not add another charge. This is a synthetic firming contract, "
            "not an emulation of every vendor's planning-time-fence exceptions."
        ),
    }
    contents["GRC"]["submission_schema"]["contingent_network_policy"]["firm_releases"] = (
        "{order_id: stock|standard|express|defer}; exactly the firm_releases.order_ids, "
        "common to every branch and committed before revelation"
    )


def solve_firm(case):
    from .contingent import MODES, choice, solve

    ids = case["coupling"]["firm_releases"]["order_ids"]
    orders = {row["order_id"]: row for row in case["orders"]}
    domains = [
        [
            m
            for m in MODES
            if all(choice(case, s, orders[oid], m) is not None for s in case["scenarios"])
        ]
        for oid in ids
    ]
    best, objective = None, None
    for modes in product(*domains):
        restricted = deepcopy(case)
        restricted["_firm_modes"] = dict(zip(ids, modes))
        try:
            candidate = solve(restricted)
        except ValueError as exc:
            if str(exc) != "no feasible contingent policy":
                raise
            continue
        key = candidate["worst_case_cost_cents"], sum(candidate["branch_costs_cents"].values())
        if objective is None or key < objective:
            best, objective = candidate, key
    if best is None:
        raise ValueError("no feasible firm-release policy")
    return best
