import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import asyncpg
import httpx

from config import (
    INCIDENT_DB_TIMEOUT_SEC,
    INCIDENT_DIRECTUS_TOKEN,
    INCIDENT_DIRECTUS_URL,
    INCIDENT_ENVIRONMENT,
    INCIDENT_LOG_ENABLED,
    INCIDENT_LOG_TRANSPORT,
    INCIDENT_POSTGRES_DSN,
    POSTGRES_DSN,
)

logger = logging.getLogger("incident_logger")

_pool: asyncpg.Pool | None = None
_pool_dsn: str | None = None

_INSERT_SQL = """
insert into robot_incidents (
    created_at,
    environment,
    source,
    severity,
    incident_type,
    status,
    caller_phone,
    did,
    trace_id,
    room_name,
    job_id,
    sip_call_id,
    component,
    provider,
    model,
    latency_ms,
    error_type,
    description,
    fingerprint,
    payload
) values (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
    $11, $12, $13, $14, $15, $16, $17, $18, $19, $20::jsonb
)
"""

_SECRET_PATTERNS = (
    (
        re.compile(r"(?i)(authorization\s*[:=]\s*)(bearer|basic)\s+[^\s,;]+"),
        r"\1\2 [redacted]",
    ),
    (
        re.compile(r"(?i)(api[_-]?key|x-api-key|token|secret)([=:\s]+)([^\s,;]+)"),
        r"\1\2[redacted]",
    ),
    (re.compile(r"(?i)(key=)([^&\s]+)"), r"\1[redacted]"),
)
_SECRET_KEY_RE = re.compile(r"(?i)(api[_-]?key|authorization|token|secret)")


def _has_value(value: Any) -> bool:
    return value is not None and value != ""


@dataclass(frozen=True)
class IncidentRecord:
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    environment: str = INCIDENT_ENVIRONMENT
    source: str = "livekit_agent"
    severity: str = "warning"
    incident_type: str = "unknown"
    status: str = "open"
    caller_phone: str | None = None
    did: str | None = None
    trace_id: str | None = None
    room_name: str | None = None
    job_id: str | None = None
    sip_call_id: str | None = None
    component: str | None = None
    provider: str | None = None
    model: str | None = None
    latency_ms: int | None = None
    error_type: str | None = None
    description: str = ""
    fingerprint: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


