from urllib.parse import parse_qs, urlparse

import pytest

import agent
from deepgram_flux_stt import DeepgramFluxSTT, build_deepgram_flux_ws_url
from robot_settings import ComponentSelection


def _stt_profile(config: dict) -> ComponentSelection:
    return ComponentSelection(
        category="stt",
        slot="primary",
        profile_key="test_stt",
        kind="stt",
        provider="deepgram",
        config={"provider": "deepgram", **config},
        source_owner_type="runtime",
        source_owner_key="base",
    )


def test_build_stt_uses_direct_deepgram_flux(monkeypatch) -> None:
    captured = {}

    class _FakeFluxSTT:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(agent, "DEEPGRAM_API_KEY", "test-key")
    monkeypatch.setattr(agent, "STT_EARLY_INTERIM_FINAL_ENABLED", False)
    monkeypatch.setattr(agent, "DeepgramFluxSTT", _FakeFluxSTT)

    result = agent.build_stt(
        stt_profile=_stt_profile(
            {
                "api_version": "v2",
                "model": "deepgram/flux-general-multi",
                "language": "ru",
                "language_hints": ["ru"],
                "sample_rate": 16000,
                "eot_threshold": 0.7,
                "eot_timeout_ms": 5000,
            }
        )
    )

    assert isinstance(result, _FakeFluxSTT)
    assert captured["api_key"] == "test-key"
    assert captured["model"] == "flux-general-multi"
    assert captured["language"] == "ru"
    assert captured["language_hints"] == ["ru"]
    assert captured["sample_rate"] == 16000
    assert captured["eot_threshold"] == 0.7
    assert captured["eot_timeout_ms"] == 5000


def test_build_stt_keeps_nova_on_deepgram_v1(monkeypatch) -> None:
    captured = {}

    class _FakeDeepgramSTT:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(agent, "DEEPGRAM_API_KEY", "test-key")
    monkeypatch.setattr(agent, "STT_EARLY_INTERIM_FINAL_ENABLED", False)
    monkeypatch.setattr(agent.deepgram, "STT", _FakeDeepgramSTT)

    result = agent.build_stt(
        stt_profile=_stt_profile(
            {
                "model": "nova-3",
                "language": "ru",
                "endpointing_ms": 90,
            }
        )
    )

    assert isinstance(result, _FakeDeepgramSTT)
    assert captured["api_key"] == "test-key"
    assert captured["model"] == "nova-3"
    assert captured["language"] == "ru"
    assert captured["endpointing_ms"] == 90
    assert "language_hints" not in captured


def test_flux_url_uses_v2_model_and_repeated_language_hint() -> None:
    url = build_deepgram_flux_ws_url(
        base_url="wss://api.deepgram.com/v2/listen",
        model="deepgram/flux-general-multi",
        sample_rate=16000,
        language_hints=["ru"],
        eot_threshold=0.7,
        eot_timeout_ms=5000,
    )

    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert parsed.scheme == "wss"
    assert parsed.path == "/v2/listen"
    assert query["model"] == ["flux-general-multi"]
    assert query["language_hint"] == ["ru"]
    assert query["encoding"] == ["linear16"]
    assert query["sample_rate"] == ["16000"]
    assert query["eot_threshold"] == ["0.7"]
    assert query["eot_timeout_ms"] == ["5000"]
    assert "language" not in query


def test_flux_rejects_eager_eot_above_eot_threshold() -> None:
    with pytest.raises(ValueError):
        DeepgramFluxSTT(
            api_key="test-key",
            model="flux-general-multi",
            eager_eot_threshold=0.8,
            eot_threshold=0.7,
        )
