import os

from dotenv import load_dotenv

load_dotenv(".env.local")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "enable", "enabled"}


def _env_optional_bool(name: str) -> bool | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    return raw.strip().lower() in {"1", "true", "yes", "on", "enable", "enabled"}


def _env_optional_float(name: str) -> float | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    return float(raw)


def _env_optional_int(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    return int(raw)


LIVEKIT_URL = os.getenv("LIVEKIT_URL", "")
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY", "")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "")
AGENT_EXTERNAL_HTTP_PROXY = (
    os.getenv("AGENT_EXTERNAL_HTTP_PROXY") or os.getenv("HTTPS_PROXY") or ""
).strip()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
XAI_API_KEY = os.getenv("XAI_API_KEY", "")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")
YANDEX_SPEECHKIT_API_KEY = os.getenv("YANDEX_SPEECHKIT_API_KEY", "")
TBANK_VOICEKIT_API_KEY = os.getenv(
    "TBANK_VOICEKIT_API_KEY",
    os.getenv("VOICEKIT_API_KEY", ""),
)
TBANK_VOICEKIT_SECRET_KEY = os.getenv(
    "TBANK_VOICEKIT_SECRET_KEY",
    os.getenv("VOICEKIT_SECRET_KEY", ""),
)
TBANK_VOICEKIT_ENDPOINT = os.getenv("TBANK_VOICEKIT_ENDPOINT", "api.tinkoff.ai:443")
TBANK_VOICEKIT_AUTHORITY = os.getenv("TBANK_VOICEKIT_AUTHORITY", "").strip()


# LLM provider switch:
# - google (default, direct Gemini API)
# - xai (xAI Grok via livekit.plugins.xai.responses.LLM)
def _normalize_llm_provider(raw_provider: str) -> str:
    return {
        "google": "google",
        "gemini": "google",
        "xai": "xai",
        "grok": "xai",
    }.get(raw_provider.strip().lower(), raw_provider.strip().lower())


def _normalize_optional_llm_provider(raw_provider: str) -> str:
    normalized = raw_provider.strip().lower()
    if normalized in {"", "disabled", "disable", "off", "none", "false"}:
        return ""
    return _normalize_llm_provider(raw_provider)


_raw_llm_provider = os.getenv("LLM_PROVIDER", "google")
LLM_PROVIDER = _normalize_llm_provider(_raw_llm_provider)

# Optional rule-based routing providers.
# If both are set, routing is enabled:
# - FAST_LLM_PROVIDER: provider used for "fast" route
# - COMPLEX_LLM_PROVIDER: provider used for "complex" route
# If either is empty, routing stays disabled and LLM_PROVIDER is used as before.
FAST_LLM_PROVIDER = _normalize_optional_llm_provider(
    os.getenv("FAST_LLM_PROVIDER", "")
)
COMPLEX_LLM_PROVIDER = _normalize_optional_llm_provider(
    os.getenv("COMPLEX_LLM_PROVIDER", "")
)
LLM_ROUTING_ENABLED = bool(FAST_LLM_PROVIDER and COMPLEX_LLM_PROVIDER)
MODEL_ROUTER_FAST_MODEL = os.getenv("MODEL_ROUTER_FAST_MODEL", "").strip()
MODEL_ROUTER_COMPLEX_MODEL = os.getenv("MODEL_ROUTER_COMPLEX_MODEL", "").strip()

# TTS provider switch:
# - elevenlabs (default)
# - google (livekit.plugins.google.TTS)
# - vertex (google.genai Vertex API path)
# - minimax (official livekit.plugins.minimax TTS plugin)
# - cosyvoice (Alibaba Cloud Model Studio WebSocket API)
# - tbank (T-Bank VoiceKit gRPC streaming synthesis)
# - sber (Sber SaluteSpeech gRPC API)
_raw_tts_provider = os.getenv("TTS_PROVIDER", "elevenlabs").strip().lower()
TTS_PROVIDER = {
    "eleven": "elevenlabs",
    "elevenlab": "elevenlabs",
    "elevenlabs": "elevenlabs",
    "google": "google",
    "google_tts": "google",
    "vertex": "vertex",
    "google_vertex": "vertex",
    "google-vertex": "vertex",
    "minimax": "minimax",
    "mini_max": "minimax",
    "cosyvoice": "cosyvoice",
    "cosy_voice": "cosyvoice",
    "cosy-voice": "cosyvoice",
    "tbank": "tbank",
    "t-bank": "tbank",
    "tbank_voicekit": "tbank",
    "voicekit": "tbank",
    "sber": "sber",
    "salutespeech": "sber",
    "salute_speech": "sber",
    "sber_salutespeech": "sber",
}.get(_raw_tts_provider, _raw_tts_provider)
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "wF58OrxELqJ5nFJxXiva")
ELEVENLABS_MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_flash_v2_5")
# Legacy switch name retained for backward compatibility.
# true  -> use custom eleven_v3 HTTP streaming adapter
# false -> use official livekit.plugins.elevenlabs.TTS path
ELEVENLABS_V3_USE_STREAM_INPUT = _env_bool(
    "ELEVENLABS_V3_USE_STREAM_INPUT", default=True
)
ELEVENLABS_V3_OUTPUT_FORMAT = os.getenv("ELEVENLABS_V3_OUTPUT_FORMAT", "mp3_22050_32")
ELEVENLABS_V3_ENABLE_LOGGING = _env_bool("ELEVENLABS_V3_ENABLE_LOGGING", default=True)
ELEVENLABS_V3_APPLY_TEXT_NORMALIZATION = os.getenv(
    "ELEVENLABS_V3_APPLY_TEXT_NORMALIZATION",
    "auto",
).strip()
ELEVENLABS_V3_LANGUAGE = os.getenv("ELEVENLABS_V3_LANGUAGE", "").strip()
ELEVENLABS_V3_OPTIMIZE_STREAMING_LATENCY = _env_optional_int(
    "ELEVENLABS_V3_OPTIMIZE_STREAMING_LATENCY"
)
ELEVENLABS_V3_REQUEST_TIMEOUT_SEC = float(
    os.getenv("ELEVENLABS_V3_REQUEST_TIMEOUT_SEC", "30.0")
)
ELEVENLABS_V3_MIN_SENTENCE_LEN = int(os.getenv("ELEVENLABS_V3_MIN_SENTENCE_LEN", "6"))
ELEVENLABS_V3_STREAM_CONTEXT_LEN = int(
    os.getenv("ELEVENLABS_V3_STREAM_CONTEXT_LEN", "2")
)
ELEVENLABS_V3_MIN_HTTP_TEXT_LEN = int(
    os.getenv("ELEVENLABS_V3_MIN_HTTP_TEXT_LEN", "18")
)
ELEVENLABS_V3_MERGE_HOLD_MS = int(os.getenv("ELEVENLABS_V3_MERGE_HOLD_MS", "140"))
ELEVENLABS_V3_MAX_MERGED_TEXT_LEN = int(
    os.getenv("ELEVENLABS_V3_MAX_MERGED_TEXT_LEN", "80")
)

