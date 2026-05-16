import asyncio
import json
from collections import deque
from typing import Any

import pytest
from livekit.agents import (
    APIConnectionError,
    APIStatusError,
    utils,
)
from livekit.agents import (
    tts as lk_tts,
)
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS
from websockets.protocol import State

import agent
from minimax_tts import PreparedMiniMaxTTS


class _FakeWebSocket:
    def __init__(
        self,
        events: list[dict[str, Any] | str] | None = None,
        *,
        block_when_empty: bool = False,
    ) -> None:
        self.state = State.OPEN
        self.sent: list[dict[str, Any]] = []
        self.closed = False
        self._block_when_empty = block_when_empty
        self._events: deque[str] = deque()
        self._recv_waiters: deque[asyncio.Future[str]] = deque()
        for event in events or []:
            self.queue(event)

    def queue(self, event: dict[str, Any] | str) -> None:
        payload = json.dumps(event) if isinstance(event, dict) else event
        if self._recv_waiters:
            while self._recv_waiters:
                waiter = self._recv_waiters.popleft()
                if not waiter.done():
                    waiter.set_result(payload)
                    return
        self._events.append(payload)

    async def recv(self) -> str:
        if not self._events:
            if self._block_when_empty:
                waiter = asyncio.get_running_loop().create_future()
                self._recv_waiters.append(waiter)
                return await waiter
            raise AssertionError("fake websocket recv called with no queued events")
        return self._events.popleft()

    async def send(self, payload: str) -> None:
        self.sent.append(json.loads(payload))

    async def close(self) -> None:
        self.closed = True
        self.state = State.CLOSED


class _Emitter:
    def __init__(self) -> None:
        self.chunks: list[bytes] = []

    def push(self, chunk: bytes) -> None:
        self.chunks.append(chunk)


def _connected_events() -> list[dict[str, Any]]:
    return [
        {
            "event": "connected_success",
            "session_id": "session-1",
            "trace_id": "trace-1",
            "base_resp": {"status_code": 0, "status_msg": "success"},
        },
        {
            "event": "task_started",
            "session_id": "session-1",
            "trace_id": "trace-1",
            "base_resp": {"status_code": 0, "status_msg": "success"},
        },
    ]


def _audio_event(hex_audio: str) -> dict[str, Any]:
    return {
        "data": {"audio": hex_audio},
        "extra_info": {"usage_characters": 4},
        "is_final": True,
        "session_id": "session-1",
        "trace_id": "trace-1",
        "base_resp": {"status_code": 0, "status_msg": "success"},
    }


@pytest.mark.asyncio
async def test_minimax_prepare_reuses_started_task() -> None:
    ws = _FakeWebSocket(_connected_events())
    connections: list[_FakeWebSocket] = []

    async def connect_factory(*args: Any, **kwargs: Any) -> _FakeWebSocket:
        connections.append(ws)
        return ws

    tts_client = PreparedMiniMaxTTS(
        api_key="test-key",
        connect_factory=connect_factory,
    )

    await tts_client.prepare(reason="test")
    await tts_client.prepare(reason="test-again")

    assert connections == [ws]
    assert [payload["event"] for payload in ws.sent] == ["task_start"]

    await tts_client.aclose()


@pytest.mark.asyncio
async def test_minimax_schedule_prepare_starts_background_task() -> None:
    ws = _FakeWebSocket(_connected_events())
    connections: list[_FakeWebSocket] = []

    async def connect_factory(*args: Any, **kwargs: Any) -> _FakeWebSocket:
        connections.append(ws)
        return ws

    tts_client = PreparedMiniMaxTTS(
        api_key="test-key",
        connect_factory=connect_factory,
    )

    tts_client.schedule_prepare(reason="dialog_start")
    assert tts_client._prepare_task is not None
    await tts_client._prepare_task

    assert connections == [ws]
    assert [payload["event"] for payload in ws.sent] == ["task_start"]

    await tts_client.aclose()


