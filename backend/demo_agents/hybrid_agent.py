"""Demo Hybrid Agent for LangOrch.

This agent demonstrates the difference between the 'Step-by-Step' paradigm (tools)
and the 'One-Shot' delegation paradigm (Agent Workflows/Macros).

Protocol:
- GET /health
- POST /execute with body:
  {
    "action": "browser.navigate | browser.click | run_full_salesforce_login",
    "params": {...},
    "run_id": "...",
    "node_id": "...",
    "step_id": "..."
  }
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

logger = logging.getLogger("hybrid_agent")
logging.basicConfig(level=logging.INFO)

@dataclass
class AgentSettings:
    orchestrator_url: str = os.getenv("ORCHESTRATOR_URL", "http://127.0.0.1:8000")
    agent_id: str = os.getenv("AGENT_ID", "hybrid-demo-agent")
    agent_port: int = int(os.getenv("AGENT_PORT", "9005"))

SETTINGS = AgentSettings()

# The capabilities represent both granular tools and large agent workflows
CAPABILITIES: list[dict[str, Any]] = [
    # --- Granular Tools (Called step-by-step by Orchestrator) ---
    {
        "name": "browser.navigate",
        "type": "tool",
        "description": "Navigates the browser to a given URL",
        "is_batch": False
    },
    {
        "name": "browser.click",
        "type": "tool",
        "description": "Clicks an element on the screen",
        "is_batch": False
    },
    {
        "name": "browser.type",
        "type": "tool",
        "description": "Types text into an input field",
        "is_batch": False
    },
    
    # --- Agent Workflow (One-Shot delegation) ---
    {
        "name": "run_full_salesforce_login",
        "type": "workflow",
        "description": "A fully automated local macro that logs into Salesforce and extracts a token",
        "estimated_duration_s": 15,
        "is_batch": False
    }
]

async def _set_agent_status(status: str) -> None:
    """Notify the orchestrator of this agent's online/offline status."""
    url = f"{SETTINGS.orchestrator_url}/api/agents/{SETTINGS.agent_id}"
    payload: dict[str, Any] = {"status": status}
    if status == "online":
        payload["capabilities"] = CAPABILITIES
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.put(url, json=payload)
            if resp.status_code == 404 and status == "online":
                # Agent not found; auto-register it
                register_url = f"{SETTINGS.orchestrator_url}/api/agents"
                register_payload = {
                    "agent_id": SETTINGS.agent_id,
                    "name": "Hybrid Tools & Workflow Demo Agent",
                    "channel": "hybrid",
                    "base_url": f"http://127.0.0.1:{SETTINGS.agent_port}",
                    "concurrency_limit": 2,
                    "resource_key": "hybrid_default",
                    "pool_id": "hybrid_pool",
                    "capabilities": CAPABILITIES
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


class ExecuteRequest(BaseModel):
    action: str
    params: dict[str, Any] = Field(default_factory=dict)
    run_id: str
    node_id: str
    step_id: str


app = FastAPI(title="LangOrch Demo Hybrid Agent", version="0.1.0", lifespan=lifespan)

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

@app.get("/capabilities")
async def capabilities() -> dict[str, Any]:
    return {
        "agent_id": SETTINGS.agent_id,
        "channel": "hybrid",
        "capabilities": CAPABILITIES,
        "description": "Demonstrates granular tools vs one-shot agent workflows",
    }

@app.post("/execute")
async def execute(req: ExecuteRequest) -> dict[str, Any]:
    action = req.action.strip().lower()
    logger.info(f"Received Execution Request: {action}")
    
    try:
        # -------------------------------------------------------------------
        # Scenario 1: Step-by-Step Granular Tools
        # Orchestrator calls these individually, making decisions in between.
        # -------------------------------------------------------------------
        if action in ["browser.navigate", "browser.click", "browser.type"]:
            logger.info(f"Executing quick granular tool: {action}")
            await asyncio.sleep(0.5) # Simulate fast click/typing
            return {
                "status": "success", 
                "result": {
                    "ok": True, 
                    "action": action, 
                    "note": f"Fast individual tool execution completed: {action}"
                }
            }

        # -------------------------------------------------------------------
        # Scenario 2: One-Shot Agent Workflow (Async/Detached)
        # Orchestrator fires this with a callback_url. The agent IMMEDIATELY
        # acknowledges the request (202) then runs the macro in the background.
        # When the macro completes, it POSTs the result to callback_url.
        # -------------------------------------------------------------------
        if action == "run_full_salesforce_login":
            username = req.params.get("username", "default_user")
            callback_url: str | None = req.params.get("callback_url")
            run_id_for_log = req.run_id
            node_id = req.node_id
            step_id = req.step_id

            logger.info(
                "Workflow '%s' dispatched for user='%s'. callback_url=%s",
                action, username, callback_url or "NONE (blocking mode)",
            )

            async def _run_macro():
                """Execute the macro steps and fire the callback when done."""
                result_payload: dict[str, Any] = {}
                error_msg: str | None = None
                cb_status = "success"
                try:
                    logger.info("[Macro Step 1] Launching stealth browser...")
                    await asyncio.sleep(2.0)
                    logger.info("[Macro Step 2] Navigating to login portal...")
                    await asyncio.sleep(2.0)
                    logger.info("[Macro Step 3] Solving Captcha...")
                    await asyncio.sleep(3.0)
                    logger.info("[Macro Step 4] Entering 2FA challenge and resolving...")
                    await asyncio.sleep(2.0)
                    logger.info("[Macro Step 5] Extracting Session Token...")
                    await asyncio.sleep(1.0)
                    result_payload = {
                        "ok": True,
                        "macro_name": "run_full_salesforce_login",
                        "extracted_token": "ey1234.salesforce.session.token.xyz987",
                        "note": "Workflow completed without Orchestrator intervention.",
                    }
                    logger.info("Workflow macro complete for run_id=%s", run_id_for_log)
                except Exception as exc:
                    logger.exception("Macro failed for run_id=%s", run_id_for_log)
                    cb_status = "failure"
                    error_msg = str(exc)

                if callback_url:
                    try:
                        import httpx as _httpx
                        async with _httpx.AsyncClient(timeout=15.0) as _c:
                            resp = await _c.post(callback_url, json={
                                "status": cb_status,
                                "output": result_payload,
                                "node_id": node_id,
                                "step_id": step_id,
                                "error": error_msg,
                            })
                            resp.raise_for_status()
                            logger.info(
                                "Callback posted to %s — HTTP %s",
                                callback_url, resp.status_code,
                            )
                    except Exception as cb_exc:
                        logger.error(
                            "Failed to post callback to %s: %s", callback_url, cb_exc
                        )
                else:
                    # No callback_url — was called in legacy blocking mode
                    logger.info("No callback_url; result discarded (legacy blocking call).")

            if callback_url:
                # Detach and immediately return 202 Accepted
                asyncio.create_task(_run_macro())
                return {
                    "status": "accepted",
                    "message": "Workflow started. Result will be POSTed to callback_url.",
                    "callback_url": callback_url,
                }
            else:
                # Blocking fallback (used when called without callback_url, e.g. tests)
                await _run_macro()
                return {"status": "success", "result": result_payload or {}}

        return {"status": "error", "error": f"Unsupported action: {action}"}
        
    except Exception as exc:
        logger.exception("Error executing action")
        return {"status": "error", "error": str(exc)}