# Optional ElevenLabs voice settings.
# Note: stability + similarity_boost must be set together for VoiceSettings.
ELEVENLABS_VOICE_STABILITY = _env_optional_float("ELEVENLABS_VOICE_STABILITY")
ELEVENLABS_VOICE_SIMILARITY_BOOST = _env_optional_float(
    "ELEVENLABS_VOICE_SIMILARITY_BOOST"
)
ELEVENLABS_VOICE_STYLE = _env_optional_float("ELEVENLABS_VOICE_STYLE")
ELEVENLABS_VOICE_SPEED = _env_optional_float("ELEVENLABS_VOICE_SPEED")
ELEVENLABS_VOICE_USE_SPEAKER_BOOST = _env_optional_bool(
    "ELEVENLABS_VOICE_USE_SPEAKER_BOOST"
)

# T-Bank VoiceKit TTS runtime settings.
TTS_TBANK_VOICE_NAME = os.getenv("TTS_TBANK_VOICE_NAME", "anna")
TTS_TBANK_PITCH = float(os.getenv("TTS_TBANK_PITCH", "0.8"))
TTS_TBANK_SPEAKING_RATE = float(os.getenv("TTS_TBANK_SPEAKING_RATE", "1.0"))
TTS_TBANK_FORMAT = os.getenv("TTS_TBANK_FORMAT", "linear16")
TTS_TBANK_SAMPLE_RATE = int(os.getenv("TTS_TBANK_SAMPLE_RATE", "24000"))
TTS_TBANK_MIN_SENTENCE_LEN = int(os.getenv("TTS_TBANK_MIN_SENTENCE_LEN", "4"))
TTS_TBANK_STREAM_CONTEXT_LEN = int(os.getenv("TTS_TBANK_STREAM_CONTEXT_LEN", "1"))

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3-flash")
GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "")
GEMINI_TEMPERATURE = float(os.getenv("GEMINI_TEMPERATURE", "0.7"))
GEMINI_MAX_OUTPUT_TOKENS = int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "512"))
GEMINI_TOP_P = float(os.getenv("GEMINI_TOP_P", "1"))
GEMINI_THINKING_LEVEL = os.getenv("GEMINI_THINKING_LEVEL", "minimal")
GEMINI_HTTP_TIMEOUT_SEC = float(os.getenv("GEMINI_HTTP_TIMEOUT_SEC", "10.0"))

# xAI Grok (Responses API)
XAI_MODEL = os.getenv("XAI_MODEL", "grok-4-1-fast-non-reasoning-latest")
XAI_TEMPERATURE = float(os.getenv("XAI_TEMPERATURE", "0.3"))
XAI_BASE_URL = os.getenv("XAI_BASE_URL", "").strip()
# xAI Responses API is more stable/fast for plain chat without function tools in this project.
# Keep tools off by default even if the agent defines them.
XAI_ENABLE_TOOLS = _env_bool("XAI_ENABLE_TOOLS", default=False)

