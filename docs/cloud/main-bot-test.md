# main-bot-test Cloud agent

Last reviewed: 2026-05-15.

This runbook prepares an isolated LiveKit Cloud test worker without changing the
production inbound SIP route.

## Identity

- Production worker: `AGENT_NAME=main-bot`, `ROBOT_RUNTIME_PROFILE=base`.
- Test worker: `AGENT_NAME=main-bot-test`, `ROBOT_RUNTIME_PROFILE=main_bot_test`.
- Directus seed: `agents/main-bot/schema/robot_main_bot_test_runtime.sql`.
- Env template: `agents/main-bot/env/cloud-test.env.example`.

LiveKit dispatch uses `AGENT_NAME`. Directus settings use
`ROBOT_RUNTIME_PROFILE`. Do not add implicit settings selection by `AGENT_NAME`;
existing runtime rows can share agent names, so `ROBOT_RUNTIME_PROFILE` is the
safe explicit selector.

## Setup

Apply the Directus seed before starting the test worker:

```bash
sudo -u postgres psql -d voicebot -f agents/main-bot/schema/robot_main_bot_test_runtime.sql
cd agents/main-bot
uv run python scripts/verify_robot_settings_directus.py --env-file .env.local --runtime main_bot_test
```

Build the test env file and create the separate Cloud agent:

```bash
cd agents/main-bot
uv run python scripts/build_env.py --profile cloud-test --secrets env/cloud-test.secrets.env --output .env.cloud-test.local
lk agent create --region eu-central --config livekit.test.toml --ignore-empty-secrets --secrets-file .env.cloud-test.local .
```

After `livekit.test.toml` exists, use it for all test Cloud operations:

```bash
uv run python scripts/sync_cloud_secrets.py --env-file .env.cloud-test.local --config livekit.test.toml --working-dir .
lk agent deploy --config livekit.test.toml .
lk agent status --config livekit.test.toml .
lk agent logs --config livekit.test.toml --log-type deploy .
```

## Experiment Rule

For test changes to LLM, STT, TTS, turn detection, fallback, or egress settings,
create or reuse a non-secret component profile and bind it to
`runtime.main_bot_test.*` in `robot_profile_bindings`. Do not edit shared
production component profiles to run test experiments.

## SIP

The first setup pass does not change SIP. Current production SIP dispatch points
to `main-bot`.

When phone testing is needed, use a separate test number or a route that can be
matched unambiguously, then create a dispatch rule with
`roomConfig.agents[].agentName = "main-bot-test"`. Do not create a second
competing dispatch rule for the current production trunk.
