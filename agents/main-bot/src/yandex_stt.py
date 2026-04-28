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

from yandex_speechkit_proto import yandex_stt_pb2 as yandex_pb

DEFAULT_YANDEX_STT_ENDPOINT = "stt.api.cloud.yandex.net:443"
_RECOGNIZE_STREAMING_PATH = "/speechkit.stt.v3.Recognizer/RecognizeStreaming"
_RENEW_AFTER_AUDIO_MS = 280_000
_RENEW_AFTER_BYTES = 9_500_000
_MIN_EOU_PAUSE_HINT_MS = 500
_MAX_EOU_PAUSE_HINT_MS = 5000
logger = logging.getLogger("yandex_stt")

RecognizeStreamFactory = Callable[
    [AsyncIterable[yandex_pb.StreamingRequest], tuple[tuple[str, str], ...]],
    AsyncIterable[yandex_pb.StreamingResponse],
]


@dataclass
class YandexSTTOptions:
    api_key: str
    model: str = "general"
    language: str = "ru-RU"
    sample_rate: int = 16000
    chunk_ms: int = 50
    eou_sensitivity: str = "high"
    max_pause_between_words_hint_ms: int = _MIN_EOU_PAUSE_HINT_MS
    endpoint: str = DEFAULT_YANDEX_STT_ENDPOINT


