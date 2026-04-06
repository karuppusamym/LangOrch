"""Universal desktop automation agent for Windows and Java applications."""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import gettempdir
from typing import Any

import httpx

from app.contracts.agent_contracts import AgentCapability, AgentExecuteRequest

from automation_agents.shared import AutomationAgentSettings, build_agent_app
from automation_agents.runtime_support import array_schema, build_session_store, object_schema, string_schema


@dataclass
class DesktopProviderSettings:
    provider: str = os.getenv("DESKTOP_AGENT_PROVIDER", "pywinauto")
    winappdriver_url: str = os.getenv("WINAPPDRIVER_URL", "http://127.0.0.1:4723")
    java_access_bridge_path: str | None = os.getenv("JAVA_ACCESS_BRIDGE_PATH")


PROVIDER_SETTINGS = DesktopProviderSettings()

SETTINGS = AutomationAgentSettings(
    orchestrator_url=os.getenv("ORCHESTRATOR_URL", "http://127.0.0.1:8000"),
    agent_id=os.getenv("DESKTOP_AGENT_ID", "desktop-automation-agent"),
    agent_name=os.getenv("DESKTOP_AGENT_NAME", "Universal Desktop Automation Agent"),
    agent_port=int(os.getenv("DESKTOP_AGENT_PORT", "9013")),
    channel=os.getenv("DESKTOP_AGENT_CHANNEL", "desktop"),
    pool_id=os.getenv("DESKTOP_AGENT_POOL_ID", "desktop_pool"),
    resource_key=os.getenv("DESKTOP_AGENT_RESOURCE_KEY", "desktop_default"),
    concurrency_limit=int(os.getenv("DESKTOP_AGENT_CONCURRENCY", "2")),
    description="Extensible desktop agent for Windows UIA, Java Access Bridge, and future terminal adapters.",
)