# LLM fallback settings.
# Default to the local manual first-token timeout path. In telephony this is more
# predictable than LiveKit FallbackAdapter, which can wait on provider/client
# timeouts before emitting availability changes.
USE_LIVEKIT_FALLBACK_ADAPTER = _env_bool(
    "USE_LIVEKIT_FALLBACK_ADAPTER",
    default=False,
)
LLM_ATTEMPT_TIMEOUT_SEC = float(os.getenv("LLM_ATTEMPT_TIMEOUT_SEC", "2.5"))
LLM_MAX_RETRY_PER_LLM = int(os.getenv("LLM_MAX_RETRY_PER_LLM", "0"))
LLM_RETRY_INTERVAL_SEC = float(
    os.getenv(
        "LLM_RETRY_INTERVAL_SEC",
        os.getenv("LLM_RETRY_DELAY_SEC", "0.3"),
    )
)
LLM_RETRY_ON_CHUNK_SENT = _env_bool("LLM_RETRY_ON_CHUNK_SENT", default=False)

# Branch-local backup model config. Defaults use the existing Gemini fallback
# model so current deployments can opt into fallback without inventing IDs.
FAST_LLM_BACKUP_PROVIDER = _normalize_llm_provider(
    os.getenv(
        "FAST_LLM_BACKUP_PROVIDER",
        "google" if GEMINI_FALLBACK_MODEL.strip() else "",
    )
)
FAST_LLM_BACKUP_MODEL = os.getenv(
    "FAST_LLM_BACKUP_MODEL",
    GEMINI_FALLBACK_MODEL,
).strip()
COMPLEX_LLM_BACKUP_PROVIDER = _normalize_llm_provider(
    os.getenv(
        "COMPLEX_LLM_BACKUP_PROVIDER",
        "google" if GEMINI_FALLBACK_MODEL.strip() else "",
    )
)
COMPLEX_LLM_BACKUP_MODEL = os.getenv(
    "COMPLEX_LLM_BACKUP_MODEL",
    GEMINI_FALLBACK_MODEL,
).strip()

# Legacy variables kept so old env files still start. The LiveKit fallback
# adapter path uses LLM_ATTEMPT_TIMEOUT_SEC / LLM_RETRY_INTERVAL_SEC instead.
LLM_FIRST_TOKEN_TIMEOUT_SEC = float(
    os.getenv("LLM_FIRST_TOKEN_TIMEOUT_SEC", str(LLM_ATTEMPT_TIMEOUT_SEC))
)
LLM_FALLBACK_FIRST_TOKEN_TIMEOUT_SEC = float(
    os.getenv("LLM_FALLBACK_FIRST_TOKEN_TIMEOUT_SEC", str(LLM_ATTEMPT_TIMEOUT_SEC))
)
LLM_RETRY_DELAY_SEC = float(
    os.getenv("LLM_RETRY_DELAY_SEC", str(LLM_RETRY_INTERVAL_SEC))
)

# Prerecorded voice prompts. Relative paths resolve under agents/main-bot/audio.
# Legacy VOICE_FILLER_* names remain as fallback env keys for existing deploys.
_legacy_voice_filler_audio_path = os.getenv("VOICE_FILLER_AUDIO_PATH", "").strip()
_legacy_voice_filler_phrase = os.getenv("VOICE_FILLER_PHRASE", "").strip()
VOICE_RESPONSE_DELAY_AUDIO_PATH = os.getenv(
    "VOICE_RESPONSE_DELAY_AUDIO_PATH",
    _legacy_voice_filler_audio_path or "response_delay.wav",
).strip() or "response_delay.wav"
VOICE_RESPONSE_DELAY_AUDIO_PATHS = os.getenv(
    "VOICE_RESPONSE_DELAY_AUDIO_PATHS",
    (
        "response_delay_khmmm.wav"
        + ",response_delay_emm.wav"
        + ",response_delay_nuuu.wav"
        + ",response_delay_khe_khe.wav"
    ),
).strip()
VOICE_RESPONSE_DELAY_PHRASE = os.getenv(
    "VOICE_RESPONSE_DELAY_PHRASE",
    _legacy_voice_filler_phrase or "Секундочку.",
).strip() or "Секундочку."
VOICE_RESPONSE_DELAY_SEC = float(os.getenv("VOICE_RESPONSE_DELAY_SEC", "3.0"))
VOICE_RESPONSE_DELAY_POST_GAP_SEC = float(
    os.getenv("VOICE_RESPONSE_DELAY_POST_GAP_SEC", "0.0")
)
VOICE_CLIENT_SILENCE_AUDIO_PATH = os.getenv(
    "VOICE_CLIENT_SILENCE_AUDIO_PATH",
    "client_silence.wav",
).strip() or "client_silence.wav"
VOICE_CLIENT_SILENCE_PHRASE = os.getenv(
    "VOICE_CLIENT_SILENCE_PHRASE",
    "Алло.",
).strip() or "Алло."
VOICE_CLIENT_SILENCE_SEC = float(os.getenv("VOICE_CLIENT_SILENCE_SEC", "8.0"))
VOICE_EMERGENCY_AUDIO_PATH = os.getenv(
    "VOICE_EMERGENCY_AUDIO_PATH",
    "emergency.wav",
).strip() or "emergency.wav"
VOICE_EMERGENCY_PHRASE = os.getenv(
    "VOICE_EMERGENCY_PHRASE",
    "Извините, перезвоните ещё раз.",
).strip() or "Извините, перезвоните ещё раз."
VOICE_FILLER_AUDIO_PATH = VOICE_RESPONSE_DELAY_AUDIO_PATH
VOICE_FILLER_PHRASE = VOICE_RESPONSE_DELAY_PHRASE

