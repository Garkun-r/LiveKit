from session_export import _directus_session_payload


def test_service_phrase_is_included_in_chat_history() -> None:
    payload = {
        "room_name": "room_1",
        "close": {},
        "sip": {},
        "transcript_items": [
            {
                "type": "service_phrase",
                "role": "assistant",
                "text": "Здравствуйте.",
            },
            {
                "type": "user_input_transcribed",
                "transcript": "Алло.",
                "is_final": True,
            },
        ],
    }

    body = _directus_session_payload(payload)

    assert body["chat_history"].splitlines()[0] == "assistant: Здравствуйте."