CAPABILITIES = [
    AgentCapability(
        name="open_session",
        description="Create a reusable desktop automation session",
        input_schema=object_schema(
            properties={
                "provider": string_schema(enum=["mock", "windows_uia", "pywinauto", "winappdriver", "java_access_bridge", "java"]),
                "application": string_schema(),
                "title": string_schema(),
                "title_re": string_schema(),
                "path": string_schema(),
                "pid": {"type": "integer"},
                "backend": string_schema(),
                "app_top_level_window": string_schema(),
            }
        ),
        output_schema=object_schema(required=["session_id", "expires_at", "created_at"], properties={"session_id": string_schema()}),
        side_effect_level="none",
        idempotent=False,
        session_scoped=True,
    ),
    AgentCapability(
        name="resume_session",
        description="Inspect the current desktop session",
        input_schema=object_schema(required=["session_id"], properties={"session_id": string_schema()}),
        output_schema=object_schema(required=["session_id", "created_at", "last_used_at", "expires_at", "data"], properties={"session_id": string_schema(), "data": object_schema()}),
        side_effect_level="none",
        idempotent=True,
        session_scoped=True,
    ),
    AgentCapability(
        name="close_session",
        description="Close the current desktop session",
        input_schema=object_schema(required=["session_id"], properties={"session_id": string_schema()}),
        output_schema=object_schema(required=["session_id", "closed"], properties={"session_id": string_schema(), "closed": {"type": "boolean"}}),
        side_effect_level="low",
        idempotent=False,
        session_scoped=True,
    ),
    AgentCapability(
        name="launch_app",
        description="Launch an application",
        input_schema=object_schema(
            required=["application"],
            properties={"application": string_schema(), "provider": string_schema(), "backend": string_schema(), "app_top_level_window": string_schema()},
        ),
        output_schema=object_schema(required=["provider"], properties={"provider": string_schema(), "session_id": string_schema()}),
        side_effect_level="medium",
        idempotent=False,
        session_scoped=True,
    ),
    AgentCapability(
        name="attach_window",
        description="Attach to an existing window or session",
        input_schema=object_schema(properties={"provider": string_schema(), "title": string_schema(), "title_re": string_schema(), "path": string_schema(), "pid": {"type": "integer"}, "session_id": string_schema()}),
        output_schema=object_schema(required=["provider"], properties={"provider": string_schema(), "session_id": string_schema()}),
        side_effect_level="none",
        idempotent=True,
        session_scoped=True,
    ),
    AgentCapability(
        name="activate_window",
        description="Bring a window to the foreground",
        input_schema=object_schema(properties={"provider": string_schema(), "title": string_schema(), "title_re": string_schema(), "session_id": string_schema()}),
        output_schema=object_schema(required=["provider"], properties={"provider": string_schema(), "focused": {"type": "boolean"}, "session_id": string_schema()}),
        side_effect_level="medium",
        idempotent=False,
        session_scoped=True,
    ),
    AgentCapability(
        name="wait_for_window",
        description="Wait for a desktop window",
        input_schema=object_schema(properties={"provider": string_schema(), "title": string_schema(), "title_re": string_schema(), "timeout_s": {"type": "number"}, "session_id": string_schema()}),
        output_schema=object_schema(required=["provider"], properties={"provider": string_schema(), "ready": {"type": "boolean"}, "session_id": string_schema()}),
        side_effect_level="none",
        idempotent=True,
        session_scoped=True,
    ),
    AgentCapability(
        name="click",
        description="Click a UI element",
        input_schema=object_schema(properties={"provider": string_schema(), "target": string_schema(), "target_re": string_schema(), "auto_id": string_schema(), "control_type": string_schema(), "best_match": string_schema(), "text": string_schema(), "session_id": string_schema()}),
        output_schema=object_schema(required=["provider"], properties={"provider": string_schema(), "clicked": {"type": "boolean"}, "session_id": string_schema()}),
        side_effect_level="high",
        idempotent=False,
        requires_approval=True,
        session_scoped=True,
    ),
    AgentCapability(
        name="type",
        description="Type into a UI field",
        input_schema=object_schema(properties={"provider": string_schema(), "target": string_schema(), "auto_id": string_schema(), "control_type": string_schema(), "text": string_schema(), "session_id": string_schema()}),
        output_schema=object_schema(required=["provider"], properties={"provider": string_schema(), "typed": {"type": "boolean"}, "session_id": string_schema()}),
        side_effect_level="high",
        idempotent=False,
        requires_approval=True,
        session_scoped=True,
    ),
    AgentCapability(
        name="press_key",
        description="Press a single key",
        input_schema=object_schema(required=["key"], properties={"provider": string_schema(), "key": string_schema(), "session_id": string_schema()}),
        output_schema=object_schema(required=["provider"], properties={"provider": string_schema(), "key": string_schema()}),
        side_effect_level="medium",
        idempotent=False,
        session_scoped=True,
    ),
    AgentCapability(
        name="press_keys",
        description="Press a keyboard shortcut",
        input_schema=object_schema(required=["keys"], properties={"provider": string_schema(), "keys": {"oneOf": [string_schema(), array_schema(string_schema())]}, "session_id": string_schema()}),
        output_schema=object_schema(required=["provider"], properties={"provider": string_schema(), "keys": string_schema()}),
        side_effect_level="medium",
        idempotent=False,
        session_scoped=True,
    ),
    AgentCapability(
        name="send_pf_key",
        description="Send a function key through the desktop contract",
        input_schema=object_schema(required=["key"], properties={"provider": string_schema(), "key": string_schema(), "session_id": string_schema()}),
        output_schema=object_schema(required=["provider"], properties={"provider": string_schema(), "pf_key": string_schema(), "session_id": string_schema()}),
        side_effect_level="medium",
        idempotent=False,
        session_scoped=True,
    ),
    AgentCapability(
        name="find_element",
        description="Locate an element using selectors",
        input_schema=object_schema(properties={"provider": string_schema(), "target": string_schema(), "target_re": string_schema(), "auto_id": string_schema(), "control_type": string_schema(), "best_match": string_schema(), "session_id": string_schema()}),
        output_schema=object_schema(required=["provider"], properties={"provider": string_schema(), "session_id": string_schema()}),
        side_effect_level="none",
        idempotent=True,
        session_scoped=True,
    ),
    AgentCapability(
        name="locate_by_text",
        description="Locate an element by visible text",
        input_schema=object_schema(properties={"provider": string_schema(), "text": string_schema(), "target": string_schema(), "session_id": string_schema()}),
        output_schema=object_schema(required=["provider"], properties={"provider": string_schema(), "session_id": string_schema()}),
        side_effect_level="none",
        idempotent=True,
        session_scoped=True,
    ),
    AgentCapability(
        name="read_screen",
        description="Read visible UI text",
        input_schema=object_schema(properties={"provider": string_schema(), "title": string_schema(), "expected_text": string_schema(), "session_id": string_schema()}),
        output_schema=object_schema(required=["provider"], properties={"provider": string_schema(), "text": string_schema(), "session_id": string_schema()}),
        side_effect_level="none",
        idempotent=True,
        session_scoped=True,
    ),
    AgentCapability(
        name="screenshot",
        description="Capture the current screen",
        input_schema=object_schema(properties={"provider": string_schema(), "output_path": string_schema(), "session_id": string_schema()}),
        output_schema=object_schema(required=["provider"], properties={"provider": string_schema(), "path": string_schema(), "base64_png": string_schema(), "session_id": string_schema()}),
        side_effect_level="none",
        idempotent=True,
        session_scoped=True,
    ),
]