@pytest.mark.asyncio
async def test_minimax_reuses_one_websocket_for_sequential_streams() -> None:
    ws = _FakeWebSocket(_connected_events())

    async def connect_factory(*args: Any, **kwargs: Any) -> _FakeWebSocket:
        return ws

    tts_client = PreparedMiniMaxTTS(
        api_key="test-key",
        connect_factory=connect_factory,
    )
    emitter = _Emitter()

    ws.queue(_audio_event("0102"))
    await tts_client._stream_text_to_emitter(
        text="первая",
        output_emitter=emitter,
        conn_options=DEFAULT_API_CONNECT_OPTIONS,
    )

    ws.queue(_audio_event("0304"))
    await tts_client._stream_text_to_emitter(
        text="вторая",
        output_emitter=emitter,
        conn_options=DEFAULT_API_CONNECT_OPTIONS,
    )

    assert [payload["event"] for payload in ws.sent] == [
        "task_start",
        "task_continue",
        "task_continue",
    ]
    assert [payload.get("text") for payload in ws.sent if payload["event"] == "task_continue"] == [
        "первая",
        "вторая",
    ]
    assert emitter.chunks == [b"\x01\x02", b"\x03\x04"]
    assert ws.closed is False

    await tts_client.aclose()
    assert [payload["event"] for payload in ws.sent][-1] == "task_finish"


@pytest.mark.asyncio
async def test_minimax_aclose_finishes_task_and_closes_websocket() -> None:
    ws = _FakeWebSocket(_connected_events())

    async def connect_factory(*args: Any, **kwargs: Any) -> _FakeWebSocket:
        return ws

    tts_client = PreparedMiniMaxTTS(
        api_key="test-key",
        connect_factory=connect_factory,
    )

    await tts_client.prepare(reason="test")
    await tts_client.aclose()

    assert [payload["event"] for payload in ws.sent] == ["task_start", "task_finish"]
    assert ws.closed is True


@pytest.mark.asyncio
async def test_minimax_reset_closes_stale_websocket_and_next_stream_reconnects() -> None:
    first_ws = _FakeWebSocket([*_connected_events(), _audio_event("not-hex")])
    second_ws = _FakeWebSocket([*_connected_events(), _audio_event("0a0b")])
    sockets = deque([first_ws, second_ws])
    connections: list[_FakeWebSocket] = []

    async def connect_factory(*args: Any, **kwargs: Any) -> _FakeWebSocket:
        ws = sockets.popleft()
        connections.append(ws)
        return ws

    tts_client = PreparedMiniMaxTTS(
        api_key="test-key",
        connect_factory=connect_factory,
    )
    emitter = _Emitter()

    with pytest.raises(APIStatusError):
        await tts_client._stream_text_to_emitter(
            text="сломать",
            output_emitter=emitter,
            conn_options=DEFAULT_API_CONNECT_OPTIONS,
        )

    assert first_ws.closed is True

    await tts_client._stream_text_to_emitter(
        text="новая фраза",
        output_emitter=emitter,
        conn_options=DEFAULT_API_CONNECT_OPTIONS,
    )

    assert connections == [first_ws, second_ws]
    assert emitter.chunks == [b"\x0a\x0b"]

    await tts_client.aclose()


async def _wait_for_sent_event(ws: _FakeWebSocket, event: str) -> None:
    for _ in range(50):
        if any(payload.get("event") == event for payload in ws.sent):
            return
        await asyncio.sleep(0)
    raise AssertionError(f"fake websocket did not send {event}")


