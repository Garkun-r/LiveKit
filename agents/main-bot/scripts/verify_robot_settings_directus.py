#!/usr/bin/env python3
"""Read-only verification for Directus-backed robot settings."""

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

LEGACY_PROVIDER_ENV_KEYS = {
    "LLM_PROVIDER",
    "FAST_LLM_PROVIDER",
    "COMPLEX_LLM_PROVIDER",
    "TTS_PROVIDER",
    "STT_PROVIDER",
    "GEMINI_MODEL",
    "GEMINI_FALLBACK_MODEL",
    "GEMINI_TEMPERATURE",
    "GEMINI_MAX_OUTPUT_TOKENS",
    "GEMINI_TOP_P",
    "GEMINI_THINKING_LEVEL",
    "XAI_MODEL",
    "XAI_TEMPERATURE",
    "XAI_BASE_URL",
    "XAI_ENABLE_TOOLS",
    "USE_LIVEKIT_FALLBACK_ADAPTER",
    "FAST_LLM_BACKUP_PROVIDER",
    "FAST_LLM_BACKUP_MODEL",
    "COMPLEX_LLM_BACKUP_PROVIDER",
    "COMPLEX_LLM_BACKUP_MODEL",
    "GOOGLE_TTS_MODEL",
    "GOOGLE_TTS_FALLBACK_MODEL",
    "GOOGLE_TTS_LANGUAGE",
    "GOOGLE_TTS_VOICE_NAME",
    "GOOGLE_TTS_SPEAKING_RATE",
    "GOOGLE_TTS_PITCH",
    "GOOGLE_TTS_USE_STREAMING",
    "GOOGLE_TTS_PROMPT",
    "GOOGLE_TTS_LOCATION",
    "GOOGLE_TTS_MIN_SENTENCE_LEN",
    "GOOGLE_TTS_STREAM_CONTEXT_LEN",
    "VERTEX_TTS_MIN_SENTENCE_LEN",
    "VERTEX_TTS_STREAM_CONTEXT_LEN",
    "MINIMAX_TTS_MODEL",
    "MINIMAX_TTS_VOICE_ID",
    "MINIMAX_TTS_BASE_URL",
    "MINIMAX_TTS_LANGUAGE_BOOST",
    "MINIMAX_TTS_SPEED",
    "MINIMAX_TTS_VOLUME",
    "MINIMAX_TTS_PITCH",
    "MINIMAX_TTS_INTENSITY",
    "MINIMAX_TTS_TIMBRE",
    "MINIMAX_TTS_SOUND_EFFECTS",
    "MINIMAX_TTS_FORMAT",
    "MINIMAX_TTS_SAMPLE_RATE",
    "MINIMAX_TTS_BITRATE",
    "MINIMAX_TTS_CHANNEL",
    "MINIMAX_TTS_MIN_SENTENCE_LEN",
    "MINIMAX_TTS_STREAM_CONTEXT_LEN",
    "COSYVOICE_PROFILE",
    "COSYVOICE_API_KEY_ENV_NAME",
    "COSYVOICE_TTS_TRANSPORT",
    "COSYVOICE_TTS_REGION",
    "COSYVOICE_TTS_WS_URL",
    "COSYVOICE_TTS_MODEL",
    "COSYVOICE_TTS_VOICE_MODE",
    "COSYVOICE_TTS_VOICE_ID",
    "COSYVOICE_TTS_CLONE_VOICE_ID",
    "COSYVOICE_TTS_DESIGN_VOICE_ID",
    "COSYVOICE_TTS_FORMAT",
    "COSYVOICE_TTS_SAMPLE_RATE",
    "COSYVOICE_TTS_RATE",
    "COSYVOICE_TTS_PITCH",
    "COSYVOICE_TTS_VOLUME",
    "COSYVOICE_TTS_CONNECTION_REUSE",
    "COSYVOICE_TTS_PLAYBACK_ON_FIRST_CHUNK",
    "COSYVOICE_TTS_MIN_SENTENCE_LEN",
    "COSYVOICE_TTS_STREAM_CONTEXT_LEN",
    "ELEVENLABS_VOICE_ID",
    "ELEVENLABS_MODEL",
    "ELEVENLABS_V3_USE_STREAM_INPUT",
    "ELEVENLABS_V3_OUTPUT_FORMAT",
    "ELEVENLABS_V3_ENABLE_LOGGING",
    "ELEVENLABS_V3_APPLY_TEXT_NORMALIZATION",
    "ELEVENLABS_V3_LANGUAGE",
    "ELEVENLABS_VOICE_STABILITY",
    "ELEVENLABS_VOICE_SIMILARITY_BOOST",
    "ELEVENLABS_VOICE_STYLE",
    "ELEVENLABS_VOICE_SPEED",
    "ELEVENLABS_VOICE_USE_SPEAKER_BOOST",
    "ELEVENLABS_V3_MIN_SENTENCE_LEN",
    "ELEVENLABS_V3_STREAM_CONTEXT_LEN",
    "STT_DEEPGRAM_MODEL",
    "STT_DEEPGRAM_LANGUAGE",
    "STT_DEEPGRAM_ENDPOINTING_MS",
    "STT_GOOGLE_MODEL",
    "STT_GOOGLE_LANGUAGE",
    "STT_GOOGLE_LOCATION",
    "STT_YANDEX_MODEL",
    "STT_YANDEX_LANGUAGE",
    "STT_YANDEX_MAX_PAUSE_BETWEEN_WORDS_HINT_MS",
    "TURN_DETECTION_MODE",
    "TURN_ENDPOINTING_MODE",
    "TURN_MIN_ENDPOINTING_DELAY",
    "TURN_MAX_ENDPOINTING_DELAY",
    "PREEMPTIVE_GENERATION",
    "SBER_TTS_VOICE",
    "SBER_TTS_PAINT_PITCH",
    "SBER_TTS_PAINT_SPEED",
    "SBER_TTS_PAINT_LOUDNESS",
}