SESSION_STORE = build_session_store(agent_id=SETTINGS.agent_id, channel=SETTINGS.channel, timeout_s=SETTINGS.session_timeout_s)


class DesktopAdapter:
    provider_name = "base"

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class MockDesktopAdapter(DesktopAdapter):
    provider_name = "mock"

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if action == "launch_app":
            return {"provider": self.provider_name, "launched": params.get("application", "unknown")}
        if action in {"attach_window", "activate_window", "wait_for_window"}:
            return {
                "provider": self.provider_name,
                "window": params.get("window") or params.get("target") or "MainWindow",
                "matched": True,
            }
        if action == "send_pf_key":
            return {"provider": self.provider_name, "pf_key": params.get("key"), "ok": True}
        if action in {"click", "type", "press_key", "press_keys", "find_element", "locate_by_text"}:
            return {"provider": self.provider_name, "action": action, "target": params.get("target"), "ok": True}
        if action == "read_screen":
            return {
                "provider": self.provider_name,
                "text": params.get("expected_text", "Mock screen text"),
                "window": params.get("window") or "MainWindow",
            }
        if action == "screenshot":
            return {"provider": self.provider_name, "artifact_hint": "desktop-screenshot-placeholder.png"}
        raise ValueError(f"Unsupported desktop action: {action}")


