import asyncio
import contextlib
import json
import logging
import uuid
from dataclasses import dataclass, field, replace

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

DEFAULT_MODEL = "cosyvoice-v3.5-flash"
DEFAULT_REGION = "cn-beijing"
DEFAULT_FORMAT = "pcm"
DEFAULT_SAMPLE_RATE = 24000
DEFAULT_VOICE_MODE = "preset"
DEFAULT_RATE = 1.0
DEFAULT_PITCH = 1.0
DEFAULT_VOLUME = 50
DEFAULT_MAX_TEXT_CHARS = 80
CN_WEBSOCKET_URL = "wss://dashscope.aliyuncs.com/api-ws/v1/inference"
INTL_WEBSOCKET_URL = "wss://dashscope-intl.aliyuncs.com/api-ws/v1/inference"

logger = logging.getLogger("agent")


@dataclass
class _CosyVoiceOptions:
    api_key: str
    model: str
    region: str
    ws_url: str
    voice_mode: str
    voice_id: str
    clone_voice_id: str
    design_voice_id: str
    audio_format: str
    sample_rate: int
    rate: float
    pitch: float
    volume: int
    connection_reuse: bool
    playback_on_first_chunk: bool
    tokenizer: tokenize.SentenceTokenizer


@dataclass
class _TaskRuntime:
    task_id: str
    run_sent_at: float = 0.0
    task_started_at: float | None = None
    first_audio_at: float | None = None
    task_finished_at: float | None = None
    text_chunks_sent: int = 0
    audio_chunks_received: int = 0
    started_event: asyncio.Event = field(default_factory=asyncio.Event)
    finished_event: asyncio.Event = field(default_factory=asyncio.Event)
    buffered_audio: list[bytes] = field(default_factory=list)
    error: Exception | None = None


def _default_ws_url_for_region(region: str) -> str:
    normalized = (region or "").strip().lower()
    if normalized.startswith("cn"):
        return CN_WEBSOCKET_URL
    return INTL_WEBSOCKET_URL


def _is_ws_open(ws: ClientConnection | None) -> bool:
    return ws is not None and ws.state == State.OPEN


def _mime_type(audio_format: str) -> str:
    fmt = (audio_format or "").strip().lower()
    if fmt == "wav":
        return "audio/wav"
    if fmt == "mp3":
        return "audio/mpeg"
    if fmt == "opus":
        return "audio/opus"
    return "audio/pcm"


def _split_continue_chunks(
    text: str, max_chars: int = DEFAULT_MAX_TEXT_CHARS
) -> list[str]:
    normalized = " ".join((text or "").split())
    if not normalized:
        return []
    if len(normalized) <= max_chars:
        return [normalized]

    chunks: list[str] = []
    current = ""
    for word in normalized.split(" "):
        if not current:
            current = word
            continue

        candidate = f"{current} {word}"
        if len(candidate) <= max_chars:
            current = candidate
            continue

        chunks.append(current)
        current = word

    if current:
        chunks.append(current)

    return chunks


