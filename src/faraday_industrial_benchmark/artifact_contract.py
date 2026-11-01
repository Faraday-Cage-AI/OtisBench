"""Explicit structured-deliverable contracts, without exposing answer values."""

import json

ANNOTATION_FIELDS = {"id", "created_minute", "supersedes", "notes", "metadata"}


def canonical_exclusions(value, field=None):
    """Canonicalize unordered exclusion reports, never chronological event inputs.

    Retain multiplicity and all fields: duplicate, missing and incorrect records
    must still fail. Other arrays remain ordered under their existing contracts.
    """
    if isinstance(value, dict):
        return {key: canonical_exclusions(item, key) for key, item in value.items()}
    if isinstance(value, list):
        rows = [canonical_exclusions(item) for item in value]
        if field == "exclusions":
            return sorted(rows, key=lambda row: json.dumps(row, sort_keys=True, separators=(",", ":")))
        return rows
    return value


def public_review_scoring(task, criteria, economics):
    """Publish grading parameters but never solved leaf values or resolution answers."""
    from .decision_contract import public_scoring_contract

    metadata = [
        {
            key: criterion[key]
            for key in ("id", "dimension", "weight", "check", "minimum")
            if key in criterion
        }
        for criterion in criteria
    ]
    public = public_scoring_contract(task, metadata, economics)
    public["cost_estimate_formula"] = (
        "reference reserve + avoidable_penalty_dollars * (1 - mitigation) + late * "
        "delay_cost_per_minute_dollars, rounded to 2 decimals; synthetic estimate, not actual loss or ROI"
    )
    public["criterion_interpretation"] = (
        "Artifact leaf criteria require exact business values derived from the public sources and "
        "schemas; documented annotations are ignored. The complete published package must be "
        "mutually consistent and satisfy every business contract. Reading, source revisions, "
        "exception resolutions, citations, approval, publication and notifications are graded "
        "as named. Criterion metadata intentionally omits solved values."
    )
    public["final_evidence_rule"] = (
        "Supply at least 18 unique existing record IDs. Bare IDs or explanatory strings containing "
        "an exact ID as a separate token are accepted. Invented, partial and duplicate IDs do not count."
    )
    return public


def matches_contract(actual, expected):
    if isinstance(expected, dict):
        return (
            isinstance(actual, dict)
            and set(expected) <= set(actual)
            and set(actual) - set(expected) <= ANNOTATION_FIELDS
            and all(matches_contract(actual[key], value) for key, value in expected.items())
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(matches_contract(a, e) for a, e in zip(actual, expected))
        )
    return actual == expected and not (
        isinstance(actual, bool) != isinstance(expected, bool)
        and isinstance(actual, (bool, int, float))
        and isinstance(expected, (bool, int, float))
    )


def structural_schema(value, field=None):
    if field == "latest_arrival_minute":
        return {"type": ["integer", "null"]}
    if isinstance(value, dict):
        return {
            "type": "object",
            "required": list(value),
            "properties": {key: structural_schema(item, key) for key, item in value.items()},
        }
    if isinstance(value, list):
        return {"type": "array", "items": structural_schema(value[0]) if value else {}}
    if value is None:
        return {"type": ["integer", "null"]}
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, (int, float)):
        return {"type": "number"}
    return {"type": "string"}


def schema_errors(value, schema, path="content"):
    """Validate only the disclosed shape, never sealed business-answer values."""
    kinds = schema.get("type", [])
    kinds = [kinds] if isinstance(kinds, str) else kinds
    checks = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "string": isinstance(value, str),
        "null": value is None,
    }
    if kinds and not any(checks.get(kind, False) for kind in kinds):
        return [f"{path}: expected {' or '.join(kinds)}"]
    errors = []
    if schema.get("type") == "object":
        properties = schema.get("properties", {})
        errors += [
            f"{path}.{key}: required" for key in schema.get("required", []) if key not in value
        ]
        errors += [
            f"{path}.{key}: unsupported field"
            for key in sorted(set(value) - set(properties) - ANNOTATION_FIELDS)
        ]
        for key in properties.keys() & value.keys():
            errors.extend(schema_errors(value[key], properties[key], f"{path}.{key}"))
    elif schema.get("type") == "array":
        for index, item in enumerate(value):
            errors.extend(schema_errors(item, schema.get("items", {}), f"{path}[{index}]"))
    return sorted(errors)
