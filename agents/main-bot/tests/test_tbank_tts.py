import base64

import pytest
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS

import agent
from tbank_tts import (
    TBankSynthesizeStream,
    TBankTTSOptions,
    TBankVoiceKitTTS,
    _grpc_channel_options,
    _stream_segment_to_emitter,
    build_tbank_tts_request,
)
from tinkoff.cloud.tts.v1 import tts_pb2 as tbank_tts_pb


class _Emitter:
    def __init__(self) -> None:
        self.chunks: list[bytes] = []
        self.started_segments: list[str] = []
        self.ended_segments = 0
        self.flush_calls = 0

    def start_segment(self, *, segment_id: str) -> None:
        self.started_segments.append(segment_id)

    def end_segment(self) -> None:
        self.ended_segments += 1

    def push(self, chunk: bytes) -> None:
        self.chunks.append(chunk)

    def flush(self) -> None:
        self.flush_calls += 1


class _Sentence:
    def __init__(self, token: str) -> None:
        self.token = token


class _SentenceStream:
    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens

    async def __aiter__(self):
        for token in self._tokens:
            yield _Sentence(token)


def _secret_key() -> str:
    return base64.urlsafe_b64encode(b"test-secret").decode("utf-8").rstrip("=")


def test_build_tbank_tts_request_uses_voice_pitch_and_speed_defaults() -> None:
    request = build_tbank_tts_request(
        text="Привет",
        opts=TBankTTSOptions(api_key="key", secret_key="secret"),
    )

    assert request.input.text == "Привет"
    assert request.voice.name == "anna"
    assert request.audio_config.audio_encoding == tbank_tts_pb.LINEAR16
    assert request.audio_config.sample_rate_hertz == 24000
    assert request.audio_config.pitch == pytest.approx(0.8)
    assert request.audio_config.speaking_rate == pytest.approx(1.0)


def test_tbank_tts_grpc_channel_options_use_authority_override() -> None:
    assert _grpc_channel_options("") == ()
    assert _grpc_channel_options("api.tinkoff.ai") == (
        ("grpc.ssl_target_name_override", "api.tinkoff.ai"),
        ("grpc.default_authority", "api.tinkoff.ai"),
    )


@pytest.mark.asyncio
async def test_tbank_tts_stream_pushes_audio_chunks_in_order() -> None:
    requests = []
    metadata_seen = []

    async def fake_streaming_synthesize(request, metadata):
        requests.append(request)
        metadata_seen.append(metadata)
        yield tbank_tts_pb.StreamingSynthesizeSpeechResponse(audio_chunk=b"one")
        yield tbank_tts_pb.StreamingSynthesizeSpeechResponse(audio_chunk=b"two")

    tts_obj = TBankVoiceKitTTS(
        api_key="test-key",
        secret_key=_secret_key(),
        synthesize_stream_factory=fake_streaming_synthesize,
    )
    emitter = _Emitter()

    await _stream_segment_to_emitter(
        tts_provider=tts_obj,
        opts=tts_obj._opts,
        text="Привет.",
        conn_options=DEFAULT_API_CONNECT_OPTIONS,
        output_emitter=emitter,
    )

    assert [request.input.text for request in requests] == ["Привет."]
    assert metadata_seen[0][0][0] == "authorization"
    assert metadata_seen[0][0][1].startswith("Bearer ")
    assert emitter.chunks == [b"one", b"two"]


@pytest.mark.asyncio
async def test_tbank_tts_sentence_splitting_keeps_one_livekit_segment() -> None:
    requests = []

    async def fake_streaming_synthesize(request, metadata):
        requests.append(request)
        yield tbank_tts_pb.StreamingSynthesizeSpeechResponse(
            audio_chunk=f"audio-{len(requests)}".encode()
        )

    tts_obj = TBankVoiceKitTTS(
        api_key="test-key",
        secret_key=_secret_key(),
        synthesize_stream_factory=fake_streaming_synthesize,
    )
    stream = TBankSynthesizeStream(
        tts=tts_obj,
        conn_options=DEFAULT_API_CONNECT_OPTIONS,
    )
    emitter = _Emitter()

    try:
        await stream._run_sentence_stream(
            _SentenceStream(["Первое предложение.", "Второе предложение."]),
            emitter,
        )
    finally:
        await stream.aclose()

    assert [request.input.text for request in requests] == [
        "Первое предложение.",
        "Второе предложение.",
    ]
    assert len(emitter.started_segments) == 1
    assert emitter.ended_segments == 1
    assert emitter.chunks == [b"audio-1", b"audio-2"]


def test_build_tts_uses_tbank_provider(monkeypatch) -> None:
    captured = {}

    class _FakeTBankTTS:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(agent, "TTS_PROVIDER", "tbank")
    monkeypatch.setattr(agent, "TBANK_VOICEKIT_API_KEY", "test-key")
    monkeypatch.setattr(agent, "TBANK_VOICEKIT_SECRET_KEY", "test-secret")
    monkeypatch.setattr(agent, "TBANK_VOICEKIT_ENDPOINT", "api.tinkoff.ai:443")
    monkeypatch.setattr(agent, "TTS_TBANK_VOICE_NAME", "anna")
    monkeypatch.setattr(agent, "TTS_TBANK_FORMAT", "linear16")
    monkeypatch.setattr(agent, "TTS_TBANK_SAMPLE_RATE", 24000)
    monkeypatch.setattr(agent, "TTS_TBANK_SPEAKING_RATE", 1.0)
    monkeypatch.setattr(agent, "TTS_TBANK_PITCH", 0.8)
    monkeypatch.setattr(agent, "TTS_TBANK_MIN_SENTENCE_LEN", 4)
    monkeypatch.setattr(agent, "TTS_TBANK_STREAM_CONTEXT_LEN", 1)
    monkeypatch.setattr(agent, "TBANK_VOICEKIT_AUTHORITY", "")
    monkeypatch.setattr(agent, "TBankVoiceKitTTS", _FakeTBankTTS)

    result = agent.build_tts()

    assert isinstance(result, _FakeTBankTTS)
    assert captured["api_key"] == "test-key"
    assert captured["secret_key"] == "test-secret"
    assert captured["voice_name"] == "anna"
    assert captured["audio_format"] == "linear16"
    assert captured["sample_rate"] == 24000
    assert captured["speaking_rate"] == 1.0
    assert captured["pitch"] == 0.8
    assert captured["endpoint"] == "api.tinkoff.ai:443"
    assert captured["authority"] == ""
