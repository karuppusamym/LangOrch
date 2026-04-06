"""Demo Web Agent for LangOrch — full Playwright + CDP automation.

Protocol:
- GET  /health
- GET  /capabilities
- POST /execute  { "action": "<name>", "params": {...}, "run_id": "...", "node_id": "...", "step_id": "..." }

Supported actions
  Core navigation :
    navigate, reload_page, go_back, go_forward, get_current_url, get_page_title
  Element interaction:
    click, double_click, right_click, hover, type, clear_field, select_option,
    check, uncheck, upload_file, drag_and_drop, press_key, focus, blur,
    scroll, scroll_into_view, get_attribute, extract_text, extract_table_data,
    select_all_text
  Dynamic waits:
    wait_for_element, wait_for_navigation, wait_for_load_state,
    wait_for_network_idle, wait_for_url, wait_for_function
  iFrame support:
    switch_frame, switch_main_frame
  Multi-tab:
    new_tab, switch_tab, close_tab, get_tabs
  Cookies / storage:
    get_cookies, set_cookies, clear_cookies,
    get_local_storage, set_local_storage
  JS / CDP:
    evaluate_js, cdp_send, set_viewport, set_geolocation, emulate_device,
    intercept_requests, set_extra_headers
  Screenshot / capture:
    screenshot, close
  DOM introspection + AI locate:
    get_dom, query_dom, get_accessibility_snapshot, ai_locate

Modes:
- Dry-run (default): WEB_AGENT_DRY_RUN=true — deterministic mocks for demos/tests.
- Real browser : WEB_AGENT_DRY_RUN=false  — requires playwright installed.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("web_agent")


@dataclass
class AgentSettings:
    dry_run: bool = True
    headless: bool = True
    # Self-registration: set ORCHESTRATOR_URL to enable auto-registration
    orchestrator_url: str = "http://127.0.0.1:8000"
    agent_id: str = "playwright-web-agent"
    agent_name: str = "Local Playwright Agent"
    agent_port: int = 9000
    channel: str = "web"
    pool_id: str = "web_pool_1"
    resource_key: str = "web_default"
    concurrency_limit: int = 1
    # LLM settings for ai_locate action
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


SETTINGS = AgentSettings(
    dry_run=_as_bool(os.getenv("WEB_AGENT_DRY_RUN"), True),
    headless=_as_bool(os.getenv("WEB_AGENT_HEADLESS"), True),
    orchestrator_url=os.getenv("ORCHESTRATOR_URL", "http://127.0.0.1:8000"),
    agent_id=os.getenv("WEB_AGENT_ID", "playwright-web-agent"),
    agent_name=os.getenv("WEB_AGENT_NAME", "Local Playwright Agent"),
    agent_port=int(os.getenv("WEB_AGENT_PORT", "9000")),
    channel=os.getenv("WEB_AGENT_CHANNEL", "web"),
    pool_id=os.getenv("WEB_AGENT_POOL_ID", "web_pool_1"),
    resource_key=os.getenv("WEB_AGENT_RESOURCE_KEY", "web_default"),
    concurrency_limit=int(os.getenv("WEB_AGENT_CONCURRENCY", "1")),
    llm_api_key=os.getenv("LLM_API_KEY", ""),
    llm_base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
    llm_model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
)


# All actions this agent can handle (drives /capabilities and self-registration)
CAPABILITIES: list[dict[str, Any]] = [
    # ── Core navigation ────────────────────────────────────────────────────────
    {"name": "navigate",              "type": "tool", "is_batch": False},
    {"name": "reload_page",           "type": "tool", "is_batch": False},
    {"name": "go_back",               "type": "tool", "is_batch": False},
    {"name": "go_forward",            "type": "tool", "is_batch": False},
    {"name": "get_current_url",       "type": "tool", "is_batch": False},
    {"name": "get_page_title",        "type": "tool", "is_batch": False},
    # ── Element interaction ─────────────────────────────────────────────────────
    {"name": "click",                 "type": "tool", "is_batch": False},
    {"name": "double_click",          "type": "tool", "is_batch": False},
    {"name": "right_click",           "type": "tool", "is_batch": False},
    {"name": "hover",                 "type": "tool", "is_batch": False},
    {"name": "type",                  "type": "tool", "is_batch": False},
    {"name": "clear_field",           "type": "tool", "is_batch": False},
    {"name": "select_option",         "type": "tool", "is_batch": False},
    {"name": "check",                 "type": "tool", "is_batch": False},
    {"name": "uncheck",               "type": "tool", "is_batch": False},
    {"name": "upload_file",           "type": "tool", "is_batch": False},
    {"name": "drag_and_drop",         "type": "tool", "is_batch": False},
    {"name": "press_key",             "type": "tool", "is_batch": False},
    {"name": "focus",                 "type": "tool", "is_batch": False},
    {"name": "blur",                  "type": "tool", "is_batch": False},
    {"name": "scroll",                "type": "tool", "is_batch": False},
    {"name": "scroll_into_view",      "type": "tool", "is_batch": False},
    {"name": "get_attribute",         "type": "tool", "is_batch": False},
    {"name": "extract_text",          "type": "tool", "is_batch": False},
    {"name": "extract_table_data",    "type": "tool", "is_batch": False},
    {"name": "select_all_text",       "type": "tool", "is_batch": False},
    # ── Dynamic waits ──────────────────────────────────────────────────────────
    {"name": "wait_for_element",      "type": "tool", "is_batch": False},
    {"name": "wait_for_navigation",   "type": "tool", "is_batch": False},
    {"name": "wait_for_load_state",   "type": "tool", "is_batch": False},
    {"name": "wait_for_network_idle", "type": "tool", "is_batch": False},
    {"name": "wait_for_url",          "type": "tool", "is_batch": False},
    {"name": "wait_for_function",     "type": "tool", "is_batch": False},
    # ── iFrame support ─────────────────────────────────────────────────────────
    {"name": "switch_frame",          "type": "tool", "is_batch": False},
    {"name": "switch_main_frame",     "type": "tool", "is_batch": False},
    # ── Multi-tab ──────────────────────────────────────────────────────────────
    {"name": "new_tab",               "type": "tool", "is_batch": False},
    {"name": "switch_tab",            "type": "tool", "is_batch": False},
    {"name": "close_tab",             "type": "tool", "is_batch": False},
    {"name": "get_tabs",              "type": "tool", "is_batch": False},
    # ── Cookies / storage ──────────────────────────────────────────────────────
    {"name": "get_cookies",           "type": "tool", "is_batch": False},
    {"name": "set_cookies",           "type": "tool", "is_batch": False},
    {"name": "clear_cookies",         "type": "tool", "is_batch": False},
    {"name": "get_local_storage",     "type": "tool", "is_batch": False},
    {"name": "set_local_storage",     "type": "tool", "is_batch": False},
    # ── JS / CDP ───────────────────────────────────────────────────────────────
    {"name": "evaluate_js",           "type": "tool", "is_batch": False},
    {"name": "cdp_send",              "type": "tool", "is_batch": False},
    {"name": "set_viewport",          "type": "tool", "is_batch": False},
    {"name": "set_geolocation",       "type": "tool", "is_batch": False},
    {"name": "emulate_device",        "type": "tool", "is_batch": False},
    {"name": "intercept_requests",    "type": "tool", "is_batch": False},
    {"name": "set_extra_headers",     "type": "tool", "is_batch": False},
    # ── Screenshot / session ───────────────────────────────────────────────────
    {"name": "screenshot",            "type": "tool", "is_batch": False},
    {"name": "close",                 "type": "tool", "is_batch": False},
    # ── DOM introspection + AI locate ─────────────────────────────────────────
    {"name": "get_dom",                       "type": "tool", "is_batch": False},
    {"name": "query_dom",                     "type": "tool", "is_batch": False},
    {"name": "get_accessibility_snapshot",    "type": "tool", "is_batch": False},
    {"name": "ai_locate",                     "type": "tool", "is_batch": False},
]


async def _set_agent_status(status: str) -> None:
    """Notify the orchestrator of this agent's online/offline status (and capabilities on startup)."""
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
                    "capabilities": CAPABILITIES
                }
                resp = await client.post(register_url, json=register_payload)
                resp.raise_for_status()
            else:
                resp = await client.put(url, json=payload)
                resp.raise_for_status()
            logger.info(
                "Agent '%s' marked %s (capabilities: %d tools).",
                SETTINGS.agent_id, status, len(CAPABILITIES) if status == "online" else 0,
            )
    except Exception as exc:
        logger.warning(
            "Could not update/register agent status in orchestrator (%s): %s", url, exc
        )


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ANN001
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


