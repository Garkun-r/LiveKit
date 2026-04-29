from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from robot_tags import ParsedRobotTags, RobotTag

logger = logging.getLogger("robot_skills")


@dataclass(frozen=True)
class RobotSkillContext:
    agent_name: str
    room_name: str
    participant_identity: str | None
    sip_call_numbers: dict[str, str | None]

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "room_name": self.room_name,
            "participant_identity": self.participant_identity,
            "sip_call_numbers": dict(self.sip_call_numbers),
        }


@dataclass(frozen=True)
class RobotSkillResult:
    status: str
    detail: str
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "detail": self.detail,
            "data": dict(self.data),
        }


class RobotSkillRunner:
    def __init__(
        self,
        *,
        context: RobotSkillContext,
        request_end_call: Callable[[str], Awaitable[str]],
        record_event: Callable[[dict[str, Any]], None],
    ) -> None:
        self._context = context
        self._request_end_call = request_end_call
        self._record_event = record_event

    async def run(
        self,
        parsed: ParsedRobotTags,
        *,
        speech_handle_id: str | None,
        interrupted: bool,
    ) -> RobotSkillResult:
        try:
            if parsed.selected is None:
                result = RobotSkillResult(
                    status="ignored",
                    detail="no supported action selected",
                    data={},
                )
            else:
                result = await self._run_selected(parsed.selected)
        except Exception as e:
            logger.exception("robot skill failed: %s", e)
            result = RobotSkillResult(
                status="error",
                detail=str(e),
                data={},
            )

        self._record_event(
            {
                "type": "robot_tag_event",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "speech_handle_id": speech_handle_id,
                "interrupted": interrupted,
                "context": self._context.to_dict(),
                "raw_text": parsed.raw_text,
                "clean_text": parsed.clean_text,
                "selected": parsed.selected.to_dict() if parsed.selected else None,
                "ignored": [tag.to_dict() for tag in parsed.ignored],
                "skill_result": result.to_dict(),
            }
        )
        return result

    async def _run_selected(self, tag: RobotTag) -> RobotSkillResult:
        if tag.action in {"status_end", "status_spam"}:
            reason = tag.action
            scheduler_result = await self._request_end_call(reason)
            return RobotSkillResult(
                status="scheduled",
                detail="call end requested",
                data={
                    "reason": reason,
                    "scheduler_result": scheduler_result,
                },
            )

        if tag.action == "status_sms_link":
            return RobotSkillResult(
                status="placeholder",
                detail="SMS link skill is not implemented yet",
                data={
                    "caller_phone": self._context.sip_call_numbers.get(
                        "sip_client_number"
                    ),
                    "message_template": None,
                },
            )

        if tag.action == "transfer":
            return RobotSkillResult(
                status="placeholder",
                detail="transfer skill is not implemented yet",
                data={
                    "transfer_to": tag.arguments.get("target"),
                    "participant_identity": self._context.participant_identity,
                    "room_name": self._context.room_name,
                    "caller_phone": self._context.sip_call_numbers.get(
                        "sip_client_number"
                    ),
                },
            )

        if tag.action == "geo_search":
            return RobotSkillResult(
                status="placeholder",
                detail="geo search skill is not implemented yet",
                data={
                    "query": tag.arguments.get("query"),
                    "city": tag.arguments.get("city"),
                    "place": tag.arguments.get("place"),
                },
            )

        return RobotSkillResult(
            status="ignored",
            detail=f"unsupported action: {tag.action}",
            data={},
        )
