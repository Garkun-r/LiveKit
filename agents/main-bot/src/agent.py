import asyncio
import base64
import json
import logging
import os
import random
import re
import tempfile
import time
import wave
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
    cli,
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
    CALL_RECORDING_FINALIZE_TIMEOUT_SEC,
    CALL_RECORDING_STOP_TIMEOUT_SEC,
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
    GOOGLE_TTS_LANGUAGE,
    GOOGLE_TTS_LOCATION,
    GOOGLE_TTS_MIN_SENTENCE_LEN,
    GOOGLE_TTS_MODEL,
    GOOGLE_TTS_PITCH,
    GOOGLE_TTS_PROMPT,
    GOOGLE_TTS_SPEAKING_RATE,
    GOOGLE_TTS_STREAM_CONTEXT_LEN,
    GOOGLE_TTS_USE_STREAMING,
    GOOGLE_TTS_VOICE_NAME,
    INCIDENT_ENVIRONMENT,
    INCIDENT_SLOW_RESPONSE_MS,
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
    ROBOT_RUNTIME_PROFILE,
    SBER_SALUTESPEECH_AUTH_KEY,
    SBER_TTS_CA_CERT_FILE,
    SBER_TTS_ENDPOINT,
    SBER_TTS_LANGUAGE,
    SBER_TTS_MIN_SENTENCE_LEN,
    SBER_TTS_OAUTH_SCOPE,
    SBER_TTS_OAUTH_URL,
    SBER_TTS_PAINT_LOUDNESS,
    SBER_TTS_PAINT_PITCH,
    SBER_TTS_PAINT_SPEED,
    SBER_TTS_REBUILD_CACHE,
    SBER_TTS_REQUEST_TIMEOUT_SEC,
    SBER_TTS_SAMPLE_RATE,
    SBER_TTS_STREAM_CONTEXT_LEN,
    SBER_TTS_VOICE,
    STT_DEEPGRAM_ENDPOINTING_MS,
    STT_DEEPGRAM_LANGUAGE,
    STT_DEEPGRAM_MODEL,
    STT_EARLY_INTERIM_FINAL_DELAY_SEC,
    STT_EARLY_INTERIM_FINAL_ENABLED,
    STT_EARLY_INTERIM_FINAL_MIN_STABLE_INTERIMS,
    STT_GOOGLE_LANGUAGE,
    STT_GOOGLE_LOCATION,
    STT_GOOGLE_MODEL,
    STT_INFERENCE_FALLBACK_MODEL,
    STT_INFERENCE_INCLUDE_GOOGLE_FALLBACK,
    STT_INFERENCE_LANGUAGE,
    STT_INFERENCE_MODEL,
    STT_PROVIDER,
    STT_TBANK_CHUNK_MS,
    STT_TBANK_INTERIM_INTERVAL_SEC,
    STT_TBANK_LANGUAGE,
    STT_TBANK_MODEL,
    STT_TBANK_SAMPLE_RATE,
    STT_YANDEX_CHUNK_MS,
    STT_YANDEX_EOU_SENSITIVITY,
    STT_YANDEX_LANGUAGE,
    STT_YANDEX_MAX_PAUSE_BETWEEN_WORDS_HINT_MS,
    STT_YANDEX_MODEL,
    STT_YANDEX_SAMPLE_RATE,
    TBANK_VOICEKIT_API_KEY,
    TBANK_VOICEKIT_AUTHORITY,
    TBANK_VOICEKIT_ENDPOINT,
    TBANK_VOICEKIT_SECRET_KEY,
    TTS_PROVIDER,
    TTS_TBANK_FORMAT,
    TTS_TBANK_MIN_SENTENCE_LEN,
    TTS_TBANK_PITCH,
    TTS_TBANK_SAMPLE_RATE,
    TTS_TBANK_SPEAKING_RATE,
    TTS_TBANK_STREAM_CONTEXT_LEN,
    TTS_TBANK_VOICE_NAME,
    TURN_DETECTION_MODE,
    TURN_ENDPOINTING_MODE,
    TURN_MAX_ENDPOINTING_DELAY,
    TURN_MIN_ENDPOINTING_DELAY,
    USE_LIVEKIT_FALLBACK_ADAPTER,
    VERTEX_TTS_MIN_SENTENCE_LEN,
    VERTEX_TTS_STREAM_CONTEXT_LEN,
    VOICE_AUDIO_CACHE_DIR,
    VOICE_AUDIO_CACHE_ENABLED,
    VOICE_AUDIO_LEGACY_PROFILE_ID,
    VOICE_AUDIO_OUTPUT_READY_TIMEOUT_SEC,
    VOICE_CLIENT_SILENCE_AUDIO_PATH,
    VOICE_CLIENT_SILENCE_FIRST_SEC,
    VOICE_CLIENT_SILENCE_MAX_PROMPTS,
    VOICE_CLIENT_SILENCE_PHRASE,
    VOICE_CLIENT_SILENCE_SEC,
    VOICE_CLIENT_SILENCE_SECOND_AUDIO_PATH,
    VOICE_CLIENT_SILENCE_STT_GRACE_SEC,
    VOICE_EMERGENCY_AUDIO_PATH,
    VOICE_EMERGENCY_PHRASE,
    VOICE_INITIAL_GREETING_DELAY_SEC,
    VOICE_INITIAL_GREETING_PHRASE,
    VOICE_PRERECORDED_MIN_PLAYOUT_TIMEOUT_SEC,
    VOICE_PRERECORDED_PLAYOUT_GRACE_SEC,
    VOICE_PRERECORDED_PLAYOUT_RETRIES,
    VOICE_RESPONSE_DELAY_AUDIO_PATH,
    VOICE_RESPONSE_DELAY_AUDIO_PATHS,
    VOICE_RESPONSE_DELAY_PHRASE,
    VOICE_RESPONSE_DELAY_POST_GAP_SEC,
    VOICE_RESPONSE_DELAY_SEC,
    VOICE_SHORT_GREETING_DELAY_SEC,
    VOICE_SHORT_GREETING_PHRASE,
    VOICE_SIP_PARTICIPANT_WAIT_TIMEOUT_SEC,
    VOICE_SPEECH_PLAYOUT_TIMEOUT_SEC,
    VOICE_STARTUP_NO_DIALOG_TIMEOUT_SEC,
    XAI_API_KEY,
    XAI_BASE_URL,
    XAI_ENABLE_TOOLS,
    XAI_MODEL,
    XAI_TEMPERATURE,
    YANDEX_SPEECHKIT_API_KEY,
)
from cosyvoice_tts import CosyVoiceTTS
from deepgram_flux_stt import (
    DeepgramFluxSTT,
    is_deepgram_flux_model,
    normalize_deepgram_flux_model,
    normalize_language_hints,
)
from early_interim_final_stt import wrap_stt_if_enabled
from egress import (
    aiohttp_proxy,
    httpx_client_args,
    provider_egress,
    provider_egress_env,
    provider_proxy_url,
)
from eleven_v3_tts import ElevenV3TTS
from incident_logger import IncidentLogger, classify_error, component_identity
from prompt_repo import PromptResolution, get_active_prompt, resolve_prompt_for_call
from raw_call_logs import (
    RawCallLogSink,
    bind_raw_call_log_sink,
    reset_raw_call_log_sink,
)
from recording_export import (
    ACTIVE_EGRESS_STATUSES,
    finalize_room_recording,
    start_room_recording,
    stop_room_recording,
)
from robot_settings import (
    ComponentSelection,
    ResolvedRobotSettings,
    resolve_robot_settings_for_call,
)
from robot_skills import RobotSkillContext, RobotSkillRunner
from robot_tags import parse_robot_tags, sanitize_tagged_text_stream
from routing.model_router import ModelRouter, ModelRouteResult, coerce_optional_bool
from sber_tts import SberSaluteTTS
from session_export import send_session_to_n8n
from tbank_stt import TBankVoiceKitSTT
from tbank_tts import TBankVoiceKitTTS
from vertex_gemini_tts import VertexGeminiTTS
from voice_audio_cache import VoiceAudioCache
from yandex_stt import YandexSpeechKitSTT

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
_VOICE_AUDIO_CACHE_DIR = None
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
_SIP_TRACE_ATTRIBUTE_KEYS = (
    "jcall.trace_id",
    "x-traceid",
    "X-TRACEID",
    "X-TraceID",
    "sip.h.X-TRACEID",
)
_SIP_CALL_ID_ATTRIBUTE_KEYS = (
    "jcall.sip_call_id",
    "sip.callID",
    "sip.callId",
    "sip.call_id",
    "sip.h.Call-ID",
)
_WHITESPACE_RE = re.compile(r"\s+")
_SHORT_GREETING_RE = re.compile(
    r"^(?:алло|алло алло|ало|ало ало|алё|алё алё|але|але але|доброе утро|алло доброе утро|ало доброе утро|алё доброе утро|добрый день|алло добрый день|ало добрый день|алё добрый день|здравствуйте|да[,\s]+здравствуйте|да[,\s]+да[,\s]+здравствуйте|алло здравствуйте|ало здравствуйте|алё здравствуйте|девушка здравствуйте|алло девушка здравствуйте|здрасьте|здрасте|да[,\s]+(?:здрасьте|здрасте)|да[,\s]+да[,\s]+(?:здрасьте|здрасте)|алло здрасьте|ало здрасьте|алё здрасьте|девушка здрасьте|алло девушка здрасьте)[\.!\?, ]*$",
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
    attempt_timeout_sec: float = LLM_ATTEMPT_TIMEOUT_SEC
    max_retry_per_llm: int = LLM_MAX_RETRY_PER_LLM
    retry_interval_sec: float = LLM_RETRY_INTERVAL_SEC
    retry_on_chunk_sent: bool = LLM_RETRY_ON_CHUNK_SENT
    enable_tools: bool | None = None

    @property
    def has_backup(self) -> bool:
        return bool(self.backup_provider and self.backup_model)


def _component_config(component: ComponentSelection | None) -> dict[str, Any]:
    return component.config if component is not None else {}


def _config_str(
    config: dict[str, Any],
    key: str,
    default: str,
) -> str:
    value = config.get(key)
    if value is None:
        return default
    return str(value).strip()


def _config_optional_str(config: dict[str, Any], key: str) -> str:
    value = config.get(key)
    if value is None:
        return ""
    return str(value).strip()


def _config_bool(config: dict[str, Any], key: str, default: bool) -> bool:
    value = config.get(key)
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enable", "enabled"}


def _config_optional_bool(config: dict[str, Any], key: str) -> bool | None:
    value = config.get(key)
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enable", "enabled"}


def _config_float(config: dict[str, Any], key: str, default: float) -> float:
    value = config.get(key)
    if value is None or value == "":
        return default
    return float(value)


def _config_optional_float(config: dict[str, Any], key: str) -> float | None:
    value = config.get(key)
    if value is None or value == "":
        return None
    return float(value)


def _config_int(config: dict[str, Any], key: str, default: int) -> int:
    value = config.get(key)
    if value is None or value == "":
        return default
    return int(value)


def _config_optional_int(config: dict[str, Any], key: str) -> int | None:
    value = config.get(key)
    if value is None or value == "":
        return None
    return int(value)


def _config_str_list(config: dict[str, Any], key: str) -> list[str]:
    return normalize_language_hints(config.get(key))


def _component_provider(
    component: ComponentSelection | None,
    default_provider: str,
) -> str:
    if component is None:
        return default_provider
    return (
        component.provider
        or str(component.config.get("provider") or "").strip()
        or default_provider
    )


def _component_egress(component: ComponentSelection | None) -> str:
    config = _component_config(component)
    return (
        _config_optional_str(config, "egress")
        or _config_optional_str(config, "egress_mode")
        or _config_optional_str(config, "proxy_mode")
    )


def resolve_configured_audio_path(raw_path: str) -> Path | None:
    path_text = (raw_path or "").strip()
    if not path_text:
        return None

    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = _AUDIO_DIR / path
    return path


def resolve_configured_audio_paths(raw_paths: str) -> tuple[Path, ...]:
    paths: list[Path] = []
    seen: set[Path] = set()
    for raw_path in (raw_paths or "").split(","):
        path = resolve_configured_audio_path(raw_path)
        if path is None or path in seen:
            continue
        paths.append(path)
        seen.add(path)
    return tuple(paths)


def resolve_voice_audio_cache_dir(raw_path: str) -> Path:
    path = Path((raw_path or "").strip() or "cache").expanduser()
    if path.is_absolute():
        return path
    if path.parts and path.parts[0] == "audio":
        return _AUDIO_DIR.parent / path
    return _AUDIO_DIR / path


_RESPONSE_DELAY_AUDIO_PATH = resolve_configured_audio_path(
    VOICE_RESPONSE_DELAY_AUDIO_PATH
)
_RESPONSE_DELAY_AUDIO_PATHS = resolve_configured_audio_paths(
    VOICE_RESPONSE_DELAY_AUDIO_PATHS
) or ((_RESPONSE_DELAY_AUDIO_PATH,) if _RESPONSE_DELAY_AUDIO_PATH else ())
_CLIENT_SILENCE_AUDIO_PATH = resolve_configured_audio_path(
    VOICE_CLIENT_SILENCE_AUDIO_PATH
)
_CLIENT_SILENCE_SECOND_AUDIO_PATH = resolve_configured_audio_path(
    VOICE_CLIENT_SILENCE_SECOND_AUDIO_PATH
)
_CLIENT_SILENCE_AUDIO_PATHS = tuple(
    path
    for path in (_CLIENT_SILENCE_AUDIO_PATH, _CLIENT_SILENCE_SECOND_AUDIO_PATH)
    if path is not None
)
_EMERGENCY_AUDIO_PATH = resolve_configured_audio_path(VOICE_EMERGENCY_AUDIO_PATH)
_VOICE_AUDIO_CACHE_DIR = resolve_voice_audio_cache_dir(VOICE_AUDIO_CACHE_DIR)


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


def state_value(state: Any) -> Any:
    return getattr(state, "value", state)


def disconnect_reason_name(reason: Any) -> str | None:
    if reason is None:
        return None
    with suppress(Exception):
        return rtc.DisconnectReason.Name(reason)
    return str(reason)


def should_play_initial_greeting(
    *,
    close_event_set: bool,
) -> bool:
    return not close_event_set


async def wait_for_initial_greeting_delay(delay_sec: float) -> None:
    if delay_sec > 0:
        await asyncio.sleep(delay_sec)


async def wait_for_room_audio_output_ready(
    session: AgentSession,
    *,
    timeout_sec: float,
) -> bool:
    try:
        subscribed_fut = session.room_io.subscribed_fut
    except Exception as e:
        logger.warning("room audio output readiness check failed: %s", e)
        return False

    if subscribed_fut is None or subscribed_fut.done():
        return True
    if timeout_sec <= 0:
        return False

    try:
        await asyncio.wait_for(asyncio.shield(subscribed_fut), timeout=timeout_sec)
        return True
    except asyncio.TimeoutError:
        return False


async def wait_for_short_greeting_delay(delay_sec: float) -> None:
    if delay_sec > 0:
        await asyncio.sleep(delay_sec)


def clear_initial_greeting_user_turn(session: AgentSession) -> bool:
    try:
        session.clear_user_turn()
    except Exception as e:
        logger.warning("failed to clear user turn after initial greeting: %s", e)
        return False
    logger.info("user turn buffer cleared after initial greeting")
    return True


def extract_sip_call_numbers(participant: Any | None) -> dict[str, str | None]:
    if participant is None:
        return {
            "sip_trunk_number": None,
            "gateway_number": None,
            "sip_client_number": None,
        }
    if getattr(participant, "kind", None) != rtc.ParticipantKind.PARTICIPANT_KIND_SIP:
        return {
            "sip_trunk_number": None,
            "gateway_number": None,
            "sip_client_number": None,
        }

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
        "gateway_number": sip_trunk_number,
        "sip_client_number": (attributes.get("sip.phoneNumber") or "").strip() or None,
    }


def extract_sip_diagnostic_context(participant: Any | None) -> dict[str, str | None]:
    numbers = extract_sip_call_numbers(participant)
    context = {
        "did": numbers["sip_trunk_number"],
        "caller_phone": numbers["sip_client_number"],
        "trace_id": None,
        "sip_call_id": None,
    }
    if participant is None or getattr(participant, "kind", None) != (
        rtc.ParticipantKind.PARTICIPANT_KIND_SIP
    ):
        return context

    attributes = getattr(participant, "attributes", None)
    if not isinstance(attributes, dict):
        return context

    for key in _SIP_TRACE_ATTRIBUTE_KEYS:
        value = (attributes.get(key) or "").strip()
        if value:
            context["trace_id"] = value
            break
    for key in _SIP_CALL_ID_ATTRIBUTE_KEYS:
        value = (attributes.get(key) or "").strip()
        if value:
            context["sip_call_id"] = value
            break
    return context


def get_job_id(ctx: JobContext) -> str | None:
    job = getattr(ctx, "job", None)
    for key in ("id", "job_id"):
        value = getattr(job, key, None)
        if value:
            return str(value)
    return None


def event_timestamp_seconds(
    event: Any, *, default: float | None = None
) -> float | None:
    created_at = getattr(event, "created_at", None)
    if isinstance(created_at, datetime):
        return created_at.timestamp()
    if isinstance(created_at, (int, float)):
        return float(created_at)
    return default


def turn_response_latency_ms(
    *,
    user_phrase_ended_at: float | None,
    assistant_started_at: float | None,
) -> float | None:
    if user_phrase_ended_at is None or assistant_started_at is None:
        return None
    return round(max(0.0, assistant_started_at - user_phrase_ended_at) * 1000, 1)


