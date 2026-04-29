from __future__ import annotations

import asyncio
import logging
import time
import weakref
from collections.abc import AsyncIterable, Callable
from dataclasses import dataclass
from typing import Any

import grpc
from livekit import rtc
from livekit.agents import (
    DEFAULT_API_CONNECT_OPTIONS,
    APIConnectionError,
    APIConnectOptions,
    APIStatusError,
    APITimeoutError,
    LanguageCode,
    stt,
    utils,
)
from livekit.agents.types import NOT_GIVEN, NotGivenOr
from livekit.agents.utils import AudioBuffer, is_given
from livekit.agents.voice.io import TimedString

from tbank_auth import VoiceKitAuth
from tinkoff.cloud.stt.v1 import stt_pb2 as tbank_stt_pb

DEFAULT_TBANK_VOICEKIT_ENDPOINT = "api.tinkoff.ai:443"
TBANK_STT_SCOPE = "tinkoff.cloud.stt"
_STREAMING_RECOGNIZE_PATH = (
    "/tinkoff.cloud.stt.v1.SpeechToText/StreamingRecognize"
)

logger = logging.getLogger("tbank_stt")

RecognizeStreamFactory = Callable[
    [
        AsyncIterable[tbank_stt_pb.StreamingRecognizeRequest],
        tuple[tuple[str, str], ...],
    ],
    AsyncIterable[tbank_stt_pb.StreamingRecognizeResponse],
]


@dataclass
class TBankSTTOptions:
    api_key: str
    secret_key: str
    model: str = ""
    language: str = "ru-RU"
    sample_rate: int = 16000
    chunk_ms: int = 50
    interim_interval_sec: float = 0.1
    endpoint: str = DEFAULT_TBANK_VOICEKIT_ENDPOINT
    authority: str = ""
    max_alternatives: int = 1
    enable_automatic_punctuation: bool = True
    enable_denormalization: bool = False


