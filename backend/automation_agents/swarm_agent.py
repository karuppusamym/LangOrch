"""Bounded swarm automation agent for LangOrch.

This agent models bounded multi-agent reasoning behind a single workflow
capability so it can plug into LangOrch's existing async delegation flow.

Protocol:
- GET /health
- GET /capabilities
- POST /execute

Supported workflow capabilities:
- swarm.case_triage
- swarm.document_review
- swarm.failure_analysis
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request

from app.config import settings as orch_settings
from app.contracts.agent_contracts import AgentCapability, AgentExecuteEnvelope, AgentExecuteRequest
from app.contracts.agent_protocol import PROTOCOL_HEADER, SIGNATURE_HEADER, TIMESTAMP_HEADER, TRACE_HEADER, generate_trace_id, verify_signed_request
from app.contracts.swarm_contracts import verify_swarm_output
from automation_agents.runtime_support import object_schema, string_schema, validate_json_schema
from automation_agents.shared import post_signed_callback

logger = logging.getLogger("swarm_agent")
logging.basicConfig(level=logging.INFO)


@dataclass
class AgentSettings:
    orchestrator_url: str = os.getenv("ORCHESTRATOR_URL", "http://127.0.0.1:8000")
    agent_id: str = os.getenv("SWARM_AGENT_ID", "swarm-automation-agent")
    agent_name: str = os.getenv("SWARM_AGENT_NAME", "Bounded Swarm Automation Agent")
    agent_port: int = int(os.getenv("SWARM_AGENT_PORT", "9006"))
    channel: str = os.getenv("SWARM_AGENT_CHANNEL", "swarm")
    pool_id: str = os.getenv("SWARM_AGENT_POOL_ID", "swarm_pool")
    resource_key: str = os.getenv("SWARM_AGENT_RESOURCE_KEY", "swarm_default")
    concurrency_limit: int = int(os.getenv("SWARM_AGENT_CONCURRENCY", "2"))


SETTINGS = AgentSettings()

_SWARM_INPUT_SCHEMA = object_schema(
    properties={
        "goal": string_schema(),
        "callback_url": string_schema(),
        "context": object_schema(),
    }
)

_SWARM_OUTPUT_SCHEMA = object_schema(
    required=["swarm_result"],
    properties={"swarm_result": object_schema()},
)

CAPABILITIES: list[AgentCapability] = [
    AgentCapability(
        name="swarm.case_triage",
        type="workflow",
        description="Bounded planner plus specialist triage for inbound cases",
        estimated_duration_s=6,
        input_schema=_SWARM_INPUT_SCHEMA,
        output_schema=_SWARM_OUTPUT_SCHEMA,
        supports_async=True,
        side_effect_level="none",
        idempotent=True,
    ),
    AgentCapability(
        name="swarm.document_review",
        type="workflow",
        description="Bounded specialist review and synthesis for document risk assessment",
        estimated_duration_s=8,
        input_schema=_SWARM_INPUT_SCHEMA,
        output_schema=_SWARM_OUTPUT_SCHEMA,
        supports_async=True,
        side_effect_level="none",
        idempotent=True,
    ),
    AgentCapability(
        name="swarm.failure_analysis",
        type="workflow",
        description="Analyze a failed run and recommend safe retry, escalation, or compensation",
        estimated_duration_s=5,
        input_schema=_SWARM_INPUT_SCHEMA,
        output_schema=_SWARM_OUTPUT_SCHEMA,
        supports_async=True,
        side_effect_level="none",
        idempotent=True,
    ),
]

ExecuteRequest = AgentExecuteRequest


async def _set_agent_status(status: str) -> None:
    url = f"{SETTINGS.orchestrator_url}/api/agents/{SETTINGS.agent_id}"
    payload: dict[str, Any] = {"status": status}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            if status == "online":
                register_url = f"{SETTINGS.orchestrator_url}/api/agents"
                register_payload = {
                    "agent_id": SETTINGS.agent_id,
                    "name": SETTINGS.agent_name,
                    "channel": SETTINGS.channel,
                    "base_url": f"http://127.0.0.1:{SETTINGS.agent_port}",
                    "concurrency_limit": SETTINGS.concurrency_limit,
                    "resource_key": SETTINGS.resource_key,
                    "pool_id": SETTINGS.pool_id,
                    "capabilities": [cap.model_dump() for cap in CAPABILITIES],
                }
                resp = await client.post(register_url, json=register_payload)
                resp.raise_for_status()
            else:
                resp = await client.put(url, json=payload)
                resp.raise_for_status()
            logger.info("Agent '%s' marked %s.", SETTINGS.agent_id, status)
    except Exception as exc:
        logger.warning("Could not update/register agent status (%s): %s", url, exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _set_agent_status("online")
    try:
        yield
    finally:
        await _set_agent_status("offline")


app = FastAPI(title="LangOrch Swarm Automation Agent", version="0.2.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "agent_id": SETTINGS.agent_id,
        "capabilities": [cap.name for cap in CAPABILITIES],
    }


@app.get("/capabilities")
async def capabilities() -> dict[str, Any]:
    return {
        "agent_id": SETTINGS.agent_id,
        "channel": SETTINGS.channel,
        "capabilities": [cap.model_dump() for cap in CAPABILITIES],
        "description": "Bounded multi-agent reasoning exposed as workflow capabilities",
        "protocol_version": orch_settings.AGENT_PROTOCOL_VERSION,
    }


def _normalize_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip().lower()
    if isinstance(value, dict):
        return " ".join(_normalize_text(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(_normalize_text(v) for v in value)
    return ""


def _keyword_present(text: str, words: set[str]) -> bool:
    return any(word in text for word in words)


async def _run_case_triage(params: dict[str, Any]) -> dict[str, Any]:
    await asyncio.sleep(0.5)
    context = params.get("context", {})
    text_blob = _normalize_text(context)

    issue_type = "general_inquiry"
    urgency = "medium"
    recommended_route = "support_queue"
    risk_flags: list[str] = []

    if _keyword_present(text_blob, {"refund", "invoice", "charge", "billing", "renewal"}):
        issue_type = "billing"
        recommended_route = "finance_specialist_queue"

    if _keyword_present(text_blob, {"breach", "security", "incident", "phishing", "leak"}):
        issue_type = "security_incident"
        urgency = "high"
        recommended_route = "security_incident_queue"
        risk_flags.append("security_signal")

    if _keyword_present(text_blob, {"legal", "contract", "msa", "dpa", "clause"}):
        issue_type = "contract_review"
        recommended_route = "legal_review_queue"
        risk_flags.append("contractual_risk")

    if _keyword_present(text_blob, {"urgent", "asap", "today", "blocked", "production down"}):
        urgency = "high"
        risk_flags.append("time_sensitive")

    confidence = 0.93 if risk_flags or issue_type != "general_inquiry" else 0.78
    specialist_reports = [
        {
            "role": "classifier",
            "summary": f"Classified case as {issue_type} with urgency {urgency}.",
        },
        {
            "role": "risk_reviewer",
            "summary": "No critical risks detected." if not risk_flags else f"Risk flags: {', '.join(risk_flags)}.",
        },
        {
            "role": "router",
            "summary": f"Recommended route is {recommended_route}.",
        },
    ]
    return {
        "swarm_result": {
            "goal": params.get("goal", "Classify and route the case"),
            "issue_type": issue_type,
            "urgency": urgency,
            "recommended_route": recommended_route,
            "confidence": confidence,
            "risk_flags": risk_flags,
            "specialist_reports": specialist_reports,
        }
    }


async def _run_document_review(params: dict[str, Any]) -> dict[str, Any]:
    await asyncio.sleep(0.75)
    context = params.get("context", {})
    text_blob = _normalize_text(context)

    legal_risk = "medium" if _keyword_present(text_blob, {"indemnity", "liability", "termination"}) else "low"
    security_risk = "high" if _keyword_present(text_blob, {"data transfer", "subprocessor", "pii", "personal data"}) else "low"
    commercial_risk = "medium" if _keyword_present(text_blob, {"auto-renew", "price increase", "exclusivity"}) else "low"

    overall = "approved"
    if "high" in {legal_risk, security_risk, commercial_risk}:
        overall = "needs_escalation"
    elif "medium" in {legal_risk, security_risk, commercial_risk}:
        overall = "needs_review"

    return {
        "swarm_result": {
            "goal": params.get("goal", "Review document risk"),
            "overall_decision": overall,
            "confidence": 0.89,
            "specialist_reports": [
                {"role": "legal_reviewer", "risk": legal_risk, "summary": f"Legal risk assessed as {legal_risk}."},
                {"role": "security_reviewer", "risk": security_risk, "summary": f"Security risk assessed as {security_risk}."},
                {"role": "commercial_reviewer", "risk": commercial_risk, "summary": f"Commercial risk assessed as {commercial_risk}."},
            ],
        }
    }


async def _run_failure_analysis(params: dict[str, Any]) -> dict[str, Any]:
    await asyncio.sleep(0.4)
    context = params.get("context", {})
    text_blob = _normalize_text(context)
    timeline = context.get("timeline") if isinstance(context, dict) else None

    probable_root_cause = "transient_dependency_failure"
    retry_recommended = True
    escalation_recommended = False
    compensation_recommended = False
    safe_next_actions = [
        "capture_latest_logs",
        "retry_from_last_safe_checkpoint",
    ]
    evidence = [
        {"source": "error_message", "detail": "Defaulted to transient failure heuristics."},
    ]

    if _keyword_present(text_blob, {"schema", "validation", "invalid payload", "malformed"}):
        probable_root_cause = "contract_mismatch"
        retry_recommended = False
        escalation_recommended = True
        safe_next_actions = ["inspect_request_schema", "run_contract_test"]
        evidence.append({"source": "classifier", "detail": "Validation or schema mismatch indicators detected."})
    elif _keyword_present(text_blob, {"timeout", "503", "rate limit", "connection reset", "unavailable"}):
        probable_root_cause = "transient_dependency_failure"
        retry_recommended = True
        safe_next_actions = ["retry_from_last_safe_checkpoint", "shift_to_fallback_dependency"]
        evidence.append({"source": "classifier", "detail": "Transient dependency keywords detected."})
    elif _keyword_present(text_blob, {"duplicate", "already exists", "conflict", "partial write"}):
        probable_root_cause = "partial_side_effect"
        retry_recommended = False
        escalation_recommended = True
        compensation_recommended = True
        safe_next_actions = ["inspect_side_effects", "run_compensation_playbook"]
        evidence.append({"source": "classifier", "detail": "Possible partial side effect or duplicate write detected."})

    if isinstance(timeline, list) and timeline:
        evidence.append({"source": "timeline", "detail": f"Observed {len(timeline)} timeline event(s)."})

    verifier_summary = (
        "Retry is safe because failure looks transient."
        if retry_recommended
        else "Retry is blocked until contract or side-effect risk is resolved."
    )

    return {
        "swarm_result": {
            "goal": params.get("goal", "Analyze the failed run and recommend the safest next step"),
            "probable_root_cause": probable_root_cause,
            "retry_recommended": retry_recommended,
            "escalation_recommended": escalation_recommended,
            "compensation_recommended": compensation_recommended,
            "safe_next_actions": safe_next_actions,
            "confidence": 0.86 if retry_recommended else 0.9,
            "evidence": evidence,
            "verifier_summary": verifier_summary,
        }
    }


async def _run_action(action: str, params: dict[str, Any]) -> dict[str, Any]:
    if action == "swarm.case_triage":
        return verify_swarm_output(action, await _run_case_triage(params))
    if action == "swarm.document_review":
        return verify_swarm_output(action, await _run_document_review(params))
    if action == "swarm.failure_analysis":
        return verify_swarm_output(action, await _run_failure_analysis(params))
    raise HTTPException(status_code=404, detail=f"Unsupported action: {action}")


@app.post("/execute")
async def execute(req: ExecuteRequest, request: Request) -> dict[str, Any]:
    raw_body = await request.body()
    secret = orch_settings.AGENT_SHARED_SECRET or None
    if secret and not verify_signed_request(
        method=request.method,
        path=request.url.path,
        body=raw_body,
        secret=secret,
        provided_timestamp=request.headers.get(TIMESTAMP_HEADER),
        provided_signature=request.headers.get(SIGNATURE_HEADER),
        ttl_seconds=orch_settings.AGENT_SIGNATURE_TTL_SECONDS,
    ):
        raise HTTPException(status_code=401, detail="Invalid agent request signature")

    action = req.action.strip().lower()
    callback_url = req.params.get("callback_url")
    trace_id = req.trace_id or request.headers.get(TRACE_HEADER) or generate_trace_id()
    capability = next((cap for cap in CAPABILITIES if cap.name == action), None)
    if capability and capability.input_schema:
        validate_json_schema(capability.input_schema, req.params, f"{action} input")
    logger.info("Received swarm execution request: %s", action)

    async def _run_and_callback() -> None:
        status = "success"
        output: dict[str, Any] = {}
        error: str | None = None
        try:
            output = await _run_action(action, req.params)
        except Exception as exc:
            status = "failure"
            error = str(exc)
            logger.exception("Swarm action failed for run_id=%s", req.run_id)

        if callback_url:
            try:
                await post_signed_callback(
                    callback_url,
                    {
                        "status": status,
                        "output": output,
                        "node_id": req.node_id,
                        "step_id": req.step_id,
                        "error": error,
                        "trace_id": trace_id,
                        "protocol_version": orch_settings.AGENT_PROTOCOL_VERSION,
                    },
                    protocol_version=orch_settings.AGENT_PROTOCOL_VERSION,
                )
                logger.info("Swarm callback posted for run_id=%s", req.run_id)
            except Exception:
                logger.exception("Failed to post swarm callback for run_id=%s", req.run_id)

    if callback_url:
        asyncio.create_task(_run_and_callback())
        envelope = AgentExecuteEnvelope(
            status="accepted",
            result={
                "ok": True,
                "action": action,
                "mode": "async",
                "note": "Swarm execution started and will resume the run through callback.",
            },
            trace_id=trace_id,
            protocol_version=orch_settings.AGENT_PROTOCOL_VERSION,
        )
        return envelope.model_dump(exclude_none=True)

    output = await _run_action(action, req.params)
    if capability and capability.output_schema:
        validate_json_schema(capability.output_schema, output, f"{action} output")
    envelope = AgentExecuteEnvelope(
        status="success",
        result=output,
        trace_id=trace_id,
        protocol_version=orch_settings.AGENT_PROTOCOL_VERSION,
    )
    return envelope.model_dump(exclude_none=True)
