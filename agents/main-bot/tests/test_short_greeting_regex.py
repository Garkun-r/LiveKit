import pytest
from livekit import rtc

from agent import (
    extract_sip_call_numbers,
    is_response_delay_candidate_transcript,
    is_short_greeting_response,
    resolve_initial_greeting_audio,
    resolve_short_greeting_audio_path,
    should_start_response_delay_after_vad,
)


class _Participant:
    def __init__(self, *, attributes, kind=rtc.ParticipantKind.PARTICIPANT_KIND_SIP):
        self.attributes = attributes
        self.kind = kind


class _VoiceAudioCache:
    def __init__(self, audio_path):
        self.audio_path = audio_path
        self.calls = []

    async def get_or_create(self, *, kind, text, legacy_path=None):
        self.calls.append(
            {
                "kind": kind,
                "text": text,
                "legacy_path": legacy_path,
            }
        )
        return self.audio_path


@pytest.mark.parametrize(
    "text",
    [
        "Алло",
        "ало",
        "алё",
        "алло алло",
        "алло здравствуйте",
        "алло девушка здрасьте",
        "доброе утро",
        "добрый день.",
        "алло доброе утро",
        "алло добрый день.",
        "да, да, здрасте.",
        "да, да, здравствуйте.",
        "да, здрасте.",
    ],
)
def test_is_short_greeting_response_matches_expected_greetings(text: str) -> None:
    assert is_short_greeting_response(text) is True


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "   ",
        "алло чем вы занимаетесь",
        "аллоа чем вы занимаетесь",
        "да, да, подскажите стоимость",
        "здравствуйте подскажите стоимость",
        "добрый день расскажите подробнее",
    ],
)
def test_is_short_greeting_response_rejects_questions_and_other_phrases(
    text: str | None,
) -> None:
    assert is_short_greeting_response(text) is False


@pytest.mark.asyncio
async def test_default_initial_greeting_uses_prerecorded_audio(tmp_path) -> None:
    audio_path = tmp_path / "1.wav"
    audio_path.write_bytes(b"wav")
    cache = _VoiceAudioCache(tmp_path / "cached.wav")

    greeting, resolved_audio_path = await resolve_initial_greeting_audio(
        voice_audio_cache=cache,
        client_greeting=None,
        default_greeting="Алло, здравствуйте.",
        prerecorded_path=audio_path,
    )

    assert greeting == "Алло, здравствуйте."
    assert resolved_audio_path == audio_path
    assert cache.calls == []


@pytest.mark.asyncio
async def test_client_initial_greeting_uses_voice_cache(tmp_path) -> None:
    cached_path = tmp_path / "client.wav"
    cache = _VoiceAudioCache(cached_path)

    greeting, resolved_audio_path = await resolve_initial_greeting_audio(
        voice_audio_cache=cache,
        client_greeting="Здравствуйте, это компания X.",
        default_greeting="Алло, здравствуйте.",
        prerecorded_path=tmp_path / "1.wav",
    )

    assert greeting == "Здравствуйте, это компания X."
    assert resolved_audio_path == cached_path
    assert cache.calls == [
        {
            "kind": "initial_greeting",
            "text": "Здравствуйте, это компания X.",
            "legacy_path": None,
        }
    ]


@pytest.mark.asyncio
async def test_short_greeting_uses_prerecorded_audio(tmp_path) -> None:
    audio_path = tmp_path / "2.wav"
    audio_path.write_bytes(b"wav")
    cache = _VoiceAudioCache(tmp_path / "cached.wav")

    resolved_audio_path = await resolve_short_greeting_audio_path(
        voice_audio_cache=cache,
        phrase="Да, слушаю.",
        prerecorded_path=audio_path,
    )

    assert resolved_audio_path == audio_path
    assert cache.calls == []


@pytest.mark.parametrize("text", ["Роман.", "  подскажите адрес  "])
def test_response_delay_marks_final_non_empty_transcript_as_candidate(
    text: str,
) -> None:
    assert is_response_delay_candidate_transcript(text, is_final=True) is True


@pytest.mark.parametrize(
    ("text", "is_final"),
    [
        ("Роман.", False),
        ("", True),
        ("   ", True),
        (None, True),
    ],
)
def test_response_delay_ignores_non_final_or_empty_transcript(
    text: str | None,
    is_final: bool,
) -> None:
    assert is_response_delay_candidate_transcript(text, is_final=is_final) is False


@pytest.mark.parametrize(
    (
        "has_final_transcript",
        "user_stopped_speaking",
        "already_started",
        "expected",
    ),
    [
        (True, True, False, True),
        (True, False, False, False),
        (False, True, False, False),
        (True, True, True, False),
    ],
)
def test_response_delay_starts_only_after_vad_end(
    has_final_transcript: bool,
    user_stopped_speaking: bool,
    already_started: bool,
    expected: bool,
) -> None:
    assert (
        should_start_response_delay_after_vad(
            has_final_transcript=has_final_transcript,
            user_stopped_speaking=user_stopped_speaking,
            already_started=already_started,
        )
        is expected
    )


def test_extract_sip_call_numbers_prefers_mapped_x_did_attribute() -> None:
    result = extract_sip_call_numbers(
        _Participant(
            attributes={
                "jcall.did": "9605669899",
                "sip.trunkPhoneNumber": "312388",
                "sip.phoneNumber": "79990001122",
            }
        )
    )

    assert result == {
        "sip_trunk_number": "9605669899",
        "gateway_number": "9605669899",
        "sip_client_number": "79990001122",
    }


def test_extract_sip_call_numbers_adds_gateway_number_from_x_did() -> None:
    result = extract_sip_call_numbers(
        _Participant(
            attributes={
                "sip.h.X-DID": "9605669899",
                "sip.trunkPhoneNumber": "312388",
                "sip.phoneNumber": "79990001122",
            }
        )
    )

    assert result == {
        "sip_trunk_number": "9605669899",
        "gateway_number": "9605669899",
        "sip_client_number": "79990001122",
    }


def test_extract_sip_call_numbers_falls_back_to_livekit_trunk_phone_number() -> None:
    result = extract_sip_call_numbers(
        _Participant(
            attributes={
                "sip.trunkPhoneNumber": "312388",
                "sip.phoneNumber": "79990001122",
            }
        )
    )

    assert result == {
        "sip_trunk_number": "312388",
        "gateway_number": "312388",
        "sip_client_number": "79990001122",
    }
