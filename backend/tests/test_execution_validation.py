"""Tests for execution_service input variable validation helpers."""

from __future__ import annotations

import pytest

from app.services.execution_service import _validate_var_constraints


class TestValidateVarConstraints:
    """Test schema constraint validation for input variables."""

    def test_no_constraints_passes(self):
        schema = {"name": {"type": "string"}}
        assert _validate_var_constraints(schema, {"name": "Alice"}) == []

    def test_empty_schema_passes(self):
        assert _validate_var_constraints({}, {"name": "Alice"}) == []

    def test_missing_var_is_skipped(self):
        """Required check is done separately; missing vars return no constraint errors."""
        schema = {"name": {"type": "string", "validation": {"regex": "^[A-Z].*"}}}
        assert _validate_var_constraints(schema, {}) == []

    # ── regex ────────────────────────────────────────────────────────────

    def test_regex_passes_matching_value(self):
        schema = {"code": {"type": "string", "validation": {"regex": "^[A-Z]{3}$"}}}
        assert _validate_var_constraints(schema, {"code": "ABC"}) == []

    def test_regex_fails_non_matching_value(self):
        schema = {"code": {"type": "string", "validation": {"regex": "^[A-Z]{3}$"}}}
        errors = _validate_var_constraints(schema, {"code": "abc"})
        assert len(errors) == 1
        assert "'code'" in errors[0]
        assert "pattern" in errors[0]

    def test_regex_ignored_for_non_string(self):
        schema = {"count": {"type": "number", "validation": {"regex": "^\\d+$"}}}
        # value is already int — regex only applies to strings
        assert _validate_var_constraints(schema, {"count": 5}) == []

    # ── max ─────────────────────────────────────────────────────────────

    def test_max_passes_below_limit(self):
        schema = {"age": {"type": "number", "validation": {"max": 120}}}
        assert _validate_var_constraints(schema, {"age": 18}) == []

    def test_max_passes_equal_to_limit(self):
        schema = {"age": {"type": "number", "validation": {"max": 18}}}
        assert _validate_var_constraints(schema, {"age": 18}) == []

    def test_max_fails_above_limit(self):
        schema = {"age": {"type": "number", "validation": {"max": 18}}}
        errors = _validate_var_constraints(schema, {"age": 19})
        assert len(errors) == 1
        assert "'age'" in errors[0]
        assert "maximum" in errors[0]

    # ── min ─────────────────────────────────────────────────────────────

    def test_min_passes_above_limit(self):
        schema = {"qty": {"type": "number", "validation": {"min": 1}}}
        assert _validate_var_constraints(schema, {"qty": 5}) == []

    def test_min_passes_equal_to_limit(self):
        schema = {"qty": {"type": "number", "validation": {"min": 1}}}
        assert _validate_var_constraints(schema, {"qty": 1}) == []

    def test_min_fails_below_limit(self):
        schema = {"qty": {"type": "number", "validation": {"min": 1}}}
        errors = _validate_var_constraints(schema, {"qty": 0})
        assert len(errors) == 1
        assert "'qty'" in errors[0]
        assert "minimum" in errors[0]

    # ── allowed_values ──────────────────────────────────────────────────

    def test_allowed_values_passes_member(self):
        schema = {"env": {"type": "string", "validation": {"allowed_values": ["dev", "staging", "prod"]}}}
        assert _validate_var_constraints(schema, {"env": "staging"}) == []

    def test_allowed_values_fails_non_member(self):
        schema = {"env": {"type": "string", "validation": {"allowed_values": ["dev", "staging", "prod"]}}}
        errors = _validate_var_constraints(schema, {"env": "local"})
        assert len(errors) == 1
        assert "'env'" in errors[0]
        assert "allowed values" in errors[0]

    def test_allowed_values_works_for_numbers(self):
        schema = {"priority": {"type": "number", "validation": {"allowed_values": [1, 2, 3]}}}
        assert _validate_var_constraints(schema, {"priority": 2}) == []
        errors = _validate_var_constraints(schema, {"priority": 5})
        assert len(errors) == 1

    # ── multiple constraints + multiple vars ─────────────────────────────

    def test_multiple_errors_collected(self):
        schema = {
            "code": {"type": "string", "validation": {"regex": "^[A-Z]{3}$"}},
            "age": {"type": "number", "validation": {"max": 100}},
        }
        errors = _validate_var_constraints(schema, {"code": "lowercase", "age": 200})
        assert len(errors) == 2

    def test_non_dict_meta_is_skipped(self):
        schema = {"x": "just a string"}
        assert _validate_var_constraints(schema, {"x": "value"}) == []

    def test_no_validation_block_is_fine(self):
        schema = {"name": {"type": "string", "required": True}}
        assert _validate_var_constraints(schema, {"name": "Alice"}) == []
