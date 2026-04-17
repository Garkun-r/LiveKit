import asyncio
import base64
import json
import logging
import os
import tempfile
from collections.abc import AsyncIterator, Awaitable
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any, Callable

from dotenv import load_dotenv
from google.auth import default as google_auth_default
from google.auth import (
    load_credentials_from_file as google_auth_load_credentials_from_file,
)
from google.cloud import texttospeech_v1 as texttospeech
from livekit import rtc
from livekit.agents import (
    NOT_GIVEN,
    Agent,
    AgentServer,
    AgentSession,
    APIStatusError,
    JobContext,
    JobProcess,
    RunContext,
    cli,
    function_tool,
    inference,
    room_io,
    tokenize,
)
from livekit.agents import (
    stt as lk_stt,
)
from livekit.agents.llm import ChatMessage
from livekit.plugins import (
    ai_coustics,
    deepgram,
    elevenlabs,
    google,
    minimax,
    noise_cancellation,
    silero,
)
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from config import (
    AGENT_NAME,
    COSYVOICE_API_KEY,
    COSYVOICE_API_KEY_ENV_NAME,
    COSYVOICE_PROFILE,
    COSYVOICE_TTS_CLONE_VOICE_ID,
    COSYVOICE_TTS_CONNECTION_REUSE,
    COSYVOICE_TTS_DESIGN_VOICE_ID,
    COSYVOICE_TTS_FORMAT,
    COSYVOICE_TTS_MIN_SENTENCE_LEN,
    COSYVOICE_TTS_MODEL,
    COSYVOICE_TTS_PITCH,
    COSYVOICE_TTS_PLAYBACK_ON_FIRST_CHUNK,
    COSYVOICE_TTS_RATE,
    COSYVOICE_TTS_REGION,
    COSYVOICE_TTS_SAMPLE_RATE,
    COSYVOICE_TTS_STREAM_CONTEXT_LEN,
    COSYVOICE_TTS_TRANSPORT,
    COSYVOICE_TTS_VOICE_ID,
    COSYVOICE_TTS_VOICE_MODE,
    COSYVOICE_TTS_VOLUME,
    COSYVOICE_TTS_WS_URL,
    DEEPGRAM_API_KEY,
    ELEVENLABS_MODEL,
    ELEVENLABS_VOICE_ID,
    GEMINI_FALLBACK_MODEL,
    GEMINI_MAX_OUTPUT_TOKENS,
    GEMINI_MODEL,
    GEMINI_TEMPERATURE,
    GEMINI_THINKING_LEVEL,
    GEMINI_TOP_P,
    GOOGLE_API_KEY,
    GOOGLE_TTS_CREDENTIALS_B64,
    GOOGLE_TTS_CREDENTIALS_FILE,
    GOOGLE_TTS_CREDENTIALS_JSON,
    GOOGLE_TTS_FALLBACK_MODEL,
    GOOGLE_TTS_LOCATION,
    GOOGLE_TTS_MIN_SENTENCE_LEN,
    GOOGLE_TTS_MODEL,
    GOOGLE_TTS_PITCH,
    GOOGLE_TTS_PROMPT,
    GOOGLE_TTS_SPEAKING_RATE,
    GOOGLE_TTS_STREAM_CONTEXT_LEN,
    GOOGLE_TTS_USE_STREAMING,
    GOOGLE_TTS_VOICE_NAME,
    LLM_FIRST_TOKEN_TIMEOUT_SEC,
    LLM_RETRY_DELAY_SEC,
    MINIMAX_API_KEY,
    MINIMAX_TTS_BASE_URL,
    MINIMAX_TTS_BITRATE,
    MINIMAX_TTS_FORMAT,
    MINIMAX_TTS_LANGUAGE_BOOST,
    MINIMAX_TTS_MIN_SENTENCE_LEN,
    MINIMAX_TTS_MODEL,
    MINIMAX_TTS_PITCH,
    MINIMAX_TTS_SAMPLE_RATE,
    MINIMAX_TTS_SPEED,
    MINIMAX_TTS_STREAM_CONTEXT_LEN,
    MINIMAX_TTS_VOICE_ID,
    MINIMAX_TTS_VOLUME,
    PREEMPTIVE_GENERATION,
    REPLY_WATCHDOG_SEC,
    STT_DEEPGRAM_LANGUAGE,
    STT_DEEPGRAM_MODEL,
    STT_GOOGLE_LANGUAGE,
    STT_GOOGLE_LOCATION,
    STT_GOOGLE_MODEL,
    STT_INFERENCE_FALLBACK_MODEL,
    STT_INFERENCE_INCLUDE_GOOGLE_FALLBACK,
    STT_INFERENCE_LANGUAGE,
    STT_INFERENCE_MODEL,
    STT_PROVIDER,
    TTS_PROVIDER,
    TURN_DETECTION_MODE,
    TURN_ENDPOINTING_MODE,
    TURN_MAX_ENDPOINTING_DELAY,
    TURN_MIN_ENDPOINTING_DELAY,
    VERTEX_TTS_MIN_SENTENCE_LEN,
    VERTEX_TTS_STREAM_CONTEXT_LEN,
)
from cosyvoice_tts import CosyVoiceTTS
from prompt_repo import get_active_prompt
from session_export import send_session_to_n8n
from vertex_gemini_tts import VertexGeminiTTS

logger = logging.getLogger("agent")

load_dotenv(".env.local")

_materialized_google_credentials_file: str | None = None