class PywinautoDesktopAdapter(DesktopAdapter):
    provider_name = "pywinauto"

    def _load_modules(self):
        try:
            pywinauto = importlib.import_module("pywinauto")
            keyboard = importlib.import_module("pywinauto.keyboard")
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError("pywinauto provider requires pywinauto to be installed") from exc
        return pywinauto, keyboard

    def _application(self, params: dict[str, Any]):
        pywinauto, _ = self._load_modules()
        backend = params.get("backend", "uia")
        return pywinauto.Application(backend=backend)

    def _resolve_window(self, params: dict[str, Any], app=None):
        if app is None:
            app = self._application(params)
        if params.get("pid") is not None:
            app = app.connect(process=int(params["pid"]))
        elif params.get("title") or params.get("title_re"):
            app = app.connect(title=params.get("title"), title_re=params.get("title_re"))
        elif params.get("path"):
            app = app.connect(path=params["path"])

        window_spec = {
            "title": params.get("title"),
            "title_re": params.get("title_re"),
            "auto_id": params.get("auto_id"),
            "control_type": params.get("control_type"),
        }
        window_spec = {key: value for key, value in window_spec.items() if value is not None}
        window = app.window(**window_spec) if window_spec else app.top_window()
        return app, window

    def _child(self, window: Any, params: dict[str, Any]):
        child_spec = {
            "title": params.get("target"),
            "title_re": params.get("target_re"),
            "auto_id": params.get("auto_id"),
            "control_type": params.get("control_type"),
            "best_match": params.get("best_match"),
        }
        child_spec = {key: value for key, value in child_spec.items() if value is not None}
        if not child_spec:
            return window
        return window.child_window(**child_spec)

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        _, keyboard = self._load_modules()
        if action == "launch_app":
            app = self._application(params)
            started = app.start(params["application"])
            return {"provider": self.provider_name, "started": params["application"], "pid": getattr(started, "process", None)}
        if action == "send_pf_key":
            keyboard.send_keys(str(params["key"]))
            return {"provider": self.provider_name, "pf_key": params["key"]}

        app, window = self._resolve_window(params)

        if action == "attach_window":
            return {
                "provider": self.provider_name,
                "window_text": window.window_text(),
                "handle": getattr(window, "handle", None),
            }
        if action == "activate_window":
            window.set_focus()
            return {"provider": self.provider_name, "window_text": window.window_text(), "focused": True}
        if action == "wait_for_window":
            timeout = float(params.get("timeout_s", 30))
            window.wait("exists ready visible", timeout=timeout)
            return {"provider": self.provider_name, "window_text": window.window_text(), "ready": True}
        if action == "find_element":
            element = self._child(window, params)
            wrapper = element.wrapper_object()
            return {
                "provider": self.provider_name,
                "control_type": getattr(wrapper.element_info, "control_type", None),
                "name": wrapper.window_text(),
            }
        if action == "locate_by_text":
            params = {**params, "target": params.get("text") or params.get("target")}
            element = self._child(window, params)
            wrapper = element.wrapper_object()
            return {"provider": self.provider_name, "name": wrapper.window_text()}
        if action == "click":
            self._child(window, params).click_input()
            return {"provider": self.provider_name, "clicked": True, "target": params.get("target")}
        if action == "type":
            element = self._child(window, params)
            text = str(params.get("text", ""))
            wrapper = element.wrapper_object() if hasattr(element, "wrapper_object") else element
            edit_target = element if hasattr(element, "set_edit_text") else wrapper
            try:
                if hasattr(edit_target, "set_edit_text"):
                    edit_target.set_edit_text(text)
                else:
                    wrapper.type_keys(text, with_spaces=True, set_foreground=True)
            except Exception:
                fallback_target = wrapper if hasattr(wrapper, "type_keys") else element
                if hasattr(fallback_target, "type_keys"):
                    fallback_target.type_keys(text, with_spaces=True, set_foreground=True)
                else:
                    raise
            return {"provider": self.provider_name, "typed": True, "text": text}
        if action == "press_key":
            keyboard.send_keys(str(params["key"]))
            return {"provider": self.provider_name, "key": params["key"]}
        if action == "press_keys":
            keys = params.get("keys")
            sequence = "".join(keys) if isinstance(keys, list) else str(keys)
            keyboard.send_keys(sequence)
            return {"provider": self.provider_name, "keys": sequence}
        if action == "read_screen":
            descendants = window.descendants()
            texts = [item.window_text() for item in descendants if getattr(item, "window_text", None)]
            texts = [text for text in texts if text]
            return {"provider": self.provider_name, "text": "\n".join(texts[:100]), "line_count": len(texts)}
        if action == "screenshot":
            image = window.capture_as_image()
            output_path = Path(params.get("output_path") or Path(gettempdir()) / "langorch-desktop-screenshot.png")
            if image is None:
                try:
                    image_grab = importlib.import_module("PIL.ImageGrab")
                except ImportError as exc:  # pragma: no cover - environment dependent
                    raise RuntimeError("desktop screenshot fallback requires pillow to be installed") from exc
                rect = window.rectangle()
                image = image_grab.grab(
                    bbox=(rect.left, rect.top, rect.right, rect.bottom),
                    all_screens=True,
                )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            image.save(output_path)
            return {"provider": self.provider_name, "path": str(output_path)}
        raise ValueError(f"Unsupported pywinauto action: {action}")