def _parse_active_env_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    if not path.exists():
        return keys
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        keys.add(stripped.split("=", 1)[0].strip())
    return keys


def _public_profile(selection: Any) -> str:
    if selection is None:
        return "missing"
    egress = selection.config.get("egress") if isinstance(selection.config, dict) else None
    suffix = f", egress={egress}" if egress else ""
    return f"{selection.profile_key} ({selection.provider}{suffix})"


def _load_snapshot(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _find_snapshot_secret_like_keys(payload: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    for profile in payload.get("component_profiles", []):
        if not isinstance(profile, dict):
            continue
        config = profile.get("config_json")
        if not isinstance(config, dict):
            continue
        for key in config:
            normalized = key.lower()
            if normalized.endswith("_ref") or normalized.endswith("_env_name"):
                continue
            if normalized in {"max_output_tokens"}:
                continue
            if any(part in normalized for part in ("api_key", "secret", "token", "credentials", "auth_key")):
                findings.append(f"{profile.get('profile_key')}.{key}")
    return findings


async def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify Directus robot settings without writing to Directus."
    )
    parser.add_argument("--env-file", default=".env.local")
    parser.add_argument("--runtime", default=None)
    parser.add_argument("--did", default=None)
    parser.add_argument("--allow-legacy-env", action="store_true")
    args = parser.parse_args()

    os.chdir(ROOT_DIR)
    sys.path.insert(0, str(SRC_DIR))
    load_dotenv(args.env_file, override=True)

    import config
    import robot_settings

    store = await robot_settings.load_robot_settings_store(force_refresh=True)
    runtime = args.runtime or config.ROBOT_RUNTIME_PROFILE
    resolved = store.resolve(did=args.did, runtime_key=runtime)
    active_env_keys = _parse_active_env_keys(Path(args.env_file))
    active_legacy_keys = sorted(active_env_keys & LEGACY_PROVIDER_ENV_KEYS)

    errors: list[str] = []
    for category, slot in (
        ("llm", "primary"),
        ("tts", "primary"),
        ("stt", "primary"),
        ("turn", "selected"),
    ):
        if resolved.component(category, slot) is None:
            errors.append(f"missing binding: {category}.{slot}")

    for binding in store.profile_bindings:
        if binding.profile_key not in store.component_profiles:
            errors.append(
                "binding points to missing profile: "
                f"{binding.owner_type}.{binding.owner_key} "
                f"{binding.category}.{binding.slot} -> {binding.profile_key}"
            )

    for profile in store.component_profiles.values():
        if profile.kind != "llm":
            continue
        if not profile.config.get("fallback_provider"):
            errors.append(f"{profile.profile_key}: missing fallback_provider")
        if not profile.config.get("fallback_model"):
            errors.append(f"{profile.profile_key}: missing fallback_model")

    snapshot_path = Path(config.ROBOT_SETTINGS_SNAPSHOT_FILE)
    if not snapshot_path.is_absolute():
        snapshot_path = ROOT_DIR / snapshot_path
    snapshot_secret_keys = _find_snapshot_secret_like_keys(_load_snapshot(snapshot_path))
    if snapshot_secret_keys:
        errors.append(
            "snapshot contains secret-like config keys: "
            + ", ".join(snapshot_secret_keys)
        )

    if active_legacy_keys and not args.allow_legacy_env:
        errors.append(
            "active legacy provider env keys remain: " + ", ".join(active_legacy_keys)
        )

    print(f"source={store.source}")
    print(f"runtime={runtime}")
    print(f"effective_runtime={resolved.effective_runtime_key}")
    print(f"project={resolved.project_key or 'none'}")
    print(f"llm={_public_profile(resolved.llm_primary)}")
    print(f"llm_fast={_public_profile(resolved.component('llm_routing', 'fast'))}")
    print(f"llm_complex={_public_profile(resolved.component('llm_routing', 'complex'))}")
    print(f"tts={_public_profile(resolved.tts_primary)}")
    print(f"stt={_public_profile(resolved.stt_primary)}")
    print(f"turn={_public_profile(resolved.turn)}")
    print(f"component_profiles={len(store.component_profiles)}")
    print(f"profile_bindings={len(store.profile_bindings)}")
    print(f"project_profiles={len(store.project_profiles)}")
    print(f"active_legacy_env_keys={len(active_legacy_keys)}")

    if errors:
        print("FAILED")
        for error in errors:
            print(f"- {error}")
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
