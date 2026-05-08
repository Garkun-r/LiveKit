from livekit import rtc

from agent import (
    event_timestamp_seconds,
    extract_sip_diagnostic_context,
    is_abnormal_close,
    should_log_startup_provider_fallback,
    turn_response_latency_ms,
)


class _Participant:
    def __init__(self, *, attributes, kind=rtc.ParticipantKind.PARTICIPANT_KIND_SIP):
        self.attributes = attributes
        self.kind = kind


class _Component:
    def __init__(self, *, provider: str, model: str):
        self.provider = provider
        self.model = model


class _FallbackComponent:
    provider = "livekit"
    model = "FallbackAdapter"

    def __init__(self, instances):
        self._stt_instances = instances


class _Event:
    def __init__(self, *, created_at=None):
        self.created_at = created_at


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
