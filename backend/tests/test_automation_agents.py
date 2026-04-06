from __future__ import annotations

import base64
from email.message import EmailMessage
from types import SimpleNamespace

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from automation_agents import database_agent, desktop_agent, email_agent, file_agent, integration_agent, swarm_agent, web_agent
from app.contracts.agent_protocol import build_signed_headers


def _request(action: str, params: dict | None = None):
    return database_agent.AgentExecuteRequest(
        action=action,
        params=params or {},
        run_id="run1",
        node_id="node1",
        step_id="step1",
    )


@pytest.mark.asyncio
async def test_file_agent_read_write_and_list(tmp_path, monkeypatch):
    monkeypatch.setattr(file_agent, "BASE_DIR", str(tmp_path))
    transport = ASGITransport(app=file_agent.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        write_resp = await client.post(
            "/execute",
            json={
                "action": "write_file",
                "params": {"path": "notes/hello.txt", "content": "hello world"},
                "run_id": "run1",
                "node_id": "node1",
                "step_id": "step1",
                "approval_id": "appr-write-1",
            },
        )
        assert write_resp.status_code == 200
        assert write_resp.json()["status"] == "success"
        assert write_resp.json()["result"]["artifact"]["name"] == "hello.txt"
        assert write_resp.json()["result"]["artifact"]["kind"] == "text"

        read_resp = await client.post(
            "/execute",
            json={
                "action": "read_file",
                "params": {"path": "notes/hello.txt"},
                "run_id": "run1",
                "node_id": "node1",
                "step_id": "step2",
            },
        )
        assert read_resp.json()["result"]["content"] == "hello world"

        list_resp = await client.post(
            "/execute",
            json={
                "action": "list_directory",
                "params": {"path": "notes"},
                "run_id": "run1",
                "node_id": "node1",
                "step_id": "step3",
            },
        )
        assert list_resp.json()["result"]["count"] == 1


@pytest.mark.asyncio
async def test_database_agent_execute_query_and_bulk_insert(tmp_path):
    db_path = tmp_path / "sample.db"
    database_url = f"sqlite:///{db_path.as_posix()}"
    transport = ASGITransport(app=database_agent.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_resp = await client.post(
            "/execute",
            json={
                "action": "execute_query",
                "params": {
                    "database_url": database_url,
                    "query": "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL)",
                },
                "run_id": "run1",
                "node_id": "node1",
                "step_id": "step1",
            },
        )
        assert create_resp.json()["status"] == "success"

        insert_resp = await client.post(
            "/execute",
            json={
                "action": "bulk_insert",
                "params": {
                    "database_url": database_url,
                    "table": "users",
                    "rows": [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}],
                },
                "run_id": "run1",
                "node_id": "node1",
                "step_id": "step2",
                "approval_id": "appr-db-1",
            },
        )
        assert insert_resp.json()["result"]["table"] == "users"
        assert insert_resp.json()["result"]["provider"] == "sqlite"

        query_resp = await client.post(
            "/execute",
            json={
                "action": "execute_query",
                "params": {
                    "database_url": database_url,
                    "query": "SELECT id, name FROM users ORDER BY id",
                },
                "run_id": "run1",
                "node_id": "node1",
                "step_id": "step3",
            },
        )
        rows = query_resp.json()["result"]["rows"]
        assert rows == [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]


@pytest.mark.asyncio
async def test_database_agent_sqlite_creates_parent_directory(tmp_path):
    db_path = tmp_path / "nested" / "demo" / "sample.db"
    result = await database_agent._execute(
        "execute_query",
        {
            "database_url": f"sqlite:///{db_path.as_posix()}",
            "query": "CREATE TABLE demo (id INTEGER PRIMARY KEY)",
        },
        _request("execute_query"),
    )

    assert result["provider"] == "sqlite"
    assert db_path.exists()


@pytest.mark.asyncio
async def test_database_agent_odbc_provider_execute_query(monkeypatch):
    calls: list[tuple[str, int]] = []

    class FakeCursor:
        description = [("id",), ("name",)]
        rowcount = 1

        def execute(self, query, params):
            self.query = query
            self.params = params

        def fetchall(self):
            return [(1, "Alice")]

    class FakeConnection:
        def __init__(self):
            self.cursor_obj = FakeCursor()

        def cursor(self):
            return self.cursor_obj

        def commit(self):
            return None

        def close(self):
            return None

    def fake_import(name: str):
        if name == "pyodbc":
            return SimpleNamespace(
                connect=lambda connection_string, timeout=15: calls.append((connection_string, timeout)) or FakeConnection()
            )
        raise ImportError(name)

    monkeypatch.setattr(database_agent.importlib, "import_module", fake_import)

    result = await database_agent._execute(
        "execute_query",
        {
            "provider": "odbc",
            "connection_string": "Driver={ODBC Driver 18 for SQL Server};Server=demo;",
            "query": "SELECT id, name FROM demo_users",
        },
        _request("execute_query"),
    )

    assert result["provider"] == "odbc"
    assert result["rows"] == [{"id": 1, "name": "Alice"}]
    assert calls == [("Driver={ODBC Driver 18 for SQL Server};Server=demo;", 15)]


@pytest.mark.asyncio
async def test_database_agent_jdbc_provider_bulk_update(monkeypatch):
    captured: dict[str, object] = {}

    class FakeCursor:
        description = None
        rowcount = 2

        def execute(self, query, params):
            captured["query"] = query
            captured["params"] = params

        def executemany(self, query, values):
            captured["query"] = query
            captured["values"] = values

    class FakeConnection:
        def __init__(self):
            self.cursor_obj = FakeCursor()
            self.committed = False

        def cursor(self):
            return self.cursor_obj

        def commit(self):
            self.committed = True

        def close(self):
            return None

    def fake_import(name: str):
        if name == "jaydebeapi":
            def connect(driver_class, jdbc_url, credentials, jars):
                captured["driver_class"] = driver_class
                captured["jdbc_url"] = jdbc_url
                captured["credentials"] = credentials
                captured["jars"] = jars
                return FakeConnection()

            return SimpleNamespace(connect=connect)
        raise ImportError(name)

    monkeypatch.setattr(database_agent.importlib, "import_module", fake_import)

    result = await database_agent._execute(
        "bulk_update",
        {
            "provider": "jdbc",
            "jdbc_url": "jdbc:postgresql://db.example.com/demo",
            "driver_class": "org.postgresql.Driver",
            "username": "demo",
            "password": "secret",
            "jars": ["postgresql.jar"],
            "table": "users",
            "rows": [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}],
            "key_columns": ["id"],
        },
        _request("bulk_update"),
    )

    assert result["provider"] == "jdbc"
    assert result["table"] == "users"
    assert captured["driver_class"] == "org.postgresql.Driver"
    assert captured["jdbc_url"] == "jdbc:postgresql://db.example.com/demo"
    assert captured["credentials"] == ["demo", "secret"]
    assert captured["jars"] == ["postgresql.jar"]
    assert "UPDATE users SET name=?" in captured["query"]


