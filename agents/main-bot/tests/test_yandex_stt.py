import asyncio

import pytest
from livekit import rtc
from livekit.agents import stt

import agent
from yandex_speechkit_proto import yandex_stt_pb2 as yandex_pb
from yandex_stt import (
    YandexSpeechKitSTT,
    YandexSTTOptions,
    build_yandex_streaming_options,
)


class _FakeYandexCall:
    def __init__(
        self,
        requests,
        responses,
        seen_requests,
    ) -> None:
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


async def _collect_events(stt_client: YandexSpeechKitSTT, frames=()):
    stream = stt_client.stream()
    for frame in frames:
        stream.push_frame(frame)
    stream.end_input()
    return [event async for event in stream]


def _stt_with_responses(responses):
    seen_requests = []
    seen_metadata = []

    def fake_recognize_stream(requests, metadata):
        seen_metadata.append(metadata)
        return _FakeYandexCall(requests, responses, seen_requests)

    client = YandexSpeechKitSTT(
        api_key="test-yandex-key",
        recognize_stream_factory=fake_recognize_stream,
    )
    return client, seen_requests, seen_metadata


def test_build_yandex_streaming_options_uses_low_latency_defaults() -> None:
    options = build_yandex_streaming_options(
        YandexSTTOptions(
            api_key="test-key",
            model="general",
            language="ru-RU",
            sample_rate=16000,
            chunk_ms=50,
            eou_sensitivity="high",
            max_pause_between_words_hint_ms=500,
        )
    )

    model = options.recognition_model
    assert model.model == "general"
    assert model.audio_processing_type == yandex_pb.RecognitionModelOptions.REAL_TIME
    assert model.audio_format.WhichOneof("AudioFormat") == "raw_audio"
    assert model.audio_format.raw_audio.audio_encoding == yandex_pb.RawAudio.LINEAR16_PCM
    assert model.audio_format.raw_audio.sample_rate_hertz == 16000
    assert model.audio_format.raw_audio.audio_channel_count == 1
    assert model.language_restriction.restriction_type == (
        yandex_pb.LanguageRestrictionOptions.WHITELIST
    )
    assert list(model.language_restriction.language_code) == ["ru-RU"]
    assert options.eou_classifier.default_classifier.type == (
        yandex_pb.DefaultEouClassifier.HIGH
    )
    assert (
        options.eou_classifier.default_classifier.max_pause_between_words_hint_ms
        == 500
    )


def test_build_yandex_streaming_options_clamps_pause_hint_to_yandex_minimum() -> None:
    options = build_yandex_streaming_options(
        YandexSTTOptions(
            api_key="test-key",
            max_pause_between_words_hint_ms=250,
        )
    )

    assert (
        options.eou_classifier.default_classifier.max_pause_between_words_hint_ms
        == 500
    )