def normalize_provider_name(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def fallback_adapter_contains_provider(component: Any, expected_provider: str) -> bool:
    expected = normalize_provider_name(expected_provider)
    if not expected:
        return False
    for attr_name in ("_stt_instances", "_llm_instances"):
        instances = getattr(component, attr_name, None)
        if not isinstance(instances, list):
            continue
        for instance in instances:
            provider = normalize_provider_name(str(getattr(instance, "provider", "")))
            if expected in provider:
                return True
    return False


def should_log_startup_provider_fallback(
    *,
    component_name: str,
    configured_provider: str,
    actual_component: Any,
) -> bool:
    configured = normalize_provider_name(configured_provider)
    actual_provider = normalize_provider_name(
        str(getattr(actual_component, "provider", ""))
    )
    if not configured:
        return False
    if component_name == "stt" and configured == "inference":
        return False
    if component_name == "tts" and configured == "elevenlabs":
        return False
    if configured in actual_provider:
        return False
    return not fallback_adapter_contains_provider(actual_component, configured)


def is_abnormal_close(reason: str | None, error: str | None) -> bool:
    if error:
        return True
    normalized = (reason or "").lower()
    if not normalized or normalized in {"none", "participant_disconnected"}:
        return False
    if normalized.startswith("end_call:"):
        return False
    return any(
        marker in normalized
        for marker in ("error", "failed", "cancelled", "timeout", "abnormal")
    )


def should_stop_recording_on_close(reason: str | None) -> bool:
    normalized = (reason or "").lower()
    return "participant_disconnected" in normalized


def should_fire_startup_no_dialog_timeout(
    *,
    timeout_sec: float,
    close_event_set: bool,
    dialog_activity_seen: bool,
    end_call_scheduled: bool,
) -> bool:
    return (
        timeout_sec > 0
        and not close_event_set
        and not dialog_activity_seen
        and not end_call_scheduled
    )


def register_stt_fallback_incident_listener(
    stt_client: Any,
    incident_log: IncidentLogger,
) -> None:
    if not hasattr(stt_client, "on"):
        return

    def _on_availability_changed(ev: Any) -> None:
        changed_stt = getattr(ev, "stt", None)
        available = bool(getattr(ev, "available", False))
        if available:
            return
        provider, model = component_identity(changed_stt)
        incident_log.record_nowait(
            "provider_fallback",
            severity="warning",
            component="stt",
            provider=provider,
            model=model,
            description="STT provider became unavailable and fallback path was used",
            payload={
                "available": available,
                "label": getattr(changed_stt, "label", None),
            },
        )

    with suppress(Exception):
        stt_client.on("stt_availability_changed", _on_availability_changed)


def register_component_metrics_listener(
    component: Any,
    *,
    component_name: str,
    sink: list[dict[str, Any]],
) -> None:
    if not hasattr(component, "on"):
        return

    def _on_metrics_collected(*args: Any, **kwargs: Any) -> None:
        event = args[0] if args else kwargs.get("event")
        metrics = getattr(event, "metrics", event)
        provider, model = component_identity(component)
        sink.append(
            {
                "component": component_name,
                "provider": provider,
                "model": model,
                "metrics": safe_dump(metrics),
            }
        )

    with suppress(Exception):
        component.on("metrics_collected", _on_metrics_collected)


def is_short_greeting_response(text: str | None) -> bool:
    if text is None:
        return False

    normalized = _WHITESPACE_RE.sub(" ", text.strip().lower())
    if not normalized:
        return False

    return bool(_SHORT_GREETING_RE.fullmatch(normalized))


def _existing_prerecorded_audio_path(audio_path: Path) -> Path | None:
    return audio_path if audio_path.exists() else None


async def resolve_short_greeting_audio_path(
    *,
    voice_audio_cache: VoiceAudioCache | None,
    phrase: str,
    prerecorded_path: Path,
) -> Path | None:
    existing_path = _existing_prerecorded_audio_path(prerecorded_path)
    if existing_path is not None:
        return existing_path
    if voice_audio_cache is None:
        return None
    return await voice_audio_cache.get_or_create(
        kind="short_greeting",
        text=phrase,
    )


async def resolve_initial_greeting_audio(
    *,
    voice_audio_cache: VoiceAudioCache | None,
    client_greeting: str | None,
    default_greeting: str,
    prerecorded_path: Path,
) -> tuple[str, Path | None]:
    resolved_client_greeting = (client_greeting or "").strip()
    if resolved_client_greeting:
        if voice_audio_cache is None:
            return resolved_client_greeting, None
        return resolved_client_greeting, await voice_audio_cache.get_or_create(
            kind="initial_greeting",
            text=resolved_client_greeting,
        )

    resolved_default_greeting = default_greeting.strip()
    return (
        resolved_default_greeting,
        _existing_prerecorded_audio_path(prerecorded_path),
    )


def is_response_delay_candidate_transcript(
    transcript: str | None,
    *,
    is_final: bool,
) -> bool:
    return is_final and bool((transcript or "").strip())


def should_start_response_delay_after_vad(
    *,
    has_final_transcript: bool,
    user_stopped_speaking: bool,
    already_started: bool,
) -> bool:
    return has_final_transcript and user_stopped_speaking and not already_started


def should_cancel_pending_reply_for_user_speech(
    *,
    stream_user_speech_revision: int,
    current_user_speech_revision: int,
    user_is_speaking: bool,
) -> bool:
    return (
        user_is_speaking
        or current_user_speech_revision > stream_user_speech_revision
    )


def should_log_slow_response_latency(
    latency_ms: int | float | None,
    threshold_ms: int,
) -> bool:
    if latency_ms is None or threshold_ms <= 0:
        return False
    return float(latency_ms) >= threshold_ms


def resolve_audio_output_sample_rate(
    tts_profile: ComponentSelection | None = None,
) -> int:
    profile_config = _component_config(tts_profile)
    provider = _component_provider(tts_profile, TTS_PROVIDER)
    if provider == "minimax":
        return _config_int(profile_config, "sample_rate", MINIMAX_TTS_SAMPLE_RATE)
    if provider == "cosyvoice":
        return _config_int(profile_config, "sample_rate", COSYVOICE_TTS_SAMPLE_RATE)
    if provider == "tbank":
        return _config_int(profile_config, "sample_rate", TTS_TBANK_SAMPLE_RATE)
    if provider == "sber":
        return _config_int(profile_config, "sample_rate", SBER_TTS_SAMPLE_RATE)
    return 24000


def speech_handle_id(handle: Any | None) -> str | None:
    value = getattr(handle, "id", None)
    return str(value) if value is not None else None


def stop_speech_handle(handle: Any | None) -> None:
    if handle is None:
        return
    with suppress(Exception):
        if hasattr(handle, "stop"):
            handle.stop()
        elif hasattr(handle, "interrupt"):
            handle.interrupt(force=True)


def wav_audio_duration_sec(audio_path: Path) -> float | None:
    try:
        with wave.open(str(audio_path), "rb") as wav_file:
            frame_rate = wav_file.getframerate()
            if frame_rate <= 0:
                return None
            return wav_file.getnframes() / frame_rate
    except (EOFError, OSError, wave.Error):
        return None


def prerecorded_playout_timeout_sec(
    *,
    audio_path: Path,
    default_timeout_sec: float | None,
) -> float | None:
    if default_timeout_sec is not None and default_timeout_sec <= 0:
        return default_timeout_sec

    duration_sec = wav_audio_duration_sec(audio_path)
    if duration_sec is None:
        return default_timeout_sec

    quick_timeout_sec = max(
        VOICE_PRERECORDED_MIN_PLAYOUT_TIMEOUT_SEC,
        duration_sec + VOICE_PRERECORDED_PLAYOUT_GRACE_SEC,
    )
    if default_timeout_sec is None:
        return quick_timeout_sec
    return min(default_timeout_sec, quick_timeout_sec)


def speech_playout_was_observed(
    *,
    speaking_revision_before: int,
    speaking_revision_after: int,
) -> bool:
    return speaking_revision_after > speaking_revision_before


async def wait_for_speech_playout(
    handle: Any,
    *,
    kind: str,
    log_label: str,
    timeout_sec: float | None = None,
    incident_log: IncidentLogger | None = None,
    payload: dict[str, Any] | None = None,
) -> bool:
    resolved_timeout_sec = (
        VOICE_SPEECH_PLAYOUT_TIMEOUT_SEC if timeout_sec is None else timeout_sec
    )
    started_at = time.monotonic()
    details = {
        "kind": kind,
        "speech_id": speech_handle_id(handle),
        "timeout_sec": resolved_timeout_sec,
        **(payload or {}),
    }
    try:
        if resolved_timeout_sec and resolved_timeout_sec > 0:
            await asyncio.wait_for(
                handle.wait_for_playout(),
                timeout=resolved_timeout_sec,
            )
        else:
            await handle.wait_for_playout()
        return True
    except asyncio.TimeoutError:
        elapsed_ms = round((time.monotonic() - started_at) * 1000, 1)
        logger.warning(
            "%s playback timeout",
            log_label,
            extra={**details, "elapsed_ms": elapsed_ms},
        )
        stop_speech_handle(handle)
        if incident_log is not None:
            incident_log.record_nowait(
                "speech_playout_timeout",
                severity="warning",
                component="voice_pipeline",
                latency_ms=elapsed_ms,
                error_type="TimeoutError",
                description=f"{log_label} playback did not finish before timeout",
                payload={**details, "elapsed_ms": elapsed_ms},
            )
        return False
    except asyncio.CancelledError:
        stop_speech_handle(handle)
        raise
    except Exception as e:
        elapsed_ms = round((time.monotonic() - started_at) * 1000, 1)
        logger.exception(
            "%s playback failed: %s",
            log_label,
            e,
            extra={**details, "elapsed_ms": elapsed_ms},
        )
        if incident_log is not None:
            incident_log.record_exception_nowait(
                "speech_playout_failed",
                e,
                severity="warning",
                component="voice_pipeline",
                description=f"{log_label} playback failed",
                payload={**details, "elapsed_ms": elapsed_ms},
            )
        return False


async def play_prerecorded_audio(
    *,
    session: AgentSession,
    audio_path: Path,
    sample_rate: int,
    allow_interruptions: bool,
    add_to_chat_ctx: bool,
    text: str = "",
    playback_kind: str = "prerecorded_audio",
    timeout_sec: float | None = None,
    retry_count: int = VOICE_PRERECORDED_PLAYOUT_RETRIES,
    incident_log: IncidentLogger | None = None,
) -> bool:
    log_label = playback_kind.replace("_", " ")
    if not audio_path.exists():
        logger.warning(
            "%s audio file not found",
            log_label,
            extra={"kind": playback_kind, "audio_path": str(audio_path)},
        )
        return False

    audio_duration_sec = wav_audio_duration_sec(audio_path)
    playout_timeout_sec = prerecorded_playout_timeout_sec(
        audio_path=audio_path,
        default_timeout_sec=timeout_sec,
    )
    max_attempts = max(1, int(retry_count) + 1)
    for attempt in range(1, max_attempts + 1):
        attempt_payload = {
            "kind": playback_kind,
            "audio_path": str(audio_path),
            "sample_rate": sample_rate,
            "text_len": len(text or ""),
            "audio_duration_sec": round(audio_duration_sec, 3)
            if audio_duration_sec is not None
            else None,
            "timeout_sec": playout_timeout_sec,
            "attempt": attempt,
            "max_attempts": max_attempts,
        }
        try:
            handle = session.say(
                text,
                audio=audio_frames_from_file(
                    str(audio_path),
                    sample_rate=sample_rate,
                    num_channels=1,
                ),
                allow_interruptions=allow_interruptions,
                add_to_chat_ctx=add_to_chat_ctx,
            )
            logger.info(
                "%s playback started",
                log_label,
                extra={**attempt_payload, "speech_id": speech_handle_id(handle)},
            )
            played = await wait_for_speech_playout(
                handle,
                kind=playback_kind,
                log_label=log_label,
                timeout_sec=playout_timeout_sec,
                incident_log=incident_log,
                payload={
                    "audio_path": str(audio_path),
                    "sample_rate": sample_rate,
                    "text_len": len(text or ""),
                    "audio_duration_sec": attempt_payload["audio_duration_sec"],
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                },
            )
            if played:
                logger.info(
                    "%s playback finished",
                    log_label,
                    extra={
                        "kind": playback_kind,
                        "audio_path": str(audio_path),
                        "speech_id": speech_handle_id(handle),
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                    },
                )
                return True
            if attempt < max_attempts:
                logger.warning(
                    "%s playback retrying after failed attempt",
                    log_label,
                    extra=attempt_payload,
                )
                continue
            return False
        except Exception as e:
            logger.exception(
                "failed to schedule %s audio '%s': %s",
                log_label,
                audio_path,
                e,
                extra=attempt_payload,
            )
            if incident_log is not None:
                incident_log.record_exception_nowait(
                    "speech_playout_failed",
                    e,
                    severity="warning",
                    component="voice_pipeline",
                    description=f"{log_label} audio could not be scheduled",
                    payload=attempt_payload,
                )
            if attempt < max_attempts:
                logger.warning(
                    "%s playback retrying after schedule failure",
                    log_label,
                    extra=attempt_payload,
                )
                continue
            return False
    return False


@dataclass(frozen=True)
class VoicePromptSpec:
    kind: str
    audio_paths: tuple[Path, ...]
    phrase: str
    prefer_prerecorded: bool = False


class VoicePromptManager:
    def __init__(
        self,
        *,
        session: AgentSession,
        background_audio: BackgroundAudioPlayer,
        voice_audio_cache: VoiceAudioCache | None,
        response_delay_prompt: VoicePromptSpec,
        client_silence_prompt: VoicePromptSpec,
        response_delay_sec: float,
        response_delay_post_gap_sec: float,
        client_silence_first_sec: float,
        client_silence_sec: float,
        client_silence_stt_grace_sec: float,
        client_silence_max_prompts: int,
        is_closed: Callable[[], bool],
        is_end_call_scheduled: Callable[[], bool],
        on_client_silence_timeout: Callable[[], Awaitable[None]],
        is_client_disconnected: Callable[[], bool],
        client_disconnect_info: Callable[[], dict[str, Any]],
        speech_playout_timeout_sec: float = VOICE_SPEECH_PLAYOUT_TIMEOUT_SEC,
        incident_log: IncidentLogger | None = None,
    ) -> None:
        self._session = session
        self._background_audio = background_audio
        self._voice_audio_cache = voice_audio_cache
        self._response_delay_prompt = response_delay_prompt
        self._client_silence_prompt = client_silence_prompt
        self._response_delay_sec = max(0.0, response_delay_sec)
        self._response_delay_post_gap_sec = max(0.0, response_delay_post_gap_sec)
        self._client_silence_first_sec = max(0.0, client_silence_first_sec)
        self._client_silence_sec = max(0.0, client_silence_sec)
        self._client_silence_stt_grace_sec = max(0.0, client_silence_stt_grace_sec)
        self._client_silence_max_prompts = max(0, client_silence_max_prompts)
        self._speech_playout_timeout_sec = max(0.0, speech_playout_timeout_sec)
        self._incident_log = incident_log
        self._is_closed = is_closed
        self._is_end_call_scheduled = is_end_call_scheduled
        self._is_client_disconnected = is_client_disconnected
        self._client_disconnect_info = client_disconnect_info
        self._on_client_silence_timeout = on_client_silence_timeout

        self._response_delay_task: asyncio.Task | None = None
        self._client_silence_task: asyncio.Task | None = None
        self._stop_active_prompt_task: asyncio.Task | None = None
        self._active_prompt_kind: str | None = None
        self._active_prompt_handle: Any | None = None
        self._active_lock = asyncio.Lock()
        self._response_delay_played = False
        self._client_silence_prompt_count = 0
        self._waiting_for_client_response = False
        self._client_silence_deadline_at: float | None = None
        self._user_is_speaking = False
        self._last_response_delay_finished_at: float | None = None
        self._prompt_after_disconnect_logged: set[tuple[str, str]] = set()

    def start_response_delay_timer(self) -> None:
        if (
            self._response_delay_sec <= 0
            or self._is_closed()
            or self._is_client_disconnected()
            or self._response_delay_played
        ):
            return
        self.cancel_response_delay_timer()
        self._response_delay_task = asyncio.create_task(
            self._run_response_delay_timer(),
            name="voice_prompt_response_delay",
        )

    def start_client_silence_timer(self) -> None:
        if (
            self._client_silence_sec <= 0
            or self._is_closed()
            or self._is_client_disconnected()
            or self._is_end_call_scheduled()
            or not self._waiting_for_client_response
        ):
            return
        self.cancel_client_silence_timer()
        self._schedule_client_silence_timer()

    def _schedule_client_silence_timer(self) -> None:
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
        self._user_is_speaking = True
        self._stop_active_prompt_task = asyncio.create_task(
            self.stop_active_prompt(),
            name="voice_prompt_stop_on_user_speech",
        )

    def on_user_finished_speaking(self) -> None:
        self._user_is_speaking = False
        if (
            self._waiting_for_client_response
            and self._client_silence_deadline_at is not None
            and self._client_silence_deadline_at <= time.monotonic()
        ):
            self._client_silence_deadline_at = (
                time.monotonic() + self._client_silence_stt_grace_sec
            )
        self.start_client_silence_timer()

    def on_user_transcribed(self, *, is_final: bool) -> None:
        self.cancel_response_delay_timer()
        self.cancel_client_silence_timer()
        self._response_delay_played = False
        self._user_is_speaking = False
        self._stop_active_prompt_task = asyncio.create_task(
            self.stop_active_prompt(),
            name="voice_prompt_stop_on_user_transcript",
        )
        if is_final:
            self._client_silence_prompt_count = 0
            self._waiting_for_client_response = False
            self._client_silence_deadline_at = None
            return
        if self._waiting_for_client_response:
            self._client_silence_deadline_at = (
                time.monotonic() + self._client_silence_sec
            )
            self.start_client_silence_timer()

    def on_agent_started_speaking(self) -> None:
        self.cancel_response_delay_timer()
        self.cancel_client_silence_timer()
        self._waiting_for_client_response = False
        self._client_silence_deadline_at = None
        if self._active_prompt_kind == "response_delay":
            self._stop_active_prompt_task = asyncio.create_task(
                self.stop_active_prompt(),
                name="voice_prompt_stop_on_agent_speech",
            )
        if self._active_prompt_kind != "client_silence":
            self._client_silence_prompt_count = 0

    def on_agent_finished_speaking(self) -> None:
        if self._is_client_disconnected():
            return
        self._client_silence_prompt_count = 0
        self._waiting_for_client_response = True
        self._client_silence_deadline_at = (
            time.monotonic() + self._client_silence_first_sec
        )
        self._user_is_speaking = False
        self.start_client_silence_timer()

    def on_client_disconnected(self) -> None:
        self.cancel_response_delay_timer()
        self.cancel_client_silence_timer()
        self._waiting_for_client_response = False
        self._client_silence_deadline_at = None
        self._user_is_speaking = False
        self._stop_active_prompt_task = asyncio.create_task(
            self.stop_active_prompt(),
            name="voice_prompt_stop_on_client_disconnect",
        )

    async def wait_for_active_prompt(self) -> None:
        kind, handle = await self._wait_for_reserved_prompt_handle()
        if kind is None:
            await self._sleep_response_delay_gap_if_needed()
            return
        if kind == "response_delay":
            await self.stop_active_prompt()
            return
        if handle is not None and not self._handle_done(handle):
            await wait_for_speech_playout(
                handle,
                kind=kind or "voice_prompt",
                log_label=f"{kind or 'voice prompt'} voice prompt",
                timeout_sec=self._speech_playout_timeout_sec,
                incident_log=self._incident_log,
            )

    async def stop_active_prompt(self) -> None:
        async with self._active_lock:
            handle = self._active_prompt_handle
            self._active_prompt_kind = None
            self._active_prompt_handle = None
        if handle is None or self._handle_done(handle):
            return
        self._stop_prompt_handle(handle)

    @staticmethod
    def _stop_prompt_handle(handle: Any | None) -> None:
        if handle is None:
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
            if self._voice_prompt_blocked_after_disconnect(
                self._response_delay_prompt.kind,
                phase="timer_elapsed",
            ):
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
            deadline_at = self._client_silence_deadline_at
            if deadline_at is None:
                deadline_at = time.monotonic() + self._client_silence_sec
                self._client_silence_deadline_at = deadline_at
            await asyncio.sleep(max(0.0, deadline_at - time.monotonic()))
            if self._is_closed() or self._is_end_call_scheduled():
                return
            if self._voice_prompt_blocked_after_disconnect(
                self._client_silence_prompt.kind,
                phase="timer_elapsed",
            ):
                return
            if not self._waiting_for_client_response or self._user_is_speaking:
                return
            if self._session.agent_state != "listening":
                return
            current_speech = self._session.current_speech
            if current_speech is not None and not current_speech.done():
                return
            if self._client_silence_prompt_count >= self._client_silence_max_prompts:
                self._waiting_for_client_response = False
                self._client_silence_deadline_at = None
                logger.info(
                    "client silence timeout reached",
                    extra={
                        "client_silence_prompt_count": self._client_silence_prompt_count,
                        "client_silence_max_prompts": self._client_silence_max_prompts,
                    },
                )
                await self._on_client_silence_timeout()
                return
            self._client_silence_prompt_count += 1
            played = await self._play_background_prompt(
                self._client_silence_prompt,
                sequence_index=self._client_silence_prompt_count - 1,
            )
            if self._is_closed() or self._is_end_call_scheduled():
                return
            if played:
                logger.info(
                    "client silence prompt completed",
                    extra={
                        "client_silence_prompt_count": self._client_silence_prompt_count,
                        "client_silence_max_prompts": self._client_silence_max_prompts,
                    },
                )
            self._waiting_for_client_response = True
            self._client_silence_deadline_at = (
                time.monotonic() + self._client_silence_sec
            )
            self._schedule_client_silence_timer()
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.exception("client silence voice prompt failed: %s", e)

    async def _play_background_prompt(
        self,
        prompt: VoicePromptSpec,
        *,
        sequence_index: int | None = None,
    ) -> bool:
        if self._voice_prompt_blocked_after_disconnect(
            prompt.kind,
            phase="before_resolve_audio",
        ):
            return False
        audio_path = await self._resolve_audio_path(
            prompt,
            sequence_index=sequence_index,
        )
        if audio_path is None:
            return False
        if self._voice_prompt_blocked_after_disconnect(
            prompt.kind,
            phase="before_playback",
        ):
            return False
        if prompt.kind == "response_delay" and self._session.agent_state == "speaking":
            return False
        if prompt.kind == "client_silence" and self._session.agent_state != "listening":
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
            played = await wait_for_speech_playout(
                handle,
                kind=prompt.kind,
                log_label=f"{prompt.kind} voice prompt",
                timeout_sec=self._speech_playout_timeout_sec,
                incident_log=self._incident_log,
                payload={"audio_path": str(audio_path)},
            )
            if not played:
                return False
            if prompt.kind == "response_delay":
                self._last_response_delay_finished_at = (
                    asyncio.get_running_loop().time()
                )
            logger.info("voice prompt finished", extra={"kind": prompt.kind})
            return True
        except asyncio.CancelledError:
            self._stop_prompt_handle(handle)
            raise
        except Exception as e:
            logger.exception(
                "failed to play background voice prompt '%s': %s",
                prompt.kind,
                e,
            )
            self._stop_prompt_handle(handle)
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

    async def _wait_for_reserved_prompt_handle(self) -> tuple[str | None, Any | None]:
        deadline = asyncio.get_running_loop().time() + 1.0
        while True:
            async with self._active_lock:
                kind = self._active_prompt_kind
                handle = self._active_prompt_handle
            if kind is None or handle is not None:
                return kind, handle
            if asyncio.get_running_loop().time() >= deadline:
                return kind, None
            await asyncio.sleep(0.01)

    async def _sleep_response_delay_gap_if_needed(self) -> None:
        if self._response_delay_post_gap_sec <= 0 or self._is_closed():
            return
        finished_at = self._last_response_delay_finished_at
        if finished_at is None:
            return
        elapsed = asyncio.get_running_loop().time() - finished_at
        remaining = self._response_delay_post_gap_sec - elapsed
        if remaining > 0:
            await asyncio.sleep(remaining)

    @staticmethod
    def _select_audio_path(
        prompt: VoicePromptSpec,
        *,
        sequence_index: int | None = None,
    ) -> Path | None:
        if not prompt.audio_paths:
            return None
        if sequence_index is not None:
            index = max(0, min(sequence_index, len(prompt.audio_paths) - 1))
            return prompt.audio_paths[index]
        existing_paths = [path for path in prompt.audio_paths if path.exists()]
        if not existing_paths:
            return random.choice(prompt.audio_paths)
        return random.choice(existing_paths)

    async def _resolve_audio_path(
        self,
        prompt: VoicePromptSpec,
        *,
        sequence_index: int | None = None,
    ) -> Path | None:
        legacy_path = self._select_audio_path(
            prompt,
            sequence_index=sequence_index,
        )
        if self._voice_audio_cache is None:
            return legacy_path
        if (
            prompt.prefer_prerecorded
            and legacy_path is not None
            and legacy_path.exists()
        ):
            return legacy_path
        return await self._voice_audio_cache.get_or_create(
            kind=prompt.kind,
            text=prompt.phrase,
            legacy_path=legacy_path,
        )

    def _voice_prompt_blocked_after_disconnect(self, kind: str, *, phase: str) -> bool:
        if not self._is_client_disconnected():
            return False
        self.cancel_response_delay_timer()
        self.cancel_client_silence_timer()
        self._waiting_for_client_response = False
        self._client_silence_deadline_at = None
        self._record_voice_prompt_after_disconnect(kind, phase=phase)
        return True

    def _record_voice_prompt_after_disconnect(self, kind: str, *, phase: str) -> None:
        if self._incident_log is None:
            return
        key = (kind, phase)
        if key in self._prompt_after_disconnect_logged:
            return
        self._prompt_after_disconnect_logged.add(key)
        disconnect_info = self._client_disconnect_info() or {}
        self._incident_log.record_nowait(
            "voice_prompt_after_disconnect",
            severity="warning",
            component="voice_pipeline",
            description="Voice prompt was blocked after linked participant disconnect",
            payload={
                "prompt_kind": kind,
                "phase": phase,
                "prompt_time": datetime.now(timezone.utc).isoformat(),
                "disconnect_time": disconnect_info.get("disconnect_time"),
                "disconnect_reason": disconnect_info.get("disconnect_reason"),
                "participant_identity": disconnect_info.get("participant_identity"),
            },
        )

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
    egress_mode: str | None = None,
) -> aiohttp.ClientSession | None:
    proxy_url = aiohttp_proxy(provider, mode_override=egress_mode)
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
    provider: str,
    *,
    timeout_ms: int | None = None,
    egress_mode: str | None = None,
) -> genai_types.HttpOptions:
    client_args = httpx_client_args(provider, mode_override=egress_mode)
    options: dict[str, Any] = {
        "client_args": client_args,
        "async_client_args": client_args,
    }
    if timeout_ms is not None:
        options["timeout"] = timeout_ms
    return genai_types.HttpOptions(**options)


