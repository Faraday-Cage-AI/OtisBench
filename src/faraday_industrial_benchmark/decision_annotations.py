"""Explicit annotation contract; never relax the underlying business values."""

import re


def exception_values_match(rows, expected):
    if not isinstance(rows, list):
        return False
    values = []
    for row in rows:
        if not isinstance(row, dict) or not {"record_id", "reason_code"} <= row.keys():
            return False
        if set(row) - {"record_id", "reason_code", "reason", "notes", "metadata"}:
            return False
        if not all(isinstance(row[key], str) for key in ("record_id", "reason_code")):
            return False
        if any(key in row and not isinstance(row[key], str) for key in ("reason", "notes")):
            return False
        if "metadata" in row and not isinstance(row["metadata"], dict):
            return False
        values.append({key: row[key] for key in ("record_id", "reason_code")})
    return sorted(values, key=lambda row: row["record_id"]) == sorted(
        expected, key=lambda row: row["record_id"]
    )


def cited_record_ids(evidence, known):
    """Count existing IDs at token boundaries, not fragments or duplicate mentions."""
    return {
        record_id
        for record_id in known
        if any(
            isinstance(item, str) and re.search(rf"(?<![\w-]){re.escape(record_id)}(?![\w-])", item)
            for item in evidence
        )
    }
