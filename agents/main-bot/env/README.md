# Agent environment profiles

This directory separates one shared agent codebase into runtime profiles:

- `mac.env.example` - local development on the Mac.
- `cloud.env.example` - LiveKit Cloud deployment.
- `cloud-test.env.example` - isolated LiveKit Cloud test agent.
- `asterisk.env.example` - self-hosted LiveKit on the Asterisk server.

Runtime env is flat. Do not keep three prefixed configs in one real `.env`
file unless the application code explicitly expands those prefixes. The current
agent reads normal keys such as `AGENT_NAME`, `TTS_PROVIDER`, `STT_PROVIDER`,
and `LLM_PROVIDER`, so each running process must receive exactly one resolved
env file.

Use `common.env.example` for settings that should normally stay the same across
all profiles. Use the profile files only for deployment identity,
networking, dispatch, local/cloud behavior, and measured provider routing.
Each profile file must also set `ROBOT_RUNTIME_PROFILE` so Directus settings
resolve through the intended runtime: `mac`, `base`, `main_bot_test`, or
`asterisk`.

Cloud SIP dispatch currently targets agent name `main-bot`. Do not change the
Cloud `AGENT_NAME` template without updating the matching LiveKit SIP dispatch
rule at the same time.

The `cloud-test` profile is intentionally separate from production:

- `AGENT_NAME=main-bot-test` controls LiveKit agent dispatch.
- `ROBOT_RUNTIME_PROFILE=main_bot_test` controls Directus profile selection.
- Do not point the current production SIP dispatch rule at `main-bot-test`.
- For test experiments, create separate component profiles and assign them to
  `runtime.main_bot_test.*` in `robot_profile_bindings`; do not edit shared
  production component profiles in place.

Secrets are not stored here. Put real values in ignored local files such as:

```console
env/mac.secrets.env
env/cloud.secrets.env
env/cloud-test.secrets.env
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

Build a Cloud test sync file:

```console
uv run python scripts/build_env.py --profile cloud-test --secrets env/cloud-test.secrets.env --output .env.cloud-test.local
uv run python scripts/sync_cloud_secrets.py --env-file .env.cloud-test.local --config livekit.test.toml
```

`sync_cloud_secrets.py` updates provided keys without deleting other cloud
secrets by default. Use `--overwrite` only for an intentional full replacement
after confirming the env file contains every required runtime and diagnostics
secret.

Build an Asterisk candidate file for review:

```console
uv run python scripts/build_env.py --profile asterisk --secrets env/asterisk.secrets.env --output /tmp/main-bot.env
```

Do not overwrite `/etc/jcall-livekit-agent/main-bot.env` on the Asterisk server
without explicit approval. That file currently contains the production-tested
settings.
