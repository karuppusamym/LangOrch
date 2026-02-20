"""Tests for Batch 20: Trigger automation — service, HMAC, dedupe, scheduler parsing, API."""

from __future__ import annotations

import hashlib
import json
import os

import pytest


# ── IRTrigger parsing ───────────────────────────────────────────

class TestIRTriggerParsing:
    def test_parse_scheduled_trigger(self):
        from app.compiler.parser import _parse_trigger
        raw = {"type": "scheduled", "schedule": "0 9 * * 1-5"}
        t = _parse_trigger(raw)
        assert t is not None
        assert t.type == "scheduled"
        assert t.schedule == "0 9 * * 1-5"
        assert t.webhook_secret is None

    def test_parse_webhook_trigger(self):
        from app.compiler.parser import _parse_trigger
        raw = {
            "type": "webhook",
            "webhook_secret": "MY_SECRET_ENV",
            "dedupe_window_seconds": 60,
        }
        t = _parse_trigger(raw)
        assert t is not None
        assert t.type == "webhook"
        assert t.webhook_secret == "MY_SECRET_ENV"
        assert t.dedupe_window_seconds == 60

    def test_parse_event_trigger_with_nested_source(self):
        from app.compiler.parser import _parse_trigger
        raw = {"type": "event", "event": {"source": "orders.created"}}
        t = _parse_trigger(raw)
        assert t is not None
        assert t.event_source == "orders.created"

    def test_parse_returns_none_for_missing(self):
        from app.compiler.parser import _parse_trigger
        assert _parse_trigger(None) is None
        assert _parse_trigger({}) is None

    def test_parse_max_concurrent_runs(self):
        from app.compiler.parser import _parse_trigger
        raw = {"type": "webhook", "max_concurrent_runs": 3}
        t = _parse_trigger(raw)
        assert t is not None
        assert t.max_concurrent_runs == 3

    def test_trigger_stored_in_ir_procedure(self):
        """IRProcedure.trigger field is populated from CKP."""
        from app.compiler.parser import parse_ckp
        ckp = {
            "procedure_id": "trigger_proc",
            "version": "1.0.0",
            "global_config": {},
            "workflow_graph": {
                "start_node": "s1",
                "nodes": {"s1": {"type": "terminate", "status": "success"}},
            },
            "trigger": {"type": "scheduled", "schedule": "*/5 * * * *"},
        }
        ir = parse_ckp(ckp)
        assert ir.trigger is not None
        assert ir.trigger.type == "scheduled"
        assert ir.trigger.schedule == "*/5 * * * *"


# ── Validator: trigger validation ──────────────────────────────

class TestTriggerValidation:
    def _make_ir_with_trigger(self, trigger_dict: dict):
        from app.compiler.ir import IRTrigger, IRProcedure, IRNode, IRTerminatePayload
        from app.compiler.parser import parse_ckp
        ckp = {
            "procedure_id": "t_proc",
            "version": "1.0",
            "global_config": {},
            "workflow_graph": {
                "start_node": "s",
                "nodes": {"s": {"type": "terminate", "status": "success"}},
            },
            "trigger": trigger_dict,
        }
        return parse_ckp(ckp)

    def test_valid_scheduled_trigger_passes(self):
        from app.compiler.validator import validate_ir
        ir = self._make_ir_with_trigger({"type": "scheduled", "schedule": "0 * * * *"})
        errors = validate_ir(ir)
        assert not any("trigger" in e.lower() for e in errors)

    def test_scheduled_without_schedule_fails(self):
        from app.compiler.validator import validate_ir
        ir = self._make_ir_with_trigger({"type": "scheduled"})
        errors = validate_ir(ir)
        assert any("schedule" in e.lower() for e in errors), f"Expected schedule error, got: {errors}"

    def test_invalid_trigger_type_fails(self):
        from app.compiler.validator import validate_ir
        ir = self._make_ir_with_trigger({"type": "magic_button"})
        errors = validate_ir(ir)
        assert any("trigger" in e.lower() for e in errors), f"Expected trigger error, got: {errors}"

    def test_valid_webhook_trigger_passes(self):
        from app.compiler.validator import validate_ir
        ir = self._make_ir_with_trigger({"type": "webhook", "webhook_secret": "MY_SECRET"})
        errors = validate_ir(ir)
        assert not any("trigger" in e.lower() for e in errors)


# ── HMAC signature verification ─────────────────────────────────