class YandexSpeechKitSTT(stt.STT):
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "general",
        language: str = "ru-RU",
        sample_rate: int = 16000,
        chunk_ms: int = 50,
        eou_sensitivity: str = "high",
        max_pause_between_words_hint_ms: int = _MIN_EOU_PAUSE_HINT_MS,
        endpoint: str = DEFAULT_YANDEX_STT_ENDPOINT,
        recognize_stream_factory: RecognizeStreamFactory | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Yandex SpeechKit API key is required")
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if chunk_ms <= 0:
            raise ValueError("chunk_ms must be positive")

        super().__init__(
            capabilities=stt.STTCapabilities(
                streaming=True,
                interim_results=True,
                offline_recognize=False,
            )
        )
        self._opts = YandexSTTOptions(
            api_key=api_key,
            model=model,
            language=language,
            sample_rate=sample_rate,
            chunk_ms=chunk_ms,
            eou_sensitivity=eou_sensitivity,
            max_pause_between_words_hint_ms=_normalize_pause_hint_ms(
                max_pause_between_words_hint_ms
            ),
            endpoint=endpoint,
        )
        self._recognize_stream_factory = recognize_stream_factory
        self._channel: grpc.aio.Channel | None = None
        if recognize_stream_factory is None:
            self._channel = grpc.aio.secure_channel(
                endpoint,
                grpc.ssl_channel_credentials(),
            )
        self._streams = weakref.WeakSet[YandexSpeechStream]()

    @property
    def model(self) -> str:
        return self._opts.model

    @property
    def provider(self) -> str:
        return "Yandex SpeechKit"

    async def _recognize_impl(
        self,
        buffer: AudioBuffer,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions,
    ) -> stt.SpeechEvent:
        raise NotImplementedError("Yandex SpeechKit STT supports streaming only")

    def stream(
        self,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> YandexSpeechStream:
        opts = YandexSTTOptions(**self._opts.__dict__)
        if is_given(language):
            opts.language = language
        stream = YandexSpeechStream(
            stt_obj=self,
            opts=opts,
            conn_options=conn_options,
        )
        self._streams.add(stream)
        return stream

    def _recognize_stream(
        self,
        requests: AsyncIterable[yandex_pb.StreamingRequest],
        *,
        metadata: tuple[tuple[str, str], ...],
    ) -> AsyncIterable[yandex_pb.StreamingResponse]:
        if self._recognize_stream_factory is not None:
            return self._recognize_stream_factory(requests, metadata)
        if self._channel is None:
            raise APIConnectionError("Yandex SpeechKit channel is not available")
        method = self._channel.stream_stream(
            _RECOGNIZE_STREAMING_PATH,
            request_serializer=yandex_pb.StreamingRequest.SerializeToString,
            response_deserializer=yandex_pb.StreamingResponse.FromString,
        )
        return method(requests, metadata=metadata)

    async def aclose(self) -> None:
        await asyncio.gather(
            *(stream.aclose() for stream in list(self._streams)),
            return_exceptions=True,
        )
        if self._channel is not None:
            await self._channel.close()


class YandexSpeechStream(stt.SpeechStream):
    def __init__(
        self,
        *,
        stt_obj: YandexSpeechKitSTT,
        opts: YandexSTTOptions,
        conn_options: APIConnectOptions,
    ) -> None:
        super().__init__(
            stt=stt_obj,
            conn_options=conn_options,
            sample_rate=opts.sample_rate,
        )
        self._stt: YandexSpeechKitSTT = stt_obj
        self._opts = opts
        self._speaking = False
        self._request_id = ""
        self._reconnect_event = asyncio.Event()
        self._session_time_offset = 0.0
        self._session_audio_ms = 0
        self._session_audio_bytes = 0
        self._renew_after_eou = False

    async def _run(self) -> None:
        while True:
            self._reconnect_event.clear()
            self._session_audio_ms = 0
            self._session_audio_bytes = 0
            self._renew_after_eou = False
            should_stop = asyncio.Event()
            metadata = (("authorization", f"Api-Key {self._opts.api_key}"),)

            call: Any | None = None
            try:
                started_at = time.perf_counter()
                call = self._stt._recognize_stream(
                    self._request_generator(should_stop),
                    metadata=metadata,
                )
                self._report_connection_acquired(
                    time.perf_counter() - started_at,
                    False,
                )

                process_task = asyncio.create_task(
                    self._process_responses(call),
                    name="YandexSpeechStream._process_responses",
                )
                reconnect_task = asyncio.create_task(
                    self._reconnect_event.wait(),
                    name="YandexSpeechStream._reconnect_event",
                )
                try:
                    done, _ = await asyncio.wait(
                        (process_task, reconnect_task),
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if process_task in done:
                        process_task.result()
                        return

                    should_stop.set()
                    if call is not None and hasattr(call, "cancel"):
                        call.cancel()
                    self._session_time_offset += self._session_audio_ms / 1000.0
                finally:
                    await utils.aio.gracefully_cancel(process_task, reconnect_task)
            except asyncio.TimeoutError as e:
                raise APITimeoutError() from e
            except grpc.aio.AioRpcError as e:
                if e.code() == grpc.StatusCode.CANCELLED and should_stop.is_set():
                    continue
                raise _grpc_error_to_livekit_error(e) from e
            except APIConnectionError:
                raise
            except Exception as e:
                raise APIConnectionError("Yandex SpeechKit stream failed") from e

    async def _request_generator(
        self,
        should_stop: asyncio.Event,
    ) -> AsyncIterable[yandex_pb.StreamingRequest]:
        yield yandex_pb.StreamingRequest(
            session_options=build_yandex_streaming_options(self._opts)
        )

        samples_per_channel = max(1, self._opts.sample_rate * self._opts.chunk_ms // 1000)
        audio_bstream = utils.audio.AudioByteStream(
            sample_rate=self._opts.sample_rate,
            num_channels=1,
            samples_per_channel=samples_per_channel,
        )

        async for data in self._input_ch:
            if should_stop.is_set():
                return

            frames: list[rtc.AudioFrame] = []
            if isinstance(data, rtc.AudioFrame):
                frames.extend(audio_bstream.write(data.data.tobytes()))
            elif isinstance(data, self._FlushSentinel):
                frames.extend(audio_bstream.flush())

            for frame in frames:
                if should_stop.is_set():
                    return
                chunk = frame.data.tobytes()
                self._session_audio_bytes += len(chunk)
                self._session_audio_ms += round(frame.duration * 1000)
                yield yandex_pb.StreamingRequest(
                    chunk=yandex_pb.AudioChunk(data=chunk)
                )

    async def _process_responses(
        self,
        responses: AsyncIterable[yandex_pb.StreamingResponse],
    ) -> None:
        async for response in responses:
            self._process_response(response)

    def _process_response(self, response: yandex_pb.StreamingResponse) -> None:
        event = response.WhichOneof("Event")
        request_id = _request_id_from_response(response)
        if request_id:
            self._request_id = request_id

        if event in {"partial", "final"}:
            update = getattr(response, event)
            alternatives = _alternatives_to_speech_data(
                update.alternatives,
                default_language=self._opts.language,
                start_time_offset=self.start_time_offset + self._session_time_offset,
            )
            if not alternatives:
                return

            if not self._speaking:
                self._speaking = True
                self._event_ch.send_nowait(
                    stt.SpeechEvent(type=stt.SpeechEventType.START_OF_SPEECH)
                )

            event_type = (
                stt.SpeechEventType.INTERIM_TRANSCRIPT
                if event == "partial"
                else stt.SpeechEventType.FINAL_TRANSCRIPT
            )
            self._event_ch.send_nowait(
                stt.SpeechEvent(
                    type=event_type,
                    request_id=self._request_id,
                    alternatives=alternatives,
                )
            )
            if event == "final" and self._should_renew_session():
                self._renew_after_eou = True
            return

        if event == "eou_update":
            if self._speaking:
                self._speaking = False
                self._event_ch.send_nowait(
                    stt.SpeechEvent(
                        type=stt.SpeechEventType.END_OF_SPEECH,
                        request_id=self._request_id,
                    )
                )
            if self._renew_after_eou or self._should_renew_session():
                self._renew_after_eou = False
                self._reconnect_event.set()
            return

        if event == "status_code":
            status = response.status_code
            if status.code_type == yandex_pb.WARNING:
                logger.warning("Yandex SpeechKit warning: %s", status.message)

    def _should_renew_session(self) -> bool:
        return (
            self._session_audio_ms >= _RENEW_AFTER_AUDIO_MS
            or self._session_audio_bytes >= _RENEW_AFTER_BYTES
        )


def build_yandex_streaming_options(
    opts: YandexSTTOptions,
) -> yandex_pb.StreamingOptions:
    return yandex_pb.StreamingOptions(
        recognition_model=yandex_pb.RecognitionModelOptions(
            model=opts.model,
            audio_format=yandex_pb.AudioFormatOptions(
                raw_audio=yandex_pb.RawAudio(
                    audio_encoding=yandex_pb.RawAudio.LINEAR16_PCM,
                    sample_rate_hertz=opts.sample_rate,
                    audio_channel_count=1,
                )
            ),
            text_normalization=yandex_pb.TextNormalizationOptions(
                text_normalization=(
                    yandex_pb.TextNormalizationOptions.TEXT_NORMALIZATION_DISABLED
                ),
                profanity_filter=False,
                literature_text=False,
                phone_formatting_mode=(
                    yandex_pb.TextNormalizationOptions.PHONE_FORMATTING_MODE_DISABLED
                ),
            ),
            language_restriction=yandex_pb.LanguageRestrictionOptions(
                restriction_type=yandex_pb.LanguageRestrictionOptions.WHITELIST,
                language_code=[opts.language],
            ),
            audio_processing_type=yandex_pb.RecognitionModelOptions.REAL_TIME,
        ),
        eou_classifier=yandex_pb.EouClassifierOptions(
            default_classifier=yandex_pb.DefaultEouClassifier(
                type=_eou_sensitivity_to_proto(opts.eou_sensitivity),
                max_pause_between_words_hint_ms=(
                    _normalize_pause_hint_ms(opts.max_pause_between_words_hint_ms)
                ),
            )
        ),
        speaker_labeling=yandex_pb.SpeakerLabelingOptions(
            speaker_labeling=yandex_pb.SpeakerLabelingOptions.SPEAKER_LABELING_DISABLED
        ),
    )


def _eou_sensitivity_to_proto(raw: str) -> int:
    value = raw.strip().lower()
    if value in {"high", "fast"}:
        return yandex_pb.DefaultEouClassifier.HIGH
    return yandex_pb.DefaultEouClassifier.DEFAULT


def _normalize_pause_hint_ms(value: int) -> int:
    if value < _MIN_EOU_PAUSE_HINT_MS:
        logger.warning(
            "Yandex SpeechKit pause hint is below the API minimum; clamping",
            extra={
                "requested_ms": value,
                "effective_ms": _MIN_EOU_PAUSE_HINT_MS,
            },
        )
        return _MIN_EOU_PAUSE_HINT_MS
    if value > _MAX_EOU_PAUSE_HINT_MS:
        logger.warning(
            "Yandex SpeechKit pause hint is above the API maximum; clamping",
            extra={
                "requested_ms": value,
                "effective_ms": _MAX_EOU_PAUSE_HINT_MS,
            },
        )
        return _MAX_EOU_PAUSE_HINT_MS
    return value


def _alternatives_to_speech_data(
    alternatives: Any,
    *,
    default_language: str,
    start_time_offset: float,
) -> list[stt.SpeechData]:
    speech_data: list[stt.SpeechData] = []
    for alternative in alternatives:
        text = (alternative.text or "").strip()
        if not text and alternative.words:
            text = " ".join(word.text for word in alternative.words).strip()
        if not text:
            continue

        words = [
            TimedString(
                text=word.text,
                start_time=word.start_time_ms / 1000.0 + start_time_offset,
                end_time=word.end_time_ms / 1000.0 + start_time_offset,
                start_time_offset=start_time_offset,
            )
            for word in alternative.words
        ]
        language = _language_from_alternative(alternative, default_language)
        speech_data.append(
            stt.SpeechData(
                language=LanguageCode(language),
                text=text,
                start_time=alternative.start_time_ms / 1000.0 + start_time_offset,
                end_time=alternative.end_time_ms / 1000.0 + start_time_offset,
                confidence=float(alternative.confidence or 0.0),
                words=words or None,
            )
        )
    return speech_data


def _language_from_alternative(alternative: Any, default_language: str) -> str:
    if not alternative.languages:
        return default_language
    best = max(alternative.languages, key=lambda item: item.probability)
    return best.language_code or default_language


def _request_id_from_response(response: yandex_pb.StreamingResponse) -> str:
    if response.session_uuid.uuid:
        return response.session_uuid.uuid
    return response.session_uuid.user_request_id


def _grpc_error_to_livekit_error(error: grpc.aio.AioRpcError) -> Exception:
    code = error.code()
    details = error.details() or code.name
    if code in {
        grpc.StatusCode.DEADLINE_EXCEEDED,
    }:
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
