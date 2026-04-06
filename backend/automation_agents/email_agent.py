"""Email automation agent with SMTP/IMAP and Microsoft Graph providers."""

from __future__ import annotations

import base64
import email
import imaplib
import os
import smtplib
from email.message import EmailMessage
from typing import Any

import httpx

from app.contracts.agent_contracts import AgentCapability, AgentExecuteRequest

from automation_agents.shared import AutomationAgentSettings, build_agent_app
from automation_agents.runtime_support import array_schema, build_session_store, object_schema, string_schema


DEFAULT_PROVIDER = os.getenv("EMAIL_AGENT_PROVIDER", "smtp_imap")

SETTINGS = AutomationAgentSettings(
    orchestrator_url=os.getenv("ORCHESTRATOR_URL", "http://127.0.0.1:8000"),
    agent_id=os.getenv("EMAIL_AGENT_ID", "email-automation-agent"),
    agent_name=os.getenv("EMAIL_AGENT_NAME", "Email Automation Agent"),
    agent_port=int(os.getenv("EMAIL_AGENT_PORT", "9014")),
    channel=os.getenv("EMAIL_AGENT_CHANNEL", "email"),
    pool_id=os.getenv("EMAIL_AGENT_POOL_ID", "email_pool"),
    resource_key=os.getenv("EMAIL_AGENT_RESOURCE_KEY", "email_default"),
    concurrency_limit=int(os.getenv("EMAIL_AGENT_CONCURRENCY", "4")),
    description="SMTP/IMAP and Microsoft Graph email automation.",
)

_RECIPIENTS_SCHEMA = {
    "oneOf": [
        string_schema(),
        array_schema(string_schema()),
    ]
}

_ATTACHMENT_SCHEMA = object_schema(
    properties={
        "filename": string_schema(),
        "content": {},
        "maintype": string_schema(),
        "subtype": string_schema(),
    },
)

_MESSAGE_INPUT_SCHEMA = object_schema(
    properties={
        "provider": string_schema(enum=["smtp_imap", "smtp", "imap", "graph", "microsoft_graph"]),
        "from": string_schema(),
        "to": _RECIPIENTS_SCHEMA,
        "cc": _RECIPIENTS_SCHEMA,
        "subject": string_schema(),
        "body": string_schema(),
        "attachments": array_schema(_ATTACHMENT_SCHEMA),
    }
)

_SESSION_INPUT_SCHEMA = object_schema(
    properties={
        "provider": string_schema(enum=["smtp_imap", "smtp", "imap", "graph", "microsoft_graph"]),
        "smtp_host": string_schema(),
        "imap_host": string_schema(),
        "smtp_port": {"type": "integer"},
        "username": string_schema(),
        "password": string_schema(),
        "access_token": string_schema(),
        "graph_base_url": string_schema(),
        "user_path": string_schema(),
        "mailbox": string_schema(),
        "headers": object_schema(),
    }
)

_SESSION_OPEN_OUTPUT_SCHEMA = object_schema(
    required=["session_id", "expires_at", "created_at"],
    properties={"session_id": string_schema()},
)

_SESSION_RESUME_OUTPUT_SCHEMA = object_schema(
    required=["session_id", "created_at", "last_used_at", "expires_at", "data"],
    properties={"session_id": string_schema(), "data": object_schema()},
)

_SESSION_CLOSE_OUTPUT_SCHEMA = object_schema(
    required=["session_id", "closed"],
    properties={"session_id": string_schema(), "closed": {"type": "boolean"}},
)

_COMPOSE_OUTPUT_SCHEMA = object_schema(
    required=["provider"],
    properties={"provider": string_schema()},
)

_SEND_OUTPUT_SCHEMA = object_schema(
    required=["provider", "sent"],
    properties={"provider": string_schema(), "sent": {"type": "boolean"}},
)

_SEARCH_OUTPUT_SCHEMA = object_schema(
    required=["provider"],
    properties={
        "provider": string_schema(),
        "message_ids": array_schema(string_schema()),
        "count": {"type": "integer"},
        "messages": array_schema(object_schema()),
    },
)

_READ_OUTPUT_SCHEMA = object_schema(
    required=["provider"],
    properties={"provider": string_schema()},
)

_ATTACHMENT_OUTPUT_SCHEMA = object_schema(
    required=["provider"],
    properties={"provider": string_schema()},
)

