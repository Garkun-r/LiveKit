import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import urlparse

from livekit.agents import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    tokenize,
    tts,
    utils,
)
from livekit.agents.types import (
    DEFAULT_API_CONNECT_OPTIONS,
    NOT_GIVEN,
    APIConnectOptions,
    NotGivenOr,
)
from livekit.agents.utils import is_given
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed
from websockets.protocol import State

DEFAULT_BASE_URL = "https://api.minimax.io"
DEFAULT_MODEL = "speech-2.8-hd"
DEFAULT_VOICE_ID = "moss_audio_43d3c43e-3a2d-11f1-b47e-928b88df9451"
DEFAULT_LANGUAGE_BOOST = "Russian"
DEFAULT_AUDIO_FORMAT = "mp3"
DEFAULT_SAMPLE_RATE = 24000
DEFAULT_BITRATE = 128000
DEFAULT_CHANNELS = 1
_DEFAULT_PREPARE_TIMEOUT_SEC = 10.0
_DEFAULT_CANCEL_DRAIN_TIMEOUT_SEC = 1.0

logger = logging.getLogger("agent")


ConnectFactory = Callable[..., Awaitable[ClientConnection]]


@dataclass
class _MiniMaxTTSOptions:
    api_key: str
    base_url: str
    model: str
    voice_id: str
    language_boost: str
    speed: float
    volume: float
    pitch: int
    intensity: int | None
    timbre: int | None
    sound_effects: str
    audio_format: str
    sample_rate: int
    bitrate: int
    channel: int
    connection_reuse: bool
    http_proxy: str | None
    cancel_drain_timeout: float
    tokenizer: tokenize.SentenceTokenizer


@dataclass
class _MiniMaxPreparedState:
    session_id: str | None = None
    trace_id: str | None = None
    prepared_at: float | None = None


@dataclass
class _MiniMaxStreamStats:
    prepared_reused: bool
    first_audio_ms: float | None
    final_ms: float | None
    audio_chunks: int
    audio_bytes: int
    usage_characters: int | None


def _is_ws_open(ws: ClientConnection | None) -> bool:
    return ws is not None and ws.state == State.OPEN


def _audio_mime_type(fmt: str) -> str:
    resolved = fmt.strip().lower()
    if resolved == "wav":
        return "audio/wav"
    if resolved == "flac":
        return "audio/flac"
    return "audio/mpeg"


def _ws_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme in {"http", "https"}:
        scheme = "wss" if parsed.scheme == "https" else "ws"
        return f"{scheme}://{parsed.netloc}/ws/v1/t2a_v2"
    return f"{base_url.rstrip('/')}/ws/v1/t2a_v2"


def _safe_ms(started_at: float, finished_at: float | None = None) -> float:
    end = finished_at if finished_at is not None else time.perf_counter()
    return round(max(0.0, end - started_at) * 1000, 1)


