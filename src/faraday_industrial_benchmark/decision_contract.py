"""Public scoring parameters, derived from the evaluator without answer values."""

from copy import deepcopy

ANNOTATIONS = {"reason", "notes", "metadata", "reconciliation"}


def artifact_schemas():
    text = {"type": "string"}
    integer = {"type": "integer"}
    free_object = {"type": "object", "additionalProperties": True}
    mode = {"type": "string", "enum": ["stock", "standard", "express", "defer"]}

    def obj(fields, optional=None):
        return {
            "type": "object",
            "required": list(fields),
            "properties": {
                **fields,
                "reason": text,
                "notes": text,
                "metadata": free_object,
                **(optional or {}),
            },
            "additionalProperties": False,
        }

    allocation = obj({"order_id": text, "mode": mode})
    allocations = {"type": "array", "items": allocation}
    policy_allocations = {
        "type": "array",
        "items": {
            "type": "object",
            "required": ["order_id", "mode"],
            "properties": {"order_id": text, "mode": mode},
            "additionalProperties": False,
        },
    }
    return {
        "contingent_network_policy": obj(
            {
                "reservations": {
                    "type": "object",
                    "required": ["standard", "express"],
                    "properties": {
                        key: {"type": "integer", "enum": [0, 1, 2]}
                        for key in ("standard", "express")
                    },
                    "additionalProperties": False,
                },
                "branches": {"type": "object", "additionalProperties": policy_allocations},
                "inventory_packs": integer,
                "exceptions": {
                    "type": "array",
                    "items": obj({"record_id": text, "reason_code": text}),
                },
                "branch_costs_cents": {"type": "object", "additionalProperties": integer},
                "worst_case_cost_cents": integer,
                "firm_releases": {"type": "object", "additionalProperties": mode},
            }
        ),
        "realized_recovery_ledger": obj(
            {
                "scenario_id": text,
                "reservation_id": text,
                "allocations": allocations,
                "reservation_fee_cents": integer,
                "operating_cost_cents": integer,
                "total_cost_cents": integer,
                "debit_account": text,
                "credit_account": text,
            },
            {
                "case_id": text,
                "policy_artifact_id": text,
                "committed_policy_artifact_id": text,
                "reconciliation": free_object,
            },
        ),
    }


def shape_errors(value, schema, path="content"):
    checks = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": type(value) is int,
    }
    kind = schema.get("type")
    if kind and not checks[kind]:
        return [f"{path}: expected {kind}"]
    if "enum" in schema and value not in schema["enum"]:
        return [f"{path}: unsupported enum value"]
    errors = []
    if kind == "object":
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}.{key}: required")
        for key, child in value.items():
            rule = properties.get(key, schema.get("additionalProperties", True))
            if rule is False:
                errors.append(f"{path}.{key}: unsupported field")
            elif isinstance(rule, dict):
                errors.extend(shape_errors(child, rule, f"{path}.{key}"))
    elif kind == "array":
        for index, child in enumerate(value):
            errors.extend(shape_errors(child, schema.get("items", {}), f"{path}[{index}]"))
    return errors


def strip_annotations(value):
    if isinstance(value, dict):
        return {
            key: strip_annotations(child) for key, child in value.items() if key not in ANNOTATIONS
        }
    if isinstance(value, list):
        return [strip_annotations(child) for child in value]
    return value


def ledger_errors(content, expected, case_id, policy_id):
    errors = shape_errors(content, artifact_schemas()["realized_recovery_ledger"])
    if errors:
        return errors
    actual = strip_annotations(content)
    for field, value in (
        ("case_id", case_id),
        ("policy_artifact_id", policy_id),
        ("committed_policy_artifact_id", policy_id),
    ):
        if field in actual and actual.pop(field) != value:
            errors.append(f"content.{field}: reference mismatch")
    wanted = strip_annotations(expected)
    actual["allocations"].sort(key=lambda row: row["order_id"])
    wanted["allocations"].sort(key=lambda row: row["order_id"])
    for field in wanted:
        if actual.get(field) != wanted[field]:
            errors.append(f"content.{field}: differs from committed recovery ledger")
    return errors


def public_scoring_contract(task, criteria, economics):
    from .grader import efficiency_target
    from .tool_specs import tool_specs_for_family
    from .world import READ_LATENCY_MINUTES, WRITE_LATENCY_MINUTES

    target = economics["target_minutes"]
    return {
        "criteria": deepcopy(criteria),
        "criterion_points": 80,
        "criterion_formula": "80 * sum(weights of passed criteria) / sum(all criterion weights)",
        "strict_success_requires": [
            "all listed criteria pass",
            "economic points equal 10",
            "no critical violation",
            "finish called with a final answer",
        ],
        "finish_by_minute_for_full_economic_credit": target,
        "hard_horizon_minutes": task.horizon_minutes,
        "economic_checks": deepcopy(economics["checks"]),
        "economic_points": 10,
        "mitigation_formula": "weighted fraction of economic_checks that pass",
        "late_formula": "max(0, final simulated minute - finish_by_minute_for_full_economic_credit)",
        "timeliness_denominator_minutes": max(target + 1, task.horizon_minutes) - target,
        "economic_formula": "round(10 * mitigation * max(0, 1 - late / timeliness_denominator_minutes), 4)",
        "delay_cost_per_minute_dollars": economics.get("delay_cost_per_minute", 0),
        "avoidable_penalty_dollars": max(
            0, economics["unmitigated_cost"] - economics["best_known_cost"]
        ),
        "cost_estimate_formula": "exact minimum worst-case cost in dollars + avoidable_penalty_dollars * (1 - mitigation) + late * delay_cost_per_minute_dollars; this synthetic estimate is not ROI",
        "efficiency_points": 10,
        "efficiency_no_penalty_tool_calls": efficiency_target(task),
        "maximum_tool_calls": task.max_tool_calls,
        "efficiency_formula": "10 at or below target; otherwise round(10 * max(0, 1 - (calls - target) / max(1, maximum_tool_calls - target)), 4)",
        "critical_violation_effect": "score zero; protected actions require the published approval gates",
        "tool_clock_costs": {
            spec["name"]: (
                "requested wait or next-event interval"
                if spec["name"] == "wait"
                else 0
                if spec["name"] == "finish"
                else READ_LATENCY_MINUTES
                if spec["name"].startswith(("get_", "list_", "query_", "trace_", "read_"))
                else WRITE_LATENCY_MINUTES
            )
            for spec in tool_specs_for_family(task.family)
        },
        "clock_note": "Clock advances after each non-wait/non-finish call, including rejected calls. Finish consumes zero minutes. API wall time does not advance simulated time.",
    }
