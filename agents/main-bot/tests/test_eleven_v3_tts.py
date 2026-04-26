import asyncio
from dataclasses import dataclass

import pytest
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS

import eleven_v3_tts
from eleven_v3_tts import (
    ElevenV3HTTPStreamSynthesizeStream,
    ElevenV3HTTPStreamTTS,
    _do_http_stream,
    _sanitize_outbound_text_segment,
)


@pytest.mark.parametrize(
    ("text", "expected_valid", "expected_reason"),
    [
        ("", False, "empty_after_trim"),
        ("   ", False, "empty_after_trim"),
        ("🙂", False, "empty_after_emoji_strip"),
        ("[speaker_1]:", False, "empty_after_speaker_tag_strip"),
        ("speaker2: 🙂", False, "empty_after_emoji_strip"),
        ("...", False, "punctuation_only"),
        ("—", False, "punctuation_only"),
        ("да", True, None),
        ("мм", True, None),
        ("ok!", True, None),
        ("  a  ", True, None),
    ],
)
def test_sanitize_outbound_text_segment(text: str, expected_valid: bool, expected_reason: str | None) -> None:
    sanitized, reason = _sanitize_outbound_text_segment(text)

    assert (reason is None) is expected_valid
    assert reason == expected_reason
    if expected_valid:
        assert sanitized == text.strip()
    else:
        assert sanitized == ""


class _NoHttpSession:
    def post(self, *args, **kwargs):  # pragma: no cover - should never be called
        raise AssertionError("HTTP request should not be executed for invalid text")


@pytest.mark.asyncio
async def test_do_http_stream_skips_invalid_segment_before_http() -> None:
    tts_obj = ElevenV3HTTPStreamTTS(api_key="test-api-key", voice_id="voice")
    tts_obj._session = _NoHttpSession()

    q: asyncio.Queue[bytes | None] = asyncio.Queue()
    await _do_http_stream(
        tts_provider=tts_obj,
        opts=tts_obj._opts,
        text="🙂",
        prev_text="hello",
        conn_options=DEFAULT_API_CONNECT_OPTIONS,
        on_chunk=q,
    )

    assert q.empty()


@dataclass
class _Sentence:
    token: str


class _Emitter:
    def __init__(self) -> None:
        self.chunks: list[bytes] = []
        self.flush_calls = 0

    def push(self, chunk: bytes) -> None:
        self.chunks.append(chunk)

    def flush(self) -> None:
        self.flush_calls += 1


@pytest.mark.asyncio
async def test_pipeline_skips_invalid_tokens_and_keeps_prev_text(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    async def _fake_stream_to_queue(*, text, prev_text, audio_q, **kwargs):
        calls.append((text, prev_text))
        await audio_q.put(f"audio:{text}".encode())

    monkeypatch.setattr(eleven_v3_tts, "_stream_to_queue", _fake_stream_to_queue)

    tts_obj = ElevenV3HTTPStreamTTS(
        api_key="test-api-key",
        voice_id="voice",
        min_http_text_len=1,
    )
    stream = ElevenV3HTTPStreamSynthesizeStream(
        tts=tts_obj,
        conn_options=DEFAULT_API_CONNECT_OPTIONS,
    )
    emitter = _Emitter()

    async def _sentence_stream():
        for token in ("Привет", "🙂", "...", "Ок"):
            yield _Sentence(token=token)

    await stream._run_pipelined_segment(_sentence_stream(), emitter)

    assert calls == [("Привет", ""), ("Ок", "Привет")]
    assert [chunk.decode("utf-8") for chunk in emitter.chunks] == ["audio:Привет", "audio:Ок"]
    assert emitter.flush_calls == 2


@pytest.mark.asyncio
async def test_pipeline_merges_short_adjacent_segments(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    async def _fake_stream_to_queue(*, text, prev_text, audio_q, **kwargs):
        calls.append((text, prev_text))
        await audio_q.put(f"audio:{text}".encode())

    monkeypatch.setattr(eleven_v3_tts, "_stream_to_queue", _fake_stream_to_queue)

    tts_obj = ElevenV3HTTPStreamTTS(
        api_key="test-api-key",
        voice_id="voice",
        min_http_text_len=20,
        merge_hold_ms=200,
        max_merged_text_len=80,
    )
    stream = ElevenV3HTTPStreamSynthesizeStream(
        tts=tts_obj,
        conn_options=DEFAULT_API_CONNECT_OPTIONS,
    )
    emitter = _Emitter()

    async def _sentence_stream():
        for token in ("Очень", "коротко"):
            yield _Sentence(token=token)

    await stream._run_pipelined_segment(_sentence_stream(), emitter)

    assert calls == [("Очень коротко", "")]
    assert [chunk.decode("utf-8") for chunk in emitter.chunks] == ["audio:Очень коротко"]
    assert emitter.flush_calls == 1


@pytest.mark.asyncio
async def test_pipeline_short_confirmation_is_not_delayed(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    async def _fake_stream_to_queue(*, text, prev_text, audio_q, **kwargs):
        calls.append((text, prev_text))
        await audio_q.put(f"audio:{text}".encode())

    monkeypatch.setattr(eleven_v3_tts, "_stream_to_queue", _fake_stream_to_queue)

    tts_obj = ElevenV3HTTPStreamTTS(
        api_key="test-api-key",
        voice_id="voice",
        min_http_text_len=20,
        merge_hold_ms=500,
        max_merged_text_len=80,
    )
    stream = ElevenV3HTTPStreamSynthesizeStream(
        tts=tts_obj,
        conn_options=DEFAULT_API_CONNECT_OPTIONS,
    )
    emitter = _Emitter()

    async def _sentence_stream():
        yield _Sentence(token="Да")

    await stream._run_pipelined_segment(_sentence_stream(), emitter)

    assert calls == [("Да", "")]
    assert [chunk.decode("utf-8") for chunk in emitter.chunks] == ["audio:Да"]
    assert emitter.flush_calls == 1