def safe_dump(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): safe_dump(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [safe_dump(item) for item in value]
    if hasattr(value, "model_dump"):
        try:
            return safe_dump(value.model_dump())
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        try:
            return {str(key): safe_dump(item) for key, item in vars(value).items()}
        except Exception:
            pass
    return str(value)


def build_google_llm() -> google.LLM:
    if not GOOGLE_API_KEY:
        raise RuntimeError("GOOGLE_API_KEY is not set. Configure it in .env.local")

    # Direct Gemini API configuration (not LiveKit Inference).
    return google.LLM(
        model=GEMINI_MODEL,
        api_key=GOOGLE_API_KEY,
        temperature=GEMINI_TEMPERATURE,
        max_output_tokens=GEMINI_MAX_OUTPUT_TOKENS,
        top_p=GEMINI_TOP_P,
        thinking_config={"thinking_level": GEMINI_THINKING_LEVEL},
    )


def build_elevenlabs_tts() -> Any:
    logger.info("using ElevenLabs TTS provider", extra={"model": ELEVENLABS_MODEL})
    return elevenlabs.TTS(
        voice_id=ELEVENLABS_VOICE_ID,
        model=ELEVENLABS_MODEL,
    )


def _resolve_google_tts_credentials_file() -> str:
    """Return a usable credentials file path for Google auth in local/cloud runtimes."""
    global _materialized_google_credentials_file

    if GOOGLE_TTS_CREDENTIALS_FILE:
        if os.path.exists(GOOGLE_TTS_CREDENTIALS_FILE):
            return GOOGLE_TTS_CREDENTIALS_FILE
        logger.warning(
            "GOOGLE_TTS_CREDENTIALS_FILE is set but file does not exist: %s. "
            "Trying GOOGLE_TTS_CREDENTIALS_JSON/B64 instead.",
            GOOGLE_TTS_CREDENTIALS_FILE,
        )

    if _materialized_google_credentials_file:
        return _materialized_google_credentials_file

    raw_json = GOOGLE_TTS_CREDENTIALS_JSON.strip()
    if not raw_json and GOOGLE_TTS_CREDENTIALS_B64.strip():
        try:
            raw_json = base64.b64decode(GOOGLE_TTS_CREDENTIALS_B64).decode("utf-8")
        except Exception as e:
            logger.warning("failed to decode GOOGLE_TTS_CREDENTIALS_B64: %s", e)
            return ""

    if not raw_json:
        return ""

    try:
        parsed = json.loads(raw_json)
    except Exception as e:
        logger.warning("GOOGLE_TTS_CREDENTIALS_JSON is invalid JSON: %s", e)
        return ""

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".json",
            prefix="google-sa-",
            delete=False,
        ) as tmp:
            json.dump(parsed, tmp)
            tmp.flush()
            os.fchmod(tmp.fileno(), 0o600)
            _materialized_google_credentials_file = tmp.name
    except Exception as e:
        logger.warning("failed to materialize Google credentials file: %s", e)
        return ""

    logger.info("materialized Google credentials JSON to temporary file for runtime auth")
    return _materialized_google_credentials_file


def _google_tts_credentials_available() -> bool:
    scope = ["https://www.googleapis.com/auth/cloud-platform"]
    creds_file = _resolve_google_tts_credentials_file()
    try:
        if creds_file:
            google_auth_load_credentials_from_file(creds_file, scopes=scope)
        else:
            google_auth_default(scopes=scope)
        return True
    except Exception as e:
        logger.warning(
            "Google TTS credentials are missing or invalid (%s). "
            "Set GOOGLE_TTS_CREDENTIALS_FILE or GOOGLE_APPLICATION_CREDENTIALS. "
            "Falling back to ElevenLabs TTS.",
            e,
        )
        return False


