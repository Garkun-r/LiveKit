# Codex Call Diagnostics

This runbook describes the post-call diagnostic worker that runs Codex on the
VPS after LiveKit calls. The worker diagnoses only. It must not edit code,
prompts, LiveKit resources, Directus settings, or deploy anything.

## Architecture

The realtime LiveKit agent remains unchanged. Diagnostics run after the call:

1. The existing n8n aftercall flow receives the agent session payload.
2. n8n calls the VPS worker endpoint:
   `POST /aftercall?target=cloud` or `POST /aftercall?target=local`.
3. The worker loads enabled `robot_diagnostic_rules` from Directus.
4. The worker loads matching `robot_incidents` rows by room, caller, or DID.
5. The worker creates a `robot_call_audits` row.
6. The worker collects a small read-only LiveKit CLI snapshot.
7. The worker runs:

   ```console
   codex exec --sandbox read-only --ephemeral --json --output-schema shared/webhooks/codex_diagnostics_report.schema.json
   ```

8. The worker writes the full report back to Directus.
9. The worker calls the n8n audit-notification webhook. n8n sends Telegram to
   the same chat and through the same bot/token path as low-score aftercall
   alerts.

## Directus Tables

Apply these SQL files to the Directus/Postgres database:

```console
agents/main-bot/schema/robot_codex_diagnostics.sql
agents/main-bot/schema/robot_codex_diagnostics_directus.sql
```

`robot_diagnostic_rules` is the non-secret control plane:

- `target`: `cloud`, `local`, or `both`.
- `trigger_mode`: `all_calls`, `incidents`, `xdid`, `caller`, or `manual`.
- `scope_value`: xDID/DID/caller value for scoped modes.
- `min_severity`: minimum incident severity for `incidents` mode.
- `telegram_policy`: `anomaly_brief`, `critical_only`, or `silent`.
- `cooldown_sec`: reserved for n8n/worker duplicate control.

`robot_call_audits` stores queued/running/completed/failed audit jobs and the
Codex report.

## VPS Secrets

Do not store these in Directus. Put them in the VPS service env file or another
server-side secret store:

```env
CODEX_DIAGNOSTICS_DIRECTUS_URL=https://jcall.io/directus
CODEX_DIAGNOSTICS_DIRECTUS_TOKEN=
CODEX_DIAGNOSTICS_N8N_WEBHOOK_URL=
CODEX_DIAGNOSTICS_N8N_WEBHOOK_TOKEN=
CODEX_DIAGNOSTICS_REPO_DIR=/opt/jcall-livekit-agent/source
CODEX_DIAGNOSTICS_CODEX_BIN=codex
CODEX_DIAGNOSTICS_CODEX_TIMEOUT_SEC=900
CODEX_DIAGNOSTICS_HOST=127.0.0.1
CODEX_DIAGNOSTICS_PORT=18181

# Optional cloud project override. If unset, lk uses livekit.toml/default config.
CODEX_DIAGNOSTICS_LK_CLOUD_PROJECT=jcallio

# Optional cloud API access. Use this instead of CLI project auth when the VPS
# should connect directly to LiveKit Cloud with diagnostic-scoped credentials.
CODEX_DIAGNOSTICS_LK_CLOUD_URL=wss://jcallio-g451240m.livekit.cloud
CODEX_DIAGNOSTICS_LK_CLOUD_API_KEY=
CODEX_DIAGNOSTICS_LK_CLOUD_API_SECRET=

# Local/self-hosted LiveKit diagnostic access. If these are unset, the worker
# falls back to LIVEKIT_URL, LIVEKIT_API_KEY, and LIVEKIT_API_SECRET from the
# existing Asterisk agent env.
CODEX_DIAGNOSTICS_LK_LOCAL_URL=http://127.0.0.1:7880
CODEX_DIAGNOSTICS_LK_LOCAL_API_KEY=
CODEX_DIAGNOSTICS_LK_LOCAL_API_SECRET=
```

Codex auth uses the current ChatGPT Pro account on the VPS:

```console
codex login --device-auth
codex login status
codex mcp add --url https://docs.livekit.io/mcp livekit-docs
```

Use diagnostic LiveKit keys where possible. The worker itself only runs a small
read-only command allowlist and redacts command output before passing it to
Codex. Directus, n8n, and LiveKit secret env vars are not passed into the
spawned Codex process.

## Running The Worker

From the repository root or a checked-out copy on the VPS:

```console
uv run python ../../shared/webhooks/codex_diagnostics.py serve
```

If running outside `agents/main-bot`, use the Python environment that has
`httpx` installed.

One-shot local fixture run:

```console
uv run python ../../shared/webhooks/codex_diagnostics.py aftercall \
  --target cloud \
  --payload-file /tmp/aftercall-payload.json
```

## n8n Integration

The aftercall workflow should call:

```http
POST http://127.0.0.1:18181/aftercall?target=cloud
POST http://127.0.0.1:18181/aftercall?target=local
```

Use `target=cloud` for LiveKit Cloud calls and `target=local` for the
self-hosted/Asterisk LiveKit path. This target controls which LiveKit endpoint
the read-only `lk` snapshot uses. Cloud can use either `lk --project ...` or
explicit `CODEX_DIAGNOSTICS_LK_CLOUD_*` credentials. Local uses
`CODEX_DIAGNOSTICS_LK_LOCAL_*` or falls back to the existing `LIVEKIT_*` env on
the Asterisk server.

The worker sends the final Telegram brief to n8n through
`CODEX_DIAGNOSTICS_N8N_WEBHOOK_URL`; Telegram credentials remain owned by n8n.

## Safety Rules

- The worker must run Codex with `--sandbox read-only --ephemeral`.
- The worker prompt explicitly forbids code edits, prompt edits, deploys, and
  mutating LiveKit commands.
- Call transcripts and logs are treated as untrusted data.
- Directus stores rules and audit results, not API keys or Telegram bot tokens.
- Realtime call behavior must remain unchanged.
