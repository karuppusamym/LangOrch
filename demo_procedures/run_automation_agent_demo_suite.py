from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from aiosmtpd.controller import Controller


ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = Path(__file__).resolve().parent
API_BASE = os.getenv("LANGORCH_BASE_URL", "http://127.0.0.1:8000")
TIMEOUT = 30


def _request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = Request(
        f"{API_BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed with HTTP {exc.code}: {detail}") from exc
    return json.loads(body.decode("utf-8")) if body else {}


def import_procedure(path: Path) -> dict[str, Any]:
    ckp = json.loads(path.read_text(encoding="utf-8"))
    try:
        _request("GET", f"/api/procedures/{ckp['procedure_id']}/{ckp['version']}")
        return _request("PUT", f"/api/procedures/{ckp['procedure_id']}/{ckp['version']}", {"ckp_json": ckp})
    except RuntimeError as exc:
        if "HTTP 404" not in str(exc):
            raise
    try:
        return _request("POST", "/api/procedures", {"ckp_json": ckp})
    except RuntimeError as exc:
        if "HTTP 409" not in str(exc):
            raise
        return _request("PUT", f"/api/procedures/{ckp['procedure_id']}/{ckp['version']}", {"ckp_json": ckp})


def create_run(procedure_id: str, input_vars: dict[str, Any] | None = None, version: str = "1.0.0") -> dict[str, Any]:
    return _request(
        "POST",
        "/api/runs",
        {
            "procedure_id": procedure_id,
            "procedure_version": version,
            "input_vars": input_vars or {},
        },
    )


def get_run(run_id: str) -> dict[str, Any]:
    return _request("GET", f"/api/runs/{run_id}")


def wait_for_run(run_id: str, timeout_s: int = 180) -> dict[str, Any]:
    started = time.time()
    last_status = None
    while time.time() - started < timeout_s:
        try:
            run = get_run(run_id)
        except RuntimeError as exc:
            if "HTTP 404" in str(exc):
                time.sleep(1)
                continue
            raise
        status = run.get("status")
        if status != last_status:
            print(f"[{run_id}] status={status}")
            last_status = status
        if status in {"completed", "failed", "cancelled", "canceled"}:
            return run
        time.sleep(2)
    raise TimeoutError(f"Run {run_id} did not reach a terminal state within {timeout_s}s")


class SmtpSinkHandler:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def handle_DATA(self, server, session, envelope) -> str:  # noqa: N802
        parsed = BytesParser(policy=default).parsebytes(envelope.content)
        self.messages.append(
            {
                "mail_from": envelope.mail_from,
                "rcpt_tos": envelope.rcpt_tos,
                "subject": parsed.get("Subject"),
                "body": parsed.get_body(preferencelist=("plain",)).get_content() if parsed.get_body() else parsed.as_string(),
            }
        )
        return "250 Message accepted for delivery"


@dataclass
class DemoCase:
    name: str
    procedure_file: Path
    input_vars: dict[str, Any]
    timeout_s: int = 180
    post_check: callable | None = None


def _kill_desktop_demo_apps() -> None:
    subprocess.run(["taskkill", "/IM", "notepad.exe", "/F"], capture_output=True, text=True, check=False)
    subprocess.run(["taskkill", "/IM", "notepad++.exe", "/F"], capture_output=True, text=True, check=False)


def _assert_file_artifact(run: dict[str, Any], relative_path: str) -> None:
    path = ROOT / "artifacts" / run["run_id"] / relative_path
    if not path.exists():
        raise AssertionError(f"Expected artifact file not found: {path}")


def main() -> int:
    smtp_handler = SmtpSinkHandler()
    controller = Controller(smtp_handler, hostname="127.0.0.1", port=8025)
    controller.start()
    _kill_desktop_demo_apps()

    try:
        cases = [
            DemoCase(
                name="web-books-actual",
                procedure_file=ROOT / "ckp_file-main" / "books_price_monitor.ckp.json",
                input_vars={"catalogue_url": "https://books.toscrape.com/catalogue/page-1.html"},
                timeout_s=180,
            ),
            DemoCase(
                name="integration-api-actual",
                procedure_file=DEMO_DIR / "automation_api_http_demo.ckp.json",
                input_vars={
                    "rest_url": "https://jsonplaceholder.typicode.com/todos/1",
                    "graphql_url": "https://countries.trevorblades.com/",
                },
            ),
            DemoCase(
                name="file-roundtrip-actual",
                procedure_file=DEMO_DIR / "automation_file_roundtrip_demo.ckp.json",
                input_vars={"artifacts_base_dir": str(ROOT / "artifacts").replace("\\", "/")},
            ),
            DemoCase(
                name="database-sqlite-actual",
                procedure_file=DEMO_DIR / "automation_database_sqlite_demo.ckp.json",
                input_vars={"artifacts_base_dir": str(ROOT / "artifacts").replace("\\", "/")},
            ),
            DemoCase(
                name="email-smtp-actual",
                procedure_file=DEMO_DIR / "automation_email_smtp_demo.ckp.json",
                input_vars={
                    "smtp_host": "127.0.0.1",
                    "smtp_port": 8025,
                    "from_email": "langorch-demo@example.com",
                    "to_email": "sink@example.com",
                },
            ),
            DemoCase(
                name="desktop-notepad-actual",
                procedure_file=DEMO_DIR / "automation_desktop_notepad_demo.ckp.json",
                input_vars={
                    "artifacts_base_dir": str(ROOT / "artifacts").replace("\\", "/"),
                    "desktop_text": "LangOrch desktop demo typed through pywinauto.",
                    "desktop_application": "\"C:/Program Files/Notepad++/notepad++.exe\" -multiInst -nosession",
                },
                timeout_s=120,
            ),
            DemoCase(
                name="swarm-failure-analysis-actual",
                procedure_file=DEMO_DIR / "automation_swarm_failure_analysis_demo.ckp.json",
                input_vars={},
                timeout_s=120,
            ),
        ]

        summary: list[dict[str, Any]] = []
        for case in cases:
            print(f"\n=== {case.name} ===")
            proc = import_procedure(case.procedure_file)
            run = create_run(proc["procedure_id"], case.input_vars, proc["version"])
            final = wait_for_run(run["run_id"], timeout_s=case.timeout_s)
            summary.append(
                {
                    "name": case.name,
                    "procedure_id": proc["procedure_id"],
                    "run_id": final["run_id"],
                    "status": final["status"],
                    "error_message": final.get("error_message"),
                }
            )
            if final["status"] != "completed":
                raise RuntimeError(f"{case.name} failed: {final.get('error_message')}")
            if case.name == "desktop-notepad-actual":
                _kill_desktop_demo_apps()

        if not smtp_handler.messages:
            raise AssertionError("Expected at least one message to reach the local SMTP sink")

        print("\nSuite summary:")
        print(json.dumps(summary, indent=2))
        print("\nSMTP sink messages:")
        print(json.dumps(smtp_handler.messages, indent=2))
        return 0
    finally:
        controller.stop()
        _kill_desktop_demo_apps()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (HTTPError, URLError, TimeoutError, RuntimeError, AssertionError) as exc:
        print(f"Demo suite failed: {exc}", file=sys.stderr)
        raise
