"""Demo Swarm Agent for LangOrch.

This agent models bounded multi-agent reasoning behind a single workflow
capability so it can plug into LangOrch's existing async delegation flow.

Protocol:
- GET /health
- GET /capabilities
- POST /execute

Supported workflow capabilities:
- swarm.case_triage
- swarm.document_review
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("swarm_agent")
logging.basicConfig(level=logging.INFO)


@dataclass
class AgentSettings:
    orchestrator_url: str = os.getenv("ORCHESTRATOR_URL", "http://127.0.0.1:8000")
    agent_id: str = os.getenv("SWARM_AGENT_ID", "swarm-demo-agent")
    agent_name: str = os.getenv("SWARM_AGENT_NAME", "Bounded Swarm Demo Agent")
    agent_port: int = int(os.getenv("SWARM_AGENT_PORT", "9006"))
    channel: str = os.getenv("SWARM_AGENT_CHANNEL", "swarm")
    pool_id: str = os.getenv("SWARM_AGENT_POOL_ID", "swarm_pool")
    resource_key: str = os.getenv("SWARM_AGENT_RESOURCE_KEY", "swarm_default")
    concurrency_limit: int = int(os.getenv("SWARM_AGENT_CONCURRENCY", "2"))


SETTINGS = AgentSettings()

CAPABILITIES: list[dict[str, Any]] = [
    {
        "name": "swarm.case_triage",
        "type": "workflow",
        "description": "Bounded planner plus specialist triage for inbound cases",
        "estimated_duration_s": 6,
        "is_batch": False,
    },
    {
        "name": "swarm.document_review",
        "type": "workflow",
        "description": "Bounded specialist review and synthesis for document risk assessment",
        "estimated_duration_s": 8,
        "is_batch": False,
    },
]


class ExecuteRequest(BaseModel):
    action: str
    params: dict[str, Any] = Field(default_factory=dict)
    run_id: str
    node_id: str
    step_id: str


async def _set_agent_status(status: str) -> None:
    url = f"{SETTINGS.orchestrator_url}/api/agents/{SETTINGS.agent_id}"
    payload: dict[str, Any] = {"status": status}
    if status == "online":
        payload["capabilities"] = CAPABILITIES
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.put(url, json=payload)
            if resp.status_code == 404 and status == "online":
                register_url = f"{SETTINGS.orchestrator_url}/api/agents"
                register_payload = {
                    "agent_id": SETTINGS.agent_id,
                    "name": SETTINGS.agent_name,
                    "channel": SETTINGS.channel,
                    "base_url": f"http://127.0.0.1:{SETTINGS.agent_port}",
                    "concurrency_limit": SETTINGS.concurrency_limit,
                    "resource_key": SETTINGS.resource_key,
                    "pool_id": SETTINGS.pool_id,
                    "capabilities": CAPABILITIES,
                }
                reg_resp = await client.post(register_url, json=register_payload)
                reg_resp.raise_for_status()
                logger.info("Agent '%s' auto-registered.", SETTINGS.agent_id)
            else:
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


app = FastAPI(title="LangOrch Demo Swarm Agent", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "agent_id": SETTINGS.agent_id,
        "capabilities": [cap["name"] for cap in CAPABILITIES],
    }


@app.get("/capabilities")
async def capabilities() -> dict[str, Any]:
    return {
        "agent_id": SETTINGS.agent_id,
        "channel": SETTINGS.channel,
        "capabilities": CAPABILITIES,
        "description": "Bounded multi-agent reasoning exposed as workflow capabilities",
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


async def _run_action(action: str, params: dict[str, Any]) -> dict[str, Any]:
    if action == "swarm.case_triage":
        return await _run_case_triage(params)
    if action == "swarm.document_review":
        return await _run_document_review(params)
    raise HTTPException(status_code=404, detail=f"Unsupported action: {action}")


async def _post_callback(callback_url: str, payload: dict[str, Any]) -> None:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(callback_url, json=payload)
        resp.raise_for_status()


@app.post("/execute")
async def execute(req: ExecuteRequest) -> dict[str, Any]:
    action = req.action.strip().lower()
    callback_url = req.params.get("callback_url")
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
                await _post_callback(
                    callback_url,
                    {
                        "status": status,
                        "output": output,
                        "node_id": req.node_id,
                        "step_id": req.step_id,
                        "error": error,
                    },
                )
                logger.info("Swarm callback posted for run_id=%s", req.run_id)
            except Exception:
                logger.exception("Failed to post swarm callback for run_id=%s", req.run_id)

    if callback_url:
        asyncio.create_task(_run_and_callback())
        return {
            "status": "accepted",
            "result": {
                "ok": True,
                "action": action,
                "mode": "async",
                "note": "Swarm execution started and will resume the run through callback.",
            },
        }

    output = await _run_action(action, req.params)
    return {"status": "success", "result": output}