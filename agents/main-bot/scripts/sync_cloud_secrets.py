#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
import tempfile
from pathlib import Path

from dotenv import dotenv_values

# Sync all non-empty .env vars by default, except connection creds
# that should come from LiveKit Cloud environment itself.
DEFAULT_EXCLUDE_KEYS = {
    "LIVEKIT_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
}
ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def build_secret_map(env_file: Path, exclude_keys: set[str]) -> dict[str, str]:
    values = dotenv_values(env_file)
    secrets: dict[str, str] = {}
    for key, value in values.items():
        if not key or key in exclude_keys:
            continue
        if not ENV_KEY_RE.match(key):
            continue
        if value is None:
            continue
        value_str = str(value).strip()
        if not value_str:
            continue
        secrets[key] = value_str

    # Accept either Eleven key name and mirror to both for compatibility.
    if "ELEVEN_API_KEY" in secrets and "ELEVENLABS_API_KEY" not in secrets:
        secrets["ELEVENLABS_API_KEY"] = secrets["ELEVEN_API_KEY"]
    if "ELEVENLABS_API_KEY" in secrets and "ELEVEN_API_KEY" not in secrets:
        secrets["ELEVEN_API_KEY"] = secrets["ELEVENLABS_API_KEY"]

    return secrets


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync .env settings to LiveKit Cloud agent secrets."
    )
    parser.add_argument(
        "--env-file",
        default=".env.local",
        help="Path to env file with local settings (default: .env.local).",
    )
    parser.add_argument("--id", help="LiveKit agent id (optional).")
    parser.add_argument("--project", help="LiveKit project name (optional).")
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Env key to exclude from sync (can be passed multiple times).",
    )
    parser.add_argument(
        "--working-dir",
        default=".",
        help="Directory with livekit.toml (default: current directory).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only show which keys would be synced.",
    )
    args = parser.parse_args()

    env_file = Path(args.env_file).expanduser().resolve()
    if not env_file.exists():
        raise FileNotFoundError(f"Env file not found: {env_file}")

    exclude_keys = set(DEFAULT_EXCLUDE_KEYS)
    exclude_keys.update({item.strip() for item in args.exclude if item.strip()})

    secrets = build_secret_map(env_file, exclude_keys=exclude_keys)
    if not secrets:
        raise RuntimeError("No non-empty secrets found to sync.")

    print(f"Loaded {len(secrets)} secrets from {env_file}")
    print("Keys:", ", ".join(sorted(secrets.keys())))

    if args.dry_run:
        return

    with tempfile.NamedTemporaryFile("w", delete=False) as tmp:
        for key in sorted(secrets.keys()):
            tmp.write(f"{key}={secrets[key]}\n")
        tmp_path = Path(tmp.name)

    cmd = [
        "lk",
        "agent",
        "update-secrets",
        "--yes",
        "--overwrite",
        "--secrets-file",
        str(tmp_path),
    ]
    if args.id:
        cmd.extend(["--id", args.id])
    if args.project:
        cmd.extend(["--project", args.project])

    cmd.append(str(Path(args.working_dir).expanduser().resolve()))
    subprocess.run(cmd, check=True)
    print("Secrets synced to LiveKit Cloud.")


if __name__ == "__main__":
    main()
