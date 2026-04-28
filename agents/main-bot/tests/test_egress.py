import os

from egress import (
    httpx_client_args,
    provider_egress,
    provider_egress_env,
    provider_proxy_url,
)


def test_provider_defaults_match_latency_policy(monkeypatch) -> None:
    monkeypatch.delenv("EGRESS_DEFAULT", raising=False)
    monkeypatch.delenv("ELEVENLABS_EGRESS", raising=False)
    monkeypatch.delenv("GEMINI_EGRESS", raising=False)
    monkeypatch.delenv("XAI_EGRESS", raising=False)
    monkeypatch.delenv("DEEPGRAM_EGRESS", raising=False)

    assert provider_egress("elevenlabs") == "proxy"
    assert provider_egress("gemini") == "proxy"
    assert provider_egress("xai") == "direct"
    assert provider_egress("deepgram") == "direct"
    assert provider_egress("livekit_inference") == "proxy"


def test_provider_override_and_proxy_url(monkeypatch) -> None:
    monkeypatch.setenv("EGRESS_PROXY_URL", "http://proxy.example:15182")
    monkeypatch.setenv("XAI_EGRESS", "proxy")

    assert provider_egress("xai") == "proxy"
    assert provider_proxy_url("xai") == "http://proxy.example:15182"
    assert httpx_client_args("xai") == {
        "trust_env": False,
        "proxy": "http://proxy.example:15182",
    }


def test_direct_mode_ignores_global_proxy_env(monkeypatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://old-proxy:15001")
    monkeypatch.setenv("DEEPGRAM_EGRESS", "direct")

    assert provider_proxy_url("deepgram") is None
    assert httpx_client_args("deepgram") == {"trust_env": False}


def test_provider_egress_env_restores_environment(monkeypatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://old-proxy:15001")
    monkeypatch.setenv("EGRESS_PROXY_URL", "http://new-proxy:15182")
    monkeypatch.setenv("GEMINI_EGRESS", "proxy")

    with provider_egress_env("gemini"):
        assert os.environ["HTTPS_PROXY"] == "http://new-proxy:15182"
        assert os.environ["HTTP_PROXY"] == "http://new-proxy:15182"

    assert os.environ["HTTPS_PROXY"] == "http://old-proxy:15001"
