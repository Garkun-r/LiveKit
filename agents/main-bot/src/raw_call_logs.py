from __future__ import annotations

import asyncio
import contextvars
import logging
import re
import threading
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from config import (
    DIRECTUS_REQUEST_TIMEOUT_SEC,
    DIRECTUS_TOKEN,
    DIRECTUS_URL,
    RAW_CALL_LOG_BATCH_SIZE,
    RAW_CALL_LOG_ENABLED,
    RAW_CALL_LOG_FLUSH_INTERVAL_SEC,
    RAW_CALL_LOG_LEVEL,
    RAW_CALL_LOG_MAX_EXTRA_CHARS,
    RAW_CALL_LOG_MAX_MESSAGE_CHARS,
    RAW_CALL_LOG_MAX_PENDING,
)

_SECRET_PATTERNS = (
    (
        re.compile(r"(?i)(authorization\s*[:=]\s*)(bearer|basic)\s+[^\s,;]+"),
        r"\1\2 [redacted]",
    ),
    (
        re.compile(r"(?i)(api[_-]?key|x-api-key|token|secret|password)([=:\s]+)([^\s,;]+)"),
        r"\1\2[redacted]",
    ),
    (re.compile(r"(?i)(key=)([^&\s]+)"), r"\1[redacted]"),
)
_SECRET_KEY_RE = re.compile(r"(?i)(api[_-]?key|authorization|token|secret|password)")
_STANDARD_LOG_RECORD_KEYS = set(
    logging.LogRecord(
        name="",
        level=0,
        pathname="",
        lineno=0,
        msg="",
        args=(),
        exc_info=None,
    ).__dict__
)

_current_sink: contextvars.ContextVar[RawCallLogSink | None] = contextvars.ContextVar(
    "raw_call_log_sink",
    default=None,
)
_flushing_logs: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "raw_call_log_flushing",
    default=False,
)
_handler_installed = False
_handler_lock = threading.Lock()


def _redact_text(value: str) -> str:
    redacted = value
    for pattern, replacement in _SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def _truncate(value: str, limit: int) -> str:
    if limit <= 0 or len(value) <= limit:
        return value
    return value[:limit] + f"... [truncated {len(value) - limit} chars]"


