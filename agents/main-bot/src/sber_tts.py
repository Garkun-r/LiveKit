from __future__ import annotations

import asyncio
import html
import logging
import time
import uuid
import weakref
from collections.abc import AsyncIterable, Callable
from dataclasses import dataclass, replace
from typing import Any

import grpc
import httpx
from livekit.agents import (
    APIConnectionError,
    APIConnectOptions,
    APIStatusError,
    APITimeoutError,
    tokenize,
    tts,
    utils,
)
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, NOT_GIVEN, NotGivenOr
from livekit.agents.utils import is_given

from sber_salutespeech_proto.synthesis.v1 import synthesis_pb2 as sber_pb
from sber_salutespeech_proto.synthesis.v1 import synthesis_pb2_grpc as sber_grpc

DEFAULT_SBER_TTS_ENDPOINT = "smartspeech.sber.ru:443"
DEFAULT_SBER_OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
DEFAULT_SBER_OAUTH_SCOPE = "SALUTE_SPEECH_PERS"
DEFAULT_SBER_VOICE = "Ost_24000"
DEFAULT_SBER_LANGUAGE = "ru-RU"
DEFAULT_SBER_SAMPLE_RATE = 24000
_FRAME_SIZE_MS = 20
_TOKEN_REFRESH_MARGIN_SEC = 60.0

logger = logging.getLogger("sber_tts")

SberStreamFactory = Callable[
    [sber_pb.SynthesisRequest, tuple[tuple[str, str], ...], float],
    AsyncIterable[sber_pb.SynthesisResponse],
]


@dataclass
class _SberTTSOptions:
    auth_key: str
    oauth_scope: str
    oauth_url: str
    endpoint: str
    voice: str
    language: str
    sample_rate: int
    paint_pitch: str
    paint_speed: str
    paint_loudness: str
    request_timeout: float
    rebuild_cache: bool
    http_proxy: str | None
    ca_cert_file: str | None
    tokenizer: tokenize.SentenceTokenizer


class _SberTokenManager:
    def __init__(
        self,
        *,
        auth_key: str,
        oauth_scope: str,
        oauth_url: str,
        http_proxy: str | None,
        ca_cert_file: str | None,
    ) -> None:
        self._auth_key = auth_key.strip()
        self._oauth_scope = oauth_scope.strip()
        self._oauth_url = oauth_url.strip()
        self._http_proxy = http_proxy
        self._ca_cert_file = ca_cert_file
        self._token = ""
        self._expires_at_monotonic = 0.0
        self._lock = asyncio.Lock()
        self._client: httpx.AsyncClient | None = None

    async def get_token(self) -> str:
        now = time.monotonic()
        if self._token and now < self._expires_at_monotonic - _TOKEN_REFRESH_MARGIN_SEC:
            return self._token

        async with self._lock:
            now = time.monotonic()
            if (
                self._token
                and now < self._expires_at_monotonic - _TOKEN_REFRESH_MARGIN_SEC
            ):
                return self._token
            await self._refresh()
            return self._token

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def _refresh(self) -> None:
        if not self._auth_key:
            raise APIConnectionError("Sber SaluteSpeech auth key is not configured")
        if not self._oauth_scope:
            raise APIConnectionError("Sber SaluteSpeech OAuth scope is not configured")

        client = self._ensure_client()
        authorization = self._auth_key
        if not authorization.lower().startswith("basic "):
            authorization = f"Basic {authorization}"

        try:
            response = await client.post(
                self._oauth_url,
                headers={
                    "Authorization": authorization,
                    "RqUID": str(uuid.uuid4()),
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"scope": self._oauth_scope},
            )
        except httpx.TimeoutException as exc:
            raise APITimeoutError("Sber SaluteSpeech OAuth request timed out") from exc
        except httpx.HTTPError as exc:
            raise APIConnectionError("Sber SaluteSpeech OAuth request failed") from exc

        if response.status_code >= 400:
            raise APIStatusError(
                message="Sber SaluteSpeech OAuth request failed",
                status_code=response.status_code,
                body={"response": response.text[:500]},
                retryable=response.status_code >= 500,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise APIConnectionError("Sber SaluteSpeech OAuth returned invalid JSON") from exc

        token = str(payload.get("access_token") or "").strip()
        if not token:
            raise APIConnectionError("Sber SaluteSpeech OAuth response has no access_token")

        self._token = token
        self._expires_at_monotonic = _expires_at_monotonic(payload.get("expires_at"))

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(10.0, connect=5.0),
                trust_env=False,
                proxy=self._http_proxy,
                verify=self._ca_cert_file or True,
            )
        return self._client


