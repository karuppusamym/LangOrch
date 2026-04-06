"""HTTP and integration automation agent."""

from __future__ import annotations

import os
from typing import Any

import httpx

from app.contracts.agent_contracts import AgentCapability, AgentExecuteRequest

from automation_agents.shared import AutomationAgentSettings, build_agent_app
from automation_agents.runtime_support import object_schema, string_schema


SETTINGS = AutomationAgentSettings(
    orchestrator_url=os.getenv("ORCHESTRATOR_URL", "http://127.0.0.1:8000"),
    agent_id=os.getenv("INTEGRATION_AGENT_ID", "integration-automation-agent"),
    agent_name=os.getenv("INTEGRATION_AGENT_NAME", "Integration Automation Agent"),
    agent_port=int(os.getenv("INTEGRATION_AGENT_PORT", "9010")),
    channel=os.getenv("INTEGRATION_AGENT_CHANNEL", "api"),
    pool_id=os.getenv("INTEGRATION_AGENT_POOL_ID", "integration_pool"),
    resource_key=os.getenv("INTEGRATION_AGENT_RESOURCE_KEY", "integration_default"),
    concurrency_limit=int(os.getenv("INTEGRATION_AGENT_CONCURRENCY", "8")),
    description="Generic HTTP, GraphQL, webhook, SOAP, and token-fetch automation.",
)

CAPABILITIES = [
    AgentCapability(
        name="http_request",
        description="Execute REST or generic HTTP requests",
        input_schema=object_schema(required=["url"], properties={"url": string_schema(), "method": string_schema()}),
        output_schema=object_schema(required=["status_code", "headers", "text"], properties={}),
        side_effect_level="medium",
        idempotent=False,
    ),
    AgentCapability(
        name="graphql_query",
        description="Execute GraphQL requests",
        input_schema=object_schema(required=["url", "query"], properties={"url": string_schema(), "query": string_schema()}),
        output_schema=object_schema(required=["status_code", "headers", "text"], properties={}),
        side_effect_level="low",
        idempotent=True,
    ),
    AgentCapability(
        name="webhook_send",
        description="Send webhook payloads",
        input_schema=object_schema(required=["url"], properties={"url": string_schema(), "method": string_schema()}),
        output_schema=object_schema(required=["status_code", "headers", "text"], properties={}),
        side_effect_level="high",
        idempotent=False,
    ),
    AgentCapability(
        name="soap_request",
        description="Send SOAP/XML requests",
        input_schema=object_schema(required=["url", "body"], properties={"url": string_schema(), "body": string_schema()}),
        output_schema=object_schema(required=["status_code", "headers", "text"], properties={}),
        side_effect_level="medium",
        idempotent=False,
    ),
    AgentCapability(
        name="authenticate",
        description="Fetch OAuth2 client_credentials tokens",
        input_schema=object_schema(required=["token_url", "client_id", "client_secret"], properties={"token_url": string_schema(), "client_id": string_schema(), "client_secret": string_schema()}),
        output_schema=object_schema(required=["token_type", "access_token"], properties={}),
        side_effect_level="none",
        idempotent=False,
    ),
]


def _response_payload(response: httpx.Response) -> dict[str, Any]:
    try:
        json_body = response.json()
    except Exception:
        json_body = None
    text = response.text
    return {
        "status_code": response.status_code,
        "headers": dict(response.headers),
        "json": json_body,
        "text": text[:4000],
    }


async def _execute(action: str, params: dict[str, Any], req: AgentExecuteRequest) -> dict[str, Any]:
    timeout = float(params.get("timeout_s", 30))
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=bool(params.get("follow_redirects", True))) as client:
        if action == "http_request":
            method = str(params.get("method", "GET")).upper()
            response = await client.request(
                method,
                params["url"],
                params=params.get("query_params"),
                headers=params.get("headers"),
                json=params.get("json"),
                data=params.get("body"),
            )
            return _response_payload(response)

        if action == "graphql_query":
            response = await client.post(
                params["url"],
                headers=params.get("headers"),
                json={
                    "query": params["query"],
                    "variables": params.get("variables") or {},
                    "operationName": params.get("operation_name"),
                },
            )
            return _response_payload(response)

        if action == "webhook_send":
            method = str(params.get("method", "POST")).upper()
            response = await client.request(
                method,
                params["url"],
                headers=params.get("headers"),
                json=params.get("json"),
                data=params.get("body"),
            )
            return _response_payload(response)

        if action == "soap_request":
            headers = {"Content-Type": "text/xml; charset=utf-8", **(params.get("headers") or {})}
            response = await client.post(
                params["url"],
                headers=headers,
                content=params["body"],
            )
            return _response_payload(response)

        if action == "authenticate":
            grant_type = str(params.get("grant_type", "client_credentials"))
            if grant_type != "client_credentials":
                raise ValueError("Only client_credentials is supported")
            response = await client.post(
                params["token_url"],
                data={
                    "grant_type": "client_credentials",
                    "client_id": params["client_id"],
                    "client_secret": params["client_secret"],
                    "scope": params.get("scope"),
                },
                headers=params.get("headers"),
            )
            response.raise_for_status()
            token_payload = response.json()
            return {
                "token_type": token_payload.get("token_type", "Bearer"),
                "access_token": token_payload.get("access_token"),
                "expires_in": token_payload.get("expires_in"),
                "raw": token_payload,
            }

    raise ValueError(f"Unsupported integration action: {action}")


app = build_agent_app(
    title="LangOrch Integration Automation Agent",
    version="0.1.0",
    settings=SETTINGS,
    capabilities=CAPABILITIES,
    execute_handler=_execute,
)
