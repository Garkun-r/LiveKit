import pytest
from livekit.agents import NOT_GIVEN
from livekit.plugins import xai

import agent


def test_build_xai_llm_requires_api_key(monkeypatch) -> None:
    monkeypatch.setattr(agent, "XAI_API_KEY", "")

    with pytest.raises(RuntimeError, match="XAI_API_KEY is not set"):
        agent.build_xai_llm()


def test_build_xai_llm_uses_config(monkeypatch) -> None:
    monkeypatch.setattr(agent, "XAI_API_KEY", "test-key")
    monkeypatch.setattr(agent, "XAI_MODEL", "grok-4-1-fast-non-reasoning-latest")
    monkeypatch.setattr(agent, "XAI_TEMPERATURE", 0.3)
    monkeypatch.setattr(agent, "XAI_BASE_URL", "")

    llm = agent.build_xai_llm()

    assert isinstance(llm, xai.responses.LLM)
    assert llm.model == "grok-4-1-fast-non-reasoning-latest"
    assert llm._opts.temperature == 0.3


def test_build_xai_llm_uses_custom_base_url(monkeypatch) -> None:
    monkeypatch.setattr(agent, "XAI_API_KEY", "test-key")
    monkeypatch.setattr(agent, "XAI_MODEL", "grok-4-1-fast-non-reasoning-latest")
    monkeypatch.setattr(agent, "XAI_TEMPERATURE", 0.3)
    monkeypatch.setattr(agent, "XAI_BASE_URL", "https://eu-west-1.api.x.ai/v1")

    llm = agent.build_xai_llm()

    assert str(llm._client.base_url) == "https://eu-west-1.api.x.ai/v1/"


class _ModelSettings:
    def __init__(self, tool_choice: str) -> None:
        self.tool_choice = tool_choice


def test_xai_tools_disabled_by_default(monkeypatch) -> None:
    monkeypatch.setattr(agent, "LLM_PROVIDER", "xai")
    monkeypatch.setattr(agent, "XAI_ENABLE_TOOLS", False)
    assistant = agent.Assistant()
    configured_tools = [object()]

    resolved_tools, tool_choice = assistant._resolve_tools_for_llm_call(
        tools=configured_tools,
        model_settings=_ModelSettings("auto"),
    )

    assert resolved_tools == []
    assert tool_choice is NOT_GIVEN


def test_xai_tools_can_be_enabled(monkeypatch) -> None:
    monkeypatch.setattr(agent, "LLM_PROVIDER", "xai")
    monkeypatch.setattr(agent, "XAI_ENABLE_TOOLS", True)
    assistant = agent.Assistant()
    configured_tools = [object()]

    resolved_tools, tool_choice = assistant._resolve_tools_for_llm_call(
        tools=configured_tools,
        model_settings=_ModelSettings("auto"),
    )

    assert resolved_tools == configured_tools
    assert tool_choice == "auto"


def test_non_xai_provider_keeps_tools(monkeypatch) -> None:
    monkeypatch.setattr(agent, "LLM_PROVIDER", "google")
    monkeypatch.setattr(agent, "XAI_ENABLE_TOOLS", False)
    assistant = agent.Assistant()
    configured_tools = [object()]

    resolved_tools, tool_choice = assistant._resolve_tools_for_llm_call(
        tools=configured_tools,
        model_settings=_ModelSettings("auto"),
    )

    assert resolved_tools == configured_tools
    assert tool_choice == "auto"
