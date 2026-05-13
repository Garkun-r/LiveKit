import asyncio
from types import SimpleNamespace

import pytest
from livekit import rtc
from livekit.agents.llm.tool_context import StopResponse

import agent
from agent import (
    Assistant,
    build_agent_room_options,
    clear_initial_greeting_user_turn,
    disconnect_reason_name,
    event_timestamp_seconds,
    extract_sip_diagnostic_context,
    is_abnormal_close,
    should_fire_startup_no_dialog_timeout,
    should_log_slow_response_latency,
    should_log_startup_provider_fallback,
    should_play_initial_greeting,
    should_stop_recording_on_close,
    turn_response_latency_ms,
    wait_for_initial_greeting_delay,
    wait_for_short_greeting_delay,
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


class _Session:
    def __init__(self) -> None:
        self.interrupt_calls: list[bool] = []
        self.clear_user_turn_calls = 0

    async def interrupt(self, *, force: bool = False) -> None:
        self.interrupt_calls.append(force)

    def clear_user_turn(self) -> None:
        self.clear_user_turn_calls += 1


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


def test_should_stop_recording_on_participant_disconnect_close() -> None:
    assert should_stop_recording_on_close("CloseReason.PARTICIPANT_DISCONNECTED") is True
    assert should_stop_recording_on_close("participant_disconnected") is True
    assert should_stop_recording_on_close("tag_action:END") is False


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


def test_disconnect_reason_name_handles_livekit_enum_values() -> None:
    assert (
        disconnect_reason_name(rtc.DisconnectReason.CLIENT_INITIATED)
        == "CLIENT_INITIATED"
    )


def test_agent_room_options_delete_room_on_close() -> None:
    options = build_agent_room_options(audio_output_sample_rate=16000)

    assert options.delete_room_on_close is True
    assert options.get_audio_output_options().sample_rate == 16000


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


def test_clear_initial_greeting_user_turn_discards_buffered_turn() -> None:
    session = _Session()

    assert clear_initial_greeting_user_turn(session) is True
    assert session.clear_user_turn_calls == 1


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


@pytest.mark.asyncio
async def test_short_greeting_delay_waits_configured_seconds(monkeypatch) -> None:
    calls = []

    async def fake_sleep(delay_sec):
        calls.append(delay_sec)

    monkeypatch.setattr("agent.asyncio.sleep", fake_sleep)

    await wait_for_short_greeting_delay(1.0)

    assert calls == [1.0]


@pytest.mark.asyncio
async def test_short_greeting_followup_cancels_if_user_resumes_before_delay(
    monkeypatch,
) -> None:
    assistant = Assistant(
        prompt="test prompt",
        first_turn_short_greeting_delay_sec=1.0,
    )
    session = _Session()
    assistant._activity = SimpleNamespace(session=session)
    resolved = False

    async def fake_sleep(delay_sec):
        assert delay_sec == 1.0
        assistant.note_user_started_speaking()

    async def fake_resolve_short_greeting_audio_path(**kwargs):
        nonlocal resolved
        resolved = True
        return None

    monkeypatch.setattr("agent.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(
        "agent.resolve_short_greeting_audio_path",
        fake_resolve_short_greeting_audio_path,
    )

    with pytest.raises(StopResponse):
        await assistant.on_user_turn_completed(None, _ChatMessage("алло"))

    assert session.interrupt_calls == []
    assert resolved is False
    assert assistant._awaiting_first_user_turn is False


@pytest.mark.asyncio
async def test_short_greeting_followup_plays_after_delay_when_user_stays_silent(
    monkeypatch,
    tmp_path,
) -> None:
    assistant = Assistant(
        prompt="test prompt",
        first_turn_short_greeting_delay_sec=0.7,
    )
    session = _Session()
    assistant._activity = SimpleNamespace(session=session)
    audio_path = tmp_path / "short.wav"
    audio_path.write_bytes(b"fake")
    delays = []
    played_calls = []

    async def fake_sleep(delay_sec):
        delays.append(delay_sec)

    async def fake_resolve_short_greeting_audio_path(**kwargs):
        return audio_path

    async def fake_play_prerecorded_audio(**kwargs):
        played_calls.append(kwargs)
        return True

    monkeypatch.setattr("agent.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(
        "agent.resolve_short_greeting_audio_path",
        fake_resolve_short_greeting_audio_path,
    )
    monkeypatch.setattr("agent.play_prerecorded_audio", fake_play_prerecorded_audio)

    with pytest.raises(StopResponse):
        await assistant.on_user_turn_completed(None, _ChatMessage("алло"))

    assert delays == [0.7]
    assert session.interrupt_calls == [True]
    assert played_calls[0]["session"] is session
    assert played_calls[0]["audio_path"] == audio_path
    assert played_calls[0]["allow_interruptions"] is True


@pytest.mark.asyncio
async def test_tts_node_cancels_before_first_audio_if_user_resumed(monkeypatch) -> None:
    assistant = Assistant(prompt="test prompt")
    fake_frame = object()

    class FakeSpeech:
        id = "speech-1"

        def __init__(self) -> None:
            self.interrupted = False

        def interrupt(self, *, force: bool = False) -> None:
            self.interrupted = force

    fake_speech = FakeSpeech()

    async def fake_tts_node(self, text, model_settings):
        yield fake_frame

    async def text_source():
        yield "hello"

    monkeypatch.setattr(agent.Agent.default, "tts_node", fake_tts_node)
    monkeypatch.setattr(assistant, "_current_speech_handle", lambda: fake_speech)
    assistant._speech_start_user_revisions["speech-1"] = 0
    assistant.note_user_started_speaking()

    frames = [frame async for frame in assistant.tts_node(text_source(), object())]

    assert frames == []
    assert fake_speech.interrupted is True
    assert "speech-1" not in assistant._speech_start_user_revisions


@pytest.mark.asyncio
async def test_tts_node_allows_first_audio_when_user_stays_silent(monkeypatch) -> None:
    assistant = Assistant(prompt="test prompt")
    fake_frame = object()

    class FakeSpeech:
        id = "speech-1"

        def __init__(self) -> None:
            self.interrupted = False

        def interrupt(self, *, force: bool = False) -> None:
            self.interrupted = force

    fake_speech = FakeSpeech()

    async def fake_tts_node(self, text, model_settings):
        yield fake_frame

    async def text_source():
        yield "hello"

    monkeypatch.setattr(agent.Agent.default, "tts_node", fake_tts_node)
    monkeypatch.setattr(assistant, "_current_speech_handle", lambda: fake_speech)
    assistant._speech_start_user_revisions["speech-1"] = 0

    frames = [frame async for frame in assistant.tts_node(text_source(), object())]

    assert frames == [fake_frame]
    assert fake_speech.interrupted is False
    assert "speech-1" not in assistant._speech_start_user_revisions
