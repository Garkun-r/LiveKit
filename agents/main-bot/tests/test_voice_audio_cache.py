from __future__ import annotations

from dataclasses import dataclass

import pytest
from livekit import rtc

from voice_audio_cache import VoiceAudioCache, build_voice_profile_id


@dataclass
class _FakeOpts:
    voice_id: str
    model_id: str
    sample_rate: int = 24000
    api_key: str = "secret"


class _Event:
    def __init__(self, frame: rtc.AudioFrame) -> None:
        self.frame = frame


class _FakeStream:
    def __init__(self, frame: rtc.AudioFrame | None = None, error: Exception | None = None) -> None:
        self._frame = frame
        self._error = error

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._error is not None:
            raise self._error
        if self._frame is None:
            raise StopAsyncIteration
        frame = self._frame
        self._frame = None
        return _Event(frame)


class _FakeTTS:
    provider = "FakeTTS"
    sample_rate = 24000
    num_channels = 1

    def __init__(self, *, voice_id: str = "voice", model_id: str = "model") -> None:
        self._opts = _FakeOpts(voice_id=voice_id, model_id=model_id)
        self.model = model_id
        self.calls: list[str] = []
        self.error: Exception | None = None

    def synthesize(self, text: str) -> _FakeStream:
        self.calls.append(text)
        frame = rtc.AudioFrame(
            data=b"\x01\x00\x02\x00",
            sample_rate=24000,
            num_channels=1,
            samples_per_channel=2,
        )
        return _FakeStream(frame=frame, error=self.error)


def test_voice_profile_changes_when_voice_changes() -> None:
    first = build_voice_profile_id(_FakeTTS(voice_id="voice-a"))
    second = build_voice_profile_id(_FakeTTS(voice_id="voice-b"))

    assert first != second


def test_cache_path_changes_when_text_changes(tmp_path) -> None:
    cache = VoiceAudioCache(cache_dir=tmp_path, tts_client=_FakeTTS())

    first = cache.path_for(kind="initial_greeting", text="Здравствуйте")
    second = cache.path_for(kind="initial_greeting", text="Добрый день")

    assert first != second


@pytest.mark.asyncio
async def test_cache_miss_synthesizes_and_hit_reuses_file(tmp_path) -> None:
    tts = _FakeTTS()
    cache = VoiceAudioCache(cache_dir=tmp_path, tts_client=tts)

    first = await cache.get_or_create(kind="initial_greeting", text="Здравствуйте")
    second = await cache.get_or_create(kind="initial_greeting", text="Здравствуйте")

    assert first == second
    assert first is not None
    assert first.exists()
    assert tts.calls == ["Здравствуйте"]


@pytest.mark.asyncio
async def test_cache_error_returns_legacy_path(tmp_path) -> None:
    tts = _FakeTTS()
    tts.error = RuntimeError("tts failed")
    legacy_path = tmp_path / "legacy.wav"
    legacy_path.write_bytes(b"legacy")
    cache = VoiceAudioCache(
        cache_dir=tmp_path / "cache",
        tts_client=tts,
        legacy_profile_id=build_voice_profile_id(tts),
    )

    result = await cache.get_or_create(
        kind="initial_greeting",
        text="Здравствуйте",
        legacy_path=legacy_path,
    )

    assert result == legacy_path
    assert tts.calls == []


@pytest.mark.asyncio
async def test_cache_error_does_not_use_legacy_for_different_profile(tmp_path) -> None:
    tts = _FakeTTS(voice_id="new-voice")
    tts.error = RuntimeError("tts failed")
    legacy_path = tmp_path / "legacy.wav"
    legacy_path.write_bytes(b"legacy")
    cache = VoiceAudioCache(
        cache_dir=tmp_path / "cache",
        tts_client=tts,
        legacy_profile_id=build_voice_profile_id(_FakeTTS(voice_id="old-voice")),
    )

    result = await cache.get_or_create(
        kind="initial_greeting",
        text="Здравствуйте",
        legacy_path=legacy_path,
    )

    assert result is None
    assert tts.calls == ["Здравствуйте"]