class SberSaluteTTS(tts.TTS):
    def __init__(
        self,
        *,
        auth_key: str,
        oauth_scope: str = DEFAULT_SBER_OAUTH_SCOPE,
        oauth_url: str = DEFAULT_SBER_OAUTH_URL,
        endpoint: str = DEFAULT_SBER_TTS_ENDPOINT,
        voice: str = DEFAULT_SBER_VOICE,
        language: str = DEFAULT_SBER_LANGUAGE,
        sample_rate: int = DEFAULT_SBER_SAMPLE_RATE,
        paint_pitch: str = "2",
        paint_speed: str = "4",
        paint_loudness: str = "5",
        request_timeout: float = 15.0,
        rebuild_cache: bool = False,
        http_proxy: str | None = None,
        ca_cert_file: str | None = None,
        tokenizer_obj: NotGivenOr[tokenize.SentenceTokenizer] = NOT_GIVEN,
        stream_factory: SberStreamFactory | None = None,
    ) -> None:
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if request_timeout <= 0:
            raise ValueError("request_timeout must be positive")

        super().__init__(
            capabilities=tts.TTSCapabilities(
                streaming=True,
                aligned_transcript=False,
            ),
            sample_rate=sample_rate,
            num_channels=1,
        )

        if not is_given(tokenizer_obj):
            tokenizer_obj = tokenize.blingfire.SentenceTokenizer(
                min_sentence_len=4,
                stream_context_len=1,
            )

        self._opts = _SberTTSOptions(
            auth_key=auth_key,
            oauth_scope=oauth_scope,
            oauth_url=oauth_url,
            endpoint=endpoint,
            voice=voice,
            language=language,
            sample_rate=sample_rate,
            paint_pitch=str(paint_pitch),
            paint_speed=str(paint_speed),
            paint_loudness=str(paint_loudness),
            request_timeout=request_timeout,
            rebuild_cache=rebuild_cache,
            http_proxy=http_proxy,
            ca_cert_file=ca_cert_file,
            tokenizer=tokenizer_obj,
        )
        self._stream_factory = stream_factory
        self._token_manager = (
            None
            if stream_factory is not None and not auth_key.strip()
            else _SberTokenManager(
                auth_key=auth_key,
                oauth_scope=oauth_scope,
                oauth_url=oauth_url,
                http_proxy=http_proxy,
                ca_cert_file=ca_cert_file,
            )
        )
        self._channel: grpc.aio.Channel | None = None
        self._stub: sber_grpc.SmartSpeechStub | None = None
        if stream_factory is None:
            self._channel = grpc.aio.secure_channel(
                endpoint,
                _ssl_channel_credentials(ca_cert_file),
            )
            self._stub = sber_grpc.SmartSpeechStub(self._channel)
        self._streams = weakref.WeakSet[_SberSynthesizeStream]()

    @property
    def model(self) -> str:
        return self._opts.voice

    @property
    def provider(self) -> str:
        return "sber-salutespeech"

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
        stream = _SberSynthesizeStream(tts_obj=self, conn_options=conn_options)
        self._streams.add(stream)
        return stream

    async def _synthesize_stream(
        self,
        request: sber_pb.SynthesisRequest,
        *,
        timeout: float,
    ) -> AsyncIterable[sber_pb.SynthesisResponse]:
        metadata = await self._metadata()
        if self._stream_factory is not None:
            return self._stream_factory(request, metadata, timeout)
        if self._stub is None:
            raise APIConnectionError("Sber SaluteSpeech gRPC stub is not available")
        return self._stub.Synthesize(
            request,
            metadata=metadata,
            timeout=timeout,
        )

    async def _metadata(self) -> tuple[tuple[str, str], ...]:
        if self._token_manager is None:
            return ()
        token = await self._token_manager.get_token()
        return (("authorization", f"Bearer {token}"),)

    async def aclose(self) -> None:
        await asyncio.gather(
            *(stream.aclose() for stream in list(self._streams)),
            return_exceptions=True,
        )
        if self._token_manager is not None:
            await self._token_manager.aclose()
        if self._channel is not None:
            await self._channel.close()