app = FastAPI(title="LangOrch Demo Web Agent", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "mode": "dry_run" if SETTINGS.dry_run else "playwright"}


@app.get("/capabilities")
async def capabilities() -> dict[str, Any]:
    """Describe the tools/actions this agent exposes."""
    return {
        "agent_id": SETTINGS.agent_id,
        "channel": SETTINGS.channel,
        "capabilities": CAPABILITIES,
        "mode": "dry_run" if SETTINGS.dry_run else "playwright",
        "description": "Playwright-based web automation agent",
    }


@app.post("/execute")
async def execute(req: ExecuteRequest) -> dict[str, Any]:
    action = req.action.strip().lower()
    try:
        if SETTINGS.dry_run:
            result = await _execute_dry_run(action, req.params)
        else:
            result = await _execute_playwright(action, req.params, req.run_id)
        return {"status": "success", "result": result}
    except Exception as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}


# -----------------------------
# Dry-run mode (default)
# -----------------------------


async def _execute_dry_run(action: str, params: dict[str, Any]) -> dict[str, Any]:
    await asyncio.sleep(0.05)

    if action == "navigate":
        url = params.get("url") or params.get("target") or ""
        title = "Demo Page"
        if isinstance(url, str) and url:
            try:
                async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
                    resp = await client.get(url)
                    text = resp.text or ""
                    m = re.search(r"<title[^>]*>(.*?)</title>", text, flags=re.IGNORECASE | re.DOTALL)
                    if m:
                        title = re.sub(r"\s+", " ", m.group(1)).strip() or title
            except Exception:
                pass
        return {"ok": True, "action": action, "url": url, "title": title}

    if action in {"click", "type", "wait_for_element", "wait"}:
        return {
            "ok": True,
            "action": action,
            "target": params.get("target"),
            "value": params.get("value"),
            "timeout_ms": params.get("timeout_ms"),
        }

    if action == "extract_text":
        return {
            "ok": True,
            "action": action,
            "target": params.get("target"),
            "text": "demo-extracted-text",
        }

    if action == "extract_table_data":
        return {
            "ok": True,
            "action": action,
            "target": params.get("target"),
            "rows": [{"col1": "demo", "col2": "value"}],
        }

    if action == "screenshot":
        return {
            "ok": True,
            "action": action,
            "artifact": {"kind": "screenshot", "uri": "memory://demo-screenshot"},
        }

    if action == "select_all_text":
        target = params.get("target")
        # Deterministic mock: three book titles for books.toscrape.com demos
        texts = [
            "A Light in the Attic",
            "Tipping the Velvet",
            "Soumission",
        ]
        return {
            "ok": True,
            "action": action,
            "target": target,
            "texts": texts,
            "count": len(texts),
            "text": texts[0] if texts else "",
        }

    if action == "get_attribute":
        return {
            "ok": True,
            "action": action,
            "target": params.get("target"),
            "attribute": params.get("attribute", "href"),
            "value": "https://demo-attribute-value.example.com",
        }

    if action == "close":
        return {"ok": True, "action": action}

    if action == "get_dom":
        return {
            "ok": True,
            "action": action,
            "html": "<html><body><button id='demo-btn'>Demo Button</button></body></html>",
            "note": "dry_run mock DOM",
        }

    if action == "query_dom":
        return {
            "ok": True,
            "action": action,
            "elements": [
                {"tag": "button", "id": "demo-btn", "text": "Continue", "visible": True, "selector": "#demo-btn"},
                {"tag": "input", "name": "email", "type": "email", "placeholder": "Email", "visible": True, "selector": "[name='email']"},
            ],
            "count": 2,
            "note": "dry_run mock element list",
        }

    if action == "get_accessibility_snapshot":
        return {
            "ok": True,
            "action": action,
            "snapshot": {"role": "WebArea", "name": "Demo Page", "children": [{"role": "button", "name": "Continue"}]},
            "note": "dry_run mock accessibility tree",
        }

    if action == "ai_locate":
        description = params.get("description") or params.get("element_description", "element")
        return {
            "ok": True,
            "action": action,
            "selector": "button:has-text('Continue')",
            "confidence": 0.9,
            "reason": f"dry_run mock — description: {description}",
        }

    # ── iframe ────────────────────────────────────────────────────────────────
    if action in {"switch_frame", "switch_main_frame"}:
        return {"ok": True, "action": action, "frame_url": "https://demo.example.com/iframe",
                "note": "dry_run mock"}

    # ── dynamic waits ─────────────────────────────────────────────────────────
    if action in {"wait_for_navigation", "wait_for_load_state", "wait_for_network_idle",
                  "wait_for_url"}:
        return {"ok": True, "action": action, "url": "https://demo.example.com/next",
                "state": params.get("state", "load"), "note": "dry_run mock"}

    if action == "wait_for_function":
        return {"ok": True, "action": action, "result": True, "note": "dry_run mock"}

    # ── mouse / keyboard ──────────────────────────────────────────────────────
    if action in {"hover", "double_click", "right_click", "focus", "blur",
                  "scroll_into_view", "drag_and_drop"}:
        return {"ok": True, "action": action, "target": params.get("target"), "note": "dry_run mock"}

    if action == "press_key":
        return {"ok": True, "action": action, "key": params.get("key"),
                "target": params.get("target"), "note": "dry_run mock"}

    if action == "clear_field":
        return {"ok": True, "action": action, "target": params.get("target"),
                "cleared": True, "note": "dry_run mock"}

    if action == "select_option":
        return {"ok": True, "action": action, "target": params.get("target"),
                "selected": [params.get("value") or params.get("label") or "demo-option"],
                "note": "dry_run mock"}

    if action in {"check", "uncheck"}:
        return {"ok": True, "action": action, "target": params.get("target"), "note": "dry_run mock"}

    if action == "upload_file":
        return {"ok": True, "action": action, "target": params.get("target"),
                "file_path": params.get("file_path"), "note": "dry_run mock"}

    if action == "scroll":
        return {"ok": True, "action": action,
                "delta_x": params.get("delta_x", 0), "delta_y": params.get("delta_y", 0),
                "note": "dry_run mock"}

    # ── JS / CDP ──────────────────────────────────────────────────────────────
    if action == "evaluate_js":
        return {"ok": True, "action": action, "result": None,
                "note": "dry_run mock (JS not executed)"}

    if action == "cdp_send":
        return {"ok": True, "action": action, "method": params.get("method"),
                "result": {}, "note": "dry_run mock"}

    if action in {"set_viewport", "set_geolocation", "emulate_device", "set_extra_headers",
                  "intercept_requests"}:
        return {"ok": True, "action": action, "note": "dry_run mock — applied in real mode only"}

    # ── navigation helpers ────────────────────────────────────────────────────
    if action in {"reload_page", "go_back", "go_forward"}:
        return {"ok": True, "action": action, "url": "https://demo.example.com/", "note": "dry_run mock"}

    if action in {"get_current_url", "get_page_title"}:
        return {"ok": True, "action": action, "url": "https://demo.example.com/",
                "title": "Demo Page", "note": "dry_run mock"}

    # ── multi-tab ─────────────────────────────────────────────────────────────
    if action == "new_tab":
        return {"ok": True, "action": action, "tab_index": 1,
                "url": params.get("url", "about:blank"), "note": "dry_run mock"}

    if action in {"switch_tab", "close_tab"}:
        return {"ok": True, "action": action, "tab_index": params.get("index", 0),
                "note": "dry_run mock"}

    if action == "get_tabs":
        return {"ok": True, "action": action,
                "tabs": [{"index": 0, "url": "https://demo.example.com/",
                           "title": "Demo Page", "active": True}],
                "count": 1, "note": "dry_run mock"}

    # ── cookies / storage ─────────────────────────────────────────────────────
    if action == "get_cookies":
        return {"ok": True, "action": action,
                "cookies": [{"name": "session", "value": "demo-token",
                              "domain": "demo.example.com"}],
                "count": 1, "note": "dry_run mock"}

    if action in {"set_cookies", "clear_cookies"}:
        return {"ok": True, "action": action,
                "note": "dry_run mock — cookies updated in real mode only"}

    if action == "get_local_storage":
        key = params.get("key")
        if key:
            return {"ok": True, "action": action, "key": key, "value": "demo-value",
                    "note": "dry_run mock"}
        return {"ok": True, "action": action, "storage": {"demo-key": "demo-value"},
                "note": "dry_run mock"}

    if action == "set_local_storage":
        return {"ok": True, "action": action, "key": params.get("key"),
                "note": "dry_run mock — set in real mode only"}

    return {"ok": True, "action": action, "note": "unsupported action mocked in dry-run"}


