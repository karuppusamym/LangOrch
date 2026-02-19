"""Server-side validation of run input_vars against a procedure's variables_schema.

Mirrors the frontend validation logic so that invalid inputs are rejected at the
API boundary before reaching the executor.

Schema format (per-variable, flat/normalized):
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

Also accepts the CKP spec nested format:
    {"required": {"<var>": {...}}, "optional": {"<var>": {...}}}
which is automatically flattened before validation.
"""
from __future__ import annotations

import re
from typing import Any


def normalize_variables_schema(raw: Any) -> dict[str, Any]:
    """Normalize variables_schema to a flat dict keyed by variable name.

    Handles two input forms:
    1. CKP spec format: {"required": {"var": {...}}, "optional": {"var": {...}}}
       → flattened to {"var": {..., "required": True/False}}
    2. Flat dict format: {"var": {"type": "string", ...}}
       → passed through as-is
    3. Any non-dict (list, None, etc.) → returns {}
    """
    if not isinstance(raw, dict):
        return {}

    has_required_key = "required" in raw and isinstance(raw["required"], dict)
    has_optional_key = "optional" in raw and isinstance(raw["optional"], dict)

    if has_required_key or has_optional_key:
        flat: dict[str, Any] = {}
        for var_name, meta in (raw.get("required") or {}).items():
            entry = dict(meta) if isinstance(meta, dict) else {}
            entry["required"] = True
            flat[var_name] = entry
        for var_name, meta in (raw.get("optional") or {}).items():
            entry = dict(meta) if isinstance(meta, dict) else {}
            entry.setdefault("required", False)
            flat[var_name] = entry
        return flat

    return raw


def validate_input_vars(
    schema: dict[str, Any],
    input_vars: dict[str, Any] | None,
) -> dict[str, str]:
    """Validate *input_vars* against *schema*.

    Automatically normalizes the schema from the CKP nested format if needed.
    Returns a dict of ``{field_name: error_message}`` for every failing field.
    An empty dict means all fields are valid.
    """
    if not schema:
        return {}

    # Normalize nested CKP format to flat format before validation
    schema = normalize_variables_schema(schema)

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