def _load_google_cloud_credentials_for_vertex() -> tuple[Any, str | None]:
    scope = ["https://www.googleapis.com/auth/cloud-platform"]
    creds_file = _resolve_google_tts_credentials_file()
    if creds_file:
        return google_auth_load_credentials_from_file(creds_file, scopes=scope)
    return google_auth_default(scopes=scope)


def build_google_llm(
    model_name: str | None = None,
    llm_profile: ComponentSelection | None = None,
) -> google.LLM:
    if not GOOGLE_API_KEY:
        raise RuntimeError("GOOGLE_API_KEY is not set. Configure it in .env.local")

    profile_config = _component_config(llm_profile)
    resolved_model = (
        model_name or _config_optional_str(profile_config, "model") or GEMINI_MODEL
    ).strip()
    temperature = _config_float(profile_config, "temperature", GEMINI_TEMPERATURE)
    max_output_tokens = _config_int(
        profile_config,
        "max_output_tokens",
        GEMINI_MAX_OUTPUT_TOKENS,
    )
    top_p = _config_float(profile_config, "top_p", GEMINI_TOP_P)
    thinking_level = _config_str(
        profile_config,
        "thinking_level",
        GEMINI_THINKING_LEVEL,
    )
    egress_mode = _component_egress(llm_profile)
    logger.info(
        "using Google LLM provider",
        extra={
            "provider": "google",
            "model": resolved_model,
            "temperature": temperature,
            "http_timeout_sec": max(GEMINI_HTTP_TIMEOUT_SEC, 10.0),
            "egress": provider_egress("gemini", mode_override=egress_mode),
        },
    )

    http_options = _genai_http_options(
        "gemini",
        timeout_ms=_gemini_http_timeout_ms(),
        egress_mode=egress_mode,
    )

    # Direct Gemini API configuration (not LiveKit Inference). LiveKit's Google
    # LLM currently stores per-call http_options but constructs google.genai.Client
    # without them, so replace the client to enforce the per-provider egress route.
    llm = google.LLM(
        model=resolved_model,
        api_key=GOOGLE_API_KEY,
        vertexai=False,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        top_p=top_p,
        thinking_config={"thinking_level": thinking_level},
        http_options=http_options,
    )
    llm._client = GenAIClient(
        api_key=GOOGLE_API_KEY,
        vertexai=False,
        http_options=http_options,
    )
    return llm


def build_google_vertex_llm(
    model_name: str | None = None,
    llm_profile: ComponentSelection | None = None,
) -> google.LLM:
    profile_config = _component_config(llm_profile)
    credentials, inferred_project = _load_google_cloud_credentials_for_vertex()
    resolved_project = (
        _config_optional_str(profile_config, "project")
        or os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
        or (inferred_project or "")
    ).strip()
    if not resolved_project:
        raise RuntimeError(
            "Google Vertex project is not set. Configure project in the LLM profile, "
            "GOOGLE_CLOUD_PROJECT, or Google service account credentials."
        )

    resolved_location = (
        _config_optional_str(profile_config, "location")
        or os.getenv("GOOGLE_CLOUD_LOCATION", "").strip()
        or "global"
    )
    resolved_model = (
        model_name or _config_optional_str(profile_config, "model") or GEMINI_MODEL
    ).strip()
    temperature = _config_float(profile_config, "temperature", GEMINI_TEMPERATURE)
    max_output_tokens = _config_int(
        profile_config,
        "max_output_tokens",
        GEMINI_MAX_OUTPUT_TOKENS,
    )
    top_p = _config_float(profile_config, "top_p", GEMINI_TOP_P)
    thinking_level = _config_str(
        profile_config,
        "thinking_level",
        GEMINI_THINKING_LEVEL,
    )
    egress_mode = _component_egress(llm_profile)
    logger.info(
        "using Google Vertex LLM provider",
        extra={
            "provider": "google_vertex",
            "model": resolved_model,
            "project": resolved_project,
            "location": resolved_location,
            "temperature": temperature,
            "http_timeout_sec": max(GEMINI_HTTP_TIMEOUT_SEC, 10.0),
            "egress": provider_egress("google_vertex_llm", mode_override=egress_mode),
        },
    )

    http_options = _genai_http_options(
        "google_vertex_llm",
        timeout_ms=_gemini_http_timeout_ms(),
        egress_mode=egress_mode,
    )
    llm = google.LLM(
        model=resolved_model,
        vertexai=True,
        project=resolved_project,
        location=resolved_location,
        credentials=credentials,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        top_p=top_p,
        thinking_config={"thinking_level": thinking_level},
        http_options=http_options,
    )
    # LiveKit's Google LLM stores per-call http_options but constructs the
    # GenAI client without them, so replace the client to preserve egress route.
    llm._client = GenAIClient(
        vertexai=True,
        project=resolved_project,
        location=resolved_location,
        credentials=credentials,
        http_options=http_options,
    )
    return llm


def build_xai_llm(
    model_name: str | None = None,
    llm_profile: ComponentSelection | None = None,
) -> xai.responses.LLM:
    if not XAI_API_KEY:
        raise RuntimeError("XAI_API_KEY is not set. Configure it in .env.local")

    profile_config = _component_config(llm_profile)
    resolved_model = (
        model_name or _config_optional_str(profile_config, "model") or XAI_MODEL
    ).strip()
    configured_base_url = _config_str(profile_config, "base_url", XAI_BASE_URL)
    base_url = configured_base_url if configured_base_url else NOT_GIVEN
    temperature = _config_float(profile_config, "temperature", XAI_TEMPERATURE)
    egress_mode = _component_egress(llm_profile)
    logger.info(
        "using xAI LLM provider",
        extra={
            "provider": "xai",
            "model": resolved_model,
            "temperature": temperature,
            "base_url": configured_base_url or "https://api.x.ai/v1",
            "egress": provider_egress("xai", mode_override=egress_mode),
        },
    )

    with provider_egress_env("xai", mode_override=egress_mode):
        return xai.responses.LLM(
            model=resolved_model,
            api_key=XAI_API_KEY,
            base_url=base_url,
            temperature=temperature,
        )


def build_llm(
    model_name: str | None = None,
    llm_profile: ComponentSelection | None = None,
) -> Any:
    return build_llm_for_provider(
        _component_provider(llm_profile, LLM_PROVIDER),
        model_name=model_name,
        llm_profile=llm_profile,
    )


def build_llm_for_provider(
    provider: str,
    model_name: str | None = None,
    llm_profile: ComponentSelection | None = None,
) -> Any:
    provider = provider.strip().lower()
    if provider == "google":
        return build_google_llm(model_name=model_name, llm_profile=llm_profile)
    if provider in {
        "google_vertex",
        "google-vertex",
        "gemini_vertex",
        "vertex",
        "vertexai",
    }:
        return build_google_vertex_llm(
            model_name=model_name,
            llm_profile=llm_profile,
        )
    if provider == "xai":
        return build_xai_llm(model_name=model_name, llm_profile=llm_profile)

    logger.warning(
        "Unknown LLM provider '%s'. Falling back to Google Gemini.",
        provider,
    )
    return build_google_llm(model_name=model_name, llm_profile=llm_profile)


def _default_llm_model_for_provider(
    provider: str,
    llm_profile: ComponentSelection | None = None,
) -> str:
    configured = _config_optional_str(_component_config(llm_profile), "model")
    if configured:
        return configured
    if provider == "google":
        return GEMINI_MODEL
    if provider == "google_vertex":
        return GEMINI_MODEL
    if provider == "xai":
        return XAI_MODEL
    return ""


def _backup_config_for_branch(
    branch: str,
    *,
    primary_provider: str,
    primary_profile: ComponentSelection | None = None,
    robot_settings: ResolvedRobotSettings | None = None,
) -> tuple[str, str]:
    profile_config = _component_config(primary_profile)
    fallback_provider = _config_optional_str(profile_config, "fallback_provider")
    fallback_model = _config_optional_str(profile_config, "fallback_model")
    if fallback_model:
        return fallback_provider or (
            "google" if primary_provider == "google" else ""
        ), fallback_model

    fallback_profile = robot_settings.fallback if robot_settings is not None else None
    fallback_config = _component_config(fallback_profile)
    if fallback_config:
        branch_provider = _config_optional_str(
            fallback_config,
            f"{branch}_backup_provider",
        )
        branch_model = _config_optional_str(
            fallback_config,
            f"{branch}_backup_model",
        )
        if branch_provider or branch_model:
            return branch_provider, branch_model

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


_LLM_FALLBACK_CONFIG_KEYS: dict[str, str] = {
    "fallback_project": "project",
    "fallback_location": "location",
    "fallback_egress": "egress",
    "fallback_egress_mode": "egress",
    "fallback_temperature": "temperature",
    "fallback_max_output_tokens": "max_output_tokens",
    "fallback_top_p": "top_p",
    "fallback_thinking_level": "thinking_level",
}


def _llm_fallback_profile(
    primary_profile: ComponentSelection | None,
    *,
    provider: str,
    model: str,
) -> ComponentSelection | None:
    primary_config = _component_config(primary_profile)
    fallback_config: dict[str, Any] = {"provider": provider, "model": model}
    for source_key, target_key in _LLM_FALLBACK_CONFIG_KEYS.items():
        value = primary_config.get(source_key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        fallback_config[target_key] = value

    if set(fallback_config) == {"provider", "model"}:
        return None

    source_owner_type = (
        primary_profile.source_owner_type if primary_profile is not None else "runtime"
    )
    source_owner_key = (
        primary_profile.source_owner_key if primary_profile is not None else "base"
    )
    return ComponentSelection(
        category="llm",
        slot="backup",
        profile_key=(
            f"{primary_profile.profile_key}.fallback"
            if primary_profile is not None
            else "llm_fallback"
        ),
        kind="llm",
        provider=provider,
        config=fallback_config,
        source_owner_type=source_owner_type,
        source_owner_key=source_owner_key,
    )


def build_llm_client_for_branch(
    *,
    branch: str,
    primary_provider: str,
    primary_model: str | None = None,
    primary_profile: ComponentSelection | None = None,
    robot_settings: ResolvedRobotSettings | None = None,
) -> tuple[Any, LLMBranchMetadata]:
    profile_config = _component_config(primary_profile)
    resolved_primary_model = (
        primary_model
        or _default_llm_model_for_provider(primary_provider, primary_profile)
    ).strip()
    if primary_profile is None:
        primary_llm = build_llm_for_provider(
            primary_provider,
            model_name=resolved_primary_model or None,
        )
    else:
        primary_llm = build_llm_for_provider(
            primary_provider,
            model_name=resolved_primary_model or None,
            llm_profile=primary_profile,
        )
    primary_provider_name, primary_model_name = _llm_identity(primary_llm)

    backup_provider, backup_model = _backup_config_for_branch(
        branch,
        primary_provider=primary_provider,
        primary_profile=primary_profile,
        robot_settings=robot_settings,
    )
    backup_provider = (backup_provider or "").strip()
    backup_model = (backup_model or "").strip()
    use_fallback_adapter = _config_bool(
        profile_config,
        "use_livekit_fallback_adapter",
        USE_LIVEKIT_FALLBACK_ADAPTER,
    )
    attempt_timeout_sec = _config_float(
        profile_config,
        "attempt_timeout_sec",
        LLM_ATTEMPT_TIMEOUT_SEC,
    )
    max_retry_per_llm = _config_int(
        profile_config,
        "max_retry_per_llm",
        LLM_MAX_RETRY_PER_LLM,
    )
    retry_interval_sec = _config_float(
        profile_config,
        "retry_interval_sec",
        LLM_RETRY_INTERVAL_SEC,
    )
    retry_on_chunk_sent = _config_bool(
        profile_config,
        "retry_on_chunk_sent",
        LLM_RETRY_ON_CHUNK_SENT,
    )

    metadata = LLMBranchMetadata(
        branch=branch,
        primary_provider=primary_provider_name,
        primary_model=primary_model_name,
        backup_provider=backup_provider or None,
        backup_model=backup_model or None,
        uses_fallback_adapter=False,
        attempt_timeout_sec=attempt_timeout_sec,
        max_retry_per_llm=max_retry_per_llm,
        retry_interval_sec=retry_interval_sec,
        retry_on_chunk_sent=retry_on_chunk_sent,
        enable_tools=_config_optional_bool(profile_config, "enable_tools"),
    )

    if not use_fallback_adapter:
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

    backup_profile = _llm_fallback_profile(
        primary_profile,
        provider=backup_provider,
        model=backup_model,
    )
    backup_kwargs: dict[str, Any] = {"model_name": backup_model}
    if backup_profile is not None:
        backup_kwargs["llm_profile"] = backup_profile
    backup_llm = build_llm_for_provider(backup_provider, **backup_kwargs)
    backup_provider_name, backup_model_name = _llm_identity(backup_llm)
    fallback_metadata = LLMBranchMetadata(
        branch=branch,
        primary_provider=metadata.primary_provider,
        primary_model=metadata.primary_model,
        backup_provider=backup_provider_name,
        backup_model=backup_model_name,
        uses_fallback_adapter=True,
        attempt_timeout_sec=attempt_timeout_sec,
        max_retry_per_llm=max_retry_per_llm,
        retry_interval_sec=retry_interval_sec,
        retry_on_chunk_sent=retry_on_chunk_sent,
        enable_tools=metadata.enable_tools,
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
            "attempt_timeout_sec": attempt_timeout_sec,
            "max_retry_per_llm": max_retry_per_llm,
            "retry_interval_sec": retry_interval_sec,
            "retry_on_chunk_sent": retry_on_chunk_sent,
        },
    )
    return (
        lk_llm.FallbackAdapter(
            llm=[primary_llm, backup_llm],
            attempt_timeout=attempt_timeout_sec,
            max_retry_per_llm=max_retry_per_llm,
            retry_interval=retry_interval_sec,
            retry_on_chunk_sent=retry_on_chunk_sent,
        ),
        fallback_metadata,
    )


def build_routed_llm_clients(
    robot_settings: ResolvedRobotSettings | None = None,
) -> tuple[
    dict[str, Any],
    dict[str, str],
    dict[str, LLMBranchMetadata],
]:
    fast_profile = (
        robot_settings.component("llm_routing", "fast")
        if robot_settings is not None
        else None
    )
    complex_profile = (
        robot_settings.component("llm_routing", "complex")
        if robot_settings is not None
        else None
    )
    route_to_profile = {
        "fast": fast_profile,
        "complex": complex_profile,
    }
    route_to_provider = {
        "fast": _component_provider(fast_profile, FAST_LLM_PROVIDER),
        "complex": _component_provider(complex_profile, COMPLEX_LLM_PROVIDER),
    }
    routed_llms: dict[str, Any] = {}
    routed_metadata: dict[str, LLMBranchMetadata] = {}

    for route_name, provider in route_to_provider.items():
        routed_llms[route_name], routed_metadata[route_name] = (
            build_llm_client_for_branch(
                branch=route_name,
                primary_provider=provider,
                primary_profile=route_to_profile[route_name],
                robot_settings=robot_settings,
            )
        )

    return routed_llms, route_to_provider, routed_metadata


