"""Parser for hidden robot action tags emitted by the LLM.

Supported action tags:
- [STATUS: END]: speak cleaned text, then end the call.
- [STATUS: SPAM]: speak cleaned text, then end the call.
- [STATUS: SMS_LINK]: speak cleaned text, then run the SMS link placeholder skill.
- [TRANSFER: ID]: speak cleaned text, then record a transfer placeholder event.
- [GEO_SEARCH: city, object/street]: speak cleaned text, then record a geo placeholder event.

All square-bracketed segments are removed before TTS and client transcription.
The first supported action tag wins. If the cleaned text before the first
supported action tag ends with "?", all action tags in the answer are ignored.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import dataclass
from typing import Any

_BRACKETED_RE = re.compile(r"\[[^\[\]]*\]")
_STATUS_RE = re.compile(r"^STATUS\s*:\s*(?P<status>[A-Z_]+)\s*$", re.IGNORECASE)
_TRANSFER_RE = re.compile(r"^TRANSFER\s*:\s*(?P<target>.+)$", re.IGNORECASE)
_GEO_SEARCH_RE = re.compile(r"^GEO_SEARCH\s*:\s*(?P<query>.+)$", re.IGNORECASE)
_SUPPORTED_STATUSES = {"END", "SPAM", "SMS_LINK"}


@dataclass(frozen=True)
class RobotTag:
    raw: str
    kind: str
    value: str
    action: str
    arguments: dict[str, str]
    start: int
    end: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw": self.raw,
            "kind": self.kind,
            "value": self.value,
            "action": self.action,
            "arguments": dict(self.arguments),
            "start": self.start,
            "end": self.end,
        }


@dataclass(frozen=True)
class IgnoredRobotTag:
    raw: str
    reason: str
    start: int
    end: int
    parsed: RobotTag | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "raw": self.raw,
            "reason": self.reason,
            "start": self.start,
            "end": self.end,
        }
        if self.parsed is not None:
            payload["parsed"] = self.parsed.to_dict()
        return payload


@dataclass(frozen=True)
class ParsedRobotTags:
    raw_text: str
    clean_text: str
    selected: RobotTag | None
    ignored: tuple[IgnoredRobotTag, ...]
    has_bracketed_segments: bool

    @property
    def has_action_or_tags(self) -> bool:
        return self.selected is not None or bool(self.ignored)

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_text": self.raw_text,
            "clean_text": self.clean_text,
            "selected": self.selected.to_dict() if self.selected else None,
            "ignored": [tag.to_dict() for tag in self.ignored],
            "has_bracketed_segments": self.has_bracketed_segments,
        }


def strip_bracketed_segments(text: str) -> str:
    """Remove all square-bracketed segments without leaving tag-only spacing."""
    output: list[str] = []
    pending_ws: list[str] = []
    in_brackets = False

    for char in text:
        if in_brackets:
            if char == "]":
                in_brackets = False
            continue

        if char == "[":
            pending_ws.clear()
            in_brackets = True
            continue

        if char.isspace():
            pending_ws.append(char)
            continue

        if pending_ws:
            output.extend(pending_ws)
            pending_ws.clear()
        output.append(char)

    if not in_brackets and pending_ws:
        output.extend(pending_ws)

    return "".join(output).strip()


async def sanitize_tagged_text_stream(
    text: AsyncIterable[str],
) -> AsyncIterator[str]:
    """Streaming variant of strip_bracketed_segments for TTS/transcriptions."""
    pending_ws: list[str] = []
    in_brackets = False

    async for chunk in text:
        output: list[str] = []
        for char in chunk:
            if in_brackets:
                if char == "]":
                    in_brackets = False
                continue

            if char == "[":
                pending_ws.clear()
                in_brackets = True
                continue

            if char.isspace():
                pending_ws.append(char)
                continue

            if pending_ws:
                output.extend(pending_ws)
                pending_ws.clear()
            output.append(char)

        if output:
            yield "".join(output)

    if not in_brackets and pending_ws:
        yield "".join(pending_ws)


def parse_robot_tags(raw_text: str) -> ParsedRobotTags:
    clean_text = strip_bracketed_segments(raw_text)
    ignored: list[IgnoredRobotTag] = []
    selected: RobotTag | None = None
    question_blocks_actions = False

    matches = list(_BRACKETED_RE.finditer(raw_text))
    for match in matches:
        raw = match.group(0)
        parsed = _parse_action_tag(raw, match.start(), match.end())
        if parsed is None:
            ignored.append(
                IgnoredRobotTag(
                    raw=raw,
                    reason="unsupported_or_non_action_tag",
                    start=match.start(),
                    end=match.end(),
                )
            )
            continue

        if selected is not None:
            ignored.append(
                IgnoredRobotTag(
                    raw=raw,
                    reason="additional_action_tag",
                    start=match.start(),
                    end=match.end(),
                    parsed=parsed,
                )
            )
            continue

        clean_before_tag = strip_bracketed_segments(raw_text[: match.start()]).rstrip()
        if clean_before_tag.endswith("?"):
            question_blocks_actions = True
            ignored.append(
                IgnoredRobotTag(
                    raw=raw,
                    reason="question_before_tag",
                    start=match.start(),
                    end=match.end(),
                    parsed=parsed,
                )
            )
            continue

        if question_blocks_actions:
            ignored.append(
                IgnoredRobotTag(
                    raw=raw,
                    reason="question_before_tag",
                    start=match.start(),
                    end=match.end(),
                    parsed=parsed,
                )
            )
            continue

        selected = parsed

    return ParsedRobotTags(
        raw_text=raw_text,
        clean_text=clean_text,
        selected=selected,
        ignored=tuple(ignored),
        has_bracketed_segments=bool(matches),
    )


def _parse_action_tag(raw: str, start: int, end: int) -> RobotTag | None:
    body = raw[1:-1].strip()

    status_match = _STATUS_RE.fullmatch(body)
    if status_match:
        status = status_match.group("status").upper()
        if status not in _SUPPORTED_STATUSES:
            return None
        return RobotTag(
            raw=raw,
            kind="STATUS",
            value=status,
            action=f"status_{status.lower()}",
            arguments={"status": status},
            start=start,
            end=end,
        )

    transfer_match = _TRANSFER_RE.fullmatch(body)
    if transfer_match:
        target = transfer_match.group("target").strip()
        if not target:
            return None
        return RobotTag(
            raw=raw,
            kind="TRANSFER",
            value=target,
            action="transfer",
            arguments={"target": target},
            start=start,
            end=end,
        )

    geo_match = _GEO_SEARCH_RE.fullmatch(body)
    if geo_match:
        query = geo_match.group("query").strip()
        if not query:
            return None
        city, _, place = query.partition(",")
        arguments = {"query": query, "city": city.strip()}
        if place.strip():
            arguments["place"] = place.strip()
        return RobotTag(
            raw=raw,
            kind="GEO_SEARCH",
            value=query,
            action="geo_search",
            arguments=arguments,
            start=start,
            end=end,
        )

    return None
