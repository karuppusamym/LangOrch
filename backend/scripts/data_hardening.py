"""Operational maintenance CLI for data hardening tasks.

Examples:
  python scripts/data_hardening.py scrub-run-data
  python scripts/data_hardening.py backfill-case-types
  python scripts/data_hardening.py all --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.engine import async_session  # noqa: E402
from app.services.data_hardening_service import (  # noqa: E402
    backfill_case_types_and_seed_policies,
    scrub_historical_run_data,
)


async def _run_task(task: str, apply_changes: bool) -> dict[str, object]:
    report: dict[str, object] = {"mode": "apply" if apply_changes else "dry_run", "task": task}
    async with async_session() as db:
        if task in {"scrub-run-data", "all"}:
            report["scrub_run_data"] = await scrub_historical_run_data(db, dry_run=not apply_changes)
        if task in {"backfill-case-types", "all"}:
            report["backfill_case_types"] = await backfill_case_types_and_seed_policies(
                db,
                dry_run=not apply_changes,
            )
        if apply_changes:
            await db.commit()
        else:
            await db.rollback()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="LangOrch data hardening maintenance CLI")
    parser.add_argument(
        "task",
        choices=["scrub-run-data", "backfill-case-types", "all"],
        help="Maintenance task to execute.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist changes. Without this flag the command runs in dry-run mode.",
    )
    args = parser.parse_args()

    report = asyncio.run(_run_task(args.task, apply_changes=args.apply))
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