def build_elevenlabs_tts(tts_profile: ComponentSelection | None = None) -> Any:
    profile_config = _component_config(tts_profile)
    egress_mode = _component_egress(tts_profile)
    resolved_model = _config_str(profile_config, "model", ELEVENLABS_MODEL).strip()
    voice_id = _config_str(profile_config, "voice_id", ELEVENLABS_VOICE_ID)
    output_format = _config_str(
        profile_config,
        "output_format",
        ELEVENLABS_V3_OUTPUT_FORMAT,
    )
    enable_logging = _config_bool(
        profile_config,
        "enable_logging",
        ELEVENLABS_V3_ENABLE_LOGGING,
    )
    apply_text_normalization = _config_str(
        profile_config,
        "apply_text_normalization",
        ELEVENLABS_V3_APPLY_TEXT_NORMALIZATION,
    )
    language = _config_str(profile_config, "language", ELEVENLABS_V3_LANGUAGE)
    min_sentence_len = _config_int(
        profile_config,
        "min_sentence_len",
        ELEVENLABS_V3_MIN_SENTENCE_LEN,
    )
    stream_context_len = _config_int(
        profile_config,
        "stream_context_len",
        ELEVENLABS_V3_STREAM_CONTEXT_LEN,
    )
    # Legacy env name kept for backward compatibility; now toggles custom HTTP stream adapter.
    use_custom_v3 = (
        _config_bool(
            profile_config,
            "use_stream_input",
            ELEVENLABS_V3_USE_STREAM_INPUT,
        )
        and resolved_model == "eleven_v3"
    )

    voice_settings: Any = NOT_GIVEN
    voice_stability = _config_optional_float(profile_config, "voice_stability")
    if voice_stability is None:
        voice_stability = ELEVENLABS_VOICE_STABILITY
    voice_similarity_boost = _config_optional_float(
        profile_config,
        "voice_similarity_boost",
    )
    if voice_similarity_boost is None:
        voice_similarity_boost = ELEVENLABS_VOICE_SIMILARITY_BOOST
    voice_style = _config_optional_float(profile_config, "voice_style")
    if voice_style is None:
        voice_style = ELEVENLABS_VOICE_STYLE
    voice_speed = _config_optional_float(profile_config, "voice_speed")
    if voice_speed is None:
        voice_speed = ELEVENLABS_VOICE_SPEED
    voice_use_speaker_boost = _config_optional_bool(
        profile_config,
        "voice_use_speaker_boost",
    )
    if voice_use_speaker_boost is None:
        voice_use_speaker_boost = ELEVENLABS_VOICE_USE_SPEAKER_BOOST
    if voice_stability is not None or voice_similarity_boost is not None:
        if voice_stability is None or voice_similarity_boost is None:
            logger.warning(
                "ElevenLabs voice settings ignored: both ELEVENLABS_VOICE_STABILITY and "
                "ELEVENLABS_VOICE_SIMILARITY_BOOST must be set together."
            )
        else:
            voice_settings = elevenlabs.VoiceSettings(
                stability=voice_stability,
                similarity_boost=voice_similarity_boost,
                style=(voice_style if voice_style is not None else NOT_GIVEN),
                speed=(voice_speed if voice_speed is not None else NOT_GIVEN),
                use_speaker_boost=(
                    voice_use_speaker_boost
                    if voice_use_speaker_boost is not None
                    else NOT_GIVEN
                ),
            )

    if use_custom_v3:
        logger.info(
            "using ElevenLabs eleven_v3 custom HTTP stream TTS provider",
            extra={
                "model": resolved_model,
                "voice_id": voice_id,
                "output_format": output_format,
                "enable_logging": enable_logging,
                "min_sentence_len": max(2, min_sentence_len),
                "stream_context_len": max(1, stream_context_len),
                "min_http_text_len": max(1, ELEVENLABS_V3_MIN_HTTP_TEXT_LEN),
                "merge_hold_ms": max(0, ELEVENLABS_V3_MERGE_HOLD_MS),
                "max_merged_text_len": max(1, ELEVENLABS_V3_MAX_MERGED_TEXT_LEN),
                "optimize_streaming_latency": ELEVENLABS_V3_OPTIMIZE_STREAMING_LATENCY,
                "egress": provider_egress("elevenlabs", mode_override=egress_mode),
            },
        )
        return ElevenV3TTS(
            voice_id=voice_id,
            model_id=resolved_model,
            voice_settings=voice_settings,
            output_format=output_format,
            enable_logging=enable_logging,
            request_timeout=ELEVENLABS_V3_REQUEST_TIMEOUT_SEC,
            apply_text_normalization=apply_text_normalization,
            language=(language if language else NOT_GIVEN),
            optimize_streaming_latency=(
                ELEVENLABS_V3_OPTIMIZE_STREAMING_LATENCY
                if ELEVENLABS_V3_OPTIMIZE_STREAMING_LATENCY is not None
                else NOT_GIVEN
            ),
            min_http_text_len=max(1, ELEVENLABS_V3_MIN_HTTP_TEXT_LEN),
            merge_hold_ms=max(0, ELEVENLABS_V3_MERGE_HOLD_MS),
            max_merged_text_len=max(1, ELEVENLABS_V3_MAX_MERGED_TEXT_LEN),
            http_proxy=provider_proxy_url("elevenlabs", mode_override=egress_mode),
            tokenizer=tokenize.blingfire.SentenceTokenizer(
                min_sentence_len=max(2, min_sentence_len),
                stream_context_len=max(1, stream_context_len),
            ),
        )

    logger.info(
        "using ElevenLabs TTS provider",
        extra={
            "model": resolved_model,
            "egress": provider_egress("elevenlabs", mode_override=egress_mode),
        },
    )
    with provider_egress_env("elevenlabs", mode_override=egress_mode):
        return elevenlabs.TTS(
            voice_id=voice_id,
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
    tts_profile: ComponentSelection | None = None,
) -> Any:
    profile_config = _component_config(tts_profile)
    configured_tts_provider = _component_provider(tts_profile, TTS_PROVIDER)
    if configured_tts_provider not in {
        "google",
        "vertex",
        "minimax",
        "cosyvoice",
        "tbank",
        "sber",
        "elevenlabs",
    }:
        logger.warning(
            "Unknown TTS_PROVIDER='%s'. Falling back to ElevenLabs.",
            configured_tts_provider,
        )
        return build_elevenlabs_tts(tts_profile)

    if configured_tts_provider == "tbank":
        if not TBANK_VOICEKIT_API_KEY.strip() or not TBANK_VOICEKIT_SECRET_KEY.strip():
            raise RuntimeError(
                "T-Bank VoiceKit TTS is configured but TBANK_VOICEKIT_API_KEY "
                "or TBANK_VOICEKIT_SECRET_KEY is missing."
            )

        tbank_voice_name = _config_str(
            profile_config,
            "voice_name",
            TTS_TBANK_VOICE_NAME,
        )
        tbank_format = _config_str(profile_config, "format", TTS_TBANK_FORMAT)
        tbank_sample_rate = _config_int(
            profile_config,
            "sample_rate",
            TTS_TBANK_SAMPLE_RATE,
        )
        tbank_speaking_rate = _config_float(
            profile_config,
            "speaking_rate",
            TTS_TBANK_SPEAKING_RATE,
        )
        tbank_pitch = _config_float(profile_config, "pitch", TTS_TBANK_PITCH)
        tbank_min_sentence_len = _config_int(
            profile_config,
            "min_sentence_len",
            TTS_TBANK_MIN_SENTENCE_LEN,
        )
        tbank_stream_context_len = _config_int(
            profile_config,
            "stream_context_len",
            TTS_TBANK_STREAM_CONTEXT_LEN,
        )
        tbank_endpoint = _config_str(
            profile_config,
            "endpoint",
            TBANK_VOICEKIT_ENDPOINT,
        )
        tbank_authority = _config_str(
            profile_config,
            "authority",
            TBANK_VOICEKIT_AUTHORITY,
        )
        egress_mode = _component_egress(tts_profile)
        logger.info(
            "using T-Bank VoiceKit TTS provider",
            extra={
                "voice": tbank_voice_name,
                "format": tbank_format,
                "sample_rate": tbank_sample_rate,
                "speaking_rate": tbank_speaking_rate,
                "pitch": tbank_pitch,
                "min_sentence_len": max(2, tbank_min_sentence_len),
                "stream_context_len": max(1, tbank_stream_context_len),
                "endpoint": tbank_endpoint,
                "authority": tbank_authority or None,
                "egress": provider_egress("tbank_tts", mode_override=egress_mode),
            },
        )
        with provider_egress_env("tbank_tts", mode_override=egress_mode):
            return TBankVoiceKitTTS(
                api_key=TBANK_VOICEKIT_API_KEY,
                secret_key=TBANK_VOICEKIT_SECRET_KEY,
                voice_name=tbank_voice_name,
                audio_format=tbank_format,
                sample_rate=tbank_sample_rate,
                speaking_rate=tbank_speaking_rate,
                pitch=tbank_pitch,
                endpoint=tbank_endpoint,
                authority=tbank_authority,
                tokenizer_obj=tokenize.blingfire.SentenceTokenizer(
                    min_sentence_len=max(2, tbank_min_sentence_len),
                    stream_context_len=max(1, tbank_stream_context_len),
                ),
            )

    if configured_tts_provider == "cosyvoice":
        cosyvoice_transport = _config_str(
            profile_config,
            "transport",
            COSYVOICE_TTS_TRANSPORT,
        )
        if cosyvoice_transport != "websocket":
            raise RuntimeError(
                "CosyVoice low-latency mode requires WebSocket transport. "
                "Set COSYVOICE_TTS_TRANSPORT=websocket."
            )

        api_key_env_name = _config_str(
            profile_config,
            "api_key_env_name",
            COSYVOICE_API_KEY_ENV_NAME,
        )
        resolved_api_key = (
            os.getenv(api_key_env_name) or COSYVOICE_API_KEY or ""
        ).strip()
        if not resolved_api_key:
            raise RuntimeError(
                f"{api_key_env_name or 'COSYVOICE_API_KEY'} is not set. "
                "CosyVoice provider is configured without API key."
            )
        cosyvoice_profile = _config_str(profile_config, "profile", COSYVOICE_PROFILE)
        cosyvoice_model = _config_str(profile_config, "model", COSYVOICE_TTS_MODEL)
        cosyvoice_region = _config_str(profile_config, "region", COSYVOICE_TTS_REGION)
        cosyvoice_ws_url = _config_str(profile_config, "ws_url", COSYVOICE_TTS_WS_URL)
        cosyvoice_voice_mode = _config_str(
            profile_config,
            "voice_mode",
            COSYVOICE_TTS_VOICE_MODE,
        )
        cosyvoice_voice_id = _config_str(
            profile_config,
            "voice_id",
            COSYVOICE_TTS_VOICE_ID,
        )
        cosyvoice_clone_voice_id = _config_str(
            profile_config,
            "clone_voice_id",
            COSYVOICE_TTS_CLONE_VOICE_ID,
        )
        cosyvoice_design_voice_id = _config_str(
            profile_config,
            "design_voice_id",
            COSYVOICE_TTS_DESIGN_VOICE_ID,
        )
        cosyvoice_format = _config_str(profile_config, "format", COSYVOICE_TTS_FORMAT)
        cosyvoice_sample_rate = _config_int(
            profile_config,
            "sample_rate",
            COSYVOICE_TTS_SAMPLE_RATE,
        )
        cosyvoice_rate = _config_float(profile_config, "rate", COSYVOICE_TTS_RATE)
        cosyvoice_pitch = _config_float(profile_config, "pitch", COSYVOICE_TTS_PITCH)
        cosyvoice_volume = _config_int(profile_config, "volume", COSYVOICE_TTS_VOLUME)
        cosyvoice_connection_reuse = _config_bool(
            profile_config,
            "connection_reuse",
            COSYVOICE_TTS_CONNECTION_REUSE,
        )
        cosyvoice_playback_on_first_chunk = _config_bool(
            profile_config,
            "playback_on_first_chunk",
            COSYVOICE_TTS_PLAYBACK_ON_FIRST_CHUNK,
        )
        cosyvoice_min_sentence_len = _config_int(
            profile_config,
            "min_sentence_len",
            COSYVOICE_TTS_MIN_SENTENCE_LEN,
        )
        cosyvoice_stream_context_len = _config_int(
            profile_config,
            "stream_context_len",
            COSYVOICE_TTS_STREAM_CONTEXT_LEN,
        )

        logger.info(
            "using CosyVoice TTS provider",
            extra={
                "profile": cosyvoice_profile,
                "model": cosyvoice_model,
                "transport": cosyvoice_transport,
                "region": cosyvoice_region,
                "format": cosyvoice_format,
                "sample_rate": cosyvoice_sample_rate,
                "voice_mode": cosyvoice_voice_mode,
                "connection_reuse": cosyvoice_connection_reuse,
                "playback_on_first_chunk": cosyvoice_playback_on_first_chunk,
                "min_sentence_len": max(2, cosyvoice_min_sentence_len),
                "stream_context_len": max(1, cosyvoice_stream_context_len),
                "egress": provider_egress("cosyvoice"),
            },
        )
        return CosyVoiceTTS(
            api_key=resolved_api_key,
            model=cosyvoice_model.strip(),
            region=cosyvoice_region,
            ws_url=cosyvoice_ws_url,
            voice_mode=cosyvoice_voice_mode,
            voice_id=cosyvoice_voice_id,
            clone_voice_id=cosyvoice_clone_voice_id,
            design_voice_id=cosyvoice_design_voice_id,
            audio_format=cosyvoice_format,
            sample_rate=cosyvoice_sample_rate,
            rate=cosyvoice_rate,
            pitch=cosyvoice_pitch,
            volume=cosyvoice_volume,
            connection_reuse=cosyvoice_connection_reuse,
            playback_on_first_chunk=cosyvoice_playback_on_first_chunk,
            http_proxy=provider_proxy_url("cosyvoice"),
            tokenizer_obj=tokenize.blingfire.SentenceTokenizer(
                min_sentence_len=max(2, cosyvoice_min_sentence_len),
                stream_context_len=max(1, cosyvoice_stream_context_len),
            ),
        )

    if configured_tts_provider == "sber":
        if not SBER_SALUTESPEECH_AUTH_KEY.strip():
            raise RuntimeError(
                "SBER_SALUTESPEECH_AUTH_KEY is not set. "
                "Sber SaluteSpeech provider is configured without auth key."
            )

        sber_endpoint = _config_str(profile_config, "endpoint", SBER_TTS_ENDPOINT)
        sber_voice = _config_str(profile_config, "voice", SBER_TTS_VOICE)
        sber_language = _config_str(profile_config, "language", SBER_TTS_LANGUAGE)
        sber_sample_rate = _config_int(
            profile_config,
            "sample_rate",
            SBER_TTS_SAMPLE_RATE,
        )
        sber_paint_pitch = _config_str(
            profile_config,
            "paint_pitch",
            SBER_TTS_PAINT_PITCH,
        )
        sber_paint_speed = _config_str(
            profile_config,
            "paint_speed",
            SBER_TTS_PAINT_SPEED,
        )
        sber_paint_loudness = _config_str(
            profile_config,
            "paint_loudness",
            SBER_TTS_PAINT_LOUDNESS,
        )
        sber_min_sentence_len = _config_int(
            profile_config,
            "min_sentence_len",
            SBER_TTS_MIN_SENTENCE_LEN,
        )
        sber_stream_context_len = _config_int(
            profile_config,
            "stream_context_len",
            SBER_TTS_STREAM_CONTEXT_LEN,
        )
        egress_mode = _component_egress(tts_profile)
        logger.info(
            "using Sber SaluteSpeech TTS provider",
            extra={
                "endpoint": sber_endpoint,
                "voice": sber_voice,
                "language": sber_language,
                "sample_rate": sber_sample_rate,
                "ca_cert_file": bool(SBER_TTS_CA_CERT_FILE),
                "paint_pitch": sber_paint_pitch,
                "paint_speed": sber_paint_speed,
                "paint_loudness": sber_paint_loudness,
                "min_sentence_len": max(2, sber_min_sentence_len),
                "stream_context_len": max(1, sber_stream_context_len),
                "egress": provider_egress("sber_tts", mode_override=egress_mode),
            },
        )
        with provider_egress_env("sber_tts", mode_override=egress_mode):
            return SberSaluteTTS(
                auth_key=SBER_SALUTESPEECH_AUTH_KEY,
                oauth_scope=SBER_TTS_OAUTH_SCOPE,
                oauth_url=SBER_TTS_OAUTH_URL,
                endpoint=sber_endpoint,
                voice=sber_voice,
                language=sber_language,
                sample_rate=sber_sample_rate,
                ca_cert_file=SBER_TTS_CA_CERT_FILE or None,
                paint_pitch=sber_paint_pitch,
                paint_speed=sber_paint_speed,
                paint_loudness=sber_paint_loudness,
                request_timeout=SBER_TTS_REQUEST_TIMEOUT_SEC,
                rebuild_cache=SBER_TTS_REBUILD_CACHE,
                http_proxy=provider_proxy_url("sber_tts", mode_override=egress_mode),
                tokenizer_obj=tokenize.blingfire.SentenceTokenizer(
                    min_sentence_len=max(2, sber_min_sentence_len),
                    stream_context_len=max(1, sber_stream_context_len),
                ),
            )

    if configured_tts_provider == "vertex":
        resolved_creds_file = _resolve_google_tts_credentials_file()
        if resolved_creds_file and not os.path.exists(resolved_creds_file):
            logger.warning(
                "GOOGLE_TTS_CREDENTIALS_FILE does not exist: %s. Falling back to ElevenLabs TTS.",
                resolved_creds_file,
            )
            return build_elevenlabs_tts(tts_profile)
        if not _google_tts_credentials_available():
            return build_elevenlabs_tts(tts_profile)

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
            model=_config_str(profile_config, "model", GOOGLE_TTS_MODEL).strip(),
            voice_name=_config_str(profile_config, "voice_name", GOOGLE_TTS_VOICE_NAME)
            or "Zephyr",
            prompt=_config_str(profile_config, "prompt", GOOGLE_TTS_PROMPT),
            location=_config_str(profile_config, "location", GOOGLE_TTS_LOCATION),
            http_proxy=provider_proxy_url("vertex_tts"),
            tokenizer_obj=tokenize.blingfire.SentenceTokenizer(
                min_sentence_len=max(
                    2,
                    _config_int(
                        profile_config,
                        "min_sentence_len",
                        VERTEX_TTS_MIN_SENTENCE_LEN,
                    ),
                ),
                stream_context_len=max(
                    1,
                    _config_int(
                        profile_config,
                        "stream_context_len",
                        VERTEX_TTS_STREAM_CONTEXT_LEN,
                    ),
                ),
            ),
        )

    if configured_tts_provider == "google":
        resolved_model = _config_str(profile_config, "model", GOOGLE_TTS_MODEL).strip()
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
            return build_elevenlabs_tts(tts_profile)
        if not _google_tts_credentials_available():
            return build_elevenlabs_tts(tts_profile)

        supported_google_tts_models = {
            "gemini-3.1-flash-tts-preview",
            "gemini-2.5-flash-tts",
            "gemini-2.5-flash-lite-preview-tts",
            "gemini-2.5-pro-tts",
            "chirp_3",
        }
        if resolved_model not in supported_google_tts_models:
            fallback_model = (
                _config_str(profile_config, "fallback_model", GOOGLE_TTS_FALLBACK_MODEL)
                or "gemini-3.1-flash-tts-preview"
            )
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
            else _config_bool(profile_config, "use_streaming", GOOGLE_TTS_USE_STREAMING)
        )
        google_tts_language = _config_str(
            profile_config,
            "language",
            GOOGLE_TTS_LANGUAGE,
        )
        google_tts_speaking_rate = _config_float(
            profile_config,
            "speaking_rate",
            GOOGLE_TTS_SPEAKING_RATE,
        )
        google_tts_pitch = _config_float(profile_config, "pitch", GOOGLE_TTS_PITCH)
        google_tts_location = _config_str(
            profile_config,
            "location",
            GOOGLE_TTS_LOCATION,
        )
        google_tts_min_sentence_len = _config_int(
            profile_config,
            "min_sentence_len",
            GOOGLE_TTS_MIN_SENTENCE_LEN,
        )
        google_tts_stream_context_len = _config_int(
            profile_config,
            "stream_context_len",
            GOOGLE_TTS_STREAM_CONTEXT_LEN,
        )

        tts_kwargs: dict[str, Any] = {
            "model_name": resolved_model,
            "prompt": _config_str(profile_config, "prompt", GOOGLE_TTS_PROMPT),
            "language": google_tts_language,
            "speaking_rate": google_tts_speaking_rate,
            "pitch": google_tts_pitch,
            "use_streaming": resolved_streaming,
            # Use configured Google Cloud Text-to-Speech endpoint location.
            "location": google_tts_location,
            # Streaming-compatible encoding for Gemini TTS.
            "audio_encoding": (
                texttospeech.AudioEncoding.PCM
                if resolved_streaming
                else texttospeech.AudioEncoding.LINEAR16
            ),
            # Shorter chunks reduce start delay for streaming TTS because
            # synthesis begins after the current chunk is half-closed.
            "tokenizer": tokenize.blingfire.SentenceTokenizer(
                min_sentence_len=max(2, google_tts_min_sentence_len),
                stream_context_len=max(1, google_tts_stream_context_len),
            ),
        }
        google_tts_voice_name = _config_str(
            profile_config,
            "voice_name",
            GOOGLE_TTS_VOICE_NAME,
        )
        if google_tts_voice_name:
            tts_kwargs["voice_name"] = google_tts_voice_name
        if resolved_creds_file:
            tts_kwargs["credentials_file"] = resolved_creds_file
        logger.info(
            "using Google TTS provider",
            extra={
                "model": resolved_model,
                "streaming": resolved_streaming,
                "location": google_tts_location,
                "min_sentence_len": max(2, google_tts_min_sentence_len),
                "stream_context_len": max(1, google_tts_stream_context_len),
                "egress": provider_egress("google_tts"),
            },
        )
        with provider_egress_env("google_tts"):
            return google.TTS(**tts_kwargs)

    if configured_tts_provider == "minimax":
        if not MINIMAX_API_KEY.strip():
            logger.warning(
                "MINIMAX_API_KEY is not set. Falling back to ElevenLabs TTS."
            )
            return build_elevenlabs_tts(tts_profile)

        _patch_minimax_sound_effects()
        minimax_model = _config_str(profile_config, "model", MINIMAX_TTS_MODEL)
        minimax_voice_id = _config_str(profile_config, "voice_id", MINIMAX_TTS_VOICE_ID)
        minimax_base_url = _config_str(profile_config, "base_url", MINIMAX_TTS_BASE_URL)
        minimax_pitch = _config_int(profile_config, "pitch", MINIMAX_TTS_PITCH)
        minimax_intensity_raw = profile_config.get("intensity", MINIMAX_TTS_INTENSITY)
        minimax_intensity = (
            int(minimax_intensity_raw)
            if minimax_intensity_raw not in (None, "")
            else None
        )
        minimax_timbre_raw = profile_config.get("timbre", MINIMAX_TTS_TIMBRE)
        minimax_timbre = (
            int(minimax_timbre_raw) if minimax_timbre_raw not in (None, "") else None
        )
        minimax_sound_effects = _config_str(
            profile_config,
            "sound_effects",
            MINIMAX_TTS_SOUND_EFFECTS,
        )
        minimax_min_sentence_len = _config_int(
            profile_config,
            "min_sentence_len",
            MINIMAX_TTS_MIN_SENTENCE_LEN,
        )
        minimax_stream_context_len = _config_int(
            profile_config,
            "stream_context_len",
            MINIMAX_TTS_STREAM_CONTEXT_LEN,
        )
        logger.info(
            "using MiniMax TTS provider",
            extra={
                "model": minimax_model,
                "voice_id": minimax_voice_id,
                "base_url": minimax_base_url,
                "pitch": minimax_pitch,
                "intensity": minimax_intensity,
                "timbre": minimax_timbre,
                "sound_effects": minimax_sound_effects or None,
                "streaming": True,
                "egress": provider_egress("minimax"),
            },
        )
        return minimax.TTS(
            model=minimax_model,
            voice=minimax_voice_id,
            speed=_config_float(profile_config, "speed", MINIMAX_TTS_SPEED),
            vol=_config_float(profile_config, "volume", MINIMAX_TTS_VOLUME),
            pitch=minimax_pitch,
            intensity=minimax_intensity,
            timbre=minimax_timbre,
            text_normalization=False,
            audio_format=_config_str(profile_config, "format", MINIMAX_TTS_FORMAT),
            sample_rate=_config_int(
                profile_config,
                "sample_rate",
                MINIMAX_TTS_SAMPLE_RATE,
            ),
            bitrate=_config_int(profile_config, "bitrate", MINIMAX_TTS_BITRATE),
            language_boost=_config_str(
                profile_config,
                "language_boost",
                MINIMAX_TTS_LANGUAGE_BOOST,
            ),
            tokenizer=tokenize.blingfire.SentenceTokenizer(
                min_sentence_len=max(2, minimax_min_sentence_len),
                stream_context_len=max(1, minimax_stream_context_len),
            ),
            text_pacing=False,
            api_key=MINIMAX_API_KEY,
            base_url=minimax_base_url,
            http_session=create_external_aiohttp_session(
                "minimax",
                external_http_sessions,
            ),
        )

    return build_elevenlabs_tts(tts_profile)


def _wrap_stt_for_early_interim_final(
    stt_client: lk_stt.STT,
    *,
    turn_profile: ComponentSelection | None = None,
) -> lk_stt.STT:
    turn_config = _component_config(turn_profile)
    return wrap_stt_if_enabled(
        stt_client,
        enabled=_config_bool(
            turn_config,
            "early_interim_final_enabled",
            STT_EARLY_INTERIM_FINAL_ENABLED,
        ),
        delay_sec=_config_float(
            turn_config,
            "early_interim_final_delay_sec",
            STT_EARLY_INTERIM_FINAL_DELAY_SEC,
        ),
        min_stable_interims=STT_EARLY_INTERIM_FINAL_MIN_STABLE_INTERIMS,
        turn_detection_mode=_config_str(
            turn_config,
            "detection_mode",
            TURN_DETECTION_MODE,
        ),
        logger_=logger,
    )