def _redact(text: str) -> str:
    redacted = text
    for pattern, replacement in _SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def safe_json(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return _redact(value) if isinstance(value, str) else value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {
            str(key): "[redacted]"
            if _SECRET_KEY_RE.search(str(key))
            else safe_json(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [safe_json(item) for item in value]
    if hasattr(value, "model_dump"):
        try:
            return safe_json(value.model_dump())
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        try:
            return {str(key): safe_json(item) for key, item in vars(value).items()}
        except Exception:
            pass
    return _redact(str(value))


def classify_error(error: BaseException | Any) -> str:
    if error is None:
        return "unknown"

    status_code = getattr(error, "status_code", None)
    response = getattr(error, "response", None)
    if status_code is None and response is not None:
        status_code = getattr(response, "status_code", None)

    text = f"{type(error).__name__} {error}".lower()
    if status_code in {401, 403} or any(
        marker in text
        for marker in (
            "unauthorized",
            "unauthenticated",
            "forbidden",
            "invalid api key",
            "api key",
            "permission denied",
        )
    ):
        return "auth_or_key"
    if status_code == 402 or any(
        marker in text
        for marker in (
            "billing",
            "payment",
            "insufficient",
            "balance",
            "credits",
            "quota exceeded",
            "quota_exceeded",
        )
    ):
        return "quota_or_billing"
    if status_code == 429 or "rate limit" in text or "too many requests" in text:
        return "rate_limit"
    if isinstance(error, TimeoutError) or "timeout" in text or "timed out" in text:
        return "timeout"
    if isinstance(status_code, int) and 500 <= status_code <= 599:
        return "provider_5xx"
    if any(
        marker in text
        for marker in (
            "connection",
            "connecterror",
            "network",
            "dns",
            "socket",
            "websocket",
            "ssl",
        )
    ):
        return "network"
    return "unknown"


def error_payload(error: BaseException | Any) -> dict[str, Any]:
    if error is None:
        return {}
    response = getattr(error, "response", None)
    return {
        "error_class": type(error).__name__,
        "message": _redact(str(error)),
        "status_code": getattr(error, "status_code", None)
        or getattr(response, "status_code", None),
        "category": classify_error(error),
    }


def component_identity(component: Any) -> tuple[str | None, str | None]:
    if component is None:
        return None, None
    provider = getattr(component, "provider", None)
    model = getattr(component, "model", None)
    return (
        str(provider) if provider is not None else None,
        str(model) if model is not None else None,
    )


async def get_incident_pool() -> asyncpg.Pool:
    global _pool, _pool_dsn

    dsn = INCIDENT_POSTGRES_DSN or POSTGRES_DSN
    if not dsn:
        raise RuntimeError("INCIDENT_POSTGRES_DSN or POSTGRES_DSN is not set")

    if _pool is None or _pool_dsn != dsn:
        _pool = await asyncpg.create_pool(
            dsn=dsn,
            min_size=1,
            max_size=2,
            command_timeout=INCIDENT_DB_TIMEOUT_SEC,
        )
        _pool_dsn = dsn
    return _pool


def _coerce_int(value: int | float | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    return round(float(value))


def _fingerprint(record: IncidentRecord) -> str:
    raw = "|".join(
        str(part or "")
        for part in (
            record.environment,
            record.source,
            record.incident_type,
            record.component,
            record.provider,
            record.model,
            record.error_type,
        )
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def record_to_payload(record: IncidentRecord) -> dict[str, Any]:
    return {
        "created_at": record.created_at.isoformat(),
        "environment": record.environment,
        "source": record.source,
        "severity": record.severity,
        "incident_type": record.incident_type,
        "status": record.status,
        "caller_phone": record.caller_phone,
        "did": record.did,
        "trace_id": record.trace_id,
        "room_name": record.room_name,
        "job_id": record.job_id,
        "sip_call_id": record.sip_call_id,
        "component": record.component,
        "provider": record.provider,
        "model": record.model,
        "latency_ms": record.latency_ms,
        "error_type": record.error_type,
        "description": record.description or record.incident_type,
        "fingerprint": record.fingerprint or _fingerprint(record),
        "payload": safe_json(record.payload),
    }


async def insert_incident_via_directus(
    record: IncidentRecord,
    *,
    directus_url: str = INCIDENT_DIRECTUS_URL,
    directus_token: str = INCIDENT_DIRECTUS_TOKEN,
    timeout_sec: float = INCIDENT_DB_TIMEOUT_SEC,
) -> None:
    if not directus_url:
        raise RuntimeError("INCIDENT_DIRECTUS_URL is not set")
    if not directus_token:
        raise RuntimeError("INCIDENT_DIRECTUS_TOKEN or DIRECTUS_TOKEN is not set")

    url = f"{directus_url.rstrip('/')}/items/robot_incidents"
    headers = {
        "Authorization": f"Bearer {directus_token}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(
        timeout=timeout_sec,
        follow_redirects=True,
    ) as client:
        response = await client.post(
            url,
            params={"fields": "id"},
            json=record_to_payload(record),
            headers=headers,
        )
        response.raise_for_status()


async def insert_incident(
    record: IncidentRecord,
    *,
    pool_factory: Callable[[], Awaitable[Any]] = get_incident_pool,
) -> None:
    payload = record_to_payload(record)
    payload_json = json.dumps(payload["payload"], ensure_ascii=False)
    pool = await pool_factory()
    async with pool.acquire() as conn:
        await conn.execute(
            _INSERT_SQL,
            record.created_at,
            payload["environment"],
            payload["source"],
            payload["severity"],
            payload["incident_type"],
            payload["status"],
            payload["caller_phone"],
            payload["did"],
            payload["trace_id"],
            payload["room_name"],
            payload["job_id"],
            payload["sip_call_id"],
            payload["component"],
            payload["provider"],
            payload["model"],
            payload["latency_ms"],
            payload["error_type"],
            payload["description"],
            payload["fingerprint"],
            payload_json,
        )


class IncidentLogger:
    def __init__(
        self,
        *,
        environment: str = INCIDENT_ENVIRONMENT,
        source: str = "livekit_agent",
        enabled: bool = INCIDENT_LOG_ENABLED,
        transport: str = INCIDENT_LOG_TRANSPORT,
        timeout_sec: float = INCIDENT_DB_TIMEOUT_SEC,
        pool_factory: Callable[[], Awaitable[Any]] = get_incident_pool,
        directus_insert: Callable[[IncidentRecord], Awaitable[Any]] | None = None,
        **context: Any,
    ) -> None:
        self._environment = environment
        self._source = source
        self._enabled = enabled
        self._transport = (transport or "directus").strip().lower()
        self._timeout_sec = max(0.1, timeout_sec)
        self._pool_factory = pool_factory
        self._directus_insert = directus_insert
        self._context: dict[str, Any] = {
            key: value for key, value in context.items() if _has_value(value)
        }
        self._pending: set[asyncio.Task] = set()

    def set_context(self, **context: Any) -> None:
        for key, value in context.items():
            if _has_value(value):
                self._context[key] = value

    async def record(
        self,
        incident_type: str,
        *,
        severity: str = "warning",
        status: str = "open",
        description: str = "",
        payload: dict[str, Any] | None = None,
        source: str | None = None,
        component: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        latency_ms: int | float | None = None,
        error_type: str | None = None,
        fingerprint: str | None = None,
        **context: Any,
    ) -> None:
        if not self._enabled:
            return

        merged_context = {
            **self._context,
            **{key: value for key, value in context.items() if _has_value(value)},
        }
        record = IncidentRecord(
            environment=self._environment,
            source=source or self._source,
            severity=severity,
            incident_type=incident_type,
            status=status,
            caller_phone=merged_context.get("caller_phone"),
            did=merged_context.get("did"),
            trace_id=merged_context.get("trace_id"),
            room_name=merged_context.get("room_name"),
            job_id=merged_context.get("job_id"),
            sip_call_id=merged_context.get("sip_call_id"),
            component=component,
            provider=provider,
            model=model,
            latency_ms=_coerce_int(latency_ms),
            error_type=error_type,
            description=description,
            fingerprint=fingerprint,
            payload=payload or {},
        )

        try:
            if self._transport == "postgres":
                await asyncio.wait_for(
                    insert_incident(record, pool_factory=self._pool_factory),
                    timeout=self._timeout_sec,
                )
            elif self._transport == "off":
                return
            else:
                directus_insert = self._directus_insert or insert_incident_via_directus
                await asyncio.wait_for(
                    directus_insert(record),
                    timeout=self._timeout_sec,
                )
        except Exception as e:
            logger.warning(
                "failed to write robot incident: %s",
                e,
                extra={
                    "incident_type": incident_type,
                    "incident_transport": self._transport,
                },
            )

    def record_nowait(self, incident_type: str, **kwargs: Any) -> asyncio.Task | None:
        if not self._enabled:
            return None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return None
        task = loop.create_task(self.record(incident_type, **kwargs))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)
        return task

    async def record_exception(
        self,
        incident_type: str,
        error: BaseException | Any,
        *,
        severity: str = "error",
        description: str = "",
        payload: dict[str, Any] | None = None,
        error_type: str | None = None,
        **kwargs: Any,
    ) -> None:
        provider = kwargs.pop("provider", None)
        model = kwargs.pop("model", None)
        source_component = kwargs.pop("source_component", None)
        if source_component is not None:
            component_provider, component_model = component_identity(source_component)
            provider = provider or component_provider
            model = model or component_model

        merged_payload = {
            **(payload or {}),
            "error": error_payload(error),
            "error_category": classify_error(error),
        }
        await self.record(
            incident_type,
            severity=severity,
            description=description or str(error),
            payload=merged_payload,
            provider=provider,
            model=model,
            error_type=error_type or type(error).__name__,
            **kwargs,
        )

    def record_exception_nowait(
        self,
        incident_type: str,
        error: BaseException | Any,
        **kwargs: Any,
    ) -> asyncio.Task | None:
        if not self._enabled:
            return None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return None
        task = loop.create_task(self.record_exception(incident_type, error, **kwargs))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)
        return task

    @asynccontextmanager
    async def observe(
        self,
        incident_type: str,
        *,
        severity: str = "error",
        description: str = "",
        payload: dict[str, Any] | None = None,
        **kwargs: Any,
    ):
        try:
            yield
        except Exception as e:
            await self.record_exception(
                incident_type,
                e,
                severity=severity,
                description=description,
                payload=payload,
                **kwargs,
            )
            raise

    async def drain(self, timeout_sec: float = 1.0) -> None:
        if not self._pending:
            return
        pending = list(self._pending)
        try:
            await asyncio.wait_for(
                asyncio.gather(*pending, return_exceptions=True),
                timeout=timeout_sec,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "incident logger drain timed out",
                extra={"pending_count": len(self._pending)},
            )