# Turn endpointing tuning (seconds). Lower values = faster replies.
TURN_MIN_ENDPOINTING_DELAY = float(os.getenv("TURN_MIN_ENDPOINTING_DELAY", "0.25"))
TURN_MAX_ENDPOINTING_DELAY = float(os.getenv("TURN_MAX_ENDPOINTING_DELAY", "1.0"))
# Turn handling stability/latency knobs.
# TURN_DETECTION_MODE: "vad" (Silero VAD, recommended), "stt" (STT-based), or "multilingual" (EOU model)
# Use "vad" with Google STT — "stt" requires enable_voice_activity_events which breaks multi-turn
# sessions with the latest_short model. "multilingual" requires PyTorch.
TURN_DETECTION_MODE = os.getenv("TURN_DETECTION_MODE", "vad").strip().lower()
# Endpointing mode: "fixed" or "dynamic"
TURN_ENDPOINTING_MODE = os.getenv("TURN_ENDPOINTING_MODE", "dynamic").strip().lower()
# Preemptive generation can reduce latency, but may cause occasional stalled turns
# depending on provider/turn-detector combination.
PREEMPTIVE_GENERATION = _env_bool("PREEMPTIVE_GENERATION", default=True)
# If no assistant reply appears after a final user turn, force one extra reply attempt.
# Set to 0 to disable.
REPLY_WATCHDOG_SEC = float(os.getenv("REPLY_WATCHDOG_SEC", "9.0"))
# When enabled, a provider-agnostic STT wrapper turns the latest interim
# transcript into a synthetic final transcript if finalization lags after EOS.
STT_EARLY_INTERIM_FINAL_ENABLED = _env_bool(
    "STT_EARLY_INTERIM_FINAL_ENABLED",
    default=False,
)
STT_EARLY_INTERIM_FINAL_DELAY_SEC = float(
    os.getenv("STT_EARLY_INTERIM_FINAL_DELAY_SEC", "0.03")
)
STT_EARLY_INTERIM_FINAL_MIN_STABLE_INTERIMS = int(
    os.getenv("STT_EARLY_INTERIM_FINAL_MIN_STABLE_INTERIMS", "2")
)

# Google TTS runtime settings.
# Google Cloud model formats example: gemini-3.1-flash-tts-preview, gemini-2.5-flash-tts
GOOGLE_TTS_MODEL = os.getenv("GOOGLE_TTS_MODEL", "gemini-3.1-flash-tts-preview")
GOOGLE_TTS_FALLBACK_MODEL = os.getenv(
    "GOOGLE_TTS_FALLBACK_MODEL",
    "gemini-2.5-flash-tts",
)
GOOGLE_TTS_LANGUAGE = os.getenv("GOOGLE_TTS_LANGUAGE", "ru-RU")
GOOGLE_TTS_VOICE_NAME = os.getenv("GOOGLE_TTS_VOICE_NAME", "Zephyr")
GOOGLE_TTS_SPEAKING_RATE = float(os.getenv("GOOGLE_TTS_SPEAKING_RATE", "1.0"))
GOOGLE_TTS_PITCH = int(os.getenv("GOOGLE_TTS_PITCH", "0"))
GOOGLE_TTS_CREDENTIALS_FILE = os.getenv("GOOGLE_TTS_CREDENTIALS_FILE", "")
# Optional alternatives for cloud deployments where local files are unavailable:
# - GOOGLE_TTS_CREDENTIALS_JSON: raw service account JSON
# - GOOGLE_TTS_CREDENTIALS_B64: base64-encoded service account JSON
GOOGLE_TTS_CREDENTIALS_JSON = os.getenv("GOOGLE_TTS_CREDENTIALS_JSON", "")
GOOGLE_TTS_CREDENTIALS_B64 = os.getenv("GOOGLE_TTS_CREDENTIALS_B64", "")
GOOGLE_TTS_LOCATION = os.getenv("GOOGLE_TTS_LOCATION", "us-central1")
GOOGLE_TTS_USE_STREAMING = _env_bool(
    "GOOGLE_TTS_USE_STREAMING",
    default=True,
)
GOOGLE_TTS_MIN_SENTENCE_LEN = int(os.getenv("GOOGLE_TTS_MIN_SENTENCE_LEN", "4"))
GOOGLE_TTS_STREAM_CONTEXT_LEN = int(os.getenv("GOOGLE_TTS_STREAM_CONTEXT_LEN", "1"))
# Vertex Gemini TTS buffering is configured separately from Google Cloud TTS
# because Vertex path uses per-segment generate_content_stream calls.
VERTEX_TTS_MIN_SENTENCE_LEN = int(os.getenv("VERTEX_TTS_MIN_SENTENCE_LEN", "6"))
VERTEX_TTS_STREAM_CONTEXT_LEN = int(os.getenv("VERTEX_TTS_STREAM_CONTEXT_LEN", "2"))
GOOGLE_TTS_PROMPT = os.getenv(
    "GOOGLE_TTS_PROMPT",
    "Speak only in Russian. "
    "Use pure standard Russian pronunciation with no foreign accent. "
    "Sound like a real human receptionist speaking on the phone. "
    "Be natural, calm, polite, and professional. "
    "Use short, clear, conversational sentences. "
    "Keep a medium pace and clear articulation. "
    "Use subtle human-like intonation variation. "
    "Avoid sounding robotic, theatrical, salesy, or overly cheerful.",
)