def build_tts() -> Any:
    if TTS_PROVIDER not in {"google", "vertex", "minimax", "cosyvoice", "elevenlabs"}:
        logger.warning(
            "Unknown TTS_PROVIDER='%s'. Falling back to ElevenLabs.",
            TTS_PROVIDER,
        )
        return build_elevenlabs_tts()

    if TTS_PROVIDER == "cosyvoice":
        if COSYVOICE_TTS_TRANSPORT != "websocket":
            raise RuntimeError(
                "CosyVoice low-latency mode requires WebSocket transport. "
                "Set COSYVOICE_TTS_TRANSPORT=websocket."
            )

        resolved_api_key = (COSYVOICE_API_KEY or "").strip()
        if not resolved_api_key:
            raise RuntimeError(
                f"{COSYVOICE_API_KEY_ENV_NAME or 'COSYVOICE_API_KEY'} is not set. "
                "CosyVoice provider is configured without API key."
            )

        logger.info(
            "using CosyVoice TTS provider",
            extra={
                "profile": COSYVOICE_PROFILE,
                "model": COSYVOICE_TTS_MODEL,
                "transport": COSYVOICE_TTS_TRANSPORT,
                "region": COSYVOICE_TTS_REGION,
                "format": COSYVOICE_TTS_FORMAT,
                "sample_rate": COSYVOICE_TTS_SAMPLE_RATE,
                "voice_mode": COSYVOICE_TTS_VOICE_MODE,
                "connection_reuse": COSYVOICE_TTS_CONNECTION_REUSE,
                "playback_on_first_chunk": COSYVOICE_TTS_PLAYBACK_ON_FIRST_CHUNK,
                "min_sentence_len": max(2, COSYVOICE_TTS_MIN_SENTENCE_LEN),
                "stream_context_len": max(1, COSYVOICE_TTS_STREAM_CONTEXT_LEN),
            },
        )
        return CosyVoiceTTS(
            api_key=resolved_api_key,
            model=COSYVOICE_TTS_MODEL.strip(),
            region=COSYVOICE_TTS_REGION,
            ws_url=COSYVOICE_TTS_WS_URL,
            voice_mode=COSYVOICE_TTS_VOICE_MODE,
            voice_id=COSYVOICE_TTS_VOICE_ID,
            clone_voice_id=COSYVOICE_TTS_CLONE_VOICE_ID,
            design_voice_id=COSYVOICE_TTS_DESIGN_VOICE_ID,
            audio_format=COSYVOICE_TTS_FORMAT,
            sample_rate=COSYVOICE_TTS_SAMPLE_RATE,
            rate=COSYVOICE_TTS_RATE,
            pitch=COSYVOICE_TTS_PITCH,
            volume=COSYVOICE_TTS_VOLUME,
            connection_reuse=COSYVOICE_TTS_CONNECTION_REUSE,
            playback_on_first_chunk=COSYVOICE_TTS_PLAYBACK_ON_FIRST_CHUNK,
            tokenizer_obj=tokenize.blingfire.SentenceTokenizer(
                min_sentence_len=max(2, COSYVOICE_TTS_MIN_SENTENCE_LEN),
                stream_context_len=max(1, COSYVOICE_TTS_STREAM_CONTEXT_LEN),
            ),
        )

    if TTS_PROVIDER == "vertex":
        resolved_creds_file = _resolve_google_tts_credentials_file()
        if resolved_creds_file and not os.path.exists(resolved_creds_file):
            logger.warning(
                "GOOGLE_TTS_CREDENTIALS_FILE does not exist: %s. Falling back to ElevenLabs TTS.",
                resolved_creds_file,
            )
            return build_elevenlabs_tts()
        if not _google_tts_credentials_available():
            return build_elevenlabs_tts()

        if resolved_creds_file:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = resolved_creds_file

        logger.info(
            "using Google Vertex Gemini API TTS provider",
            extra={
                "model": GOOGLE_TTS_MODEL,
                "location": GOOGLE_TTS_LOCATION,
                "min_sentence_len": max(2, VERTEX_TTS_MIN_SENTENCE_LEN),
                "stream_context_len": max(1, VERTEX_TTS_STREAM_CONTEXT_LEN),
            },
        )
        return VertexGeminiTTS(
            model=GOOGLE_TTS_MODEL.strip(),
            voice_name=GOOGLE_TTS_VOICE_NAME or "Zephyr",
            prompt=GOOGLE_TTS_PROMPT,
            location=GOOGLE_TTS_LOCATION,
            tokenizer_obj=tokenize.blingfire.SentenceTokenizer(
                min_sentence_len=max(2, VERTEX_TTS_MIN_SENTENCE_LEN),
                stream_context_len=max(1, VERTEX_TTS_STREAM_CONTEXT_LEN),
            ),
        )

    if TTS_PROVIDER == "google":
        resolved_model = GOOGLE_TTS_MODEL.strip()
        resolved_creds_file = _resolve_google_tts_credentials_file()
        # Normalize common typo/order variant to official Google TTS model id.
        if resolved_model == "gemini-tts-3.1-flash-preview":
            resolved_model = "gemini-3.1-flash-tts-preview"
            logger.warning(
                "Normalized GOOGLE_TTS_MODEL to '%s'.",
                resolved_model,
            )
        # Google Cloud TTS credentials check.
        if resolved_creds_file and not os.path.exists(resolved_creds_file):
            logger.warning(
                "GOOGLE_TTS_CREDENTIALS_FILE does not exist: %s. Falling back to ElevenLabs TTS.",
                resolved_creds_file,
            )
            return build_elevenlabs_tts()
        if not _google_tts_credentials_available():
            return build_elevenlabs_tts()

        supported_google_tts_models = {
            "gemini-3.1-flash-tts-preview",
            "gemini-2.5-flash-tts",
            "gemini-2.5-flash-lite-preview-tts",
            "gemini-2.5-pro-tts",
            "chirp_3",
        }
        if resolved_model not in supported_google_tts_models:
            fallback_model = GOOGLE_TTS_FALLBACK_MODEL or "gemini-3.1-flash-tts-preview"
            if fallback_model not in supported_google_tts_models:
                fallback_model = "gemini-3.1-flash-tts-preview"
            resolved_model = fallback_model
            logger.warning(
                "Google TTS model '%s' is not supported by current plugin/API; using '%s' instead.",
                GOOGLE_TTS_MODEL,
                resolved_model,
            )

        # Gemini 3.1 Flash TTS should run in streaming mode for lower TTFB.
        resolved_streaming = (
            True if resolved_model == "gemini-3.1-flash-tts-preview" else GOOGLE_TTS_USE_STREAMING
        )

        tts_kwargs: dict[str, Any] = {
            "model_name": resolved_model,
            "prompt": GOOGLE_TTS_PROMPT,
            # Hard pin Russian telephony language as requested.
            "language": "ru-RU",
            "speaking_rate": GOOGLE_TTS_SPEAKING_RATE,
            "pitch": GOOGLE_TTS_PITCH,
            "use_streaming": resolved_streaming,
            # Use configured Google Cloud Text-to-Speech endpoint location.
            "location": GOOGLE_TTS_LOCATION,
            # Streaming-compatible encoding for Gemini TTS.
            "audio_encoding": (
                texttospeech.AudioEncoding.PCM
                if resolved_streaming
                else texttospeech.AudioEncoding.LINEAR16
            ),
            # Shorter chunks reduce start delay for streaming TTS because
            # synthesis begins after the current chunk is half-closed.
            "tokenizer": tokenize.blingfire.SentenceTokenizer(
                min_sentence_len=max(2, GOOGLE_TTS_MIN_SENTENCE_LEN),
                stream_context_len=max(1, GOOGLE_TTS_STREAM_CONTEXT_LEN),
            ),
        }
        if GOOGLE_TTS_VOICE_NAME:
            tts_kwargs["voice_name"] = GOOGLE_TTS_VOICE_NAME
        if resolved_creds_file:
            tts_kwargs["credentials_file"] = resolved_creds_file
        logger.info(
            "using Google TTS provider",
            extra={
                "model": resolved_model,
                "streaming": resolved_streaming,
                "location": GOOGLE_TTS_LOCATION,
                "min_sentence_len": max(2, GOOGLE_TTS_MIN_SENTENCE_LEN),
                "stream_context_len": max(1, GOOGLE_TTS_STREAM_CONTEXT_LEN),
            },
        )
        return google.TTS(**tts_kwargs)

    if TTS_PROVIDER == "minimax":
        if not MINIMAX_API_KEY.strip():
            logger.warning("MINIMAX_API_KEY is not set. Falling back to ElevenLabs TTS.")
            return build_elevenlabs_tts()

        logger.info(
            "using MiniMax TTS provider",
            extra={
                "model": MINIMAX_TTS_MODEL,
                "voice_id": MINIMAX_TTS_VOICE_ID,
                "base_url": MINIMAX_TTS_BASE_URL,
                "streaming": True,
            },
        )
        return minimax.TTS(
            model=MINIMAX_TTS_MODEL,
            voice=MINIMAX_TTS_VOICE_ID,
            speed=MINIMAX_TTS_SPEED,
            vol=MINIMAX_TTS_VOLUME,
            pitch=MINIMAX_TTS_PITCH,
            text_normalization=False,
            audio_format=MINIMAX_TTS_FORMAT,
            sample_rate=MINIMAX_TTS_SAMPLE_RATE,
            bitrate=MINIMAX_TTS_BITRATE,
            language_boost=MINIMAX_TTS_LANGUAGE_BOOST,
            tokenizer=tokenize.blingfire.SentenceTokenizer(
                min_sentence_len=max(2, MINIMAX_TTS_MIN_SENTENCE_LEN),
                stream_context_len=max(1, MINIMAX_TTS_STREAM_CONTEXT_LEN),
            ),
            text_pacing=False,
            api_key=MINIMAX_API_KEY,
            base_url=MINIMAX_TTS_BASE_URL,
        )

    return build_elevenlabs_tts()