# -----------------------------
# Playwright mode (optional)
# -----------------------------


_browser = None
_playwright = None
_pages: dict[str, Any] = {}          # run_id -> active Page
_contexts: dict[str, Any] = {}       # run_id -> BrowserContext
_all_pages: dict[str, list] = {}     # run_id -> [Page, ...]  (multi-tab)
_active_frames: dict[str, Any] = {}  # run_id -> Frame  (set by switch_frame)
_cdp_sessions: dict[str, Any] = {}   # run_id -> CDPSession (cached)


async def _ensure_browser() -> Any:
    global _browser, _playwright
    if _browser is not None:
        return _browser

    try:
        from playwright.async_api import async_playwright
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "Playwright is not installed. Run: pip install playwright; playwright install chromium"
        ) from exc

    _playwright = await async_playwright().start()
    _browser = await _playwright.chromium.launch(headless=SETTINGS.headless)
    return _browser


async def _get_page(run_id: str) -> Any:
    """Return (or create) the active top-level Page for this run."""
    if run_id in _pages:
        return _pages[run_id]

    browser = await _ensure_browser()
    context = await browser.new_context()
    page = await context.new_page()
    _pages[run_id] = page
    _contexts[run_id] = context
    _all_pages[run_id] = [page]
    return page


async def _get_frame(run_id: str) -> Any:
    """Return the active execution context — a Frame (inside an iframe) or the main Page."""
    active = _active_frames.get(run_id)
    if active is not None:
        return active
    return await _get_page(run_id)