class _SberSynthesizeStream(tts.SynthesizeStream):
    def __init__(
        self,
        *,
        tts_obj: SberSaluteTTS,
        conn_options: APIConnectOptions,
    ) -> None:
        super().__init__(tts=tts_obj, conn_options=conn_options)
        self._tts: SberSaluteTTS = tts_obj
        self._opts = replace(tts_obj._opts)

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        segments_ch = utils.aio.Chan[tokenize.SentenceStream]()
        output_emitter.initialize(
            request_id=utils.shortuuid(),
            sample_rate=self._opts.sample_rate,
            num_channels=1,
            mime_type="audio/pcm",
            frame_size_ms=_FRAME_SIZE_MS,
            stream=True,
        )

        async def _tokenize_input() -> None:
            input_stream: tokenize.SentenceStream | None = None
            try:
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
            finally:
                if input_stream is not None:
                    input_stream.end_input()
                segments_ch.close()

        async def _run_segments() -> None:
            async for sentence_stream in segments_ch:
                output_emitter.start_segment(segment_id=utils.shortuuid())
                try:
                    await self._run_segment(sentence_stream, output_emitter)
                finally:
                    output_emitter.end_segment()

        tasks = [
            asyncio.create_task(_tokenize_input(), name="sber_tts_tokenize_input"),
            asyncio.create_task(_run_segments(), name="sber_tts_run_segments"),
        ]
        try:
            await asyncio.gather(*tasks)
        finally:
            await utils.aio.gracefully_cancel(*tasks)

    async def _run_segment(
        self,
        sentence_stream: tokenize.SentenceStream,
        output_emitter: tts.AudioEmitter,
    ) -> None:
        seen_text = False
        found_audio = False

        async for sentence in sentence_stream:
            text = _clean_text(sentence.token or "")
            if not text:
                continue

            seen_text = True
            sentence_has_audio = await self._synthesize_sentence(
                text=text,
                output_emitter=output_emitter,
            )
            found_audio = found_audio or sentence_has_audio

        if seen_text and not found_audio:
            raise APIStatusError(
                "Sber SaluteSpeech returned no audio for the segment",
                status_code=502,
                retryable=False,
            )

    async def _synthesize_sentence(
        self,
        *,
        text: str,
        output_emitter: tts.AudioEmitter,
    ) -> bool:
        request = sber_pb.SynthesisRequest(
            text=_build_ssml(text, self._opts),
            audio_encoding=sber_pb.SynthesisRequest.PCM_S16LE,
            language=self._opts.language,
            content_type=sber_pb.SynthesisRequest.SSML,
            voice=self._opts.voice,
            rebuild_cache=self._opts.rebuild_cache,
        )
        timeout = min(self._opts.request_timeout, self._conn_options.timeout)
        started_at = time.perf_counter()
        first_chunk_at: float | None = None
        total_bytes = 0
        pcm_tail = b""

        logger.debug(
            "Sber SaluteSpeech request started",
            extra={
                "voice": self._opts.voice,
                "text_len": len(text),
                "sample_rate": self._opts.sample_rate,
            },
        )

        try:
            self._mark_started()
            async with asyncio.timeout(timeout):
                responses = await self._tts._synthesize_stream(
                    request,
                    timeout=timeout,
                )
                async for response in responses:
                    chunk = bytes(response.data or b"")
                    if not chunk:
                        continue
                    if first_chunk_at is None:
                        first_chunk_at = time.perf_counter()
                        logger.info(
                            "Sber SaluteSpeech first audio chunk",
                            extra={
                                "ttfb_ms": round(
                                    (first_chunk_at - started_at) * 1000,
                                    1,
                                ),
                                "text_len": len(text),
                                "voice": self._opts.voice,
                            },
                        )
                    payload = pcm_tail + chunk
                    aligned = len(payload) - (len(payload) % 2)
                    if aligned:
                        output_emitter.push(payload[:aligned])
                    pcm_tail = payload[aligned:]
                    total_bytes += len(chunk)
        except TimeoutError as exc:
            raise APITimeoutError("Sber SaluteSpeech synthesis timed out") from exc
        except grpc.aio.AioRpcError as exc:
            raise _grpc_error_to_livekit_error(exc) from exc
        except (APIConnectionError, APIStatusError, APITimeoutError):
            raise
        except Exception as exc:
            raise APIConnectionError("Sber SaluteSpeech synthesis failed") from exc

        if pcm_tail:
            logger.warning(
                "Sber SaluteSpeech returned unaligned PCM tail byte",
                extra={"tail_bytes": len(pcm_tail)},
            )
        return total_bytes > 0


