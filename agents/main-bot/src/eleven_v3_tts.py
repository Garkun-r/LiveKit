from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
import re
import time
import urllib.parse
import weakref
from dataclasses import dataclass, replace
from typing import Any, Literal

import aiohttp
from livekit.agents import (
    APIConnectionError,
    APIConnectOptions,
    APIError,
    APIStatusError,
    APITimeoutError,
    LanguageCode,
    tokenize,
    tts,
    utils,
)
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, NOT_GIVEN, NotGivenOr
from livekit.agents.utils import is_given
from livekit.plugins import elevenlabs
from livekit.plugins.elevenlabs import TTSEncoding

# Keep same encoding default as the official ElevenLabs plugin.
_DEFAULT_ENCODING: TTSEncoding = "mp3_22050_32"
API_BASE_URL_V1 = "https://api.elevenlabs.io/v1"
AUTHORIZATION_HEADER = "xi-api-key"
_DEFAULT_REQUEST_TIMEOUT = 30.0
_EMITTER_FRAME_SIZE_MS = 20
# Maximum sentences to prefetch simultaneously; limits memory for long responses.
_PIPELINE_PREFETCH = 3

logger = logging.getLogger("agent")

_EMOJI_RE = re.compile(
    "["
    "\U0001f1e6-\U0001f1ff"  # flags
    "\U0001f300-\U0001faff"  # symbols & pictographs
    "\u2600-\u27bf"  # misc symbols/dingbats
    "\u200d"  # zero width joiner
    "\ufe0e\ufe0f"  # text/emoji variation selectors
    "]"
)
_SPEAKER_TAG_PREFIX_RE = re.compile(
    r"^\s*(?:"
    r"\[(?:speaker|spk|spkr|спикер)\s*[_\-]?\d+\]\s*:?\s*|"
    r"<(?:speaker|spk|spkr|спикер)\b[^>]*>\s*:?\s*|"
    r"(?:speaker|spk|spkr|спикер)\s*[_\-]?\d+\s*:?\s*"
    r")+",
    flags=re.IGNORECASE,
)
_STRONG_SENTENCE_END_RE = re.compile(r"[.!?…]\s*$")
_TRAILING_SOFT_PUNCT_RE = re.compile(r"[\s\.,!?:;…\-—]+$")
_SHORT_CONFIRMATIONS = {
    "\u0430\u0433\u0430",
    "\u0434\u0430",
    "\u043a\u043e\u043d\u0435\u0447\u043d\u043e",
    "\u043b\u0430\u0434\u043d\u043e",
    "\u043d\u0435\u0442",
    "\u043e\u043a",
    "ok",
    "okay",
    "\u043e\u043a\u0435\u0439",
    "\u043f\u043e\u043d\u044f\u043b",
    "\u043f\u043e\u043d\u044f\u043b\u0430",
    "\u043f\u0440\u0438\u043d\u044f\u0442\u043e",
    "\u0443\u0433\u0443",
    "\u0445\u043e\u0440\u043e\u0448\u043e",
}


def _sample_rate_from_format(output_format: TTSEncoding) -> int:
    return int(output_format.split("_")[1])


def _encoding_to_mimetype(encoding: TTSEncoding) -> str:
    # FIX: "audio/mp3" is not a registered MIME type — correct type is "audio/mpeg".
    # Using the wrong type causes LiveKit's AudioEmitter to select the wrong decoder,
    # which produces white noise / hissing when MP3 bytes are interpreted as raw PCM.
    if encoding.startswith("mp3"):
        return "audio/mpeg"
    if encoding.startswith("opus"):
        return "audio/opus"
    if encoding.startswith("pcm"):
        return "audio/pcm"
    raise ValueError(f"Unsupported encoding: {encoding}")


def _strip_nones(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if is_given(v) and v is not None}