CAPABILITIES = [
    AgentCapability(
        name="open_session",
        description="Create a reusable email session with provider defaults",
        input_schema=_SESSION_INPUT_SCHEMA,
        output_schema=_SESSION_OPEN_OUTPUT_SCHEMA,
        side_effect_level="none",
        idempotent=False,
        session_scoped=True,
    ),
    AgentCapability(
        name="resume_session",
        description="Inspect the active email session",
        input_schema=object_schema(required=["session_id"], properties={"session_id": string_schema()}),
        output_schema=_SESSION_RESUME_OUTPUT_SCHEMA,
        side_effect_level="none",
        idempotent=True,
        session_scoped=True,
    ),
    AgentCapability(
        name="close_session",
        description="Close the active email session",
        input_schema=object_schema(required=["session_id"], properties={"session_id": string_schema()}),
        output_schema=_SESSION_CLOSE_OUTPUT_SCHEMA,
        side_effect_level="low",
        idempotent=False,
        session_scoped=True,
    ),
    AgentCapability(
        name="compose_email",
        description="Build a message payload",
        input_schema=_MESSAGE_INPUT_SCHEMA,
        output_schema=_COMPOSE_OUTPUT_SCHEMA,
        side_effect_level="none",
        idempotent=True,
        session_scoped=True,
    ),
    AgentCapability(
        name="create_draft",
        description="Create a draft message",
        input_schema=_MESSAGE_INPUT_SCHEMA,
        output_schema=_COMPOSE_OUTPUT_SCHEMA,
        side_effect_level="medium",
        idempotent=False,
        session_scoped=True,
    ),
    AgentCapability(
        name="send_email",
        description="Send a message",
        input_schema=_MESSAGE_INPUT_SCHEMA,
        output_schema=_SEND_OUTPUT_SCHEMA,
        side_effect_level="high",
        idempotent=False,
        requires_approval=True,
        session_scoped=True,
    ),
    AgentCapability(
        name="read_email",
        description="Read a message",
        input_schema=object_schema(
            required=["message_id"],
            properties={**_SESSION_INPUT_SCHEMA["properties"], "message_id": string_schema()},
        ),
        output_schema=_READ_OUTPUT_SCHEMA,
        side_effect_level="none",
        idempotent=True,
        session_scoped=True,
    ),
    AgentCapability(
        name="search_email",
        description="Search a mailbox",
        input_schema=object_schema(
            properties={
                **_SESSION_INPUT_SCHEMA["properties"],
                "criterion": string_schema(),
                "query": string_schema(),
            }
        ),
        output_schema=_SEARCH_OUTPUT_SCHEMA,
        side_effect_level="none",
        idempotent=True,
        session_scoped=True,
    ),
    AgentCapability(
        name="download_attachment",
        description="Download a message attachment",
        input_schema=object_schema(
            required=["message_id"],
            properties={
                **_SESSION_INPUT_SCHEMA["properties"],
                "message_id": string_schema(),
                "attachment_id": string_schema(),
                "attachment_name": string_schema(),
            },
        ),
        output_schema=_ATTACHMENT_OUTPUT_SCHEMA,
        side_effect_level="none",
        idempotent=True,
        session_scoped=True,
    ),
]

SESSION_STORE = build_session_store(agent_id=SETTINGS.agent_id, channel=SETTINGS.channel, timeout_s=SETTINGS.session_timeout_s)


def _build_message(params: dict[str, Any]) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = params.get("subject", "")
    msg["From"] = params.get("from")
    recipients = params.get("to") or []
    if isinstance(recipients, str):
        recipients = [recipients]
    msg["To"] = ", ".join(recipients)
    if params.get("cc"):
        cc = params["cc"]
        if isinstance(cc, str):
            cc = [cc]
        msg["Cc"] = ", ".join(cc)
    body = params.get("body", "")
    msg.set_content(body)
    for attachment in params.get("attachments") or []:
        content = attachment.get("content")
        if isinstance(content, str):
            content_bytes = content.encode("utf-8")
        else:
            content_bytes = content or b""
        maintype = attachment.get("maintype", "application")
        subtype = attachment.get("subtype", "octet-stream")
        msg.add_attachment(content_bytes, maintype=maintype, subtype=subtype, filename=attachment.get("filename"))
    return msg


