import importlib.util
import sys
from pathlib import Path


def load_build_env_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "build_env.py"
    spec = importlib.util.spec_from_file_location("build_env", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_env_supports_cloud_test_profile(tmp_path, monkeypatch) -> None:
    build_env = load_build_env_module()
    output = tmp_path / ".env.cloud-test.local"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_env.py",
            "--profile",
            "cloud-test",
            "--output",
            str(output),
        ],
    )

    build_env.main()

    content = output.read_text(encoding="utf-8")
    assert "# profile=cloud-test" in content
    assert "DEPLOYMENT_PROFILE=cloud-test\n" in content
    assert "AGENT_NAME=main-bot-test\n" in content
    assert "ROBOT_RUNTIME_PROFILE=main_bot_test\n" in content
    assert "INCIDENT_ENVIRONMENT=cloud-test\n" in content
    assert "LIVEKIT_SELF_HOSTED=false\n" in content
