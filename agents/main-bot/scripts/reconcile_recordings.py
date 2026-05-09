#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from recording_export import reconcile_pending_recordings  # noqa: E402


async def _run(limit: int, fail_on_error: bool) -> int:
    summary = await reconcile_pending_recordings(limit=limit)
    print(
        "recording reconcile "
        + " ".join(f"{key}={value}" for key, value in summary.items()),
        flush=True,
    )
    return 1 if fail_on_error and summary.get("failed") else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh Directus metadata for pending LiveKit Egress recordings."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Recent robot_call_recordings rows to inspect (default: 200).",
    )
    parser.add_argument(
        "--fail-on-error",
        action="store_true",
        help="Exit non-zero if any recording refresh fails.",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args.limit, args.fail_on_error)))


if __name__ == "__main__":
    main()