def build_stt() -> Any:
    def _build_google_stt_or_none(*, log_prefix: str) -> Any | None:
        resolved_creds_file = _resolve_google_tts_credentials_file()
        if not _google_tts_credentials_available():
            logger.warning("%s: Google STT credentials are not available", log_prefix)
            return None

        if STT_GOOGLE_MODEL in ("latest_short", "telephony_short"):
            logger.warning(
                "STT_GOOGLE_MODEL=%s closes the streaming connection after the first "
                "utterance — multi-turn conversations will freeze after the first exchange. "
                "Set STT_GOOGLE_MODEL=latest_long in .env.local for reliable multi-turn operation.",
                STT_GOOGLE_MODEL,
            )

        stt_kwargs: dict[str, Any] = {
            "languages": STT_GOOGLE_LANGUAGE,
            "model": STT_GOOGLE_MODEL,
            "location": STT_GOOGLE_LOCATION,
            "interim_results": True,
            "use_streaming": True,
        }
        if resolved_creds_file:
            stt_kwargs["credentials_file"] = resolved_creds_file

        return google.STT(**stt_kwargs)

    # Default path: LiveKit inference STT.
    if STT_PROVIDER == "inference":
        stt_instances: list[Any] = [
            inference.STT(
                model=STT_INFERENCE_MODEL,
                language=STT_INFERENCE_LANGUAGE,
            )
        ]
        fallback_descriptions = [STT_INFERENCE_MODEL]

        if STT_INFERENCE_INCLUDE_GOOGLE_FALLBACK:
            google_stt = _build_google_stt_or_none(log_prefix="inference->google fallback")
            if google_stt is not None:
                stt_instances.append(google_stt)
                fallback_descriptions.append(f"google:{STT_GOOGLE_MODEL}")

        fallback_model = STT_INFERENCE_FALLBACK_MODEL.strip()
        # Important: both inference models share the same LiveKit gateway quota.
        # A second inference model does not protect from gateway-wide 429.
        # It is placed after Google STT so gateway 429 fails over to Google faster.
        if fallback_model and fallback_model != STT_INFERENCE_MODEL:
            stt_instances.append(
                inference.STT(
                    model=fallback_model,
                    language=STT_INFERENCE_LANGUAGE,
                )
            )
            fallback_descriptions.append(fallback_model)

        if len(stt_instances) == 1:
            return stt_instances[0]

        logger.info(
            "using STT fallback adapter",
            extra={
                "provider": "inference",
                "chain": fallback_descriptions,
            },
        )
        return lk_stt.FallbackAdapter(
            stt=stt_instances,
            # Keep failover quick to avoid long silence when primary is rate-limited.
            attempt_timeout=8.0,
            max_retry_per_stt=0,
            retry_interval=0.7,
        )

    if STT_PROVIDER == "google":
        google_stt = _build_google_stt_or_none(log_prefix="google provider")
        if google_stt is None:
            logger.warning(
                "Google STT credentials are not available; falling back to inference STT."
            )
            return inference.STT(
                model=STT_INFERENCE_MODEL,
                language=STT_INFERENCE_LANGUAGE,
            )

        stt_instances: list[Any] = [google_stt]
        fallback_descriptions = [f"google:{STT_GOOGLE_MODEL}"]
        fallback_model = STT_INFERENCE_MODEL.strip()
        if fallback_model:
            stt_instances.append(
                inference.STT(
                    model=fallback_model,
                    language=STT_INFERENCE_LANGUAGE,
                )
            )
            fallback_descriptions.append(fallback_model)

        logger.info(
            "using Google STT provider",
            extra={
                "model": STT_GOOGLE_MODEL,
                "language": STT_GOOGLE_LANGUAGE,
                "location": STT_GOOGLE_LOCATION,
            },
        )
        if len(stt_instances) == 1:
            return google_stt

        logger.info(
            "using STT fallback adapter",
            extra={
                "provider": "google",
                "chain": fallback_descriptions,
            },
        )
        return lk_stt.FallbackAdapter(
            stt=stt_instances,
            attempt_timeout=8.0,
            max_retry_per_stt=0,
            retry_interval=0.7,
        )

    if STT_PROVIDER == "deepgram":
        if not DEEPGRAM_API_KEY:
            logger.warning("DEEPGRAM_API_KEY is not set. Falling back to inference STT.")
            return inference.STT(
                model=STT_INFERENCE_MODEL,
                language=STT_INFERENCE_LANGUAGE,
            )

        logger.info(
            "using Deepgram STT provider",
            extra={
                "model": STT_DEEPGRAM_MODEL,
                "language": STT_DEEPGRAM_LANGUAGE,
            },
        )
        return deepgram.STT(
            api_key=DEEPGRAM_API_KEY,
            model=STT_DEEPGRAM_MODEL,
            language=STT_DEEPGRAM_LANGUAGE,
        )

    logger.warning(
        "Unknown STT_PROVIDER='%s'. Falling back to inference STT.",
        STT_PROVIDER,
    )
    return inference.STT(
        model=STT_INFERENCE_MODEL,
        language=STT_INFERENCE_LANGUAGE,
    )

