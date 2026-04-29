import os
from collections.abc import Iterator
from contextlib import contextmanager

_PROXY_ENV_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)

_NO_PROXY_DEFAULT = "127.0.0.1,localhost,::1"

_PROVIDER_DEFAULTS: dict[str, str] = {
    # Tested from Asterisk/local robot on 2026-04-28.
    "elevenlabs": "proxy",
    "gemini": "proxy",
    "google_llm": "proxy",
    "google_tts": "proxy",
    "vertex_tts": "proxy",
    "google_stt": "proxy",
    "yandex_stt": "direct",
    "tbank_stt": "direct",
    "tbank_tts": "direct",
    "xai": "direct",
    "deepgram": "direct",
    "minimax": "direct",
    "cosyvoice": "direct",
    "sber_tts": "direct",
    "livekit_inference": "proxy",
}

_PROVIDER_ENV_NAMES: dict[str, tuple[str, ...]] = {
    "elevenlabs": ("ELEVENLABS_EGRESS", "TTS_ELEVENLABS_EGRESS"),
    "gemini": ("GEMINI_EGRESS", "GOOGLE_LLM_EGRESS"),
    "google_llm": ("GOOGLE_LLM_EGRESS", "GEMINI_EGRESS"),
    "google_tts": ("GOOGLE_TTS_EGRESS",),
    "vertex_tts": ("VERTEX_TTS_EGRESS", "GOOGLE_TTS_EGRESS"),
    "google_stt": ("GOOGLE_STT_EGRESS", "STT_GOOGLE_EGRESS"),
    "yandex_stt": ("YANDEX_STT_EGRESS", "STT_YANDEX_EGRESS"),
    "tbank_stt": ("TBANK_STT_EGRESS", "STT_TBANK_EGRESS", "TBANK_VOICEKIT_EGRESS"),
    "tbank_tts": ("TBANK_TTS_EGRESS", "TTS_TBANK_EGRESS", "TBANK_VOICEKIT_EGRESS"),
    "xai": ("XAI_EGRESS",),
    "deepgram": ("DEEPGRAM_EGRESS", "STT_DEEPGRAM_EGRESS"),
    "minimax": ("MINIMAX_EGRESS", "MINIMAX_TTS_EGRESS"),
    "cosyvoice": ("COSYVOICE_EGRESS", "COSYVOICE_TTS_EGRESS"),
    "sber_tts": ("SBER_EGRESS", "SBER_TTS_EGRESS"),
    "livekit_inference": ("LIVEKIT_INFERENCE_EGRESS", "STT_INFERENCE_EGRESS"),
}


def _normalize_mode(raw: str | None, *, default: str = "direct") -> str:
    value = (raw or "").strip().lower()
    if value in {"proxy", "proxied", "vps", "squid", "http_connect"}:
        return "proxy"
    if value in {"direct", "none", "off", "no_proxy", "bypass"}:
        return "direct"
    return default


def egress_proxy_url() -> str:
    return (
        os.getenv("EGRESS_PROXY_URL")
        or os.getenv("AGENT_EXTERNAL_HTTP_PROXY")
        or os.getenv("HTTPS_PROXY")
        or ""
    ).strip()


def provider_egress(provider: str) -> str:
    normalized_provider = provider.strip().lower()
    default_mode = _normalize_mode(
        os.getenv("EGRESS_DEFAULT"),
        default=_PROVIDER_DEFAULTS.get(normalized_provider, "direct"),
    )

    for env_name in _PROVIDER_ENV_NAMES.get(
        normalized_provider,
        (f"{normalized_provider.upper()}_EGRESS",),
    ):
        if env_name in os.environ:
            return _normalize_mode(os.getenv(env_name), default=default_mode)

    return default_mode


def provider_proxy_url(provider: str) -> str | None:
    if provider_egress(provider) != "proxy":
        return None
    proxy_url = egress_proxy_url()
    return proxy_url or None


def aiohttp_proxy(provider: str) -> str | None:
    return provider_proxy_url(provider)


def httpx_client_args(provider: str) -> dict[str, object]:
    proxy_url = provider_proxy_url(provider)
    args: dict[str, object] = {"trust_env": False}
    if proxy_url:
        args["proxy"] = proxy_url
    return args


@contextmanager
def provider_egress_env(provider: str) -> Iterator[None]:
    old_values = {
        name: os.environ.get(name)
        for name in (*_PROXY_ENV_VARS, "NO_PROXY", "no_proxy")
    }

    for name in _PROXY_ENV_VARS:
        os.environ.pop(name, None)

    proxy_url = provider_proxy_url(provider)
    if proxy_url:
        os.environ["HTTP_PROXY"] = proxy_url
        os.environ["HTTPS_PROXY"] = proxy_url
        os.environ["ALL_PROXY"] = proxy_url
        os.environ.setdefault("NO_PROXY", _NO_PROXY_DEFAULT)
        os.environ.setdefault("no_proxy", _NO_PROXY_DEFAULT)
    else:
        os.environ["NO_PROXY"] = _NO_PROXY_DEFAULT
        os.environ["no_proxy"] = _NO_PROXY_DEFAULT

    try:
        yield
    finally:
        for name, value in old_values.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