async def _execute_playwright(action: str, params: dict[str, Any], run_id: str) -> dict[str, Any]:
    page = await _get_page(run_id)                       # top-level Page (nav, CDP, screenshots)
    frame_ctx = _active_frames.get(run_id, page)         # active ctx: Frame (inside iframe) or Page

    if action == "navigate":
        url = params.get("url") or params.get("target")
        if not isinstance(url, str) or not url:
            raise HTTPException(status_code=422, detail="navigate requires params.url")
        await page.goto(url)
        return {"ok": True, "action": action, "url": page.url, "title": await page.title()}

    if action == "click":
        target = params.get("target")
        await frame_ctx.click(target)
        return {"ok": True, "action": action, "target": target}

    if action == "type":
        target = params.get("target")
        value = str(params.get("value", ""))
        await frame_ctx.fill(target, value)
        return {"ok": True, "action": action, "target": target}

    if action == "wait_for_element":
        target = params.get("target")
        timeout_ms = int(params.get("timeout_ms", 10000))
        await frame_ctx.wait_for_selector(target, timeout=timeout_ms)
        return {"ok": True, "action": action, "target": target}

    if action == "extract_text":
        target = params.get("target")
        text = await frame_ctx.locator(target).first.inner_text()
        return {"ok": True, "action": action, "target": target, "text": text}

    if action == "extract_table_data":
        target = params.get("target")
        rows = await frame_ctx.eval_on_selector_all(
            f"{target} tr",
            """
            (rows) => rows.map((r) =>
              Array.from(r.querySelectorAll('th,td')).map((c) => c.textContent?.trim() || '')
            )
            """,
        )
        return {"ok": True, "action": action, "target": target, "rows": rows}

    if action == "screenshot":
        import os as _os, time as _time, uuid as _uuid
        path = params.get("path")
        if path:
            abs_path = _os.path.abspath(path)
            _os.makedirs(_os.path.dirname(abs_path), exist_ok=True)
            await page.screenshot(path=abs_path, full_page=True)
            # Return raw absolute path so run_service._normalize converts to /api/artifacts/<rel>
            uri = abs_path
        else:
            # Save to run-scoped artifacts folder so the orchestrator can serve it
            run_dir = _os.path.abspath(_os.path.join("./artifacts", run_id))
            _os.makedirs(run_dir, exist_ok=True)
            fname = f"screenshot-{int(_time.time())}-{_uuid.uuid4().hex[:8]}.png"
            abs_path = _os.path.join(run_dir, fname)
            await page.screenshot(path=abs_path, full_page=True)
            uri = abs_path
        return {"ok": True, "action": action, "artifact": {"kind": "screenshot", "uri": uri}}

    if action == "select_all_text":
        target = params.get("target")
        texts = await frame_ctx.eval_on_selector_all(
            target,
            "(els) => els.map(e => e.textContent ? e.textContent.trim() : '')",
        )
        return {
            "ok": True,
            "action": action,
            "target": target,
            "texts": texts,
            "count": len(texts),
            "text": texts[0] if texts else "",
        }

    if action == "get_attribute":
        target = params.get("target")
        attr = params.get("attribute", "href")
        value = await frame_ctx.get_attribute(target, attr)
        return {"ok": True, "action": action, "target": target, "attribute": attr, "value": value}

    if action == "close":
        pg = _pages.pop(run_id, None)
        _active_frames.pop(run_id, None)
        _all_pages.pop(run_id, None)
        _cdp_sessions.pop(run_id, None)
        _contexts.pop(run_id, None)
        if pg is not None:
            await pg.context.close()
        return {"ok": True, "action": action}

    if action == "get_dom":
        scope = params.get("scope")  # optional CSS selector to scope
        clean = params.get("clean", True)  # strip script/style tags
        if scope:
            html: str = await frame_ctx.eval_on_selector(
                scope,
                "(el) => el.outerHTML",
            )
        else:
            html = await frame_ctx.content()
        if clean:
            html = _strip_html_for_llm(html)
        return {"ok": True, "action": action, "html": html, "length": len(html)}

    if action == "query_dom":
        scope = params.get(
            "scope",
            "input, button, a, select, textarea, [role='button'], [role='combobox'], "
            "[role='listbox'], [role='option'], [role='tab'], [tabindex]",
        )
        max_elems = int(params.get("max_elements", 100))
        elements = await frame_ctx.eval_on_selector_all(
            scope,
            """
            (els) => els.map(el => ({
                tag: el.tagName.toLowerCase(),
                id: el.id || null,
                name: el.getAttribute('name') || null,
                type: el.getAttribute('type') || null,
                placeholder: el.getAttribute('placeholder') || null,
                aria_label: el.getAttribute('aria-label') || null,
                role: el.getAttribute('role') || null,
                href: el.tagName === 'A' ? el.getAttribute('href') : null,
                text: (el.textContent || '').trim().slice(0, 120),
                visible: el.offsetParent !== null,
                class: (el.getAttribute('class') || '').slice(0, 80),
            }))
            """,
        )
        # Filter to visible elements first, then cap total
        visible = [e for e in elements if e.get("visible")]
        result_elems = visible[:max_elems] if len(visible) >= max_elems // 2 else elements[:max_elems]
        return {
            "ok": True,
            "action": action,
            "elements": result_elems,
            "count": len(result_elems),
            "total_found": len(elements),
        }

    if action == "get_accessibility_snapshot":
        interesting_only = params.get("interesting_only", True)
        snapshot = await page.accessibility.snapshot(interesting_only=interesting_only)
        return {"ok": True, "action": action, "snapshot": snapshot}

    if action == "ai_locate":
        description = params.get("description") or params.get("element_description", "")
        if not description:
            return {"ok": False, "action": action, "error": "ai_locate requires 'description' param"}
        selector, confidence, reason = await _ai_locate_element(frame_ctx, description)
        return {
            "ok": True,
            "action": action,
            "selector": selector,
            "confidence": confidence,
            "reason": reason,
        }

    # ── iFrame support ────────────────────────────────────────────────────────

    if action == "switch_frame":
        selector   = params.get("frame_selector")
        name       = params.get("frame_name")
        url_pat    = params.get("frame_url")
        index      = params.get("frame_index")
        target_frame = None
        if selector:
            elem = await page.query_selector(selector)
            if elem is None:
                return {"ok": False, "action": action,
                        "error": f"No element found for selector: {selector!r}"}
            target_frame = await elem.content_frame()
        elif name:
            target_frame = page.frame(name=name)
        elif url_pat:
            target_frame = page.frame(url=url_pat)
        elif index is not None:
            frames = page.frames
            idx = int(index)
            if idx < len(frames):
                target_frame = frames[idx]
            else:
                return {"ok": False, "action": action,
                        "error": f"Frame index {idx} out of range (total: {len(frames)})"}
        else:
            return {"ok": False, "action": action,
                    "error": "switch_frame requires frame_selector, frame_name, frame_url, or frame_index"}
        if target_frame is None:
            return {"ok": False, "action": action, "error": "Could not resolve target frame"}
        _active_frames[run_id] = target_frame
        return {"ok": True, "action": action, "frame_url": target_frame.url}

    if action == "switch_main_frame":
        _active_frames.pop(run_id, None)
        return {"ok": True, "action": action, "url": page.url}

    # ── Dynamic waits ─────────────────────────────────────────────────────────

    if action == "wait_for_navigation":
        timeout_ms  = int(params.get("timeout_ms", 30000))
        url_pat     = params.get("url")
        wait_until  = params.get("wait_until", "load")
        if url_pat:
            await page.wait_for_url(url_pat, timeout=timeout_ms, wait_until=wait_until)
        else:
            await page.wait_for_load_state(wait_until, timeout=timeout_ms)
        return {"ok": True, "action": action, "url": page.url}

    if action == "wait_for_load_state":
        state      = params.get("state", "load")   # load | domcontentloaded | networkidle
        timeout_ms = int(params.get("timeout_ms", 30000))
        await page.wait_for_load_state(state, timeout=timeout_ms)
        return {"ok": True, "action": action, "state": state, "url": page.url}

    if action == "wait_for_network_idle":
        timeout_ms = int(params.get("timeout_ms", 30000))
        await page.wait_for_load_state("networkidle", timeout=timeout_ms)
        return {"ok": True, "action": action, "url": page.url}

    if action == "wait_for_url":
        url_pat    = params.get("url") or params.get("pattern")
        if not url_pat:
            return {"ok": False, "action": action,
                    "error": "wait_for_url requires 'url' param (glob or regex string)"}
        timeout_ms = int(params.get("timeout_ms", 30000))
        wait_until = params.get("wait_until", "load")
        await page.wait_for_url(url_pat, timeout=timeout_ms, wait_until=wait_until)
        return {"ok": True, "action": action, "url": page.url}

    if action == "wait_for_function":
        expression = params.get("expression") or params.get("js")
        if not expression:
            return {"ok": False, "action": action,
                    "error": "wait_for_function requires 'expression' param"}
        timeout_ms = int(params.get("timeout_ms", 30000))
        polling    = params.get("polling", "raf")   # "raf" or interval ms
        handle     = await frame_ctx.wait_for_function(expression, timeout=timeout_ms,
                                                        polling=polling)
        try:
            result_val = await handle.json_value()
        except Exception:
            result_val = True   # truthy but not JSON-serialisable
        return {"ok": True, "action": action, "result": result_val}

    # ── Mouse / keyboard ──────────────────────────────────────────────────────

    if action == "hover":
        target     = params.get("target")
        timeout_ms = int(params.get("timeout_ms", 10000))
        await frame_ctx.hover(target, timeout=timeout_ms)
        return {"ok": True, "action": action, "target": target}

    if action == "double_click":
        target     = params.get("target")
        timeout_ms = int(params.get("timeout_ms", 10000))
        await frame_ctx.dblclick(target, timeout=timeout_ms)
        return {"ok": True, "action": action, "target": target}

    if action == "right_click":
        target     = params.get("target")
        timeout_ms = int(params.get("timeout_ms", 10000))
        await frame_ctx.click(target, button="right", timeout=timeout_ms)
        return {"ok": True, "action": action, "target": target}

    if action == "press_key":
        key    = params.get("key")
        target = params.get("target")   # optional: focus this element first
        if not key:
            return {"ok": False, "action": action, "error": "press_key requires 'key' param"}
        if target:
            await frame_ctx.locator(target).press(key)
        else:
            await page.keyboard.press(key)
        return {"ok": True, "action": action, "key": key, "target": target}

    if action == "focus":
        target     = params.get("target")
        timeout_ms = int(params.get("timeout_ms", 10000))
        await frame_ctx.focus(target, timeout=timeout_ms)
        return {"ok": True, "action": action, "target": target}

    if action == "blur":
        target = params.get("target")
        await frame_ctx.eval_on_selector(target, "(el) => el.blur()")
        return {"ok": True, "action": action, "target": target}

    # ── Form actions ──────────────────────────────────────────────────────────

    if action == "clear_field":
        target     = params.get("target")
        value      = params.get("value")        # if provided, type after clearing
        timeout_ms = int(params.get("timeout_ms", 10000))
        await frame_ctx.wait_for_selector(target, timeout=timeout_ms)
        await frame_ctx.fill(target, "")
        if value is not None:
            await frame_ctx.fill(target, str(value))
        return {"ok": True, "action": action, "target": target, "cleared": True}

    if action == "select_option":
        target = params.get("target")
        if not target:
            return {"ok": False, "action": action, "error": "select_option requires 'target' param"}
        value  = params.get("value")
        label  = params.get("label")
        index  = params.get("index")
        if value is not None:
            selected = await frame_ctx.select_option(target, value=str(value))
        elif label is not None:
            selected = await frame_ctx.select_option(target, label=str(label))
        elif index is not None:
            selected = await frame_ctx.select_option(target, index=int(index))
        else:
            return {"ok": False, "action": action,
                    "error": "select_option requires 'value', 'label', or 'index'"}
        return {"ok": True, "action": action, "target": target, "selected": selected}

    if action == "check":
        target     = params.get("target")
        timeout_ms = int(params.get("timeout_ms", 10000))
        await frame_ctx.check(target, timeout=timeout_ms)
        return {"ok": True, "action": action, "target": target}

    if action == "uncheck":
        target     = params.get("target")
        timeout_ms = int(params.get("timeout_ms", 10000))
        await frame_ctx.uncheck(target, timeout=timeout_ms)
        return {"ok": True, "action": action, "target": target}

    if action == "upload_file":
        target    = params.get("target")
        file_path = params.get("file_path") or params.get("path")
        if not target or not file_path:
            return {"ok": False, "action": action,
                    "error": "upload_file requires 'target' (file input selector) and 'file_path'"}
        abs_path = os.path.abspath(file_path)
        await frame_ctx.set_input_files(target, abs_path)
        return {"ok": True, "action": action, "target": target, "file_path": abs_path}

    if action == "drag_and_drop":
        source     = params.get("source") or params.get("from")
        target_sel = params.get("target") or params.get("to")
        if not source or not target_sel:
            return {"ok": False, "action": action,
                    "error": "drag_and_drop requires 'source' and 'target' params"}
        await frame_ctx.drag_and_drop(source, target_sel)
        return {"ok": True, "action": action, "source": source, "target": target_sel}

    if action == "scroll":
        target  = params.get("target")         # optional: element to scroll within
        delta_x = int(params.get("delta_x", 0))
        delta_y = int(params.get("delta_y", 0))
        if target:
            await frame_ctx.eval_on_selector(
                target,
                f"(el) => {{ el.scrollBy({delta_x}, {delta_y}); }}",
            )
        else:
            await page.mouse.wheel(delta_x, delta_y)
        return {"ok": True, "action": action, "delta_x": delta_x, "delta_y": delta_y}

    if action == "scroll_into_view":
        target = params.get("target")
        if not target:
            return {"ok": False, "action": action, "error": "scroll_into_view requires 'target'"}
        await frame_ctx.locator(target).first.scroll_into_view_if_needed()
        return {"ok": True, "action": action, "target": target}

    # ── Navigation helpers ────────────────────────────────────────────────────

    if action == "reload_page":
        timeout_ms = int(params.get("timeout_ms", 30000))
        wait_until = params.get("wait_until", "load")
        await page.reload(timeout=timeout_ms, wait_until=wait_until)
        return {"ok": True, "action": action, "url": page.url}

    if action == "go_back":
        timeout_ms = int(params.get("timeout_ms", 30000))
        wait_until = params.get("wait_until", "load")
        await page.go_back(timeout=timeout_ms, wait_until=wait_until)
        return {"ok": True, "action": action, "url": page.url}

    if action == "go_forward":
        timeout_ms = int(params.get("timeout_ms", 30000))
        wait_until = params.get("wait_until", "load")
        await page.go_forward(timeout=timeout_ms, wait_until=wait_until)
        return {"ok": True, "action": action, "url": page.url}

    if action == "get_current_url":
        return {"ok": True, "action": action, "url": page.url}

    if action == "get_page_title":
        return {"ok": True, "action": action, "title": await page.title()}

    # ── Multi-tab ─────────────────────────────────────────────────────────────

    if action == "new_tab":
        url = params.get("url")
        ctx = _contexts.get(run_id)
        if ctx is None:
            await _get_page(run_id)   # ensures context is created
            ctx = _contexts[run_id]
        new_page = await ctx.new_page()
        if url:
            await new_page.goto(url)
        _all_pages.setdefault(run_id, [_pages[run_id]])
        _all_pages[run_id].append(new_page)
        _pages[run_id] = new_page
        _active_frames.pop(run_id, None)
        tab_index = len(_all_pages[run_id]) - 1
        return {"ok": True, "action": action, "tab_index": tab_index, "url": new_page.url}

    if action == "switch_tab":
        index    = params.get("index")
        title    = params.get("title")
        url_pat  = params.get("url")
        pages    = _all_pages.get(run_id, [page])
        target_p = None
        if index is not None:
            idx = int(index)
            if 0 <= idx < len(pages):
                target_p = pages[idx]
            else:
                return {"ok": False, "action": action,
                        "error": f"Tab index {idx} out of range (open: {len(pages)})"}
        elif title:
            for pg in pages:
                if title.lower() in (await pg.title()).lower():
                    target_p = pg
                    break
        elif url_pat:
            for pg in pages:
                if url_pat in pg.url:
                    target_p = pg
                    break
        if target_p is None:
            return {"ok": False, "action": action, "error": "No matching tab found"}
        _pages[run_id] = target_p
        _active_frames.pop(run_id, None)
        return {"ok": True, "action": action, "url": target_p.url,
                "title": await target_p.title()}

    if action == "close_tab":
        index   = params.get("index")
        pages   = _all_pages.get(run_id, [])
        current = _pages.get(run_id)
        if index is not None:
            idx = int(index)
            if 0 <= idx < len(pages):
                pg_to_close = pages[idx]
                await pg_to_close.close()
                pages.pop(idx)
                if pg_to_close is current:
                    _pages[run_id] = pages[-1] if pages else None
            else:
                return {"ok": False, "action": action,
                        "error": f"Tab index {idx} out of range"}
        elif current:
            await current.close()
            remaining = [p for p in pages if p is not current]
            _all_pages[run_id] = remaining
            _pages[run_id] = remaining[-1] if remaining else None
        return {"ok": True, "action": action,
                "remaining_tabs": len(_all_pages.get(run_id, []))}

    if action == "get_tabs":
        pages   = _all_pages.get(run_id, [page] if run_id in _pages else [])
        current = _pages.get(run_id)
        tabs: list[dict[str, Any]] = []
        for i, pg in enumerate(pages):
            if pg is not None:
                tabs.append({"index": i, "url": pg.url,
                             "title": await pg.title(), "active": pg is current})
        return {"ok": True, "action": action, "tabs": tabs, "count": len(tabs)}

    # ── Cookies / storage ─────────────────────────────────────────────────────

    if action == "get_cookies":
        ctx = _contexts.get(run_id)
        if ctx is None:
            return {"ok": False, "action": action, "error": "No browser context for run_id"}
        url_f   = params.get("url")
        cookies = await ctx.cookies([url_f]) if url_f else await ctx.cookies()
        return {"ok": True, "action": action, "cookies": cookies, "count": len(cookies)}

    if action == "set_cookies":
        ctx = _contexts.get(run_id)
        if ctx is None:
            return {"ok": False, "action": action, "error": "No browser context for run_id"}
        cookies = params.get("cookies", [])
        if not isinstance(cookies, list):
            cookies = [cookies]
        await ctx.add_cookies(cookies)
        return {"ok": True, "action": action, "count": len(cookies)}

    if action == "clear_cookies":
        ctx = _contexts.get(run_id)
        if ctx is None:
            return {"ok": False, "action": action, "error": "No browser context for run_id"}
        await ctx.clear_cookies()
        return {"ok": True, "action": action}

    if action == "get_local_storage":
        key = params.get("key")
        if key:
            value = await page.evaluate("(k) => localStorage.getItem(k)", key)
            return {"ok": True, "action": action, "key": key, "value": value}
        storage = await page.evaluate(
            "() => Object.fromEntries(Object.entries(localStorage))"
        )
        return {"ok": True, "action": action, "storage": storage}

    if action == "set_local_storage":
        key   = params.get("key")
        value = params.get("value")
        if not key:
            return {"ok": False, "action": action, "error": "set_local_storage requires 'key'"}
        await page.evaluate("([k, v]) => localStorage.setItem(k, v)", [key, str(value)])
        return {"ok": True, "action": action, "key": key}

    # ── JS / CDP ──────────────────────────────────────────────────────────────

    if action == "evaluate_js":
        expression = params.get("expression") or params.get("js")
        if not expression:
            return {"ok": False, "action": action, "error": "evaluate_js requires 'expression'"}
        arg = params.get("arg")
        result = await frame_ctx.evaluate(expression, arg) if arg is not None \
            else await frame_ctx.evaluate(expression)
        return {"ok": True, "action": action, "result": result}

    if action == "cdp_send":
        method     = params.get("method")
        cdp_params = params.get("cdp_params") or params.get("params") or {}
        if not method:
            return {"ok": False, "action": action,
                    "error": "cdp_send requires 'method' (e.g. 'Runtime.evaluate')"}
        ctx = _contexts.get(run_id)
        if ctx is None:
            return {"ok": False, "action": action, "error": "No browser context for run_id"}
        cdp = _cdp_sessions.get(run_id)
        if cdp is None:
            cdp = await ctx.new_cdp_session(page)
            _cdp_sessions[run_id] = cdp
        result = await cdp.send(method, cdp_params)
        return {"ok": True, "action": action, "method": method, "result": result}

    if action == "set_viewport":
        width  = int(params.get("width", 1280))
        height = int(params.get("height", 720))
        await page.set_viewport_size({"width": width, "height": height})
        return {"ok": True, "action": action, "width": width, "height": height}

    if action == "set_geolocation":
        ctx = _contexts.get(run_id)
        if ctx is None:
            return {"ok": False, "action": action,
                    "error": "No browser context — call navigate first"}
        lat      = float(params.get("latitude",  0.0))
        lon      = float(params.get("longitude", 0.0))
        accuracy = float(params.get("accuracy",  10.0))
        await ctx.set_geolocation({"latitude": lat, "longitude": lon, "accuracy": accuracy})
        return {"ok": True, "action": action, "latitude": lat, "longitude": lon}

    if action == "emulate_device":
        device_name = params.get("device_name")
        if device_name and _playwright is not None:
            devices = _playwright.devices
            if device_name not in devices:
                return {"ok": False, "action": action,
                        "error": f"Device '{device_name}' not found in playwright.devices"}
            descriptor  = devices[device_name]
            new_context = await _browser.new_context(**descriptor)
            new_page    = await new_context.new_page()
            old_ctx     = _contexts.get(run_id)
            if old_ctx:
                await old_ctx.close()
            _pages[run_id]        = new_page
            _contexts[run_id]     = new_context
            _all_pages[run_id]    = [new_page]
            _active_frames.pop(run_id, None)
            _cdp_sessions.pop(run_id, None)
            return {"ok": True, "action": action, "device_name": device_name,
                    "viewport": descriptor.get("viewport")}
        # Manual viewport emulation
        w = params.get("width")
        h = params.get("height")
        if w and h:
            await page.set_viewport_size({"width": int(w), "height": int(h)})
        return {"ok": True, "action": action,
                "note": "Viewport resized; use device_name for full emulation"}

    if action == "intercept_requests":
        url_pattern  = params.get("url_pattern") or params.get("pattern", "**")
        mode         = params.get("mode", "block")   # block | mock | unroute
        mock_body    = params.get("mock_body", "")
        mock_status  = int(params.get("mock_status", 200))
        mock_headers = params.get("mock_headers", {"Content-Type": "application/json"})
        ctx = _contexts.get(run_id)
        if ctx is None:
            return {"ok": False, "action": action, "error": "No browser context for run_id"}
        if mode == "block":
            async def _block(route: Any) -> None:
                await route.abort()
            await ctx.route(url_pattern, _block)
        elif mode == "mock":
            _status  = mock_status
            _body    = mock_body
            _headers = mock_headers

            async def _mock(route: Any) -> None:
                await route.fulfill(status=_status, body=_body, headers=_headers)
            await ctx.route(url_pattern, _mock)
        else:   # "unroute" / "passthrough"
            await ctx.unroute(url_pattern)
        return {"ok": True, "action": action, "url_pattern": url_pattern, "mode": mode}

    if action == "set_extra_headers":
        headers = params.get("headers", {})
        ctx = _contexts.get(run_id)
        if ctx is None:
            return {"ok": False, "action": action, "error": "No browser context for run_id"}
        await ctx.set_extra_http_headers(headers)
        return {"ok": True, "action": action, "headers": list(headers.keys())}

    return {"ok": True, "action": action, "note": "unsupported action"}


