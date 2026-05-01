import pytest

import robot_settings
from robot_settings import (
    ComponentProfile,
    ProfileBinding,
    ProjectProfile,
    RobotSettingsStore,
)


def _store() -> RobotSettingsStore:
    return RobotSettingsStore(
        component_profiles=[
            ComponentProfile(
                profile_key="llm_base",
                kind="llm",
                provider="google",
                config={"provider": "google", "model": "base-model"},
            ),
            ComponentProfile(
                profile_key="llm_asterisk",
                kind="llm",
                provider="xai",
                config={"provider": "xai", "model": "asterisk-model"},
            ),
            ComponentProfile(
                profile_key="llm_project",
                kind="llm",
                provider="google",
                config={"provider": "google", "model": "project-model"},
            ),
            ComponentProfile(
                profile_key="tts_base",
                kind="tts",
                provider="elevenlabs",
                config={"provider": "elevenlabs", "voice_id": "base-voice"},
            ),
            ComponentProfile(
                profile_key="turn_base",
                kind="turn",
                provider="livekit",
                config={"min_endpointing_delay": 0.25},
            ),
        ],
        profile_bindings=[
            ProfileBinding("runtime", "base", "llm", "primary", "llm_base"),
            ProfileBinding("runtime", "base", "tts", "primary", "tts_base"),
            ProfileBinding("runtime", "base", "turn", "selected", "turn_base"),
            ProfileBinding("runtime", "asterisk", "llm", "primary", "llm_asterisk"),
            ProfileBinding("project", "coffee", "llm", "primary", "llm_project"),
        ],
        project_profiles=[
            ProjectProfile(
                profile_key="coffee",
                display_name="Coffee",
                client_id="10",
                did="+79990000000",
                runtime_key="base",
            )
        ],
        source="test",
    )


def test_runtime_inherits_base_when_runtime_binding_missing() -> None:
    resolved = _store().resolve(did=None, runtime_key="asterisk")

    assert resolved.llm_primary is not None
    assert resolved.llm_primary.profile_key == "llm_asterisk"
    assert resolved.tts_primary is not None
    assert resolved.tts_primary.profile_key == "tts_base"
    assert resolved.turn is not None
    assert resolved.turn.profile_key == "turn_base"


def test_project_binding_wins_over_runtime_and_base() -> None:
    resolved = _store().resolve(did="79990000000", runtime_key="asterisk")

    assert resolved.project_key == "coffee"
    assert resolved.effective_runtime_key == "asterisk"
    assert resolved.llm_primary is not None
    assert resolved.llm_primary.profile_key == "llm_project"


def test_unknown_project_falls_back_to_runtime_then_base() -> None:
    resolved = _store().resolve(did="+78880000000", runtime_key="asterisk")

    assert resolved.project_key is None
    assert resolved.llm_primary is not None
    assert resolved.llm_primary.profile_key == "llm_asterisk"
    assert resolved.tts_primary is not None
    assert resolved.tts_primary.profile_key == "tts_base"


def test_runtime_profile_columns_are_used_as_bindings() -> None:
    store = RobotSettingsStore.from_payload(
        {
            "component_profiles": [
                {
                    "profile_key": "llm_base",
                    "kind": "llm",
                    "provider": "google",
                    "config_json": {"model": "base-model"},
                    "active": True,
                }
            ],
            "runtime_profiles": [
                {
                    "runtime_key": "base",
                    "llm_profile": "llm_base",
                    "active": True,
                }
            ],
            "profile_bindings": [],
            "project_profiles": [],
        },
        source="test",
    )

    resolved = store.resolve(did=None, runtime_key="base")

    assert resolved.llm_primary is not None
    assert resolved.llm_primary.profile_key == "llm_base"