class SmtpImapEmailAdapter:
    provider_name = "smtp_imap"

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if action == "compose_email":
            msg = _build_message(params)
            return {"provider": self.provider_name, "raw": msg.as_string(), "subject": msg["Subject"]}

        if action == "create_draft":
            msg = _build_message(params)
            return {
                "provider": self.provider_name,
                "draft": {
                    "subject": msg["Subject"],
                    "to": msg["To"],
                    "raw": msg.as_string(),
                },
            }

        if action == "send_email":
            msg = _build_message(params)
            host = params["smtp_host"]
            port = int(params.get("smtp_port", 587))
            username = params.get("username")
            password = params.get("password")
            use_tls = bool(params.get("use_tls", True))
            with smtplib.SMTP(host, port, timeout=20) as server:
                if use_tls:
                    server.starttls()
                if username and password:
                    server.login(username, password)
                server.send_message(msg)
            return {"provider": self.provider_name, "sent": True, "subject": msg["Subject"]}

        if action in {"search_email", "read_email", "download_attachment"}:
            mailbox = params.get("mailbox", "INBOX")
            host = params["imap_host"]
            username = params["username"]
            password = params["password"]
            with imaplib.IMAP4_SSL(host) as client:
                client.login(username, password)
                client.select(mailbox)
                if action == "search_email":
                    criterion = params.get("criterion", 'ALL')
                    status, data = client.search(None, criterion)
                    ids = data[0].decode().split() if status == "OK" and data else []
                    return {"provider": self.provider_name, "message_ids": ids, "count": len(ids)}

                message_id = str(params["message_id"])
                status, data = client.fetch(message_id, "(RFC822)")
                if status != "OK":
                    raise ValueError(f"Could not fetch message {message_id}")
                raw = data[0][1]
                msg = email.message_from_bytes(raw)
                if action == "read_email":
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                body = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="ignore")
                                break
                    else:
                        body = msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", errors="ignore")
                    return {
                        "provider": self.provider_name,
                        "subject": msg.get("Subject"),
                        "from": msg.get("From"),
                        "to": msg.get("To"),
                        "body": body,
                    }

                attachment_name = params.get("attachment_name")
                for part in msg.walk():
                    filename = part.get_filename()
                    if filename and (attachment_name is None or filename == attachment_name):
                        content = part.get_payload(decode=True)
                        return {
                            "provider": self.provider_name,
                            "filename": filename,
                            "content_base64": base64.b64encode(content).decode("ascii"),
                        }
                raise ValueError("Attachment not found")

        raise ValueError(f"Unsupported SMTP/IMAP email action: {action}")


class GraphEmailAdapter:
    provider_name = "graph"

    async def _request(self, method: str, url: str, params: dict[str, Any], json_body: dict[str, Any] | None = None):
        headers = {"Authorization": f"Bearer {params['access_token']}"}
        headers.update(params.get("headers") or {})
        async with httpx.AsyncClient(timeout=float(params.get("timeout_s", 30))) as client:
            response = await client.request(method, url, headers=headers, json=json_body)
            response.raise_for_status()
            if response.content:
                return response.json()
            return {}

    def _message_body(self, params: dict[str, Any]) -> dict[str, Any]:
        recipients = params.get("to") or []
        if isinstance(recipients, str):
            recipients = [recipients]
        return {
            "subject": params.get("subject", ""),
            "body": {"contentType": "Text", "content": params.get("body", "")},
            "toRecipients": [{"emailAddress": {"address": address}} for address in recipients],
        }

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        base_url = params.get("graph_base_url", "https://graph.microsoft.com/v1.0")
        user_path = params.get("user_path", "me")
        if action == "compose_email":
            return {"provider": self.provider_name, "message": self._message_body(params)}
        if action == "create_draft":
            payload = await self._request("POST", f"{base_url}/{user_path}/messages", params, self._message_body(params))
            return {"provider": self.provider_name, "draft": payload}
        if action == "send_email":
            payload = {"message": self._message_body(params), "saveToSentItems": bool(params.get("save_to_sent_items", True))}
            await self._request("POST", f"{base_url}/{user_path}/sendMail", params, payload)
            return {"provider": self.provider_name, "sent": True}
        if action == "read_email":
            payload = await self._request("GET", f"{base_url}/{user_path}/messages/{params['message_id']}", params)
            return {"provider": self.provider_name, "message": payload}
        if action == "search_email":
            query = params.get("query", "")
            payload = await self._request("GET", f"{base_url}/{user_path}/messages?$search=\"{query}\"", params)
            return {"provider": self.provider_name, "messages": payload.get("value", [])}
        if action == "download_attachment":
            payload = await self._request(
                "GET",
                f"{base_url}/{user_path}/messages/{params['message_id']}/attachments/{params['attachment_id']}",
                params,
            )
            return {"provider": self.provider_name, "attachment": payload}
        raise ValueError(f"Unsupported Graph email action: {action}")


def _adapter_for(provider: str):
    normalized = provider.strip().lower()
    if normalized in {"smtp_imap", "smtp", "imap"}:
        return SmtpImapEmailAdapter()
    if normalized in {"graph", "microsoft_graph"}:
        return GraphEmailAdapter()
    raise ValueError(f"Unknown email provider: {provider}")


async def _execute(action: str, params: dict[str, Any], req: AgentExecuteRequest) -> dict[str, Any]:
    provider = str(params.get("provider") or DEFAULT_PROVIDER)
    adapter = _adapter_for(provider)
    result = await adapter.execute(action, params)
    result.setdefault("provider", provider)
    return result


app = build_agent_app(
    title="LangOrch Email Automation Agent",
    version="0.2.0",
    settings=SETTINGS,
    capabilities=CAPABILITIES,
    execute_handler=_execute,
    health_provider=lambda: {"provider": DEFAULT_PROVIDER},
    session_store=SESSION_STORE,
)
