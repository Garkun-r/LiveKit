from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import logging
import os
import re
import tempfile
import wave
from contextlib import suppress
from pathlib import Path
from typing import Any

from livekit import rtc

logger = logging.getLogger("voice_audio_cache")

_SAFE_PATH_RE = re.compile(r"[^a-z0-9._-]+")
_SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "auth_key",
    "authorization",
    "credential",
    "secret",
    "token",
)


class VoiceAudioCache:
    def __init__(
        self,
        *,
        cache_dir: Path,
        tts_client: Any,
        enabled: bool = True,
        legacy_profile_id: str = "",
    ) -> None:
        self.cache_dir = cache_dir
        self.tts_client = tts_client
        self.enabled = enabled
        self.voice_profile_id = build_voice_profile_id(tts_client)
        self.legacy_profile_id = legacy_profile_id.strip()
        self._locks: dict[Path, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    @property
    def is_legacy_profile(self) -> bool:
        return bool(self.legacy_profile_id and self.voice_profile_id == self.legacy_profile_id)

    async def get_or_create(
        self,
        *,
        kind: str,
        text: str,
        legacy_path: Path | None = None,
    ) -> Path | None:
        normalized_text = normalize_cache_text(text)
        if not normalized_text:
            return self._legacy_path_if_allowed(legacy_path)

        legacy_path = self._legacy_path_if_allowed(legacy_path)
        if legacy_path is not None:
            return legacy_path

        if not self.enabled:
            return self._existing_path(legacy_path)

        cache_path = self.path_for(kind=kind, text=normalized_text)
        if cache_path.exists():
            return cache_path

        lock = await self._lock_for(cache_path)
        async with lock:
            if cache_path.exists():
                return cache_path
            try:
                await synthesize_text_to_wav(
                    tts_client=self.tts_client,
                    text=normalized_text,
                    output_path=cache_path,
                )
                logger.info(
                    "voice audio cache created",
                    extra={
                        "kind": kind,
                        "voice_profile_id": self.voice_profile_id,
                        "audio_path": str(cache_path),
                    },
                )
                return cache_path
            except Exception as e:
                logger.exception(
                    "failed to create voice audio cache for '%s': %s",
                    kind,
                    e,
                    extra={"voice_profile_id": self.voice_profile_id},
                )
                return legacy_path

    def get_existing(
        self,
        *,
        kind: str,
        text: str,
        legacy_path: Path | None = None,
    ) -> Path | None:
        normalized_text = normalize_cache_text(text)
        if not normalized_text:
            return self._legacy_path_if_allowed(legacy_path)
        legacy_path = self._legacy_path_if_allowed(legacy_path)
        if legacy_path is not None:
            return legacy_path
        cache_path = self.path_for(kind=kind, text=normalized_text)
        if cache_path.exists():
            return cache_path
        return None

    def _legacy_path_if_allowed(self, legacy_path: Path | None) -> Path | None:
        if self.is_legacy_profile or not self.enabled:
            return self._existing_path(legacy_path)
        return None

    @staticmethod
    def _existing_path(path: Path | None) -> Path | None:
        return path if path is not None and path.exists() else None

    def path_for(self, *, kind: str, text: str) -> Path:
        safe_kind = _safe_path_part(kind.strip().lower() or "voice")
        text_hash = hashlib.sha256(normalize_cache_text(text).encode("utf-8")).hexdigest()[:16]
        return self.cache_dir / self.voice_profile_id / f"{safe_kind}-{text_hash}.wav"

    async def _lock_for(self, cache_path: Path) -> asyncio.Lock:
        async with self._locks_guard:
            lock = self._locks.get(cache_path)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[cache_path] = lock
            return lock


def normalize_cache_text(text: str) -> str:
    return (text or "").strip()


def build_voice_profile_id(tts_client: Any) -> str:
    profile = voice_profile_data(tts_client)
    encoded = json.dumps(profile, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
    provider = _safe_path_part(str(profile.get("provider") or "tts").lower())
    model = _safe_path_part(str(profile.get("model") or "model").lower())
    voice = _safe_path_part(str(profile.get("voice") or "voice").lower())
    return f"{provider}-{model}-{voice}-{digest}"


def voice_profile_data(tts_client: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "class": f"{type(tts_client).__module__}.{type(tts_client).__name__}",
        "provider": _safe_getattr(tts_client, "provider"),
        "model": _safe_getattr(tts_client, "model"),
        "sample_rate": _safe_getattr(tts_client, "sample_rate"),
        "num_channels": _safe_getattr(tts_client, "num_channels"),
    }
    opts = getattr(tts_client, "_opts", None)
    if opts is not None:
        opts_data = _profile_mapping_from_object(opts)
        data["options"] = opts_data
        data["voice"] = _first_present(
            opts_data,
            (
                "voice",
                "voice_id",
                "voice_name",
                "clone_voice_id",
                "design_voice_id",
            ),
        )
    return _simplify_value(data)


async def synthesize_text_to_wav(
    *,
    tts_client: Any,
    text: str,
    output_path: Path,
) -> None:
    stream = tts_client.synthesize(text)
    frames: list[rtc.AudioFrame] = []
    try:
        async for event in stream:
            frame = getattr(event, "frame", None)
            if frame is not None:
                frames.append(frame)
    except Exception:
        close = getattr(stream, "aclose", None)
        if callable(close):
            await close()
        raise

    if not frames:
        raise RuntimeError("TTS returned no audio frames")

    _write_frames_to_wav(frames, output_path)


def _write_frames_to_wav(frames: list[rtc.AudioFrame], output_path: Path) -> None:
    first = frames[0]
    sample_rate = int(first.sample_rate)
    num_channels = int(first.num_channels)
    if sample_rate <= 0 or num_channels <= 0:
        raise RuntimeError("TTS returned invalid audio frame metadata")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            suffix=".tmp",
            prefix=f".{output_path.name}.",
            dir=output_path.parent,
            delete=False,
        ) as tmp:
            tmp_path = tmp.name
        with wave.open(tmp_path, "wb") as wav_file:
            wav_file.setnchannels(num_channels)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            for frame in frames:
                if frame.sample_rate != sample_rate or frame.num_channels != num_channels:
                    raise RuntimeError("TTS returned frames with mixed audio formats")
                wav_file.writeframes(bytes(frame.data))
        with open(tmp_path, "rb") as tmp:
            os.fsync(tmp.fileno())
        os.replace(tmp_path, output_path)
    except Exception:
        if tmp_path:
            with suppress(FileNotFoundError):
                os.unlink(tmp_path)
        raise


def _profile_mapping_from_object(value: Any) -> dict[str, Any]:
    raw = dataclasses.asdict(value) if dataclasses.is_dataclass(value) else vars(value)
    result: dict[str, Any] = {}
    for key, item in raw.items():
        key_lower = key.lower()
        if any(part in key_lower for part in _SENSITIVE_KEY_PARTS):
            continue
        result[key] = _simplify_value(item)
    return result


def _simplify_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if dataclasses.is_dataclass(value):
        return _profile_mapping_from_object(value)
    if isinstance(value, dict):
        return {
            str(key): _simplify_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if not any(part in str(key).lower() for part in _SENSITIVE_KEY_PARTS)
        }
    if isinstance(value, (list, tuple)):
        return [_simplify_value(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _simplify_value(model_dump())
        except Exception:
            pass
    return f"{type(value).__module__}.{type(value).__name__}"


def _first_present(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return None


def _safe_getattr(value: Any, name: str) -> Any:
    try:
        attr = getattr(value, name)
        if callable(attr):
            return attr()
        return attr
    except Exception:
        return None


def _safe_path_part(value: str) -> str:
    safe = _SAFE_PATH_RE.sub("-", value.strip().lower()).strip("-._")
    return safe[:80] or "unknown"
