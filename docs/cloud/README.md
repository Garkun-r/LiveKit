# LiveKit Cloud documentation

Last reviewed: 2026-04-24 11:25:02 +07.

This folder is the project runbook for LiveKit Cloud work. Read it before touching cloud deployment, secrets, telephony, rooms, ingress, egress, or agent observability.

## Files

- [assistant-cloud-playbook.md](assistant-cloud-playbook.md): what Codex can manage in LiveKit Cloud, required access, safety rules, and standard commands.
- [current-cloud-state.md](current-cloud-state.md): read-only snapshot of the current LiveKit Cloud project and agent configuration.
- [cold-starts.md](cold-starts.md): why the cloud agent can show `Sleeping`, what causes test delays, and what can reduce them.

## Project entrypoints

- Repository root: `/Users/romangarkun/Documents/LiveKit`
- Main agent directory: `/Users/romangarkun/Documents/LiveKit/agents/main-bot`
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
cd /Users/romangarkun/Documents/LiveKit/agents/main-bot
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
cd /Users/romangarkun/Documents/LiveKit/agents/main-bot
uv run python scripts/sync_cloud_secrets.py --env-file .env.local
lk agent deploy
lk agent status
```

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
