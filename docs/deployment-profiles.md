# Deployment profiles

This repository keeps one LiveKit agent codebase and separates runtime behavior
through env profiles.

## Principle

The runtime environment is flat. The agent reads keys like `AGENT_NAME`,
`LIVEKIT_SELF_HOSTED`, `TTS_PROVIDER`, `STT_PROVIDER`, and `LLM_PROVIDER`
directly from the process environment. Therefore one running process should get
one resolved env file, not one file containing three prefixed configurations.

Use these layers:

1. Code: shared voice flow, tools, provider builders, diagnostics, exports.
2. Deployment env: LiveKit URL, dispatch name, self-hosted/cloud mode, secrets,
   egress, health port, worker sizing.
3. Project/call profile: prompt, greeting, voice, and later per-client
   TTS/STT/LLM choices from Directus or another profile store.

## Profiles

| Profile | Purpose | Env template |
| --- | --- | --- |
| `mac` | local Mac development and console testing | `agents/main-bot/env/mac.env.example` |
| `cloud` | LiveKit Cloud deployed agent | `agents/main-bot/env/cloud.env.example` |
| `asterisk` | self-hosted LiveKit on the Asterisk server | `agents/main-bot/env/asterisk.env.example` |

Shared defaults live in `agents/main-bot/env/common.env.example`.

## Dispatch names

The intended dispatch names are:

```console
main-bot-mac
main-bot-cloud
main-bot-asterisk
```

Changing `AGENT_NAME` is not just cosmetic. SIP dispatch rules, API dispatch,
or token `room_config.agents` must target the same name. Do not change the
Asterisk production `AGENT_NAME` until the SIP dispatch rule is changed at the
same time.

## Build env files

Mac:

```console
cd agents/main-bot
uv run python scripts/build_env.py --profile mac --secrets env/mac.secrets.env --output .env.local
uv run python src/agent.py console
```

Cloud:

```console
cd agents/main-bot
uv run python scripts/build_env.py --profile cloud --secrets env/cloud.secrets.env --output .env.cloud.local
uv run python scripts/sync_cloud_secrets.py --env-file .env.cloud.local
lk agent deploy
```

Asterisk candidate file:

```console
cd agents/main-bot
uv run python scripts/build_env.py --profile asterisk --secrets env/asterisk.secrets.env --output /tmp/main-bot.env
```

The current Asterisk env file already exists on the server:

```console
/etc/jcall-livekit-agent/main-bot.env
```

Treat it as the production source of truth. Generate `/tmp/main-bot.env` only
for review or migration, then compare sanitized keys before replacing anything.

## What belongs where

Keep shared in `common.env.example`:

- prompt lookup collection names;
- LLM routing/fallback policy after approval;
- turn handling defaults;
- provider model defaults that all deployments intentionally share;
- incident log schema/transport defaults;
- non-secret webhook defaults.

Keep per deployment in `mac/cloud/asterisk.env.example`:

- `AGENT_NAME`;
- `INCIDENT_ENVIRONMENT`;
- `LIVEKIT_SELF_HOSTED`;
- health host/port;
- worker concurrency;
- audio enhancement;
- `EGRESS_*` routing;
- LiveKit connection placeholders.

Keep real values only in ignored secrets files or platform secret stores:

- API keys;
- LiveKit credentials;
- Directus token;
- n8n token;
- Google service account JSON/B64;
- provider-specific credentials.

Keep per project/client out of deployment env when possible:

- prompt text;
- first greeting;
- voice/persona;
- project-specific TTS/STT/LLM profile;
- transfer number;
- customer-specific workflow facts.

Those should come from Directus by DID/client/project so the same deployed
agent can handle multiple projects without code forks.
