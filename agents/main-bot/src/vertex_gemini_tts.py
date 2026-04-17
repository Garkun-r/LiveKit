import asyncio
import json
import os
from dataclasses import dataclass, replace
from typing import AsyncGenerator

from google import genai
from google.genai import types
from google.genai.errors import APIError as GenAIAPIError
from google.genai.errors import ClientError as GenAIClientError
from google.genai.errors import ServerError as GenAIServerError
from livekit.agents import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    tts,
    tokenize,
    utils,
)
from livekit.agents.types import APIConnectOptions, NOT_GIVEN, NotGivenOr
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS
from livekit.agents.utils import is_given

DEFAULT_MODEL = "gemini-3.1-flash-tts-preview"
DEFAULT_VOICE = "Zephyr"
DEFAULT_SAMPLE_RATE = 24000
DEFAULT_LOCATION = "global"


@dataclass
class _VertexGeminiTTSOptions:
    model: str
    voice_name: str
    prompt: str | None
    project: str
    location: str
    tokenizer: tokenize.SentenceTokenizer


def _project_from_credentials_file() -> str | None:
    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if not creds_path or not os.path.exists(creds_path):
        return None

    try:
        with open(creds_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None

    project = data.get("project_id")
    return str(project).strip() if project else None


def _iter_audio_bytes_from_chunk(chunk: types.GenerateContentResponse):
    candidates = getattr(chunk, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            inline_data = getattr(part, "inline_data", None)
            if not inline_data:
                continue
            mime_type = (getattr(inline_data, "mime_type", "") or "").lower()
            data = getattr(inline_data, "data", None)
            if not data or not mime_type.startswith("audio/"):
                continue
            yield bytes(data)


class VertexGeminiTTS(tts.TTS):
    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        voice_name: str = DEFAULT_VOICE,
        prompt: NotGivenOr[str] = NOT_GIVEN,
        project: NotGivenOr[str] = NOT_GIVEN,
        location: str = DEFAULT_LOCATION,
        tokenizer_obj: NotGivenOr[tokenize.SentenceTokenizer] = NOT_GIVEN,
    ) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=True),
            sample_rate=DEFAULT_SAMPLE_RATE,
            num_channels=1,
        )

        resolved_project = (
            project
            if is_given(project)
            else (os.environ.get("GOOGLE_CLOUD_PROJECT") or _project_from_credentials_file())
        )
        if not resolved_project:
            raise ValueError(
                "GOOGLE_CLOUD_PROJECT is required for Vertex Gemini TTS "
                "(or project_id in GOOGLE_APPLICATION_CREDENTIALS)."
            )

        if not is_given(tokenizer_obj):
            tokenizer_obj = tokenize.blingfire.SentenceTokenizer(
                min_sentence_len=4,
                stream_context_len=1,
            )

        self._opts = _VertexGeminiTTSOptions(
            model=model,
            voice_name=voice_name,
            prompt=prompt if is_given(prompt) else None,
            project=resolved_project,
            location=location,
            tokenizer=tokenizer_obj,
        )

        # Match requested Vertex invocation style.
        os.environ.setdefault("GOOGLE_CLOUD_PROJECT", resolved_project)
        os.environ.setdefault("GOOGLE_CLOUD_LOCATION", location)
        os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

        self._client = genai.Client(
            vertexai=True,
            project=resolved_project,
            location=location,
        )

    @property
    def model(self) -> str:
        return self._opts.model

    @property
    def provider(self) -> str:
        return "google-vertex-genai"

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
        return _VertexGeminiSynthesizeStream(tts_obj=self, conn_options=conn_options)

    async def aclose(self) -> None:
        await self._client.aio.aclose()


class _VertexGeminiSynthesizeStream(tts.SynthesizeStream):
    def __init__(self, *, tts_obj: VertexGeminiTTS, conn_options: APIConnectOptions):
        super().__init__(tts=tts_obj, conn_options=conn_options)
        self._tts: VertexGeminiTTS = tts_obj
        self._opts = replace(tts_obj._opts)

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        segments_ch = utils.aio.Chan[tokenize.SentenceStream]()

        output_emitter.initialize(
            request_id=utils.shortuuid(),
            sample_rate=self._tts.sample_rate,
            num_channels=self._tts.num_channels,
            mime_type="audio/pcm",
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
                await self._run_segment_stream(input_stream, output_emitter)
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
        input_stream: tokenize.SentenceStream,
        output_emitter: tts.AudioEmitter,
    ) -> None:
        is_first_chunk = True
        found_audio = False

        async for sentence in input_stream:
            text = (sentence.token or "").strip()
            if not text:
                continue

            self._mark_started()
            chunk_has_audio = await self._synthesize_sentence(
                text=text,
                output_emitter=output_emitter,
                include_prompt=is_first_chunk,
            )
            found_audio = found_audio or chunk_has_audio
            is_first_chunk = False

        if not found_audio:
            raise APIStatusError(
                "vertex gemini tts: no audio returned for the segment",
                status_code=502,
                retryable=False,
            )

    async def _synthesize_sentence(
        self,
        *,
        text: str,
        output_emitter: tts.AudioEmitter,
        include_prompt: bool,
    ) -> bool:
        config = types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=self._opts.voice_name
                    )
                )
            ),
        )

        parts: list[types.Part] = []
        if include_prompt and self._opts.prompt:
            parts.append(types.Part.from_text(text=self._opts.prompt))
        parts.append(types.Part.from_text(text=text))

        contents = [
            types.Content(
                role="user",
                parts=parts,
            )
        ]

        try:
            async with asyncio.timeout(self._conn_options.timeout):
                stream = await self._tts._client.aio.models.generate_content_stream(
                    model=self._opts.model,
                    contents=contents,
                    config=config,
                )

                has_audio = False
                async for chunk in stream:
                    for audio_bytes in _iter_audio_bytes_from_chunk(chunk):
                        output_emitter.push(audio_bytes)
                        has_audio = True
                return has_audio
        except TimeoutError:
            raise APITimeoutError() from None
        except GenAIClientError as e:
            raise APIStatusError(
                message=f"vertex gemini tts client error: {e}",
                status_code=getattr(e, "code", -1) or -1,
                retryable=(getattr(e, "code", None) in {429, 499}),
            ) from e
        except GenAIServerError as e:
            raise APIStatusError(
                message=f"vertex gemini tts server error: {e}",
                status_code=getattr(e, "code", -1) or -1,
                retryable=True,
            ) from e
        except GenAIAPIError as e:
            raise APIStatusError(
                message=f"vertex gemini tts api error: {e}",
                status_code=getattr(e, "code", -1) or -1,
                retryable=True,
            ) from e
        except Exception as e:
            raise APIConnectionError(
                f"vertex gemini tts connection error: {e}",
                retryable=True,
            ) from e
