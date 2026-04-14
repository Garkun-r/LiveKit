import pytest

import agent
from livekit.plugins import google


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