@pytest.mark.asyncio
async def test_minimax_cancel_after_continue_drains_and_reuses_websocket() -> None:
    ws = _FakeWebSocket(_connected_events(), block_when_empty=True)
    connections: list[_FakeWebSocket] = []

    async def connect_factory(*args: Any, **kwargs: Any) -> _FakeWebSocket:
        connections.append(ws)
        return ws

    tts_client = PreparedMiniMaxTTS(
        api_key="test-key",
        connect_factory=connect_factory,
        cancel_drain_timeout=0.5,
    )
    emitter = _Emitter()
    task = asyncio.create_task(
        tts_client._stream_text_to_emitter(
            text="старая фраза",
            output_emitter=emitter,
            conn_options=DEFAULT_API_CONNECT_OPTIONS,
        )
    )

    await _wait_for_sent_event(ws, "task_continue")
    task.cancel()
    await asyncio.sleep(0)
    ws.queue(_audio_event("0102"))

    with pytest.raises(asyncio.CancelledError):
        await task

    assert ws.closed is False
    assert emitter.chunks == []

    ws.queue(_audio_event("0304"))
    await tts_client._stream_text_to_emitter(
        text="новая фраза",
        output_emitter=emitter,
        conn_options=DEFAULT_API_CONNECT_OPTIONS,
    )

    assert connections == [ws]
    assert [payload["event"] for payload in ws.sent] == [
        "task_start",
        "task_continue",
        "task_continue",
    ]
    assert emitter.chunks == [b"\x03\x04"]

    await tts_client.aclose()


@pytest.mark.asyncio
async def test_minimax_cancel_drain_timeout_resets_and_prepares_new_websocket() -> None:
    first_ws = _FakeWebSocket(_connected_events(), block_when_empty=True)
    second_ws = _FakeWebSocket(_connected_events())
    sockets = deque([first_ws, second_ws])
    connections: list[_FakeWebSocket] = []

    async def connect_factory(*args: Any, **kwargs: Any) -> _FakeWebSocket:
        ws = sockets.popleft()
        connections.append(ws)
        return ws

    tts_client = PreparedMiniMaxTTS(
        api_key="test-key",
        connect_factory=connect_factory,
        cancel_drain_timeout=0.01,
    )
    task = asyncio.create_task(
        tts_client._stream_text_to_emitter(
            text="старая фраза",
            output_emitter=_Emitter(),
            conn_options=DEFAULT_API_CONNECT_OPTIONS,
        )
    )

    await _wait_for_sent_event(first_ws, "task_continue")
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    if tts_client._prepare_task is not None:
        await tts_client._prepare_task

    assert first_ws.closed is True
    assert second_ws.closed is False
    assert connections == [first_ws, second_ws]
    assert [payload["event"] for payload in second_ws.sent] == ["task_start"]

    await tts_client.aclose()


@pytest.mark.asyncio
async def test_minimax_cancel_before_continue_keeps_prepared_websocket() -> None:
    ws = _FakeWebSocket(_connected_events())

    async def connect_factory(*args: Any, **kwargs: Any) -> _FakeWebSocket:
        return ws

    tts_client = PreparedMiniMaxTTS(
        api_key="test-key",
        connect_factory=connect_factory,
    )

    await tts_client.prepare(reason="test")
    async with tts_client._task_lock:
        await tts_client._recover_cancelled_stream_locked(
            task_continue_started=False,
            task_continue_sent=False,
            found_audio=False,
        )

    assert ws.closed is False
    assert [payload["event"] for payload in ws.sent] == ["task_start"]

    await tts_client.aclose()


class _FakeTTS(lk_tts.TTS):
    def __init__(
        self,
        *,
        provider: str = "MiniMax",
        model: str = "speech-test",
        sample_rate: int = 24000,
    ) -> None:
        super().__init__(
            capabilities=lk_tts.TTSCapabilities(streaming=True),
            sample_rate=sample_rate,
            num_channels=1,
        )
        self._provider = provider
        self._model = model
        self.closed = False
        self.prewarm_calls = 0

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model(self) -> str:
        return self._model

    def synthesize(self, text: str, *, conn_options=DEFAULT_API_CONNECT_OPTIONS):
        raise NotImplementedError

    def stream(self, *, conn_options=DEFAULT_API_CONNECT_OPTIONS):
        return _FakeTTSStream(tts_obj=self, conn_options=conn_options)

    def prewarm(self) -> None:
        self.prewarm_calls += 1

    async def aclose(self) -> None:
        self.closed = True