def build_stt(
    external_http_sessions: list[aiohttp.ClientSession] | None = None,
    stt_profile: ComponentSelection | None = None,
    turn_profile: ComponentSelection | None = None,
) -> Any:
    profile_config = _component_config(stt_profile)
    configured_stt_provider = _component_provider(stt_profile, STT_PROVIDER)

    def _build_google_stt_or_none(*, log_prefix: str) -> Any | None:
        resolved_creds_file = _resolve_google_tts_credentials_file()
        if not _google_tts_credentials_available():
            logger.warning("%s: Google STT credentials are not available", log_prefix)
            return None

        google_stt_model = _config_str(profile_config, "model", STT_GOOGLE_MODEL)
        if google_stt_model in ("latest_short", "telephony_short"):
            logger.warning(
                "STT_GOOGLE_MODEL=%s closes the streaming connection after the first "
                "utterance — multi-turn conversations will freeze after the first exchange. "
                "Set STT_GOOGLE_MODEL=latest_long in .env.local for reliable multi-turn operation.",
                google_stt_model,
            )

        stt_kwargs: dict[str, Any] = {
            "languages": _config_str(profile_config, "language", STT_GOOGLE_LANGUAGE),
            "model": google_stt_model,
            "location": _config_str(profile_config, "location", STT_GOOGLE_LOCATION),
            "interim_results": True,
            "use_streaming": True,
        }
        if resolved_creds_file:
            stt_kwargs["credentials_file"] = resolved_creds_file

        with provider_egress_env("google_stt"):
            return google.STT(**stt_kwargs)

    # Default path: LiveKit inference STT.
    if configured_stt_provider == "inference":
        with provider_egress_env("livekit_inference"):
            stt_instances: list[Any] = [
                inference.STT(
                    model=_config_str(profile_config, "model", STT_INFERENCE_MODEL),
                    language=_config_str(
                        profile_config,
                        "language",
                        STT_INFERENCE_LANGUAGE,
                    ),
                )
            ]
        fallback_descriptions = [
            _config_str(profile_config, "model", STT_INFERENCE_MODEL)
        ]

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
            return _wrap_stt_for_early_interim_final(
                stt_instances[0],
                turn_profile=turn_profile,
            )

        logger.info(
            "using STT fallback adapter",
            extra={
                "provider": "inference",
                "chain": fallback_descriptions,
            },
        )
        return _wrap_stt_for_early_interim_final(
            lk_stt.FallbackAdapter(
                stt=stt_instances,
                # Keep failover quick to avoid long silence when primary is rate-limited.
                attempt_timeout=8.0,
                max_retry_per_stt=0,
                retry_interval=0.7,
            ),
            turn_profile=turn_profile,
        )

    if configured_stt_provider == "google":
        google_stt = _build_google_stt_or_none(log_prefix="google provider")
        if google_stt is None:
            logger.warning(
                "Google STT credentials are not available; falling back to inference STT."
            )
            return _wrap_stt_for_early_interim_final(
                inference.STT(
                    model=STT_INFERENCE_MODEL,
                    language=STT_INFERENCE_LANGUAGE,
                ),
                turn_profile=turn_profile,
            )

        stt_instances: list[Any] = [google_stt]
        fallback_descriptions = [
            f"google:{_config_str(profile_config, 'model', STT_GOOGLE_MODEL)}"
        ]
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
                "model": _config_str(profile_config, "model", STT_GOOGLE_MODEL),
                "language": _config_str(
                    profile_config, "language", STT_GOOGLE_LANGUAGE
                ),
                "location": _config_str(
                    profile_config, "location", STT_GOOGLE_LOCATION
                ),
                "egress": provider_egress("google_stt"),
            },
        )
        if len(stt_instances) == 1:
            return _wrap_stt_for_early_interim_final(
                google_stt,
                turn_profile=turn_profile,
            )

        logger.info(
            "using STT fallback adapter",
            extra={
                "provider": "google",
                "chain": fallback_descriptions,
            },
        )
        return _wrap_stt_for_early_interim_final(
            lk_stt.FallbackAdapter(
                stt=stt_instances,
                attempt_timeout=8.0,
                max_retry_per_stt=0,
                retry_interval=0.7,
            ),
            turn_profile=turn_profile,
        )

    if configured_stt_provider == "yandex":
        if not YANDEX_SPEECHKIT_API_KEY.strip():
            logger.warning(
                "YANDEX_SPEECHKIT_API_KEY is not set. Falling back to inference STT."
            )
            return _wrap_stt_for_early_interim_final(
                inference.STT(
                    model=STT_INFERENCE_MODEL,
                    language=STT_INFERENCE_LANGUAGE,
                ),
                turn_profile=turn_profile,
            )

        yandex_model = _config_str(profile_config, "model", STT_YANDEX_MODEL)
        yandex_language = _config_str(profile_config, "language", STT_YANDEX_LANGUAGE)
        yandex_sample_rate = _config_int(
            profile_config,
            "sample_rate",
            STT_YANDEX_SAMPLE_RATE,
        )
        yandex_chunk_ms = _config_int(
            profile_config,
            "chunk_ms",
            STT_YANDEX_CHUNK_MS,
        )
        yandex_eou_sensitivity = _config_str(
            profile_config,
            "eou_sensitivity",
            STT_YANDEX_EOU_SENSITIVITY,
        )
        yandex_max_pause = _config_int(
            profile_config,
            "max_pause_between_words_hint_ms",
            STT_YANDEX_MAX_PAUSE_BETWEEN_WORDS_HINT_MS,
        )
        egress_mode = _component_egress(stt_profile)
        logger.info(
            "using Yandex SpeechKit STT provider",
            extra={
                "model": yandex_model,
                "language": yandex_language,
                "sample_rate": yandex_sample_rate,
                "chunk_ms": yandex_chunk_ms,
                "eou_sensitivity": yandex_eou_sensitivity,
                "max_pause_between_words_hint_ms": yandex_max_pause,
                "egress": provider_egress("yandex_stt", mode_override=egress_mode),
            },
        )
        with provider_egress_env("yandex_stt", mode_override=egress_mode):
            return _wrap_stt_for_early_interim_final(
                YandexSpeechKitSTT(
                    api_key=YANDEX_SPEECHKIT_API_KEY,
                    model=yandex_model,
                    language=yandex_language,
                    sample_rate=yandex_sample_rate,
                    chunk_ms=yandex_chunk_ms,
                    eou_sensitivity=yandex_eou_sensitivity,
                    max_pause_between_words_hint_ms=yandex_max_pause,
                ),
                turn_profile=turn_profile,
            )

    if configured_stt_provider == "tbank":
        if not TBANK_VOICEKIT_API_KEY.strip() or not TBANK_VOICEKIT_SECRET_KEY.strip():
            raise RuntimeError(
                "T-Bank VoiceKit STT is configured but TBANK_VOICEKIT_API_KEY "
                "or TBANK_VOICEKIT_SECRET_KEY is missing."
            )

        tbank_model = _config_str(profile_config, "model", STT_TBANK_MODEL)
        tbank_language = _config_str(profile_config, "language", STT_TBANK_LANGUAGE)
        tbank_sample_rate = _config_int(
            profile_config,
            "sample_rate",
            STT_TBANK_SAMPLE_RATE,
        )
        tbank_chunk_ms = _config_int(profile_config, "chunk_ms", STT_TBANK_CHUNK_MS)
        tbank_interim_interval_sec = _config_float(
            profile_config,
            "interim_interval_sec",
            STT_TBANK_INTERIM_INTERVAL_SEC,
        )
        tbank_endpoint = _config_str(
            profile_config,
            "endpoint",
            TBANK_VOICEKIT_ENDPOINT,
        )
        tbank_authority = _config_str(
            profile_config,
            "authority",
            TBANK_VOICEKIT_AUTHORITY,
        )
        egress_mode = _component_egress(stt_profile)
        logger.info(
            "using T-Bank VoiceKit STT provider",
            extra={
                "model": tbank_model or "default",
                "language": tbank_language,
                "sample_rate": tbank_sample_rate,
                "chunk_ms": tbank_chunk_ms,
                "interim_interval_sec": tbank_interim_interval_sec,
                "endpoint": tbank_endpoint,
                "authority": tbank_authority or None,
                "egress": provider_egress("tbank_stt", mode_override=egress_mode),
            },
        )
        with provider_egress_env("tbank_stt", mode_override=egress_mode):
            return _wrap_stt_for_early_interim_final(
                TBankVoiceKitSTT(
                    api_key=TBANK_VOICEKIT_API_KEY,
                    secret_key=TBANK_VOICEKIT_SECRET_KEY,
                    model=tbank_model,
                    language=tbank_language,
                    sample_rate=tbank_sample_rate,
                    chunk_ms=tbank_chunk_ms,
                    interim_interval_sec=tbank_interim_interval_sec,
                    endpoint=tbank_endpoint,
                    authority=tbank_authority,
                ),
                turn_profile=turn_profile,
            )

    if configured_stt_provider == "deepgram":
        if not DEEPGRAM_API_KEY:
            logger.warning(
                "DEEPGRAM_API_KEY is not set. Falling back to inference STT."
            )
            return _wrap_stt_for_early_interim_final(
                inference.STT(
                    model=STT_INFERENCE_MODEL,
                    language=STT_INFERENCE_LANGUAGE,
                ),
                turn_profile=turn_profile,
            )

        deepgram_model = _config_str(profile_config, "model", STT_DEEPGRAM_MODEL)
        deepgram_api_version = _config_optional_str(
            profile_config,
            "api_version",
        ).lower()
        deepgram_language = _config_str(
            profile_config,
            "language",
            STT_DEEPGRAM_LANGUAGE,
        )
        egress_mode = _component_egress(stt_profile)

        if deepgram_api_version in {"2", "v2"} or is_deepgram_flux_model(
            deepgram_model
        ):
            flux_model = normalize_deepgram_flux_model(deepgram_model)
            flux_kwargs: dict[str, Any] = {
                "api_key": DEEPGRAM_API_KEY,
                "model": flux_model,
                "language": deepgram_language,
                "language_hints": _config_str_list(profile_config, "language_hints"),
                "sample_rate": _config_int(profile_config, "sample_rate", 16000),
                "mip_opt_out": _config_bool(profile_config, "mip_opt_out", False),
                "http_session": create_external_aiohttp_session(
                    "deepgram",
                    external_http_sessions,
                    egress_mode=egress_mode,
                ),
            }
            eager_eot_threshold = _config_optional_float(
                profile_config,
                "eager_eot_threshold",
            )
            if eager_eot_threshold is not None:
                flux_kwargs["eager_eot_threshold"] = eager_eot_threshold
            eot_threshold = _config_optional_float(profile_config, "eot_threshold")
            if eot_threshold is not None:
                flux_kwargs["eot_threshold"] = eot_threshold
            eot_timeout_ms = _config_optional_int(profile_config, "eot_timeout_ms")
            if eot_timeout_ms is not None:
                flux_kwargs["eot_timeout_ms"] = eot_timeout_ms
            if keyterm := _config_str_list(profile_config, "keyterm"):
                flux_kwargs["keyterm"] = keyterm
            if tags := _config_str_list(profile_config, "tags"):
                flux_kwargs["tags"] = tags
            if base_url := _config_optional_str(profile_config, "base_url"):
                flux_kwargs["base_url"] = base_url

            logger.info(
                "using Deepgram Flux STT provider",
                extra={
                    "model": flux_model,
                    "language": deepgram_language,
                    "language_hints": flux_kwargs["language_hints"],
                    "egress": provider_egress("deepgram", mode_override=egress_mode),
                },
            )
            return _wrap_stt_for_early_interim_final(
                DeepgramFluxSTT(**flux_kwargs),
                turn_profile=turn_profile,
            )

        deepgram_endpointing_ms = _config_int(
            profile_config,
            "endpointing_ms",
            STT_DEEPGRAM_ENDPOINTING_MS,
        )
        logger.info(
            "using Deepgram STT provider",
            extra={
                "model": deepgram_model,
                "language": deepgram_language,
                "egress": provider_egress("deepgram", mode_override=egress_mode),
            },
        )
        return _wrap_stt_for_early_interim_final(
            deepgram.STT(
                api_key=DEEPGRAM_API_KEY,
                model=deepgram_model,
                language=deepgram_language,
                http_session=create_external_aiohttp_session(
                    "deepgram",
                    external_http_sessions,
                    egress_mode=egress_mode,
                ),
                interim_results=True,
                no_delay=True,
                endpointing_ms=deepgram_endpointing_ms,
                smart_format=False,
                punctuate=True,
                filler_words=False,
                vad_events=True,
            ),
            turn_profile=turn_profile,
        )

    logger.warning(
        "Unknown STT_PROVIDER='%s'. Falling back to inference STT.",
        configured_stt_provider,
    )
    return _wrap_stt_for_early_interim_final(
        inference.STT(
            model=STT_INFERENCE_MODEL,
            language=STT_INFERENCE_LANGUAGE,
        ),
        turn_profile=turn_profile,
    )