class WinAppDriverDesktopAdapter(DesktopAdapter):
    provider_name = "winappdriver"

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def _create_session(self, params: dict[str, Any]) -> str:
        capabilities: dict[str, Any] = {}
        if params.get("application"):
            capabilities["app"] = params["application"]
        if params.get("app_top_level_window"):
            capabilities["appTopLevelWindow"] = params["app_top_level_window"]
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{self.base_url}/session",
                json={"capabilities": {"alwaysMatch": capabilities}},
            )
            response.raise_for_status()
            payload = response.json()
        return payload.get("sessionId") or payload.get("value", {}).get("sessionId")

    async def _element_id(self, session_id: str, params: dict[str, Any]) -> str:
        selector = params.get("target")
        using = params.get("using")
        if not selector:
            selector = params.get("text")
            using = using or "name"
        if not selector:
            raise ValueError("target or text is required for element lookup")
        if using is None:
            using = "accessibility id" if params.get("auto_id") else "name"
            selector = params.get("auto_id") or selector
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{self.base_url}/session/{session_id}/element",
                json={"using": using, "value": selector},
            )
            response.raise_for_status()
            payload = response.json().get("value", {})
        return payload.get("ELEMENT") or payload.get("element-6066-11e4-a52e-4f735466cecf")

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        session_id = params.get("session_id")
        if action == "launch_app":
            session_id = await self._create_session(params)
            return {"provider": self.provider_name, "session_id": session_id}
        if not session_id:
            raise ValueError("session_id is required for WinAppDriver operations")

        async with httpx.AsyncClient(timeout=20.0) as client:
            if action == "attach_window":
                return {"provider": self.provider_name, "session_id": session_id}
            if action == "activate_window":
                response = await client.post(f"{self.base_url}/session/{session_id}/window/maximize", json={})
                response.raise_for_status()
                return {"provider": self.provider_name, "session_id": session_id, "focused": True}
            if action == "wait_for_window":
                response = await client.get(f"{self.base_url}/session/{session_id}/title")
                response.raise_for_status()
                return {"provider": self.provider_name, "title": response.json().get("value")}

            if action in {"click", "type", "find_element", "locate_by_text"}:
                element_id = await self._element_id(session_id, params)
                if action == "find_element" or action == "locate_by_text":
                    return {"provider": self.provider_name, "session_id": session_id, "element_id": element_id}
                if action == "click":
                    response = await client.post(f"{self.base_url}/session/{session_id}/element/{element_id}/click", json={})
                    response.raise_for_status()
                    return {"provider": self.provider_name, "session_id": session_id, "clicked": True, "element_id": element_id}
                response = await client.post(
                    f"{self.base_url}/session/{session_id}/element/{element_id}/value",
                    json={"text": str(params.get("text", ""))},
                )
                response.raise_for_status()
                return {"provider": self.provider_name, "session_id": session_id, "typed": True, "element_id": element_id}

            if action in {"press_key", "press_keys"}:
                text = str(params.get("key") or params.get("keys"))
                response = await client.post(
                    f"{self.base_url}/session/{session_id}/keys",
                    json={"text": text},
                )
                response.raise_for_status()
                return {"provider": self.provider_name, "session_id": session_id, "keys": text}
            if action == "send_pf_key":
                response = await client.post(
                    f"{self.base_url}/session/{session_id}/keys",
                    json={"text": str(params['key'])},
                )
                response.raise_for_status()
                return {"provider": self.provider_name, "session_id": session_id, "pf_key": params["key"]}

            if action == "read_screen":
                response = await client.get(f"{self.base_url}/session/{session_id}/source")
                response.raise_for_status()
                return {"provider": self.provider_name, "session_id": session_id, "source": response.json().get("value", "")}

            if action == "screenshot":
                response = await client.get(f"{self.base_url}/session/{session_id}/screenshot")
                response.raise_for_status()
                return {"provider": self.provider_name, "session_id": session_id, "base64_png": response.json().get("value")}

        raise ValueError(f"Unsupported WinAppDriver action: {action}")


