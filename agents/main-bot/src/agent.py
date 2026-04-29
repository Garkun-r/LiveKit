import asyncio
import base64
import json
import logging
import os
import re
import tempfile
import time
from collections.abc import AsyncIterable, AsyncIterator, Awaitable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import aiohttp
from dotenv import load_dotenv
from google.auth import default as google_auth_default
from google.auth import (
    load_credentials_from_file as google_auth_load_credentials_from_file,
)
from google.cloud import texttospeech_v1 as texttospeech
from google.genai import Client as GenAIClient
from google.genai import types as genai_types
from livekit import rtc
from livekit.agents import (
    NOT_GIVEN,
    Agent,
    AgentServer,
    AgentSession,
    APIStatusError,
    BackgroundAudioPlayer,
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
    llm as lk_llm,
)
from livekit.agents import (
    stt as lk_stt,
)
from livekit.agents.llm import ChatContext, ChatMessage
from livekit.agents.llm.tool_context import StopResponse
from livekit.agents.utils.audio import audio_frames_from_file
from livekit.plugins import (
    ai_coustics,
    deepgram,
    elevenlabs,
    google,
    minimax,
    silero,
    xai,
)
from livekit.plugins.minimax import tts as minimax_tts_plugin
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from config import (
    AGENT_HEALTH_HOST,
    AGENT_HEALTH_PORT,
    AGENT_MAX_CONCURRENT_JOBS,
    AGENT_NAME,
    AGENT_NUM_IDLE_PROCESSES,
    AUDIO_INPUT_ENHANCEMENT,
    COMPLEX_LLM_BACKUP_MODEL,
    COMPLEX_LLM_BACKUP_PROVIDER,
    COMPLEX_LLM_PROVIDER,
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
    ELEVENLABS_V3_APPLY_TEXT_NORMALIZATION,
    ELEVENLABS_V3_ENABLE_LOGGING,
    ELEVENLABS_V3_LANGUAGE,
    ELEVENLABS_V3_MAX_MERGED_TEXT_LEN,
    ELEVENLABS_V3_MERGE_HOLD_MS,
    ELEVENLABS_V3_MIN_HTTP_TEXT_LEN,
    ELEVENLABS_V3_MIN_SENTENCE_LEN,
    ELEVENLABS_V3_OPTIMIZE_STREAMING_LATENCY,
    ELEVENLABS_V3_OUTPUT_FORMAT,
    ELEVENLABS_V3_REQUEST_TIMEOUT_SEC,
    ELEVENLABS_V3_STREAM_CONTEXT_LEN,
    ELEVENLABS_V3_USE_STREAM_INPUT,
    ELEVENLABS_VOICE_ID,
    ELEVENLABS_VOICE_SIMILARITY_BOOST,
    ELEVENLABS_VOICE_SPEED,
    ELEVENLABS_VOICE_STABILITY,
    ELEVENLABS_VOICE_STYLE,
    ELEVENLABS_VOICE_USE_SPEAKER_BOOST,
    FAST_LLM_BACKUP_MODEL,
    FAST_LLM_BACKUP_PROVIDER,
    FAST_LLM_PROVIDER,
    GEMINI_FALLBACK_MODEL,
    GEMINI_HTTP_TIMEOUT_SEC,
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
    LIVEKIT_SELF_HOSTED,
    LLM_ATTEMPT_TIMEOUT_SEC,
    LLM_FALLBACK_FIRST_TOKEN_TIMEOUT_SEC,
    LLM_FIRST_TOKEN_TIMEOUT_SEC,
    LLM_MAX_RETRY_PER_LLM,
    LLM_PROVIDER,
    LLM_RETRY_DELAY_SEC,
    LLM_RETRY_INTERVAL_SEC,
    LLM_RETRY_ON_CHUNK_SENT,
    LLM_ROUTING_ENABLED,
    MINIMAX_API_KEY,
    MINIMAX_TTS_BASE_URL,
    MINIMAX_TTS_BITRATE,
    MINIMAX_TTS_FORMAT,
    MINIMAX_TTS_INTENSITY,
    MINIMAX_TTS_LANGUAGE_BOOST,
    MINIMAX_TTS_MIN_SENTENCE_LEN,
    MINIMAX_TTS_MODEL,
    MINIMAX_TTS_PITCH,
    MINIMAX_TTS_SAMPLE_RATE,
    MINIMAX_TTS_SOUND_EFFECTS,
    MINIMAX_TTS_SPEED,
    MINIMAX_TTS_STREAM_CONTEXT_LEN,
    MINIMAX_TTS_TIMBRE,
    MINIMAX_TTS_VOICE_ID,
    MINIMAX_TTS_VOLUME,
    MODEL_ROUTER_COMPLEX_MODEL,
    MODEL_ROUTER_FAST_MODEL,
    PREEMPTIVE_GENERATION,
    REPLY_WATCHDOG_SEC,
    STT_DEEPGRAM_ENDPOINTING_MS,
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
    USE_LIVEKIT_FALLBACK_ADAPTER,
    VERTEX_TTS_MIN_SENTENCE_LEN,
    VERTEX_TTS_STREAM_CONTEXT_LEN,
    VOICE_CLIENT_SILENCE_AUDIO_PATH,
    VOICE_CLIENT_SILENCE_PHRASE,
    VOICE_CLIENT_SILENCE_SEC,
    VOICE_EMERGENCY_AUDIO_PATH,
    VOICE_EMERGENCY_PHRASE,
    VOICE_RESPONSE_DELAY_AUDIO_PATH,
    VOICE_RESPONSE_DELAY_PHRASE,
    VOICE_RESPONSE_DELAY_SEC,
    XAI_API_KEY,
    XAI_BASE_URL,
    XAI_ENABLE_TOOLS,
    XAI_MODEL,
    XAI_TEMPERATURE,
)
from cosyvoice_tts import CosyVoiceTTS
from egress import (
    aiohttp_proxy,
    httpx_client_args,
    provider_egress,
    provider_egress_env,
    provider_proxy_url,
)
from eleven_v3_tts import ElevenV3TTS
from prompt_repo import PromptResolution, get_active_prompt, resolve_prompt_for_call
from routing.model_router import ModelRouter, ModelRouteResult, coerce_optional_bool
from session_export import send_session_to_n8n
from vertex_gemini_tts import VertexGeminiTTS

logger = logging.getLogger("agent")

load_dotenv(".env.local")

_materialized_google_credentials_file: str | None = None
_minimax_sound_effects_patched = False

