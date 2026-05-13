#!/usr/bin/env python3
"""Export Directus robot settings to a deterministic non-secret snapshot."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"

SNAPSHOT_VERSION = 1

COLLECTION_KEYS: dict[str, tuple[str, ...]] = {
    "component_profiles": (
        "profile_key",
        "kind",
        "provider",
        "display_name",
        "description",
        "status",
        "config_json",
        "schema_version",
        "active",
    ),
    "setting_fields": (
        "setting_key",
        "module",
        "scope",
        "label",
        "description",
        "value_type",
        "ui_control",
        "options_json",
        "default_value",
        "validation_json",
        "visible_when_json",
        "sort",
        "requires_restart",
        "sensitive",
        "active",
        "schema_version",
    ),
    "runtime_profiles": (
        "runtime_key",
        "display_name",
        "agent_name",
        "environment",
        "status",
        "llm_profile",
        "fast_llm_profile",
        "complex_llm_profile",
        "tts_profile",
        "stt_profile",
        "turn_profile",
        "fallback_profile",
        "override_json",
        "active",
    ),
    "profile_bindings": (
        "owner_type",
        "owner_key",
        "category",
        "slot",
        "profile_key",
        "note",
        "sort",
        "active",
    ),
    "project_profiles": (
        "profile_key",
        "display_name",
        "client_id",
        "did",
        "runtime_key",
        "status",
        "llm_profile",
        "fast_llm_profile",
        "complex_llm_profile",
        "tts_profile",
        "stt_profile",
        "turn_profile",
        "fallback_profile",
        "prompt_source",
        "greeting_source",
        "override_json",
        "active",
    ),
}

COLLECTION_SORT_KEYS: dict[str, tuple[str, ...]] = {
    "component_profiles": ("kind", "profile_key"),
    "setting_fields": ("module", "sort", "setting_key"),
    "runtime_profiles": ("runtime_key",),
    "profile_bindings": ("owner_type", "owner_key", "category", "slot", "profile_key"),
    "project_profiles": ("profile_key",),
}


def _canonical_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _canonical_value(inner)
            for key, inner in sorted(value.items(), key=lambda item: str(item[0]))
            if inner is not None
        }
    if isinstance(value, list):
        return [_canonical_value(item) for item in value]
    return value


def _compact_row(row: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {
        key: _canonical_value(row[key])
        for key in keys
        if key in row and row[key] is not None
    }


def _row_sort_value(collection: str, row: dict[str, Any]) -> tuple[str, ...]:
    keys = COLLECTION_SORT_KEYS[collection]
    return tuple(str(row.get(key, "")).lower() for key in keys)


def build_snapshot_payload(payload: dict[str, Any]) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "snapshot_version": SNAPSHOT_VERSION,
        "source": "directus",
    }
    for collection, keys in COLLECTION_KEYS.items():
        rows = payload.get(collection, [])
        if not isinstance(rows, list):
            rows = []
        compact_rows = [
            _compact_row(row, keys)
            for row in rows
            if isinstance(row, dict) and row.get("active") is not False
        ]
        snapshot[collection] = sorted(
            compact_rows,
            key=lambda row, collection=collection: _row_sort_value(collection, row),
        )
    return snapshot


def stable_snapshot_text(payload: dict[str, Any]) -> str:
    return (
        json.dumps(
            _canonical_value(payload),
            ensure_ascii=False,
            indent=2,
            sort_keys=False,
        )
        + "\n"
    )


def load_snapshot_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return build_snapshot_payload(payload)


def find_secret_like_config_keys(payload: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    rows = payload.get("component_profiles", [])
    if not isinstance(rows, list):
        return findings

    for profile in rows:
        if not isinstance(profile, dict):
            continue
        config = profile.get("config_json")
        if not isinstance(config, dict):
            continue
        profile_key = str(profile.get("profile_key") or "unknown")
        for key in config:
            normalized = str(key).lower()
            if normalized.endswith("_ref") or normalized.endswith("_env_name"):
                continue
            if normalized in {"max_output_tokens"}:
                continue
            if any(
                part in normalized
                for part in ("api_key", "secret", "token", "credentials", "auth_key")
            ):
                findings.append(f"{profile_key}.{key}")
    return findings


async def fetch_directus_snapshot_payload() -> dict[str, Any]:
    sys.path.insert(0, str(SRC_DIR))
    import robot_settings

    payload = await robot_settings._fetch_directus_payload()
    return build_snapshot_payload(payload)


def _resolve_output_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path
    return ROOT_DIR / path


def _print_summary(payload: dict[str, Any], *, prefix: str = "") -> None:
    for collection in COLLECTION_KEYS:
        rows = payload.get(collection, [])
        count = len(rows) if isinstance(rows, list) else 0
        print(f"{prefix}{collection}={count}")


async def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Export Directus robot settings into config/robot_settings_snapshot.json."
    )
    parser.add_argument("--env-file", default=".env.local")
    parser.add_argument(
        "--output",
        default="config/robot_settings_snapshot.json",
        help="Snapshot output path relative to agents/main-bot unless absolute.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the output file differs; do not write.",
    )
    args = parser.parse_args()

    os.chdir(ROOT_DIR)
    load_dotenv(args.env_file, override=True)

    output_path = _resolve_output_path(args.output)
    try:
        snapshot = await fetch_directus_snapshot_payload()
    except Exception as e:
        detail = f"{type(e).__name__}: {e}".strip()
        print(f"Failed to fetch Directus robot settings: {detail}")
        return 1
    secret_like_keys = find_secret_like_config_keys(snapshot)
    if secret_like_keys:
        print(
            "Refusing to export snapshot with secret-like config keys: "
            + ", ".join(secret_like_keys)
        )
        return 1

    new_text = stable_snapshot_text(snapshot)
    existing_payload = load_snapshot_payload(output_path)
    existing_text = stable_snapshot_text(existing_payload) if existing_payload else ""

    if args.check:
        if existing_text != new_text:
            print(f"Snapshot differs from Directus: {output_path}")
            _print_summary(snapshot, prefix="directus.")
            _print_summary(existing_payload, prefix="snapshot.")
            return 1
        print(f"Snapshot matches Directus: {output_path}")
        _print_summary(snapshot)
        return 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if existing_text == new_text:
        print(f"Snapshot already up to date: {output_path}")
        _print_summary(snapshot)
        return 0

    output_path.write_text(new_text, encoding="utf-8")
    print(f"Snapshot exported: {output_path}")
    _print_summary(snapshot)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
