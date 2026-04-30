from __future__ import annotations

import asyncio
import logging
import re
import time
import weakref
from collections.abc import AsyncIterable, Callable
from dataclasses import dataclass, replace

import grpc
from livekit.agents import (
    APIConnectionError,
    APIConnectOptions,
    APIStatusError,
    APITimeoutError,
    tokenize,
    tts,
    utils,
)
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS

from tbank_auth import VoiceKitAuth
from tinkoff.cloud.tts.v1 import tts_pb2 as tbank_tts_pb

DEFAULT_TBANK_VOICEKIT_ENDPOINT = "api.tinkoff.ai:443"
TBANK_TTS_SCOPE = "tinkoff.cloud.tts"
_STREAMING_SYNTHESIZE_PATH = (
    "/tinkoff.cloud.tts.v1.TextToSpeech/StreamingSynthesize"
)
_EMITTER_FRAME_SIZE_MS = 20
_ALNUM_RE = re.compile(r"\w", flags=re.UNICODE)

logger = logging.getLogger("tbank_tts")

SynthesizeStreamFactory = Callable[
    [tbank_tts_pb.SynthesizeSpeechRequest, tuple[tuple[str, str], ...]],
    AsyncIterable[tbank_tts_pb.StreamingSynthesizeSpeechResponse],
]


@dataclass
class TBankTTSOptions:
    api_key: str
    secret_key: str
    voice_name: str = "anna"
    audio_format: str = "linear16"
    sample_rate: int = 24000
    speaking_rate: float = 1.0
    pitch: float = 0.8
    endpoint: str = DEFAULT_TBANK_VOICEKIT_ENDPOINT
    authority: str = ""
    tokenizer: tokenize.SentenceTokenizer | None = None