class Assistant(Agent):
    def __init__(
        self,
        request_end_call: Callable[[RunContext, str], Awaitable[str]] | None = None,
        fallback_llm: google.LLM | None = None,
    ) -> None:
        self._request_end_call = request_end_call or self._noop_end_call
        self._fallback_llm = fallback_llm
        prompt = get_active_prompt()
        super().__init__(
            instructions=(
                f"{prompt}\n\n"
                "Дополнительное правило: когда разговор логически завершен и ты уже "
                "сказала финальную прощальную фразу, вызови tool end_call.\n"
                "После вызова end_call не добавляй новых реплик пользователю."
            )
        )

    async def _noop_end_call(self, _: RunContext, __: str) -> str:
        return "END_CALL_DISABLED"

    async def _stream_llm(
        self,
        llm_client: Any,
        chat_ctx: Any,
        tools: list[Any],
        model_settings: Any,
    ) -> AsyncIterator[Any]:
        tool_choice = model_settings.tool_choice if model_settings else NOT_GIVEN
        activity = self._get_activity_or_raise()
        conn_options = activity.session.conn_options.llm_conn_options
        async with llm_client.chat(
            chat_ctx=chat_ctx,
            tools=tools,
            tool_choice=tool_choice,
            conn_options=conn_options,
        ) as stream:
            async for chunk in stream:
                yield chunk

    async def _stream_llm_with_ttft_timeout(
        self,
        llm_client: Any,
        chat_ctx: Any,
        tools: list[Any],
        model_settings: Any,
        *,
        first_token_timeout: float,
    ) -> AsyncIterator[Any]:
        stream = self._stream_llm(llm_client, chat_ctx, tools, model_settings)
        stream_iter = stream.__aiter__()
        try:
            first_chunk = await asyncio.wait_for(
                stream_iter.__anext__(),
                timeout=first_token_timeout,
            )
        except StopAsyncIteration:
            return
        except asyncio.TimeoutError:
            with suppress(Exception):
                await stream.aclose()
            raise

        yield first_chunk
        async for chunk in stream_iter:
            yield chunk

    async def llm_node(self, chat_ctx: Any, tools: list[Any], model_settings: Any) -> AsyncIterator[Any]:
        """
        Retries one transient 5xx Gemini failure before first output token.
        If configured, fallback model is used as the final attempt.
        """
        activity = self._get_activity_or_raise()
        primary_llm = activity.llm
        yielded_any = False

        try:
            async for chunk in self._stream_llm_with_ttft_timeout(
                primary_llm,
                chat_ctx,
                tools,
                model_settings,
                first_token_timeout=LLM_FIRST_TOKEN_TIMEOUT_SEC,
            ):
                yielded_any = True
                yield chunk
            return
        except asyncio.TimeoutError:
            logger.warning(
                "primary Gemini first token timeout after %.1fs; retrying once",
                LLM_FIRST_TOKEN_TIMEOUT_SEC,
            )
        except APIStatusError as e:
            if yielded_any or e.status_code < 500:
                raise
            logger.warning("primary Gemini returned %s before first token; retrying once", e.status_code)
        except Exception as e:
            if yielded_any:
                raise
            logger.warning("primary Gemini failed before first token; retrying once: %s", e)

        await asyncio.sleep(max(0.0, LLM_RETRY_DELAY_SEC))

        try:
            async for chunk in self._stream_llm_with_ttft_timeout(
                primary_llm,
                chat_ctx,
                tools,
                model_settings,
                first_token_timeout=LLM_FIRST_TOKEN_TIMEOUT_SEC,
            ):
                yield chunk
            return
        except asyncio.TimeoutError:
            if self._fallback_llm is None:
                raise
            logger.warning(
                "retry first token timeout after %.1fs; switching to fallback Gemini model",
                LLM_FIRST_TOKEN_TIMEOUT_SEC,
            )
        except APIStatusError as e:
            if e.status_code < 500 or self._fallback_llm is None:
                raise
            logger.warning("retry failed with %s; switching to fallback Gemini model", e.status_code)
        except Exception:
            if self._fallback_llm is None:
                raise
            logger.warning("retry failed; switching to fallback Gemini model")

        async for chunk in self._stream_llm_with_ttft_timeout(
            self._fallback_llm,
            chat_ctx,
            tools,
            model_settings,
            first_token_timeout=LLM_FIRST_TOKEN_TIMEOUT_SEC,
        ):
            yield chunk

    @function_tool
    async def end_call(self, context: RunContext, reason: str = "conversation_completed") -> str:
        """Use only when the conversation is logically finished and no more questions are expected.

        Rules:
        - Call only after a final goodbye phrase.
        - Never call in the middle of consultation.
        - If the user asks a new question, continue dialogue and do not call this tool.
        - After this tool call, do not produce additional user-facing text.
        """
        return await self._request_end_call(context, reason)