def test_explicit_binding_wins_over_profile_column() -> None:
    store = RobotSettingsStore.from_payload(
        {
            "component_profiles": [
                {
                    "profile_key": "llm_column",
                    "kind": "llm",
                    "provider": "google",
                    "config_json": {"model": "column-model"},
                    "active": True,
                },
                {
                    "profile_key": "llm_binding",
                    "kind": "llm",
                    "provider": "xai",
                    "config_json": {"model": "binding-model"},
                    "active": True,
                },
            ],
            "runtime_profiles": [
                {
                    "runtime_key": "base",
                    "llm_profile": "llm_column",
                    "active": True,
                }
            ],
            "profile_bindings": [
                {
                    "owner_type": "runtime",
                    "owner_key": "base",
                    "category": "llm",
                    "slot": "primary",
                    "profile_key": "llm_binding",
                    "active": True,
                }
            ],
            "project_profiles": [],
        },
        source="test",
    )

    resolved = store.resolve(did=None, runtime_key="base")

    assert resolved.llm_primary is not None
    assert resolved.llm_primary.profile_key == "llm_binding"


def test_project_profile_columns_override_runtime() -> None:
    store = RobotSettingsStore.from_payload(
        {
            "component_profiles": [
                {
                    "profile_key": "llm_base",
                    "kind": "llm",
                    "provider": "google",
                    "config_json": {"model": "base-model"},
                    "active": True,
                },
                {
                    "profile_key": "llm_project",
                    "kind": "llm",
                    "provider": "xai",
                    "config_json": {"model": "project-model"},
                    "active": True,
                },
            ],
            "runtime_profiles": [
                {
                    "runtime_key": "base",
                    "llm_profile": "llm_base",
                    "active": True,
                }
            ],
            "profile_bindings": [],
            "project_profiles": [
                {
                    "profile_key": "coffee",
                    "did": "+7 999 000-00-00",
                    "runtime_key": "base",
                    "llm_profile": "llm_project",
                    "active": True,
                }
            ],
        },
        source="test",
    )

    resolved = store.resolve(did="79990000000", runtime_key="base")

    assert resolved.project_key == "coffee"
    assert resolved.llm_primary is not None
    assert resolved.llm_primary.profile_key == "llm_project"


@pytest.mark.asyncio
async def test_directus_failure_uses_existing_cache(monkeypatch) -> None:
    robot_settings.reset_robot_settings_cache()
    cached_store = _store()
    monkeypatch.setattr(robot_settings, "_cached_store", cached_store)
    monkeypatch.setattr(robot_settings, "_cached_at", 0.0)
    monkeypatch.setattr(robot_settings, "ROBOT_SETTINGS_CACHE_TTL_SEC", 0.0)
    monkeypatch.setattr(robot_settings, "DIRECTUS_URL", "https://directus.example")
    monkeypatch.setattr(robot_settings, "DIRECTUS_TOKEN", "token")

    async def fail_fetch() -> dict:
        raise RuntimeError("directus down")

    monkeypatch.setattr(robot_settings, "_fetch_directus_payload", fail_fetch)

    store = await robot_settings.load_robot_settings_store(force_refresh=True)

    assert store is cached_store


@pytest.mark.asyncio
async def test_directus_failure_uses_snapshot_on_cold_start(monkeypatch, tmp_path) -> None:
    snapshot = tmp_path / "robot_settings_snapshot.json"
    snapshot.write_text(
        """
        {
          "component_profiles": [
            {
              "profile_key": "llm_base",
              "kind": "llm",
              "provider": "google",
              "config_json": {"provider": "google", "model": "snapshot-model"},
              "active": true
            }
          ],
          "profile_bindings": [
            {
              "owner_type": "runtime",
              "owner_key": "base",
              "category": "llm",
              "slot": "primary",
              "profile_key": "llm_base",
              "active": true
            }
          ],
          "project_profiles": []
        }
        """,
        encoding="utf-8",
    )
    robot_settings.reset_robot_settings_cache()
    monkeypatch.setattr(robot_settings, "ROBOT_SETTINGS_SNAPSHOT_FILE", str(snapshot))
    monkeypatch.setattr(robot_settings, "DIRECTUS_URL", "https://directus.example")
    monkeypatch.setattr(robot_settings, "DIRECTUS_TOKEN", "token")

    async def fail_fetch() -> dict:
        raise RuntimeError("directus down")

    monkeypatch.setattr(robot_settings, "_fetch_directus_payload", fail_fetch)

    resolved = await robot_settings.resolve_robot_settings_for_call(
        did=None,
        runtime_key="base",
    )

    assert resolved.source.startswith("snapshot:")
    assert resolved.llm_primary is not None
    assert resolved.llm_primary.config["model"] == "snapshot-model"