class CosyVoiceTTS(tts.TTS):
    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_MODEL,
        region: str = DEFAULT_REGION,
        ws_url: str = "",
        voice_mode: str = DEFAULT_VOICE_MODE,
        voice_id: str = "",
        clone_voice_id: str = "",
        design_voice_id: str = "",
        audio_format: str = DEFAULT_FORMAT,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        rate: float = DEFAULT_RATE,
        pitch: float = DEFAULT_PITCH,
        volume: int = DEFAULT_VOLUME,
        connection_reuse: bool = True,
        playback_on_first_chunk: bool = True,
        tokenizer_obj: NotGivenOr[tokenize.SentenceTokenizer] = NOT_GIVEN,
    ) -> None:
        if not api_key.strip():
            raise ValueError("COSYVOICE_API_KEY is required for CosyVoice TTS")

        if not is_given(tokenizer_obj):
            tokenizer_obj = tokenize.blingfire.SentenceTokenizer(
                min_sentence_len=4,
                stream_context_len=1,
            )

        resolved_format = (audio_format or DEFAULT_FORMAT).strip().lower()
        if resolved_format not in {"pcm", "wav", "mp3", "opus"}:
            raise ValueError("COSYVOICE_TTS_FORMAT must be one of: pcm, wav, mp3, opus")

        resolved_mode = (voice_mode or DEFAULT_VOICE_MODE).strip().lower()
        if resolved_mode not in {"preset", "clone", "design"}:
            raise ValueError(
                "COSYVOICE_TTS_VOICE_MODE must be one of: preset, clone, design"
            )
        if resolved_mode == "preset" and not (voice_id or "").strip():
            raise ValueError(
                "COSYVOICE_TTS_VOICE_ID is required when voice_mode=preset"
            )
        if resolved_mode == "clone" and not (clone_voice_id or "").strip():
            raise ValueError(
                "COSYVOICE_TTS_CLONE_VOICE_ID is required when voice_mode=clone"
            )
        if resolved_mode == "design" and not (design_voice_id or "").strip():
            raise ValueError(
                "COSYVOICE_TTS_DESIGN_VOICE_ID is required when voice_mode=design"
            )

        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=True),
            sample_rate=int(sample_rate),
            num_channels=1,
        )

        resolved_model = (model or DEFAULT_MODEL).strip()
        self._opts = _CosyVoiceOptions(
            api_key=api_key.strip(),
            model=resolved_model,
            region=(region or DEFAULT_REGION).strip(),
            ws_url=(ws_url or _default_ws_url_for_region(region)).strip(),
            voice_mode=resolved_mode,
            voice_id=(voice_id or "").strip(),
            clone_voice_id=(clone_voice_id or "").strip(),
            design_voice_id=(design_voice_id or "").strip(),
            audio_format=resolved_format,
            sample_rate=int(sample_rate),
            rate=float(rate),
            pitch=float(pitch),
            volume=int(volume),
            connection_reuse=bool(connection_reuse),
            playback_on_first_chunk=bool(playback_on_first_chunk),
            tokenizer=tokenizer_obj,
        )

        if resolved_model.startswith("cosyvoice-v3.5") and resolved_mode == "preset":
            logger.warning(
                "CosyVoice model '%s' usually requires custom clone/design voice ids; "
                "preset voice mode may fail if voice is not compatible",
                resolved_model,
            )

        self._ws: ClientConnection | None = None
        self._connection_lock = asyncio.Lock()
        self._task_lock = asyncio.Lock()
        self._websocket_reconnect_count = 0

    @property
    def model(self) -> str:
        return self._opts.model

    @property
    def provider(self) -> str:
        return "CosyVoice"

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
        return _CosyVoiceSynthesizeStream(tts_obj=self, conn_options=conn_options)

    async def _open_connection(self) -> ClientConnection:
        try:
            return await connect(
                self._opts.ws_url,
                additional_headers={
                    "Authorization": f"bearer {self._opts.api_key}",
                },
                open_timeout=10,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
                max_size=None,
            )
        except Exception as e:
            raise APIConnectionError(
                f"cosyvoice tts websocket connect error: {e}",
                retryable=True,
            ) from e

    async def _ensure_connection(self) -> ClientConnection:
        async with self._connection_lock:
            if _is_ws_open(self._ws):
                return self._ws  # type: ignore[return-value]

            if self._ws is not None:
                self._websocket_reconnect_count += 1
                logger.warning(
                    "cosyvoice websocket reconnecting",
                    extra={
                        "websocket_reconnect_count": self._websocket_reconnect_count
                    },
                )
                await self._close_connection_locked()

            self._ws = await self._open_connection()
            return self._ws

    async def _reset_connection(self, reason: str) -> None:
        async with self._connection_lock:
            if self._ws is None:
                return
            self._websocket_reconnect_count += 1
            logger.warning(
                "cosyvoice websocket dropped; resetting connection",
                extra={
                    "reason": reason,
                    "websocket_reconnect_count": self._websocket_reconnect_count,
                },
            )
            await self._close_connection_locked()

    async def _close_connection_locked(self) -> None:
        ws = self._ws
        self._ws = None
        if ws is None:
            return
        with contextlib.suppress(Exception):
            await ws.close()

    async def _close_connection(self) -> None:
        async with self._connection_lock:
            await self._close_connection_locked()

    async def aclose(self) -> None:
        await self._close_connection()