server = AgentServer()


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session(agent_name=AGENT_NAME)
async def my_agent(ctx: JobContext):
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }

    session_started_at = datetime.now(timezone.utc)

    transcript_items = []
    usage_updates = []
    metrics_events = []
    close_info = {"reason": None, "error": None}
    close_event = asyncio.Event()
    user_activity_event = asyncio.Event()
    user_activity_count = 0
    assistant_message_count = 0
    end_call_task: asyncio.Task | None = None
    reply_watchdog_task: asyncio.Task | None = None
    end_call_grace_sec = 6.0
    export_wait_sec = 20.0
    export_task: asyncio.Task | None = None
    session_close_task: asyncio.Task | None = None

    fallback_llm = None
    if GEMINI_FALLBACK_MODEL:
        # Keep all settings identical; only model name differs for transient fallback.
        fallback_llm = google.LLM(
            model=GEMINI_FALLBACK_MODEL,
            api_key=GOOGLE_API_KEY,
            temperature=GEMINI_TEMPERATURE,
            max_output_tokens=GEMINI_MAX_OUTPUT_TOKENS,
            top_p=GEMINI_TOP_P,
            thinking_config={"thinking_level": GEMINI_THINKING_LEVEL},
        )

    min_endpointing_delay = max(0.0, TURN_MIN_ENDPOINTING_DELAY)
    max_endpointing_delay = max(min_endpointing_delay, TURN_MAX_ENDPOINTING_DELAY)
    endpointing_mode = "dynamic" if TURN_ENDPOINTING_MODE == "dynamic" else "fixed"
    turn_detection_mode: str | MultilingualModel
    if TURN_DETECTION_MODE == "multilingual":
        turn_detection_mode = MultilingualModel()
    elif TURN_DETECTION_MODE in ("vad", "stt", "manual"):
        turn_detection_mode = TURN_DETECTION_MODE
        if TURN_DETECTION_MODE == "stt" and STT_PROVIDER == "google":
            # turn_detection="stt" with Google STT requires enable_voice_activity_events=True,
            # but that causes the streaming session to close after first utterance on latest_short.
            # VAD-based detection (Silero) is the reliable alternative: no Google stream dependency.
            logger.warning(
                "turn_detection='stt' is unreliable with Google STT in LiveKit 1.5+. "
                "Set TURN_DETECTION_MODE=vad in .env.local for stable multi-turn operation."
            )
    else:
        turn_detection_mode = "vad"

    session = AgentSession(
        stt=build_stt(),
        llm=build_google_llm(),
        tts=build_tts(),
        turn_handling={
            "turn_detection": turn_detection_mode,
            "endpointing": {
                "mode": endpointing_mode,
                "min_delay": min_endpointing_delay,
                "max_delay": max_endpointing_delay,
            },
        },
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=PREEMPTIVE_GENERATION,
    )
    logger.info(
        "session latency guards configured",
        extra={
            "llm_first_token_timeout_sec": LLM_FIRST_TOKEN_TIMEOUT_SEC,
            "preemptive_generation": PREEMPTIVE_GENERATION,
            "turn_detection_mode": TURN_DETECTION_MODE,
            "turn_endpointing_mode": endpointing_mode,
            "turn_min_endpointing_delay": min_endpointing_delay,
            "turn_max_endpointing_delay": max_endpointing_delay,
            "reply_watchdog_sec": REPLY_WATCHDOG_SEC,
        },
    )

    async def reply_watchdog(
        *,
        expected_user_activity_count: int,
        expected_assistant_message_count: int,
    ) -> None:
        if REPLY_WATCHDOG_SEC <= 0:
            return
        try:
            await asyncio.sleep(REPLY_WATCHDOG_SEC)
            if close_event.is_set():
                return
            if user_activity_count != expected_user_activity_count:
                return
            if assistant_message_count != expected_assistant_message_count:
                return
            # If generation already started, do not inject an extra reply.
            if session.agent_state in {"thinking", "speaking"}:
                logger.debug(
                    "reply watchdog skipped: agent is already generating",
                    extra={"agent_state": session.agent_state},
                )
                return
            logger.warning(
                "reply watchdog fired; forcing generate_reply",
                extra={
                    "timeout_sec": REPLY_WATCHDOG_SEC,
                    "user_activity_count": user_activity_count,
                    "assistant_message_count": assistant_message_count,
                },
            )
            # Safety path for stuck scheduling:
            # - disable tools to prevent accidental end_call
            # - nudge model to answer latest user request directly
            await session.generate_reply(
                instructions=(
                    "Answer the user's latest question in concise Russian. "
                    "Do not call tools."
                ),
                tool_choice="none",
            )
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.exception("reply watchdog failed: %s", e)

    @session.on("conversation_item_added")
    def on_conversation_item_added(ev):
        nonlocal assistant_message_count, reply_watchdog_task
        try:
            item = ev.item
            if not isinstance(item, ChatMessage):
                return

            transcript_items.append({
                "type": "conversation_item",
                "role": getattr(item, "role", None),
                "text": getattr(item, "text_content", None),
                "interrupted": getattr(item, "interrupted", None),
                "created_at": getattr(item, "created_at", None),
                "metrics": safe_dump(getattr(item, "metrics", None)),
            })
            role_str = str(getattr(item, "role", "")).lower()
            if role_str == "assistant" or role_str.endswith(".assistant"):
                assistant_message_count += 1
                if reply_watchdog_task and not reply_watchdog_task.done():
                    reply_watchdog_task.cancel()
                    reply_watchdog_task = None
        except Exception as e:
            logger.exception("conversation_item_added handler failed: %s", e)

    @session.on("user_input_transcribed")
    def on_user_input_transcribed(ev):
        nonlocal user_activity_count, end_call_task, reply_watchdog_task
        try:
            transcript_items.append({
                "type": "user_input_transcribed",
                "transcript": getattr(ev, "transcript", None),
                "is_final": getattr(ev, "is_final", None),
                "language": getattr(ev, "language", None),
                "speaker_id": getattr(ev, "speaker_id", None),
            })
            transcript = (getattr(ev, "transcript", None) or "").strip()
            if transcript:
                # Any new user speech cancels a pending auto-hangup timer.
                user_activity_count += 1
                user_activity_event.set()
                if end_call_task and not end_call_task.done():
                    end_call_task.cancel()
                    end_call_task = None
                if (
                    bool(getattr(ev, "is_final", False))
                    and REPLY_WATCHDOG_SEC > 0
                ):
                    if reply_watchdog_task and not reply_watchdog_task.done():
                        reply_watchdog_task.cancel()
                    reply_watchdog_task = asyncio.create_task(
                        reply_watchdog(
                            expected_user_activity_count=user_activity_count,
                            expected_assistant_message_count=assistant_message_count,
                        )
                    )
        except Exception as e:
            logger.exception("user_input_transcribed handler failed: %s", e)

    @session.on("session_usage_updated")
    def on_session_usage_updated(ev):
        try:
            usage_updates.append(safe_dump(getattr(ev, "usage", None)))
        except Exception as e:
            logger.exception("session_usage_updated handler failed: %s", e)

    @session.on("agent_state_changed")
    def on_agent_state_changed(ev):
        nonlocal reply_watchdog_task
        try:
            logger.debug(
                "agent state changed",
                extra={
                    "old_state": getattr(ev, "old_state", None),
                    "new_state": getattr(ev, "new_state", None),
                },
            )
            # If generation has started, watchdog fallback is no longer needed.
            if (
                getattr(ev, "new_state", None) in {"thinking", "speaking"}
                and reply_watchdog_task
                and not reply_watchdog_task.done()
            ):
                reply_watchdog_task.cancel()
                reply_watchdog_task = None
        except Exception as e:
            logger.exception("agent_state_changed handler failed: %s", e)

    @session.on("metrics_collected")
    def on_metrics_collected(ev):
        try:
            metrics_events.append(safe_dump(getattr(ev, "metrics", None)))
        except Exception as e:
            logger.exception("metrics_collected handler failed: %s", e)

    async def export_session_data():
        ended_at = datetime.now(timezone.utc)

        payload = {
            "agent_name": AGENT_NAME,
            "room_name": ctx.room.name,
            "started_at": session_started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "duration_sec": (ended_at - session_started_at).total_seconds(),
            "close": close_info,
            "transcript_items": transcript_items,
            "usage_updates": usage_updates,
            "metrics_events": metrics_events,
            "summary": {
                "transcript_count": len(transcript_items),
                "usage_update_count": len(usage_updates),
                "metrics_count": len(metrics_events),
            },
        }

        logger.info("sending session data to n8n")
        await send_session_to_n8n(payload)
        logger.info("session data sent to n8n")

    async def ensure_session_closed(timeout_sec: float) -> None:
        nonlocal session_close_task
        if session_close_task is None:
            session_close_task = asyncio.create_task(session.aclose())
        try:
            await asyncio.wait_for(asyncio.shield(session_close_task), timeout=timeout_sec)
        except asyncio.CancelledError:
            # During shutdown LiveKit may cancel pending tasks aggressively.
            # This is expected and should not be treated as an error.
            logger.debug("session close task was cancelled during shutdown")
        except asyncio.TimeoutError:
            logger.warning("session close timed out after %ss", timeout_sec)
        except BaseException as e:
            logger.exception("session close failed: %s", e)

    async def delete_room_safely(reason: str) -> None:
        close_reason = f"end_call:{reason}"
        try:
            close_info["reason"] = close_reason
            logger.info("ending call by deleting room", extra={"room": ctx.room.name})
            # Bound delete_room call to avoid waiting indefinitely on API edge cases.
            await asyncio.wait_for(asyncio.shield(ctx.delete_room(ctx.room.name)), timeout=3.0)
        except asyncio.TimeoutError:
            logger.warning("delete_room timed out; forcing local shutdown")
        except Exception as e:
            logger.exception("failed to delete room: %s", e)
            close_reason = f"end_call_failed:{reason}"
            close_info["reason"] = close_reason
        finally:
            # Unblock main entrypoint even if LiveKit close signal arrives late.
            close_event.set()
            # Ensure worker exits promptly after final playout and grace window.
            ctx.shutdown(reason=close_reason)
            # Close local AgentSession explicitly so entrypoint does not hang
            # waiting for an external room-close callback.
            await ensure_session_closed(timeout_sec=2.0)

    async def request_end_call(context: RunContext, reason: str) -> str:
        nonlocal end_call_task
        if end_call_task and not end_call_task.done():
            return "END_CALL_ALREADY_SCHEDULED"

        requested_activity = user_activity_count
        end_call_requested_at = asyncio.get_running_loop().time()

        async def end_after_farewell() -> None:
            try:
                # Prevent cutting the final assistant phrase.
                await context.wait_for_playout()
            except Exception as e:
                logger.exception("wait_for_playout failed before end_call: %s", e)
                return

            if user_activity_count != requested_activity:
                logger.info("end_call canceled: user spoke during final playout")
                return

            # Grace timeout is counted from end_call request moment to avoid
            # stacking "playout duration + full grace period".
            elapsed = asyncio.get_running_loop().time() - end_call_requested_at
            remaining_grace = max(0.0, end_call_grace_sec - elapsed)
            try:
                # If the grace window has already passed while the final phrase
                # was playing, end the room immediately.
                if remaining_grace <= 0:
                    await delete_room_safely(reason)
                    return

                user_activity_event.clear()
                # Fallback grace period: if user resumes talking, keep the call open.
                await asyncio.wait_for(user_activity_event.wait(), timeout=remaining_grace)
                logger.info("end_call canceled: user resumed speech")
                return
            except asyncio.TimeoutError:
                await delete_room_safely(reason)
            except asyncio.CancelledError:
                logger.info("end_call timer canceled")
            except Exception as e:
                logger.exception("end_call timer failed: %s", e)

        end_call_task = asyncio.create_task(end_after_farewell())
        return "END_CALL_SCHEDULED"

    @session.on("close")
    def on_close(ev):
        nonlocal reply_watchdog_task
        if close_event.is_set():
            return
        close_info["reason"] = str(getattr(ev, "reason", None))
        err = getattr(ev, "error", None)
        close_info["error"] = str(err) if err else None
        if reply_watchdog_task and not reply_watchdog_task.done():
            reply_watchdog_task.cancel()
            reply_watchdog_task = None
        close_event.set()

    await session.start(
        agent=Assistant(request_end_call=request_end_call, fallback_llm=fallback_llm),
        room=ctx.room,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=lambda params: (
                    noise_cancellation.BVCTelephony()
                    if params.participant.kind
                    == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                    else ai_coustics.audio_enhancement(
                        model=ai_coustics.EnhancerModel.QUAIL_VF_L
                    )
                ),
            ),
            audio_output=room_io.AudioOutputOptions(
                sample_rate=(
                    MINIMAX_TTS_SAMPLE_RATE
                    if TTS_PROVIDER == "minimax"
                    else COSYVOICE_TTS_SAMPLE_RATE
                    if TTS_PROVIDER == "cosyvoice"
                    else 24000
                ),
                num_channels=1,
            ),
        ),
    )

    async def export_best_effort(timeout_sec: float) -> None:
        nonlocal export_task
        if export_task is None:
            export_task = asyncio.create_task(export_session_data())
        try:
            await asyncio.wait_for(asyncio.shield(export_task), timeout=timeout_sec)
        except asyncio.TimeoutError:
            logger.warning("n8n export timed out after %ss", timeout_sec)
        except asyncio.CancelledError:
            # Preserve cancellation semantics for outer handler, but do not lose
            # the in-flight export task. It will be awaited again in cancel path.
            raise
        except BaseException as e:
            logger.exception("n8n export failed: %s", e)

    try:
        await ctx.connect()
        await session.generate_reply(
            instructions=(
                "Сразу после подключения поприветствуй клиента одной фразой: "
                "Здравствуйте! Это компания Кофемастер! Чем могу помочь?"
            )
        )
        await close_event.wait()
        await export_best_effort(timeout_sec=export_wait_sec)
    except asyncio.CancelledError:
        # Python 3.13: CancelledError is a BaseException, and LiveKit will cancel the entrypoint
        # during shutdown. Best-effort export should still complete quickly.
        asyncio.current_task().uncancel()
        logger.warning("entrypoint cancelled; exporting session data to n8n before exit")
        with suppress(BaseException):
            await asyncio.wait_for(close_event.wait(), timeout=0.8)
        if close_info["reason"] is None:
            close_info["reason"] = "entrypoint_cancelled"
        await export_best_effort(timeout_sec=export_wait_sec)
        await ensure_session_closed(timeout_sec=1.0)
    finally:
        if end_call_task and not end_call_task.done():
            end_call_task.cancel()
        if reply_watchdog_task and not reply_watchdog_task.done():
            reply_watchdog_task.cancel()
        await ensure_session_closed(timeout_sec=2.0)
        if export_task and not export_task.done():
            try:
                await asyncio.wait_for(asyncio.shield(export_task), timeout=export_wait_sec)
            except asyncio.TimeoutError:
                logger.warning("n8n export timed out after %ss in finalizer", export_wait_sec)
            except BaseException as e:
                logger.exception("n8n export finalizer failed: %s", e)


if __name__ == "__main__":
    cli.run_app(server)