class _FakeTTSStream(lk_tts.SynthesizeStream):
    def __init__(self, *, tts_obj: "_FallbackTestTTS", conn_options) -> None:
        super().__init__(tts=tts_obj, conn_options=conn_options)
        self._owner = tts_obj

    async def _run(self, output_emitter: lk_tts.AudioEmitter) -> None:
        text_parts: list[str] = []
        async for item in self._input_ch:
            if isinstance(item, str):
                text_parts.append(item)

        text = "".join(text_parts)
        self._owner.requests.append(text)
        if self._owner.fail:
            raise APIConnectionError("primary failed before audio", retryable=True)

        output_emitter.initialize(
            request_id=utils.shortuuid(),
            sample_rate=self._owner.sample_rate,
            num_channels=self._owner.num_channels,
            mime_type="audio/pcm",
            stream=True,
        )
        output_emitter.start_segment(segment_id=utils.shortuuid())
        output_emitter.push(b"\0\0" * 480)
        output_emitter.end_segment()


class _FallbackTestTTS(_FakeTTS):
    def __init__(self, *, provider: str, fail: bool) -> None:
        super().__init__(provider=provider)
        self.fail = fail
        self.requests: list[str] = []


def test_build_tts_minimax_uses_profile_config(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class _FakePreparedMiniMaxTTS(_FakeTTS):
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)
            super().__init__(model=kwargs["model"], sample_rate=kwargs["sample_rate"])

    monkeypatch.setattr(agent, "TTS_PROVIDER", "elevenlabs")
    monkeypatch.setattr(agent, "MINIMAX_API_KEY", "test-key")
    monkeypatch.setattr(agent, "PreparedMiniMaxTTS", _FakePreparedMiniMaxTTS)
    monkeypatch.setattr(agent, "provider_proxy_url", lambda provider: "http://proxy")

    profile = agent.ComponentSelection(
        category="tts",
        slot="primary",
        profile_key="tts_minimax_profile",
        kind="tts",
        provider="minimax",
        config={
            "model": "speech-profile",
            "voice_id": "voice-profile",
            "base_url": "https://api.minimax.io",
            "language_boost": "Russian",
            "speed": 1.15,
            "volume": 0.9,
            "pitch": -1,
            "intensity": 15,
            "timbre": -5,
            "sound_effects": "spacious_echo",
            "format": "mp3",
            "sample_rate": 24000,
            "bitrate": 128000,
            "channel": 1,
            "connection_reuse": False,
            "min_sentence_len": 5,
            "stream_context_len": 2,
        },
        source_owner_type="runtime",
        source_owner_key="base",
    )

    result = agent.build_tts(tts_profile=profile)

    assert isinstance(result, _FakePreparedMiniMaxTTS)
    assert captured["api_key"] == "test-key"
    assert captured["model"] == "speech-profile"
    assert captured["voice_id"] == "voice-profile"
    assert captured["base_url"] == "https://api.minimax.io"
    assert captured["language_boost"] == "Russian"
    assert captured["speed"] == 1.15
    assert captured["volume"] == 0.9
    assert captured["pitch"] == -1
    assert captured["intensity"] == 15
    assert captured["timbre"] == -5
    assert captured["sound_effects"] == "spacious_echo"
    assert captured["audio_format"] == "mp3"
    assert captured["sample_rate"] == 24000
    assert captured["bitrate"] == 128000
    assert captured["channel"] == 1
    assert captured["connection_reuse"] is False
    assert captured["http_proxy"] == "http://proxy"