class TBankVoiceKitSTT(stt.STT):
    def __init__(
        self,
        *,
        api_key: str,
        secret_key: str,
        model: str = "",
        language: str = "ru-RU",
        sample_rate: int = 16000,
        chunk_ms: int = 50,
        interim_interval_sec: float = 0.1,
        endpoint: str = DEFAULT_TBANK_VOICEKIT_ENDPOINT,
        authority: str = "",
        recognize_stream_factory: RecognizeStreamFactory | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("T-Bank VoiceKit API key is required")
        if not secret_key.strip():
            raise ValueError("T-Bank VoiceKit secret key is required")
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if chunk_ms <= 0:
            raise ValueError("chunk_ms must be positive")
        if interim_interval_sec <= 0:
            raise ValueError("interim_interval_sec must be positive")

        super().__init__(
            capabilities=stt.STTCapabilities(
                streaming=True,
                interim_results=True,
                offline_recognize=False,
            )
        )
        self._opts = TBankSTTOptions(
            api_key=api_key,
            secret_key=secret_key,
            model=model,
            language=language,
            sample_rate=sample_rate,
            chunk_ms=chunk_ms,
            interim_interval_sec=interim_interval_sec,
            endpoint=endpoint,
            authority=authority.strip(),
        )
        self._auth = VoiceKitAuth(api_key=api_key, secret_key=secret_key)
        self._recognize_stream_factory = recognize_stream_factory
        self._channel: grpc.aio.Channel | None = None
        if recognize_stream_factory is None:
            self._channel = grpc.aio.secure_channel(
                endpoint,
                grpc.ssl_channel_credentials(),
                options=_grpc_channel_options(self._opts.authority),
            )
        self._streams = weakref.WeakSet[TBankSpeechStream]()

    @property
    def model(self) -> str:
        return self._opts.model or "default"

    @property
    def provider(self) -> str:
        return "T-Bank VoiceKit"

    async def _recognize_impl(
        self,
        buffer: AudioBuffer,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions,
    ) -> stt.SpeechEvent:
        raise NotImplementedError("T-Bank VoiceKit STT supports streaming only")

    def stream(
        self,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> TBankSpeechStream:
        opts = TBankSTTOptions(**self._opts.__dict__)
        if is_given(language):
            opts.language = language
        stream = TBankSpeechStream(
            stt_obj=self,
            opts=opts,
            conn_options=conn_options,
        )
        self._streams.add(stream)
        return stream

    def _recognize_stream(
        self,
        requests: AsyncIterable[tbank_stt_pb.StreamingRecognizeRequest],
        *,
        metadata: tuple[tuple[str, str], ...],
    ) -> AsyncIterable[tbank_stt_pb.StreamingRecognizeResponse]:
        if self._recognize_stream_factory is not None:
            return self._recognize_stream_factory(requests, metadata)
        if self._channel is None:
            raise APIConnectionError("T-Bank VoiceKit channel is not available")
        method = self._channel.stream_stream(
            _STREAMING_RECOGNIZE_PATH,
            request_serializer=tbank_stt_pb.StreamingRecognizeRequest.SerializeToString,
            response_deserializer=tbank_stt_pb.StreamingRecognizeResponse.FromString,
        )
        return method(requests, metadata=metadata)

    def _authorization_metadata(self) -> tuple[tuple[str, str], ...]:
        return self._auth.authorization_metadata(TBANK_STT_SCOPE)

    async def aclose(self) -> None:
        await asyncio.gather(
            *(stream.aclose() for stream in list(self._streams)),
            return_exceptions=True,
        )
        if self._channel is not None:
            await self._channel.close()


class TBankSpeechStream(stt.SpeechStream):
    def __init__(
        self,
        *,
        stt_obj: TBankVoiceKitSTT,
        opts: TBankSTTOptions,
        conn_options: APIConnectOptions,
    ) -> None:
        super().__init__(
            stt=stt_obj,
            conn_options=conn_options,
            sample_rate=opts.sample_rate,
        )
        self._stt: TBankVoiceKitSTT = stt_obj
        self._opts = opts
        self._request_id = utils.shortuuid()
        self._speaking = False

    async def _run(self) -> None:
        metadata = self._stt._authorization_metadata()
        call: Any | None = None
        try:
            started_at = time.perf_counter()
            call = self._stt._recognize_stream(
                self._request_generator(),
                metadata=metadata,
            )
            self._report_connection_acquired(time.perf_counter() - started_at, False)
            async for response in call:
                self._process_response(response)
        except asyncio.CancelledError:
            if call is not None and hasattr(call, "cancel"):
                call.cancel()
            raise
        except asyncio.TimeoutError as e:
            if call is not None and hasattr(call, "cancel"):
                call.cancel()
            raise APITimeoutError() from e
        except grpc.aio.AioRpcError as e:
            raise _grpc_error_to_livekit_error(e) from e
        except APIConnectionError:
            raise
        except Exception as e:
            if call is not None and hasattr(call, "cancel"):
                call.cancel()
            raise APIConnectionError("T-Bank VoiceKit STT stream failed") from e

    async def _request_generator(
        self,
    ) -> AsyncIterable[tbank_stt_pb.StreamingRecognizeRequest]:
        yield tbank_stt_pb.StreamingRecognizeRequest(
            streaming_config=build_tbank_streaming_config(self._opts)
        )

        samples_per_channel = max(1, self._opts.sample_rate * self._opts.chunk_ms // 1000)
        audio_bstream = utils.audio.AudioByteStream(
            sample_rate=self._opts.sample_rate,
            num_channels=1,
            samples_per_channel=samples_per_channel,
        )

        async for data in self._input_ch:
            frames: list[rtc.AudioFrame] = []
            if isinstance(data, rtc.AudioFrame):
                frames.extend(audio_bstream.write(data.data.tobytes()))
            elif isinstance(data, self._FlushSentinel):
                frames.extend(audio_bstream.flush())

            for frame in frames:
                yield tbank_stt_pb.StreamingRecognizeRequest(
                    audio_content=frame.data.tobytes()
                )

    def _process_response(
        self,
        response: tbank_stt_pb.StreamingRecognizeResponse,
    ) -> None:
        for result in response.results:
            recognition = result.recognition_result
            alternatives = _alternatives_to_speech_data(
                recognition.alternatives,
                default_language=self._opts.language,
                start_time_offset=self.start_time_offset,
                start_time=recognition.start_time,
                end_time=recognition.end_time,
            )
            if not alternatives:
                continue

            if not self._speaking:
                self._speaking = True
                self._event_ch.send_nowait(
                    stt.SpeechEvent(type=stt.SpeechEventType.START_OF_SPEECH)
                )

            event_type = (
                stt.SpeechEventType.FINAL_TRANSCRIPT
                if result.is_final
                else stt.SpeechEventType.INTERIM_TRANSCRIPT
            )
            self._event_ch.send_nowait(
                stt.SpeechEvent(
                    type=event_type,
                    request_id=self._request_id,
                    alternatives=alternatives,
                )
            )

            if result.is_final:
                self._speaking = False
                self._event_ch.send_nowait(
                    stt.SpeechEvent(
                        type=stt.SpeechEventType.END_OF_SPEECH,
                        request_id=self._request_id,
                    )
                )


def build_tbank_streaming_config(
    opts: TBankSTTOptions,
) -> tbank_stt_pb.StreamingRecognitionConfig:
    return tbank_stt_pb.StreamingRecognitionConfig(
        config=tbank_stt_pb.RecognitionConfig(
            encoding=tbank_stt_pb.LINEAR16,
            sample_rate_hertz=opts.sample_rate,
            language_code=opts.language,
            max_alternatives=opts.max_alternatives,
            enable_automatic_punctuation=opts.enable_automatic_punctuation,
            model=opts.model,
            num_channels=1,
            enable_denormalization=opts.enable_denormalization,
        ),
        single_utterance=False,
        interim_results_config=tbank_stt_pb.InterimResultsConfig(
            enable_interim_results=True,
            interval=opts.interim_interval_sec,
        ),
    )


def _alternatives_to_speech_data(
    alternatives: Any,
    *,
    default_language: str,
    start_time_offset: float,
    start_time: Any,
    end_time: Any,
) -> list[stt.SpeechData]:
    speech_data: list[stt.SpeechData] = []
    start_seconds = _duration_to_seconds(start_time) + start_time_offset
    end_seconds = _duration_to_seconds(end_time) + start_time_offset
    for alternative in alternatives:
        text = (alternative.transcript or "").strip()
        if not text and alternative.words:
            text = " ".join(word.word for word in alternative.words).strip()
        if not text:
            continue

        words = [
            TimedString(
                text=word.word,
                start_time=_duration_to_seconds(word.start_time) + start_time_offset,
                end_time=_duration_to_seconds(word.end_time) + start_time_offset,
                start_time_offset=start_time_offset,
            )
            for word in alternative.words
            if word.word
        ]
        speech_data.append(
            stt.SpeechData(
                language=LanguageCode(default_language),
                text=text,
                start_time=start_seconds,
                end_time=end_seconds,
                confidence=float(alternative.confidence or 0.0),
                words=words or None,
            )
        )
    return speech_data


def _duration_to_seconds(duration: Any) -> float:
    return float(getattr(duration, "seconds", 0)) + float(
        getattr(duration, "nanos", 0)
    ) / 1_000_000_000.0


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
