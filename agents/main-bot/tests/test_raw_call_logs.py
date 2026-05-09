from __future__ import annotations

import logging

import pytest

from raw_call_logs import RawCallLogSink


@pytest.mark.asyncio
async def test_flush_once_stops_after_failed_batch(monkeypatch):
    sink = RawCallLogSink(
        room_name="room-1",
        directus_url="https://directus.example",
        directus_token="token",
    )
    sink.capture(
        logging.LogRecord(
            name="agent",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg="first",
            args=(),
            exc_info=None,
        )
    )
    sink.capture(
        logging.LogRecord(
            name="agent",
            level=logging.INFO,
            pathname=__file__,
            lineno=11,
            msg="second",
            args=(),
            exc_info=None,
        )
    )

    calls = 0

    async def fail_send(rows):
        nonlocal calls
        calls += 1
        sink._pending = rows + sink._pending
        return False

    monkeypatch.setattr(sink, "_send_rows", fail_send)

    await sink.flush_once()

    assert calls == 1
    assert len(sink._pending) == 2