# MiniMax TTS runtime settings.
# Docs: https://platform.minimax.io/docs/api-reference/speech-t2a-http
MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
MINIMAX_TTS_MODEL = os.getenv("MINIMAX_TTS_MODEL", "speech-2.8-turbo")
MINIMAX_TTS_VOICE_ID = os.getenv(
    "MINIMAX_TTS_VOICE_ID",
    "moss_audio_43d3c43e-3a2d-11f1-b47e-928b88df9451",
)
MINIMAX_TTS_BASE_URL = os.getenv("MINIMAX_TTS_BASE_URL", "https://api-uw.minimax.io")
MINIMAX_TTS_LANGUAGE_BOOST = os.getenv("MINIMAX_TTS_LANGUAGE_BOOST", "Russian")
MINIMAX_TTS_SPEED = float(os.getenv("MINIMAX_TTS_SPEED", "1.0"))
MINIMAX_TTS_VOLUME = float(os.getenv("MINIMAX_TTS_VOLUME", "1.0"))
MINIMAX_TTS_PITCH = int(os.getenv("MINIMAX_TTS_PITCH", "0"))
_raw_minimax_tts_intensity = os.getenv("MINIMAX_TTS_INTENSITY", "").strip()
MINIMAX_TTS_INTENSITY = (
    int(_raw_minimax_tts_intensity) if _raw_minimax_tts_intensity else None
)
_raw_minimax_tts_timbre = os.getenv("MINIMAX_TTS_TIMBRE", "").strip()
MINIMAX_TTS_TIMBRE = int(_raw_minimax_tts_timbre) if _raw_minimax_tts_timbre else None
MINIMAX_TTS_SOUND_EFFECTS = os.getenv("MINIMAX_TTS_SOUND_EFFECTS", "").strip()
MINIMAX_TTS_FORMAT = os.getenv("MINIMAX_TTS_FORMAT", "mp3")
MINIMAX_TTS_SAMPLE_RATE = int(os.getenv("MINIMAX_TTS_SAMPLE_RATE", "24000"))
MINIMAX_TTS_BITRATE = int(os.getenv("MINIMAX_TTS_BITRATE", "128000"))
MINIMAX_TTS_CHANNEL = int(os.getenv("MINIMAX_TTS_CHANNEL", "1"))
MINIMAX_TTS_MIN_SENTENCE_LEN = int(os.getenv("MINIMAX_TTS_MIN_SENTENCE_LEN", "4"))
MINIMAX_TTS_STREAM_CONTEXT_LEN = int(os.getenv("MINIMAX_TTS_STREAM_CONTEXT_LEN", "1"))

