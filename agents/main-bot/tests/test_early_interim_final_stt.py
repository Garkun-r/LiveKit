from __future__ import annotations

import asyncio

import pytest
from livekit.agents import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions, stt
from livekit.agents.types import NOT_GIVEN, NotGivenOr
from livekit.agents.utils import AudioBuffer

import agent
from early_interim_final_stt import (
    EarlyInterimFinalSTT,
    should_wrap_stt,
)


def _event(
    event_type: stt.SpeechEventType,
    text: str = "",
    *,
    request_id: str = "req",
) -> stt.SpeechEvent:
    if event_type == stt.SpeechEventType.RECOGNITION_USAGE:
        return stt.SpeechEvent(
            type=event_type,
            request_id=request_id,
            recognition_usage=stt.RecognitionUsage(audio_duration=0.1),
        )
    alternatives = []
    if text:
        alternatives = [stt.SpeechData(language="ru", text=text, confidence=0.8)]
    return stt.SpeechEvent(
        type=event_type,
        request_id=request_id,
        alternatives=alternatives,
    )


class _ScriptedSTT(stt.STT):
    def __init__(
        self,
        script: list[tuple[float, stt.SpeechEvent]] | None = None,
        *,
        streaming: bool = True,
        interim_results: bool = True,
    ) -> None:
        super().__init__(
            capabilities=stt.STTCapabilities(
                streaming=streaming,
                interim_results=interim_results,
                offline_recognize=False,
            )
        )
        self._script = script or []
        self.closed = False

    @property
    def model(self) -> str:
        return "scripted-model"

    @property
    def provider(self) -> str:
        return "scripted-provider"

    async def _recognize_impl(
        self,
        buffer: AudioBuffer,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions,
    ) -> stt.SpeechEvent:
        return _event(stt.SpeechEventType.FINAL_TRANSCRIPT, "recognized")

    def stream(
        self,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> _ScriptedStream:
        return _ScriptedStream(
            stt_obj=self, script=self._script, conn_options=conn_options
        )

    async def aclose(self) -> None:
        self.closed = True


class _ScriptedStream(stt.SpeechStream):
    def __init__(
        self,
        *,
        stt_obj: _ScriptedSTT,
        script: list[tuple[float, stt.SpeechEvent]],
        conn_options: APIConnectOptions,
    ) -> None:
        super().__init__(stt=stt_obj, conn_options=conn_options)
        self._script = script

    async def _run(self) -> None:
        for delay, event in self._script:
            await asyncio.sleep(delay)
            self._event_ch.send_nowait(event)


async def _collect_events(stt_client: stt.STT) -> list[stt.SpeechEvent]:
    stream = stt_client.stream()
    stream.end_input()
    return [event async for event in stream]


async def _collect_events_with_local_vad_notify(
    stt_client: EarlyInterimFinalSTT,
    *,
    notify_after_sec: float,
    timeout_sec: float = 1.0,
) -> list[stt.SpeechEvent]:
    stream = stt_client.stream()
    stream.end_input()
    events: list[stt.SpeechEvent] = []

    async def _collect() -> None:
        async for event in stream:
            events.append(event)

    collect_task = asyncio.create_task(_collect())
    await asyncio.sleep(notify_after_sec)
    stt_client.notify_local_end_of_speech(ended_at=123.0)
    await asyncio.wait_for(collect_task, timeout=timeout_sec)
    return events


def test_should_wrap_stt_respects_disabled_mode() -> None:
    assert not should_wrap_stt(
        _ScriptedSTT(),
        enabled=False,
        turn_detection_mode="vad",
    )


def test_should_wrap_stt_requires_streaming_interim_support() -> None:
    assert not should_wrap_stt(
        _ScriptedSTT(streaming=True, interim_results=False),
        enabled=True,
        turn_detection_mode="vad",
    )
    assert not should_wrap_stt(
        _ScriptedSTT(streaming=False, interim_results=True),
        enabled=True,
        turn_detection_mode="vad",
    )


@pytest.mark.asyncio
async def test_real_final_before_delay_passes_without_synthetic() -> None:
    wrapped = EarlyInterimFinalSTT(
        _ScriptedSTT(
            [
                (0, _event(stt.SpeechEventType.START_OF_SPEECH)),
                (0, _event(stt.SpeechEventType.INTERIM_TRANSCRIPT, "привет")),
                (0, _event(stt.SpeechEventType.END_OF_SPEECH)),
                (0.01, _event(stt.SpeechEventType.FINAL_TRANSCRIPT, "привет")),
            ]
        ),
        delay_sec=0.05,
    )

    events = await _collect_events(wrapped)

    assert [event.type for event in events] == [
        stt.SpeechEventType.START_OF_SPEECH,
        stt.SpeechEventType.INTERIM_TRANSCRIPT,
        stt.SpeechEventType.FINAL_TRANSCRIPT,
        stt.SpeechEventType.END_OF_SPEECH,
    ]
    assert events[2].alternatives[0].text == "привет"


@pytest.mark.asyncio
async def test_interim_becomes_synthetic_final_after_eos_delay() -> None:
    wrapped = EarlyInterimFinalSTT(
        _ScriptedSTT(
            [
                (0, _event(stt.SpeechEventType.START_OF_SPEECH)),
                (0, _event(stt.SpeechEventType.INTERIM_TRANSCRIPT, "адрес")),
                (0, _event(stt.SpeechEventType.END_OF_SPEECH)),
                (0.05, _event(stt.SpeechEventType.RECOGNITION_USAGE)),
            ]
        ),
        delay_sec=0.01,
    )

    events = await _collect_events(wrapped)

    assert [event.type for event in events[:4]] == [
        stt.SpeechEventType.START_OF_SPEECH,
        stt.SpeechEventType.INTERIM_TRANSCRIPT,
        stt.SpeechEventType.FINAL_TRANSCRIPT,
        stt.SpeechEventType.END_OF_SPEECH,
    ]
    assert events[2].alternatives[0].text == "адрес"


@pytest.mark.asyncio
async def test_local_vad_end_creates_synthetic_final_without_stt_eos() -> None:
    wrapped = EarlyInterimFinalSTT(
        _ScriptedSTT(
            [
                (0, _event(stt.SpeechEventType.START_OF_SPEECH)),
                (0, _event(stt.SpeechEventType.INTERIM_TRANSCRIPT, "адрес")),
                (0.05, _event(stt.SpeechEventType.FINAL_TRANSCRIPT, "адрес")),
            ]
        ),
        delay_sec=0.01,
    )

    events = await _collect_events_with_local_vad_notify(
        wrapped,
        notify_after_sec=0.001,
    )

    assert [event.type for event in events] == [
        stt.SpeechEventType.START_OF_SPEECH,
        stt.SpeechEventType.INTERIM_TRANSCRIPT,
        stt.SpeechEventType.FINAL_TRANSCRIPT,
    ]
    assert events[2].alternatives[0].text == "адрес"


@pytest.mark.asyncio
async def test_real_final_before_local_vad_delay_cancels_synthetic() -> None:
    wrapped = EarlyInterimFinalSTT(
        _ScriptedSTT(
            [
                (0, _event(stt.SpeechEventType.START_OF_SPEECH)),
                (0, _event(stt.SpeechEventType.INTERIM_TRANSCRIPT, "адрес")),
                (0.005, _event(stt.SpeechEventType.FINAL_TRANSCRIPT, "точный адрес")),
            ]
        ),
        delay_sec=0.05,
    )

    events = await _collect_events_with_local_vad_notify(
        wrapped,
        notify_after_sec=0.001,
    )

    assert [event.type for event in events] == [
        stt.SpeechEventType.START_OF_SPEECH,
        stt.SpeechEventType.INTERIM_TRANSCRIPT,
        stt.SpeechEventType.FINAL_TRANSCRIPT,
    ]
    assert events[2].alternatives[0].text == "точный адрес"


@pytest.mark.asyncio
async def test_local_vad_deadline_waits_for_next_interim_if_none_seen() -> None:
    wrapped = EarlyInterimFinalSTT(
        _ScriptedSTT(
            [
                (0, _event(stt.SpeechEventType.START_OF_SPEECH)),
                (0.05, _event(stt.SpeechEventType.INTERIM_TRANSCRIPT, "адрес")),
                (0.05, _event(stt.SpeechEventType.FINAL_TRANSCRIPT, "адрес")),
            ]
        ),
        delay_sec=0.01,
    )

    events = await _collect_events_with_local_vad_notify(
        wrapped,
        notify_after_sec=0.001,
    )

    assert [event.type for event in events] == [
        stt.SpeechEventType.START_OF_SPEECH,
        stt.SpeechEventType.INTERIM_TRANSCRIPT,
        stt.SpeechEventType.FINAL_TRANSCRIPT,
    ]
    assert events[2].alternatives[0].text == "адрес"


@pytest.mark.asyncio
async def test_local_vad_waits_for_provider_final_when_interim_is_not_stable() -> None:
    wrapped = EarlyInterimFinalSTT(
        _ScriptedSTT(
            [
                (0, _event(stt.SpeechEventType.START_OF_SPEECH)),
                (0, _event(stt.SpeechEventType.INTERIM_TRANSCRIPT, "чего денег")),
                (
                    0.05,
                    _event(stt.SpeechEventType.FINAL_TRANSCRIPT, "чем вы занимаетесь"),
                ),
            ]
        ),
        delay_sec=0.01,
        min_stable_interims=2,
    )

    events = await _collect_events_with_local_vad_notify(
        wrapped,
        notify_after_sec=0.001,
    )

    assert [event.type for event in events] == [
        stt.SpeechEventType.START_OF_SPEECH,
        stt.SpeechEventType.INTERIM_TRANSCRIPT,
        stt.SpeechEventType.FINAL_TRANSCRIPT,
    ]
    assert events[2].alternatives[0].text == "чем вы занимаетесь"


@pytest.mark.asyncio
async def test_local_vad_creates_synthetic_after_stable_interim_repeats() -> None:
    wrapped = EarlyInterimFinalSTT(
        _ScriptedSTT(
            [
                (0, _event(stt.SpeechEventType.START_OF_SPEECH)),
                (0, _event(stt.SpeechEventType.INTERIM_TRANSCRIPT, "адрес")),
                (0.05, _event(stt.SpeechEventType.INTERIM_TRANSCRIPT, "адрес")),
                (0.05, _event(stt.SpeechEventType.RECOGNITION_USAGE)),
            ]
        ),
        delay_sec=0.01,
        min_stable_interims=2,
    )

    events = await _collect_events_with_local_vad_notify(
        wrapped,
        notify_after_sec=0.001,
    )

    assert [event.type for event in events[:4]] == [
        stt.SpeechEventType.START_OF_SPEECH,
        stt.SpeechEventType.INTERIM_TRANSCRIPT,
        stt.SpeechEventType.INTERIM_TRANSCRIPT,
        stt.SpeechEventType.FINAL_TRANSCRIPT,
    ]
    assert events[3].alternatives[0].text == "адрес"


@pytest.mark.asyncio
async def test_late_duplicate_final_after_synthetic_is_suppressed() -> None:
    wrapped = EarlyInterimFinalSTT(
        _ScriptedSTT(
            [
                (0, _event(stt.SpeechEventType.START_OF_SPEECH)),
                (0, _event(stt.SpeechEventType.INTERIM_TRANSCRIPT, "какой адрес")),
                (0, _event(stt.SpeechEventType.END_OF_SPEECH)),
                (0.05, _event(stt.SpeechEventType.FINAL_TRANSCRIPT, "Какой   адрес")),
            ]
        ),
        delay_sec=0.01,
    )

    events = await _collect_events(wrapped)

    assert [event.type for event in events] == [
        stt.SpeechEventType.START_OF_SPEECH,
        stt.SpeechEventType.INTERIM_TRANSCRIPT,
        stt.SpeechEventType.FINAL_TRANSCRIPT,
        stt.SpeechEventType.END_OF_SPEECH,
    ]


@pytest.mark.asyncio
async def test_late_different_final_after_synthetic_is_suppressed() -> None:
    wrapped = EarlyInterimFinalSTT(
        _ScriptedSTT(
            [
                (0, _event(stt.SpeechEventType.START_OF_SPEECH)),
                (0, _event(stt.SpeechEventType.INTERIM_TRANSCRIPT, "адрес")),
                (0, _event(stt.SpeechEventType.END_OF_SPEECH)),
                (0.05, _event(stt.SpeechEventType.FINAL_TRANSCRIPT, "цены")),
            ]
        ),
        delay_sec=0.01,
    )

    events = await _collect_events(wrapped)

    assert [event.type for event in events] == [
        stt.SpeechEventType.START_OF_SPEECH,
        stt.SpeechEventType.INTERIM_TRANSCRIPT,
        stt.SpeechEventType.FINAL_TRANSCRIPT,
        stt.SpeechEventType.END_OF_SPEECH,
    ]
    assert events[2].alternatives[0].text == "адрес"


@pytest.mark.asyncio
async def test_new_start_of_speech_cancels_pending_synthetic_final() -> None:
    wrapped = EarlyInterimFinalSTT(
        _ScriptedSTT(
            [
                (0, _event(stt.SpeechEventType.START_OF_SPEECH)),
                (0, _event(stt.SpeechEventType.INTERIM_TRANSCRIPT, "старый")),
                (0, _event(stt.SpeechEventType.END_OF_SPEECH)),
                (0.005, _event(stt.SpeechEventType.START_OF_SPEECH)),
                (0, _event(stt.SpeechEventType.INTERIM_TRANSCRIPT, "новый")),
                (0, _event(stt.SpeechEventType.END_OF_SPEECH)),
                (0.05, _event(stt.SpeechEventType.RECOGNITION_USAGE)),
            ]
        ),
        delay_sec=0.02,
    )

    events = await _collect_events(wrapped)

    assert [event.type for event in events[:5]] == [
        stt.SpeechEventType.START_OF_SPEECH,
        stt.SpeechEventType.INTERIM_TRANSCRIPT,
        stt.SpeechEventType.START_OF_SPEECH,
        stt.SpeechEventType.INTERIM_TRANSCRIPT,
        stt.SpeechEventType.FINAL_TRANSCRIPT,
    ]
    assert events[4].alternatives[0].text == "новый"


def test_metrics_and_error_events_are_forwarded() -> None:
    base = _ScriptedSTT()
    wrapped = EarlyInterimFinalSTT(base)
    seen_metrics = []
    seen_errors = []
    marker_metric = object()
    marker_error = object()

    wrapped.on("metrics_collected", seen_metrics.append)
    wrapped.on("error", seen_errors.append)

    base.emit("metrics_collected", marker_metric)
    base.emit("error", marker_error)

    assert seen_metrics == [marker_metric]
    assert seen_errors == [marker_error]


def test_build_stt_wraps_any_streaming_interim_provider_when_enabled(
    monkeypatch,
) -> None:
    fake_stt = _ScriptedSTT()

    monkeypatch.setattr(agent, "STT_PROVIDER", "yandex")
    monkeypatch.setattr(agent, "YANDEX_SPEECHKIT_API_KEY", "test-key")
    monkeypatch.setattr(agent, "STT_EARLY_INTERIM_FINAL_ENABLED", True)
    monkeypatch.setattr(agent, "STT_EARLY_INTERIM_FINAL_DELAY_SEC", 0.15)
    monkeypatch.setattr(agent, "STT_EARLY_INTERIM_FINAL_MIN_STABLE_INTERIMS", 2)
    monkeypatch.setattr(agent, "TURN_DETECTION_MODE", "vad")
    monkeypatch.setattr(agent, "YandexSpeechKitSTT", lambda **_: fake_stt)

    result = agent.build_stt()

    assert isinstance(result, EarlyInterimFinalSTT)
    assert result.wrapped is fake_stt
    assert result.min_stable_interims == 2
