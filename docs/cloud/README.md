# LiveKit Cloud documentation

Last reviewed: 2026-04-24 11:25:02 +07.

This folder is the project runbook for LiveKit Cloud work. Read it before touching cloud deployment, secrets, telephony, rooms, ingress, egress, or agent observability.

## Files

- [assistant-cloud-playbook.md](assistant-cloud-playbook.md): what Codex can manage in LiveKit Cloud, required access, safety rules, and standard commands.
- [current-cloud-state.md](current-cloud-state.md): read-only snapshot of the current LiveKit Cloud project and agent configuration.
- [cold-starts.md](cold-starts.md): why the cloud agent can show `Sleeping`, what causes test delays, and what can reduce them.

## Project entrypoints

- Repository root: `/Users/romangarkun/Documents/Проекты/LiveKit`
- Main agent directory: `/Users/romangarkun/Documents/Проекты/LiveKit/agents/main-bot`
- Agent code entrypoint: `agents/main-bot/src/agent.py`
- Cloud deployment config: `agents/main-bot/livekit.toml`
- Local env template: `agents/main-bot/.env.example`
- Local secret source for sync/deploy: `agents/main-bot/.env.local`
- Cloud secret sync helper: `agents/main-bot/scripts/sync_cloud_secrets.py`

## Required first checks

Before making cloud changes:

1. Read root `AGENTS.md`.
2. Read this folder.
3. Run `lk docs --help`.
4. Fetch or search the latest official LiveKit docs with `lk docs`, because LiveKit changes quickly.
5. Run read-only inspection commands before write commands.

Useful read-only commands:

```bash
cd /Users/romangarkun/Documents/Проекты/LiveKit/agents/main-bot
lk project list
lk agent status
lk agent versions
lk agent secrets
lk sip inbound list
lk sip outbound list
lk sip dispatch list
lk number list
lk room list
lk ingress list
lk egress list
```

## Canonical deploy flow

Use the repository's existing workflow unless the task explicitly requires something else:

```bash
cd /Users/romangarkun/Documents/Проекты/LiveKit/agents/main-bot
uv run python scripts/sync_cloud_secrets.py --env-file .env.local
lk agent deploy
lk agent status
```

The Cloud deploy flow includes env sync: update LiveKit Cloud secrets from the
env file before every `lk agent deploy`. The helper script is
`agents/main-bot/scripts/sync_cloud_secrets.py`; it uploads non-empty keys but
filters out LiveKit connection credentials (`LIVEKIT_URL`, `LIVEKIT_API_KEY`,
`LIVEKIT_API_SECRET`) and local proxy routing.

Cloud env must not contain service proxy routing. Do not sync local proxy keys
such as `EGRESS_PROXY_URL`, `AGENT_EXTERNAL_HTTP_PROXY`, `HTTP_PROXY`,
`HTTPS_PROXY`, `ALL_PROXY`, or provider flags like `ELEVENLABS_EGRESS=proxy`,
`GEMINI_EGRESS=proxy`, `GOOGLE_TTS_EGRESS=proxy`, `VERTEX_TTS_EGRESS=proxy`,
`GOOGLE_STT_EGRESS=proxy`, `XAI_EGRESS=proxy`, and
`LIVEKIT_INFERENCE_EGRESS=proxy`.

If the source env file also contains a local-only proxy key that the script does
not know yet, remove that key from the Cloud source file or pass
`--exclude <KEY>` when syncing secrets.

For local/self-hosted deploys, keep the provider proxy route explicit in the
local production env: `EGRESS_PROXY_URL=...`, `EGRESS_DEFAULT=direct`, and the
services that need the VPS route set to `<PROVIDER>_EGRESS=proxy`.

For diagnostics after deploy:

```bash
lk agent logs --log-type deploy
lk agent logs --log-type build
```

## LiveKit docs used for this runbook

Checked with `lk docs` on 2026-04-24:

- `/intro/cloud.md`
- `/intro/basics/cli.md`
- `/deploy/agents.md`
- `/reference/developer-tools/livekit-cli/agent.md`
- `/deploy/agents/secrets.md`
- `/deploy/agents/logs.md`
- `/deploy/observability/insights.md`
- `/telephony.md`
- `/telephony/accepting-calls/inbound-trunk.md`
- `/telephony/accepting-calls/dispatch-rule.md`
- `/telephony/making-calls/outbound-trunk.md`
- `/frontends/reference/tokens-grants.md`
- `/reference/other/roomservice-api.md`
- `/transport/media/ingress-egress/egress.md`
- `/transport/media/ingress-egress/ingress.md`

Note: local `lk` is version `2.16.0`. During docs fetch, CLI warned that the docs server is version `1.4.0` while this CLI was built for `1.3.x`; update `lk` if docs behavior looks inconsistent.