_AUDIO_DIR = Path(__file__).resolve().parent.parent / "audio"
_INITIAL_GREETING_AUDIO_PATH = _AUDIO_DIR / "1.wav"
_SHORT_GREETING_AUDIO_PATH = _AUDIO_DIR / "2.wav"
_RESPONSE_DELAY_AUDIO_PATH = None
_CLIENT_SILENCE_AUDIO_PATH = None
_EMERGENCY_AUDIO_PATH = None
_WARMUP_REQUEST_TIMEOUT_SEC = 4.0
_PROMPT_CACHE_WARMUP_USER_TEXT = (
    "Служебный запрос прогрева. Ответь строго одним словом: OK."
)
_SIP_DID_ATTRIBUTE_KEYS = (
    "jcall.did",
    "x-did",
    "X-DID",
    "sip.h.X-DID",
    "sip.trunkPhoneNumber",
)
_WHITESPACE_RE = re.compile(r"\s+")
_SHORT_GREETING_RE = re.compile(
    r"^(?:алло|алло алло|ало|ало ало|алё|алё алё|але|але але|доброе утро|алло доброе утро|ало доброе утро|алё доброе утро|добрый день|алло добрый день|ало добрый день|алё добрый день|здравствуйте|да здравствуйте|алло здравствуйте|ало здравствуйте|алё здравствуйте|девушка здравствуйте|алло девушка здравствуйте|здрасьте|алло здрасьте|ало здрасьте|алё здрасьте|девушка здрасьте|алло девушка здрасьте)[\.!\?, ]*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class LLMBranchMetadata:
    branch: str
    primary_provider: str
    primary_model: str
    backup_provider: str | None = None
    backup_model: str | None = None
    uses_fallback_adapter: bool = False

    @property
    def has_backup(self) -> bool:
        return bool(self.backup_provider and self.backup_model)


def resolve_configured_audio_path(raw_path: str) -> Path | None:
    path_text = (raw_path or "").strip()
    if not path_text:
        return None

    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = _AUDIO_DIR / path
    return path


_RESPONSE_DELAY_AUDIO_PATH = resolve_configured_audio_path(
    VOICE_RESPONSE_DELAY_AUDIO_PATH
)
_CLIENT_SILENCE_AUDIO_PATH = resolve_configured_audio_path(
    VOICE_CLIENT_SILENCE_AUDIO_PATH
)
_EMERGENCY_AUDIO_PATH = resolve_configured_audio_path(VOICE_EMERGENCY_AUDIO_PATH)


def _patch_minimax_sound_effects() -> None:
    """Inject voice_modify.sound_effects into official MiniMax plugin payload."""
    global _minimax_sound_effects_patched

    if _minimax_sound_effects_patched:
        return
    if not MINIMAX_TTS_SOUND_EFFECTS:
        return

    original_to_minimax_options = minimax_tts_plugin._to_minimax_options

    def _patched_to_minimax_options(opts: Any) -> dict[str, Any]:
        config = original_to_minimax_options(opts)
        voice_modify = config.get("voice_modify")
        if not isinstance(voice_modify, dict):
            voice_modify = {}
            config["voice_modify"] = voice_modify
        voice_modify["sound_effects"] = MINIMAX_TTS_SOUND_EFFECTS
        return config

    minimax_tts_plugin._to_minimax_options = _patched_to_minimax_options
    _minimax_sound_effects_patched = True
    logger.info(
        "patched MiniMax plugin payload with voice_modify.sound_effects",
        extra={"sound_effects": MINIMAX_TTS_SOUND_EFFECTS},
    )


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


def extract_sip_call_numbers(participant: Any | None) -> dict[str, str | None]:
    if participant is None:
        return {"sip_trunk_number": None, "sip_client_number": None}
    if getattr(participant, "kind", None) != rtc.ParticipantKind.PARTICIPANT_KIND_SIP:
        return {"sip_trunk_number": None, "sip_client_number": None}

    attributes = getattr(participant, "attributes", None)
    if not isinstance(attributes, dict):
        attributes = {}

    sip_trunk_number = None
    for key in _SIP_DID_ATTRIBUTE_KEYS:
        value = (attributes.get(key) or "").strip()
        if value:
            sip_trunk_number = value
            break

    return {
        "sip_trunk_number": sip_trunk_number,
        "sip_client_number": (attributes.get("sip.phoneNumber") or "").strip() or None,
    }


def is_short_greeting_response(text: str | None) -> bool:
    if text is None:
        return False

    normalized = _WHITESPACE_RE.sub(" ", text.strip().lower())
    if not normalized:
        return False

    return bool(_SHORT_GREETING_RE.fullmatch(normalized))


def resolve_audio_output_sample_rate() -> int:
    if TTS_PROVIDER == "minimax":
        return MINIMAX_TTS_SAMPLE_RATE
    if TTS_PROVIDER == "cosyvoice":
        return COSYVOICE_TTS_SAMPLE_RATE
    return 24000


async def play_prerecorded_audio(
    *,
    session: AgentSession,
    audio_path: Path,
    sample_rate: int,
    allow_interruptions: bool,
    add_to_chat_ctx: bool,
) -> bool:
    if not audio_path.exists():
        logger.warning("prerecorded audio file not found: %s", audio_path)
        return False

    try:
        handle = session.say(
            "",
            audio=audio_frames_from_file(
                str(audio_path),
                sample_rate=sample_rate,
                num_channels=1,
            ),
            allow_interruptions=allow_interruptions,
            add_to_chat_ctx=add_to_chat_ctx,
        )
        await handle.wait_for_playout()
        return True
    except Exception as e:
        logger.exception("failed to play prerecorded audio '%s': %s", audio_path, e)
        return False


@dataclass(frozen=True)
class VoicePromptSpec:
    kind: str
    audio_path: Path | None
    phrase: str


class VoicePromptManager:
    def __init__(
        self,
        *,
        session: AgentSession,
        background_audio: BackgroundAudioPlayer,
        sample_rate: int,
        response_delay_prompt: VoicePromptSpec,
        client_silence_prompt: VoicePromptSpec,
        response_delay_sec: float,
        client_silence_sec: float,
        is_closed: Callable[[], bool],
        is_end_call_scheduled: Callable[[], bool],
    ) -> None:
        self._session = session
        self._background_audio = background_audio
        self._sample_rate = sample_rate
        self._response_delay_prompt = response_delay_prompt
        self._client_silence_prompt = client_silence_prompt
        self._response_delay_sec = max(0.0, response_delay_sec)
        self._client_silence_sec = max(0.0, client_silence_sec)
        self._is_closed = is_closed
        self._is_end_call_scheduled = is_end_call_scheduled

        self._response_delay_task: asyncio.Task | None = None
        self._client_silence_task: asyncio.Task | None = None
        self._stop_active_prompt_task: asyncio.Task | None = None
        self._active_prompt_kind: str | None = None
        self._active_prompt_handle: Any | None = None
        self._active_lock = asyncio.Lock()
        self._response_delay_played = False
        self._client_silence_played = False

    def start_response_delay_timer(self) -> None:
        if self._response_delay_sec <= 0 or self._is_closed():
            return
        self.cancel_response_delay_timer()
        self._response_delay_played = False
        self._response_delay_task = asyncio.create_task(
            self._run_response_delay_timer(),
            name="voice_prompt_response_delay",
        )

    def start_client_silence_timer(self) -> None:
        if (
            self._client_silence_sec <= 0
            or self._is_closed()
            or self._is_end_call_scheduled()
            or self._client_silence_played
        ):
            return
        self.cancel_client_silence_timer()
        self._client_silence_task = asyncio.create_task(
            self._run_client_silence_timer(),
            name="voice_prompt_client_silence",
        )

    def cancel_response_delay_timer(self) -> None:
        if self._response_delay_task and not self._response_delay_task.done():
            self._response_delay_task.cancel()
        self._response_delay_task = None

    def cancel_client_silence_timer(self) -> None:
        if self._client_silence_task and not self._client_silence_task.done():
            self._client_silence_task.cancel()
        self._client_silence_task = None

    def on_user_started_speaking(self) -> None:
        self.cancel_response_delay_timer()
        self.cancel_client_silence_timer()
        self._response_delay_played = False
        self._client_silence_played = False
        self._stop_active_prompt_task = asyncio.create_task(
            self.stop_active_prompt(),
            name="voice_prompt_stop_on_user_speech",
        )

    def on_agent_started_speaking(self) -> None:
        self.cancel_response_delay_timer()
        self.cancel_client_silence_timer()
        if self._active_prompt_kind != "client_silence":
            self._client_silence_played = False

    async def wait_for_active_prompt(self) -> None:
        handle = self._active_prompt_handle
        if handle is None or self._handle_done(handle):
            return
        with suppress(Exception):
            await handle.wait_for_playout()

    async def stop_active_prompt(self) -> None:
        async with self._active_lock:
            handle = self._active_prompt_handle
            self._active_prompt_kind = None
            self._active_prompt_handle = None
        if handle is None or self._handle_done(handle):
            return
        with suppress(Exception):
            if hasattr(handle, "stop"):
                handle.stop()
            elif hasattr(handle, "interrupt"):
                handle.interrupt(force=True)

    async def aclose(self) -> None:
        self.cancel_response_delay_timer()
        self.cancel_client_silence_timer()
        if self._stop_active_prompt_task and not self._stop_active_prompt_task.done():
            self._stop_active_prompt_task.cancel()
        await self.stop_active_prompt()

    async def _run_response_delay_timer(self) -> None:
        try:
            await asyncio.sleep(self._response_delay_sec)
            if self._is_closed() or self._response_delay_played:
                return
            if self._session.agent_state == "speaking":
                return
            played = await self._play_background_prompt(self._response_delay_prompt)
            if played:
                self._response_delay_played = True
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.exception("response delay voice prompt failed: %s", e)

    async def _run_client_silence_timer(self) -> None:
        try:
            await asyncio.sleep(self._client_silence_sec)
            if (
                self._is_closed()
                or self._is_end_call_scheduled()
                or self._client_silence_played
            ):
                return
            if self._session.agent_state != "listening":
                return
            current_speech = self._session.current_speech
            if current_speech is not None and not current_speech.done():
                return
            played = await self._play_session_prompt(self._client_silence_prompt)
            if played:
                self._client_silence_played = True
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.exception("client silence voice prompt failed: %s", e)

    async def _play_background_prompt(self, prompt: VoicePromptSpec) -> bool:
        audio_path = prompt.audio_path
        if audio_path is None:
            return False
        if not audio_path.exists():
            logger.warning(
                "voice prompt audio file not found",
                extra={"kind": prompt.kind, "audio_path": str(audio_path)},
            )
            return False
        if not await self._reserve_active_prompt(prompt.kind):
            return False

        handle = None
        try:
            handle = self._background_audio.play(str(audio_path))
            await self._set_active_prompt(prompt.kind, handle)
            logger.info(
                "voice prompt started",
                extra={"kind": prompt.kind, "audio_path": str(audio_path)},
            )
            await handle.wait_for_playout()
            logger.info("voice prompt finished", extra={"kind": prompt.kind})
            return True
        except Exception as e:
            logger.exception(
                "failed to play background voice prompt '%s': %s",
                prompt.kind,
                e,
            )
            if handle is not None and hasattr(handle, "stop"):
                with suppress(Exception):
                    handle.stop()
            return False
        finally:
            await self._clear_active_prompt(prompt.kind)

    async def _play_session_prompt(self, prompt: VoicePromptSpec) -> bool:
        audio_path = prompt.audio_path
        if audio_path is None:
            return False
        if not audio_path.exists():
            logger.warning(
                "voice prompt audio file not found",
                extra={"kind": prompt.kind, "audio_path": str(audio_path)},
            )
            return False
        if not await self._reserve_active_prompt(prompt.kind):
            return False

        handle = None
        try:
            handle = self._session.say(
                prompt.phrase,
                audio=audio_frames_from_file(
                    str(audio_path),
                    sample_rate=self._sample_rate,
                    num_channels=1,
                ),
                allow_interruptions=True,
                add_to_chat_ctx=False,
            )
            await self._set_active_prompt(prompt.kind, handle)
            logger.info(
                "voice prompt started",
                extra={"kind": prompt.kind, "audio_path": str(audio_path)},
            )
            await handle.wait_for_playout()
            logger.info("voice prompt finished", extra={"kind": prompt.kind})
            return True
        except Exception as e:
            logger.exception(
                "failed to play session voice prompt '%s': %s",
                prompt.kind,
                e,
            )
            if handle is not None and hasattr(handle, "interrupt"):
                with suppress(Exception):
                    handle.interrupt(force=True)
            return False
        finally:
            await self._clear_active_prompt(prompt.kind)

    async def _reserve_active_prompt(self, kind: str) -> bool:
        async with self._active_lock:
            handle = self._active_prompt_handle
            if self._active_prompt_kind is not None and (
                handle is None or not self._handle_done(handle)
            ):
                logger.debug(
                    "voice prompt skipped because another prompt is active",
                    extra={
                        "kind": kind,
                        "active_kind": self._active_prompt_kind,
                    },
                )
                return False
            self._active_prompt_kind = kind
            self._active_prompt_handle = None
            return True

    async def _set_active_prompt(self, kind: str, handle: Any) -> None:
        async with self._active_lock:
            self._active_prompt_kind = kind
            self._active_prompt_handle = handle

    async def _clear_active_prompt(self, kind: str) -> None:
        async with self._active_lock:
            if self._active_prompt_kind == kind:
                self._active_prompt_kind = None
                self._active_prompt_handle = None

    @staticmethod
    def _handle_done(handle: Any) -> bool:
        done = getattr(handle, "done", None)
        if callable(done):
            return bool(done())
        return False


async def warmup_google_llm_transport(llm_client: google.LLM, *, label: str) -> None:
    """Warm up Gemini transport via model metadata call (no generation tokens)."""
    model_name = str(getattr(llm_client, "model", "")).strip()
    client = getattr(llm_client, "_client", None)
    if not model_name or client is None or not hasattr(client, "aio"):
        return

    started_at = asyncio.get_running_loop().time()
    try:
        await asyncio.wait_for(
            client.aio.models.get(model=model_name),
            timeout=_WARMUP_REQUEST_TIMEOUT_SEC,
        )
        elapsed_ms = (asyncio.get_running_loop().time() - started_at) * 1000
        logger.info(
            "llm transport warmup completed",
            extra={
                "provider": "google",
                "model": model_name,
                "label": label,
                "elapsed_ms": round(elapsed_ms, 1),
            },
        )
    except asyncio.TimeoutError:
        logger.warning(
            "llm transport warmup timed out",
            extra={
                "provider": "google",
                "model": model_name,
                "label": label,
                "timeout_sec": _WARMUP_REQUEST_TIMEOUT_SEC,
            },
        )
    except Exception as e:
        logger.warning(
            "llm transport warmup failed: %s",
            e,
            extra={"provider": "google", "model": model_name, "label": label},
        )


async def warmup_xai_llm_transport(
    llm_client: xai.responses.LLM, *, label: str
) -> None:
    """Warm up xAI transport via model metadata call (no generation tokens)."""
    model_name = str(getattr(llm_client, "model", "")).strip()
    client = getattr(llm_client, "_client", None)
    if not model_name or client is None or not hasattr(client, "models"):
        return

    started_at = asyncio.get_running_loop().time()
    try:
        await asyncio.wait_for(
            client.models.retrieve(model_name),
            timeout=_WARMUP_REQUEST_TIMEOUT_SEC,
        )
        elapsed_ms = (asyncio.get_running_loop().time() - started_at) * 1000
        logger.info(
            "llm transport warmup completed",
            extra={
                "provider": "xai",
                "model": model_name,
                "label": label,
                "elapsed_ms": round(elapsed_ms, 1),
            },
        )
    except asyncio.TimeoutError:
        logger.warning(
            "llm transport warmup timed out",
            extra={
                "provider": "xai",
                "model": model_name,
                "label": label,
                "timeout_sec": _WARMUP_REQUEST_TIMEOUT_SEC,
            },
        )
    except Exception as e:
        logger.warning(
            "llm transport warmup failed: %s",
            e,
            extra={"provider": "xai", "model": model_name, "label": label},
        )


async def warmup_llm_transport(llm_client: Any, *, label: str) -> None:
    child_llms = getattr(llm_client, "_llm_instances", None)
    if isinstance(child_llms, list):
        await asyncio.gather(
            *[
                warmup_llm_transport(child_llm, label=f"{label}_{index}")
                for index, child_llm in enumerate(child_llms)
            ],
            return_exceptions=True,
        )
        return
    if isinstance(llm_client, google.LLM):
        await warmup_google_llm_transport(llm_client, label=label)
        return
    if isinstance(llm_client, xai.responses.LLM):
        await warmup_xai_llm_transport(llm_client, label=label)
        return


def create_external_aiohttp_session(
    provider: str,
    owned_sessions: list[aiohttp.ClientSession] | None = None,
) -> aiohttp.ClientSession | None:
    proxy_url = aiohttp_proxy(provider)
    if not proxy_url:
        return None

    connector = aiohttp.TCPConnector(
        limit_per_host=50,
        keepalive_timeout=120,
    )
    session = aiohttp.ClientSession(
        proxy=proxy_url,
        connector=connector,
    )
    if owned_sessions is not None:
        owned_sessions.append(session)
    return session


async def warmup_tts_transport(tts_client: Any) -> None:
    """Warm up TTS transport before the first user turn."""
    if not isinstance(tts_client, ElevenV3TTS):
        return

    opts = getattr(tts_client, "_opts", None)
    if opts is None:
        return

    base_url = str(getattr(opts, "base_url", "")).strip().rstrip("/")
    voice_id = str(getattr(opts, "voice_id", "")).strip()
    api_key = str(getattr(opts, "api_key", "")).strip()
    if not base_url or not voice_id or not api_key:
        return

    started_at = asyncio.get_running_loop().time()
    try:
        warmup_synthesis = getattr(tts_client, "warmup_synthesis", None)
        if callable(warmup_synthesis):
            await asyncio.wait_for(
                warmup_synthesis(),
                timeout=_WARMUP_REQUEST_TIMEOUT_SEC,
            )
            elapsed_ms = (asyncio.get_running_loop().time() - started_at) * 1000
            logger.info(
                "tts synthesis warmup completed",
                extra={
                    "provider": "elevenlabs",
                    "voice_id": voice_id,
                    "elapsed_ms": round(elapsed_ms, 1),
                },
            )
            return

        session = tts_client._ensure_session()
        warmup_url = f"{base_url}/voices/{voice_id}"
        timeout = aiohttp.ClientTimeout(
            total=_WARMUP_REQUEST_TIMEOUT_SEC,
            connect=min(2.5, _WARMUP_REQUEST_TIMEOUT_SEC),
            sock_read=_WARMUP_REQUEST_TIMEOUT_SEC,
        )
        async with session.get(
            warmup_url,
            headers={"xi-api-key": api_key, "Accept": "application/json"},
            timeout=timeout,
        ) as response:
            _ = await response.read()
            if response.status >= 400:
                raise RuntimeError(f"HTTP {response.status}")

        elapsed_ms = (asyncio.get_running_loop().time() - started_at) * 1000
        logger.info(
            "tts transport warmup completed",
            extra={
                "provider": "elevenlabs",
                "voice_id": voice_id,
                "elapsed_ms": round(elapsed_ms, 1),
            },
        )
    except asyncio.TimeoutError:
        logger.warning(
            "tts transport warmup timed out",
            extra={
                "provider": "elevenlabs",
                "voice_id": voice_id,
                "timeout_sec": _WARMUP_REQUEST_TIMEOUT_SEC,
            },
        )
    except Exception as e:
        logger.warning(
            "tts transport warmup failed: %s",
            e,
            extra={"provider": "elevenlabs", "voice_id": voice_id},
        )


async def warmup_runtime_backends(
    *,
    llm_candidates: list[tuple[str, Any]],
    tts_client: Any,
    prompt_cache_warmup_llm: Any | None = None,
    prompt_cache_warmup_instructions: str | None = None,
    prompt_cache_warmup_conn_options: Any | None = None,
) -> None:
    tasks: list[asyncio.Task] = []
    seen_llm_ids: set[int] = set()

    for label, llm_client in llm_candidates:
        if llm_client is None:
            continue
        llm_id = id(llm_client)
        if llm_id in seen_llm_ids:
            continue
        seen_llm_ids.add(llm_id)
        tasks.append(
            asyncio.create_task(
                warmup_llm_transport(llm_client, label=label),
                name=f"warmup_llm_{label}",
            )
        )

    tasks.append(
        asyncio.create_task(
            warmup_tts_transport(tts_client),
            name="warmup_tts",
        )
    )

    if prompt_cache_warmup_llm is not None and prompt_cache_warmup_instructions:
        tasks.append(
            asyncio.create_task(
                warmup_llm_prompt_cache(
                    llm_client=prompt_cache_warmup_llm,
                    instructions=prompt_cache_warmup_instructions,
                    conn_options=prompt_cache_warmup_conn_options,
                ),
                name="warmup_llm_prompt_cache",
            )
        )

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def warmup_llm_prompt_cache(
    *,
    llm_client: Any,
    instructions: str,
    conn_options: Any | None,
) -> None:
    if llm_client is None or not hasattr(llm_client, "chat"):
        return

    chat_ctx = ChatContext.empty()
    chat_ctx.add_message(role="system", content=[instructions])
    chat_ctx.add_message(role="user", content=[_PROMPT_CACHE_WARMUP_USER_TEXT])

    started_at = asyncio.get_running_loop().time()
    first_chunk_at: float | None = None
    usage = None
    provider = str(getattr(llm_client, "provider", "unknown"))
    model_name = str(getattr(llm_client, "model", "unknown"))

    try:
        # Some Responses-compatible providers, including xAI, reject
        # tool_choice when the request has no tools.
        chat_kwargs: dict[str, Any] = {
            "chat_ctx": chat_ctx,
            "tools": [],
        }
        if conn_options is not None:
            chat_kwargs["conn_options"] = conn_options

        stream = llm_client.chat(**chat_kwargs)
        async with stream:
            async for chunk in stream:
                if first_chunk_at is None:
                    first_chunk_at = asyncio.get_running_loop().time()
                chunk_usage = getattr(chunk, "usage", None)
                if chunk_usage is not None:
                    usage = chunk_usage

        finished_at = asyncio.get_running_loop().time()
        ttft_ms = (
            round((first_chunk_at - started_at) * 1000, 1)
            if first_chunk_at is not None
            else None
        )
        elapsed_ms = round((finished_at - started_at) * 1000, 1)
        logger.info(
            "llm prompt-cache warmup completed",
            extra={
                "provider": provider,
                "model": model_name,
                "ttft_ms": ttft_ms,
                "elapsed_ms": elapsed_ms,
                "prompt_tokens": getattr(usage, "prompt_tokens", None),
                "prompt_cached_tokens": getattr(usage, "prompt_cached_tokens", None),
                "completion_tokens": getattr(usage, "completion_tokens", None),
            },
        )
    except Exception as e:
        logger.warning(
            "llm prompt-cache warmup failed: %s",
            e,
            extra={
                "provider": provider,
                "model": model_name,
            },
        )


def _gemini_http_timeout_ms() -> int:
    timeout_sec = GEMINI_HTTP_TIMEOUT_SEC
    if timeout_sec < 10.0:
        logger.warning(
            "GEMINI_HTTP_TIMEOUT_SEC is below the Gemini API minimum; clamping to 10s",
            extra={"configured_timeout_sec": timeout_sec},
        )
        timeout_sec = 10.0
    return int(timeout_sec * 1000)


def _genai_http_options(
    provider: str, *, timeout_ms: int | None = None
) -> genai_types.HttpOptions:
    client_args = httpx_client_args(provider)
    options: dict[str, Any] = {
        "client_args": client_args,
        "async_client_args": client_args,
    }
    if timeout_ms is not None:
        options["timeout"] = timeout_ms
    return genai_types.HttpOptions(**options)


def build_google_llm(model_name: str | None = None) -> google.LLM:
    if not GOOGLE_API_KEY:
        raise RuntimeError("GOOGLE_API_KEY is not set. Configure it in .env.local")

    resolved_model = (model_name or GEMINI_MODEL).strip()
    logger.info(
        "using Google LLM provider",
        extra={
            "provider": "google",
            "model": resolved_model,
            "temperature": GEMINI_TEMPERATURE,
            "http_timeout_sec": max(GEMINI_HTTP_TIMEOUT_SEC, 10.0),
            "egress": provider_egress("gemini"),
        },
    )

    http_options = _genai_http_options(
        "gemini",
        timeout_ms=_gemini_http_timeout_ms(),
    )

    # Direct Gemini API configuration (not LiveKit Inference). LiveKit's Google
    # LLM currently stores per-call http_options but constructs google.genai.Client
    # without them, so replace the client to enforce the per-provider egress route.
    llm = google.LLM(
        model=resolved_model,
        api_key=GOOGLE_API_KEY,
        vertexai=False,
        temperature=GEMINI_TEMPERATURE,
        max_output_tokens=GEMINI_MAX_OUTPUT_TOKENS,
        top_p=GEMINI_TOP_P,
        thinking_config={"thinking_level": GEMINI_THINKING_LEVEL},
        http_options=http_options,
    )
    llm._client = GenAIClient(
        api_key=GOOGLE_API_KEY,
        vertexai=False,
        http_options=http_options,
    )
    return llm


def build_xai_llm(model_name: str | None = None) -> xai.responses.LLM:
    if not XAI_API_KEY:
        raise RuntimeError("XAI_API_KEY is not set. Configure it in .env.local")

    resolved_model = (model_name or XAI_MODEL).strip()
    base_url = XAI_BASE_URL if XAI_BASE_URL else NOT_GIVEN
    logger.info(
        "using xAI LLM provider",
        extra={
            "provider": "xai",
            "model": resolved_model,
            "temperature": XAI_TEMPERATURE,
            "base_url": XAI_BASE_URL or "https://api.x.ai/v1",
            "egress": provider_egress("xai"),
        },
    )

    with provider_egress_env("xai"):
        return xai.responses.LLM(
            model=resolved_model,
            api_key=XAI_API_KEY,
            base_url=base_url,
            temperature=XAI_TEMPERATURE,
        )


def build_llm(model_name: str | None = None) -> Any:
    return build_llm_for_provider(LLM_PROVIDER, model_name=model_name)


def build_llm_for_provider(provider: str, model_name: str | None = None) -> Any:
    if provider == "google":
        return build_google_llm(model_name=model_name)
    if provider == "xai":
        return build_xai_llm(model_name=model_name)

    logger.warning(
        "Unknown LLM provider '%s'. Falling back to Google Gemini.",
        provider,
    )
    return build_google_llm(model_name=model_name)


def _default_llm_model_for_provider(provider: str) -> str:
    if provider == "google":
        return GEMINI_MODEL
    if provider == "xai":
        return XAI_MODEL
    return ""


def _backup_config_for_branch(branch: str) -> tuple[str, str]:
    if branch == "fast":
        return FAST_LLM_BACKUP_PROVIDER, FAST_LLM_BACKUP_MODEL
    return COMPLEX_LLM_BACKUP_PROVIDER, COMPLEX_LLM_BACKUP_MODEL


def _resolve_router_model_names(router: ModelRouter) -> dict[str, str]:
    return {
        "fast": MODEL_ROUTER_FAST_MODEL or router.fast_model_name,
        "complex": MODEL_ROUTER_COMPLEX_MODEL or router.complex_model_name,
    }


def _llm_identity(llm_client: Any) -> tuple[str, str]:
    return (
        str(getattr(llm_client, "provider", "unknown")),
        str(getattr(llm_client, "model", "unknown")),
    )


def build_llm_client_for_branch(
    *,
    branch: str,
    primary_provider: str,
    primary_model: str | None = None,
) -> tuple[Any, LLMBranchMetadata]:
    resolved_primary_model = (
        primary_model or _default_llm_model_for_provider(primary_provider)
    ).strip()
    primary_llm = build_llm_for_provider(
        primary_provider,
        model_name=resolved_primary_model or None,
    )
    primary_provider_name, primary_model_name = _llm_identity(primary_llm)

    backup_provider, backup_model = _backup_config_for_branch(branch)
    backup_provider = (backup_provider or "").strip()
    backup_model = (backup_model or "").strip()

    metadata = LLMBranchMetadata(
        branch=branch,
        primary_provider=primary_provider_name,
        primary_model=primary_model_name,
        backup_provider=backup_provider or None,
        backup_model=backup_model or None,
        uses_fallback_adapter=False,
    )

    if not USE_LIVEKIT_FALLBACK_ADAPTER:
        logger.info(
            "LiveKit LLM fallback adapter disabled; using primary LLM only for branch",
            extra={
                "branch": branch,
                "primary_provider": metadata.primary_provider,
                "primary_model": metadata.primary_model,
            },
        )
        return primary_llm, metadata

    if not backup_provider or not backup_model:
        logger.warning(
            "LLM fallback is enabled but no backup is configured for branch",
            extra={
                "branch": branch,
                "primary_provider": metadata.primary_provider,
                "primary_model": metadata.primary_model,
            },
        )
        return primary_llm, metadata

    if (
        backup_provider == metadata.primary_provider
        and backup_model == metadata.primary_model
    ):
        logger.warning(
            "LLM backup matches primary; using primary LLM only for branch",
            extra={
                "branch": branch,
                "provider": backup_provider,
                "model": backup_model,
            },
        )
        return primary_llm, metadata

    backup_llm = build_llm_for_provider(backup_provider, model_name=backup_model)
    backup_provider_name, backup_model_name = _llm_identity(backup_llm)
    fallback_metadata = LLMBranchMetadata(
        branch=branch,
        primary_provider=metadata.primary_provider,
        primary_model=metadata.primary_model,
        backup_provider=backup_provider_name,
        backup_model=backup_model_name,
        uses_fallback_adapter=True,
    )

    if backup_provider_name == metadata.primary_provider:
        logger.warning(
            "LLM fallback branch uses the same provider for primary and backup; "
            "this does not protect from provider/account/quota-wide failures",
            extra={
                "branch": branch,
                "provider": backup_provider_name,
                "primary_model": metadata.primary_model,
                "backup_model": backup_model_name,
            },
        )

    logger.info(
        "using LiveKit LLM fallback adapter",
        extra={
            "branch": branch,
            "primary_provider": fallback_metadata.primary_provider,
            "primary_model": fallback_metadata.primary_model,
            "backup_provider": fallback_metadata.backup_provider,
            "backup_model": fallback_metadata.backup_model,
            "attempt_timeout_sec": LLM_ATTEMPT_TIMEOUT_SEC,
            "max_retry_per_llm": LLM_MAX_RETRY_PER_LLM,
            "retry_interval_sec": LLM_RETRY_INTERVAL_SEC,
            "retry_on_chunk_sent": LLM_RETRY_ON_CHUNK_SENT,
        },
    )
    return (
        lk_llm.FallbackAdapter(
            llm=[primary_llm, backup_llm],
            attempt_timeout=LLM_ATTEMPT_TIMEOUT_SEC,
            max_retry_per_llm=LLM_MAX_RETRY_PER_LLM,
            retry_interval=LLM_RETRY_INTERVAL_SEC,
            retry_on_chunk_sent=LLM_RETRY_ON_CHUNK_SENT,
        ),
        fallback_metadata,
    )


def build_routed_llm_clients() -> tuple[
    dict[str, Any],
    dict[str, str],
    dict[str, LLMBranchMetadata],
]:
    route_to_provider = {
        "fast": FAST_LLM_PROVIDER,
        "complex": COMPLEX_LLM_PROVIDER,
    }
    routed_llms: dict[str, Any] = {}
    routed_metadata: dict[str, LLMBranchMetadata] = {}

    for route_name, provider in route_to_provider.items():
        routed_llms[route_name], routed_metadata[route_name] = (
            build_llm_client_for_branch(
                branch=route_name,
                primary_provider=provider,
            )
        )

    return routed_llms, route_to_provider, routed_metadata


def build_elevenlabs_tts() -> Any:
    resolved_model = ELEVENLABS_MODEL.strip()
    # Legacy env name kept for backward compatibility; now toggles custom HTTP stream adapter.
    use_custom_v3 = ELEVENLABS_V3_USE_STREAM_INPUT and resolved_model == "eleven_v3"

    voice_settings: Any = NOT_GIVEN
    if (
        ELEVENLABS_VOICE_STABILITY is not None
        or ELEVENLABS_VOICE_SIMILARITY_BOOST is not None
    ):
        if (
            ELEVENLABS_VOICE_STABILITY is None
            or ELEVENLABS_VOICE_SIMILARITY_BOOST is None
        ):
            logger.warning(
                "ElevenLabs voice settings ignored: both ELEVENLABS_VOICE_STABILITY and "
                "ELEVENLABS_VOICE_SIMILARITY_BOOST must be set together."
            )
        else:
            voice_settings = elevenlabs.VoiceSettings(
                stability=ELEVENLABS_VOICE_STABILITY,
                similarity_boost=ELEVENLABS_VOICE_SIMILARITY_BOOST,
                style=(
                    ELEVENLABS_VOICE_STYLE
                    if ELEVENLABS_VOICE_STYLE is not None
                    else NOT_GIVEN
                ),
                speed=(
                    ELEVENLABS_VOICE_SPEED
                    if ELEVENLABS_VOICE_SPEED is not None
                    else NOT_GIVEN
                ),
                use_speaker_boost=(
                    ELEVENLABS_VOICE_USE_SPEAKER_BOOST
                    if ELEVENLABS_VOICE_USE_SPEAKER_BOOST is not None
                    else NOT_GIVEN
                ),
            )

    if use_custom_v3:
        logger.info(
            "using ElevenLabs eleven_v3 custom HTTP stream TTS provider",
            extra={
                "model": resolved_model,
                "voice_id": ELEVENLABS_VOICE_ID,
                "output_format": ELEVENLABS_V3_OUTPUT_FORMAT,
                "enable_logging": ELEVENLABS_V3_ENABLE_LOGGING,
                "min_sentence_len": max(2, ELEVENLABS_V3_MIN_SENTENCE_LEN),
                "stream_context_len": max(1, ELEVENLABS_V3_STREAM_CONTEXT_LEN),
                "min_http_text_len": max(1, ELEVENLABS_V3_MIN_HTTP_TEXT_LEN),
                "merge_hold_ms": max(0, ELEVENLABS_V3_MERGE_HOLD_MS),
                "max_merged_text_len": max(1, ELEVENLABS_V3_MAX_MERGED_TEXT_LEN),
                "optimize_streaming_latency": ELEVENLABS_V3_OPTIMIZE_STREAMING_LATENCY,
                "egress": provider_egress("elevenlabs"),
            },
        )
        return ElevenV3TTS(
            voice_id=ELEVENLABS_VOICE_ID,
            model_id=resolved_model,
            voice_settings=voice_settings,
            output_format=ELEVENLABS_V3_OUTPUT_FORMAT,
            enable_logging=ELEVENLABS_V3_ENABLE_LOGGING,
            request_timeout=ELEVENLABS_V3_REQUEST_TIMEOUT_SEC,
            apply_text_normalization=ELEVENLABS_V3_APPLY_TEXT_NORMALIZATION,
            language=(ELEVENLABS_V3_LANGUAGE if ELEVENLABS_V3_LANGUAGE else NOT_GIVEN),
            optimize_streaming_latency=(
                ELEVENLABS_V3_OPTIMIZE_STREAMING_LATENCY
                if ELEVENLABS_V3_OPTIMIZE_STREAMING_LATENCY is not None
                else NOT_GIVEN
            ),
            min_http_text_len=max(1, ELEVENLABS_V3_MIN_HTTP_TEXT_LEN),
            merge_hold_ms=max(0, ELEVENLABS_V3_MERGE_HOLD_MS),
            max_merged_text_len=max(1, ELEVENLABS_V3_MAX_MERGED_TEXT_LEN),
            http_proxy=provider_proxy_url("elevenlabs"),
            tokenizer=tokenize.blingfire.SentenceTokenizer(
                min_sentence_len=max(2, ELEVENLABS_V3_MIN_SENTENCE_LEN),
                stream_context_len=max(1, ELEVENLABS_V3_STREAM_CONTEXT_LEN),
            ),
        )

    logger.info(
        "using ElevenLabs TTS provider",
        extra={"model": resolved_model, "egress": provider_egress("elevenlabs")},
    )
    with provider_egress_env("elevenlabs"):
        return elevenlabs.TTS(
            voice_id=ELEVENLABS_VOICE_ID,
            model=resolved_model,
            voice_settings=voice_settings,
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

    logger.info(
        "materialized Google credentials JSON to temporary file for runtime auth"
    )
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


def build_tts(
    external_http_sessions: list[aiohttp.ClientSession] | None = None,
) -> Any:
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
                "egress": provider_egress("cosyvoice"),
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
            http_proxy=provider_proxy_url("cosyvoice"),
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
                "egress": provider_egress("vertex_tts"),
            },
        )
        return VertexGeminiTTS(
            model=GOOGLE_TTS_MODEL.strip(),
            voice_name=GOOGLE_TTS_VOICE_NAME or "Zephyr",
            prompt=GOOGLE_TTS_PROMPT,
            location=GOOGLE_TTS_LOCATION,
            http_proxy=provider_proxy_url("vertex_tts"),
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
            True
            if resolved_model == "gemini-3.1-flash-tts-preview"
            else GOOGLE_TTS_USE_STREAMING
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
                "egress": provider_egress("google_tts"),
            },
        )
        with provider_egress_env("google_tts"):
            return google.TTS(**tts_kwargs)

    if TTS_PROVIDER == "minimax":
        if not MINIMAX_API_KEY.strip():
            logger.warning(
                "MINIMAX_API_KEY is not set. Falling back to ElevenLabs TTS."
            )
            return build_elevenlabs_tts()

        _patch_minimax_sound_effects()
        logger.info(
            "using MiniMax TTS provider",
            extra={
                "model": MINIMAX_TTS_MODEL,
                "voice_id": MINIMAX_TTS_VOICE_ID,
                "base_url": MINIMAX_TTS_BASE_URL,
                "pitch": MINIMAX_TTS_PITCH,
                "intensity": MINIMAX_TTS_INTENSITY,
                "timbre": MINIMAX_TTS_TIMBRE,
                "sound_effects": MINIMAX_TTS_SOUND_EFFECTS or None,
                "streaming": True,
                "egress": provider_egress("minimax"),
            },
        )
        return minimax.TTS(
            model=MINIMAX_TTS_MODEL,
            voice=MINIMAX_TTS_VOICE_ID,
            speed=MINIMAX_TTS_SPEED,
            vol=MINIMAX_TTS_VOLUME,
            pitch=MINIMAX_TTS_PITCH,
            intensity=MINIMAX_TTS_INTENSITY,
            timbre=MINIMAX_TTS_TIMBRE,
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
            http_session=create_external_aiohttp_session(
                "minimax",
                external_http_sessions,
            ),
        )

    return build_elevenlabs_tts()