class PreparedMiniMaxTTS(tts.TTS):
    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_MODEL,
        voice_id: str = DEFAULT_VOICE_ID,
        base_url: str = DEFAULT_BASE_URL,
        language_boost: str = DEFAULT_LANGUAGE_BOOST,
        speed: float = 1.0,
        volume: float = 1.0,
        pitch: int = 0,
        intensity: int | None = None,
        timbre: int | None = None,
        sound_effects: str = "",
        audio_format: str = DEFAULT_AUDIO_FORMAT,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        bitrate: int = DEFAULT_BITRATE,
        channel: int = DEFAULT_CHANNELS,
        connection_reuse: bool = True,
        http_proxy: str | None = None,
        cancel_drain_timeout: float = _DEFAULT_CANCEL_DRAIN_TIMEOUT_SEC,
        tokenizer_obj: NotGivenOr[tokenize.SentenceTokenizer] = NOT_GIVEN,
        connect_factory: ConnectFactory = connect,
    ) -> None:
        if not api_key.strip():
            raise ValueError("MINIMAX_API_KEY is required for MiniMax TTS")

        if not is_given(tokenizer_obj):
            tokenizer_obj = tokenize.blingfire.SentenceTokenizer(
                min_sentence_len=4,
                stream_context_len=1,
            )

        resolved_format = (audio_format or DEFAULT_AUDIO_FORMAT).strip().lower()
        if resolved_format not in {"mp3", "wav", "flac"}:
            resolved_format = "mp3"

        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=True),
            sample_rate=int(sample_rate),
            num_channels=1,
        )

        self._opts = _MiniMaxTTSOptions(
            api_key=api_key.strip(),
            base_url=(
                (base_url or DEFAULT_BASE_URL).strip().rstrip("/") or DEFAULT_BASE_URL
            ),
            model=(model or DEFAULT_MODEL).strip(),
            voice_id=(voice_id or DEFAULT_VOICE_ID).strip(),
            language_boost=(language_boost or DEFAULT_LANGUAGE_BOOST).strip(),
            speed=float(speed),
            volume=float(volume),
            pitch=int(pitch),
            intensity=intensity,
            timbre=timbre,
            sound_effects=(sound_effects or "").strip(),
            audio_format=resolved_format,
            sample_rate=int(sample_rate),
            bitrate=int(bitrate),
            channel=int(channel),
            connection_reuse=bool(connection_reuse),
            http_proxy=http_proxy,
            cancel_drain_timeout=max(0.0, float(cancel_drain_timeout)),
            tokenizer=tokenizer_obj,
        )
        self._connect_factory = connect_factory
        self._task_lock = asyncio.Lock()
        self._ws: ClientConnection | None = None
        self._prepared = _MiniMaxPreparedState()
        self._closed = False
        self._prepare_task: asyncio.Task[None] | None = None
        self._websocket_reconnect_count = 0

    @property
    def model(self) -> str:
        return self._opts.model

    @property
    def provider(self) -> str:
        return "MiniMax"

    @property
    def websocket_reconnect_count(self) -> int:
        return self._websocket_reconnect_count

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> tts.ChunkedStream:
        return self._synthesize_with_stream(text, conn_options=conn_options)

    def stream(
        self,
        *,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> tts.SynthesizeStream:
        return _PreparedMiniMaxSynthesizeStream(tts_obj=self, conn_options=conn_options)

    def schedule_prepare(self, reason: str = "background") -> None:
        if self._closed or not self._opts.connection_reuse:
            return
        if self._prepare_task is not None and not self._prepare_task.done():
            return
        self._prepare_task = asyncio.create_task(
            self.prepare(reason=reason),
            name=f"minimax_tts_prepare_{reason}",
        )
        self._prepare_task.add_done_callback(self._log_prepare_task_result)

    async def prepare(self, reason: str = "manual") -> None:
        if self._closed or not self._opts.connection_reuse:
            return
        try:
            async with self._task_lock:
                await self._ensure_prepared_locked(
                    timeout=_DEFAULT_PREPARE_TIMEOUT_SEC,
                    reason=reason,
                )
        except asyncio.CancelledError:
            async with self._task_lock:
                await self._reset_connection_locked(reason="prepare_cancelled")
            raise
        except Exception:
            async with self._task_lock:
                await self._reset_connection_locked(reason="prepare_failed")
            raise

    async def aclose(self) -> None:
        self._closed = True
        if self._prepare_task is not None and not self._prepare_task.done():
            await utils.aio.cancel_and_wait(self._prepare_task)
        async with self._task_lock:
            await self._finish_and_close_locked(wait_for_finish=False)

    def _log_prepare_task_result(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        with contextlib.suppress(Exception):
            exc = task.exception()
            if exc is not None:
                logger.warning("minimax prepared tts background prepare failed: %s", exc)

    async def _open_ws(self, timeout: float) -> ClientConnection:
        url = _ws_url(self._opts.base_url)
        started_at = time.perf_counter()
        try:
            ws = await asyncio.wait_for(
                self._connect_factory(
                    url,
                    additional_headers={"Authorization": f"Bearer {self._opts.api_key}"},
                    open_timeout=timeout,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                    max_size=16 * 1024 * 1024,
                    proxy=self._opts.http_proxy,
                ),
                timeout=timeout,
            )
            logger.info(
                "minimax prepared tts websocket connected",
                extra={
                    "base_url": self._opts.base_url,
                    "connect_ms": _safe_ms(started_at),
                    "websocket_reconnect_count": self._websocket_reconnect_count,
                },
            )
            return ws
        except asyncio.TimeoutError:
            raise APITimeoutError("minimax tts websocket connect timed out") from None
        except Exception as e:
            raise APIConnectionError(
                f"minimax tts websocket connect error: {e}",
                retryable=True,
            ) from e

    async def _recv_json_locked(self, *, timeout: float) -> dict[str, Any]:
        ws = self._ws
        if not _is_ws_open(ws):
            raise APIConnectionError("minimax tts websocket is not open", retryable=True)
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        except asyncio.TimeoutError:
            raise APITimeoutError("minimax tts websocket receive timed out") from None
        except ConnectionClosed as e:
            raise APIConnectionError(
                f"minimax tts websocket closed: {e}",
                retryable=True,
            ) from e

        try:
            message = json.loads(raw)
        except json.JSONDecodeError as e:
            raise APIStatusError(
                "minimax tts websocket returned invalid JSON",
                status_code=502,
                retryable=True,
                body=str(raw)[:500],
            ) from e

        self._raise_for_message_error(message)
        return message

    def _raise_for_message_error(self, message: dict[str, Any]) -> None:
        base_resp = message.get("base_resp") or {}
        status_code = int(base_resp.get("status_code", 0) or 0)
        if status_code != 0:
            raise APIStatusError(
                str(base_resp.get("status_msg") or "minimax tts api error"),
                status_code=status_code,
                retryable=False,
                body=str(message)[:500],
            )
        if message.get("event") == "task_failed":
            raise APIStatusError(
                "minimax tts task_failed event",
                status_code=502,
                retryable=False,
                body=str(message)[:500],
            )

    async def _wait_for_event_locked(
        self,
        event_name: str,
        *,
        timeout: float,
    ) -> dict[str, Any]:
        while True:
            message = await self._recv_json_locked(timeout=timeout)
            if message.get("event") == event_name:
                return message

    async def _ensure_prepared_locked(self, *, timeout: float, reason: str) -> None:
        if _is_ws_open(self._ws) and self._prepared.prepared_at is not None:
            return

        if self._ws is not None:
            self._websocket_reconnect_count += 1
            logger.info(
                "minimax prepared tts websocket was not reusable; reconnecting",
                extra={
                    "reason": reason,
                    "idle_reconnect": True,
                    "websocket_reconnect_count": self._websocket_reconnect_count,
                },
            )
            await self._close_connection_locked()

        self._ws = await self._open_ws(timeout)
        connected = await self._wait_for_event_locked(
            "connected_success",
            timeout=timeout,
        )
        self._prepared.session_id = connected.get("session_id")
        self._prepared.trace_id = connected.get("trace_id")

        start_msg = self._task_start_payload()
        started_at = time.perf_counter()
        await self._send_json_locked(start_msg)
        task_started = await self._wait_for_event_locked("task_started", timeout=timeout)
        self._prepared.session_id = task_started.get("session_id")
        self._prepared.trace_id = task_started.get("trace_id")
        self._prepared.prepared_at = time.perf_counter()
        logger.info(
            "minimax prepared tts task started",
            extra={
                "reason": reason,
                "model": self._opts.model,
                "voice_id": self._opts.voice_id,
                "base_url": self._opts.base_url,
                "task_start_ms": _safe_ms(started_at),
                "session_id": self._prepared.session_id,
            },
        )

    async def _send_json_locked(self, payload: dict[str, Any]) -> None:
        ws = self._ws
        if not _is_ws_open(ws):
            raise APIConnectionError("minimax tts websocket is not open", retryable=True)
        try:
            await ws.send(json.dumps(payload, ensure_ascii=False))
        except ConnectionClosed as e:
            raise APIConnectionError(
                f"minimax tts websocket closed while sending: {e}",
                retryable=True,
            ) from e
        except Exception as e:
            raise APIConnectionError(
                f"minimax tts websocket send error: {e}",
                retryable=True,
            ) from e

    def _task_start_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "event": "task_start",
            "model": self._opts.model,
            "language_boost": self._opts.language_boost,
            "voice_setting": {
                "voice_id": self._opts.voice_id,
                "speed": self._opts.speed,
                "vol": self._opts.volume,
                "pitch": self._opts.pitch,
            },
            "audio_setting": {
                "sample_rate": self._opts.sample_rate,
                "bitrate": self._opts.bitrate,
                "format": self._opts.audio_format,
                "channel": self._opts.channel,
            },
            "text_normalization": False,
        }
        voice_modify: dict[str, Any] = {}
        if self._opts.intensity is not None:
            voice_modify["intensity"] = self._opts.intensity
        if self._opts.timbre is not None:
            voice_modify["timbre"] = self._opts.timbre
        if self._opts.sound_effects:
            voice_modify["sound_effects"] = self._opts.sound_effects
        if voice_modify:
            payload["voice_modify"] = voice_modify
        return payload

    async def _stream_text_to_emitter(
        self,
        *,
        text: str,
        output_emitter: Any,
        conn_options: APIConnectOptions,
    ) -> _MiniMaxStreamStats:
        async with self._task_lock:
            prepared_reused = _is_ws_open(self._ws) and self._prepared.prepared_at is not None
            started_at = time.perf_counter()
            found_audio = False
            first_audio_at: float | None = None
            audio_chunks = 0
            audio_bytes = 0
            usage_characters: int | None = None
            task_continue_started = False
            task_continue_sent = False
            try:
                await self._ensure_prepared_locked(
                    timeout=conn_options.timeout,
                    reason="stream",
                )
                task_continue_started = True
                await self._send_json_locked({"event": "task_continue", "text": text})
                task_continue_sent = True

                while True:
                    message = await self._recv_json_locked(timeout=conn_options.timeout)
                    data = message.get("data") or {}
                    raw_audio = data.get("audio")
                    if isinstance(raw_audio, str) and raw_audio:
                        if first_audio_at is None:
                            first_audio_at = time.perf_counter()
                        audio_bytes_chunk = bytes.fromhex(raw_audio)
                        if audio_bytes_chunk:
                            output_emitter.push(audio_bytes_chunk)
                            found_audio = True
                            audio_chunks += 1
                            audio_bytes += len(audio_bytes_chunk)

                    if message.get("is_final"):
                        extra_info = message.get("extra_info") or {}
                        usage_raw = extra_info.get("usage_characters")
                        usage_characters = (
                            int(usage_raw)
                            if isinstance(usage_raw, (int, float, str))
                            and str(usage_raw).isdigit()
                            else None
                        )
                        break

                if not found_audio:
                    raise APIStatusError(
                        "minimax tts: no audio returned for the segment",
                        status_code=502,
                        retryable=False,
                    )

                stats = _MiniMaxStreamStats(
                    prepared_reused=prepared_reused,
                    first_audio_ms=(
                        _safe_ms(started_at, first_audio_at) if first_audio_at else None
                    ),
                    final_ms=_safe_ms(started_at),
                    audio_chunks=audio_chunks,
                    audio_bytes=audio_bytes,
                    usage_characters=usage_characters,
                )
                logger.info(
                    "minimax prepared tts segment completed",
                    extra={
                        "prepared_reused": stats.prepared_reused,
                        "ttfb_after_continue_ms": stats.first_audio_ms,
                        "final_ms": stats.final_ms,
                        "audio_chunks": stats.audio_chunks,
                        "audio_bytes": stats.audio_bytes,
                        "usage_characters": stats.usage_characters,
                    },
                )
                if not self._opts.connection_reuse:
                    await self._finish_and_close_locked(wait_for_finish=True)
                return stats
            except asyncio.CancelledError:
                await self._recover_cancelled_stream_locked(
                    task_continue_started=task_continue_started,
                    task_continue_sent=task_continue_sent,
                    found_audio=found_audio,
                )
                raise
            except (APIConnectionError, APIStatusError, APITimeoutError):
                await self._reset_connection_locked(reason="connection_error")
                self.schedule_prepare("connection_error")
                raise
            except ValueError as e:
                await self._reset_connection_locked(reason="invalid_audio_hex")
                raise APIStatusError(
                    "minimax tts returned invalid audio hex",
                    status_code=502,
                    retryable=True,
                ) from e

    async def _recover_cancelled_stream_locked(
        self,
        *,
        task_continue_started: bool,
        task_continue_sent: bool,
        found_audio: bool,
    ) -> None:
        if not task_continue_started:
            if _is_ws_open(self._ws) and self._prepared.prepared_at is not None:
                logger.info(
                    "minimax prepared tts cancel before task_continue; keeping websocket"
                )
                return
            await self._reset_connection_locked(reason="cancelled_before_continue")
            self.schedule_prepare("cancelled_before_continue")
            return

        if not task_continue_sent:
            await self._reset_connection_locked(reason="cancelled_during_continue_send")
            self.schedule_prepare("cancelled_during_continue_send")
            return

        if await self._drain_cancelled_segment_locked(found_audio=found_audio):
            return

        await self._reset_connection_locked(reason="cancel_drain_failed")
        self.schedule_prepare("cancel_drain_failed")

    async def _drain_cancelled_segment_locked(self, *, found_audio: bool) -> bool:
        timeout = self._opts.cancel_drain_timeout
        if timeout <= 0 or not _is_ws_open(self._ws):
            return False

        started_at = time.perf_counter()
        discarded_chunks = 0
        discarded_bytes = 0
        try:
            while True:
                remaining = timeout - (time.perf_counter() - started_at)
                if remaining <= 0:
                    logger.info(
                        "minimax prepared tts cancel drain timed out",
                        extra={
                            "cancel_drain_timeout_ms": round(timeout * 1000, 1),
                            "cancel_drain_ms": _safe_ms(started_at),
                            "cancel_drain_discarded_chunks": discarded_chunks,
                            "cancel_drain_discarded_bytes": discarded_bytes,
                            "cancel_after_audio": found_audio,
                        },
                    )
                    return False

                message = await self._recv_json_locked(timeout=remaining)
                data = message.get("data") or {}
                raw_audio = data.get("audio")
                if isinstance(raw_audio, str) and raw_audio:
                    discarded_chunks += 1
                    discarded_bytes += max(0, len(raw_audio) // 2)

                if message.get("is_final"):
                    logger.info(
                        "minimax prepared tts cancel drained segment; keeping websocket",
                        extra={
                            "cancel_drain_ms": _safe_ms(started_at),
                            "cancel_drain_discarded_chunks": discarded_chunks,
                            "cancel_drain_discarded_bytes": discarded_bytes,
                            "cancel_after_audio": found_audio,
                        },
                    )
                    return True
        except (APIConnectionError, APIStatusError, APITimeoutError) as e:
            logger.warning(
                "minimax prepared tts cancel drain failed: %s",
                e,
                extra={"cancel_after_audio": found_audio},
            )
            return False

    async def _reset_connection_locked(self, reason: str) -> None:
        if self._ws is None:
            self._prepared = _MiniMaxPreparedState()
            return
        self._websocket_reconnect_count += 1
        logger.warning(
            "minimax prepared tts websocket reset",
            extra={
                "reason": reason,
                "websocket_reconnect_count": self._websocket_reconnect_count,
            },
        )
        await self._close_connection_locked()

    async def _finish_and_close_locked(self, *, wait_for_finish: bool) -> None:
        if self._ws is not None and self._prepared.prepared_at is not None:
            with contextlib.suppress(Exception):
                await self._send_json_locked({"event": "task_finish"})
                if wait_for_finish:
                    await self._wait_for_event_locked("task_finished", timeout=2.0)
        await self._close_connection_locked()

    async def _close_connection_locked(self) -> None:
        ws = self._ws
        self._ws = None
        self._prepared = _MiniMaxPreparedState()
        if ws is None:
            return
        with contextlib.suppress(Exception):
            await ws.close()


class _PreparedMiniMaxSynthesizeStream(tts.SynthesizeStream):
    def __init__(self, *, tts_obj: PreparedMiniMaxTTS, conn_options: APIConnectOptions):
        super().__init__(tts=tts_obj, conn_options=conn_options)
        self._tts: PreparedMiniMaxTTS = tts_obj
        self._opts = replace(tts_obj._opts)

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        segments_ch = utils.aio.Chan[tokenize.SentenceStream]()
        output_emitter.initialize(
            request_id=utils.shortuuid(),
            sample_rate=self._tts.sample_rate,
            num_channels=self._tts.num_channels,
            mime_type=_audio_mime_type(self._opts.audio_format),
            stream=True,
        )

        async def _tokenize_input() -> None:
            input_stream = None
            async for input_item in self._input_ch:
                if isinstance(input_item, str):
                    if input_stream is None:
                        input_stream = self._opts.tokenizer.stream()
                        segments_ch.send_nowait(input_stream)
                    input_stream.push_text(input_item)
                elif isinstance(input_item, self._FlushSentinel):
                    if input_stream is not None:
                        input_stream.end_input()
                    input_stream = None
            if input_stream is not None:
                input_stream.end_input()
            segments_ch.close()

        async def _run_segments() -> None:
            async for input_stream in segments_ch:
                output_emitter.start_segment(segment_id=utils.shortuuid())
                await self._run_segment_stream(
                    input_stream=input_stream,
                    output_emitter=output_emitter,
                )
                output_emitter.end_segment()

        tasks = [
            asyncio.create_task(_tokenize_input()),
            asyncio.create_task(_run_segments()),
        ]
        try:
            await asyncio.gather(*tasks)
        finally:
            await utils.aio.cancel_and_wait(*tasks)

    async def _run_segment_stream(
        self,
        *,
        input_stream: tokenize.SentenceStream,
        output_emitter: tts.AudioEmitter,
    ) -> None:
        text_parts: list[str] = []
        async for sentence in input_stream:
            text = (sentence.token or "").strip()
            if text:
                text_parts.append(text)

        if not text_parts:
            raise APIStatusError(
                "minimax tts: empty segment text",
                status_code=400,
                retryable=False,
            )

        text = " ".join(text_parts)
        self._mark_started()
        await self._tts._stream_text_to_emitter(
            text=text,
            output_emitter=output_emitter,
            conn_options=self._conn_options,
        )


MiniMaxTTS = PreparedMiniMaxTTS
