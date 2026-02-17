"""Demo Web Agent for LangOrch.

Protocol:
- GET /health
- POST /execute with body:
  {
    "action": "navigate|click|type|wait_for_element|extract_text|extract_table_data|screenshot|close",
    "params": {...},
    "run_id": "...",
    "node_id": "...",
    "step_id": "..."
  }

Modes:
- Dry-run (default): WEB_AGENT_DRY_RUN=true
  Returns deterministic mock responses for demos/tests.
- Real browser mode: WEB_AGENT_DRY_RUN=false + playwright installed.
"""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


@dataclass
class AgentSettings:
    dry_run: bool = True
    headless: bool = True


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


SETTINGS = AgentSettings(
    dry_run=_as_bool(os.getenv("WEB_AGENT_DRY_RUN"), True),
    headless=_as_bool(os.getenv("WEB_AGENT_HEADLESS"), True),
)


class ExecuteRequest(BaseModel):
    action: str
    params: dict[str, Any] = Field(default_factory=dict)
    run_id: str
    node_id: str
    step_id: str


app = FastAPI(title="LangOrch Demo Web Agent", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "mode": "dry_run" if SETTINGS.dry_run else "playwright"}


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

    if action == "close":
        return {"ok": True, "action": action}

    return {"ok": True, "action": action, "note": "unsupported action mocked in dry-run"}


# -----------------------------
# Playwright mode (optional)
# -----------------------------


_browser = None
_playwright = None
_pages: dict[str, Any] = {}


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
    if run_id in _pages:
        return _pages[run_id]

    browser = await _ensure_browser()
    context = await browser.new_context()
    page = await context.new_page()
    _pages[run_id] = page
    return page


async def _execute_playwright(action: str, params: dict[str, Any], run_id: str) -> dict[str, Any]:
    page = await _get_page(run_id)

    if action == "navigate":
        url = params.get("url") or params.get("target")
        if not isinstance(url, str) or not url:
            raise HTTPException(status_code=422, detail="navigate requires params.url")
        await page.goto(url)
        return {"ok": True, "action": action, "url": page.url, "title": await page.title()}

    if action == "click":
        target = params.get("target")
        await page.click(target)
        return {"ok": True, "action": action, "target": target}

    if action == "type":
        target = params.get("target")
        value = str(params.get("value", ""))
        await page.fill(target, value)
        return {"ok": True, "action": action, "target": target}

    if action == "wait_for_element":
        target = params.get("target")
        timeout_ms = int(params.get("timeout_ms", 10000))
        await page.wait_for_selector(target, timeout=timeout_ms)
        return {"ok": True, "action": action, "target": target}

    if action == "extract_text":
        target = params.get("target")
        text = await page.locator(target).first.inner_text()
        return {"ok": True, "action": action, "target": target, "text": text}

    if action == "extract_table_data":
        target = params.get("target")
        rows = await page.eval_on_selector_all(
            f"{target} tr",
            """
            (rows) => rows.map((r) =>
              Array.from(r.querySelectorAll('th,td')).map((c) => c.textContent?.trim() || '')
            )
            """,
        )
        return {"ok": True, "action": action, "target": target, "rows": rows}

    if action == "screenshot":
        path = params.get("path")
        if path:
            await page.screenshot(path=path, full_page=True)
            uri = f"file://{path}"
        else:
            _ = await page.screenshot(full_page=True)
            uri = "memory://playwright-screenshot"
        return {"ok": True, "action": action, "artifact": {"kind": "screenshot", "uri": uri}}

    if action == "close":
        pg = _pages.pop(run_id, None)
        if pg is not None:
            await pg.context.close()
        return {"ok": True, "action": action}

    return {"ok": True, "action": action, "note": "unsupported action"}
