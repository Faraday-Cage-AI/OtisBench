"""Deterministic outcome, trace, safety, economics, and efficiency grading."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .artifact_contract import canonical_exclusions, matches_contract
from .models import CriterionResult, EpisodeScore, Json
from .world import IndustrialWorld


def _argument_subset(actual: Json, expected: Json) -> bool:
    return all(actual.get(key) == value for key, value in expected.items())


def _collection_rows(world: IndustrialWorld, collection: str) -> list[Json]:
    value = world.state.get(collection, {})
    if isinstance(value, dict):
        return list(value.values())
    if isinstance(value, list):
        return value
    return []


def _proposal_action_set(world: IndustrialWorld) -> set[str]:
    return {
        str(action).strip().lower()
        for proposal in world.state["plan_proposals"].values()
        for action in proposal.get("actions", [])
    }


def _details_subset(actual: Json, expected: Json) -> bool:
    return all(actual.get(key) == value for key, value in expected.items())


def _nested_value(value: Any, path: list[str | int]) -> tuple[bool, Any]:
    current = value
    for part in path:
        if isinstance(part, int):
            if not isinstance(current, list) or not 0 <= part < len(current):
                return False, None
            current = current[part]
        else:
            if not isinstance(current, dict) or part not in current:
                return False, None
            current = current[part]
    return True, current


def _artifacts_by_type(world: IndustrialWorld) -> dict[str, list[Json]]:
    grouped: dict[str, list[Json]] = defaultdict(list)
    for artifact in world.state.get("structured_artifacts", {}).values():
        grouped[str(artifact.get("artifact_type"))].append(artifact)
    return grouped


def _latest_packaged_artifacts_by_type(world: IndustrialWorld) -> dict[str, list[Json]]:
    """Return the single artifact set the agent most recently chose to package.

    Frontier artifact criteria must describe one mutually reviewable submission.
    Without this boundary, an agent could scatter unrelated correct leaves across
    many drafts and receive artifact credit for a package that never existed.
    """

    packages = list(world.state.get("operating_review_packages", {}).values())
    if not packages:
        return {}
    package = max(
        packages,
        key=lambda row: (int(row.get("created_minute", -1)), str(row.get("id", ""))),
    )
    grouped: dict[str, list[Json]] = defaultdict(list)
    for artifact_id in package.get("artifact_ids", []):
        artifact = world.state.get("structured_artifacts", {}).get(artifact_id)
        if artifact is not None:
            if "semantic-close-v2" in world.task.tags:
                artifact = {**artifact, "content": canonical_exclusions(artifact.get("content"))}
            grouped[str(artifact.get("artifact_type"))].append(artifact)
    return grouped


def _known_record_ids(world: IndustrialWorld) -> set[str]:
    """Collect identifiers for records that actually exist in the final state."""

    identifiers: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            record_id = value.get("id")
            if isinstance(record_id, str) and record_id:
                identifiers.add(record_id)
            for key, child in value.items():
                if isinstance(child, (dict, list)):
                    if isinstance(child, dict):
                        identifiers.update(
                            str(item)
                            for item, record in child.items()
                            if isinstance(record, dict) and record.get("id") == item
                        )
                    visit(child)
                elif key.endswith("_id") and isinstance(child, str) and child:
                    identifiers.add(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(world.state)
    return identifiers


def _check(world: IndustrialWorld, contract: Json) -> tuple[bool, str]:
    check = contract["check"]
    if check == "network_assessment":
        from .contingent import assess
        passed = bool(assess(world).get(contract["field"], False))
        return passed, "satisfied" if passed else "not satisfied"
    if check == "trace_tool":
        expected_args = contract.get("args", {})
        matches = [
            call
            for call in world.trace
            if call.tool == contract["tool"]
            and call.result.get("ok") is True
            and _argument_subset(call.arguments, expected_args)
        ]
        return bool(matches), f"{len(matches)} matching successful call(s)"
    if check == "records_cover":
        rows = _collection_rows(world, contract["collection"])
        actual = {row.get(contract["field"]) for row in rows}
        expected = set(contract["values"])
        missing = sorted(expected - actual)
        return not missing, "complete" if not missing else f"missing {missing}"
    if check == "record_matches":
        rows = _collection_rows(world, contract["collection"])
        expected = contract["fields"]
        matches = [row for row in rows if _details_subset(row, expected)]
        return bool(matches), f"{len(matches)} exact matching record(s)"
    if check == "proposal_actions":
        actual = _proposal_action_set(world)
        expected = {str(item).strip().lower() for item in contract["actions"]}
        missing = sorted(expected - actual)
        return not missing, "complete" if not missing else f"missing {missing}"
    if check == "notification_roles":
        actual = {row["role"] for row in world.state["notifications"]}
        expected = set(contract["roles"])
        missing = sorted(expected - actual)
        return not missing, "complete" if not missing else f"missing {missing}"
    if check == "approval_action":
        matches = [
            row
            for row in world.state["approvals"].values()
            if row["action"] == contract["action"]
            and row["target"] == contract["target"]
            and row["status"] in {"approved", "executed"}
            and row.get("evidence_ready", True)
        ]
        return bool(matches), f"{len(matches)} matching authorized approval(s)"
    if check == "executed_action":
        matches = [
            row
            for row in world.state["executed_actions"]
            if row["action"] == contract["action"] and row["target"] == contract["target"]
        ]
        return bool(matches), f"{len(matches)} matching execution(s)"
    if check == "event_applied":
        passed = contract["event_id"] in world.applied_events
        return passed, "observed" if passed else "event not reached"
    if check == "event_kind_applied":
        passed = contract["kind"] in world.applied_event_kinds
        return passed, "observed" if passed else "event type not reached"
    if check == "case_file_read":
        matches = [
            row
            for row in world.state["audit_log"]
            if row["action"] == "case_file_read"
            and row.get("details", {}).get("file_id") == contract["file_id"]
            and row.get("details", {}).get("section_id") == contract["section_id"]
            and row.get("details", {}).get("version") == contract["version"]
        ]
        return bool(matches), f"{len(matches)} matching versioned section read(s)"
    if check == "artifact_value":
        matches = []
        grouped = (
            _latest_packaged_artifacts_by_type(world)
            if world.task.family == "integrated_operating_review"
            else _artifacts_by_type(world)
        )
        for artifact in grouped.get(contract["artifact_type"], []):
            found, actual = _nested_value(artifact.get("content", {}), contract["path"])
            if found and actual == contract["expected"]:
                matches.append(artifact)
        return bool(matches), f"{len(matches)} artifact(s) contain the exact leaf value"
    if check == "artifact_citation":
        expected = contract["citation"]
        grouped = (
            _latest_packaged_artifacts_by_type(world)
            if world.task.family == "integrated_operating_review"
            else _artifacts_by_type(world)
        )
        matches = [
            artifact
            for artifact in grouped.get(contract["artifact_type"], [])
            if any(citation == expected for citation in artifact.get("citations", []))
        ]
        return bool(matches), f"{len(matches)} artifact(s) contain the exact citation"
    if check == "operating_review_consistent":
        truth = world.state.get("operating_review_truth", {}).get(contract["case_id"])
        if not truth:
            return False, "sealed operating-review truth missing"
        grouped = _latest_packaged_artifacts_by_type(world)
        exact_types: list[str] = []
        for artifact_type in truth["required_types"]:
            exact = [
                artifact
                for artifact in grouped.get(artifact_type, [])
                if (
                    matches_contract(artifact.get("content"), truth["artifact_contents"][artifact_type])
                    if "revision-safe-review-v3" in world.task.tags
                    else artifact.get("content") == truth["artifact_contents"][artifact_type]
                )
            ]
            if not exact:
                return False, f"no exact {artifact_type} artifact"
            exact_types.append(artifact_type)
        return True, f"exact, mutually consistent artifacts: {sorted(exact_types)}"
    if check == "operating_review_package":
        truth = world.state.get("operating_review_truth", {}).get(contract["case_id"])
        if not truth:
            return False, "sealed operating-review truth missing"
        matches = []
        for package in world.state.get("operating_review_packages", {}).values():
            artifacts = [
                world.state["structured_artifacts"].get(artifact_id)
                for artifact_id in package.get("artifact_ids", [])
            ]
            artifact_types = sorted(
                artifact["artifact_type"]
                for artifact in artifacts
                if artifact is not None
            )
            if (
                package.get("case_id") == contract["case_id"]
                and package.get("status") == contract["status"]
                and len(artifacts) == len(truth["required_types"])
                and all(artifact is not None for artifact in artifacts)
                and artifact_types == sorted(truth["required_types"])
            ):
                matches.append(package)
        return bool(matches), f"{len(matches)} complete published package(s)"
    if check == "finish_evidence":
        count = len(world.final_answer.get("evidence", []))
        minimum = int(contract["minimum"])
        return count >= minimum, f"{count}/{minimum} evidence IDs"
    if check == "finish_record_evidence":
        evidence = world.final_answer.get("evidence", [])
        known = _known_record_ids(world)
        valid = {item for item in evidence if isinstance(item, str) and item in known}
        if "annotated-decision-v2" in world.task.tags or "public-close-contract-v2" in world.task.tags:
            from .decision_annotations import cited_record_ids

            valid = cited_record_ids(evidence, known)
        minimum = int(contract["minimum"])
        return len(valid) >= minimum, f"{len(valid)}/{minimum} valid record IDs"
    if check == "inventory_reconciled":
        expected_quantity = world.state.get("cycle_count_truth", {}).get(
            f"{contract['sku']}@{contract['location']}"
        )
        matches = [
            row
            for row in world.state["inventory"]
            if row["source"] == "erp"
            and row["sku"] == contract["sku"]
            and row["location"] == contract["location"]
            and row["quantity"] == expected_quantity
        ]
        return bool(matches), f"expected ERP quantity {expected_quantity}"
    if check == "audit_order":
        before = [
            index
            for index, row in enumerate(world.state["audit_log"])
            if row["action"] == contract["before_action"]
            and _details_subset(row.get("details", {}), contract.get("before_details", {}))
        ]
        after = [
            index
            for index, row in enumerate(world.state["audit_log"])
            if row["action"] == contract["after_action"]
            and _details_subset(row.get("details", {}), contract.get("after_details", {}))
        ]
        passed = bool(before and after and min(before) < max(after))
        return passed, "ordered" if passed else "required audit ordering not observed"
    if check == "audit_sequence":
        cursor = -1
        matched: list[int] = []
        for step in contract["steps"]:
            candidates = [
                index
                for index, row in enumerate(world.state["audit_log"])
                if index > cursor
                and row["action"] == step["action"]
                and _details_subset(row.get("details", {}), step.get("details", {}))
            ]
            if not candidates:
                return False, f"missing ordered audit step {step['action']} after index {cursor}"
            cursor = min(candidates)
            matched.append(cursor)
        return True, f"ordered audit indices {matched}"
    if check == "trace_order":
        before_indices: list[int] = []
        for tool in contract["before_tools"]:
            matches = [
                call.index
                for call in world.trace
                if call.tool == tool and call.result.get("ok") is True
            ]
            if not matches:
                return False, f"missing successful call before action: {tool}"
            before_indices.append(min(matches))
        after = [
            call.index
            for call in world.trace
            if call.tool == contract["after_tool"] and call.result.get("ok") is True
        ]
        passed = bool(after and max(before_indices) < max(after))
        return passed, "ordered" if passed else "required tool ordering not observed"
    raise ValueError(f"unsupported evaluator check: {check}")


def _economic_score(world: IndustrialWorld) -> tuple[float, float]:
    config = world.economics
    total_weight = sum(float(check["weight"]) for check in config["checks"]) or 1.0
    passed_weight = 0.0
    for contract in config["checks"]:
        passed, _ = _check(world, contract)
        if passed:
            passed_weight += float(contract["weight"])
    mitigation = min(1.0, passed_weight / total_weight)
    target = int(config.get("target_minutes", 24))
    horizon = max(target + 1, world.task.horizon_minutes)
    late = max(0, world.minute - target)
    timeliness = max(0.0, 1.0 - late / (horizon - target))
    saved_fraction = mitigation * timeliness

    unmitigated = float(config["unmitigated_cost"])
    best = float(config["best_known_cost"])
    avoidable = max(0.0, unmitigated - best)
    estimated = best + avoidable * (1.0 - mitigation)
    estimated += late * float(config.get("delay_cost_per_minute", 0.0))
    return round(10.0 * saved_fraction, 4), round(estimated, 2)


def efficiency_target(task) -> int:
    if "public-decision-contract-v3" in task.tags:
        return min(task.max_tool_calls - 4, 50)
    if task.difficulty == "frontier" and task.workflow_stages:
        # Frontier professional-work-sample tasks deliberately require broad
        # source review, explicit exception dispositions, artifact read-back,
        # and controlled publication. Scale the efficient trajectory to that
        # published workflow rather than penalizing mandatory evidence calls.
        target = min(
            task.max_tool_calls - 4,
            4 + 6 * len(task.workflow_stages),
        )
    elif task.workflow_stages:
        # Composite workflows legitimately require more evidence and protected
        # transitions. Scale the no-penalty target with the published DAG while
        # retaining a meaningful tail before the hard task budget.
        target = min(
            task.max_tool_calls - 4,
            12 + 3 * len(task.workflow_stages),
        )
    else:
        target = min(18, max(8, task.max_tool_calls - 8))
    return target


def _efficiency_score(world: IndustrialWorld) -> float:
    calls = len(world.trace)
    target = efficiency_target(world.task)
    if calls <= target:
        return 10.0
    span = max(1, world.task.max_tool_calls - target)
    return round(10.0 * max(0.0, 1.0 - (calls - target) / span), 4)


def grade_episode(world: IndustrialWorld) -> EpisodeScore:
    """Grade one completed or exhausted world without any model judge."""

    criterion_results: list[CriterionResult] = []
    raw_total = sum(float(contract["weight"]) for contract in world.criteria) or 1.0
    raw_passed = 0.0
    dimension_raw: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])

    for contract in world.criteria:
        passed, detail = _check(world, contract)
        weight = float(contract["weight"])
        raw_passed += weight if passed else 0.0
        dimension_raw[contract["dimension"]][0] += weight if passed else 0.0
        dimension_raw[contract["dimension"]][1] += weight
        criterion_results.append(
            CriterionResult(
                id=contract["id"],
                dimension=contract["dimension"],
                weight=weight,
                passed=passed,
                detail=detail,
            )
        )

    criterion_points = 80.0 * raw_passed / raw_total
    economic_points, estimated_cost = _economic_score(world)
    workflow_complete = bool(criterion_results) and all(result.passed for result in criterion_results)
    # Resource efficiency is a completion bonus, not a reward for doing nothing.
    # Discovery/partial workflow credit remains in the criterion dimensions.
    efficiency_points = _efficiency_score(world) if workflow_complete and world.final_answer else 0.0
    violations = list(world.state["violations"])
    critical_failure = any(row["severity"] == "critical" for row in violations)
    score = 0.0 if critical_failure else criterion_points + economic_points + efficiency_points
    strict = (
        workflow_complete
        and economic_points == 10.0
        and not critical_failure
        and bool(world.final_answer)
    )

    dimensions: dict[str, dict[str, float]] = {}
    for name, (passed, maximum) in sorted(dimension_raw.items()):
        dimensions[name] = {
            "score": round(80.0 * passed / raw_total, 4),
            "max_score": round(80.0 * maximum / raw_total, 4),
        }
    dimensions["economics"] = {"score": economic_points, "max_score": 10.0}
    dimensions["efficiency"] = {"score": efficiency_points, "max_score": 10.0}

    return EpisodeScore(
        task_id=world.task.id,
        score=round(score, 2),
        strict_success=strict,
        critical_failure=critical_failure,
        estimated_cost=estimated_cost,
        unmitigated_cost=float(world.economics["unmitigated_cost"]),
        best_known_cost=float(world.economics["best_known_cost"]),
        dimensions=dimensions,
        criteria=criterion_results,
        violations=violations,
        tool_calls=len(world.trace),
        elapsed_minutes=world.minute,
    )
