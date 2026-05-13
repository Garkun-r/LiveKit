import pytest
from google.auth.credentials import AnonymousCredentials
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


def test_build_google_vertex_llm_uses_profile_location_and_credentials(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        agent,
        "_load_google_cloud_credentials_for_vertex",
        lambda: (AnonymousCredentials(), "inferred-project"),
    )

    llm = agent.build_llm_for_provider(
        "google_vertex",
        llm_profile=agent.ComponentSelection(
            category="llm",
            slot="primary",
            profile_key="test_vertex",
            kind="llm",
            provider="google_vertex",
            config={
                "model": "gemini-3.1-flash-lite",
                "location": "europe-west1",
                "temperature": 0.7,
                "max_output_tokens": 512,
                "top_p": 1,
                "thinking_level": "minimal",
                "egress": "direct",
            },
            source_owner_type="runtime",
            source_owner_key="base",
        ),
    )

    assert isinstance(llm, google.LLM)
    assert llm.provider == "Vertex AI"
    assert llm.model == "gemini-3.1-flash-lite"
    assert llm._client.vertexai is True
    assert llm._client._api_client.project == "inferred-project"
    assert llm._client._api_client.location == "europe-west1"
    assert llm._client._api_client._http_options.client_args == {"trust_env": False}
