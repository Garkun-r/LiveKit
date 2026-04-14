#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

from dotenv import dotenv_values

# Keep this list explicit: we sync only runtime settings that the agent uses.
SYNC_KEYS = [
    "AGENT_NAME",
    "GOOGLE_API_KEY",
    "GEMINI_MODEL",
    "GEMINI_TEMPERATURE",
    "GEMINI_MAX_OUTPUT_TOKENS",
    "GEMINI_TOP_P",
    "GEMINI_THINKING_LEVEL",
    "ELEVEN_API_KEY",
    "ELEVENLABS_API_KEY",
    "N8N_WEBHOOK_URL",
    "N8N_WEBHOOK_TOKEN",
]


def build_secret_map(env_file: Path) -> dict[str, str]:
    values = dotenv_values(env_file)
    secrets = {
        key: str(values[key]).strip()
        for key in SYNC_KEYS
        if key in values and values[key] is not None and str(values[key]).strip()
    }

    # Accept either Eleven key name and mirror to both for compatibility.
    if "ELEVEN_API_KEY" in secrets and "ELEVENLABS_API_KEY" not in secrets:
        secrets["ELEVENLABS_API_KEY"] = secrets["ELEVEN_API_KEY"]
    if "ELEVENLABS_API_KEY" in secrets and "ELEVEN_API_KEY" not in secrets:
        secrets["ELEVEN_API_KEY"] = secrets["ELEVENLABS_API_KEY"]

    if "GOOGLE_API_KEY" not in secrets:
        raise RuntimeError("GOOGLE_API_KEY is missing in env file.")
    if "ELEVEN_API_KEY" not in secrets:
        raise RuntimeError("ELEVEN_API_KEY (or ELEVENLABS_API_KEY) is missing in env file.")

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

    secrets = build_secret_map(env_file)
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
