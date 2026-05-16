import importlib.util
import sys
from pathlib import Path


def load_sync_cloud_secrets_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "sync_cloud_secrets.py"
    spec = importlib.util.spec_from_file_location("sync_cloud_secrets", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sync_cloud_secrets_updates_without_overwrite_by_default(
    tmp_path, monkeypatch
) -> None:
    sync_cloud_secrets = load_sync_cloud_secrets_module()
    env_file = tmp_path / ".env.local"
    env_file.write_text(
        "\n".join(
            [
                "AGENT_NAME=main-bot",
                "DIRECTUS_TOKEN=directus-token",
                "ELEVEN_API_KEY=eleven-token",
                "LIVEKIT_URL=wss://example.livekit.cloud",
            ]
        ),
        encoding="utf-8",
    )
    calls = []

    def fake_run(cmd, check):
        secrets_file = Path(cmd[cmd.index("--secrets-file") + 1])
        calls.append(
            {
                "cmd": cmd,
                "check": check,
                "secrets": secrets_file.read_text(encoding="utf-8"),
            }
        )

    monkeypatch.setattr(sync_cloud_secrets.subprocess, "run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sync_cloud_secrets.py",
            "--env-file",
            str(env_file),
            "--working-dir",
            str(tmp_path),
        ],
    )

    sync_cloud_secrets.main()

    assert len(calls) == 1
    assert "--overwrite" not in calls[0]["cmd"]
    assert calls[0]["check"] is True
    assert "AGENT_NAME=main-bot\n" in calls[0]["secrets"]
    assert "DIRECTUS_TOKEN=directus-token\n" in calls[0]["secrets"]
    assert "ELEVEN_API_KEY=eleven-token\n" in calls[0]["secrets"]
    assert "ELEVENLABS_API_KEY=eleven-token\n" in calls[0]["secrets"]
    assert "LIVEKIT_URL=" not in calls[0]["secrets"]


def test_sync_cloud_secrets_overwrite_requires_explicit_flag(tmp_path, monkeypatch) -> None:
    sync_cloud_secrets = load_sync_cloud_secrets_module()
    env_file = tmp_path / ".env.local"
    env_file.write_text("AGENT_NAME=main-bot\n", encoding="utf-8")
    calls = []

    def fake_run(cmd, check):
        calls.append({"cmd": cmd, "check": check})

    monkeypatch.setattr(sync_cloud_secrets.subprocess, "run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sync_cloud_secrets.py",
            "--env-file",
            str(env_file),
            "--working-dir",
            str(tmp_path),
            "--overwrite",
        ],
    )

    sync_cloud_secrets.main()

    assert len(calls) == 1
    assert "--overwrite" in calls[0]["cmd"]


def test_sync_cloud_secrets_can_target_separate_config(tmp_path, monkeypatch) -> None:
    sync_cloud_secrets = load_sync_cloud_secrets_module()
    env_file = tmp_path / ".env.cloud-test.local"
    env_file.write_text("AGENT_NAME=main-bot-test\n", encoding="utf-8")
    calls = []

    def fake_run(cmd, check):
        calls.append({"cmd": cmd, "check": check})

    monkeypatch.setattr(sync_cloud_secrets.subprocess, "run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sync_cloud_secrets.py",
            "--env-file",
            str(env_file),
            "--working-dir",
            str(tmp_path),
            "--config",
            "livekit.test.toml",
        ],
    )

    sync_cloud_secrets.main()

    assert len(calls) == 1
    assert "--overwrite" not in calls[0]["cmd"]
    assert calls[0]["cmd"][calls[0]["cmd"].index("--config") + 1] == "livekit.test.toml"
