import config


def test_optional_llm_provider_disabled_values_disable_routing() -> None:
    for raw_provider in ("", "disabled", "disable", "off", "none", "false"):
        assert config._normalize_optional_llm_provider(raw_provider) == ""


def test_optional_llm_provider_keeps_supported_aliases() -> None:
    assert config._normalize_optional_llm_provider("gemini") == "google"
    assert config._normalize_optional_llm_provider("grok") == "xai"