def build_stt(
    external_http_sessions: list[aiohttp.ClientSession] | None = None,
) -> Any:
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

        with provider_egress_env("google_stt"):
            return google.STT(**stt_kwargs)

    # Default path: LiveKit inference STT.
    if STT_PROVIDER == "inference":
        with provider_egress_env("livekit_inference"):
            stt_instances: list[Any] = [
                inference.STT(
                    model=STT_INFERENCE_MODEL,
                    language=STT_INFERENCE_LANGUAGE,
                )
            ]
        fallback_descriptions = [STT_INFERENCE_MODEL]

        if STT_INFERENCE_INCLUDE_GOOGLE_FALLBACK:
            google_stt = _build_google_stt_or_none(
                log_prefix="inference->google fallback"
            )
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
                "egress": provider_egress("google_stt"),
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
            logger.warning(
                "DEEPGRAM_API_KEY is not set. Falling back to inference STT."
            )
            return inference.STT(
                model=STT_INFERENCE_MODEL,
                language=STT_INFERENCE_LANGUAGE,
            )

        logger.info(
            "using Deepgram STT provider",
            extra={
                "model": STT_DEEPGRAM_MODEL,
                "language": STT_DEEPGRAM_LANGUAGE,
                "egress": provider_egress("deepgram"),
            },
        )
        return deepgram.STT(
            api_key=DEEPGRAM_API_KEY,
            model=STT_DEEPGRAM_MODEL,
            language=STT_DEEPGRAM_LANGUAGE,
            http_session=create_external_aiohttp_session(
                "deepgram",
                external_http_sessions,
            ),
            interim_results=True,
            no_delay=True,
            endpointing_ms=STT_DEEPGRAM_ENDPOINTING_MS,
            smart_format=False,
            punctuate=True,
            filler_words=False,
            vad_events=True,
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
        model_router: ModelRouter | None = None,
        routed_llms: dict[str, Any] | None = None,
        routed_llm_providers: dict[str, str] | None = None,
        routed_llm_metadata: dict[str, LLMBranchMetadata] | None = None,
        fallback_llm: google.LLM | None = None,
        first_turn_short_greeting_audio_path: Path = _SHORT_GREETING_AUDIO_PATH,
        prerecorded_audio_sample_rate: int = 24000,
        voice_prompts: VoicePromptManager | None = None,
        prompt: str | None = None,
    ) -> None:
        self._request_end_call = request_end_call or self._noop_end_call
        self._model_router = model_router
        self._routed_llms = routed_llms or {}
        self._routed_llm_providers = routed_llm_providers or {}
        self._routed_llm_metadata = routed_llm_metadata or {}
        self._fallback_llm = fallback_llm
        self._first_turn_short_greeting_audio_path = (
            first_turn_short_greeting_audio_path
        )
        self._prerecorded_audio_sample_rate = prerecorded_audio_sample_rate
        self._voice_prompts = voice_prompts
        self._awaiting_first_user_turn = True
        self._llm_branch_started_at: dict[str, float] = {}
        self._tts_first_frame_ready_at: float | None = None
        self._tts_first_frame_yielded_at: float | None = None
        resolved_prompt = prompt if prompt is not None else get_active_prompt()
        super().__init__(
            instructions=(
                f"{resolved_prompt}\n\n"
                "Дополнительное правило: когда разговор логически завершен и ты уже "
                "сказала финальную прощальную фразу, вызови tool end_call.\n"
                "После вызова end_call не добавляй новых реплик пользователю."
            )
        )
        self._register_llm_availability_listeners()

    async def _noop_end_call(self, _: RunContext, __: str) -> str:
        return "END_CALL_DISABLED"

    async def on_user_turn_completed(self, _: Any, new_message: ChatMessage) -> None:
        if not self._awaiting_first_user_turn:
            return

        user_text = (getattr(new_message, "text_content", None) or "").strip()
        if not user_text:
            return

        self._awaiting_first_user_turn = False
        if not is_short_greeting_response(user_text):
            return

        logger.info(
            "first user turn matched short greeting regex; playing prerecorded follow-up audio"
        )
        with suppress(Exception):
            await self.session.interrupt(force=True)

        played = await play_prerecorded_audio(
            session=self.session,
            audio_path=self._first_turn_short_greeting_audio_path,
            sample_rate=self._prerecorded_audio_sample_rate,
            allow_interruptions=True,
            add_to_chat_ctx=False,
        )
        if played:
            raise StopResponse()

    async def tts_node(
        self, text: AsyncIterable[str], model_settings: Any
    ) -> AsyncIterator[rtc.AudioFrame]:
        audio_stream = Agent.default.tts_node(self, text, model_settings)
        waited_for_prompt = False
        async for frame in audio_stream:
            if not waited_for_prompt:
                self._tts_first_frame_ready_at = time.time()
                self._tts_first_frame_yielded_at = None
                if self._voice_prompts is not None:
                    await self._voice_prompts.wait_for_active_prompt()
                self._tts_first_frame_yielded_at = time.time()
                waited_for_prompt = True
            yield frame

    def _get_last_user_turn(self, chat_ctx: Any) -> tuple[str | None, bool | None]:
        if self._model_router is None:
            return None, None

        items = getattr(chat_ctx, "items", None)
        if not isinstance(items, list):
            return None, None

        for item in reversed(items):
            if not isinstance(item, ChatMessage):
                continue
            role_str = str(getattr(item, "role", "")).lower()
            if role_str != "user" and not role_str.endswith(".user"):
                continue

            fast_model: bool | None = None
            extra = getattr(item, "extra", None)
            if isinstance(extra, dict):
                flag_field = self._model_router.force_fast_flag_field
                fast_model = coerce_optional_bool(extra.get(flag_field))
            return getattr(item, "text_content", None), fast_model

        return None, None

    def _resolve_primary_llm(
        self,
        *,
        activity_llm: Any,
        route: ModelRouteResult,
    ) -> tuple[Any, str, LLMBranchMetadata | None]:
        routed_llm = self._routed_llms.get(route.selected_model)
        if routed_llm is not None:
            metadata = self._routed_llm_metadata.get(route.selected_model)
            provider = (
                metadata.primary_provider
                if metadata is not None
                else self._routed_llm_providers.get(route.selected_model, LLM_PROVIDER)
            )
            return routed_llm, provider, metadata

        logger.warning(
            "model router selected '%s' but no routed LLM client is configured; using session llm",
            route.selected_model,
        )
        metadata = self._routed_llm_metadata.get("complex")
        provider = metadata.primary_provider if metadata is not None else LLM_PROVIDER
        return activity_llm, provider, metadata

    def _log_model_route(
        self,
        *,
        original_text: str | None,
        forced_fast: bool,
        route: ModelRouteResult,
        selected_model_name: str,
        metadata: LLMBranchMetadata | None = None,
    ) -> None:
        logger.info('[MODEL_ROUTER] text="%s"', original_text or "")
        logger.info('[MODEL_ROUTER] normalized_text="%s"', route.normalized_text)
        logger.info("[MODEL_ROUTER] forced_fast=%s", forced_fast)
        logger.info('[MODEL_ROUTER] matched_rule="%s"', route.reason)
        if route.matched_value is None:
            logger.info("[MODEL_ROUTER] matched_value=null")
        else:
            logger.info('[MODEL_ROUTER] matched_value="%s"', route.matched_value)
        logger.info('[MODEL_ROUTER] selected_model="%s"', route.selected_model)
        logger.info('[MODEL_ROUTER] model_name="%s"', selected_model_name)
        if metadata is not None:
            logger.info(
                "llm route resolved",
                extra={
                    "branch": metadata.branch,
                    "primary_provider": metadata.primary_provider,
                    "primary_model": metadata.primary_model,
                    "backup_provider": metadata.backup_provider,
                    "backup_model": metadata.backup_model,
                    "uses_fallback_adapter": metadata.uses_fallback_adapter,
                },
            )

    def _register_llm_availability_listeners(self) -> None:
        for branch, llm_client in self._routed_llms.items():
            metadata = self._routed_llm_metadata.get(branch)
            if metadata is None or not metadata.uses_fallback_adapter:
                continue
            if not hasattr(llm_client, "on"):
                continue

            def _on_availability_changed(ev: Any, *, branch: str = branch) -> None:
                self._log_llm_availability_changed(branch=branch, ev=ev)

            try:
                llm_client.on("llm_availability_changed", _on_availability_changed)
            except Exception as e:
                logger.warning(
                    "failed to register llm_availability_changed listener: %s",
                    e,
                    extra={"branch": branch},
                )

    def _log_llm_availability_changed(self, *, branch: str, ev: Any) -> None:
        metadata = self._routed_llm_metadata.get(branch)
        changed_llm = getattr(ev, "llm", None)
        available = bool(getattr(ev, "available", False))
        changed_provider = str(getattr(changed_llm, "provider", "unknown"))
        changed_model = str(getattr(changed_llm, "model", "unknown"))
        started_at = self._llm_branch_started_at.get(branch)
        elapsed_ms = (
            round((asyncio.get_running_loop().time() - started_at) * 1000, 1)
            if started_at is not None
            else None
        )
        final_provider = None
        final_model = None
        if metadata is not None and not available:
            if (
                changed_provider == metadata.primary_provider
                and changed_model == metadata.primary_model
            ):
                final_provider = metadata.backup_provider
                final_model = metadata.backup_model
            else:
                final_provider = metadata.primary_provider
                final_model = metadata.primary_model

        log_method = logger.info if available else logger.warning
        log_method(
            "llm availability changed",
            extra={
                "branch": branch,
                "available": available,
                "changed_provider": changed_provider,
                "changed_model": changed_model,
                "primary_provider": metadata.primary_provider if metadata else None,
                "primary_model": metadata.primary_model if metadata else None,
                "backup_provider": metadata.backup_provider if metadata else None,
                "backup_model": metadata.backup_model if metadata else None,
                "elapsed_ms_before_fallback": elapsed_ms,
                "final_provider": final_provider,
                "final_model": final_model,
                "chunk_sent": None,
            },
        )

    async def _stream_llm(
        self,
        llm_client: Any,
        llm_provider: str,
        chat_ctx: Any,
        tools: list[Any],
        model_settings: Any,
    ) -> AsyncIterator[Any]:
        resolved_tools, tool_choice = self._resolve_tools_for_llm_call(
            tools=tools,
            model_settings=model_settings,
            llm_provider=llm_provider,
        )
        activity = self._get_activity_or_raise()
        conn_options = activity.session.conn_options.llm_conn_options
        async with llm_client.chat(
            chat_ctx=chat_ctx,
            tools=resolved_tools,
            tool_choice=tool_choice,
            conn_options=conn_options,
        ) as stream:
            async for chunk in stream:
                yield chunk

    def _resolve_tools_for_llm_call(
        self,
        *,
        tools: list[Any],
        model_settings: Any,
        llm_provider: str | None = None,
    ) -> tuple[list[Any], Any]:
        tool_choice = model_settings.tool_choice if model_settings else NOT_GIVEN
        resolved_tools = tools
        provider = str(llm_provider or LLM_PROVIDER).strip().lower()
        is_xai_provider = provider in {"xai", "api.x.ai", "x.ai"}
        # For xAI provider we keep tools disabled by default, even if declared in the agent.
        # This avoids Responses API 400 errors around tool_choice/tools coupling
        # and keeps lower TTFT for voice turns.
        if is_xai_provider and not XAI_ENABLE_TOOLS:
            if resolved_tools:
                logger.info(
                    "xAI tools are disabled by default; ignoring %d configured tool(s)",
                    len(resolved_tools),
                )
            resolved_tools = []
            tool_choice = NOT_GIVEN
        return resolved_tools, tool_choice

    async def _stream_llm_with_ttft_timeout(
        self,
        llm_client: Any,
        llm_provider: str,
        chat_ctx: Any,
        tools: list[Any],
        model_settings: Any,
        *,
        first_token_timeout: float,
    ) -> AsyncIterator[Any]:
        stream = self._stream_llm(
            llm_client,
            llm_provider,
            chat_ctx,
            tools,
            model_settings,
        )
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

    async def llm_node(
        self, chat_ctx: Any, tools: list[Any], model_settings: Any
    ) -> AsyncIterator[Any]:
        """
        Preserve fast/complex routing and provider-specific tool handling.
        In the default path, branch-local LiveKit FallbackAdapter instances own
        timeout/fallback behavior; the legacy manual retry path stays available
        behind USE_LIVEKIT_FALLBACK_ADAPTER=false.
        """
        activity = self._get_activity_or_raise()
        primary_llm = activity.llm
        primary_provider = LLM_PROVIDER
        selected_branch = "complex"
        route_metadata = self._routed_llm_metadata.get(selected_branch)
        if self._model_router is not None and self._routed_llms:
            user_text, fast_model = self._get_last_user_turn(chat_ctx)
            route = self._model_router.route(user_text, fast_model=fast_model)
            selected_branch = route.selected_model
            primary_llm, primary_provider, route_metadata = self._resolve_primary_llm(
                activity_llm=activity.llm,
                route=route,
            )
            selected_model_name = (
                route_metadata.primary_model
                if route_metadata is not None
                else str(getattr(primary_llm, "model", route.selected_model))
            )
            self._log_model_route(
                original_text=user_text,
                forced_fast=fast_model is True,
                route=route,
                selected_model_name=selected_model_name,
                metadata=route_metadata,
            )
        elif route_metadata is not None:
            primary_provider = route_metadata.primary_provider

        if route_metadata is None and isinstance(primary_llm, inference.LLM):
            async for chunk in self._stream_llm(
                primary_llm,
                "livekit_inference",
                chat_ctx,
                tools,
                model_settings,
            ):
                yield chunk
            return

        if USE_LIVEKIT_FALLBACK_ADAPTER:
            self._llm_branch_started_at[selected_branch] = (
                asyncio.get_running_loop().time()
            )
            yielded_any = False
            try:
                async for chunk in self._stream_llm(
                    primary_llm,
                    primary_provider,
                    chat_ctx,
                    tools,
                    model_settings,
                ):
                    yielded_any = True
                    yield chunk
                return
            except Exception as e:
                logger.warning(
                    "llm generation failed",
                    extra={
                        "branch": selected_branch,
                        "primary_provider": route_metadata.primary_provider
                        if route_metadata
                        else primary_provider,
                        "primary_model": route_metadata.primary_model
                        if route_metadata
                        else str(getattr(primary_llm, "model", None)),
                        "backup_provider": route_metadata.backup_provider
                        if route_metadata
                        else None,
                        "backup_model": route_metadata.backup_model
                        if route_metadata
                        else None,
                        "chunk_sent": yielded_any,
                        "error_type": type(e).__name__,
                    },
                )
                raise
            finally:
                self._llm_branch_started_at.pop(selected_branch, None)

        yielded_any = False

        try:
            async for chunk in self._stream_llm_with_ttft_timeout(
                primary_llm,
                primary_provider,
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
                "primary LLM first token timeout after %.1fs; retrying once",
                LLM_FIRST_TOKEN_TIMEOUT_SEC,
            )
        except APIStatusError as e:
            if yielded_any or e.status_code < 500:
                raise
            logger.warning(
                "primary LLM returned %s before first token; retrying once",
                e.status_code,
            )
        except Exception as e:
            if yielded_any:
                raise
            logger.warning(
                "primary LLM failed before first token; retrying once: %s", e
            )

        await asyncio.sleep(max(0.0, LLM_RETRY_DELAY_SEC))

        try:
            async for chunk in self._stream_llm_with_ttft_timeout(
                primary_llm,
                primary_provider,
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
                "retry first token timeout after %.1fs; switching to fallback model",
                LLM_FIRST_TOKEN_TIMEOUT_SEC,
            )
        except APIStatusError as e:
            if e.status_code < 500 or self._fallback_llm is None:
                raise
            logger.warning(
                "retry failed with %s; switching to fallback model", e.status_code
            )
        except Exception:
            if self._fallback_llm is None:
                raise
            logger.warning("retry failed; switching to fallback model")

        async for chunk in self._stream_llm_with_ttft_timeout(
            self._fallback_llm,
            "google",
            chat_ctx,
            tools,
            model_settings,
            first_token_timeout=LLM_FALLBACK_FIRST_TOKEN_TIMEOUT_SEC,
        ):
            yield chunk

    @function_tool
    async def end_call(
        self, context: RunContext, reason: str = "conversation_completed"
    ) -> None:
        """Use only when the conversation is logically finished and no more questions are expected.

        Rules:
        - Call only after a final goodbye phrase.
        - Never call in the middle of consultation.
        - If the user asks a new question, continue dialogue and do not call this tool.
        - After this tool call, do not produce additional user-facing text.
        """
        await self._request_end_call(context, reason)
        raise StopResponse()


