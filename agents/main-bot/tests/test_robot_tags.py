import pytest

from robot_tags import parse_robot_tags, sanitize_tagged_text_stream


async def _collect(chunks: list[str]) -> str:
    async def source():
        for chunk in chunks:
            yield chunk

    parts = []
    async for chunk in sanitize_tagged_text_stream(source()):
        parts.append(chunk)
    return "".join(parts)


def test_parse_status_end_selects_action_and_cleans_text() -> None:
    parsed = parse_robot_tags("Хорошо, до свидания. [STATUS: END]")

    assert parsed.clean_text == "Хорошо, до свидания."
    assert parsed.selected is not None
    assert parsed.selected.action == "status_end"
    assert parsed.selected.arguments == {"status": "END"}
    assert parsed.ignored == ()


def test_parse_supported_tags() -> None:
    cases = [
        ("Сейчас отправлю ссылку. [STATUS: SMS_LINK]", "status_sms_link"),
        ("Хорошо, перевожу. [TRANSFER: TR5]", "transfer"),
        (
            "[GEO_SEARCH: Калининград, улица Чайковского]",
            "geo_search",
        ),
        ("Извините, всего доброго. [STATUS: SPAM]", "status_spam"),
    ]

    for raw_text, action in cases:
        parsed = parse_robot_tags(raw_text)
        assert parsed.selected is not None
        assert parsed.selected.action == action


def test_first_valid_action_tag_wins() -> None:
    parsed = parse_robot_tags(
        "Хорошо. [STATUS: END] [TRANSFER: TR5] [STATUS: SMS_LINK]"
    )

    assert parsed.selected is not None
    assert parsed.selected.action == "status_end"
    assert [tag.reason for tag in parsed.ignored] == [
        "additional_action_tag",
        "additional_action_tag",
    ]


def test_question_before_tag_ignores_action() -> None:
    parsed = parse_robot_tags("Когда вам удобно? [STATUS: END]")

    assert parsed.clean_text == "Когда вам удобно?"
    assert parsed.selected is None
    assert len(parsed.ignored) == 1
    assert parsed.ignored[0].reason == "question_before_tag"


def test_unknown_tags_are_hidden_but_not_selected() -> None:
    parsed = parse_robot_tags("Заявка принята. [STATUS: LEAD] [вздыхает]")

    assert parsed.clean_text == "Заявка принята."
    assert parsed.selected is None
    assert [tag.reason for tag in parsed.ignored] == [
        "unsupported_or_non_action_tag",
        "unsupported_or_non_action_tag",
    ]


@pytest.mark.asyncio
async def test_sanitize_stream_handles_split_tags() -> None:
    cleaned = await _collect(["Хорошо, ", "до", " свидания. [STA", "TUS: END]"])

    assert cleaned == "Хорошо, до свидания."


@pytest.mark.asyncio
async def test_sanitize_stream_hides_all_square_segments() -> None:
    cleaned = await _collect(
        ["Кхм [вздыхает], перевожу [TRANSFER: TR5] сейчас."]
    )

    assert cleaned == "Кхм, перевожу сейчас."