def _sanitize_outbound_text_segment(text: str) -> tuple[str, str | None]:
    """Return trimmed text + skip reason when segment is unsafe for Eleven input."""
    trimmed = (text or "").strip()
    if not trimmed:
        return "", "empty_after_trim"

    probe = _SPEAKER_TAG_PREFIX_RE.sub("", trimmed).strip()
    if not probe:
        return "", "empty_after_speaker_tag_strip"

    probe = _EMOJI_RE.sub("", probe).strip()
    if not probe:
        return "", "empty_after_emoji_strip"

    if not any(char.isalnum() for char in probe):
        return "", "punctuation_only"

    return trimmed, None


def _is_short_confirmation(text: str) -> bool:
    normalized = _TRAILING_SOFT_PUNCT_RE.sub("", text.strip()).casefold()
    return normalized in _SHORT_CONFIRMATIONS


@dataclass
class _TTSOptions:
    api_key: str
    voice_id: str
    voice_settings: NotGivenOr[elevenlabs.VoiceSettings]
    model_id: str
    language: NotGivenOr[LanguageCode]
    base_url: str
    output_format: TTSEncoding
    sample_rate: int
    tokenizer: tokenize.SentenceTokenizer
    enable_logging: bool
    request_timeout: float
    apply_text_normalization: Literal["auto", "on", "off"]
    optimize_streaming_latency: NotGivenOr[int]
    min_http_text_len: int
    merge_hold_ms: int
    max_merged_text_len: int


