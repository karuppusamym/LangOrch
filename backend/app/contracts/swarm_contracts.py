"""Structured result contracts for bounded swarm capabilities."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SpecialistReport(BaseModel):
    role: str
    summary: str
    risk: str | None = None


class SwarmCaseTriageResult(BaseModel):
    goal: str
    issue_type: str
    urgency: Literal["low", "medium", "high"]
    recommended_route: str
    confidence: float = Field(ge=0.0, le=1.0)
    risk_flags: list[str] = Field(default_factory=list)
    specialist_reports: list[SpecialistReport] = Field(default_factory=list)


class SwarmDocumentReviewResult(BaseModel):
    goal: str
    overall_decision: Literal["approved", "needs_review", "needs_escalation"]
    confidence: float = Field(ge=0.0, le=1.0)
    specialist_reports: list[SpecialistReport] = Field(default_factory=list)


class FailureEvidence(BaseModel):
    source: str
    detail: str


class SwarmFailureAnalysisResult(BaseModel):
    goal: str
    probable_root_cause: str
    retry_recommended: bool
    escalation_recommended: bool
    compensation_recommended: bool = False
    safe_next_actions: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[FailureEvidence] = Field(default_factory=list)
    verifier_summary: str


def verify_swarm_output(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Validate the structured swarm result and return the normalized payload."""
    result = payload.get("swarm_result")
    if not isinstance(result, dict):
        raise ValueError("swarm_result payload is required")

    if action == "swarm.case_triage":
        validated = SwarmCaseTriageResult.model_validate(result)
    elif action == "swarm.document_review":
        validated = SwarmDocumentReviewResult.model_validate(result)
    elif action == "swarm.failure_analysis":
        validated = SwarmFailureAnalysisResult.model_validate(result)
        if validated.retry_recommended and validated.compensation_recommended:
            raise ValueError("failure analysis cannot recommend retry and compensation together")
        if not validated.safe_next_actions:
            raise ValueError("failure analysis must provide at least one safe_next_action")
    else:
        raise ValueError(f"Unsupported swarm verifier action: {action}")

    return {"swarm_result": validated.model_dump()}
