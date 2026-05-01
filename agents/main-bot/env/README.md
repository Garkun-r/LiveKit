# Agent environment profiles

This directory separates one shared agent codebase into three runtime profiles:

- `mac.env.example` - local development on the Mac.
- `cloud.env.example` - LiveKit Cloud deployment.
- `asterisk.env.example` - self-hosted LiveKit on the Asterisk server.

Runtime env is flat. Do not keep three prefixed configs in one real `.env`
file unless the application code explicitly expands those prefixes. The current
agent reads normal keys such as `AGENT_NAME`, `TTS_PROVIDER`, `STT_PROVIDER`,
and `LLM_PROVIDER`, so each running process must receive exactly one resolved
env file.

Use `common.env.example` for settings that should normally stay the same across
all three profiles. Use the profile files only for deployment identity,
networking, dispatch, local/cloud behavior, and measured provider routing.

Secrets are not stored here. Put real values in ignored local files such as:

```console
env/mac.secrets.env
env/cloud.secrets.env
env/asterisk.secrets.env
```

Use `secrets.env.example` as the copy source for those ignored files.

Build a local env file:

```console
uv run python scripts/build_env.py --profile mac --secrets env/mac.secrets.env --output .env.local
```

Build a Cloud sync file:

```console
uv run python scripts/build_env.py --profile cloud --secrets env/cloud.secrets.env --output .env.cloud.local
uv run python scripts/sync_cloud_secrets.py --env-file .env.cloud.local
```

Build an Asterisk candidate file for review:

```console
uv run python scripts/build_env.py --profile asterisk --secrets env/asterisk.secrets.env --output /tmp/main-bot.env
```

Do not overwrite `/etc/jcall-livekit-agent/main-bot.env` on the Asterisk server
without explicit approval. That file currently contains the production-tested
settings.
