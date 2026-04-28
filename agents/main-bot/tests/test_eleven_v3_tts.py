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
    ("text", "expected_sanitized", "expected_reason"),
    [
        ("", "", "empty_after_trim"),
        ("   ", "", "empty_after_trim"),
        ("🙂", "", "empty_after_emoji_strip"),
        ("[speaker_1]:", "", "empty_after_speaker_tag_strip"),
        ("speaker2: 🙂", "", "empty_after_emoji_strip"),
        ("[STATUS: LEAD]", "", "empty_after_bracket_tag_strip"),
        ("Спасибо. [STATUS: LEAD]", "Спасибо.", None),
        ("Хорошо [короткая пауза] до свидания", "Хорошо до свидания", None),
        ("...", "", "punctuation_only"),
        ("—", "", "punctuation_only"),
        ("да", "да", None),
        ("мм", "мм", None),
        ("ok!", "ok!", None),
        ("  a  ", "a", None),
    ],
)
def test_sanitize_outbound_text_segment(
    text: str,
    expected_sanitized: str,
    expected_reason: str | None,
) -> None:
    sanitized, reason = _sanitize_outbound_text_segment(text)

    assert reason == expected_reason
    assert sanitized == expected_sanitized


class _NoHttpSession:
    def post(self, *args, **kwargs):  # pragma: no cover - should never be called
        raise AssertionError("HTTP request should not be executed for invalid text")


class _OneChunkContent:
    async def iter_any(self):
        yield b"audio"


class _AudioResponse:
    status = 200
    reason = "OK"
    content_type = "audio/mpeg"
    content = _OneChunkContent()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _CaptureHttpSession:
    def __init__(self) -> None:
        self.requests: list[dict] = []

    def post(self, *args, **kwargs):
        self.requests.append({"args": args, "kwargs": kwargs})
        return _AudioResponse()


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


@pytest.mark.asyncio
async def test_do_http_stream_strips_bracketed_tags_from_payload() -> None:
    http_session = _CaptureHttpSession()
    tts_obj = ElevenV3HTTPStreamTTS(api_key="test-api-key", voice_id="voice")
    tts_obj._session = http_session

    q: asyncio.Queue[bytes | None] = asyncio.Queue()
    await _do_http_stream(
        tts_provider=tts_obj,
        opts=tts_obj._opts,
        text="Спасибо. [STATUS: LEAD]",
        prev_text="hello",
        conn_options=DEFAULT_API_CONNECT_OPTIONS,
        on_chunk=q,
    )

    assert len(http_session.requests) == 1
    assert http_session.requests[0]["kwargs"]["json"]["text"] == "Спасибо."


@pytest.mark.asyncio
async def test_do_http_stream_skips_bracket_only_segment_before_http() -> None:
    tts_obj = ElevenV3HTTPStreamTTS(api_key="test-api-key", voice_id="voice")
    tts_obj._session = _NoHttpSession()

    q: asyncio.Queue[bytes | None] = asyncio.Queue()
    await _do_http_stream(
        tts_provider=tts_obj,
        opts=tts_obj._opts,
        text="[STATUS: LEAD]",
        prev_text="hello",
        conn_options=DEFAULT_API_CONNECT_OPTIONS,
        on_chunk=q,
    )

    assert q.empty()


def test_connection_reused_hint_tracks_provider_http_requests() -> None:
    tts_obj = ElevenV3HTTPStreamTTS(api_key="test-api-key", voice_id="voice")

    assert tts_obj._connection_reused_hint() is False
    assert tts_obj._connection_reused_hint() is True
    assert tts_obj._connection_reused_hint() is True


@pytest.mark.asyncio
async def test_warmup_synthesis_hits_stream_endpoint_and_discards_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = []

    async def _fake_do_http_stream(**kwargs):
        calls.append(kwargs)
        kwargs["on_chunk"].push(b"discarded-audio")

    monkeypatch.setattr(eleven_v3_tts, "_do_http_stream", _fake_do_http_stream)

    tts_obj = ElevenV3HTTPStreamTTS(api_key="test-api-key", voice_id="voice")
    await tts_obj.warmup_synthesis(text="Да.")

    assert len(calls) == 1
    assert calls[0]["tts_provider"] is tts_obj
    assert calls[0]["text"] == "Да."
    assert calls[0]["prev_text"] == ""
    assert not isinstance(calls[0]["on_chunk"], asyncio.Queue)


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