# Sber SaluteSpeech TTS runtime settings.
# SBER_SALUTESPEECH_AUTH_KEY is the Authorization key from Sber, without secrets in code.
SBER_SALUTESPEECH_AUTH_KEY = os.getenv(
    "SBER_SALUTESPEECH_AUTH_KEY",
    os.getenv("SBER_AUTH_KEY", ""),
)
SBER_TTS_OAUTH_SCOPE = os.getenv("SBER_TTS_OAUTH_SCOPE", "SALUTE_SPEECH_PERS")
SBER_TTS_OAUTH_URL = os.getenv(
    "SBER_TTS_OAUTH_URL",
    "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
)
SBER_TTS_ENDPOINT = os.getenv("SBER_TTS_ENDPOINT", "smartspeech.sber.ru:443")
SBER_TTS_CA_CERT_FILE = os.getenv("SBER_TTS_CA_CERT_FILE", "").strip()
SBER_TTS_VOICE = os.getenv("SBER_TTS_VOICE", "Ost_24000")
SBER_TTS_LANGUAGE = os.getenv("SBER_TTS_LANGUAGE", "ru-RU")
SBER_TTS_SAMPLE_RATE = int(os.getenv("SBER_TTS_SAMPLE_RATE", "24000"))
SBER_TTS_PAINT_PITCH = os.getenv("SBER_TTS_PAINT_PITCH", "2")
SBER_TTS_PAINT_SPEED = os.getenv("SBER_TTS_PAINT_SPEED", "4")
SBER_TTS_PAINT_LOUDNESS = os.getenv("SBER_TTS_PAINT_LOUDNESS", "5")
SBER_TTS_REQUEST_TIMEOUT_SEC = float(
    os.getenv("SBER_TTS_REQUEST_TIMEOUT_SEC", "15.0")
)
SBER_TTS_REBUILD_CACHE = _env_bool("SBER_TTS_REBUILD_CACHE", default=False)
SBER_TTS_MIN_SENTENCE_LEN = int(os.getenv("SBER_TTS_MIN_SENTENCE_LEN", "4"))
SBER_TTS_STREAM_CONTEXT_LEN = int(os.getenv("SBER_TTS_STREAM_CONTEXT_LEN", "1"))

# CosyVoice (Alibaba DashScope / Model Studio) runtime settings.
_raw_cosyvoice_profile = (
    os.getenv(
        "COSYVOICE_PROFILE",
        "cosyvoice_cn_flash_fast",
    )
    .strip()
    .lower()
)
COSYVOICE_PROFILE = {
    "flash": "cosyvoice_cn_flash_fast",
    "plus": "cosyvoice_cn_plus_quality",
    "cosyvoice_cn_flash_fast": "cosyvoice_cn_flash_fast",
    "cosyvoice_cn_plus_quality": "cosyvoice_cn_plus_quality",
}.get(_raw_cosyvoice_profile, _raw_cosyvoice_profile)

_COSYVOICE_PROFILE_DEFAULTS = {
    "cosyvoice_cn_flash_fast": {
        "model": "cosyvoice-v3.5-flash",
        "transport": "websocket",
        "format": "pcm",
        "sample_rate": "24000",
        "region": "cn-beijing",
        "voice_mode": "preset",
        "connection_reuse": "true",
        "playback_on_first_chunk": "true",
        "min_sentence_len": "4",
        "stream_context_len": "1",
    },
    "cosyvoice_cn_plus_quality": {
        "model": "cosyvoice-v3.5-plus",
        "transport": "websocket",
        "format": "pcm",
        "sample_rate": "24000",
        "region": "cn-beijing",
        "voice_mode": "preset",
        "connection_reuse": "true",
        "playback_on_first_chunk": "true",
        "min_sentence_len": "6",
        "stream_context_len": "2",
    },
}

_cosyvoice_defaults = _COSYVOICE_PROFILE_DEFAULTS.get(
    COSYVOICE_PROFILE,
    _COSYVOICE_PROFILE_DEFAULTS["cosyvoice_cn_flash_fast"],
)

COSYVOICE_API_KEY_ENV_NAME = os.getenv(
    "COSYVOICE_API_KEY_ENV_NAME",
    "COSYVOICE_API_KEY",
).strip()
COSYVOICE_API_KEY = os.getenv(
    COSYVOICE_API_KEY_ENV_NAME or "COSYVOICE_API_KEY",
    os.getenv("COSYVOICE_API_KEY", ""),
)
COSYVOICE_TTS_MODEL = os.getenv("COSYVOICE_TTS_MODEL", _cosyvoice_defaults["model"])
COSYVOICE_TTS_TRANSPORT = (
    os.getenv(
        "COSYVOICE_TTS_TRANSPORT",
        _cosyvoice_defaults["transport"],
    )
    .strip()
    .lower()
)
COSYVOICE_TTS_REGION = os.getenv("COSYVOICE_TTS_REGION", _cosyvoice_defaults["region"])
COSYVOICE_TTS_WS_URL = os.getenv("COSYVOICE_TTS_WS_URL", "")
COSYVOICE_TTS_VOICE_MODE = (
    os.getenv(
        "COSYVOICE_TTS_VOICE_MODE",
        _cosyvoice_defaults["voice_mode"],
    )
    .strip()
    .lower()
)
COSYVOICE_TTS_VOICE_ID = os.getenv("COSYVOICE_TTS_VOICE_ID", "")
COSYVOICE_TTS_CLONE_VOICE_ID = os.getenv("COSYVOICE_TTS_CLONE_VOICE_ID", "")
COSYVOICE_TTS_DESIGN_VOICE_ID = os.getenv("COSYVOICE_TTS_DESIGN_VOICE_ID", "")
COSYVOICE_TTS_FORMAT = os.getenv("COSYVOICE_TTS_FORMAT", _cosyvoice_defaults["format"])
COSYVOICE_TTS_SAMPLE_RATE = int(
    os.getenv("COSYVOICE_TTS_SAMPLE_RATE", _cosyvoice_defaults["sample_rate"])
)
COSYVOICE_TTS_RATE = float(os.getenv("COSYVOICE_TTS_RATE", "1.0"))
COSYVOICE_TTS_PITCH = float(os.getenv("COSYVOICE_TTS_PITCH", "1.0"))
COSYVOICE_TTS_VOLUME = int(os.getenv("COSYVOICE_TTS_VOLUME", "50"))
COSYVOICE_TTS_CONNECTION_REUSE = _env_bool(
    "COSYVOICE_TTS_CONNECTION_REUSE",
    default=_cosyvoice_defaults["connection_reuse"] == "true",
)
COSYVOICE_TTS_PLAYBACK_ON_FIRST_CHUNK = _env_bool(
    "COSYVOICE_TTS_PLAYBACK_ON_FIRST_CHUNK",
    default=_cosyvoice_defaults["playback_on_first_chunk"] == "true",
)
COSYVOICE_TTS_MIN_SENTENCE_LEN = int(
    os.getenv("COSYVOICE_TTS_MIN_SENTENCE_LEN", _cosyvoice_defaults["min_sentence_len"])
)
COSYVOICE_TTS_STREAM_CONTEXT_LEN = int(
    os.getenv(
        "COSYVOICE_TTS_STREAM_CONTEXT_LEN",
        _cosyvoice_defaults["stream_context_len"],
    )
)

