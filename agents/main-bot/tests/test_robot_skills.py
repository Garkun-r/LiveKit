import pytest

from robot_skills import RobotSkillContext, RobotSkillRunner
from robot_tags import parse_robot_tags


def _context() -> RobotSkillContext:
    return RobotSkillContext(
        agent_name="test-agent",
        room_name="room",
        participant_identity="sip-user",
        sip_call_numbers={
            "sip_trunk_number": "79990000001",
            "sip_client_number": "79990000002",
        },
    )


@pytest.mark.asyncio
async def test_status_end_requests_call_close_and_records_event() -> None:
    requested_reasons: list[str] = []
    events: list[dict] = []

    async def request_end_call(reason: str) -> str:
        requested_reasons.append(reason)
        return "END_CALL_SCHEDULED"

    runner = RobotSkillRunner(
        context=_context(),
        request_end_call=request_end_call,
        record_event=events.append,
    )

    result = await runner.run(
        parse_robot_tags("До свидания. [STATUS: END]"),
        speech_handle_id="speech_1",
        interrupted=True,
    )

    assert requested_reasons == ["status_end"]
    assert result.status == "scheduled"
    assert len(events) == 1
    assert events[0]["interrupted"] is True
    assert events[0]["selected"]["action"] == "status_end"
    assert events[0]["clean_text"] == "До свидания."


@pytest.mark.asyncio
async def test_placeholder_transfer_records_context_without_external_action() -> None:
    events: list[dict] = []

    async def request_end_call(reason: str) -> str:
        raise AssertionError(reason)

    runner = RobotSkillRunner(
        context=_context(),
        request_end_call=request_end_call,
        record_event=events.append,
    )

    result = await runner.run(
        parse_robot_tags("Хорошо, перевожу. [TRANSFER: TR5]"),
        speech_handle_id="speech_2",
        interrupted=False,
    )

    assert result.status == "placeholder"
    assert result.data["transfer_to"] == "TR5"
    assert result.data["participant_identity"] == "sip-user"
    assert events[0]["skill_result"]["status"] == "placeholder"