@pytest.mark.asyncio
async def test_desktop_agent_mock_provider_supports_cross_app_contract():
    transport = ASGITransport(app=desktop_agent.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/execute",
            json={
                "action": "send_pf_key",
                "params": {"provider": "mock", "key": "PF8"},
                "run_id": "run1",
                "node_id": "node1",
                "step_id": "step1",
            },
        )
        payload = response.json()
        assert payload["status"] == "success"
        assert payload["result"]["pf_key"] == "PF8"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("agent_module", "params"),
    [
        (email_agent, {"provider": "smtp_imap", "smtp_host": "smtp.example.com"}),
        (database_agent, {"provider": "sqlite", "database_url": "sqlite:///:memory:"}),
        (desktop_agent, {"provider": "mock", "title": "Main Window"}),
        (web_agent, {"start_url": "https://example.com"}),
    ],
)
async def test_stateful_agents_support_session_lifecycle(agent_module, params):
    transport = ASGITransport(app=agent_module.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        health_resp = await client.get("/health")
        if health_resp.status_code == 200:
            assert health_resp.json().get("session_backend") in {None, "memory", "db"}
        open_resp = await client.post(
            "/execute",
            json={
                "action": "open_session",
                "params": params,
                "run_id": "run-session",
                "node_id": "node-session",
                "step_id": "step-open",
            },
        )
        payload = open_resp.json()
        assert payload["status"] == "success"
        session_id = payload["result"]["session_id"]

        resume_resp = await client.post(
            "/execute",
            json={
                "action": "resume_session",
                "params": {"session_id": session_id},
                "run_id": "run-session",
                "node_id": "node-session",
                "step_id": "step-resume",
                "session_id": session_id,
            },
        )
        resume_payload = resume_resp.json()
        assert resume_payload["status"] == "success"
        assert resume_payload["result"]["session_id"] == session_id

        close_resp = await client.post(
            "/execute",
            json={
                "action": "close_session",
                "params": {"session_id": session_id},
                "run_id": "run-session",
                "node_id": "node-session",
                "step_id": "step-close",
                "session_id": session_id,
            },
        )
        close_payload = close_resp.json()
        assert close_payload["status"] == "success"
        assert close_payload["result"]["closed"] is True


@pytest.mark.asyncio
async def test_file_agent_policy_blocks_high_risk_write_without_approval(tmp_path, monkeypatch):
    monkeypatch.setattr(file_agent, "BASE_DIR", str(tmp_path))
    transport = ASGITransport(app=file_agent.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/execute",
            json={
                "action": "write_file",
                "params": {"path": "notes/policy.txt", "content": "blocked"},
                "run_id": "run-policy",
                "node_id": "node-policy",
                "step_id": "step-policy",
            },
        )
    payload = response.json()
    assert payload["status"] == "error"
    assert "approval_id is required" in payload["error"]


@pytest.mark.asyncio
async def test_web_agent_click_allows_routine_navigation_without_approval(monkeypatch):
    monkeypatch.setattr(web_agent.SETTINGS, "dry_run", True)
    transport = ASGITransport(app=web_agent.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/execute",
            json={
                "action": "click",
                "params": {"target": "text=Join Now"},
                "run_id": "run-web-click",
                "node_id": "node-web-click",
                "step_id": "step-web-click",
            },
        )
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["result"]["action"] == "click"


@pytest.mark.asyncio
async def test_web_agent_sensitive_request_interception_still_requires_approval(monkeypatch):
    monkeypatch.setattr(web_agent.SETTINGS, "dry_run", True)
    transport = ASGITransport(app=web_agent.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/execute",
            json={
                "action": "intercept_requests",
                "params": {"url_pattern": "**/*"},
                "run_id": "run-web-policy",
                "node_id": "node-web-policy",
                "step_id": "step-web-policy",
            },
        )
    payload = response.json()
    assert payload["status"] == "error"
    assert "approval_id is required" in payload["error"]


@pytest.mark.asyncio
async def test_integration_agent_schema_validation_rejects_invalid_input():
    transport = ASGITransport(app=integration_agent.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/execute",
            json={
                "action": "http_request",
                "params": {"method": "GET"},
                "run_id": "run-schema",
                "node_id": "node-schema",
                "step_id": "step-schema",
            },
        )
    payload = response.json()
    assert payload["status"] == "error"
    assert "schema validation failed" in payload["error"]


@pytest.mark.asyncio
async def test_desktop_agent_execute_requires_signature_when_secret_configured(monkeypatch):
    previous_secret = desktop_agent.SETTINGS.signed_communication_secret
    monkeypatch.setattr(desktop_agent.SETTINGS, "signed_communication_secret", "protocol-secret")
    payload = {
        "action": "send_pf_key",
        "params": {"provider": "mock", "key": "PF9"},
        "run_id": "run1",
        "node_id": "node1",
        "step_id": "step1",
    }
    transport = ASGITransport(app=desktop_agent.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        unsigned = await client.post("/execute", json=payload)
        assert unsigned.status_code == 401

        headers = build_signed_headers("POST", "/execute", payload, "protocol-secret")
        signed = await client.post("/execute", json=payload, headers=headers)
        assert signed.status_code == 200
        assert signed.json()["status"] == "success"

    monkeypatch.setattr(desktop_agent.SETTINGS, "signed_communication_secret", previous_secret)


@pytest.mark.asyncio
async def test_desktop_agent_pywinauto_provider_find_element_and_type(monkeypatch):
    sent_keys: list[str] = []
    typed: list[str] = []

    class FakeWrapper:
        def __init__(self, name: str):
            self._name = name
            self.element_info = SimpleNamespace(control_type="Edit")

        def window_text(self):
            return self._name

    class FakeElement:
        def wrapper_object(self):
            return FakeWrapper("Username")

        def set_edit_text(self, text: str):
            typed.append(text)

    class FakeWindow:
        handle = 123

        def window_text(self):
            return "Main Window"

        def child_window(self, **kwargs):
            return FakeElement()

        def descendants(self):
            return [SimpleNamespace(window_text=lambda: "Line 1"), SimpleNamespace(window_text=lambda: "Line 2")]

    class FakeApplication:
        def __init__(self, backend: str):
            self.backend = backend

        def connect(self, **kwargs):
            return self

        def window(self, **kwargs):
            return FakeWindow()

        def top_window(self):
            return FakeWindow()

    def fake_import(name: str):
        if name == "pywinauto":
            return SimpleNamespace(Application=FakeApplication)
        if name == "pywinauto.keyboard":
            return SimpleNamespace(send_keys=lambda value: sent_keys.append(value))
        raise ImportError(name)

    monkeypatch.setattr(desktop_agent.importlib, "import_module", fake_import)

    find_result = await desktop_agent._execute(
        "find_element",
        {"provider": "pywinauto", "title": "Main Window", "target": "Username"},
        _request("find_element"),
    )
    type_result = await desktop_agent._execute(
        "type",
        {"provider": "pywinauto", "title": "Main Window", "target": "Username", "text": "alice"},
        _request("type"),
    )
    pf_result = await desktop_agent._execute(
        "send_pf_key",
        {"provider": "pywinauto", "key": "{F8}"},
        _request("send_pf_key"),
    )

    assert find_result["provider"] == "pywinauto"
    assert find_result["name"] == "Username"
    assert type_result["typed"] is True
    assert typed == ["alice"]
    assert pf_result["pf_key"] == "{F8}"
    assert sent_keys == ["{F8}"]


@pytest.mark.asyncio
async def test_desktop_agent_pywinauto_type_falls_back_to_type_keys(monkeypatch):
    typed: list[str] = []

    class FakeWrapper:
        def set_edit_text(self, text: str):
            raise RuntimeError("set_edit_text unsupported")

        def type_keys(self, text: str, with_spaces: bool = True, set_foreground: bool = True):
            typed.append(text)

    class FakeWindow:
        handle = 123

        def window_text(self):
            return "Main Window"

        def descendants(self):
            return []

        def wrapper_object(self):
            return FakeWrapper()

    class FakeApplication:
        def __init__(self, backend: str):
            self.backend = backend

        def connect(self, **kwargs):
            return self

        def window(self, **kwargs):
            return FakeWindow()

        def top_window(self):
            return FakeWindow()

    def fake_import(name: str):
        if name == "pywinauto":
            return SimpleNamespace(Application=FakeApplication)
        if name == "pywinauto.keyboard":
            return SimpleNamespace(send_keys=lambda value: None)
        raise ImportError(name)

    monkeypatch.setattr(desktop_agent.importlib, "import_module", fake_import)

    result = await desktop_agent._execute(
        "type",
        {"provider": "pywinauto", "title": "Main Window", "text": "fallback text"},
        _request("type"),
    )

    assert result["typed"] is True
    assert typed == ["fallback text"]


@pytest.mark.asyncio
async def test_desktop_agent_winappdriver_provider_launch_and_click(monkeypatch):
    calls: list[tuple[str, str]] = []

    class FakeResponse:
        def __init__(self, payload: dict[str, object], content: bytes | None = None):
            self._payload = payload
            self.content = b"{}" if content is None else content

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class FakeAsyncClient:
        def __init__(self, timeout: float):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url: str, json: dict | None = None):
            calls.append(("POST", url))
            if url.endswith("/session"):
                return FakeResponse({"sessionId": "session-1"})
            if url.endswith("/element"):
                return FakeResponse({"value": {"element-6066-11e4-a52e-4f735466cecf": "element-1"}})
            return FakeResponse({})

        async def get(self, url: str):
            calls.append(("GET", url))
            return FakeResponse({"value": "Window Title"})

    monkeypatch.setattr(desktop_agent.httpx, "AsyncClient", FakeAsyncClient)

    launch_result = await desktop_agent._execute(
        "launch_app",
        {"provider": "winappdriver", "application": "notepad.exe"},
        _request("launch_app"),
    )
    click_result = await desktop_agent._execute(
        "click",
        {"provider": "winappdriver", "session_id": "session-1", "target": "OK"},
        _request("click"),
    )

    assert launch_result["session_id"] == "session-1"
    assert click_result["clicked"] is True
    assert any(url.endswith("/session") for _, url in calls)
    assert any(url.endswith("/click") for _, url in calls)


@pytest.mark.asyncio
async def test_desktop_agent_java_access_bridge_provider_click(monkeypatch):
    clicks: list[str] = []

    class FakeElement:
        def __init__(self, name: str):
            self.name = name

        def click(self):
            clicks.append(self.name)

        def send_text(self, text: str):
            clicks.append(text)

    class FakeDriver:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def find_element_by_name(self, name: str):
            return FakeElement(name)

        def send_keys(self, text: str):
            clicks.append(text)

        def get_accessible_context_tree(self):
            return {"role": "frame"}

    def fake_import(name: str):
        if name == "pyjab":
            return SimpleNamespace(JABDriver=FakeDriver)
        raise ImportError(name)

    monkeypatch.setattr(desktop_agent.importlib, "import_module", fake_import)

    click_result = await desktop_agent._execute(
        "click",
        {"provider": "java_access_bridge", "title": "Claims", "target": "Submit"},
        _request("click"),
    )
    pf_result = await desktop_agent._execute(
        "send_pf_key",
        {"provider": "java_access_bridge", "title": "Claims", "key": "F5"},
        _request("send_pf_key"),
    )

    assert click_result["clicked"] is True
    assert pf_result["pf_key"] == "F5"
    assert clicks == ["Submit", "F5"]


@pytest.mark.asyncio
async def test_integration_agent_http_request(monkeypatch):
    async def fake_request(self, method, url, **kwargs):
        request = httpx.Request(method, url)
        return httpx.Response(200, json={"ok": True, "url": str(url)}, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    result = await integration_agent._execute(
        "http_request",
        {"method": "GET", "url": "https://example.com/api"},
        integration_agent.AgentExecuteRequest(
            action="http_request",
            params={"method": "GET", "url": "https://example.com/api"},
            run_id="run1",
            node_id="node1",
            step_id="step1",
        ),
    )
    assert result["json"] == {"ok": True, "url": "https://example.com/api"}


@pytest.mark.asyncio
async def test_email_agent_smtp_and_imap_paths(monkeypatch):
    sent_messages: list[EmailMessage] = []

    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: int):
            self.host = host
            self.port = port
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def starttls(self):
            return None

        def login(self, username: str, password: str):
            self.username = username
            self.password = password

        def send_message(self, message: EmailMessage):
            sent_messages.append(message)

    attachment_message = EmailMessage()
    attachment_message["Subject"] = "Demo subject"
    attachment_message["From"] = "ops@example.com"
    attachment_message["To"] = "user@example.com"
    attachment_message.set_content("Hello from IMAP")
    attachment_message.add_attachment(b"csv,data", maintype="text", subtype="csv", filename="report.csv")
    raw_message = attachment_message.as_bytes()

    class FakeImapClient:
        def __init__(self, host: str):
            self.host = host

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def login(self, username: str, password: str):
            return ("OK", [b"logged-in"])

        def select(self, mailbox: str):
            return ("OK", [mailbox.encode("utf-8")])

        def search(self, charset, criterion: str):
            return ("OK", [b"1 2"])

        def fetch(self, message_id: str, query: str):
            return ("OK", [(b"1", raw_message)])

    monkeypatch.setattr(email_agent.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(email_agent.imaplib, "IMAP4_SSL", FakeImapClient)

    send_result = await email_agent._execute(
        "send_email",
        {
            "provider": "smtp_imap",
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "from": "ops@example.com",
            "to": ["user@example.com"],
            "subject": "Automation ready",
            "body": "Hello world",
            "username": "ops",
            "password": "secret",
        },
        _request("send_email"),
    )
    search_result = await email_agent._execute(
        "search_email",
        {
            "provider": "smtp_imap",
            "imap_host": "imap.example.com",
            "username": "ops",
            "password": "secret",
            "criterion": 'SUBJECT "Demo"',
        },
        _request("search_email"),
    )
    read_result = await email_agent._execute(
        "read_email",
        {
            "provider": "smtp_imap",
            "imap_host": "imap.example.com",
            "username": "ops",
            "password": "secret",
            "message_id": "1",
        },
        _request("read_email"),
    )
    attachment_result = await email_agent._execute(
        "download_attachment",
        {
            "provider": "smtp_imap",
            "imap_host": "imap.example.com",
            "username": "ops",
            "password": "secret",
            "message_id": "1",
            "attachment_name": "report.csv",
        },
        _request("download_attachment"),
    )

    assert send_result["sent"] is True
    assert sent_messages[0]["Subject"] == "Automation ready"
    assert search_result["count"] == 2
    assert read_result["subject"] == "Demo subject"
    assert "Hello from IMAP" in read_result["body"]
    assert attachment_result["filename"] == "report.csv"
    assert base64.b64decode(attachment_result["content_base64"]) == b"csv,data"


@pytest.mark.asyncio
async def test_email_agent_graph_provider_send_and_search(monkeypatch):
    calls: list[tuple[str, str]] = []

    class FakeResponse:
        def __init__(self, payload: dict[str, object], content: bytes = b"{}"):
            self._payload = payload
            self.content = content

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class FakeAsyncClient:
        def __init__(self, timeout: float):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def request(self, method: str, url: str, headers=None, json=None):
            calls.append((method, url))
            if url.endswith("/sendMail"):
                return FakeResponse({}, content=b"")
            if "$search=" in url:
                return FakeResponse({"value": [{"id": "message-1", "subject": "Quarterly update"}]})
            return FakeResponse({"id": "draft-1"})

    monkeypatch.setattr(email_agent.httpx, "AsyncClient", FakeAsyncClient)

    send_result = await email_agent._execute(
        "send_email",
        {
            "provider": "graph",
            "access_token": "token",
            "to": ["user@example.com"],
            "subject": "Quarterly update",
            "body": "Attached summary",
        },
        _request("send_email"),
    )
    search_result = await email_agent._execute(
        "search_email",
        {
            "provider": "graph",
            "access_token": "token",
            "query": "Quarterly",
        },
        _request("search_email"),
    )

    assert send_result["provider"] == "graph"
    assert send_result["sent"] is True
    assert search_result["messages"] == [{"id": "message-1", "subject": "Quarterly update"}]
    assert any(url.endswith("/sendMail") for _, url in calls)


@pytest.mark.asyncio
async def test_web_agent_dry_run_endpoints(monkeypatch):
    monkeypatch.setattr(web_agent.SETTINGS, "dry_run", True)
    transport = ASGITransport(app=web_agent.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        caps_response = await client.get("/capabilities")
        execute_response = await client.post(
            "/execute",
            json={
                "action": "extract_text",
                "params": {"target": "#demo"},
                "run_id": "run1",
                "node_id": "node1",
                "step_id": "step1",
            },
        )

    assert caps_response.json()["agent_id"] == "web-automation-agent"
    assert execute_response.json()["status"] == "success"
    assert execute_response.json()["result"]["text"] == "demo-extracted-text"


@pytest.mark.asyncio
async def test_swarm_agent_failure_analysis_endpoint():
    transport = ASGITransport(app=swarm_agent.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        caps_response = await client.get("/capabilities")
        execute_response = await client.post(
            "/execute",
            json={
                "action": "swarm.failure_analysis",
                "params": {
                    "context": {
                        "error": "503 timeout from upstream dependency",
                        "timeline": [{"event": "request_sent"}, {"event": "timeout"}],
                    }
                },
                "run_id": "run1",
                "node_id": "node1",
                "step_id": "step1",
            },
        )

    payload = execute_response.json()["result"]["swarm_result"]
    assert caps_response.json()["agent_id"] == "swarm-automation-agent"
    assert payload["probable_root_cause"] == "transient_dependency_failure"
    assert payload["retry_recommended"] is True
    assert "verifier_summary" in payload
