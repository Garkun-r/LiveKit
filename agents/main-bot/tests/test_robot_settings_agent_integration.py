import agent
from robot_settings import ComponentSelection


def test_llm_fallback_comes_from_llm_profile() -> None:
    llm_profile = ComponentSelection(
        category="llm",
        slot="primary",
        profile_key="llm_xai",
        kind="llm",
        provider="xai",
        config={
            "provider": "xai",
            "model": "primary-model",
            "fallback_provider": "google",
            "fallback_model": "backup-model",
        },
        source_owner_type="runtime",
        source_owner_key="base",
    )

    provider, model = agent._backup_config_for_branch(
        "complex",
        primary_provider="xai",
        primary_profile=llm_profile,
    )

    assert provider == "google"
    assert model == "backup-model"