class Assistant(Agent):
    def __init__(
        self,
        model_router: ModelRouter | None = None,
        routed_llms: dict[str, Any] | None = None,
        routed_llm_providers: dict[str, str] | None = None,
        routed_llm_metadata: dict[str, LLMBranchMetadata] | None = None,
        fallback_llm: google.LLM | None = None,
        fallback_llm_provider: str = "google",
        first_turn_short_greeting_audio_path: Path = _SHORT_GREETING_AUDIO_PATH,
        first_turn_short_greeting_phrase: str = VOICE_SHORT_GREETING_PHRASE,
        first_turn_short_greeting_delay_sec: float = VOICE_SHORT_GREETING_DELAY_SEC,
        prerecorded_audio_sample_rate: int = 24000,
        voice_audio_cache: VoiceAudioCache | None = None,
        voice_prompts: VoicePromptManager | None = None,
        tag_skill_runner: RobotSkillRunner | None = None,
        prompt: str | None = None,
        incident_logger: IncidentLogger | None = None,
    ) -> None:
        self._model_router = model_router
        self._routed_llms = routed_llms or {}
        self._routed_llm_providers = routed_llm_providers or {}
        self._routed_llm_metadata = routed_llm_metadata or {}
        self._fallback_llm = fallback_llm
        self._fallback_llm_provider = fallback_llm_provider
        self._first_turn_short_greeting_audio_path = (
            first_turn_short_greeting_audio_path
        )
        self._first_turn_short_greeting_phrase = first_turn_short_greeting_phrase
        self._first_turn_short_greeting_delay_sec = max(
            0.0,
            first_turn_short_greeting_delay_sec,
        )
        self._prerecorded_audio_sample_rate = prerecorded_audio_sample_rate
        self._voice_audio_cache = voice_audio_cache
        self._voice_prompts = voice_prompts
        self._tag_skill_runner = tag_skill_runner
        self._incident_logger = incident_logger
        self._awaiting_first_user_turn = True
        self._initial_greeting_in_progress = False
        self._llm_branch_started_at: dict[str, float] = {}
        self._tts_first_frame_ready_at: float | None = None
        self._tts_first_frame_yielded_at: float | None = None
        self._user_speech_revision = 0
        self._user_is_speaking = False
        self._speech_start_user_revisions: dict[str, int] = {}
        resolved_prompt = prompt if prompt is not None else get_active_prompt()
        super().__init__(instructions=resolved_prompt)
        self._register_llm_availability_listeners()

    def begin_initial_greeting(self) -> None:
        self._initial_greeting_in_progress = True

    def finish_initial_greeting(self) -> None:
        self._initial_greeting_in_progress = False

    def note_user_started_speaking(self) -> None:
        self._user_speech_revision += 1
        self._user_is_speaking = True

    def note_user_finished_speaking(self) -> None:
        self._user_is_speaking = False

    def _current_speech_handle(self) -> Any | None:
        try:
            from livekit.agents.voice.agent_activity import _SpeechHandleContextVar

            return _SpeechHandleContextVar.get(None)
        except Exception:
            return None

    def _current_speech_id(self) -> str | None:
        return speech_handle_id(self._current_speech_handle())

    def _remember_speech_start_revision(self) -> int:
        revision = self._user_speech_revision
        speech_id = self._current_speech_id()
        if speech_id:
            self._speech_start_user_revisions.setdefault(speech_id, revision)
        return revision

    def _speech_start_revision(self, speech_id: str | None) -> int:
        if not speech_id:
            return self._user_speech_revision
        return self._speech_start_user_revisions.get(
            speech_id,
            self._user_speech_revision,
        )

    def _user_spoke_since(self, revision: int) -> bool:
        return should_cancel_pending_reply_for_user_speech(
            stream_user_speech_revision=revision,
            current_user_speech_revision=self._user_speech_revision,
            user_is_speaking=self._user_is_speaking,
        )

    def _cancel_current_speech_before_audio(
        self,
        *,
        speech_id: str | None,
        started_revision: int,
        phase: str,
    ) -> bool:
        if not self._user_spoke_since(started_revision):
            return False

        handle = self._current_speech_handle()
        if handle is not None and not bool(getattr(handle, "allow_interruptions", True)):
            return False

        logger.info(
            "assistant speech canceled before first audio because user started speaking",
            extra={
                "speech_id": speech_id,
                "phase": phase,
                "speech_start_user_revision": started_revision,
                "current_user_revision": self._user_speech_revision,
                "user_is_speaking": self._user_is_speaking,
            },
        )
        if handle is not None:
            with suppress(Exception):
                handle.interrupt(force=True)
        else:
            with suppress(Exception):
                self.session.interrupt(force=True)
        return True

    async def on_user_turn_completed(self, _: Any, new_message: ChatMessage) -> None:
        if not self._awaiting_first_user_turn:
            return

        user_text = (getattr(new_message, "text_content", None) or "").strip()
        if not user_text:
            return

        if self._initial_greeting_in_progress:
            logger.info("user turn ignored while initial greeting is playing")
            raise StopResponse()

        self._awaiting_first_user_turn = False
        if not is_short_greeting_response(user_text):
            return

        short_greeting_revision = self._user_speech_revision
        if self._first_turn_short_greeting_delay_sec > 0:
            logger.info(
                "first user turn matched short greeting regex; waiting before prerecorded follow-up audio",
                extra={
                    "delay_sec": self._first_turn_short_greeting_delay_sec,
                    "speech_start_user_revision": short_greeting_revision,
                },
            )
            await wait_for_short_greeting_delay(
                self._first_turn_short_greeting_delay_sec
            )
            if self._user_spoke_since(short_greeting_revision):
                logger.info(
                    "short greeting follow-up canceled because user started speaking",
                    extra={
                        "speech_start_user_revision": short_greeting_revision,
                        "current_user_revision": self._user_speech_revision,
                        "user_is_speaking": self._user_is_speaking,
                    },
                )
                raise StopResponse()

        logger.info(
            "first user turn matched short greeting regex; playing prerecorded follow-up audio"
        )
        with suppress(Exception):
            await self.session.interrupt(force=True)

        audio_path = await resolve_short_greeting_audio_path(
            voice_audio_cache=self._voice_audio_cache,
            phrase=self._first_turn_short_greeting_phrase,
            prerecorded_path=self._first_turn_short_greeting_audio_path,
        )
        if audio_path is None:
            return
        if self._user_spoke_since(short_greeting_revision):
            logger.info(
                "short greeting follow-up canceled before playback because user started speaking",
                extra={
                    "speech_start_user_revision": short_greeting_revision,
                    "current_user_revision": self._user_speech_revision,
                    "user_is_speaking": self._user_is_speaking,
                },
            )
            raise StopResponse()

        played = await play_prerecorded_audio(
            session=self.session,
            audio_path=audio_path,
            sample_rate=self._prerecorded_audio_sample_rate,
            allow_interruptions=True,
            add_to_chat_ctx=False,
            text=self._first_turn_short_greeting_phrase,
        )
        if played:
            raise StopResponse()

    async def tts_node(
        self, text: AsyncIterable[str], model_settings: Any
    ) -> AsyncIterator[rtc.AudioFrame]:
        speech_handle = self._current_speech_handle()
        speech_id = speech_handle_id(speech_handle)
        speech_start_revision = self._speech_start_revision(speech_id)
        audio_stream = Agent.default.tts_node(
            self,
            sanitize_tagged_text_stream(text),
            model_settings,
        )
        waited_for_prompt = False
        try:
            async for frame in audio_stream:
                if not waited_for_prompt:
                    self._tts_first_frame_ready_at = time.time()
                    self._tts_first_frame_yielded_at = None
                    if self._cancel_current_speech_before_audio(
                        speech_id=speech_id,
                        started_revision=speech_start_revision,
                        phase="first_frame_ready",
                    ):
                        return
                    if self._voice_prompts is not None:
                        await self._voice_prompts.wait_for_active_prompt()
                    if self._cancel_current_speech_before_audio(
                        speech_id=speech_id,
                        started_revision=speech_start_revision,
                        phase="after_voice_prompt_wait",
                    ):
                        return
                    self._tts_first_frame_yielded_at = time.time()
                    waited_for_prompt = True
                yield frame
        finally:
            if speech_id:
                self._speech_start_user_revisions.pop(speech_id, None)

    async def transcription_node(
        self, text: AsyncIterable[str], model_settings: Any
    ) -> AsyncIterator[str]:
        async for chunk in Agent.default.transcription_node(
            self,
            sanitize_tagged_text_stream(text),
            model_settings,
        ):
            yield chunk

    def _capture_robot_tag_text(self, raw_parts: list[str], chunk: Any) -> None:
        if isinstance(chunk, str):
            raw_parts.append(chunk)
            return

        delta = getattr(chunk, "delta", None)
        content = getattr(delta, "content", None)
        if content:
            raw_parts.append(str(content))

    def _register_robot_tag_output(
        self,
        raw_text: str,
        *,
        stream_user_speech_revision: int,
    ) -> None:
        if self._tag_skill_runner is None or not raw_text:
            return

        parsed = parse_robot_tags(raw_text)
        if not parsed.has_action_or_tags:
            return

        interrupted_by_user_speech = (
            self._user_speech_revision > stream_user_speech_revision
        )

        try:
            from livekit.agents.voice.agent_activity import _SpeechHandleContextVar

            speech_handle = _SpeechHandleContextVar.get(None)
        except Exception:
            speech_handle = None

        if speech_handle is None:
            self._schedule_robot_tag_run(
                parsed,
                speech_handle_id=None,
                interrupted=interrupted_by_user_speech,
            )
            return

        def _on_speech_done(handle: Any) -> None:
            interrupted = bool(getattr(handle, "interrupted", False)) or (
                self._user_speech_revision > stream_user_speech_revision
            )
            self._schedule_robot_tag_run(
                parsed,
                speech_handle_id=str(getattr(handle, "id", "")) or None,
                interrupted=interrupted,
            )

        speech_handle.add_done_callback(_on_speech_done)

    def _schedule_robot_tag_run(
        self,
        parsed: Any,
        *,
        speech_handle_id: str | None,
        interrupted: bool,
    ) -> None:
        if self._tag_skill_runner is None:
            return

        task = asyncio.create_task(
            self._tag_skill_runner.run(
                parsed,
                speech_handle_id=speech_handle_id,
                interrupted=interrupted,
            ),
            name="robot_tag_skill",
        )

        def _log_task_result(done_task: asyncio.Task) -> None:
            with suppress(BaseException):
                done_task.result()

        task.add_done_callback(_log_task_result)

    async def _tracked_robot_tag_llm_stream(
        self,
        stream: AsyncIterable[Any],
    ) -> AsyncIterator[Any]:
        raw_parts: list[str] = []
        stream_user_speech_revision = self._remember_speech_start_revision()
        try:
            async for chunk in stream:
                self._capture_robot_tag_text(raw_parts, chunk)
                yield chunk
        finally:
            self._register_robot_tag_output(
                "".join(raw_parts),
                stream_user_speech_revision=stream_user_speech_revision,
            )

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
        if not available and self._incident_logger is not None:
            self._incident_logger.record_nowait(
                "provider_fallback",
                severity="warning",
                component="llm",
                provider=changed_provider,
                model=changed_model,
                latency_ms=elapsed_ms,
                description="LLM provider became unavailable and fallback path was used",
                payload={
                    "branch": branch,
                    "available": available,
                    "primary_provider": metadata.primary_provider if metadata else None,
                    "primary_model": metadata.primary_model if metadata else None,
                    "backup_provider": metadata.backup_provider if metadata else None,
                    "backup_model": metadata.backup_model if metadata else None,
                    "final_provider": final_provider,
                    "final_model": final_model,
                    "elapsed_ms_before_fallback": elapsed_ms,
                },
            )

    async def _stream_llm(
        self,
        llm_client: Any,
        llm_provider: str,
        chat_ctx: Any,
        tools: list[Any],
        model_settings: Any,
        *,
        enable_tools: bool | None = None,
    ) -> AsyncIterator[Any]:
        resolved_tools, tool_choice = self._resolve_tools_for_llm_call(
            tools=tools,
            model_settings=model_settings,
            llm_provider=llm_provider,
            enable_tools=enable_tools,
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
        enable_tools: bool | None = None,
    ) -> tuple[list[Any], Any]:
        tool_choice = model_settings.tool_choice if model_settings else NOT_GIVEN
        resolved_tools = tools
        provider = str(llm_provider or LLM_PROVIDER).strip().lower()
        is_xai_provider = provider in {"xai", "api.x.ai", "x.ai"}
        # For xAI provider we keep tools disabled by default, even if declared in the agent.
        # This avoids Responses API 400 errors around tool_choice/tools coupling
        # and keeps lower TTFT for voice turns.
        xai_tools_enabled = XAI_ENABLE_TOOLS if enable_tools is None else enable_tools
        if is_xai_provider and not xai_tools_enabled:
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
        enable_tools: bool | None = None,
    ) -> AsyncIterator[Any]:
        stream = self._stream_llm(
            llm_client,
            llm_provider,
            chat_ctx,
            tools,
            model_settings,
            enable_tools=enable_tools,
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
            async for chunk in self._tracked_robot_tag_llm_stream(
                self._stream_llm(
                    primary_llm,
                    "livekit_inference",
                    chat_ctx,
                    tools,
                    model_settings,
                )
            ):
                yield chunk
            return

        selected_uses_fallback_adapter = (
            route_metadata.uses_fallback_adapter
            if route_metadata is not None
            else USE_LIVEKIT_FALLBACK_ADAPTER
        )
        selected_enable_tools = (
            route_metadata.enable_tools if route_metadata is not None else None
        )
        if selected_uses_fallback_adapter:
            self._llm_branch_started_at[selected_branch] = (
                asyncio.get_running_loop().time()
            )
            yielded_any = False
            try:
                async for chunk in self._tracked_robot_tag_llm_stream(
                    self._stream_llm(
                        primary_llm,
                        primary_provider,
                        chat_ctx,
                        tools,
                        model_settings,
                        enable_tools=selected_enable_tools,
                    )
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
        fallback_reason = None
        fallback_error_type = None

        try:
            async for chunk in self._tracked_robot_tag_llm_stream(
                self._stream_llm_with_ttft_timeout(
                    primary_llm,
                    primary_provider,
                    chat_ctx,
                    tools,
                    model_settings,
                    first_token_timeout=LLM_FIRST_TOKEN_TIMEOUT_SEC,
                    enable_tools=selected_enable_tools,
                )
            ):
                yielded_any = True
                yield chunk
            return
        except asyncio.TimeoutError:
            logger.warning(
                "primary LLM first token timeout after %.1fs; retrying once",
                LLM_FIRST_TOKEN_TIMEOUT_SEC,
            )
            fallback_reason = "primary_first_token_timeout"
            fallback_error_type = "TimeoutError"
        except APIStatusError as e:
            if yielded_any or e.status_code < 500:
                raise
            logger.warning(
                "primary LLM returned %s before first token; retrying once",
                e.status_code,
            )
            fallback_reason = f"primary_api_{e.status_code}"
            fallback_error_type = type(e).__name__
        except Exception as e:
            if yielded_any:
                raise
            logger.warning(
                "primary LLM failed before first token; retrying once: %s", e
            )
            fallback_reason = "primary_error"
            fallback_error_type = type(e).__name__

        await asyncio.sleep(max(0.0, LLM_RETRY_DELAY_SEC))

        try:
            async for chunk in self._tracked_robot_tag_llm_stream(
                self._stream_llm_with_ttft_timeout(
                    primary_llm,
                    primary_provider,
                    chat_ctx,
                    tools,
                    model_settings,
                    first_token_timeout=LLM_FIRST_TOKEN_TIMEOUT_SEC,
                    enable_tools=selected_enable_tools,
                )
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
            fallback_reason = "retry_first_token_timeout"
            fallback_error_type = "TimeoutError"
        except APIStatusError as e:
            if e.status_code < 500 or self._fallback_llm is None:
                raise
            logger.warning(
                "retry failed with %s; switching to fallback model", e.status_code
            )
            fallback_reason = f"retry_api_{e.status_code}"
            fallback_error_type = type(e).__name__
        except Exception:
            if self._fallback_llm is None:
                raise
            logger.warning("retry failed; switching to fallback model")
            fallback_reason = "retry_error"
            fallback_error_type = "Exception"

        if self._incident_logger is not None:
            fallback_provider, fallback_model = component_identity(self._fallback_llm)
            primary_model_name = (
                route_metadata.primary_model
                if route_metadata
                else str(getattr(primary_llm, "model", None))
            )
            self._incident_logger.record_nowait(
                "provider_fallback",
                severity="warning",
                component="llm",
                provider=primary_provider,
                model=primary_model_name,
                error_type=fallback_error_type,
                description="Manual LLM fallback model was used",
                payload={
                    "branch": selected_branch,
                    "reason": fallback_reason,
                    "primary_provider": primary_provider,
                    "primary_model": primary_model_name,
                    "fallback_provider": fallback_provider,
                    "fallback_model": fallback_model,
                    "first_token_timeout_sec": LLM_FIRST_TOKEN_TIMEOUT_SEC,
                    "fallback_first_token_timeout_sec": LLM_FALLBACK_FIRST_TOKEN_TIMEOUT_SEC,
                },
            )

        async for chunk in self._tracked_robot_tag_llm_stream(
            self._stream_llm_with_ttft_timeout(
                self._fallback_llm,
                self._fallback_llm_provider,
                chat_ctx,
                tools,
                model_settings,
                first_token_timeout=LLM_FALLBACK_FIRST_TOKEN_TIMEOUT_SEC,
            )
        ):
            yield chunk


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


def build_agent_room_options(
    *,
    audio_output_sample_rate: int,
    participant_identity: str | None = None,
) -> room_io.RoomOptions:
    options = room_io.RoomOptions(
        audio_input=build_audio_input_options(),
        audio_output=room_io.AudioOutputOptions(
            sample_rate=audio_output_sample_rate,
            num_channels=1,
        ),
        delete_room_on_close=True,
    )
    if participant_identity:
        options.participant_identity = participant_identity
    return options


@server.rtc_session(agent_name=AGENT_NAME)
async def my_agent(ctx: JobContext):
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }
    job_id = get_job_id(ctx)
    incident_log = IncidentLogger(
        environment=INCIDENT_ENVIRONMENT,
        room_name=ctx.room.name,
        job_id=job_id,
    )

    session_started_at = datetime.now(timezone.utc)

    transcript_items = []
    tag_events = []
    usage_updates = []
    metrics_events = []
    component_metrics_events = []
    close_info = {"reason": None, "error": None}
    close_event = asyncio.Event()
    user_activity_count = 0
    pending_user_phrase_end_at: float | None = None
    pending_user_phrase_end_source: str | None = None
    assistant_message_count = 0
    last_final_user_turn_started_at: float | None = None
    last_final_user_turn_text_len = 0
    slow_response_logged_for_current_turn = False
    agent_speaking_revision = 0
    response_delay_has_final_transcript = False
    response_delay_user_stopped_speaking = False
    response_delay_started_for_turn = False
    end_call_task: asyncio.Task | None = None
    reply_watchdog_task: asyncio.Task | None = None
    startup_no_dialog_task: asyncio.Task | None = None
    recording_stop_task: asyncio.Task | None = None
    export_wait_sec = 20.0
    export_task: asyncio.Task | None = None
    session_close_task: asyncio.Task | None = None
    runtime_warmup_task: asyncio.Task | None = None
    unrecoverable_error_task: asyncio.Task | None = None
    unrecoverable_error_response_started = False
    startup_dialog_activity_seen = False
    session_started = False
    startup_failure_recorded = False
    prompt_resolution = PromptResolution(
        prompt="",
        source="file:not_resolved",
    )
    sip_call_numbers = {
        "sip_trunk_number": None,
        "gateway_number": None,
        "sip_client_number": None,
    }
    sip_diagnostic_context = {
        "trace_id": None,
        "sip_call_id": None,
    }
    participant = None
    participant_missing_before_settings = False
    client_disconnect_context: dict[str, Any] = {}
    participant_disconnect_cleanup_handler: Callable[
        [rtc.RemoteParticipant], None
    ] | None = None
    robot_settings: ResolvedRobotSettings | None = None
    recording_handle = None
    recording_stop_requested = False
    raw_log_sink = RawCallLogSink(
        room_name=ctx.room.name,
        session_id=ctx.room.name,
        agent_name=AGENT_NAME,
        runtime_profile=ROBOT_RUNTIME_PROFILE,
        job_id=job_id,
    )
    raw_log_token = bind_raw_call_log_sink(raw_log_sink)
    await raw_log_sink.start()
    logger.info("raw call log capture started")

    try:
        await ctx.connect()
        try:
            participant = await asyncio.wait_for(
                ctx.wait_for_participant(),
                timeout=VOICE_SIP_PARTICIPANT_WAIT_TIMEOUT_SEC,
            )
        except asyncio.TimeoutError:
            participant_missing_before_settings = True
            logger.warning(
                "sip participant not available before prompt/settings lookup",
                extra={"timeout_sec": VOICE_SIP_PARTICIPANT_WAIT_TIMEOUT_SEC},
            )
            incident_log.record_nowait(
                "sip_participant_not_ready",
                severity="warning",
                component="livekit_room",
                latency_ms=int(VOICE_SIP_PARTICIPANT_WAIT_TIMEOUT_SEC * 1000),
                error_type="TimeoutError",
                description="SIP participant was not available before settings lookup",
                payload={
                    "timeout_sec": VOICE_SIP_PARTICIPANT_WAIT_TIMEOUT_SEC,
                    "phase": "before_settings_lookup",
                },
            )

        sip_call_numbers = extract_sip_call_numbers(participant)
        sip_diagnostic_context = extract_sip_diagnostic_context(participant)
        incident_log.set_context(**sip_diagnostic_context)
        raw_log_sink.trace_id = sip_diagnostic_context.get("trace_id")
        raw_log_sink.sip_call_id = sip_diagnostic_context.get("sip_call_id")
        prompt_resolution = await resolve_prompt_for_call(
            sip_trunk_number=sip_call_numbers["sip_trunk_number"],
            sip_client_number=sip_call_numbers["sip_client_number"],
        )
        robot_settings = await resolve_robot_settings_for_call(
            did=sip_call_numbers["sip_trunk_number"],
            runtime_key=ROBOT_RUNTIME_PROFILE,
        )
        try:
            recording_handle = await start_room_recording(ctx.room.name)
            if recording_handle:
                logger.info(
                    "room recording started",
                    extra={
                        "egress_id": recording_handle.egress_id,
                        "object_key": recording_handle.object_key,
                    },
                )
        except Exception as e:
            logger.warning("failed to start room recording: %s", e)
            incident_log.record_exception_nowait(
                "call_recording_failed",
                e,
                severity="warning",
                component="livekit_egress",
                description="Failed to start LiveKit room recording",
            )
        logger.info(
            "robot settings resolved",
            extra={
                "source": robot_settings.source,
                "runtime_profile": ROBOT_RUNTIME_PROFILE,
                "effective_runtime_profile": robot_settings.effective_runtime_key,
                "project_key": robot_settings.project_key,
                "did": sip_call_numbers["sip_trunk_number"],
                "llm_profile": robot_settings.llm_primary.profile_key
                if robot_settings.llm_primary
                else None,
                "tts_profile": robot_settings.tts_primary.profile_key
                if robot_settings.tts_primary
                else None,
                "stt_profile": robot_settings.stt_primary.profile_key
                if robot_settings.stt_primary
                else None,
            },
        )
    except Exception as e:
        startup_failure_recorded = True
        await incident_log.record_exception(
            "session_start_failed",
            e,
            severity="critical",
            component="settings",
            description="Failed to resolve prompt or robot settings before session start",
            payload={
                "phase": "resolve_prompt_robot_settings",
                "runtime_profile": ROBOT_RUNTIME_PROFILE,
            },
        )
        raise

    model_router: ModelRouter | None = None
    routed_llms: dict[str, Any] = {}
    routed_llm_providers: dict[str, str] = {}
    routed_llm_metadata: dict[str, LLMBranchMetadata] = {}
    directus_routing_enabled = bool(
        robot_settings
        and robot_settings.component("llm_routing", "fast")
        and robot_settings.component("llm_routing", "complex")
    )
    llm_routing_enabled = directus_routing_enabled or LLM_ROUTING_ENABLED
    if llm_routing_enabled:
        model_router = ModelRouter.from_default_config()
        router_model_names = _resolve_router_model_names(model_router)
        try:
            routed_llms, routed_llm_providers, routed_llm_metadata = (
                build_routed_llm_clients(robot_settings)
            )
        except Exception as e:
            await incident_log.record_exception(
                "session_start_failed",
                e,
                severity="critical",
                component="llm",
                description="Failed to build routed LLM clients before session start",
                payload={"phase": "build_routed_llm_clients"},
            )
            raise
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
                "use_livekit_fallback_adapter": routed_llm_metadata[
                    "complex"
                ].uses_fallback_adapter,
                "settings_source": robot_settings.source if robot_settings else "env",
            },
        )
    elif FAST_LLM_PROVIDER or COMPLEX_LLM_PROVIDER:
        logger.warning(
            "model routing is disabled because FAST_LLM_PROVIDER and COMPLEX_LLM_PROVIDER must both be set"
        )
    else:
        logger.info("model routing is disabled; using single LLM_PROVIDER flow")

    fallback_llm = None
    fallback_llm_provider_name = "google"
    session_llm_metadata: LLMBranchMetadata | None = None
    if not llm_routing_enabled:
        primary_llm_profile = robot_settings.llm_primary if robot_settings else None
        primary_llm_provider = _component_provider(primary_llm_profile, LLM_PROVIDER)
        try:
            session_llm, session_llm_metadata = build_llm_client_for_branch(
                branch="complex",
                primary_provider=primary_llm_provider,
                primary_profile=primary_llm_profile,
                robot_settings=robot_settings,
            )
        except Exception as e:
            await incident_log.record_exception(
                "session_start_failed",
                e,
                severity="critical",
                component="llm",
                provider=primary_llm_provider,
                description="Failed to build session LLM before session start",
                payload={"phase": "build_session_llm"},
            )
            raise
        routed_llms["complex"] = session_llm
        routed_llm_metadata["complex"] = session_llm_metadata
    else:
        session_llm = routed_llms.get("complex")

    fallback_provider = routed_llm_metadata.get("complex")
    if (
        fallback_provider is not None
        and not fallback_provider.uses_fallback_adapter
        and fallback_provider.has_backup
    ):
        try:
            fallback_llm_provider_name = fallback_provider.backup_provider or "google"
            fallback_llm = build_llm_for_provider(
                fallback_llm_provider_name,
                model_name=fallback_provider.backup_model,
            )
        except Exception as e:
            await incident_log.record_exception(
                "session_start_failed",
                e,
                severity="critical",
                component="llm",
                provider=fallback_provider.backup_provider,
                model=fallback_provider.backup_model,
                description="Failed to build manual fallback LLM before session start",
                payload={"phase": "build_manual_fallback_llm"},
            )
            raise
    elif (
        not USE_LIVEKIT_FALLBACK_ADAPTER
        and fallback_provider is not None
        and fallback_provider.primary_provider == "google"
        and GEMINI_FALLBACK_MODEL
    ):
        try:
            fallback_llm_provider_name = "google"
            fallback_llm = build_google_llm(model_name=GEMINI_FALLBACK_MODEL)
        except Exception as e:
            await incident_log.record_exception(
                "session_start_failed",
                e,
                severity="critical",
                component="llm",
                provider="google",
                model=GEMINI_FALLBACK_MODEL,
                description="Failed to build manual fallback LLM before session start",
                payload={"phase": "build_manual_fallback_llm"},
            )
            raise

    turn_profile = robot_settings.turn if robot_settings else None
    turn_config = _component_config(turn_profile)
    min_endpointing_delay = max(
        0.0,
        _config_float(
            turn_config,
            "min_endpointing_delay",
            TURN_MIN_ENDPOINTING_DELAY,
        ),
    )
    max_endpointing_delay = max(
        min_endpointing_delay,
        _config_float(
            turn_config,
            "max_endpointing_delay",
            TURN_MAX_ENDPOINTING_DELAY,
        ),
    )
    configured_endpointing_mode = _config_str(
        turn_config,
        "endpointing_mode",
        TURN_ENDPOINTING_MODE,
    )
    endpointing_mode = (
        "dynamic" if configured_endpointing_mode == "dynamic" else "fixed"
    )
    configured_turn_detection_mode = _config_str(
        turn_config,
        "detection_mode",
        TURN_DETECTION_MODE,
    )
    turn_detection_mode: str | MultilingualModel
    if configured_turn_detection_mode == "multilingual":
        turn_detection_mode = MultilingualModel()
    elif configured_turn_detection_mode in ("vad", "stt", "manual"):
        turn_detection_mode = configured_turn_detection_mode
        configured_stt_provider = _component_provider(
            robot_settings.stt_primary if robot_settings else None,
            STT_PROVIDER,
        )
        if (
            configured_turn_detection_mode == "stt"
            and configured_stt_provider == "google"
        ):
            # turn_detection="stt" with Google STT requires enable_voice_activity_events=True,
            # but that causes the streaming session to close after first utterance on latest_short.
            # VAD-based detection (Silero) is the reliable alternative: no Google stream dependency.
            logger.warning(
                "turn_detection='stt' is unreliable with Google STT in LiveKit 1.5+. "
                "Set TURN_DETECTION_MODE=vad in .env.local for stable multi-turn operation."
            )
    else:
        turn_detection_mode = "vad"
    preemptive_generation = _config_bool(
        turn_config,
        "preemptive_generation",
        PREEMPTIVE_GENERATION,
    )

    audio_output_sample_rate = resolve_audio_output_sample_rate(
        robot_settings.tts_primary if robot_settings else None
    )
    external_http_sessions: list[aiohttp.ClientSession] = []
    try:
        stt_client = build_stt(
            external_http_sessions=external_http_sessions,
            stt_profile=robot_settings.stt_primary if robot_settings else None,
            turn_profile=turn_profile,
        )
        tts_client = build_tts(
            external_http_sessions=external_http_sessions,
            tts_profile=robot_settings.tts_primary if robot_settings else None,
        )
    except Exception as e:
        await incident_log.record_exception(
            "session_start_failed",
            e,
            severity="critical",
            component="pipeline",
            description="Failed to build STT/TTS pipeline before session start",
            payload={
                "phase": "build_stt_tts",
                "stt_provider": _component_provider(
                    robot_settings.stt_primary if robot_settings else None,
                    STT_PROVIDER,
                ),
                "tts_provider": _component_provider(
                    robot_settings.tts_primary if robot_settings else None,
                    TTS_PROVIDER,
                ),
            },
        )
        raise

    voice_audio_cache = VoiceAudioCache(
        cache_dir=_VOICE_AUDIO_CACHE_DIR,
        tts_client=tts_client,
        enabled=VOICE_AUDIO_CACHE_ENABLED,
        legacy_profile_id=VOICE_AUDIO_LEGACY_PROFILE_ID,
    )

    if should_log_startup_provider_fallback(
        component_name="stt",
        configured_provider=_component_provider(
            robot_settings.stt_primary if robot_settings else None,
            STT_PROVIDER,
        ),
        actual_component=stt_client,
    ):
        provider, model = component_identity(stt_client)
        incident_log.record_nowait(
            "provider_fallback",
            severity="warning",
            component="stt",
            provider=provider,
            model=model,
            description="Configured STT provider was not used at startup",
            payload={
                "configured_provider": _component_provider(
                    robot_settings.stt_primary if robot_settings else None,
                    STT_PROVIDER,
                ),
                "actual_provider": provider,
                "actual_model": model,
            },
        )

    if should_log_startup_provider_fallback(
        component_name="tts",
        configured_provider=_component_provider(
            robot_settings.tts_primary if robot_settings else None,
            TTS_PROVIDER,
        ),
        actual_component=tts_client,
    ):
        provider, model = component_identity(tts_client)
        incident_log.record_nowait(
            "provider_fallback",
            severity="warning",
            component="tts",
            provider=provider,
            model=model,
            description="Configured TTS provider was not used at startup",
            payload={
                "configured_provider": _component_provider(
                    robot_settings.tts_primary if robot_settings else None,
                    TTS_PROVIDER,
                ),
                "actual_provider": provider,
                "actual_model": model,
            },
        )

    register_stt_fallback_incident_listener(stt_client, incident_log)
    register_component_metrics_listener(
        stt_client,
        component_name="stt",
        sink=component_metrics_events,
    )
    register_component_metrics_listener(
        tts_client,
        component_name="tts",
        sink=component_metrics_events,
    )
    for branch_name, llm_client in routed_llms.items():
        register_component_metrics_listener(
            llm_client,
            component_name=f"llm:{branch_name}",
            sink=component_metrics_events,
        )

    session = AgentSession(
        stt=stt_client,
        llm=session_llm or build_llm(),
        tts=tts_client,
        turn_handling={
            "turn_detection": turn_detection_mode,
            "endpointing": {
                "mode": endpointing_mode,
                "min_delay": min_endpointing_delay,
                "max_delay": max_endpointing_delay,
            },
        },
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=preemptive_generation,
    )
    background_audio = BackgroundAudioPlayer()

    async def on_client_silence_timeout() -> None:
        await request_client_silence_end_call()

    def is_client_disconnected() -> bool:
        return bool(client_disconnect_context)

    def client_disconnect_info() -> dict[str, Any]:
        return dict(client_disconnect_context)

    voice_prompts = VoicePromptManager(
        session=session,
        background_audio=background_audio,
        voice_audio_cache=voice_audio_cache,
        response_delay_prompt=VoicePromptSpec(
            kind="response_delay",
            audio_paths=_RESPONSE_DELAY_AUDIO_PATHS,
            phrase=VOICE_RESPONSE_DELAY_PHRASE,
        ),
        client_silence_prompt=VoicePromptSpec(
            kind="client_silence",
            audio_paths=_CLIENT_SILENCE_AUDIO_PATHS,
            phrase=VOICE_CLIENT_SILENCE_PHRASE,
            prefer_prerecorded=True,
        ),
        response_delay_sec=VOICE_RESPONSE_DELAY_SEC,
        response_delay_post_gap_sec=VOICE_RESPONSE_DELAY_POST_GAP_SEC,
        client_silence_first_sec=VOICE_CLIENT_SILENCE_FIRST_SEC,
        client_silence_sec=VOICE_CLIENT_SILENCE_SEC,
        client_silence_stt_grace_sec=VOICE_CLIENT_SILENCE_STT_GRACE_SEC,
        client_silence_max_prompts=VOICE_CLIENT_SILENCE_MAX_PROMPTS,
        is_closed=close_event.is_set,
        is_end_call_scheduled=lambda: bool(end_call_task and not end_call_task.done()),
        on_client_silence_timeout=on_client_silence_timeout,
        is_client_disconnected=is_client_disconnected,
        client_disconnect_info=client_disconnect_info,
        speech_playout_timeout_sec=VOICE_SPEECH_PLAYOUT_TIMEOUT_SEC,
        incident_log=incident_log,
    )

    def on_linked_participant_disconnected(
        disconnected_participant: rtc.RemoteParticipant,
    ) -> None:
        nonlocal client_disconnect_context, reply_watchdog_task, startup_no_dialog_task
        identity = str(getattr(disconnected_participant, "identity", "") or "")
        linked_identity = str(getattr(participant, "identity", "") or "")
        if not linked_identity:
            return
        if identity != linked_identity:
            return

        reason = disconnect_reason_name(
            getattr(disconnected_participant, "disconnect_reason", None)
        )
        if not client_disconnect_context:
            client_disconnect_context = {
                "disconnect_time": datetime.now(timezone.utc).isoformat(),
                "disconnect_reason": reason,
                "participant_identity": identity or None,
            }
            logger.info(
                "linked participant disconnected; canceling voice prompt timers",
                extra={
                    "participant": identity or None,
                    "reason": reason,
                },
            )
        voice_prompts.on_client_disconnected()
        request_recording_stop("participant_disconnected")
        if reply_watchdog_task and not reply_watchdog_task.done():
            reply_watchdog_task.cancel()
            reply_watchdog_task = None
        if startup_no_dialog_task and not startup_no_dialog_task.done():
            startup_no_dialog_task.cancel()
            startup_no_dialog_task = None

    participant_disconnect_cleanup_handler = on_linked_participant_disconnected
    ctx.room.on("participant_disconnected", participant_disconnect_cleanup_handler)

    logger.info(
        "session latency guards configured",
        extra={
            "llm_first_token_timeout_sec": LLM_FIRST_TOKEN_TIMEOUT_SEC,
            "llm_fallback_first_token_timeout_sec": LLM_FALLBACK_FIRST_TOKEN_TIMEOUT_SEC,
            "llm_attempt_timeout_sec": routed_llm_metadata[
                "complex"
            ].attempt_timeout_sec
            if "complex" in routed_llm_metadata
            else LLM_ATTEMPT_TIMEOUT_SEC,
            "llm_max_retry_per_llm": routed_llm_metadata["complex"].max_retry_per_llm
            if "complex" in routed_llm_metadata
            else LLM_MAX_RETRY_PER_LLM,
            "llm_retry_interval_sec": routed_llm_metadata["complex"].retry_interval_sec
            if "complex" in routed_llm_metadata
            else LLM_RETRY_INTERVAL_SEC,
            "llm_retry_on_chunk_sent": routed_llm_metadata[
                "complex"
            ].retry_on_chunk_sent
            if "complex" in routed_llm_metadata
            else LLM_RETRY_ON_CHUNK_SENT,
            "use_livekit_fallback_adapter": routed_llm_metadata[
                "complex"
            ].uses_fallback_adapter
            if "complex" in routed_llm_metadata
            else USE_LIVEKIT_FALLBACK_ADAPTER,
            "preemptive_generation": preemptive_generation,
            "turn_detection_mode": configured_turn_detection_mode,
            "turn_endpointing_mode": endpointing_mode,
            "turn_min_endpointing_delay": min_endpointing_delay,
            "turn_max_endpointing_delay": max_endpointing_delay,
            "reply_watchdog_sec": REPLY_WATCHDOG_SEC,
            "stt_early_interim_final_enabled": _config_bool(
                turn_config,
                "early_interim_final_enabled",
                STT_EARLY_INTERIM_FINAL_ENABLED,
            ),
            "stt_early_interim_final_delay_sec": _config_float(
                turn_config,
                "early_interim_final_delay_sec",
                STT_EARLY_INTERIM_FINAL_DELAY_SEC,
            ),
            "stt_early_interim_final_min_stable_interims": STT_EARLY_INTERIM_FINAL_MIN_STABLE_INTERIMS,
            "voice_initial_greeting_delay_sec": VOICE_INITIAL_GREETING_DELAY_SEC,
            "voice_speech_playout_timeout_sec": VOICE_SPEECH_PLAYOUT_TIMEOUT_SEC,
            "voice_sip_participant_wait_timeout_sec": (
                VOICE_SIP_PARTICIPANT_WAIT_TIMEOUT_SEC
            ),
            "voice_audio_output_ready_timeout_sec": (
                VOICE_AUDIO_OUTPUT_READY_TIMEOUT_SEC
            ),
            "voice_startup_no_dialog_timeout_sec": VOICE_STARTUP_NO_DIALOG_TIMEOUT_SEC,
            "voice_response_delay_sec": VOICE_RESPONSE_DELAY_SEC,
            "voice_response_delay_post_gap_sec": VOICE_RESPONSE_DELAY_POST_GAP_SEC,
            "voice_response_delay_audio_paths": [
                str(path) for path in _RESPONSE_DELAY_AUDIO_PATHS
            ],
            "voice_client_silence_first_sec": VOICE_CLIENT_SILENCE_FIRST_SEC,
            "voice_client_silence_sec": VOICE_CLIENT_SILENCE_SEC,
            "voice_client_silence_stt_grace_sec": VOICE_CLIENT_SILENCE_STT_GRACE_SEC,
            "voice_client_silence_max_prompts": VOICE_CLIENT_SILENCE_MAX_PROMPTS,
            "voice_short_greeting_delay_sec": VOICE_SHORT_GREETING_DELAY_SEC,
            "voice_client_silence_audio_paths": [
                str(path) for path in _CLIENT_SILENCE_AUDIO_PATHS
            ],
            "voice_client_silence_audio_path": str(_CLIENT_SILENCE_AUDIO_PATH)
            if _CLIENT_SILENCE_AUDIO_PATH
            else None,
            "voice_emergency_audio_path": str(_EMERGENCY_AUDIO_PATH)
            if _EMERGENCY_AUDIO_PATH
            else None,
            "voice_audio_cache_enabled": VOICE_AUDIO_CACHE_ENABLED,
            "voice_audio_cache_dir": str(_VOICE_AUDIO_CACHE_DIR),
            "voice_audio_cache_profile_id": voice_audio_cache.voice_profile_id,
        },
    )

    def maybe_start_response_delay_timer() -> None:
        nonlocal response_delay_started_for_turn
        if not should_start_response_delay_after_vad(
            has_final_transcript=response_delay_has_final_transcript,
            user_stopped_speaking=response_delay_user_stopped_speaking,
            already_started=response_delay_started_for_turn,
        ):
            return
        response_delay_started_for_turn = True
        voice_prompts.start_response_delay_timer()

    def mark_startup_dialog_activity(activity: str, **payload: Any) -> None:
        nonlocal startup_dialog_activity_seen, startup_no_dialog_task
        if startup_dialog_activity_seen:
            return
        startup_dialog_activity_seen = True
        logger.info(
            "startup dialog activity observed",
            extra={"activity": activity, **payload},
        )
        if startup_no_dialog_task and not startup_no_dialog_task.done():
            startup_no_dialog_task.cancel()
            startup_no_dialog_task = None

    async def handle_unrecoverable_error(ev: Any) -> None:
        nonlocal unrecoverable_error_response_started
        if unrecoverable_error_response_started:
            return
        unrecoverable_error_response_started = True
        await voice_prompts.stop_active_prompt()

        err = getattr(ev, "error", None)
        err_type = str(getattr(err, "type", type(err).__name__))
        emergency_audio_path = _EMERGENCY_AUDIO_PATH
        if err_type == "tts_error":
            emergency_audio_path = voice_audio_cache.get_existing(
                kind="emergency",
                text=VOICE_EMERGENCY_PHRASE,
                legacy_path=_EMERGENCY_AUDIO_PATH,
                allow_legacy_any_profile=True,
            )
        else:
            emergency_audio_path = await voice_audio_cache.get_or_create(
                kind="emergency",
                text=VOICE_EMERGENCY_PHRASE,
                legacy_path=_EMERGENCY_AUDIO_PATH,
            )

        if emergency_audio_path is not None:
            played = await play_prerecorded_audio(
                session=session,
                audio_path=emergency_audio_path,
                sample_rate=audio_output_sample_rate,
                allow_interruptions=False,
                add_to_chat_ctx=False,
                text=VOICE_EMERGENCY_PHRASE,
                playback_kind="emergency",
                timeout_sec=VOICE_SPEECH_PLAYOUT_TIMEOUT_SEC,
                incident_log=incident_log,
            )
            if played:
                if err_type == "tts_error":
                    await request_tag_end_call("unrecoverable_tts_error")
                return

        # If TTS itself is broken and no emergency audio exists, saying a text
        # fallback would likely loop back into the same failing TTS path.
        if err_type == "tts_error":
            logger.warning(
                "unrecoverable TTS error has no playable emergency audio fallback"
            )
            await request_tag_end_call("unrecoverable_tts_error")
            return

        try:
            handle = session.say(
                VOICE_EMERGENCY_PHRASE,
                allow_interruptions=False,
                add_to_chat_ctx=False,
            )
            await wait_for_speech_playout(
                handle,
                kind="emergency",
                log_label="emergency fallback",
                timeout_sec=VOICE_SPEECH_PLAYOUT_TIMEOUT_SEC,
                incident_log=incident_log,
                payload={"source": "session.say"},
            )
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
            incident_log.record_nowait(
                "reply_watchdog_fired",
                severity="warning",
                component="turn_runtime",
                latency_ms=REPLY_WATCHDOG_SEC * 1000,
                description="No assistant reply appeared before reply watchdog timeout",
                payload={
                    "timeout_sec": REPLY_WATCHDOG_SEC,
                    "user_activity_count": user_activity_count,
                    "assistant_message_count": assistant_message_count,
                    "agent_state": session.agent_state,
                },
            )
            # Safety path for stuck scheduling:
            # - disable tools to prevent accidental action calls
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

    @session.on("speech_created")
    def on_speech_created(ev):
        try:
            handle = getattr(ev, "speech_handle", None)
            source = getattr(ev, "source", None)
            logger.info(
                "speech created",
                extra={
                    "source": source,
                    "user_initiated": getattr(ev, "user_initiated", None),
                    "speech_id": speech_handle_id(handle),
                    "allow_interruptions": getattr(handle, "allow_interruptions", None),
                },
            )
            if handle is not None and hasattr(handle, "add_done_callback"):

                def _on_speech_done(done_handle: Any) -> None:
                    with suppress(Exception):
                        logger.info(
                            "speech completed",
                            extra={
                                "source": source,
                                "user_initiated": getattr(ev, "user_initiated", None),
                                "speech_id": speech_handle_id(done_handle),
                                "interrupted": getattr(done_handle, "interrupted", None),
                                "allow_interruptions": getattr(
                                    done_handle,
                                    "allow_interruptions",
                                    None,
                                ),
                            },
                        )

                handle.add_done_callback(_on_speech_done)
        except Exception as e:
            logger.exception("speech_created handler failed: %s", e)

    @session.on("overlapping_speech")
    def on_overlapping_speech(ev):
        try:
            logger.info(
                "overlapping speech detected",
                extra={
                    "is_interruption": getattr(ev, "is_interruption", None),
                    "probability": getattr(ev, "probability", None),
                    "num_requests": getattr(ev, "num_requests", None),
                    "total_duration_ms": round(
                        float(getattr(ev, "total_duration", 0.0) or 0.0) * 1000,
                        1,
                    ),
                    "prediction_duration_ms": round(
                        float(getattr(ev, "prediction_duration", 0.0) or 0.0)
                        * 1000,
                        1,
                    ),
                    "detection_delay_ms": round(
                        float(getattr(ev, "detection_delay", 0.0) or 0.0) * 1000,
                        1,
                    ),
                    "overlap_started_at": getattr(ev, "overlap_started_at", None),
                    "detected_at": getattr(ev, "detected_at", None),
                },
            )
        except Exception as e:
            logger.exception("overlapping_speech handler failed: %s", e)

    @session.on("agent_false_interruption")
    def on_agent_false_interruption(ev):
        try:
            logger.info(
                "agent false interruption detected",
                extra={
                    "resumed": getattr(ev, "resumed", None),
                    "created_at": getattr(ev, "created_at", None),
                },
            )
        except Exception as e:
            logger.exception("agent_false_interruption handler failed: %s", e)

    @session.on("conversation_item_added")
    def on_conversation_item_added(ev):
        nonlocal assistant_message_count, reply_watchdog_task
        nonlocal slow_response_logged_for_current_turn
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
        nonlocal pending_user_phrase_end_at, pending_user_phrase_end_source
        nonlocal user_activity_count, end_call_task, reply_watchdog_task
        nonlocal last_final_user_turn_started_at, last_final_user_turn_text_len
        nonlocal slow_response_logged_for_current_turn
        nonlocal response_delay_has_final_transcript
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
            raw_transcript = getattr(ev, "transcript", None)
            transcript = (raw_transcript or "").strip()
            is_final = bool(getattr(ev, "is_final", False))
            if transcript:
                logger.info(
                    "user input transcribed",
                    extra={
                        "transcript": transcript,
                        "is_final": is_final,
                        "language": getattr(ev, "language", None),
                    },
                )
                mark_startup_dialog_activity(
                    "user_input_transcribed",
                    is_final=is_final,
                    transcript_len=len(transcript),
                )
                # Any new user speech cancels a pending auto-hangup timer.
                user_activity_count += 1
                voice_prompts.on_user_transcribed(is_final=is_final)
                if is_final and pending_user_phrase_end_at is None:
                    pending_user_phrase_end_at = event_timestamp_seconds(
                        ev,
                        default=time.time(),
                    )
                    pending_user_phrase_end_source = "final_transcript"
                if is_final:
                    last_final_user_turn_started_at = time.monotonic()
                    last_final_user_turn_text_len = len(transcript)
                    slow_response_logged_for_current_turn = False
                if is_response_delay_candidate_transcript(
                    raw_transcript,
                    is_final=is_final,
                ):
                    response_delay_has_final_transcript = True
                    maybe_start_response_delay_timer()
                if is_final and REPLY_WATCHDOG_SEC > 0:
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
        nonlocal pending_user_phrase_end_at, pending_user_phrase_end_source
        nonlocal response_delay_has_final_transcript
        nonlocal response_delay_user_stopped_speaking
        nonlocal response_delay_started_for_turn
        try:
            old_state = getattr(ev, "old_state", None)
            new_state = getattr(ev, "new_state", None)
            old_state_value = state_value(old_state)
            new_state_value = state_value(new_state)
            logger.info(
                "user state changed",
                extra={"old_state": old_state_value, "new_state": new_state_value},
            )
            if new_state_value == "speaking":
                mark_startup_dialog_activity(
                    "user_state_speaking",
                    old_state=old_state_value,
                    new_state=new_state_value,
                )
                pending_user_phrase_end_at = None
                pending_user_phrase_end_source = None
                response_delay_has_final_transcript = False
                response_delay_user_stopped_speaking = False
                response_delay_started_for_turn = False
                assistant.note_user_started_speaking()
                started_at = getattr(ev, "created_at", None)
                notify_local_start_of_speech = getattr(
                    stt_client, "notify_local_start_of_speech", None
                )
                if callable(notify_local_start_of_speech):
                    notify_local_start_of_speech(started_at=started_at)
                voice_prompts.on_user_started_speaking()
                return
            if old_state_value == "speaking" and new_state_value == "listening":
                ended_at = event_timestamp_seconds(ev, default=time.time())
                pending_user_phrase_end_at = ended_at
                pending_user_phrase_end_source = "user_state_changed"
                if isinstance(ended_at, (int, float)):
                    logger.info(
                        "local VAD end of speech",
                        extra={
                            "ended_at": ended_at,
                            "handler_lag_ms": round(
                                max(0.0, time.time() - float(ended_at)) * 1000,
                                1,
                            ),
                        },
                    )
                notify_local_end_of_speech = getattr(
                    stt_client, "notify_local_end_of_speech", None
                )
                if callable(notify_local_end_of_speech):
                    notify_local_end_of_speech(ended_at=ended_at)
                assistant.note_user_finished_speaking()
                response_delay_user_stopped_speaking = True
                maybe_start_response_delay_timer()
                voice_prompts.on_user_finished_speaking()
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
        nonlocal agent_speaking_revision
        nonlocal pending_user_phrase_end_at, pending_user_phrase_end_source
        nonlocal reply_watchdog_task
        nonlocal slow_response_logged_for_current_turn
        try:
            old_state = getattr(ev, "old_state", None)
            new_state = getattr(ev, "new_state", None)
            logger.info(
                "agent state changed",
                extra={
                    "old_state": old_state,
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
                mark_startup_dialog_activity(
                    f"agent_state_{new_state}",
                    old_state=old_state,
                    new_state=new_state,
                )
                voice_prompts.cancel_client_silence_timer()
            if new_state == "speaking":
                agent_speaking_revision += 1
                tts_first_frame_ready_at = assistant._tts_first_frame_ready_at
                tts_first_frame_yielded_at = assistant._tts_first_frame_yielded_at
                assistant._tts_first_frame_ready_at = None
                assistant._tts_first_frame_yielded_at = None
                created_at = event_timestamp_seconds(ev, default=time.time())
                latency_ms = turn_response_latency_ms(
                    user_phrase_ended_at=pending_user_phrase_end_at,
                    assistant_started_at=created_at,
                )
                if (
                    latency_ms is not None
                    and not slow_response_logged_for_current_turn
                    and should_log_slow_response_latency(
                        latency_ms,
                        INCIDENT_SLOW_RESPONSE_MS,
                    )
                ):
                    slow_response_logged_for_current_turn = True
                    incident_log.record_nowait(
                        "slow_response",
                        severity="warning",
                        component="voice_pipeline",
                        latency_ms=latency_ms,
                        description=(
                            "Assistant speech started after response latency threshold"
                        ),
                        payload={
                            "threshold_ms": INCIDENT_SLOW_RESPONSE_MS,
                            "measured_from": pending_user_phrase_end_source,
                            "user_phrase_ended_at": pending_user_phrase_end_at,
                            "assistant_started_speaking_at": created_at,
                            "user_activity_count": user_activity_count,
                            "final_transcript_len": last_final_user_turn_text_len,
                            "metric_source": "agent_state_changed",
                        },
                    )
                pending_user_phrase_end_at = None
                pending_user_phrase_end_source = None
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
            elif old_state == "speaking" and new_state == "listening":
                voice_prompts.on_agent_finished_speaking()
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
            incident_log.record_nowait(
                "agent_session_error",
                severity="warning" if recoverable else "error",
                component=str(
                    getattr(err, "type", "livekit_session") or "livekit_session"
                ),
                provider=getattr(source, "provider", None),
                model=getattr(source, "model", None),
                error_type=str(getattr(err, "type", type(err).__name__)),
                description=str(getattr(err, "label", None) or "Agent session error"),
                payload={
                    "recoverable": recoverable,
                    "error_label": getattr(err, "label", None),
                    "source_label": getattr(source, "label", None),
                    "error": safe_dump(err),
                    "source": {
                        "provider": getattr(source, "provider", None),
                        "model": getattr(source, "model", None),
                        "label": getattr(source, "label", None),
                    },
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
            "client_id": getattr(prompt_resolution, "client_id", None),
            "started_at": session_started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "duration_sec": (ended_at - session_started_at).total_seconds(),
            "close": close_info,
            "sip": {
                **sip_call_numbers,
                "trace_id": sip_diagnostic_context.get("trace_id"),
                "sip_call_id": sip_diagnostic_context.get("sip_call_id"),
                "prompt_source": prompt_resolution.source,
                "prompt_lookup_error": prompt_resolution.error,
            },
            "transcript_items": transcript_items,
            "tag_events": tag_events,
            "usage_updates": usage_updates,
            "metrics_events": metrics_events,
            "component_metrics_events": component_metrics_events,
            "summary": {
                "transcript_count": len(transcript_items),
                "tag_event_count": len(tag_events),
                "usage_update_count": len(usage_updates),
                "metrics_count": len(metrics_events),
                "component_metrics_count": len(component_metrics_events),
            },
        }

        logger.info("sending session data to n8n")
        if recording_stop_task and not recording_stop_task.done():
            try:
                await asyncio.wait_for(
                    asyncio.shield(recording_stop_task),
                    timeout=max(CALL_RECORDING_STOP_TIMEOUT_SEC, 0.5) + 0.5,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "room recording stop still pending before export",
                    extra={"room": ctx.room.name},
                )
        try:
            egress_info = await finalize_room_recording(recording_handle)
            if (
                egress_info is not None
                and getattr(egress_info, "status", None) in ACTIVE_EGRESS_STATUSES
            ):
                incident_log.record_nowait(
                    "egress_finalize_lag",
                    severity="warning",
                    component="livekit_egress",
                    description=(
                        "LiveKit room recording was still active after finalize timeout"
                    ),
                    payload={
                        "room": ctx.room.name,
                        "egress_id": getattr(egress_info, "egress_id", None),
                        "status": state_value(getattr(egress_info, "status", None)),
                        "finalize_timeout_sec": CALL_RECORDING_FINALIZE_TIMEOUT_SEC,
                    },
                )
        except Exception as e:
            logger.warning("failed to finalize room recording metadata: %s", e)
            incident_log.record_exception_nowait(
                "call_recording_failed",
                e,
                severity="warning",
                component="livekit_egress",
                description="Failed to finalize LiveKit room recording metadata",
            )
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

    async def stop_recording_safely(reason: str) -> None:
        nonlocal recording_stop_requested
        if recording_handle is None:
            return
        if recording_stop_requested:
            return
        recording_stop_requested = True
        logger.info(
            "stopping room recording",
            extra={
                "reason": reason,
                "egress_id": recording_handle.egress_id,
                "room": recording_handle.room_name,
            },
        )
        try:
            info = await stop_room_recording(recording_handle)
            logger.info(
                "room recording stop requested",
                extra={
                    "reason": reason,
                    "egress_id": recording_handle.egress_id,
                    "status": state_value(getattr(info, "status", None))
                    if info is not None
                    else None,
                },
            )
        except Exception as e:
            logger.warning(
                "failed to stop room recording: %s",
                e,
                extra={
                    "reason": reason,
                    "egress_id": recording_handle.egress_id,
                    "room": recording_handle.room_name,
                },
            )
            incident_log.record_exception_nowait(
                "call_recording_failed",
                e,
                severity="warning",
                component="livekit_egress",
                description="Failed to stop LiveKit room recording during cleanup",
                payload={
                    "reason": reason,
                    "egress_id": recording_handle.egress_id,
                    "room": recording_handle.room_name,
                },
            )

    def request_recording_stop(reason: str) -> None:
        nonlocal recording_stop_task
        if recording_handle is None:
            return
        if recording_stop_task and not recording_stop_task.done():
            return
        recording_stop_task = asyncio.create_task(
            stop_recording_safely(reason),
            name=f"stop_room_recording:{reason}",
        )

    async def delete_room_safely(
        reason: str,
        *,
        close_reason: str | None = None,
    ) -> None:
        resolved_close_reason = close_reason or f"tag_action:{reason}"
        try:
            close_info["reason"] = resolved_close_reason
            voice_prompts.cancel_client_silence_timer()
            voice_prompts.cancel_response_delay_timer()
            logger.info(
                "ending call by deleting room",
                extra={
                    "room": ctx.room.name,
                    "reason": reason,
                    "close_reason": resolved_close_reason,
                },
            )
            # Delete the room first so the SIP leg is dropped immediately after
            # the final tagged phrase finishes.
            await asyncio.wait_for(
                asyncio.shield(ctx.delete_room(ctx.room.name)), timeout=3.0
            )
            logger.info(
                "room delete completed",
                extra={
                    "room": ctx.room.name,
                    "reason": reason,
                    "close_reason": resolved_close_reason,
                },
            )
        except asyncio.TimeoutError:
            logger.warning("delete_room timed out; forcing local shutdown")
            incident_log.record_nowait(
                "abnormal_close",
                severity="warning",
                component="livekit_room",
                error_type="TimeoutError",
                description="delete_room timed out while ending call",
                payload={
                    "reason": reason,
                    "close_reason": resolved_close_reason,
                    "room": ctx.room.name,
                },
            )
            await stop_recording_safely(resolved_close_reason)
        except Exception as e:
            logger.exception("failed to delete room: %s", e)
            resolved_close_reason = (
                f"{close_reason}_failed"
                if close_reason
                else f"tag_action_failed:{reason}"
            )
            close_info["reason"] = resolved_close_reason
            incident_log.record_exception_nowait(
                "abnormal_close",
                e,
                severity="warning",
                component="livekit_room",
                description="delete_room failed while ending call",
                payload={
                    "reason": reason,
                    "close_reason": resolved_close_reason,
                    "room": ctx.room.name,
                },
            )
            await stop_recording_safely(resolved_close_reason)
        finally:
            # Unblock main entrypoint even if LiveKit close signal arrives late.
            close_event.set()
            # Ensure worker exits promptly after final playout and grace window.
            ctx.shutdown(reason=resolved_close_reason)
            # Close local AgentSession explicitly so entrypoint does not hang
            # waiting for an external room-close callback.
            await ensure_session_closed(timeout_sec=2.0)

    async def request_tag_end_call(reason: str) -> str:
        nonlocal end_call_task
        if end_call_task and not end_call_task.done():
            return "END_CALL_ALREADY_SCHEDULED"

        voice_prompts.cancel_client_silence_timer()
        voice_prompts.cancel_response_delay_timer()

        async def end_after_tag() -> None:
            try:
                await delete_room_safely(reason)
            except asyncio.CancelledError:
                logger.info("tag end-call task canceled")
            except Exception as e:
                logger.exception("tag end-call task failed: %s", e)

        end_call_task = asyncio.create_task(end_after_tag(), name="tag_end_call")
        return "END_CALL_SCHEDULED"

    async def request_client_silence_end_call() -> str:
        nonlocal end_call_task
        if end_call_task and not end_call_task.done():
            return "END_CALL_ALREADY_SCHEDULED"

        voice_prompts.cancel_response_delay_timer()

        async def end_after_client_silence() -> None:
            try:
                await delete_room_safely(
                    "client_silence_timeout",
                    close_reason="client_silence_timeout",
                )
            except asyncio.CancelledError:
                logger.info("client silence end-call task canceled")
            except Exception as e:
                logger.exception("client silence end-call task failed: %s", e)

        end_call_task = asyncio.create_task(
            end_after_client_silence(),
            name="client_silence_end_call",
        )
        return "END_CALL_SCHEDULED"

    async def request_no_dialog_startup_end_call() -> str:
        nonlocal end_call_task
        if end_call_task and not end_call_task.done():
            return "END_CALL_ALREADY_SCHEDULED"

        voice_prompts.cancel_response_delay_timer()
        voice_prompts.cancel_client_silence_timer()

        async def end_after_no_dialog() -> None:
            try:
                await delete_room_safely(
                    "no_dialog_startup_timeout",
                    close_reason="no_dialog_startup_timeout",
                )
            except asyncio.CancelledError:
                logger.info("no-dialog startup end-call task canceled")
            except Exception as e:
                logger.exception("no-dialog startup end-call task failed: %s", e)

        end_call_task = asyncio.create_task(
            end_after_no_dialog(),
            name="no_dialog_startup_end_call",
        )
        return "END_CALL_SCHEDULED"

    async def startup_no_dialog_watchdog() -> None:
        try:
            await asyncio.sleep(VOICE_STARTUP_NO_DIALOG_TIMEOUT_SEC)
            if not should_fire_startup_no_dialog_timeout(
                timeout_sec=VOICE_STARTUP_NO_DIALOG_TIMEOUT_SEC,
                close_event_set=close_event.is_set(),
                dialog_activity_seen=startup_dialog_activity_seen,
                end_call_scheduled=bool(end_call_task and not end_call_task.done()),
            ):
                return
            logger.warning(
                "startup no-dialog timeout reached",
                extra={
                    "timeout_sec": VOICE_STARTUP_NO_DIALOG_TIMEOUT_SEC,
                    "agent_state": session.agent_state,
                    "user_activity_count": user_activity_count,
                    "assistant_message_count": assistant_message_count,
                },
            )
            incident_log.record_nowait(
                "no_dialog_startup_timeout",
                severity="warning",
                component="turn_runtime",
                latency_ms=VOICE_STARTUP_NO_DIALOG_TIMEOUT_SEC * 1000,
                error_type="TimeoutError",
                description=(
                    "No assistant speech, user speech, or transcript appeared after "
                    "session start"
                ),
                payload={
                    "timeout_sec": VOICE_STARTUP_NO_DIALOG_TIMEOUT_SEC,
                    "agent_state": session.agent_state,
                    "user_activity_count": user_activity_count,
                    "assistant_message_count": assistant_message_count,
                },
            )
            await request_no_dialog_startup_end_call()
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.exception("startup no-dialog watchdog failed: %s", e)

    @session.on("close")
    def on_close(ev):
        nonlocal reply_watchdog_task, startup_no_dialog_task
        if close_event.is_set():
            return
        close_info["reason"] = str(getattr(ev, "reason", None))
        err = getattr(ev, "error", None)
        close_info["error"] = str(err) if err else None
        if is_abnormal_close(close_info["reason"], close_info["error"]):
            incident_log.record_nowait(
                "abnormal_close",
                severity="warning",
                component="livekit_session",
                error_type=type(err).__name__ if err else None,
                description="LiveKit session closed with abnormal reason or error",
                payload={"close": dict(close_info)},
            )
        if reply_watchdog_task and not reply_watchdog_task.done():
            reply_watchdog_task.cancel()
            reply_watchdog_task = None
        if startup_no_dialog_task and not startup_no_dialog_task.done():
            startup_no_dialog_task.cancel()
            startup_no_dialog_task = None
        voice_prompts.cancel_response_delay_timer()
        voice_prompts.cancel_client_silence_timer()
        if should_stop_recording_on_close(close_info["reason"]):
            request_recording_stop(close_info["reason"] or "session_close")
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
            incident_log.record_nowait(
                "n8n_export_failed",
                severity="warning",
                component="n8n_export",
                latency_ms=timeout_sec * 1000,
                error_type="TimeoutError",
                description="n8n session export timed out",
                payload={"timeout_sec": timeout_sec},
            )
        except asyncio.CancelledError:
            # Preserve cancellation semantics for outer handler, but do not lose
            # the in-flight export task. It will be awaited again in cancel path.
            raise
        except BaseException as e:
            logger.exception("n8n export failed: %s", e)
            incident_log.record_exception_nowait(
                "n8n_export_failed",
                e,
                severity="warning",
                component="n8n_export",
                description="n8n session export failed",
            )

    try:
        logger.info(
            "prompt resolved",
            extra={
                "source": prompt_resolution.source,
                "sip_trunk_number": prompt_resolution.sip_trunk_number,
                "gateway_number": sip_call_numbers["gateway_number"],
                "sip_client_number": prompt_resolution.sip_client_number,
            },
        )
        participant_identity = str(getattr(participant, "identity", "") or "") or None
        tag_skill_runner = RobotSkillRunner(
            context=RobotSkillContext(
                agent_name=AGENT_NAME,
                room_name=ctx.room.name,
                participant_identity=participant_identity,
                sip_call_numbers=sip_call_numbers,
            ),
            request_end_call=request_tag_end_call,
            record_event=tag_events.append,
        )
        if prompt_resolution.error:
            incident_log.record_nowait(
                "prompt_lookup_failed",
                severity="warning",
                component="prompt_repo",
                error_type=classify_error(RuntimeError(prompt_resolution.error)),
                description="Prompt lookup failed; file prompt was used",
                payload={
                    "prompt_source": prompt_resolution.source,
                    "error": prompt_resolution.error,
                    "sip_trunk_number": prompt_resolution.sip_trunk_number,
                    "gateway_number": sip_call_numbers["gateway_number"],
                    "sip_client_number": prompt_resolution.sip_client_number,
                },
            )

        assistant = Assistant(
            model_router=model_router,
            routed_llms=routed_llms,
            routed_llm_providers=routed_llm_providers,
            routed_llm_metadata=routed_llm_metadata,
            fallback_llm=fallback_llm,
            fallback_llm_provider=fallback_llm_provider_name,
            first_turn_short_greeting_audio_path=_SHORT_GREETING_AUDIO_PATH,
            first_turn_short_greeting_phrase=VOICE_SHORT_GREETING_PHRASE,
            first_turn_short_greeting_delay_sec=VOICE_SHORT_GREETING_DELAY_SEC,
            prerecorded_audio_sample_rate=audio_output_sample_rate,
            voice_audio_cache=voice_audio_cache,
            voice_prompts=voice_prompts,
            tag_skill_runner=tag_skill_runner,
            prompt=prompt_resolution.prompt,
            incident_logger=incident_log,
        )

        try:
            await session.start(
                agent=assistant,
                room=ctx.room,
                room_options=build_agent_room_options(
                    audio_output_sample_rate=audio_output_sample_rate,
                    participant_identity=participant_identity,
                ),
            )
            session_started = True
        except Exception as e:
            startup_failure_recorded = True
            await incident_log.record_exception(
                "session_start_failed",
                e,
                severity="critical",
                component="livekit_session",
                description="AgentSession.start failed",
                payload={"phase": "session.start"},
            )
            raise
        if participant_missing_before_settings:
            logger.warning(
                "closing call before initial greeting because SIP participant was not resolved",
                extra={"timeout_sec": VOICE_SIP_PARTICIPANT_WAIT_TIMEOUT_SEC},
            )
            await delete_room_safely(
                "sip_participant_not_ready",
                close_reason="sip_participant_not_ready",
            )
            close_event.set()
            await export_best_effort(timeout_sec=export_wait_sec)
            return
        if not await wait_for_room_audio_output_ready(
            session,
            timeout_sec=VOICE_AUDIO_OUTPUT_READY_TIMEOUT_SEC,
        ):
            logger.warning(
                "room audio output was not ready before initial greeting",
                extra={
                    "timeout_sec": VOICE_AUDIO_OUTPUT_READY_TIMEOUT_SEC,
                    "participant_identity": participant_identity,
                    "sip_call_id": sip_diagnostic_context.get("sip_call_id"),
                },
            )
            incident_log.record_nowait(
                "room_audio_output_not_ready",
                severity="warning",
                component="livekit_room",
                latency_ms=int(VOICE_AUDIO_OUTPUT_READY_TIMEOUT_SEC * 1000),
                error_type="TimeoutError",
                description="Room audio output was not ready before initial greeting",
                payload={
                    "timeout_sec": VOICE_AUDIO_OUTPUT_READY_TIMEOUT_SEC,
                    "participant_identity": participant_identity,
                    "sip_call_id": sip_diagnostic_context.get("sip_call_id"),
                },
            )
            await delete_room_safely(
                "room_audio_output_not_ready",
                close_reason="room_audio_output_not_ready",
            )
            close_event.set()
            await export_best_effort(timeout_sec=export_wait_sec)
            return
        if VOICE_STARTUP_NO_DIALOG_TIMEOUT_SEC > 0:
            startup_no_dialog_task = asyncio.create_task(
                startup_no_dialog_watchdog(),
                name="startup_no_dialog_watchdog",
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
        initial_greeting_audio_path = None
        should_greet = should_play_initial_greeting(
            close_event_set=close_event.is_set(),
        )
        if should_greet:
            (
                initial_greeting,
                initial_greeting_audio_path,
            ) = await resolve_initial_greeting_audio(
                voice_audio_cache=voice_audio_cache,
                client_greeting=prompt_resolution.initial_greeting,
                default_greeting=VOICE_INITIAL_GREETING_PHRASE,
                prerecorded_path=_INITIAL_GREETING_AUDIO_PATH,
            )
            logger.info(
                "initial greeting resolved",
                extra={
                    "source": "directus"
                    if (prompt_resolution.initial_greeting or "").strip()
                    else "default",
                    "text_len": len(initial_greeting or ""),
                    "audio_path": str(initial_greeting_audio_path)
                    if initial_greeting_audio_path is not None
                    else None,
                    "voice_audio_cache_enabled": VOICE_AUDIO_CACHE_ENABLED,
                },
            )
        else:
            initial_greeting = (
                prompt_resolution.initial_greeting or ""
            ).strip() or VOICE_INITIAL_GREETING_PHRASE
            logger.info(
                "initial greeting skipped",
                extra={"reason": "close_event_set", "text_len": len(initial_greeting)},
            )
        played_initial_greeting = False
        if should_greet:
            assistant.begin_initial_greeting()
            try:
                if (
                    initial_greeting_audio_path is not None
                    and should_play_initial_greeting(
                        close_event_set=close_event.is_set(),
                    )
                ):
                    await wait_for_initial_greeting_delay(
                        VOICE_INITIAL_GREETING_DELAY_SEC
                    )
                    if should_play_initial_greeting(
                        close_event_set=close_event.is_set(),
                    ):
                        speaking_revision_before = agent_speaking_revision
                        played_initial_greeting = await play_prerecorded_audio(
                            session=session,
                            audio_path=initial_greeting_audio_path,
                            sample_rate=audio_output_sample_rate,
                            allow_interruptions=False,
                            add_to_chat_ctx=False,
                            text=initial_greeting,
                            playback_kind="initial_greeting",
                            timeout_sec=VOICE_SPEECH_PLAYOUT_TIMEOUT_SEC,
                            incident_log=incident_log,
                        )
                        if played_initial_greeting and not speech_playout_was_observed(
                            speaking_revision_before=speaking_revision_before,
                            speaking_revision_after=agent_speaking_revision,
                        ):
                            logger.warning(
                                "initial greeting playback completed without observed speaking state",
                                extra={
                                    "source": "prerecorded_audio",
                                    "speech_revision_before": speaking_revision_before,
                                    "speech_revision_after": agent_speaking_revision,
                                },
                            )
                            played_initial_greeting = False
                # Do not block call flow if warmup is still in progress.
                if runtime_warmup_task and not runtime_warmup_task.done():
                    with suppress(Exception):
                        await asyncio.wait_for(
                            asyncio.shield(runtime_warmup_task),
                            timeout=0.25,
                        )
                if not played_initial_greeting and should_play_initial_greeting(
                    close_event_set=close_event.is_set(),
                ):
                    logger.info(
                        "initial greeting tts fallback started",
                        extra={"text_len": len(initial_greeting or "")},
                    )
                    speaking_revision_before = agent_speaking_revision
                    handle = session.say(
                        initial_greeting,
                        allow_interruptions=False,
                        add_to_chat_ctx=True,
                    )
                    played_initial_greeting = await wait_for_speech_playout(
                        handle,
                        kind="initial_greeting",
                        log_label="initial greeting tts fallback",
                        timeout_sec=VOICE_SPEECH_PLAYOUT_TIMEOUT_SEC,
                        incident_log=incident_log,
                        payload={
                            "source": "session.say",
                            "text_len": len(initial_greeting or ""),
                        },
                    )
                    if played_initial_greeting and not speech_playout_was_observed(
                        speaking_revision_before=speaking_revision_before,
                        speaking_revision_after=agent_speaking_revision,
                    ):
                        logger.warning(
                            "initial greeting tts fallback completed without observed speaking state",
                            extra={
                                "source": "session.say",
                                "speech_revision_before": speaking_revision_before,
                                "speech_revision_after": agent_speaking_revision,
                            },
                        )
                        played_initial_greeting = False
                    if played_initial_greeting:
                        logger.info("initial greeting tts fallback finished")
                    else:
                        logger.warning("initial greeting was not completed")
            finally:
                clear_initial_greeting_user_turn(session)
                assistant.finish_initial_greeting()
        if played_initial_greeting:
            voice_prompts.on_agent_finished_speaking()
        elif should_greet and not close_event.is_set():
            incident_log.record_nowait(
                "initial_greeting_failed",
                severity="warning",
                component="voice_pipeline",
                description="Initial greeting did not complete by any playback path",
                payload={
                    "audio_path": str(initial_greeting_audio_path)
                    if initial_greeting_audio_path is not None
                    else None,
                    "text_len": len(initial_greeting or ""),
                    "timeout_sec": VOICE_SPEECH_PLAYOUT_TIMEOUT_SEC,
                },
            )
            await delete_room_safely(
                "initial_greeting_failed",
                close_reason="initial_greeting_failed",
            )
        elif runtime_warmup_task and not runtime_warmup_task.done():
            # Do not block call flow if warmup is still in progress.
            with suppress(Exception):
                await asyncio.wait_for(
                    asyncio.shield(runtime_warmup_task),
                    timeout=0.25,
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
        incident_log.record_nowait(
            "abnormal_close",
            severity="warning",
            component="livekit_entrypoint",
            error_type="CancelledError",
            description="LiveKit agent entrypoint was cancelled",
            payload={"close": dict(close_info)},
        )
        with suppress(BaseException):
            await stop_recording_safely(close_info["reason"] or "entrypoint_cancelled")
        with suppress(BaseException):
            await delete_room_safely(
                "entrypoint_cancelled",
                close_reason=close_info["reason"] or "entrypoint_cancelled",
            )
        await export_best_effort(timeout_sec=export_wait_sec)
        await ensure_session_closed(timeout_sec=1.0)
    except Exception as e:
        if not startup_failure_recorded:
            await incident_log.record_exception(
                "agent_session_error" if session_started else "session_start_failed",
                e,
                severity="error" if session_started else "critical",
                component="livekit_entrypoint",
                description=(
                    "LiveKit agent entrypoint failed"
                    if session_started
                    else "LiveKit agent failed before session start"
                ),
                payload={"session_started": session_started},
            )
        raise
    finally:
        if participant_disconnect_cleanup_handler is not None:
            with suppress(Exception):
                ctx.room.off(
                    "participant_disconnected",
                    participant_disconnect_cleanup_handler,
                )
        if end_call_task and not end_call_task.done():
            end_call_task.cancel()
        if reply_watchdog_task and not reply_watchdog_task.done():
            reply_watchdog_task.cancel()
        if startup_no_dialog_task and not startup_no_dialog_task.done():
            startup_no_dialog_task.cancel()
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
                incident_log.record_nowait(
                    "n8n_export_failed",
                    severity="warning",
                    component="n8n_export",
                    latency_ms=export_wait_sec * 1000,
                    error_type="TimeoutError",
                    description="n8n session export timed out in finalizer",
                    payload={"timeout_sec": export_wait_sec, "phase": "finalizer"},
                )
            except BaseException as e:
                logger.exception("n8n export finalizer failed: %s", e)
                incident_log.record_exception_nowait(
                    "n8n_export_failed",
                    e,
                    severity="warning",
                    component="n8n_export",
                    description="n8n export finalizer failed",
                    payload={"phase": "finalizer"},
                )
        await incident_log.drain(timeout_sec=1.0)
        reset_raw_call_log_sink(raw_log_token)
        await raw_log_sink.close(timeout_sec=3.0)


if __name__ == "__main__":
    cli.run_app(server)
