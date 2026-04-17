import asyncio
import base64
import binascii
import json
import logging
from dataclasses import dataclass, replace

import httpx
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

DEFAULT_BASE_URL = "https://api-uw.minimax.io"
DEFAULT_MODEL = "speech-2.8-turbo"
DEFAULT_VOICE_ID = "moss_audio_43d3c43e-3a2d-11f1-b47e-928b88df9451"
DEFAULT_LANGUAGE_BOOST = "Russian"
DEFAULT_AUDIO_FORMAT = "mp3"
DEFAULT_SAMPLE_RATE = 32000
DEFAULT_BITRATE = 128000
DEFAULT_CHANNELS = 1

logger = logging.getLogger("agent")


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
    audio_format: str
    sample_rate: int
    bitrate: int
    channel: int
    tokenizer: tokenize.SentenceTokenizer


def _audio_mime_type(fmt: str) -> str:
    resolved = fmt.strip().lower()
    if resolved == "wav":
        return "audio/wav"
    if resolved == "flac":
        return "audio/flac"
    # MiniMax streaming/non-streaming supports mp3 well for telephony.
    return "audio/mpeg"


def _decode_minimax_audio(raw_audio: str) -> bytes:
    text = raw_audio.strip()
    if not text:
        return b""

    # HTTP T2A returns hex by default (output_format=hex).
    try:
        return bytes.fromhex(text)
    except ValueError:
        pass

    # Keep a base64 fallback for compatibility if endpoint config changes.
    try:
        padded = text + ("=" * ((4 - len(text) % 4) % 4))
        return base64.b64decode(padded)
    except (binascii.Error, ValueError):
        return b""


class MiniMaxTTS(tts.TTS):
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
        audio_format: str = DEFAULT_AUDIO_FORMAT,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        bitrate: int = DEFAULT_BITRATE,
        channel: int = DEFAULT_CHANNELS,
        tokenizer_obj: NotGivenOr[tokenize.SentenceTokenizer] = NOT_GIVEN,
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
            sample_rate=sample_rate,
            num_channels=1,
        )

        self._opts = _MiniMaxTTSOptions(
            api_key=api_key.strip(),
            base_url=((base_url or DEFAULT_BASE_URL).strip().rstrip("/") or DEFAULT_BASE_URL),
            model=(model or DEFAULT_MODEL).strip(),
            voice_id=(voice_id or DEFAULT_VOICE_ID).strip(),
            language_boost=(language_boost or DEFAULT_LANGUAGE_BOOST).strip(),
            speed=float(speed),
            volume=float(volume),
            pitch=int(pitch),
            audio_format=resolved_format,
            sample_rate=int(sample_rate),
            bitrate=int(bitrate),
            channel=int(channel),
            tokenizer=tokenizer_obj,
        )

        # Keep one pooled client per TTS instance.
        self._client = httpx.AsyncClient(
            base_url=self._opts.base_url,
            headers={
                "Authorization": f"Bearer {self._opts.api_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    @property
    def model(self) -> str:
        return self._opts.model

    @property
    def provider(self) -> str:
        return "MiniMax"

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
        return _MiniMaxSynthesizeStream(tts_obj=self, conn_options=conn_options)

    async def aclose(self) -> None:
        await self._client.aclose()


class _MiniMaxSynthesizeStream(tts.SynthesizeStream):
    def __init__(self, *, tts_obj: MiniMaxTTS, conn_options: APIConnectOptions):
        super().__init__(tts=tts_obj, conn_options=conn_options)
        self._tts: MiniMaxTTS = tts_obj
        self._opts = replace(tts_obj._opts)

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        segments_ch = utils.aio.Chan[tokenize.SentenceStream]()
        stream_format = self._opts.audio_format if self._opts.audio_format == "mp3" else "mp3"

        output_emitter.initialize(
            request_id=utils.shortuuid(),
            sample_rate=self._tts.sample_rate,
            num_channels=self._tts.num_channels,
            mime_type=_audio_mime_type(stream_format),
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
        text_parts: list[str] = []
        async for sentence in input_stream:
            text = (sentence.token or "").strip()
            if not text:
                continue
            text_parts.append(text)

        if not text_parts:
            raise APIStatusError(
                "minimax tts: empty segment text",
                status_code=400,
                retryable=False,
            )

        self._mark_started()
        found_audio = await self._stream_segment_audio(
            text=" ".join(text_parts),
            output_emitter=output_emitter,
        )
        if not found_audio:
            raise APIStatusError(
                "minimax tts: no audio returned for the segment",
                status_code=502,
                retryable=False,
            )

    async def _stream_segment_audio(
        self,
        *,
        text: str,
        output_emitter: tts.AudioEmitter,
    ) -> bool:
        resolved_format = self._opts.audio_format
        # MiniMax HTTP streaming is stable with mp3 chunks. Force mp3 for
        # stream=true even if env requested another format.
        if resolved_format != "mp3":
            logger.warning(
                "MiniMax streaming TTS requires mp3 chunks; forcing format=mp3 (requested=%s)",
                resolved_format,
            )
            resolved_format = "mp3"

        payload = {
            "model": self._opts.model,
            "text": text,
            "stream": True,
            # Remove final aggregated full audio blob to avoid duplicate audio.
            "stream_options": {"exclude_aggregated_audio": True},
            "output_format": "hex",
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
                "format": resolved_format,
                "channel": self._opts.channel,
            },
        }

        try:
            async with asyncio.timeout(self._conn_options.timeout):
                async with self._tts._client.stream(
                    "POST",
                    "/v1/t2a_v2",
                    json=payload,
                ) as response:
                    found_audio = False
                    first_audio_logged = False
                    if response.status_code >= 400:
                        body = await response.aread()
                        raise APIStatusError(
                            message=f"minimax tts http error {response.status_code}",
                            status_code=response.status_code,
                            retryable=response.status_code in {408, 429, 500, 502, 503, 504},
                            body=body.decode("utf-8", errors="ignore")[:500],
                        )

                    async for raw_line in response.aiter_lines():
                        if not raw_line:
                            continue
                        line = raw_line.strip()
                        if not line.startswith("data: "):
                            continue
                        json_payload = line[6:]
                        try:
                            event_obj = json.loads(json_payload)
                        except json.JSONDecodeError:
                            continue

                        data = event_obj.get("data") or {}
                        base_resp = event_obj.get("base_resp") or {}
                        base_status = int(base_resp.get("status_code", 0) or 0)
                        if base_status != 0:
                            raise APIStatusError(
                                message=str(base_resp.get("status_msg") or "minimax tts api error"),
                                status_code=400,
                                retryable=False,
                                body=str(event_obj)[:500],
                            )

                        raw_audio = data.get("audio") or ""
                        if not isinstance(raw_audio, str) or not raw_audio:
                            status = int(data.get("status", 0) or 0)
                            if status == 2:
                                # MiniMax signals end-of-stream with status=2.
                                # Do not wait for TCP close, otherwise we may hang.
                                break
                            continue

                        audio_bytes = _decode_minimax_audio(raw_audio)
                        if not audio_bytes:
                            continue

                        output_emitter.push(audio_bytes)
                        found_audio = True
                        if not first_audio_logged:
                            logger.debug("minimax tts: first audio chunk received")
                            first_audio_logged = True

                        status = int(data.get("status", 0) or 0)
                        if status == 2:
                            break

                    return found_audio
        except TimeoutError:
            raise APITimeoutError() from None
        except httpx.TimeoutException:
            raise APITimeoutError() from None
        except httpx.HTTPError as e:
            raise APIConnectionError(f"minimax tts connection error: {e}", retryable=True) from e
