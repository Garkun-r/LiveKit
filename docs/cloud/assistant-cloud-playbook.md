# Assistant cloud playbook

Last reviewed: 2026-04-24 11:25:02 +07.

This document tells a future coding agent how to work with the LiveKit Cloud part of this project.

## What Codex can manage

With the right access, Codex can help manage:

- LiveKit Cloud projects visible to the local `lk` CLI.
- Cloud agents: create, deploy, update, restart, rollback, delete, list versions, inspect status, and tail logs.
- Agent secrets: list secret names, sync from `.env.local`, update secrets, and add file-mounted secrets.
- Runtime diagnostics: build logs, deploy logs, agent status, active rooms, participants, ingress, egress, and sessions visible in LiveKit Cloud.
- Telephony: LiveKit Phone Numbers, SIP inbound trunks, SIP outbound trunks, dispatch rules, and SIP participants for outbound calls.
- Room service operations: create/list/delete rooms, list/remove participants, mute tracks, update metadata, send data packets.
- Media import/export: ingress resources and egress recordings/streams.
- Access tokens and grants: generate or explain JWT grants for video, SIP, ingress, egress, and room admin workflows.

## Access required

- `lk cloud auth` for account-level CLI access to LiveKit Cloud projects.
- Or `LIVEKIT_URL`, `LIVEKIT_API_KEY`, and `LIVEKIT_API_SECRET` for server API access.
- Dashboard project access for UI-only settings, billing, data/privacy, observability, and some telephony operations.
- SIP grant with `admin: true` for trunk and dispatch-rule management.
- SIP grant with `call: true` for outbound SIP calls through `CreateSIPParticipant`.
- Video grants for room operations:
  - `roomCreate` for create/delete rooms.
  - `roomList` for listing active rooms.
  - `roomAdmin` for participant moderation.
  - `roomRecord` for egress.
  - `ingressAdmin` for ingress.
- Provider secrets for this agent's runtime: Google/Gemini, Deepgram, ElevenLabs, xAI, MiniMax, CosyVoice, Postgres, and n8n as configured.

## Safety rules

- Never print, commit, or document secret values.
- Listing cloud secret names with `lk agent secrets` is allowed; values cannot be retrieved from CLI or dashboard.
- Do not use `--overwrite` on secrets unless the user explicitly asks for full replacement.
- Do not release phone numbers, delete trunks, delete dispatch rules, delete agents, delete rooms, stop egress, or start outbound calls unless the user explicitly asks.
- Treat `lk agent restart`, `lk agent rollback`, `lk agent update-secrets`, and `lk agent deploy` as production-impacting operations.
- Before any write operation, run read-only inspection first and summarize the intended change.
- Preserve the voice pipeline unless the user asks to change it.

## Standard workflow

Start from the agent directory:

```bash
cd /Users/romangarkun/Documents/LiveKit/agents/main-bot
```

Check docs first:

```bash
lk docs --help
lk docs overview
lk docs get-page /deploy/agents.md /reference/developer-tools/livekit-cli/agent.md
```

Inspect cloud state:

```bash
lk project list
lk agent list
lk agent status
lk agent versions
lk agent secrets
lk room list
lk sip inbound list
lk sip outbound list
lk sip dispatch list
lk number list
lk ingress list
lk egress list
```

Deploy after local verification:

```bash
uv run python scripts/sync_cloud_secrets.py --env-file .env.local
lk agent deploy
lk agent status
lk agent logs --log-type deploy
```

Rollback if a deployed version is bad:

```bash
lk agent versions
lk agent rollback --version <version>
lk agent status
```

## Project-specific cloud assumptions

- The main cloud agent is configured by `agents/main-bot/livekit.toml`.
- The configured agent ID is `CA_oaEZ279sgQGr`.
- The configured project subdomain is `jcallio-g451240m`.
- Current deployed region is `eu-central`.
- The code default `AGENT_NAME` is `main-bot`, and the current SIP dispatch rule targets `main-bot`.
- The current inbound SIP path uses one inbound trunk and one dispatch rule; see [current-cloud-state.md](current-cloud-state.md).

## Telephony workflow

For inbound calls:

1. Confirm SIP provider routing and source IPs.
2. Create or update an inbound trunk with `lk sip inbound ...`.
3. Create or update a dispatch rule with `lk sip dispatch ...`.
4. Confirm the rule points to the expected agent name.
5. Test with a controlled inbound call and inspect room/agent logs.

Current inbound pattern:

- Inbound trunk accepts traffic from `87.226.145.66/32`.
- Dispatch rule creates individual caller rooms named like `_<caller>_<random>`.
- Dispatch rule dispatches agent `main-bot`.

For outbound calls:

1. Confirm an outbound trunk exists.
2. Confirm the token or server key has SIP `call` permission.
3. Use `lk sip participant create <participant.json>` or the server SDK.
4. Never place real outbound calls without explicit user approval.

## Secrets workflow

Preferred sync path for this repository:

```bash
uv run python scripts/sync_cloud_secrets.py --env-file .env.local
```

Direct LiveKit CLI alternative:

```bash
lk agent update-secrets --secrets-file .env.local
```

Important details from LiveKit docs:

- LiveKit automatically injects `LIVEKIT_URL`, `LIVEKIT_API_KEY`, and `LIVEKIT_API_SECRET` for the deployed cloud agent.
- Secret values are encrypted at rest and injected into the container runtime as environment variables.
- Secret values have a 16KB maximum size.
- File-mounted secrets are mounted under `/etc/secrets/<filename>`.
- Updating secrets restarts the agent pool for future sessions.

## Observability workflow

Use CLI logs for quick server-level inspection:

```bash
lk agent logs --log-type deploy
lk agent logs --log-type build
```

Use LiveKit Cloud Dashboard for Agent Insights:

- Session transcripts.
- Voice pipeline traces and metrics.
- Session logs.
- Session audio recordings.

Important details from LiveKit docs:

- Agent observability data has a 30-day retention window.
- Session-level logs do not cover startup failures, crashes outside a session, or dispatch errors; use CLI logs or a log drain for those.
- External log drains are available through specific secrets for Datadog, CloudWatch, Sentry, and New Relic.

## Verification checklist

After cloud changes:

- `lk agent status` shows expected version/status.
- `lk agent logs --log-type deploy` shows no startup error.
- `lk room list` behaves as expected for active test sessions.
- SIP changes are visible with `lk sip inbound/outbound/dispatch list`.
- Secrets list contains expected names and no unexpected removals.
- Local entrypoint remains `agents/main-bot/src/agent.py`.
- Realtime flow is not changed unless the task requested it.