@pytest.mark.asyncio
async def test_yandex_stream_maps_partial_final_and_eou_to_livekit_events() -> None:
    responses = [
        yandex_pb.StreamingResponse(
            session_uuid=yandex_pb.SessionUuid(uuid="session-1"),
            partial=yandex_pb.AlternativeUpdate(
                alternatives=[
                    yandex_pb.Alternative(
                        text="прив",
                        start_time_ms=0,
                        end_time_ms=120,
                        confidence=0.4,
                        languages=[
                            yandex_pb.LanguageEstimation(
                                language_code="ru-RU",
                                probability=0.95,
                            )
                        ],
                    )
                ]
            ),
        ),
        yandex_pb.StreamingResponse(
            session_uuid=yandex_pb.SessionUuid(uuid="session-1"),
            final=yandex_pb.AlternativeUpdate(
                alternatives=[
                    yandex_pb.Alternative(
                        text="привет",
                        start_time_ms=0,
                        end_time_ms=300,
                        confidence=0.9,
                    )
                ]
            ),
        ),
        yandex_pb.StreamingResponse(
            session_uuid=yandex_pb.SessionUuid(uuid="session-1"),
            eou_update=yandex_pb.EouUpdate(time_ms=320),
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
    assert events[2].request_id == "session-1"


@pytest.mark.asyncio
async def test_yandex_stream_ignores_empty_status_and_final_refinement() -> None:
    responses = [
        yandex_pb.StreamingResponse(
            partial=yandex_pb.AlternativeUpdate(alternatives=[]),
        ),
        yandex_pb.StreamingResponse(
            status_code=yandex_pb.StatusCode(
                code_type=yandex_pb.WORKING,
                message="ok",
            ),
        ),
        yandex_pb.StreamingResponse(
            final_refinement=yandex_pb.FinalRefinement(
                final_index=1,
                normalized_text=yandex_pb.AlternativeUpdate(
                    alternatives=[
                        yandex_pb.Alternative(text="нормализованный текст")
                    ]
                ),
            ),
        ),
    ]
    stt_client, _, _ = _stt_with_responses(responses)

    events = await _collect_events(stt_client)

    assert events == []


@pytest.mark.asyncio
async def test_yandex_stream_sends_api_key_metadata_and_50ms_pcm_chunks() -> None:
    stt_client, seen_requests, seen_metadata = _stt_with_responses([])
    frame = rtc.AudioFrame(
        data=bytes(1600 * 2),
        sample_rate=16000,
        num_channels=1,
        samples_per_channel=1600,
    )

    await asyncio.wait_for(_collect_events(stt_client, frames=[frame]), timeout=2)

    assert seen_metadata == [(("authorization", "Api-Key test-yandex-key"),)]
    assert seen_requests[0].WhichOneof("Event") == "session_options"
    chunk_requests = [
        request for request in seen_requests if request.WhichOneof("Event") == "chunk"
    ]
    assert len(chunk_requests) == 2
    assert [len(request.chunk.data) for request in chunk_requests] == [1600, 1600]


def test_build_stt_uses_yandex_provider(monkeypatch) -> None:
    captured = {}

    class _FakeYandexSTT:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(agent, "STT_PROVIDER", "yandex")
    monkeypatch.setattr(agent, "YANDEX_SPEECHKIT_API_KEY", "test-key")
    monkeypatch.setattr(agent, "STT_YANDEX_MODEL", "general")
    monkeypatch.setattr(agent, "STT_YANDEX_LANGUAGE", "ru-RU")
    monkeypatch.setattr(agent, "STT_YANDEX_SAMPLE_RATE", 16000)
    monkeypatch.setattr(agent, "STT_YANDEX_CHUNK_MS", 50)
    monkeypatch.setattr(agent, "STT_YANDEX_EOU_SENSITIVITY", "high")
    monkeypatch.setattr(agent, "STT_YANDEX_MAX_PAUSE_BETWEEN_WORDS_HINT_MS", 500)
    monkeypatch.setattr(agent, "STT_EARLY_INTERIM_FINAL_ENABLED", False)
    monkeypatch.setattr(agent, "YandexSpeechKitSTT", _FakeYandexSTT)

    result = agent.build_stt()

    assert isinstance(result, _FakeYandexSTT)
    assert captured == {
        "api_key": "test-key",
        "model": "general",
        "language": "ru-RU",
        "sample_rate": 16000,
        "chunk_ms": 50,
        "eou_sensitivity": "high",
        "max_pause_between_words_hint_ms": 500,
    }


def test_build_stt_yandex_missing_key_falls_back_to_inference(monkeypatch) -> None:
    captured = {}

    class _FakeInferenceSTT:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(agent, "STT_PROVIDER", "yandex")
    monkeypatch.setattr(agent, "YANDEX_SPEECHKIT_API_KEY", "")
    monkeypatch.setattr(agent, "STT_INFERENCE_MODEL", "deepgram/nova-3")
    monkeypatch.setattr(agent, "STT_INFERENCE_LANGUAGE", "ru")
    monkeypatch.setattr(agent, "STT_EARLY_INTERIM_FINAL_ENABLED", False)
    monkeypatch.setattr(agent.inference, "STT", _FakeInferenceSTT)

    result = agent.build_stt()

    assert isinstance(result, _FakeInferenceSTT)
    assert captured == {
        "model": "deepgram/nova-3",
        "language": "ru",
    }