class TestHMACVerification:
    def test_valid_hmac_accepted(self):
        from app.services.trigger_service import verify_hmac_signature
        secret = "test_secret_value"
        body = b'{"event": "order.created"}'
        sig_hex = hashlib.sha256(secret.encode() + body).hexdigest()
        header = f"sha256={sig_hex}"
        os.environ["TEST_WEBHOOK_SECRET"] = secret
        assert verify_hmac_signature(body, header, "TEST_WEBHOOK_SECRET")

    def test_wrong_signature_rejected(self):
        from app.services.trigger_service import verify_hmac_signature
        os.environ["TEST_WEBHOOK_SECRET_2"] = "real_secret"
        body = b'{"event": "order.created"}'
        assert not verify_hmac_signature(body, "sha256=deadbeef", "TEST_WEBHOOK_SECRET_2")

    def test_missing_signature_with_secret_configured_rejected(self):
        from app.services.trigger_service import verify_hmac_signature
        os.environ["TEST_WEBHOOK_SECRET_3"] = "configured"
        body = b'hello'
        assert not verify_hmac_signature(body, None, "TEST_WEBHOOK_SECRET_3")

    def test_no_secret_configured_allows_all(self):
        from app.services.trigger_service import verify_hmac_signature
        # Env var not set — should allow (dev mode)
        os.environ.pop("NONEXISTENT_SECRET_VAR", None)
        assert verify_hmac_signature(b"anything", None, "NONEXISTENT_SECRET_VAR")


# ── Payload hash ────────────────────────────────────────────────

class TestPayloadHash:
    def test_same_body_same_hash(self):
        from app.services.trigger_service import compute_payload_hash
        body = b'{"order_id": 123}'
        assert compute_payload_hash(body) == compute_payload_hash(body)

    def test_different_bodies_different_hashes(self):
        from app.services.trigger_service import compute_payload_hash
        assert compute_payload_hash(b"aaa") != compute_payload_hash(b"bbb")

    def test_hash_is_64_hex_chars(self):
        from app.services.trigger_service import compute_payload_hash
        h = compute_payload_hash(b"test")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


# ── Cron expression parsing ──────────────────────────────────────

class TestCronParsing:
    def test_5_field_expression(self):
        from app.runtime.scheduler import _parse_cron
        result = _parse_cron("0 9 * * 1-5")
        assert result == {
            "minute": "0",
            "hour": "9",
            "day": "*",
            "month": "*",
            "day_of_week": "1-5",
        }

    def test_all_star_expression(self):
        from app.runtime.scheduler import _parse_cron
        result = _parse_cron("* * * * *")
        assert result["minute"] == "*"
        assert result["hour"] == "*"

    def test_every_5_minutes(self):
        from app.runtime.scheduler import _parse_cron
        result = _parse_cron("*/5 * * * *")
        assert result["minute"] == "*/5"


# ── DB model: TriggerRegistration and TriggerDedupeRecord ──────

class TestTriggerModels:
    def test_trigger_registration_fields(self):
        from app.db.models import TriggerRegistration
        t = TriggerRegistration(
            procedure_id="p1",
            version="1.0",
            trigger_type="scheduled",
            schedule="0 * * * *",
            enabled=True,
        )
        assert t.trigger_type == "scheduled"
        assert t.schedule == "0 * * * *"
        assert t.enabled is True

    def test_trigger_dedupe_record_fields(self):
        from app.db.models import TriggerDedupeRecord
        r = TriggerDedupeRecord(
            procedure_id="p1",
            payload_hash="abc123",
            run_id="run-xyz",
        )
        assert r.payload_hash == "abc123"
        assert r.run_id == "run-xyz"

    def test_run_has_trigger_fields(self):
        from app.db.models import Run
        r = Run(
            procedure_id="p",
            procedure_version="1.0",
            thread_id="t",
            trigger_type="webhook",
            triggered_by="webhook:127.0.0.1",
        )
        assert r.trigger_type == "webhook"
        assert r.triggered_by == "webhook:127.0.0.1"


# ── Schema: TriggerRegistrationOut ──────────────────────────────

class TestTriggerSchema:
    def test_registration_out_roundtrip(self):
        from app.schemas.triggers import TriggerRegistrationOut
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        data = {
            "id": 1,
            "procedure_id": "proc_a",
            "version": "1.0.0",
            "trigger_type": "webhook",
            "schedule": None,
            "webhook_secret": "MY_ENV_VAR",
            "event_source": None,
            "dedupe_window_seconds": 30,
            "max_concurrent_runs": 5,
            "enabled": True,
            "created_at": now,
            "updated_at": now,
        }
        out = TriggerRegistrationOut(**data)
        assert out.procedure_id == "proc_a"
        assert out.dedupe_window_seconds == 30
        assert out.webhook_secret == "MY_ENV_VAR"

    def test_trigger_fire_out(self):
        from app.schemas.triggers import TriggerFireOut
        out = TriggerFireOut(
            run_id="r1",
            procedure_id="p1",
            procedure_version="1.0",
            trigger_type="scheduled",
        )
        assert out.status == "created"


# ── RunOut: trigger fields ───────────────────────────────────────

class TestRunOutTriggerFields:
    def test_run_out_includes_trigger_type(self):
        from app.schemas.runs import RunOut
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        data = {
            "run_id": "r1",
            "procedure_id": "p1",
            "procedure_version": "1.0",
            "thread_id": "t1",
            "status": "created",
            "trigger_type": "webhook",
            "triggered_by": "webhook:10.0.0.1",
            "project_id": None,
            "created_at": now,
            "updated_at": now,
        }
        out = RunOut(**data)
        assert out.trigger_type == "webhook"
        assert out.triggered_by == "webhook:10.0.0.1"
