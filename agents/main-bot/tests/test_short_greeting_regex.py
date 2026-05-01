import pytest
from livekit import rtc

from agent import extract_sip_call_numbers, is_short_greeting_response


class _Participant:
    def __init__(self, *, attributes, kind=rtc.ParticipantKind.PARTICIPANT_KIND_SIP):
        self.attributes = attributes
        self.kind = kind


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
        "здравствуйте подскажите стоимость",
        "добрый день расскажите подробнее",
    ],
)
def test_is_short_greeting_response_rejects_questions_and_other_phrases(
    text: str | None,
) -> None:
    assert is_short_greeting_response(text) is False


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
