import pytest
from livekit.plugins import google

import agent


def test_build_google_llm_requires_api_key(monkeypatch) -> None:
    monkeypatch.setattr(agent, "GOOGLE_API_KEY", "")

    with pytest.raises(RuntimeError, match="GOOGLE_API_KEY is not set"):
        agent.build_google_llm()


def test_build_google_llm_uses_config(monkeypatch) -> None:
    monkeypatch.setattr(agent, "GOOGLE_API_KEY", "test-key")
    monkeypatch.setattr(agent, "GEMINI_MODEL", "gemini-3-flash")
    monkeypatch.setattr(agent, "GEMINI_TEMPERATURE", 0.7)
    monkeypatch.setattr(agent, "GEMINI_MAX_OUTPUT_TOKENS", 512)
    monkeypatch.setattr(agent, "GEMINI_TOP_P", 1.0)
    monkeypatch.setattr(agent, "GEMINI_THINKING_LEVEL", "minimal")

    llm = agent.build_google_llm()

    assert isinstance(llm, google.LLM)
    assert llm.model == "gemini-3-flash"


def test_build_google_llm_applies_egress_to_genai_client(monkeypatch) -> None:
    monkeypatch.setattr(agent, "GOOGLE_API_KEY", "test-key")
    monkeypatch.setattr(agent, "GEMINI_MODEL", "gemini-3-flash")
    monkeypatch.setattr(agent, "GEMINI_TEMPERATURE", 0.7)
    monkeypatch.setattr(agent, "GEMINI_MAX_OUTPUT_TOKENS", 512)
    monkeypatch.setattr(agent, "GEMINI_TOP_P", 1.0)
    monkeypatch.setattr(agent, "GEMINI_THINKING_LEVEL", "minimal")
    monkeypatch.setenv("EGRESS_PROXY_URL", "http://proxy.example:15182")
    monkeypatch.setenv("GEMINI_EGRESS", "proxy")

    llm = agent.build_google_llm()

    assert llm._opts.http_options.client_args == {
        "trust_env": False,
        "proxy": "http://proxy.example:15182",
    }
    assert llm._client._api_client._http_options.client_args == {
        "trust_env": False,
        "proxy": "http://proxy.example:15182",
    }