# STT provider switch:
# - deepgram (Deepgram plugin, requires DEEPGRAM_API_KEY)
# - inference (LiveKit Agent Gateway)
# - google (Google Cloud STT plugin, uses ADC/service-account credentials)
# - yandex (Yandex SpeechKit v3 direct gRPC, requires YANDEX_SPEECHKIT_API_KEY)
# - tbank (T-Bank VoiceKit gRPC StreamingRecognize)
_raw_stt_provider = os.getenv("STT_PROVIDER", "deepgram").strip().lower()
STT_PROVIDER = {
    "deepgram": "deepgram",
    "inference": "inference",
    "livekit": "inference",
    "livekit_inference": "inference",
    "google": "google",
    "google_cloud": "google",
    "yandex": "yandex",
    "yandex_cloud": "yandex",
    "speechkit": "yandex",
    "tbank": "tbank",
    "t-bank": "tbank",
    "tbank_voicekit": "tbank",
    "voicekit": "tbank",
}.get(_raw_stt_provider, _raw_stt_provider)

# Inference STT settings.
STT_INFERENCE_MODEL = os.getenv("STT_INFERENCE_MODEL", "deepgram/nova-3")
STT_INFERENCE_FALLBACK_MODEL = os.getenv("STT_INFERENCE_FALLBACK_MODEL", "")
STT_INFERENCE_LANGUAGE = os.getenv("STT_INFERENCE_LANGUAGE", "ru")
STT_INFERENCE_INCLUDE_GOOGLE_FALLBACK = _env_bool(
    "STT_INFERENCE_INCLUDE_GOOGLE_FALLBACK",
    default=True,
)

# Deepgram STT settings.
STT_DEEPGRAM_MODEL = os.getenv("STT_DEEPGRAM_MODEL", "nova-3")
STT_DEEPGRAM_LANGUAGE = os.getenv("STT_DEEPGRAM_LANGUAGE", "ru")
# How long Deepgram waits after silence before finalizing an utterance (ms).
# 25ms is Deepgram's minimum and gives the fastest end-of-turn signal.
STT_DEEPGRAM_ENDPOINTING_MS = int(os.getenv("STT_DEEPGRAM_ENDPOINTING_MS", "25"))

# Google STT settings.
STT_GOOGLE_MODEL = os.getenv("STT_GOOGLE_MODEL", "latest_long")
STT_GOOGLE_LANGUAGE = os.getenv("STT_GOOGLE_LANGUAGE", "ru-RU")
STT_GOOGLE_LOCATION = os.getenv("STT_GOOGLE_LOCATION", "global")

# Yandex SpeechKit STT settings.
STT_YANDEX_MODEL = os.getenv("STT_YANDEX_MODEL", "general")
STT_YANDEX_LANGUAGE = os.getenv("STT_YANDEX_LANGUAGE", "ru-RU")
STT_YANDEX_SAMPLE_RATE = int(os.getenv("STT_YANDEX_SAMPLE_RATE", "16000"))
STT_YANDEX_CHUNK_MS = int(os.getenv("STT_YANDEX_CHUNK_MS", "50"))
STT_YANDEX_EOU_SENSITIVITY = os.getenv(
    "STT_YANDEX_EOU_SENSITIVITY",
    "high",
).strip()
STT_YANDEX_MAX_PAUSE_BETWEEN_WORDS_HINT_MS = int(
    os.getenv("STT_YANDEX_MAX_PAUSE_BETWEEN_WORDS_HINT_MS", "500")
)