def _safe_json(value: Any, *, depth: int = 0) -> Any:
    if depth > 5:
        return "[max_depth]"
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, str):
        return _truncate(_redact_text(value), RAW_CALL_LOG_MAX_EXTRA_CHARS)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {
            str(key): "[redacted]"
            if _SECRET_KEY_RE.search(str(key))
            else _safe_json(item, depth=depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [_safe_json(item, depth=depth + 1) for item in value]
    if hasattr(value, "model_dump"):
        try:
            return _safe_json(value.model_dump(), depth=depth + 1)
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        try:
            return _safe_json(vars(value), depth=depth + 1)
        except Exception:
            pass
    return _truncate(_redact_text(str(value)), RAW_CALL_LOG_MAX_EXTRA_CHARS)


def _record_extras(record: logging.LogRecord) -> dict[str, Any]:
    extras = {}
    for key, value in record.__dict__.items():
        if key in _STANDARD_LOG_RECORD_KEYS or key.startswith("_"):
            continue
        if _SECRET_KEY_RE.search(str(key)):
            extras[str(key)] = "[redacted]"
            continue
        extras[str(key)] = _safe_json(value)
    return extras


def _task_name() -> str | None:
    try:
        task = asyncio.current_task()
    except RuntimeError:
        return None
    return task.get_name() if task else None


class RawCallLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        if _flushing_logs.get(False):
            return
        sink = _current_sink.get(None)
        if sink is None:
            return
        sink.capture(record)


def install_raw_call_log_handler() -> None:
    global _handler_installed
    if _handler_installed:
        return
    with _handler_lock:
        if _handler_installed:
            return
        handler = RawCallLogHandler(level=logging.NOTSET)
        logging.getLogger().addHandler(handler)
        _handler_installed = True


def bind_raw_call_log_sink(
    sink: RawCallLogSink,
) -> contextvars.Token[RawCallLogSink | None]:
    install_raw_call_log_handler()
    return _current_sink.set(sink)


def reset_raw_call_log_sink(token: contextvars.Token[RawCallLogSink | None]) -> None:
    _current_sink.reset(token)


@dataclass
class RawCallLogSink:
    room_name: str
    session_id: str | None = None
    agent_name: str | None = None
    runtime_profile: str | None = None
    job_id: str | None = None
    trace_id: str | None = None
    sip_call_id: str | None = None
    directus_url: str = DIRECTUS_URL
    directus_token: str = DIRECTUS_TOKEN
    enabled: bool = RAW_CALL_LOG_ENABLED
    min_level: int = field(
        default_factory=lambda: getattr(
            logging,
            str(RAW_CALL_LOG_LEVEL or "INFO").upper(),
            logging.INFO,
        )
    )
    _pending: list[dict[str, Any]] = field(default_factory=list, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _sequence: int = field(default=0, init=False)
    _flush_task: asyncio.Task | None = field(default=None, init=False)
    _closed: bool = field(default=False, init=False)
    _dropped: int = field(default=0, init=False)

    async def start(self) -> None:
        if not self.enabled:
            return
        if not self.directus_url or not self.directus_token:
            return
        if self._flush_task is None:
            self._flush_task = asyncio.create_task(
                self._flush_loop(),
                name=f"raw_call_log_flush:{self.room_name}",
            )

    def capture(self, record: logging.LogRecord) -> None:
        if not self.enabled or self._closed or record.levelno < self.min_level:
            return
        row = self._row_from_record(record)
        with self._lock:
            if len(self._pending) >= RAW_CALL_LOG_MAX_PENDING:
                self._pending.pop(0)
                self._dropped += 1
            self._pending.append(row)

    async def close(self, timeout_sec: float = 3.0) -> None:
        self._closed = True
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            with suppress(BaseException):
                await self._flush_task
        if self._dropped:
            self.capture_manual(
                level="warning",
                logger_name="raw_call_logs",
                message=f"raw call log buffer dropped {self._dropped} records",
            )
        try:
            await asyncio.wait_for(self.flush_once(), timeout=timeout_sec)
        except Exception as exc:
            print(f"[raw_call_logs] final flush failed: {exc}", flush=True)

    def capture_manual(
        self,
        *,
        level: str,
        logger_name: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        level_number = getattr(logging, level.upper(), logging.INFO)
        now = datetime.now(timezone.utc)
        with self._lock:
            self._sequence += 1
            self._pending.append(
                {
                    "event_time": now.isoformat(),
                    "source": "livekit_agent",
                    "agent_name": self.agent_name,
                    "runtime_profile": self.runtime_profile,
                    "room_name": self.room_name,
                    "session_id": self.session_id or self.room_name,
                    "job_id": self.job_id,
                    "trace_id": self.trace_id,
                    "sip_call_id": self.sip_call_id,
                    "sequence": self._sequence,
                    "level": logging.getLevelName(level_number),
                    "logger_name": logger_name,
                    "message": _truncate(_redact_text(message), RAW_CALL_LOG_MAX_MESSAGE_CHARS),
                    "raw_text": f"{now.isoformat()} {level.upper()} {logger_name}: {message}",
                    "payload": _safe_json(payload or {}),
                }
            )

    async def _flush_loop(self) -> None:
        while not self._closed:
            await asyncio.sleep(RAW_CALL_LOG_FLUSH_INTERVAL_SEC)
            await self.flush_once()

    async def flush_once(self) -> None:
        rows = self._drain(RAW_CALL_LOG_BATCH_SIZE)
        while rows:
            if not await self._send_rows(rows):
                break
            rows = self._drain(RAW_CALL_LOG_BATCH_SIZE)

    def _drain(self, limit: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._pending[:limit]
            del self._pending[:limit]
            return rows

    async def _send_rows(self, rows: list[dict[str, Any]]) -> bool:
        if not rows or not self.directus_url or not self.directus_token:
            return True
        token = _flushing_logs.set(True)
        try:
            headers = {
                "Authorization": f"Bearer {self.directus_token}",
                "Content-Type": "application/json",
            }
            timeout = max(float(DIRECTUS_REQUEST_TIMEOUT_SEC or 2.0), 5.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{self.directus_url.rstrip('/')}/items/robot_call_raw_logs",
                    json=rows if len(rows) > 1 else rows[0],
                    headers=headers,
                )
                if response.status_code >= 400 and len(rows) > 1:
                    for row in rows:
                        single = await client.post(
                            f"{self.directus_url.rstrip('/')}/items/robot_call_raw_logs",
                            json=row,
                            headers=headers,
                        )
                        single.raise_for_status()
                    return True
                response.raise_for_status()
            return True
        except Exception as exc:
            with self._lock:
                self._pending = rows + self._pending
            print(f"[raw_call_logs] flush failed: {exc}", flush=True)
            return False
        finally:
            _flushing_logs.reset(token)

    def _row_from_record(self, record: logging.LogRecord) -> dict[str, Any]:
        created_at = datetime.fromtimestamp(record.created, timezone.utc)
        message = _truncate(
            _redact_text(record.getMessage()),
            RAW_CALL_LOG_MAX_MESSAGE_CHARS,
        )
        exc_text = ""
        if record.exc_info:
            exc_text = logging.Formatter().formatException(record.exc_info)
            exc_text = _truncate(_redact_text(exc_text), RAW_CALL_LOG_MAX_EXTRA_CHARS)
        raw_text = f"{created_at.isoformat()} {record.levelname} {record.name}: {message}"
        if exc_text:
            raw_text = f"{raw_text}\n{exc_text}"

        with self._lock:
            self._sequence += 1
            sequence = self._sequence

        return {
            "event_time": created_at.isoformat(),
            "source": "livekit_agent",
            "agent_name": self.agent_name,
            "runtime_profile": self.runtime_profile,
            "room_name": self.room_name,
            "session_id": self.session_id or self.room_name,
            "job_id": self.job_id,
            "trace_id": self.trace_id,
            "sip_call_id": self.sip_call_id,
            "sequence": sequence,
            "level": record.levelname,
            "logger_name": record.name,
            "message": message,
            "raw_text": raw_text,
            "module": record.module,
            "function_name": record.funcName,
            "line_no": record.lineno,
            "task_name": _task_name(),
            "payload": {
                "pathname": record.pathname,
                "process": record.process,
                "thread": record.threadName,
                "extras": _record_extras(record),
                "exception": exc_text,
            },
        }
