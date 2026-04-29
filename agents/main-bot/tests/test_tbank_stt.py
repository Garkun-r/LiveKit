import asyncio
import base64

import pytest
from livekit import rtc
from livekit.agents import stt

import agent
from tbank_stt import (
    TBankSTTOptions,
    TBankVoiceKitSTT,
    _grpc_channel_options,
    build_tbank_streaming_config,
)
from tinkoff.cloud.stt.v1 import stt_pb2 as tbank_stt_pb


class _FakeTBankSTTCall:
    def __init__(self, requests, responses, seen_requests) -> None:
        self._requests = requests
        self._responses = responses
        self._seen_requests = seen_requests
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True

    def __aiter__(self):
        return self._run()

    async def _run(self):
        async for request in self._requests:
            self._seen_requests.append(request)
        for response in self._responses:
            yield response


async def _collect_events(stt_client: TBankVoiceKitSTT, frames=()):
    stream = stt_client.stream()
    for frame in frames:
        stream.push_frame(frame)
    stream.end_input()
    return [event async for event in stream]


def _stt_with_responses(responses):
    seen_requests = []
    seen_metadata = []
    secret_key = base64.urlsafe_b64encode(b"test-secret").decode("utf-8").rstrip("=")

    def fake_recognize_stream(requests, metadata):
        seen_metadata.append(metadata)
        return _FakeTBankSTTCall(requests, responses, seen_requests)

    client = TBankVoiceKitSTT(
        api_key="test-tbank-key",
        secret_key=secret_key,
        recognize_stream_factory=fake_recognize_stream,
    )
    return client, seen_requests, seen_metadata


def test_build_tbank_streaming_config_uses_low_latency_defaults() -> None:
    config = build_tbank_streaming_config(
        TBankSTTOptions(
            api_key="key",
            secret_key="secret",
            model="general",
            language="ru-RU",
            sample_rate=16000,
            chunk_ms=50,
            interim_interval_sec=0.1,
        )
    )

    assert config.single_utterance is False
    assert config.config.encoding == tbank_stt_pb.LINEAR16
    assert config.config.sample_rate_hertz == 16000
    assert config.config.language_code == "ru-RU"
    assert config.config.model == "general"
    assert config.config.num_channels == 1
    assert config.config.max_alternatives == 1
    assert config.config.enable_automatic_punctuation is True
    assert config.interim_results_config.enable_interim_results is True
    assert config.interim_results_config.interval == pytest.approx(0.1)


def test_tbank_grpc_channel_options_use_authority_override() -> None:
    assert _grpc_channel_options("") == ()
    assert _grpc_channel_options("api.tinkoff.ai") == (
        ("grpc.ssl_target_name_override", "api.tinkoff.ai"),
        ("grpc.default_authority", "api.tinkoff.ai"),
    )


@pytest.mark.asyncio
async def test_tbank_stream_sends_bearer_metadata_config_first_and_50ms_chunks() -> None:
    stt_client, seen_requests, seen_metadata = _stt_with_responses([])
    frame = rtc.AudioFrame(
        data=bytes(1600 * 2),
        sample_rate=16000,
        num_channels=1,
        samples_per_channel=1600,
    )

    await asyncio.wait_for(_collect_events(stt_client, frames=[frame]), timeout=2)

    assert seen_metadata
    assert seen_metadata[0][0][0] == "authorization"
    assert seen_metadata[0][0][1].startswith("Bearer ")
    assert seen_requests[0].WhichOneof("streaming_request") == "streaming_config"
    chunk_requests = [
        request
        for request in seen_requests
        if request.WhichOneof("streaming_request") == "audio_content"
    ]
    assert len(chunk_requests) == 2
    assert [len(request.audio_content) for request in chunk_requests] == [1600, 1600]


@pytest.mark.asyncio
async def test_tbank_stream_maps_interim_and_final_to_livekit_events() -> None:
    responses = [
        tbank_stt_pb.StreamingRecognizeResponse(
            results=[
                tbank_stt_pb.StreamingRecognitionResult(
                    is_final=False,
                    recognition_result=tbank_stt_pb.SpeechRecognitionResult(
                        alternatives=[
                            tbank_stt_pb.SpeechRecognitionAlternative(
                                transcript="прив",
                                confidence=0.4,
                            )
                        ]
                    ),
                )
            ]
        ),
        tbank_stt_pb.StreamingRecognizeResponse(
            results=[
                tbank_stt_pb.StreamingRecognitionResult(
                    is_final=True,
                    recognition_result=tbank_stt_pb.SpeechRecognitionResult(
                        alternatives=[
                            tbank_stt_pb.SpeechRecognitionAlternative(
                                transcript="привет",
                                confidence=0.9,
                            )
                        ]
                    ),
                )
            ]
        ),
    ]
    stt_client, _, _ = _stt_with_responses(responses)

    events = await _collect_events(stt_client)

    assert [event.type for event in events] == [
        stt.SpeechEventType.START_OF_SPEECH,
        stt.SpeechEventType.INTERIM_TRANSCRIPT,
        stt.SpeechEventType.FINAL_TRANSCRIPT,
        stt.SpeechEventType.END_OF_SPEECH,
    ]
    assert events[1].alternatives[0].text == "прив"
    assert events[1].alternatives[0].language == "ru-RU"
    assert events[2].alternatives[0].text == "привет"
    assert events[2].request_id


def test_build_stt_uses_tbank_provider(monkeypatch) -> None:
    captured = {}

    class _FakeTBankSTT:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(agent, "STT_PROVIDER", "tbank")
    monkeypatch.setattr(agent, "TBANK_VOICEKIT_API_KEY", "test-key")
    monkeypatch.setattr(agent, "TBANK_VOICEKIT_SECRET_KEY", "test-secret")
    monkeypatch.setattr(agent, "TBANK_VOICEKIT_ENDPOINT", "api.tinkoff.ai:443")
    monkeypatch.setattr(agent, "STT_TBANK_MODEL", "")
    monkeypatch.setattr(agent, "STT_TBANK_LANGUAGE", "ru-RU")
    monkeypatch.setattr(agent, "STT_TBANK_SAMPLE_RATE", 16000)
    monkeypatch.setattr(agent, "STT_TBANK_CHUNK_MS", 50)
    monkeypatch.setattr(agent, "STT_TBANK_INTERIM_INTERVAL_SEC", 0.1)
    monkeypatch.setattr(agent, "TBANK_VOICEKIT_AUTHORITY", "")
    monkeypatch.setattr(agent, "STT_EARLY_INTERIM_FINAL_ENABLED", False)
    monkeypatch.setattr(agent, "TBankVoiceKitSTT", _FakeTBankSTT)

    result = agent.build_stt()

    assert isinstance(result, _FakeTBankSTT)
    assert captured == {
        "api_key": "test-key",
        "secret_key": "test-secret",
        "model": "",
        "language": "ru-RU",
        "sample_rate": 16000,
        "chunk_ms": 50,
        "interim_interval_sec": 0.1,
        "endpoint": "api.tinkoff.ai:443",
        "authority": "",
    }