# T-Bank VoiceKit STT settings.
STT_TBANK_MODEL = os.getenv("STT_TBANK_MODEL", "")
STT_TBANK_LANGUAGE = os.getenv("STT_TBANK_LANGUAGE", "ru-RU")
STT_TBANK_SAMPLE_RATE = int(os.getenv("STT_TBANK_SAMPLE_RATE", "16000"))
STT_TBANK_CHUNK_MS = int(os.getenv("STT_TBANK_CHUNK_MS", "50"))
STT_TBANK_INTERIM_INTERVAL_SEC = float(
    os.getenv("STT_TBANK_INTERIM_INTERVAL_SEC", "0.1")
)

POSTGRES_DSN = os.getenv("POSTGRES_DSN", "")
PROMPT_LOOKUP_SQL = os.getenv("PROMPT_LOOKUP_SQL", "").strip()
PROMPT_LOOKUP_TIMEOUT_SEC = float(os.getenv("PROMPT_LOOKUP_TIMEOUT_SEC", "2.0"))

# Directus prompt lookup. The LiveKit agent uses a read-only Directus token
# instead of connecting to Postgres directly.
DIRECTUS_URL = os.getenv("DIRECTUS_URL", "").strip().rstrip("/")
DIRECTUS_TOKEN = os.getenv("DIRECTUS_TOKEN", "").strip()
DIRECTUS_REQUEST_TIMEOUT_SEC = float(os.getenv("DIRECTUS_REQUEST_TIMEOUT_SEC", "2.0"))
DIRECTUS_PROMPT_CACHE_TTL_SEC = float(
    os.getenv("DIRECTUS_PROMPT_CACHE_TTL_SEC", "300")
)
DIRECTUS_DEFAULT_TIMEZONE = os.getenv(
    "DIRECTUS_DEFAULT_TIMEZONE",
    "Europe/Kaliningrad",
).strip()
DIRECTUS_COLLECTION_CALLER_ID = os.getenv(
    "DIRECTUS_COLLECTION_CALLER_ID",
    "CallerID",
).strip()
DIRECTUS_COLLECTION_BOT_CONFIGURATIONS = os.getenv(
    "DIRECTUS_COLLECTION_BOT_CONFIGURATIONS",
    "bot_configurations",
).strip()
DIRECTUS_COLLECTION_CLIENTS = os.getenv(
    "DIRECTUS_COLLECTION_CLIENTS",
    "clients",
).strip()
DIRECTUS_COLLECTION_CLIENTS_PROMPT = os.getenv(
    "DIRECTUS_COLLECTION_CLIENTS_PROMPT",
    "clients_prompt",
).strip()
DIRECTUS_COLLECTION_WEBPARSING = os.getenv(
    "DIRECTUS_COLLECTION_WEBPARSING",
    "webparsing",
).strip()
DIRECTUS_COLLECTION_TRANSFER_NUMBER = os.getenv(
    "DIRECTUS_COLLECTION_TRANSFER_NUMBER",
    "transfer_number",
).strip()
DIRECTUS_COLLECTION_CLIENT_PROMPT_CACHE = os.getenv(
    "DIRECTUS_COLLECTION_CLIENT_PROMPT_CACHE",
    "client_prompt_cache",
).strip()
AGENT_NAME = os.getenv("AGENT_NAME", "main-bot")
LIVEKIT_SELF_HOSTED = _env_bool("LIVEKIT_SELF_HOSTED", default=False)
AGENT_HEALTH_HOST = os.getenv(
    "AGENT_HEALTH_HOST",
    "127.0.0.1" if LIVEKIT_SELF_HOSTED else "",
)
AGENT_HEALTH_PORT = int(
    os.getenv("AGENT_HEALTH_PORT", "18081" if LIVEKIT_SELF_HOSTED else "8081")
)
AGENT_MAX_CONCURRENT_JOBS = max(
    1,
    int(os.getenv("AGENT_MAX_CONCURRENT_JOBS", "10")),
)
AGENT_NUM_IDLE_PROCESSES = int(
    os.getenv("AGENT_NUM_IDLE_PROCESSES", "1" if LIVEKIT_SELF_HOSTED else "10")
)
AUDIO_INPUT_ENHANCEMENT = os.getenv(
    "AUDIO_INPUT_ENHANCEMENT",
    "none" if LIVEKIT_SELF_HOSTED else "livekit",
).strip().lower()

N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL", "")
N8N_WEBHOOK_TOKEN = os.getenv("N8N_WEBHOOK_TOKEN", "")

SMS_RU_API_URL = os.getenv("SMS_RU_API_URL", "https://sms.ru/sms/send")
SMS_RU_API_ID = os.getenv("SMS_RU_API_ID", "")
SMS_LINK_SIGNATURE = os.getenv(
    "SMS_LINK_SIGNATURE",
    "Отправил наш ИИ робот: jcall.io",
)