# ── DOM HTML cleaner ─────────────────────────────────────────────────────────

def _strip_html_for_llm(html: str) -> str:
    """Remove <script>, <style>, <svg>, HTML comments to reduce token count."""
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<svg[^>]*>.*?</svg>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)
    # Collapse runs of whitespace
    html = re.sub(r'\s{3,}', ' ', html)
    return html.strip()


# ── LLM-assisted element locator ─────────────────────────────────────────────

async def _ai_locate_element(page: Any, description: str) -> tuple[str, float, str]:
    """Query the live DOM and ask the LLM to identify the best CSS selector.

    Returns:
        (selector, confidence, reason)
    Falls back to an empty selector on any error so the caller can handle gracefully.
    """
    if not SETTINGS.llm_api_key:
        logger.warning("ai_locate: LLM_API_KEY not set — cannot call LLM")
        return ("", 0.0, "LLM_API_KEY not configured")

    # Step 1: collect structured element list (compact, token-efficient)
    try:
        elements = await page.eval_on_selector_all(
            "input, button, a, select, textarea, [role='button'], [role='combobox'], "
            "[role='listbox'], [role='option'], [role='tab'], label",
            """
            (els) => els.filter(el => el.offsetParent !== null).slice(0, 80).map(el => ({
                tag: el.tagName.toLowerCase(),
                id: el.id || null,
                name: el.getAttribute('name') || null,
                type: el.getAttribute('type') || null,
                placeholder: el.getAttribute('placeholder') || null,
                aria_label: el.getAttribute('aria-label') || null,
                role: el.getAttribute('role') || null,
                text: (el.textContent || '').trim().slice(0, 80),
                href: el.tagName === 'A' ? el.getAttribute('href') : null,
                class: (el.getAttribute('class') || '').slice(0, 60),
            }))
            """,
        )
    except Exception as exc:
        logger.warning("ai_locate: DOM query failed: %s", exc)
        return ("", 0.0, f"DOM query failed: {exc}")

    import json as _json

    prompt = (
        f"You are a Playwright automation expert.\n"
        f"The page has these visible interactive elements (JSON array):\n"
        f"{_json.dumps(elements, indent=2)}\n\n"
        f"Find the element that best matches this description: \"{description}\"\n\n"
        f"Return ONLY valid JSON with this exact shape (no markdown, no explanation):\n"
        f'{{ "selector": "<css_selector>", "confidence": <0.0-1.0>, "reason": "<one sentence>" }}'
    )

    url = f"{SETTINGS.llm_base_url.rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {SETTINGS.llm_api_key}",
    }
    body = {
        "model": SETTINGS.llm_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        raw = data["choices"][0]["message"]["content"]
        parsed = _json.loads(raw)
        selector = str(parsed.get("selector", ""))
        confidence = float(parsed.get("confidence", 0.0))
        reason = str(parsed.get("reason", ""))
        logger.info(
            "ai_locate: description=%r selector=%r confidence=%.2f reason=%r",
            description, selector, confidence, reason,
        )
        return (selector, confidence, reason)

    except Exception as exc:
        logger.warning("ai_locate: LLM call failed: %s", exc)
        return ("", 0.0, f"LLM error: {exc}")