class ElevenV3HTTPStreamTTS(tts.TTS):
    """Production HTTP streaming adapter for ElevenLabs eleven_v3.

    Uses POST /v1/text-to-speech/{voice_id}/stream and pipelines per-sentence
    HTTP requests so that request N+1 starts while N is still being played back.
    """

    def __init__(
        self,
        *,
        voice_id: str = elevenlabs.DEFAULT_VOICE_ID,
        voice_settings: NotGivenOr[elevenlabs.VoiceSettings] = NOT_GIVEN,
        model_id: str = "eleven_v3",
        output_format: NotGivenOr[TTSEncoding] = NOT_GIVEN,
        api_key: NotGivenOr[str] = NOT_GIVEN,
        base_url: NotGivenOr[str] = NOT_GIVEN,
        tokenizer: NotGivenOr[tokenize.SentenceTokenizer] = NOT_GIVEN,
        enable_logging: bool = True,
        request_timeout: float = _DEFAULT_REQUEST_TIMEOUT,
        apply_text_normalization: Literal["auto", "off", "on"] = "auto",
        language: NotGivenOr[str] = NOT_GIVEN,
        optimize_streaming_latency: NotGivenOr[int] = NOT_GIVEN,
        min_http_text_len: int = 18,
        merge_hold_ms: int = 140,
        max_merged_text_len: int = 80,
        http_session: aiohttp.ClientSession | None = None,
        http_proxy: str | None = None,
    ) -> None:
        if not is_given(output_format):
            output_format = _DEFAULT_ENCODING

        super().__init__(
            capabilities=tts.TTSCapabilities(
                streaming=True,
                aligned_transcript=False,
            ),
            sample_rate=_sample_rate_from_format(output_format),
            num_channels=1,
        )

        elevenlabs_api_key = (
            api_key
            if is_given(api_key)
            else os.environ.get("ELEVENLABS_API_KEY")
            or os.environ.get("ELEVEN_API_KEY")
        )
        if not elevenlabs_api_key:
            raise ValueError(
                "ElevenLabs API key is required, either as argument or set "
                "ELEVENLABS_API_KEY / ELEVEN_API_KEY environment variable"
            )

        if not is_given(tokenizer):
            tokenizer = tokenize.blingfire.SentenceTokenizer()

        if is_given(optimize_streaming_latency):
            if not (0 <= optimize_streaming_latency <= 4):
                raise ValueError(
                    "optimize_streaming_latency must be in range [0, 4] when provided"
                )
            if model_id == "eleven_v3":
                logger.warning(
                    "optimize_streaming_latency is not supported for eleven_v3; "
                    "ignoring this parameter to avoid 400 unsupported_model",
                    extra={"value": optimize_streaming_latency},
                )
                optimize_streaming_latency = NOT_GIVEN
            else:
                logger.warning(
                    "optimize_streaming_latency is a legacy ElevenLabs latency knob; "
                    "behavior may vary across models/endpoints",
                    extra={"value": optimize_streaming_latency},
                )

        self._opts = _TTSOptions(
            api_key=elevenlabs_api_key,
            voice_id=voice_id,
            voice_settings=voice_settings,
            model_id=model_id,
            language=LanguageCode(language) if is_given(language) else NOT_GIVEN,
            base_url=base_url if is_given(base_url) else API_BASE_URL_V1,
            output_format=output_format,
            sample_rate=self.sample_rate,
            tokenizer=tokenizer,
            enable_logging=enable_logging,
            request_timeout=request_timeout,
            apply_text_normalization=apply_text_normalization,
            optimize_streaming_latency=optimize_streaming_latency,
            min_http_text_len=max(1, int(min_http_text_len)),
            merge_hold_ms=max(0, int(merge_hold_ms)),
            max_merged_text_len=max(1, int(max_merged_text_len)),
        )
        self._session = http_session
        self._http_proxy = http_proxy
        self._owns_session = False
        self._http_request_count = 0
        self._streams = weakref.WeakSet[ElevenV3HTTPStreamSynthesizeStream]()

    @property
    def model(self) -> str:
        return self._opts.model_id

    @property
    def provider(self) -> str:
        return "ElevenLabs"

    def _ensure_session(self) -> aiohttp.ClientSession:
        if not self._session:
            if self._http_proxy:
                connector = aiohttp.TCPConnector(
                    limit_per_host=50,
                    keepalive_timeout=120,
                )
                self._session = aiohttp.ClientSession(
                    proxy=self._http_proxy,
                    connector=connector,
                )
                self._owns_session = True
            else:
                self._session = utils.http_context.http_session()
        return self._session

    def _connection_reused_hint(self) -> bool:
        reused = self._http_request_count > 0
        self._http_request_count += 1
        return reused

    async def warmup_synthesis(self, text: str = "Да.") -> None:
        """Warm the actual ElevenLabs streaming endpoint and discard audio bytes."""

        class _DiscardAudio:
            def push(self, _: bytes) -> None:
                return

        await _do_http_stream(
            tts_provider=self,
            opts=replace(self._opts),
            text=text,
            prev_text="",
            conn_options=DEFAULT_API_CONNECT_OPTIONS,
            on_chunk=_DiscardAudio(),
        )

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> tts.ChunkedStream:
        return ElevenV3HTTPChunkedStream(
            tts=self,
            input_text=text,
            conn_options=conn_options,
        )

    def stream(
        self,
        *,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> tts.SynthesizeStream:
        stream = ElevenV3HTTPStreamSynthesizeStream(tts=self, conn_options=conn_options)
        self._streams.add(stream)
        return stream

    async def aclose(self) -> None:
        for stream in list(self._streams):
            await stream.aclose()
        self._streams.clear()
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()
            self._session = None
            self._owns_session = False


class ElevenV3HTTPChunkedStream(tts.ChunkedStream):
    def __init__(
        self,
        *,
        tts: ElevenV3HTTPStreamTTS,
        input_text: str,
        conn_options: APIConnectOptions,
    ) -> None:
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._tts = tts
        self._opts = replace(tts._opts)

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        output_emitter.initialize(
            request_id=utils.shortuuid(),
            sample_rate=self._opts.sample_rate,
            num_channels=1,
            mime_type=_encoding_to_mimetype(self._opts.output_format),
            frame_size_ms=_EMITTER_FRAME_SIZE_MS,
        )
        await _stream_to_emitter(
            tts_provider=self._tts,
            opts=self._opts,
            text=self._input_text,
            prev_text="",
            conn_options=self._conn_options,
            output_emitter=output_emitter,
            metrics_owner=self,
        )
        output_emitter.flush()


class ElevenV3HTTPStreamSynthesizeStream(tts.SynthesizeStream):
    def __init__(
        self,
        *,
        tts: ElevenV3HTTPStreamTTS,
        conn_options: APIConnectOptions,
    ) -> None:
        super().__init__(tts=tts, conn_options=conn_options)
        self._tts = tts
        self._opts = replace(tts._opts)
        self._request_id = utils.shortuuid()

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        segments_ch = utils.aio.Chan[tokenize.SentenceStream]()
        output_emitter.initialize(
            request_id=self._request_id,
            sample_rate=self._opts.sample_rate,
            num_channels=1,
            stream=True,
            mime_type=_encoding_to_mimetype(self._opts.output_format),
            frame_size_ms=_EMITTER_FRAME_SIZE_MS,
        )
        output_emitter.start_segment(segment_id=self._request_id)

        try:

            async def _tokenize_input() -> None:
                input_stream: tokenize.SentenceStream | None = None
                try:
                    async for input_data in self._input_ch:
                        if isinstance(input_data, str):
                            if input_stream is None:
                                input_stream = self._opts.tokenizer.stream()
                                segments_ch.send_nowait(input_stream)
                            input_stream.push_text(input_data)
                        elif isinstance(input_data, self._FlushSentinel):
                            if input_stream is not None:
                                input_stream.end_input()
                            input_stream = None
                finally:
                    if input_stream is not None:
                        input_stream.end_input()
                    segments_ch.close()

            async def _run_segments() -> None:
                async for sentence_stream in segments_ch:
                    await self._run_pipelined_segment(sentence_stream, output_emitter)

            tasks = [
                asyncio.create_task(_tokenize_input()),
                asyncio.create_task(_run_segments()),
            ]
            try:
                await asyncio.gather(*tasks)
            finally:
                await utils.aio.gracefully_cancel(*tasks)
        finally:
            segments_ch.close()
            output_emitter.end_segment()

    async def _run_pipelined_segment(
        self,
        sentence_stream: tokenize.SentenceStream,
        output_emitter: tts.AudioEmitter,
    ) -> None:
        """Pipeline HTTP requests: sentence N+1's request starts while N is streaming.

        Architecture:
          _produce: reads sentences → fires HTTP tasks immediately → enqueues their audio queues
          _consume: drains each audio queue in order → pushes to output_emitter

        This means by the time sentence N finishes playing, sentence N+1's audio is
        already in-flight or fully buffered, cutting perceived inter-sentence latency
        from ~TTFB per sentence to near-zero after the first.
        """
        is_pcm = self._opts.output_format.startswith("pcm")

        # Queue of per-sentence audio buffers, in order.
        # maxsize=_PIPELINE_PREFETCH limits simultaneous in-flight requests.
        ordered: asyncio.Queue[asyncio.Queue | None] = asyncio.Queue(
            maxsize=_PIPELINE_PREFETCH
        )
        fetch_tasks: list[asyncio.Task] = []
        first_error: list[Exception] = []
        found_audio = False

        async def _fetch_one(text: str, prev_text: str, audio_q: asyncio.Queue) -> None:
            try:
                await _stream_to_queue(
                    tts_provider=self._tts,
                    opts=self._opts,
                    text=text,
                    prev_text=prev_text,
                    conn_options=self._conn_options,
                    audio_q=audio_q,
                    metrics_owner=self,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if not first_error:
                    first_error.append(exc)
            finally:
                # Always signal consumer that this sentence is done,
                # even on error, so consumer doesn't block forever.
                await audio_q.put(None)

        async def _produce() -> None:
            prev_text = ""
            min_http_text_len = max(1, self._opts.min_http_text_len)
            max_merged_text_len = max(min_http_text_len, self._opts.max_merged_text_len)
            merge_hold_timeout = max(0.0, self._opts.merge_hold_ms / 1000.0)
            sentence_iter = sentence_stream.__aiter__()
            pending_text: str | None = None

            async def _queue_text(text: str) -> None:
                nonlocal prev_text
                self._mark_started()
                audio_q: asyncio.Queue = asyncio.Queue()
                task = asyncio.create_task(
                    _fetch_one(text=text, prev_text=prev_text, audio_q=audio_q)
                )
                fetch_tasks.append(task)
                # This blocks when _PIPELINE_PREFETCH sentences are already queued,
                # providing backpressure so we don't over-prefetch.
                await ordered.put(audio_q)
                prev_text = text

            def _should_hold(text: str) -> bool:
                if len(text) >= min_http_text_len:
                    return False
                if _is_short_confirmation(text):
                    return False
                return not _STRONG_SENTENCE_END_RE.search(text)

            def _can_merge(left: str, right: str) -> bool:
                if _STRONG_SENTENCE_END_RE.search(left):
                    return False
                merged_candidate = f"{left} {right}".strip()
                return len(merged_candidate) <= max_merged_text_len

            async def _next_sanitized_sentence(
                timeout_seconds: float | None = None,
            ) -> tuple[str | None, bool]:
                while True:
                    try:
                        if timeout_seconds is None:
                            sentence = await sentence_iter.__anext__()
                        else:
                            sentence = await asyncio.wait_for(
                                sentence_iter.__anext__(),
                                timeout=timeout_seconds,
                            )
                    except asyncio.TimeoutError:
                        return None, False
                    except StopAsyncIteration:
                        return None, True

                    raw_text = sentence.token or ""
                    text, skip_reason = _sanitize_outbound_text_segment(raw_text)
                    if skip_reason:
                        logger.debug(
                            "eleven_v3 segment skipped before HTTP pipeline",
                            extra={
                                "skip_reason": skip_reason,
                                "text_len": len(raw_text),
                                "has_prev": bool(prev_text),
                            },
                        )
                        continue
                    return text, False

            stream_ended = False
            while not stream_ended:
                if pending_text is None:
                    text, stream_ended = await _next_sanitized_sentence()
                    if stream_ended:
                        break
                    if text is None:
                        continue
                    if _should_hold(text):
                        pending_text = text
                        continue
                    await _queue_text(text)
                    continue

                text, stream_ended = await _next_sanitized_sentence(
                    timeout_seconds=merge_hold_timeout
                    if merge_hold_timeout > 0
                    else None
                )
                if stream_ended:
                    await _queue_text(pending_text)
                    pending_text = None
                    break
                if text is None:
                    await _queue_text(pending_text)
                    pending_text = None
                    continue
                if _can_merge(pending_text, text):
                    merged_text = f"{pending_text} {text}".strip()
                    logger.debug(
                        "eleven_v3 segment merged before HTTP pipeline",
                        extra={
                            "left_len": len(pending_text),
                            "right_len": len(text),
                            "merged_len": len(merged_text),
                            "hold_ms": self._opts.merge_hold_ms,
                            "has_prev": bool(prev_text),
                        },
                    )
                    if _should_hold(merged_text):
                        pending_text = merged_text
                        continue
                    await _queue_text(merged_text)
                    pending_text = None
                    continue
                await _queue_text(pending_text)
                pending_text = text if _should_hold(text) else None
                if pending_text is None:
                    await _queue_text(text)
            await ordered.put(None)  # sentinel

        async def _consume() -> None:
            nonlocal found_audio
            while True:
                audio_q = await ordered.get()
                if audio_q is None:
                    break
                while True:
                    chunk = await audio_q.get()
                    if chunk is None:
                        break
                    output_emitter.push(chunk)
                    found_audio = True
                # For compressed formats, flush decoder state between independent
                # bitstreams so the next sentence doesn't inherit stale decoder context.
                # PCM has no such state — flush() would be a no-op or introduce gaps.
                if not is_pcm:
                    output_emitter.flush()

        produce_task = asyncio.create_task(_produce())
        consume_task = asyncio.create_task(_consume())
        try:
            await asyncio.gather(produce_task, consume_task)
        finally:
            await utils.aio.cancel_and_wait(produce_task, consume_task, *fetch_tasks)

        if first_error:
            raise first_error[0]

        if not found_audio:
            raise APIStatusError(
                "eleven_v3: no audio returned for segment",
                status_code=502,
                retryable=False,
            )


# ---------------------------------------------------------------------------
# URL / payload helpers
# ---------------------------------------------------------------------------


def _build_stream_url(opts: _TTSOptions) -> str:
    # FIX: Only output_format and enable_logging are valid query params for
    # POST /v1/text-to-speech/{voice_id}/stream.
    # model_id, language_code, apply_text_normalization all belong in the JSON body.
    query: dict[str, str] = {
        "output_format": opts.output_format,
        "enable_logging": str(opts.enable_logging).lower(),
    }
    if is_given(opts.optimize_streaming_latency):
        query["optimize_streaming_latency"] = str(opts.optimize_streaming_latency)

    return (
        f"{opts.base_url}/text-to-speech/{opts.voice_id}/stream"
        f"?{urllib.parse.urlencode(query)}"
    )


def _request_payload(
    opts: _TTSOptions, *, text: str, prev_text: str = ""
) -> dict[str, Any]:
    voice_settings = (
        _strip_nones(dataclasses.asdict(opts.voice_settings))
        if is_given(opts.voice_settings)
        else None
    )

    # FIX: model_id, language_code, and apply_text_normalization are JSON body
    # params — not query params. Sending them as query params caused them to be
    # silently ignored by the API.
    payload: dict[str, Any] = {
        "text": text,
        "model_id": opts.model_id,
        "apply_text_normalization": opts.apply_text_normalization,
    }
    if voice_settings:
        payload["voice_settings"] = voice_settings
    if is_given(opts.language):
        payload["language_code"] = opts.language.language
    # eleven_v3 explicitly rejects previous_text/next_text with 400 "unsupported_model".
    # Only send it for other models that support it.
    if prev_text and opts.model_id != "eleven_v3":
        payload["previous_text"] = prev_text
    return payload


async def _response_text_safe(resp: aiohttp.ClientResponse) -> str:
    try:
        return await resp.text()
    except Exception:
        return "<failed to read response body>"


# ---------------------------------------------------------------------------
# Core HTTP streaming primitives
# ---------------------------------------------------------------------------


async def _do_http_stream(
    *,
    tts_provider: ElevenV3HTTPStreamTTS,
    opts: _TTSOptions,
    text: str,
    prev_text: str,
    conn_options: APIConnectOptions,
    on_chunk: Any,  # tts.AudioEmitter | asyncio.Queue[bytes | None]
    metrics_owner: Any | None = None,
) -> None:
    """Execute one ElevenLabs streaming request and route bytes to *on_chunk*.

    on_chunk may be either an AudioEmitter (calls push()) or an asyncio.Queue
    (puts bytes). Callers must handle the final None sentinel on the queue
    themselves — this function does NOT put the sentinel.
    """
    raw_text = text
    text, skip_reason = _sanitize_outbound_text_segment(raw_text)
    if skip_reason:
        logger.debug(
            "eleven_v3 HTTP stream skipped invalid text segment",
            extra={
                "skip_reason": skip_reason,
                "text_len": len(raw_text),
                "has_prev": bool(prev_text),
            },
        )
        return

    url = _build_stream_url(opts)
    t0 = time.perf_counter()
    first_chunk_at: float | None = None
    chunk_count = 0
    total_bytes = 0
    is_pcm = opts.output_format.startswith("pcm")
    is_queue = isinstance(on_chunk, asyncio.Queue)
    pcm_tail = b""
    connection_reused_hint = tts_provider._connection_reused_hint()
    if metrics_owner is not None:
        metrics_owner._connection_reused = (
            getattr(metrics_owner, "_connection_reused", False)
            or connection_reused_hint
        )

    timeout = aiohttp.ClientTimeout(
        total=None,
        sock_connect=conn_options.timeout,
        sock_read=opts.request_timeout,
    )

    logger.debug(
        "eleven_v3 HTTP stream request started",
        extra={
            "model": opts.model_id,
            "voice_id": opts.voice_id,
            "text_len": len(text),
            "has_prev": bool(prev_text),
        },
    )

    try:
        async with tts_provider._ensure_session().post(
            url,
            headers={AUTHORIZATION_HEADER: opts.api_key},
            json=_request_payload(opts, text=text, prev_text=prev_text),
            timeout=timeout,
        ) as resp:
            if resp.status >= 400:
                body = await _response_text_safe(resp)
                raise APIStatusError(
                    message=f"eleven_v3 HTTP stream failed: {resp.reason}",
                    status_code=resp.status,
                    body={"url": url, "response": body},
                    retryable=resp.status >= 500,
                )

            content_type = resp.content_type or ""
            if not content_type.startswith("audio/"):
                body = await _response_text_safe(resp)
                raise APIError(
                    message="eleven_v3 HTTP stream returned non-audio response",
                    body={"url": url, "content_type": content_type, "response": body},
                )

            async for data in resp.content.iter_any():
                if not data:
                    continue

                if first_chunk_at is None:
                    first_chunk_at = time.perf_counter()
                    logger.info(
                        "eleven_v3 first audio chunk",
                        extra={
                            "ttfb_ms": round((first_chunk_at - t0) * 1000, 1),
                            "text_len": len(text),
                            "model": opts.model_id,
                            "proxy_enabled": bool(tts_provider._http_proxy),
                            "connection_reused_hint": connection_reused_hint,
                        },
                    )

                if is_pcm:
                    payload = pcm_tail + data
                    aligned = len(payload) - (len(payload) % 2)
                    if aligned > 0:
                        chunk = payload[:aligned]
                        if is_queue:
                            await on_chunk.put(chunk)
                        else:
                            on_chunk.push(chunk)
                    pcm_tail = payload[aligned:]
                else:
                    if is_queue:
                        await on_chunk.put(data)
                    else:
                        on_chunk.push(data)

                chunk_count += 1
                total_bytes += len(data)

            if pcm_tail:
                logger.warning(
                    "eleven_v3: dropping unaligned PCM tail byte",
                    extra={"tail_bytes": len(pcm_tail)},
                )

    except asyncio.CancelledError:
        raise
    except asyncio.TimeoutError as exc:
        raise APITimeoutError(
            f"eleven_v3 HTTP stream timed out after {opts.request_timeout}s"
        ) from exc
    except aiohttp.ClientResponseError as exc:
        raise APIStatusError(
            message=exc.message,
            status_code=exc.status,
            request_id=None,
            body=None,
            retryable=exc.status >= 500,
        ) from exc
    except (APIStatusError, APIError):
        raise
    except Exception as exc:
        raise APIConnectionError(
            f"eleven_v3 HTTP stream request failed: {exc}"
        ) from exc
    finally:
        logger.info(
            "eleven_v3 HTTP stream request finished",
            extra={
                "model": opts.model_id,
                "voice_id": opts.voice_id,
                "text_len": len(text),
                "ttfb_ms": (
                    round((first_chunk_at - t0) * 1000, 1)
                    if first_chunk_at is not None
                    else None
                ),
                "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
                "chunk_count": chunk_count,
                "audio_bytes": total_bytes,
                "proxy_enabled": bool(tts_provider._http_proxy),
                "connection_reused_hint": connection_reused_hint,
            },
        )


async def _stream_to_emitter(
    *,
    tts_provider: ElevenV3HTTPStreamTTS,
    opts: _TTSOptions,
    text: str,
    prev_text: str,
    conn_options: APIConnectOptions,
    output_emitter: tts.AudioEmitter,
    metrics_owner: Any | None = None,
) -> None:
    await _do_http_stream(
        tts_provider=tts_provider,
        opts=opts,
        text=text,
        prev_text=prev_text,
        conn_options=conn_options,
        on_chunk=output_emitter,
        metrics_owner=metrics_owner,
    )


async def _stream_to_queue(
    *,
    tts_provider: ElevenV3HTTPStreamTTS,
    opts: _TTSOptions,
    text: str,
    prev_text: str,
    conn_options: APIConnectOptions,
    audio_q: asyncio.Queue,
    metrics_owner: Any | None = None,
) -> None:
    await _do_http_stream(
        tts_provider=tts_provider,
        opts=opts,
        text=text,
        prev_text=prev_text,
        conn_options=conn_options,
        on_chunk=audio_q,
        metrics_owner=metrics_owner,
    )


# Backward-compatible alias for current imports.
ElevenV3TTS = ElevenV3HTTPStreamTTS