class JavaAccessBridgeDesktopAdapter(DesktopAdapter):
    provider_name = "java_access_bridge"

    def _driver(self, params: dict[str, Any]):
        try:
            pyjab = importlib.import_module("pyjab")
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError("java_access_bridge provider requires pyjab to be installed") from exc
        kwargs: dict[str, Any] = {}
        if PROVIDER_SETTINGS.java_access_bridge_path:
            kwargs["bridge_dll"] = PROVIDER_SETTINGS.java_access_bridge_path
        if params.get("title"):
            kwargs["title"] = params["title"]
        return pyjab.JABDriver(**kwargs)

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        driver = self._driver(params)
        target_text = params.get("target") or params.get("text")

        if action == "launch_app":
            return {"provider": self.provider_name, "note": "Java applications should usually be launched externally before attaching."}
        if action == "attach_window":
            return {"provider": self.provider_name, "title": params.get("title"), "attached": True}
        if action == "activate_window":
            if hasattr(driver, "set_focus"):
                driver.set_focus()
            return {"provider": self.provider_name, "focused": True}
        if action == "wait_for_window":
            return {"provider": self.provider_name, "title": params.get("title"), "ready": True}
        if action in {"find_element", "locate_by_text"}:
            element = driver.find_element_by_name(target_text)
            return {"provider": self.provider_name, "name": getattr(element, "name", target_text)}
        if action == "click":
            driver.find_element_by_name(target_text).click()
            return {"provider": self.provider_name, "clicked": True, "target": target_text}
        if action == "type":
            text = str(params.get("text", ""))
            driver.find_element_by_name(target_text).send_text(text)
            return {"provider": self.provider_name, "typed": True, "text": text}
        if action == "press_key":
            if hasattr(driver, "send_keys"):
                driver.send_keys(str(params["key"]))
            return {"provider": self.provider_name, "key": params["key"]}
        if action == "press_keys":
            keys = params.get("keys")
            sequence = "".join(keys) if isinstance(keys, list) else str(keys)
            if hasattr(driver, "send_keys"):
                driver.send_keys(sequence)
            return {"provider": self.provider_name, "keys": sequence}
        if action == "send_pf_key":
            if hasattr(driver, "send_keys"):
                driver.send_keys(str(params["key"]))
            return {"provider": self.provider_name, "pf_key": params["key"]}
        if action == "read_screen":
            root = driver.get_accessible_context_tree()
            return {"provider": self.provider_name, "tree": root}
        if action == "screenshot":
            raise ValueError("Java Access Bridge does not provide screenshot capture; use pywinauto or vision tooling")
        raise ValueError(f"Unsupported Java Access Bridge action: {action}")


def _adapter_for(provider: str) -> DesktopAdapter:
    normalized = provider.strip().lower()
    if normalized == "mock":
        return MockDesktopAdapter()
    if normalized in {"windows_uia", "pywinauto"}:
        return PywinautoDesktopAdapter()
    if normalized == "winappdriver":
        return WinAppDriverDesktopAdapter(PROVIDER_SETTINGS.winappdriver_url)
    if normalized in {"java_access_bridge", "java"}:
        return JavaAccessBridgeDesktopAdapter()
    raise ValueError(f"Unknown desktop provider: {provider}")


async def _close_desktop_session(data: dict[str, Any]) -> None:
    provider = str(data.get("provider") or "").strip().lower()
    session_id = data.get("session_id")
    if provider == "winappdriver" and session_id:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.delete(f"{PROVIDER_SETTINGS.winappdriver_url.rstrip('/')}/session/{session_id}")
            response.raise_for_status()


async def _execute(action: str, params: dict[str, Any], req: AgentExecuteRequest) -> dict[str, Any]:
    provider = str(params.get("provider") or PROVIDER_SETTINGS.provider)
    adapter = _adapter_for(provider)
    result = await adapter.execute(action, params)
    result.setdefault("provider", provider)
    if req.session_id and action in {"launch_app", "attach_window"}:
        persisted: dict[str, Any] = {"provider": provider}
        if isinstance(result, dict):
            for key in ("session_id", "title", "window_text", "handle"):
                value = result.get(key)
                if value is not None:
                    persisted[key] = value
        await SESSION_STORE.update(req.session_id, persisted)
    return result


app = build_agent_app(
    title="LangOrch Universal Desktop Agent",
    version="0.3.0",
    settings=SETTINGS,
    capabilities=CAPABILITIES,
    execute_handler=_execute,
    health_provider=lambda: {
        "provider": PROVIDER_SETTINGS.provider,
        "winappdriver_url": PROVIDER_SETTINGS.winappdriver_url,
    },
    session_store=SESSION_STORE,
    session_close_handler=_close_desktop_session,
)