def test_schedule_tts_prepare_prepares_all_fallback_children() -> None:
    class _PreparedFakeTTS(_FakeTTS):
        def __init__(self, *, model: str) -> None:
            super().__init__(model=model)
            self.prepare_reasons: list[str] = []

        def schedule_prepare(self, reason: str = "background") -> None:
            self.prepare_reasons.append(reason)

    primary = _PreparedFakeTTS(model="primary")
    backup = _PreparedFakeTTS(model="backup")
    adapter = agent.WarmupClosingTTSFallbackAdapter(
        [primary, backup],
        max_retry_per_tts=0,
        sample_rate=24000,
    )

    agent.schedule_tts_prepare(adapter, reason="dialog_start")

    assert primary.prepare_reasons == ["dialog_start"]
    assert backup.prepare_reasons == ["dialog_start"]


def test_build_tts_wraps_backup_profile_in_fallback_adapter(monkeypatch) -> None:
    class _FakePreparedMiniMaxTTS(_FakeTTS):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(model=kwargs["model"], sample_rate=kwargs["sample_rate"])

    monkeypatch.setattr(agent, "MINIMAX_API_KEY", "test-key")
    monkeypatch.setattr(agent, "PreparedMiniMaxTTS", _FakePreparedMiniMaxTTS)
    monkeypatch.setattr(agent, "provider_proxy_url", lambda provider: None)

    primary = agent.ComponentSelection(
        category="tts",
        slot="primary",
        profile_key="tts_minimax_primary",
        kind="tts",
        provider="minimax",
        config={"model": "primary", "sample_rate": 24000},
        source_owner_type="runtime",
        source_owner_key="base",
    )
    backup = agent.ComponentSelection(
        category="tts",
        slot="backup",
        profile_key="tts_minimax_backup",
        kind="tts",
        provider="minimax",
        config={"model": "backup", "sample_rate": 24000},
        source_owner_type="runtime",
        source_owner_key="base",
    )

    result = agent.build_tts(
        tts_profile=primary,
        backup_tts_profile=backup,
        fallback_sample_rate=24000,
    )

    assert isinstance(result, agent.WarmupClosingTTSFallbackAdapter)
    assert [child.model for child in result._tts_instances] == ["primary", "backup"]
    assert result.sample_rate == 24000


@pytest.mark.asyncio
async def test_tts_fallback_replays_text_to_backup_before_first_audio() -> None:
    primary = _FallbackTestTTS(provider="PrimaryTTS", fail=True)
    backup = _FallbackTestTTS(provider="MiniMax", fail=False)
    adapter = agent.WarmupClosingTTSFallbackAdapter(
        [primary, backup],
        max_retry_per_tts=0,
        sample_rate=24000,
    )

    stream = adapter.stream()
    stream.push_text("Привет")
    stream.end_input()
    events = [event async for event in stream]

    assert primary.requests[:1] == ["Привет"]
    assert backup.requests == ["Привет"]
    assert events
    assert backup.closed is False

    await adapter.aclose()
    assert primary.closed is True
    assert backup.closed is True


def test_tts_availability_changed_logs_provider_fallback() -> None:
    primary = _FallbackTestTTS(provider="PrimaryTTS", fail=True)
    backup = _FallbackTestTTS(provider="MiniMax", fail=False)
    adapter = agent.WarmupClosingTTSFallbackAdapter(
        [primary, backup],
        max_retry_per_tts=0,
        sample_rate=24000,
    )
    records: list[dict[str, Any]] = []

    class _IncidentLog:
        def record_nowait(self, incident_type: str, **kwargs: Any) -> None:
            records.append({"incident_type": incident_type, **kwargs})

    agent.register_tts_fallback_incident_listener(adapter, _IncidentLog())
    adapter.emit(
        "tts_availability_changed",
        lk_tts.AvailabilityChangedEvent(tts=primary, available=False),
    )

    assert records == [
        {
            "incident_type": "provider_fallback",
            "severity": "warning",
            "component": "tts",
            "provider": "PrimaryTTS",
            "model": "speech-test",
            "description": "TTS provider became unavailable and fallback path was used",
            "payload": {
                "available": False,
                "label": primary.label,
            },
        }
    ]
