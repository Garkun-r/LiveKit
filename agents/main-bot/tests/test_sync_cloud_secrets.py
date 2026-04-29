import importlib.util
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "sync_cloud_secrets.py"
SPEC = importlib.util.spec_from_file_location("sync_cloud_secrets", SCRIPT_PATH)
sync_cloud_secrets = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(sync_cloud_secrets)


def test_build_secret_map_excludes_cloud_creds_and_proxy_routes(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.local"
    env_file.write_text(
        "\n".join(
            [
                "LIVEKIT_URL=wss://example.livekit.cloud",
                "LIVEKIT_API_KEY=api-key",
                "LIVEKIT_API_SECRET=api-secret",
                "EGRESS_PROXY_URL=http://proxy.example:15182",
                "HTTPS_PROXY=http://proxy.example:15182",
                "GEMINI_EGRESS=proxy",
                "XAI_EGRESS=true",
                "DEEPGRAM_EGRESS=direct",
                "OPENAI_API_KEY=openai-key",
                "ELEVEN_API_KEY=eleven-key",
            ]
        )
    )

    secrets = sync_cloud_secrets.build_secret_map(
        env_file,
        exclude_keys=set(sync_cloud_secrets.DEFAULT_EXCLUDE_KEYS),
    )

    assert "LIVEKIT_URL" not in secrets
    assert "LIVEKIT_API_KEY" not in secrets
    assert "LIVEKIT_API_SECRET" not in secrets
    assert "EGRESS_PROXY_URL" not in secrets
    assert "HTTPS_PROXY" not in secrets
    assert "GEMINI_EGRESS" not in secrets
    assert "XAI_EGRESS" not in secrets
    assert secrets["DEEPGRAM_EGRESS"] == "direct"
    assert secrets["OPENAI_API_KEY"] == "openai-key"
    assert secrets["ELEVEN_API_KEY"] == "eleven-key"
    assert secrets["ELEVENLABS_API_KEY"] == "eleven-key"