def _build_ssml(text: str, opts: _SberTTSOptions) -> str:
    escaped = html.escape(text, quote=False)
    pitch = html.escape(opts.paint_pitch, quote=True)
    speed = html.escape(opts.paint_speed, quote=True)
    loudness = html.escape(opts.paint_loudness, quote=True)
    return (
        "<speak>"
        f'<paint pitch="{pitch}" speed="{speed}" loudness="{loudness}">'
        f"{escaped}"
        "</paint>"
        "</speak>"
    )


def _clean_text(text: str) -> str:
    cleaned = " ".join(text.split())
    if not cleaned:
        return ""
    if not any(ch.isalnum() for ch in cleaned):
        return ""
    return cleaned


def _expires_at_monotonic(raw_expires_at: Any) -> float:
    now_monotonic = time.monotonic()
    now_epoch = time.time()
    try:
        value = float(raw_expires_at)
    except (TypeError, ValueError):
        return now_monotonic + 20 * 60

    if value > 10_000_000_000:
        expires_epoch = value / 1000.0
    elif value > 1_000_000_000:
        expires_epoch = value
    else:
        return now_monotonic + max(60.0, value)

    return now_monotonic + max(60.0, expires_epoch - now_epoch)


def _ssl_channel_credentials(ca_cert_file: str | None) -> grpc.ChannelCredentials:
    if not ca_cert_file:
        return grpc.ssl_channel_credentials()
    try:
        with open(ca_cert_file, "rb") as cert_file:
            root_certificates = cert_file.read()
    except OSError as exc:
        raise ValueError(f"Sber SaluteSpeech CA cert file is unreadable: {ca_cert_file}") from exc
    return grpc.ssl_channel_credentials(root_certificates=root_certificates)


def _grpc_error_to_livekit_error(error: grpc.aio.AioRpcError) -> Exception:
    code = error.code()
    details = error.details() or code.name
    if code == grpc.StatusCode.DEADLINE_EXCEEDED:
        return APITimeoutError(details)
    if code in {
        grpc.StatusCode.UNAVAILABLE,
        grpc.StatusCode.RESOURCE_EXHAUSTED,
        grpc.StatusCode.CANCELLED,
        grpc.StatusCode.UNKNOWN,
    }:
        return APIConnectionError(details)
    status_code = int(code.value[0]) if isinstance(code.value, tuple) else -1
    return APIStatusError(
        message=details,
        status_code=status_code,
        request_id=None,
        body=None,
    )