class TBankVoiceKitTTS(tts.TTS):
    def __init__(
        self,
        *,
        api_key: str,
        secret_key: str,
        voice_name: str = "anna",
        audio_format: str = "linear16",
        sample_rate: int = 24000,
        speaking_rate: float = 1.0,
        pitch: float = 0.8,
        endpoint: str = DEFAULT_TBANK_VOICEKIT_ENDPOINT,
        authority: str = "",
        tokenizer_obj: tokenize.SentenceTokenizer | None = None,
        synthesize_stream_factory: SynthesizeStreamFactory | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("T-Bank VoiceKit API key is required")
        if not secret_key.strip():
            raise ValueError("T-Bank VoiceKit secret key is required")
        if not voice_name.strip():
            raise ValueError("voice_name is required")
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        _validate_rate("speaking_rate", speaking_rate)
        _validate_rate("pitch", pitch)
        _audio_encoding(audio_format)

        super().__init__(
            capabilities=tts.TTSCapabilities(
                streaming=True,
                aligned_transcript=False,
            ),
            sample_rate=sample_rate,
            num_channels=1,
        )
        self._opts = TBankTTSOptions(
            api_key=api_key,
            secret_key=secret_key,
            voice_name=voice_name,
            audio_format=audio_format,
            sample_rate=sample_rate,
            speaking_rate=speaking_rate,
            pitch=pitch,
            endpoint=endpoint,
            authority=authority.strip(),
            tokenizer=tokenizer_obj or tokenize.blingfire.SentenceTokenizer(),
        )
        self._auth = VoiceKitAuth(api_key=api_key, secret_key=secret_key)
        self._synthesize_stream_factory = synthesize_stream_factory
        self._channel: grpc.aio.Channel | None = None
        if synthesize_stream_factory is None:
            self._channel = grpc.aio.secure_channel(
                endpoint,
                grpc.ssl_channel_credentials(),
                options=_grpc_channel_options(self._opts.authority),
            )
        self._streams = weakref.WeakSet[TBankSynthesizeStream]()

    @property
    def model(self) -> str:
        return self._opts.voice_name

    @property
    def provider(self) -> str:
        return "T-Bank VoiceKit"

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> tts.ChunkedStream:
        return TBankChunkedStream(
            tts=self,
            input_text=text,
            conn_options=conn_options,
        )

    def stream(
        self,
        *,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> tts.SynthesizeStream:
        stream = TBankSynthesizeStream(tts=self, conn_options=conn_options)
        self._streams.add(stream)
        return stream

    def _streaming_synthesize(
        self,
        request: tbank_tts_pb.SynthesizeSpeechRequest,
        *,
        metadata: tuple[tuple[str, str], ...],
    ) -> AsyncIterable[tbank_tts_pb.StreamingSynthesizeSpeechResponse]:
        if self._synthesize_stream_factory is not None:
            return self._synthesize_stream_factory(request, metadata)
        if self._channel is None:
            raise APIConnectionError("T-Bank VoiceKit channel is not available")
        method = self._channel.unary_stream(
            _STREAMING_SYNTHESIZE_PATH,
            request_serializer=tbank_tts_pb.SynthesizeSpeechRequest.SerializeToString,
            response_deserializer=(
                tbank_tts_pb.StreamingSynthesizeSpeechResponse.FromString
            ),
        )
        return method(request, metadata=metadata)

    def _authorization_metadata(self) -> tuple[tuple[str, str], ...]:
        return self._auth.authorization_metadata(TBANK_TTS_SCOPE)

    async def aclose(self) -> None:
        await asyncio.gather(
            *(stream.aclose() for stream in list(self._streams)),
            return_exceptions=True,
        )
        self._streams.clear()
        if self._channel is not None:
            await self._channel.close()


class TBankChunkedStream(tts.ChunkedStream):
    def __init__(
        self,
        *,
        tts: TBankVoiceKitTTS,
        input_text: str,
        conn_options: APIConnectOptions,
    ) -> None:
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._tts = tts
        self._opts = replace(tts._opts)
        self._request_id = utils.shortuuid()

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        output_emitter.initialize(
            request_id=self._request_id,
            sample_rate=self._opts.sample_rate,
            num_channels=1,
            mime_type=_mime_type(self._opts.audio_format),
            frame_size_ms=_EMITTER_FRAME_SIZE_MS,
        )
        await _stream_segment_to_emitter(
            tts_provider=self._tts,
            opts=self._opts,
            text=self._input_text,
            conn_options=self._conn_options,
            output_emitter=output_emitter,
        )
        output_emitter.flush()


class TBankSynthesizeStream(tts.SynthesizeStream):
    def __init__(
        self,
        *,
        tts: TBankVoiceKitTTS,
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
            mime_type=_mime_type(self._opts.audio_format),
            frame_size_ms=_EMITTER_FRAME_SIZE_MS,
        )

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
                    await self._run_sentence_stream(sentence_stream, output_emitter)

            tasks = [
                asyncio.create_task(_tokenize_input(), name="tbank_tts_tokenize"),
                asyncio.create_task(_run_segments(), name="tbank_tts_segments"),
            ]
            try:
                await asyncio.gather(*tasks)
            finally:
                await utils.aio.gracefully_cancel(*tasks)
        finally:
            segments_ch.close()

    async def _run_sentence_stream(
        self,
        sentence_stream: tokenize.SentenceStream,
        output_emitter: tts.AudioEmitter,
    ) -> None:
        segment_started = False
        async for sentence in sentence_stream:
            text = _sanitize_text_segment(sentence.token or "")
            if not text:
                continue

            self._mark_started()
            if not segment_started:
                output_emitter.start_segment(segment_id=utils.shortuuid())
                segment_started = True
            await _stream_segment_to_emitter(
                tts_provider=self._tts,
                opts=self._opts,
                text=text,
                conn_options=self._conn_options,
                output_emitter=output_emitter,
            )
            output_emitter.flush()

        if segment_started:
            try:
                output_emitter.flush()
            finally:
                output_emitter.end_segment()


def build_tbank_tts_request(
    *,
    text: str,
    opts: TBankTTSOptions,
) -> tbank_tts_pb.SynthesizeSpeechRequest:
    return tbank_tts_pb.SynthesizeSpeechRequest(
        input=tbank_tts_pb.SynthesisInput(text=text),
        voice=tbank_tts_pb.VoiceSelectionParams(name=opts.voice_name),
        audio_config=tbank_tts_pb.AudioConfig(
            audio_encoding=_audio_encoding(opts.audio_format),
            sample_rate_hertz=opts.sample_rate,
            speaking_rate=opts.speaking_rate,
            pitch=opts.pitch,
        ),
    )


async def _stream_segment_to_emitter(
    *,
    tts_provider: TBankVoiceKitTTS,
    opts: TBankTTSOptions,
    text: str,
    conn_options: APIConnectOptions,
    output_emitter: tts.AudioEmitter,
) -> None:
    sanitized = _sanitize_text_segment(text)
    if not sanitized:
        return

    request = build_tbank_tts_request(text=sanitized, opts=opts)
    metadata = tts_provider._authorization_metadata()
    started_at = time.perf_counter()
    first_chunk_at: float | None = None
    chunk_count = 0
    total_bytes = 0
    try:
        responses = tts_provider._streaming_synthesize(request, metadata=metadata)
        for_audio = responses.__aiter__()
        while True:
            try:
                response = await asyncio.wait_for(
                    for_audio.__anext__(),
                    timeout=conn_options.timeout,
                )
            except StopAsyncIteration:
                break

            chunk = response.audio_chunk
            if not chunk:
                continue
            if first_chunk_at is None:
                first_chunk_at = time.perf_counter()
                logger.info(
                    "tbank_tts first audio chunk",
                    extra={
                        "ttfb_ms": round((first_chunk_at - started_at) * 1000, 1),
                        "voice": opts.voice_name,
                        "text_len": len(sanitized),
                    },
                )
            output_emitter.push(chunk)
            chunk_count += 1
            total_bytes += len(chunk)

        if total_bytes <= 0 and sanitized:
            raise APIStatusError(
                "T-Bank VoiceKit TTS returned no audio",
                status_code=502,
                retryable=False,
            )
    except asyncio.TimeoutError as e:
        raise APITimeoutError("T-Bank VoiceKit TTS stream timed out") from e
    except grpc.aio.AioRpcError as e:
        raise _grpc_error_to_livekit_error(e) from e
    except (APIConnectionError, APIStatusError, APITimeoutError):
        raise
    except Exception as e:
        raise APIConnectionError("T-Bank VoiceKit TTS stream failed") from e
    finally:
        logger.info(
            "tbank_tts stream finished",
            extra={
                "voice": opts.voice_name,
                "text_len": len(sanitized),
                "ttfb_ms": (
                    round((first_chunk_at - started_at) * 1000, 1)
                    if first_chunk_at is not None
                    else None
                ),
                "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 1),
                "chunk_count": chunk_count,
                "audio_bytes": total_bytes,
            },
        )


def _audio_encoding(audio_format: str) -> int:
    normalized = audio_format.strip().lower()
    if normalized in {"linear16", "pcm", "lpcm"}:
        return tbank_tts_pb.LINEAR16
    if normalized in {"alaw", "a-law"}:
        return tbank_tts_pb.ALAW
    if normalized in {"raw_opus", "opus"}:
        return tbank_tts_pb.RAW_OPUS
    raise ValueError(f"Unsupported T-Bank VoiceKit TTS format: {audio_format}")


def _mime_type(audio_format: str) -> str:
    normalized = audio_format.strip().lower()
    if normalized in {"linear16", "pcm", "lpcm"}:
        return "audio/pcm"
    if normalized in {"alaw", "a-law"}:
        return "audio/pcma"
    if normalized in {"raw_opus", "opus"}:
        return "audio/opus"
    raise ValueError(f"Unsupported T-Bank VoiceKit TTS format: {audio_format}")


def _sanitize_text_segment(text: str) -> str:
    stripped = " ".join((text or "").split())
    if not stripped or not _ALNUM_RE.search(stripped):
        return ""
    return stripped


def _validate_rate(name: str, value: float) -> None:
    if not (0.33 <= value <= 3.0):
        raise ValueError(f"{name} must be in range [0.33, 3.0]")


def _grpc_channel_options(authority: str) -> tuple[tuple[str, str], ...]:
    if not authority:
        return ()
    return (
        ("grpc.ssl_target_name_override", authority),
        ("grpc.default_authority", authority),
    )


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
