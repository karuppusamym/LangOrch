"""Server-side validation of run input_vars against a procedure's variables_schema.

Mirrors the frontend validation logic so that invalid inputs are rejected at the
API boundary before reaching the executor.

Schema format (per-variable):
    {
        "type": "string" | "number" | "boolean" | "array" | "object",
        "required": true | false,
        "default": <any>,
        "description": "...",
        "validation": {
            "regex": "<pattern>",
            "min": <number>,
            "max": <number>,
            "allowed_values": ["a", "b", ...]
        }
    }
"""
from __future__ import annotations

import re
from typing import Any


def validate_input_vars(
    schema: dict[str, Any],
    input_vars: dict[str, Any] | None,
) -> dict[str, str]:
    """Validate *input_vars* against *schema*.

    Returns a dict of ``{field_name: error_message}`` for every failing field.
    An empty dict means all fields are valid.
    """
    if not schema:
        return {}

    vars_: dict[str, Any] = input_vars or {}
    errors: dict[str, str] = {}

    for key, meta in schema.items():
        if not isinstance(meta, dict):
            continue

        value = vars_.get(key)
        is_required: bool = bool(meta.get("required", False))
        field_type: str | None = meta.get("type")
        validation: dict[str, Any] = meta.get("validation") or {}

        # ── required check ────────────────────────────────────────────────────
        if value is None or (isinstance(value, str) and value.strip() == ""):
            if is_required:
                errors[key] = "This field is required"
                continue
            # Optional and absent — skip further validation
            continue

        # ── type coercion check ───────────────────────────────────────────────
        if field_type == "number":
            try:
                value = float(value)
            except (TypeError, ValueError):
                errors[key] = f"Must be a number"
                continue
        elif field_type == "boolean":
            if not isinstance(value, bool):
                errors[key] = "Must be a boolean (true/false)"
                continue
        elif field_type in ("array", "object"):
            if not isinstance(value, (list, dict)):
                errors[key] = f"Must be a valid {field_type}"
                continue

        # ── validation rules ──────────────────────────────────────────────────
        allowed: list | None = validation.get("allowed_values")
        if allowed is not None:
            if str(value) not in [str(v) for v in allowed]:
                errors[key] = f"Must be one of: {', '.join(str(v) for v in allowed)}"
                continue

        pattern: str | None = validation.get("regex")
        if pattern and isinstance(value, str):
            try:
                if not re.fullmatch(pattern, value):
                    errors[key] = f"Does not match required pattern: {pattern}"
                    continue
            except re.error:
                pass  # invalid regex in schema — skip enforcement

        min_val = validation.get("min")
        max_val = validation.get("max")
        if field_type == "number" and isinstance(value, (int, float)):
            if min_val is not None and value < float(min_val):
                errors[key] = f"Must be at least {min_val}"
                continue
            if max_val is not None and value > float(max_val):
                errors[key] = f"Must be at most {max_val}"
                continue
        elif isinstance(value, str):
            if min_val is not None and len(value) < int(min_val):
                errors[key] = f"Must be at least {min_val} characters"
                continue
            if max_val is not None and len(value) > int(max_val):
                errors[key] = f"Must be at most {max_val} characters"
                continue

    return errors
