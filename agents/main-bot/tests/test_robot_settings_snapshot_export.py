import importlib.util
from pathlib import Path


def _load_export_module():
    script_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "export_robot_settings_snapshot.py"
    )
    spec = importlib.util.spec_from_file_location("snapshot_export", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


snapshot_export = _load_export_module()


def test_build_snapshot_payload_is_stable_and_non_volatile() -> None:
    payload = {
        "component_profiles": [
            {
                "id": 2,
                "profile_key": "tts_b",
                "kind": "tts",
                "provider": "elevenlabs",
                "config_json": {"voice_id": "b", "unused": None},
                "active": True,
                "updated_at": "ignored",
            },
            {
                "id": 1,
                "profile_key": "llm_a",
                "kind": "llm",
                "provider": "google",
                "config_json": {"model": "a"},
                "active": True,
            },
        ],
        "runtime_profiles": [
            {
                "runtime_key": "base",
                "llm_profile": None,
                "override_json": {},
                "active": True,
                "created_at": "ignored",
            }
        ],
        "profile_bindings": [],
        "project_profiles": [],
        "setting_fields": [],
    }

    snapshot = snapshot_export.build_snapshot_payload(payload)

    assert snapshot["snapshot_version"] == 1
    assert [row["profile_key"] for row in snapshot["component_profiles"]] == [
        "llm_a",
        "tts_b",
    ]
    assert "id" not in snapshot["component_profiles"][0]
    assert "updated_at" not in snapshot["component_profiles"][1]
    assert "unused" not in snapshot["component_profiles"][1]["config_json"]
    assert "llm_profile" not in snapshot["runtime_profiles"][0]
    assert snapshot["runtime_profiles"][0]["override_json"] == {}


def test_secret_like_config_detection_allows_refs_only() -> None:
    payload = {
        "component_profiles": [
            {
                "profile_key": "llm_test",
                "config_json": {
                    "api_key_ref": "GOOGLE_API_KEY",
                    "max_output_tokens": 512,
                    "api_key": "not-allowed",
                },
            }
        ]
    }

    assert snapshot_export.find_secret_like_config_keys(payload) == ["llm_test.api_key"]
