import json

import pytest

from incident_logger import (
    IncidentLogger,
    IncidentRecord,
    classify_error,
    insert_incident,
    record_to_payload,
    safe_json,
)


class _AcquireContext:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _AcquireContext(self.conn)


class _Conn:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    async def execute(self, *args):
        self.calls.append(args)
        if self.error:
            raise self.error
        return "INSERT 0 1"


class _HTTPError(Exception):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


@pytest.mark.parametrize(
    ("error", "category"),
    [
        (_HTTPError("invalid api key", 401), "auth_or_key"),
        (_HTTPError("quota exceeded", 402), "quota_or_billing"),
        (_HTTPError("too many requests", 429), "rate_limit"),
        (TimeoutError("timed out"), "timeout"),
        (_HTTPError("server exploded", 503), "provider_5xx"),
        (ConnectionError("connection reset"), "network"),
        (RuntimeError("unexpected"), "unknown"),
    ],
)
def test_classify_error(error: Exception, category: str) -> None:
    assert classify_error(error) == category


def test_safe_json_redacts_obvious_secrets() -> None:
    value = safe_json(
        {
            "message": "authorization: Bearer abc123",
            "url": "https://example.test?key=secret-value",
        }
    )

    assert value["message"] == "authorization: Bearer [redacted]"
    assert value["url"] == "https://example.test?key=[redacted]"


@pytest.mark.asyncio
async def test_insert_incident_builds_robot_incidents_row() -> None:
    conn = _Conn()

    async def pool_factory():
        return _Pool(conn)

    await insert_incident(
        IncidentRecord(
            environment="cloud",
            source="livekit_agent",
            severity="warning",
            incident_type="slow_response",
            caller_phone="79990001122",
            did="312388",
            room_name="room-1",
            component="voice_pipeline",
            latency_ms=8123,
            description="slow",
            payload={"authorization": "Bearer token"},
        ),
        pool_factory=pool_factory,
    )

    assert len(conn.calls) == 1
    _, *params = conn.calls[0]
    assert params[1] == "cloud"
    assert params[4] == "slow_response"
    assert params[6] == "79990001122"
    assert params[7] == "312388"
    assert params[9] == "room-1"
    assert params[12] == "voice_pipeline"
    assert params[15] == 8123
    assert params[17] == "slow"
    payload = json.loads(params[19])
    assert payload["authorization"] == "[redacted]"


@pytest.mark.asyncio
async def test_incident_logger_db_failure_does_not_raise() -> None:
    conn = _Conn(error=RuntimeError("database unavailable"))

    async def pool_factory():
        return _Pool(conn)

    logger = IncidentLogger(
        environment="local",
        room_name="room-1",
        transport="postgres",
        pool_factory=pool_factory,
    )

    await logger.record(
        "provider_fallback",
        component="llm",
        provider="google",
        model="gemini",
        description="fallback",
    )

    assert len(conn.calls) == 1


@pytest.mark.asyncio
async def test_record_exception_adds_error_category_and_context() -> None:
    conn = _Conn()

    async def pool_factory():
        return _Pool(conn)

    logger = IncidentLogger(
        environment="cloud",
        room_name="room-1",
        caller_phone="79990001122",
        transport="postgres",
        pool_factory=pool_factory,
    )

    await logger.record_exception(
        "n8n_export_failed",
        _HTTPError("rate limit", 429),
        component="n8n_export",
        description="n8n failed",
    )

    _, *params = conn.calls[0]
    assert params[4] == "n8n_export_failed"
    assert params[6] == "79990001122"
    assert params[12] == "n8n_export"
    assert params[16] == "_HTTPError"
    payload = json.loads(params[19])
    assert payload["error_category"] == "rate_limit"
    assert payload["error"]["status_code"] == 429


@pytest.mark.asyncio
async def test_incident_logger_directus_transport_uses_insert_callback() -> None:
    records = []

    async def directus_insert(record):
        records.append(record)

    logger = IncidentLogger(
        environment="cloud",
        room_name="room-1",
        caller_phone="79990001122",
        transport="directus",
        directus_insert=directus_insert,
    )

    await logger.record(
        "slow_response",
        component="voice_pipeline",
        latency_ms=9000,
        description="slow",
    )

    assert len(records) == 1
    payload = record_to_payload(records[0])
    assert payload["incident_type"] == "slow_response"
    assert payload["room_name"] == "room-1"
    assert payload["caller_phone"] == "79990001122"
    assert payload["latency_ms"] == 9000


@pytest.mark.asyncio
async def test_incident_logger_directus_failure_does_not_raise() -> None:
    calls = 0

    async def directus_insert(_):
        nonlocal calls
        calls += 1
        raise RuntimeError("directus unavailable")

    logger = IncidentLogger(
        environment="cloud",
        room_name="room-1",
        transport="directus",
        directus_insert=directus_insert,
    )

    await logger.record(
        "provider_fallback",
        component="llm",
        provider="google",
        model="gemini",
        description="fallback",
    )

    assert calls == 1