class _CosyVoiceSynthesizeStream(tts.SynthesizeStream):
    def __init__(self, *, tts_obj: CosyVoiceTTS, conn_options: APIConnectOptions):
        super().__init__(tts=tts_obj, conn_options=conn_options)
        self._tts: CosyVoiceTTS = tts_obj
        self._opts = replace(tts_obj._opts)

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        segments_ch = utils.aio.Chan[tokenize.SentenceStream]()

        output_emitter.initialize(
            request_id=utils.shortuuid(),
            sample_rate=self._tts.sample_rate,
            num_channels=self._tts.num_channels,
            mime_type=_mime_type(self._opts.audio_format),
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
                    if input_stream:
                        input_stream.end_input()
                    input_stream = None

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
        async with self._tts._task_lock:
            ws = await self._tts._ensure_connection()

            runtime = _TaskRuntime(task_id=uuid.uuid4().hex)
            runtime.run_sent_at = asyncio.get_running_loop().time()
            reader_task = asyncio.create_task(
                self._read_task_messages(
                    ws=ws,
                    runtime=runtime,
                    output_emitter=output_emitter,
                )
            )

            try:
                await self._send_run_task(ws=ws, runtime=runtime)
                await self._wait_for_started(runtime)
                self._mark_started()

                async for sentence in input_stream:
                    token = (sentence.token or "").strip()
                    if not token:
                        continue
                    for text_chunk in _split_continue_chunks(token):
                        await self._send_continue_task(
                            ws=ws,
                            runtime=runtime,
                            text=text_chunk,
                        )

                await self._send_finish_task(ws=ws, runtime=runtime)
                await self._wait_for_finished(runtime)
            except Exception as e:
                if not isinstance(
                    e,
                    (APIStatusError, APIConnectionError, APITimeoutError),
                ):
                    logger.exception("cosyvoice tts task failed: %s", e)
                await self._tts._reset_connection(reason=str(e))
                raise
            finally:
                if not reader_task.done():
                    reader_task.cancel()
                await asyncio.gather(reader_task, return_exceptions=True)

                if not self._opts.connection_reuse:
                    await self._tts._close_connection()

            if runtime.error:
                raise runtime.error

            if (
                not self._opts.playback_on_first_chunk
                and runtime.audio_chunks_received > 0
                and runtime.buffered_audio
            ):
                for chunk in runtime.buffered_audio:
                    output_emitter.push(chunk)

            if runtime.text_chunks_sent > 0 and runtime.audio_chunks_received == 0:
                raise APIStatusError(
                    "cosyvoice tts: no audio returned for the segment",
                    status_code=502,
                    retryable=False,
                )

            time_to_task_started = (
                runtime.task_started_at - runtime.run_sent_at
                if runtime.task_started_at is not None
                else None
            )
            time_to_first_audio = (
                runtime.first_audio_at - runtime.run_sent_at
                if runtime.first_audio_at is not None
                else None
            )
            total_tts_duration = (
                runtime.task_finished_at - runtime.run_sent_at
                if runtime.task_finished_at is not None
                else None
            )
            logger.info(
                "cosyvoice tts metrics",
                extra={
                    "task_id": runtime.task_id,
                    "model": self._opts.model,
                    "time_to_task_started": time_to_task_started,
                    "time_to_first_audio": time_to_first_audio,
                    "total_tts_duration": total_tts_duration,
                    "audio_chunks_received": runtime.audio_chunks_received,
                    "text_chunks_sent": runtime.text_chunks_sent,
                    "websocket_reconnect_count": self._tts.websocket_reconnect_count,
                },
            )

    def _resolve_voice_id(self) -> str:
        if self._opts.voice_mode == "clone":
            resolved_voice = self._opts.clone_voice_id
        elif self._opts.voice_mode == "design":
            resolved_voice = self._opts.design_voice_id
        else:
            resolved_voice = self._opts.voice_id

        if not resolved_voice:
            raise APIStatusError(
                (
                    "cosyvoice tts: voice id is required "
                    f"for voice_mode='{self._opts.voice_mode}'"
                ),
                status_code=400,
                retryable=False,
            )
        return resolved_voice

    async def _send_run_task(
        self, *, ws: ClientConnection, runtime: _TaskRuntime
    ) -> None:
        payload = {
            "header": {
                "action": "run-task",
                "task_id": runtime.task_id,
                "streaming": "duplex",
            },
            "payload": {
                "task_group": "audio",
                "task": "tts",
                "function": "SpeechSynthesizer",
                "model": self._opts.model,
                "parameters": {
                    "text_type": "PlainText",
                    "voice": self._resolve_voice_id(),
                    "format": self._opts.audio_format,
                    "sample_rate": self._opts.sample_rate,
                    "volume": self._opts.volume,
                    "rate": self._opts.rate,
                    "pitch": self._opts.pitch,
                },
                "input": {},
            },
        }
        try:
            await ws.send(json.dumps(payload, ensure_ascii=False))
        except ConnectionClosed as e:
            raise APIConnectionError(
                f"cosyvoice tts run-task send failed: {e}",
                retryable=True,
            ) from e

    async def _send_continue_task(
        self,
        *,
        ws: ClientConnection,
        runtime: _TaskRuntime,
        text: str,
    ) -> None:
        payload = {
            "header": {
                "action": "continue-task",
                "task_id": runtime.task_id,
                "streaming": "duplex",
            },
            "payload": {
                "input": {
                    "text": text,
                }
            },
        }

        try:
            await ws.send(json.dumps(payload, ensure_ascii=False))
        except ConnectionClosed as e:
            raise APIConnectionError(
                f"cosyvoice tts continue-task send failed: {e}",
                retryable=True,
            ) from e

        runtime.text_chunks_sent += 1

    async def _send_finish_task(
        self, *, ws: ClientConnection, runtime: _TaskRuntime
    ) -> None:
        payload = {
            "header": {
                "action": "finish-task",
                "task_id": runtime.task_id,
                "streaming": "duplex",
            },
            "payload": {
                "input": {},
            },
        }

        try:
            await ws.send(json.dumps(payload, ensure_ascii=False))
        except ConnectionClosed as e:
            raise APIConnectionError(
                f"cosyvoice tts finish-task send failed: {e}",
                retryable=True,
            ) from e

    async def _wait_for_started(self, runtime: _TaskRuntime) -> None:
        try:
            await asyncio.wait_for(
                runtime.started_event.wait(), timeout=self._conn_options.timeout
            )
        except asyncio.TimeoutError:
            raise APITimeoutError() from None

        if runtime.error:
            raise runtime.error

    async def _wait_for_finished(self, runtime: _TaskRuntime) -> None:
        finish_timeout = max(float(self._conn_options.timeout), 60.0)
        try:
            await asyncio.wait_for(
                runtime.finished_event.wait(), timeout=finish_timeout
            )
        except asyncio.TimeoutError:
            raise APITimeoutError() from None

        if runtime.error:
            raise runtime.error

    async def _read_task_messages(
        self,
        *,
        ws: ClientConnection,
        runtime: _TaskRuntime,
        output_emitter: tts.AudioEmitter,
    ) -> None:
        loop = asyncio.get_running_loop()

        try:
            while True:
                message = await ws.recv()
                now = loop.time()

                if isinstance(message, bytes):
                    if runtime.first_audio_at is None:
                        runtime.first_audio_at = now
                    runtime.audio_chunks_received += 1
                    if self._opts.playback_on_first_chunk:
                        output_emitter.push(message)
                    else:
                        runtime.buffered_audio.append(message)
                    continue

                if not isinstance(message, str):
                    continue

                try:
                    event_obj = json.loads(message)
                except json.JSONDecodeError:
                    continue

                header = event_obj.get("header") or {}
                event_task_id = str(header.get("task_id") or "").strip()
                if event_task_id and event_task_id != runtime.task_id:
                    # Shared connection can carry old/parallel control events.
                    # Ignore events that do not belong to this task.
                    continue

                event_name = str(header.get("event") or "").strip().lower()
                if not event_name:
                    continue

                if event_name == "task-started":
                    runtime.task_started_at = now
                    runtime.started_event.set()
                    continue

                if event_name == "task-finished":
                    runtime.task_finished_at = now
                    runtime.started_event.set()
                    runtime.finished_event.set()
                    return

                if event_name == "task-failed":
                    runtime.error = APIStatusError(
                        message="cosyvoice tts task-failed event",
                        status_code=502,
                        retryable=False,
                        body=message[:500],
                    )
                    runtime.started_event.set()
                    runtime.finished_event.set()
                    return

        except ConnectionClosed as e:
            runtime.error = APIConnectionError(
                f"cosyvoice tts websocket closed: {e}",
                retryable=True,
            )
            runtime.started_event.set()
            runtime.finished_event.set()
        except Exception as e:
            runtime.error = APIConnectionError(
                f"cosyvoice tts websocket read error: {e}",
                retryable=True,
            )
            runtime.started_event.set()
            runtime.finished_event.set()