def compute_server_load(agent_server: AgentServer) -> float:
    return min(len(agent_server.active_jobs) / AGENT_MAX_CONCURRENT_JOBS, 1.0)


if LIVEKIT_SELF_HOSTED:
    server = AgentServer(
        host=AGENT_HEALTH_HOST,
        port=AGENT_HEALTH_PORT,
        http_proxy=None,
        load_fnc=compute_server_load,
        load_threshold=1.0,
        num_idle_processes=AGENT_NUM_IDLE_PROCESSES,
    )
else:
    server = AgentServer()


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


def build_audio_input_options() -> room_io.AudioInputOptions:
    if AUDIO_INPUT_ENHANCEMENT in {"", "none", "off", "disable", "disabled", "false"}:
        return room_io.AudioInputOptions()

    if AUDIO_INPUT_ENHANCEMENT == "livekit":
        from livekit.plugins import noise_cancellation

        return room_io.AudioInputOptions(
            noise_cancellation=lambda params: (
                noise_cancellation.BVCTelephony()
                if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                else ai_coustics.audio_enhancement(
                    model=ai_coustics.EnhancerModel.QUAIL_VF_L
                )
            ),
        )

    if AUDIO_INPUT_ENHANCEMENT == "ai_coustics":
        return room_io.AudioInputOptions(
            noise_cancellation=ai_coustics.audio_enhancement(
                model=ai_coustics.EnhancerModel.QUAIL_VF_L
            )
        )

    logger.warning(
        "unknown AUDIO_INPUT_ENHANCEMENT=%s; audio enhancement disabled",
        AUDIO_INPUT_ENHANCEMENT,
    )
    return room_io.AudioInputOptions()


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
    runtime_warmup_task: asyncio.Task | None = None
    unrecoverable_error_task: asyncio.Task | None = None
    unrecoverable_error_response_started = False
    prompt_resolution = PromptResolution(
        prompt="",
        source="file:not_resolved",
    )
    sip_call_numbers = {
        "sip_trunk_number": None,
        "sip_client_number": None,
    }

    model_router: ModelRouter | None = None
    routed_llms: dict[str, Any] = {}
    routed_llm_providers: dict[str, str] = {}
    routed_llm_metadata: dict[str, LLMBranchMetadata] = {}
    if LLM_ROUTING_ENABLED:
        model_router = ModelRouter.from_default_config()
        router_model_names = _resolve_router_model_names(model_router)
        routed_llms, routed_llm_providers, routed_llm_metadata = (
            build_routed_llm_clients()
        )
        logger.info(
            "model router configured",
            extra={
                "fast_provider": routed_llm_providers.get("fast"),
                "complex_provider": routed_llm_providers.get("complex"),
                "fast_model": routed_llm_metadata["fast"].primary_model,
                "fast_route_label": router_model_names["fast"],
                "fast_backup_model": routed_llm_metadata["fast"].backup_model,
                "complex_model": routed_llm_metadata["complex"].primary_model,
                "complex_route_label": router_model_names["complex"],
                "complex_backup_model": routed_llm_metadata["complex"].backup_model,
                "force_fast_flag_field": model_router.force_fast_flag_field,
                "use_livekit_fallback_adapter": USE_LIVEKIT_FALLBACK_ADAPTER,
            },
        )
    elif FAST_LLM_PROVIDER or COMPLEX_LLM_PROVIDER:
        logger.warning(
            "model routing is disabled because FAST_LLM_PROVIDER and COMPLEX_LLM_PROVIDER must both be set"
        )
    else:
        logger.info("model routing is disabled; using single LLM_PROVIDER flow")

    fallback_llm = None
    if not LLM_ROUTING_ENABLED:
        session_llm, session_llm_metadata = build_llm_client_for_branch(
            branch="complex",
            primary_provider=LLM_PROVIDER,
        )
        routed_llms["complex"] = session_llm
        routed_llm_metadata["complex"] = session_llm_metadata
    else:
        session_llm = routed_llms.get("complex")

    fallback_provider = routed_llm_metadata.get("complex")
    if (
        not USE_LIVEKIT_FALLBACK_ADAPTER
        and fallback_provider is not None
        and fallback_provider.primary_provider == "google"
        and GEMINI_FALLBACK_MODEL
    ):
        fallback_llm = build_google_llm(model_name=GEMINI_FALLBACK_MODEL)

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

    audio_output_sample_rate = resolve_audio_output_sample_rate()
    external_http_sessions: list[aiohttp.ClientSession] = []

    session = AgentSession(
        stt=build_stt(external_http_sessions=external_http_sessions),
        llm=session_llm or build_llm(),
        tts=build_tts(external_http_sessions=external_http_sessions),
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
    background_audio = BackgroundAudioPlayer()
    voice_prompts = VoicePromptManager(
        session=session,
        background_audio=background_audio,
        sample_rate=audio_output_sample_rate,
        response_delay_prompt=VoicePromptSpec(
            kind="response_delay",
            audio_path=_RESPONSE_DELAY_AUDIO_PATH,
            phrase=VOICE_RESPONSE_DELAY_PHRASE,
        ),
        client_silence_prompt=VoicePromptSpec(
            kind="client_silence",
            audio_path=_CLIENT_SILENCE_AUDIO_PATH,
            phrase=VOICE_CLIENT_SILENCE_PHRASE,
        ),
        response_delay_sec=VOICE_RESPONSE_DELAY_SEC,
        client_silence_sec=VOICE_CLIENT_SILENCE_SEC,
        is_closed=close_event.is_set,
        is_end_call_scheduled=lambda: bool(end_call_task and not end_call_task.done()),
    )
    logger.info(
        "session latency guards configured",
        extra={
            "llm_first_token_timeout_sec": LLM_FIRST_TOKEN_TIMEOUT_SEC,
            "llm_fallback_first_token_timeout_sec": LLM_FALLBACK_FIRST_TOKEN_TIMEOUT_SEC,
            "llm_attempt_timeout_sec": LLM_ATTEMPT_TIMEOUT_SEC,
            "llm_max_retry_per_llm": LLM_MAX_RETRY_PER_LLM,
            "llm_retry_interval_sec": LLM_RETRY_INTERVAL_SEC,
            "llm_retry_on_chunk_sent": LLM_RETRY_ON_CHUNK_SENT,
            "use_livekit_fallback_adapter": USE_LIVEKIT_FALLBACK_ADAPTER,
            "preemptive_generation": PREEMPTIVE_GENERATION,
            "turn_detection_mode": TURN_DETECTION_MODE,
            "turn_endpointing_mode": endpointing_mode,
            "turn_min_endpointing_delay": min_endpointing_delay,
            "turn_max_endpointing_delay": max_endpointing_delay,
            "reply_watchdog_sec": REPLY_WATCHDOG_SEC,
            "voice_response_delay_sec": VOICE_RESPONSE_DELAY_SEC,
            "voice_response_delay_audio_path": str(_RESPONSE_DELAY_AUDIO_PATH)
            if _RESPONSE_DELAY_AUDIO_PATH
            else None,
            "voice_client_silence_sec": VOICE_CLIENT_SILENCE_SEC,
            "voice_client_silence_audio_path": str(_CLIENT_SILENCE_AUDIO_PATH)
            if _CLIENT_SILENCE_AUDIO_PATH
            else None,
            "voice_emergency_audio_path": str(_EMERGENCY_AUDIO_PATH)
            if _EMERGENCY_AUDIO_PATH
            else None,
        },
    )

    async def handle_unrecoverable_error(ev: Any) -> None:
        nonlocal unrecoverable_error_response_started
        if unrecoverable_error_response_started:
            return
        unrecoverable_error_response_started = True
        await voice_prompts.stop_active_prompt()

        err = getattr(ev, "error", None)
        err_type = str(getattr(err, "type", type(err).__name__))
        if _EMERGENCY_AUDIO_PATH is not None:
            played = await play_prerecorded_audio(
                session=session,
                audio_path=_EMERGENCY_AUDIO_PATH,
                sample_rate=audio_output_sample_rate,
                allow_interruptions=False,
                add_to_chat_ctx=False,
            )
            if played:
                return

        # If TTS itself is broken and no emergency audio exists, saying a text
        # fallback would likely loop back into the same failing TTS path.
        if err_type == "tts_error":
            logger.warning(
                "unrecoverable TTS error has no playable emergency audio fallback"
            )
            return

        try:
            handle = session.say(
                VOICE_EMERGENCY_PHRASE,
                allow_interruptions=False,
                add_to_chat_ctx=False,
            )
            await handle.wait_for_playout()
        except Exception as e:
            logger.exception("failed to play emergency fallback phrase: %s", e)

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
                "reply watchdog fired",
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

            transcript_items.append(
                {
                    "type": "conversation_item",
                    "role": getattr(item, "role", None),
                    "text": getattr(item, "text_content", None),
                    "interrupted": getattr(item, "interrupted", None),
                    "created_at": getattr(item, "created_at", None),
                    "metrics": safe_dump(getattr(item, "metrics", None)),
                }
            )
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
            transcript_items.append(
                {
                    "type": "user_input_transcribed",
                    "transcript": getattr(ev, "transcript", None),
                    "is_final": getattr(ev, "is_final", None),
                    "language": getattr(ev, "language", None),
                    "speaker_id": getattr(ev, "speaker_id", None),
                }
            )
            transcript = (getattr(ev, "transcript", None) or "").strip()
            if transcript:
                logger.info(
                    "user input transcribed",
                    extra={
                        "transcript": transcript,
                        "is_final": bool(getattr(ev, "is_final", False)),
                        "language": getattr(ev, "language", None),
                    },
                )
                # Any new user speech cancels a pending auto-hangup timer.
                user_activity_count += 1
                user_activity_event.set()
                if end_call_task and not end_call_task.done():
                    end_call_task.cancel()
                    end_call_task = None
                if bool(getattr(ev, "is_final", False)) and REPLY_WATCHDOG_SEC > 0:
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

    @session.on("user_state_changed")
    def on_user_state_changed(ev):
        try:
            old_state = getattr(ev, "old_state", None)
            new_state = getattr(ev, "new_state", None)
            logger.debug(
                "user state changed",
                extra={"old_state": old_state, "new_state": new_state},
            )
            if new_state == "speaking":
                voice_prompts.on_user_started_speaking()
                return
            if old_state == "speaking" and new_state == "listening":
                voice_prompts.start_response_delay_timer()
        except Exception as e:
            logger.exception("user_state_changed handler failed: %s", e)

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
            new_state = getattr(ev, "new_state", None)
            logger.debug(
                "agent state changed",
                extra={
                    "old_state": getattr(ev, "old_state", None),
                    "new_state": new_state,
                },
            )
            # If generation has started, watchdog fallback is no longer needed.
            if (
                new_state in {"thinking", "speaking"}
                and reply_watchdog_task
                and not reply_watchdog_task.done()
            ):
                reply_watchdog_task.cancel()
                reply_watchdog_task = None
            if new_state in {"thinking", "speaking"}:
                voice_prompts.cancel_client_silence_timer()
            if new_state == "speaking":
                tts_first_frame_ready_at = assistant._tts_first_frame_ready_at
                tts_first_frame_yielded_at = assistant._tts_first_frame_yielded_at
                created_at = getattr(ev, "created_at", None)
                if isinstance(created_at, (int, float)):
                    logger.info(
                        "agent playback started latency",
                        extra={
                            "tts_first_frame_ready_to_speaking_ms": round(
                                (created_at - tts_first_frame_ready_at) * 1000, 1
                            )
                            if tts_first_frame_ready_at is not None
                            else None,
                            "tts_first_frame_yielded_to_speaking_ms": round(
                                (created_at - tts_first_frame_yielded_at) * 1000, 1
                            )
                            if tts_first_frame_yielded_at is not None
                            else None,
                        },
                    )
                voice_prompts.on_agent_started_speaking()
            elif new_state == "listening":
                voice_prompts.start_client_silence_timer()
        except Exception as e:
            logger.exception("agent_state_changed handler failed: %s", e)

    @session.on("error")
    def on_error(ev):
        nonlocal unrecoverable_error_task
        try:
            err = getattr(ev, "error", None)
            source = getattr(ev, "source", None)
            recoverable = bool(getattr(err, "recoverable", False))
            log_method = logger.warning if recoverable else logger.error
            log_method(
                "agent session error",
                extra={
                    "recoverable": recoverable,
                    "error_type": getattr(err, "type", type(err).__name__),
                    "error_label": getattr(err, "label", None),
                    "source_provider": getattr(source, "provider", None),
                    "source_model": getattr(source, "model", None),
                    "source_label": getattr(source, "label", None),
                    "room": ctx.room.name,
                },
            )
            if recoverable:
                return
            if unrecoverable_error_task and not unrecoverable_error_task.done():
                return
            unrecoverable_error_task = asyncio.create_task(
                handle_unrecoverable_error(ev),
                name="handle_unrecoverable_error",
            )
        except Exception as e:
            logger.exception("error handler failed: %s", e)

    @session.on("metrics_collected")
    def on_metrics_collected(ev):
        try:
            metrics = getattr(ev, "metrics", None)
            metrics_events.append(safe_dump(metrics))
            if getattr(metrics, "type", None) == "llm_metrics":
                metadata = getattr(metrics, "metadata", None)
                logger.info(
                    "llm metrics",
                    extra={
                        "request_id": getattr(metrics, "request_id", None),
                        "ttft_ms": round(
                            float(getattr(metrics, "ttft", 0.0)) * 1000, 1
                        ),
                        "duration_ms": round(
                            float(getattr(metrics, "duration", 0.0)) * 1000, 1
                        ),
                        "prompt_tokens": getattr(metrics, "prompt_tokens", None),
                        "prompt_cached_tokens": getattr(
                            metrics, "prompt_cached_tokens", None
                        ),
                        "completion_tokens": getattr(
                            metrics, "completion_tokens", None
                        ),
                        "provider": getattr(metadata, "model_provider", None)
                        if metadata
                        else None,
                        "model": getattr(metadata, "model_name", None)
                        if metadata
                        else None,
                    },
                )
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
            "sip": {
                **sip_call_numbers,
                "prompt_source": prompt_resolution.source,
                "prompt_lookup_error": prompt_resolution.error,
            },
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
            await asyncio.wait_for(
                asyncio.shield(session_close_task), timeout=timeout_sec
            )
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
            voice_prompts.cancel_client_silence_timer()
            voice_prompts.cancel_response_delay_timer()
            await ensure_session_closed(timeout_sec=4.0)
            logger.info("ending call by deleting room", extra={"room": ctx.room.name})
            # Bound delete_room call to avoid waiting indefinitely on API edge cases.
            await asyncio.wait_for(
                asyncio.shield(ctx.delete_room(ctx.room.name)), timeout=3.0
            )
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
        voice_prompts.cancel_client_silence_timer()
        voice_prompts.cancel_response_delay_timer()

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
                await asyncio.wait_for(
                    user_activity_event.wait(), timeout=remaining_grace
                )
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
        voice_prompts.cancel_response_delay_timer()
        voice_prompts.cancel_client_silence_timer()
        if end_call_task and not end_call_task.done():
            return
        close_event.set()

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
        participant = None
        try:
            participant = await asyncio.wait_for(
                ctx.wait_for_participant(), timeout=3.0
            )
        except asyncio.TimeoutError:
            logger.info(
                "no participant available before prompt lookup; using file prompt"
            )

        sip_call_numbers = extract_sip_call_numbers(participant)
        prompt_resolution = await resolve_prompt_for_call(**sip_call_numbers)
        logger.info(
            "prompt resolved",
            extra={
                "source": prompt_resolution.source,
                "sip_trunk_number": prompt_resolution.sip_trunk_number,
                "sip_client_number": prompt_resolution.sip_client_number,
            },
        )

        assistant = Assistant(
            request_end_call=request_end_call,
            model_router=model_router,
            routed_llms=routed_llms,
            routed_llm_providers=routed_llm_providers,
            routed_llm_metadata=routed_llm_metadata,
            fallback_llm=fallback_llm,
            first_turn_short_greeting_audio_path=_SHORT_GREETING_AUDIO_PATH,
            prerecorded_audio_sample_rate=audio_output_sample_rate,
            voice_prompts=voice_prompts,
            prompt=prompt_resolution.prompt,
        )

        await session.start(
            agent=assistant,
            room=ctx.room,
            room_options=room_io.RoomOptions(
                audio_input=build_audio_input_options(),
                audio_output=room_io.AudioOutputOptions(
                    sample_rate=audio_output_sample_rate,
                    num_channels=1,
                ),
            ),
        )
        await background_audio.start(room=ctx.room, agent_session=session)

        runtime_warmup_task = asyncio.create_task(
            warmup_runtime_backends(
                llm_candidates=[
                    ("session", session.llm),
                    ("route_fast", routed_llms.get("fast")),
                    ("route_complex", routed_llms.get("complex")),
                ],
                tts_client=session.tts,
                prompt_cache_warmup_llm=session.llm,
                prompt_cache_warmup_instructions=str(assistant.instructions),
                prompt_cache_warmup_conn_options=session.conn_options.llm_conn_options,
            ),
            name="runtime_warmup_backends",
        )
        played_initial_greeting = await play_prerecorded_audio(
            session=session,
            audio_path=_INITIAL_GREETING_AUDIO_PATH,
            sample_rate=audio_output_sample_rate,
            allow_interruptions=False,
            add_to_chat_ctx=False,
        )
        # Do not block call flow if warmup is still in progress.
        if runtime_warmup_task and not runtime_warmup_task.done():
            with suppress(Exception):
                await asyncio.wait_for(
                    asyncio.shield(runtime_warmup_task),
                    timeout=0.25,
                )
        if not played_initial_greeting:
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
        logger.warning(
            "entrypoint cancelled; exporting session data to n8n before exit"
        )
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
        if unrecoverable_error_task and not unrecoverable_error_task.done():
            unrecoverable_error_task.cancel()
        if runtime_warmup_task and not runtime_warmup_task.done():
            runtime_warmup_task.cancel()
            with suppress(BaseException):
                await runtime_warmup_task
        await voice_prompts.aclose()
        with suppress(Exception):
            await background_audio.aclose()
        await ensure_session_closed(timeout_sec=2.0)
        for http_session in external_http_sessions:
            if not http_session.closed:
                with suppress(Exception):
                    await http_session.close()
        if export_task and not export_task.done():
            try:
                await asyncio.wait_for(
                    asyncio.shield(export_task), timeout=export_wait_sec
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "n8n export timed out after %ss in finalizer", export_wait_sec
                )
            except BaseException as e:
                logger.exception("n8n export finalizer failed: %s", e)


if __name__ == "__main__":
    cli.run_app(server)
