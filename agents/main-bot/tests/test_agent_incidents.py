import asyncio

import pytest
from livekit import rtc
from livekit.agents.llm.tool_context import StopResponse

from agent import (
    Assistant,
    event_timestamp_seconds,
    extract_sip_diagnostic_context,
    is_abnormal_close,
    should_fire_startup_no_dialog_timeout,
    should_log_slow_response_latency,
    should_log_startup_provider_fallback,
    should_play_initial_greeting,
    turn_response_latency_ms,
    wait_for_initial_greeting_delay,
    wait_for_speech_playout,
)


class _Participant:
    def __init__(self, *, attributes, kind=rtc.ParticipantKind.PARTICIPANT_KIND_SIP):
        self.attributes = attributes
        self.kind = kind


class _Component:
    def __init__(self, *, provider: str, model: str):
        self.provider = provider
        self.model = model


class _ChatMessage:
    def __init__(self, text_content: str):
        self.text_content = text_content


class _FallbackComponent:
    provider = "livekit"
    model = "FallbackAdapter"

    def __init__(self, instances):
        self._stt_instances = instances


class _Event:
    def __init__(self, *, created_at=None):
        self.created_at = created_at


class _SpeechHandle:
    def __init__(self, *, done: bool = False):
        self._done = done
        self.stopped = False
        self.interrupted = False

    async def wait_for_playout(self) -> None:
        while not self._done:
            await asyncio.sleep(0.01)

    def stop(self) -> None:
        self.stopped = True
        self._done = True

    def interrupt(self, *, force: bool = False) -> None:
        self.interrupted = force
        self._done = True


def test_extract_sip_diagnostic_context_reads_trace_and_call_id() -> None:
    result = extract_sip_diagnostic_context(
        _Participant(
            attributes={
                "sip.h.X-DID": "4012312389",
                "sip.phoneNumber": "79990001122",
                "sip.h.X-TRACEID": "trace-123",
                "sip.callID": "sip-call-456",
            }
        )
    )

    assert result == {
        "did": "4012312389",
        "caller_phone": "79990001122",
        "trace_id": "trace-123",
        "sip_call_id": "sip-call-456",
    }


def test_should_log_startup_provider_fallback_for_missing_configured_provider() -> None:
    assert (
        should_log_startup_provider_fallback(
            component_name="tts",
            configured_provider="google",
            actual_component=_Component(provider="ElevenLabs", model="eleven_flash"),
        )
        is True
    )


def test_should_not_log_startup_provider_fallback_when_chain_contains_provider() -> (
    None
):
    assert (
        should_log_startup_provider_fallback(
            component_name="stt",
            configured_provider="google",
            actual_component=_FallbackComponent(
                [_Component(provider="Google Cloud", model="latest_long")]
            ),
        )
        is False
    )


def test_is_abnormal_close_only_flags_error_like_reasons() -> None:
    assert is_abnormal_close("end_call:conversation_completed", None) is False
    assert is_abnormal_close("participant_disconnected", None) is False
    assert is_abnormal_close("entrypoint_cancelled", None) is True
    assert is_abnormal_close("anything", "transport lost") is True


def test_startup_no_dialog_timeout_only_fires_without_activity() -> None:
    assert (
        should_fire_startup_no_dialog_timeout(
            timeout_sec=12,
            close_event_set=False,
            dialog_activity_seen=False,
            end_call_scheduled=False,
        )
        is True
    )
    assert (
        should_fire_startup_no_dialog_timeout(
            timeout_sec=12,
            close_event_set=False,
            dialog_activity_seen=True,
            end_call_scheduled=False,
        )
        is False
    )
    assert (
        should_fire_startup_no_dialog_timeout(
            timeout_sec=0,
            close_event_set=False,
            dialog_activity_seen=False,
            end_call_scheduled=False,
        )
        is False
    )


@pytest.mark.asyncio
async def test_speech_playout_timeout_stops_handle() -> None:
    handle = _SpeechHandle(done=False)

    played = await wait_for_speech_playout(
        handle,
        kind="initial_greeting",
        log_label="initial greeting",
        timeout_sec=0.01,
    )

    assert played is False
    assert handle.stopped is True


def test_turn_response_latency_measures_user_end_to_agent_start() -> None:
    assert (
        turn_response_latency_ms(
            user_phrase_ended_at=100.0,
            assistant_started_at=104.25,
        )
        == 4250.0
    )


def test_event_timestamp_seconds_falls_back_when_created_at_missing() -> None:
    assert event_timestamp_seconds(_Event(created_at=123.5)) == 123.5
    assert event_timestamp_seconds(_Event(), default=456.0) == 456.0


def test_should_log_slow_response_latency_when_threshold_is_reached() -> None:
    assert should_log_slow_response_latency(7000, 7000) is True
    assert should_log_slow_response_latency(7200.5, 7000) is True


def test_should_not_log_slow_response_latency_below_threshold_or_disabled() -> None:
    assert should_log_slow_response_latency(None, 7000) is False
    assert should_log_slow_response_latency(6999.9, 7000) is False
    assert should_log_slow_response_latency(10000, 0) is False


def test_initial_greeting_plays_regardless_of_user_speech() -> None:
    assert should_play_initial_greeting(close_event_set=False) is True


def test_initial_greeting_is_skipped_after_close() -> None:
    assert should_play_initial_greeting(close_event_set=True) is False


@pytest.mark.asyncio
async def test_initial_greeting_in_progress_ignores_first_user_turn() -> None:
    assistant = Assistant(prompt="test prompt")
    assistant.begin_initial_greeting()

    with pytest.raises(StopResponse):
        await assistant.on_user_turn_completed(None, _ChatMessage("алло"))

    assert assistant._awaiting_first_user_turn is True


@pytest.mark.asyncio
async def test_initial_greeting_delay_waits_configured_seconds(monkeypatch) -> None:
    calls = []

    async def fake_sleep(delay_sec):
        calls.append(delay_sec)

    monkeypatch.setattr("agent.asyncio.sleep", fake_sleep)

    await wait_for_initial_greeting_delay(1.5)

    assert calls == [1.5]


@pytest.mark.asyncio
async def test_initial_greeting_delay_skips_non_positive_values(monkeypatch) -> None:
    calls = []

    async def fake_sleep(delay_sec):
        calls.append(delay_sec)

    monkeypatch.setattr("agent.asyncio.sleep", fake_sleep)

    await wait_for_initial_greeting_delay(0)
    await wait_for_initial_greeting_delay(-1)

    assert calls == []
