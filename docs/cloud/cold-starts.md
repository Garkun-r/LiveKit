# Agent sleep and cold starts

Last reviewed: 2026-04-24.

## Summary

The current cloud agent can show `Sleeping` because LiveKit Cloud may scale deployed agents down to zero replicas on the Build plan after all active sessions end. This is expected platform behavior, not a project bug.

LiveKit docs state that Build plan projects might shut deployed agents down after active sessions end. The agent starts again when a new session begins, which can add about 10 to 20 seconds before the agent joins the room.

## Current project state

Read-only check on 2026-04-24:

- Agent ID: `CA_oaEZ279sgQGr`
- Region: `eu-central`
- Version: `v20260421162443`
- Status: `Sleeping`
- Replicas: `0 / 1 / 1`

This matches the documented cold-start behavior.

## Code-level latency checks

The project already avoids several common cold-start penalties:

- `agents/main-bot/Dockerfile` runs `uv run "src/agent.py" download-files` during image build, so required model files are not downloaded at runtime.
- `src/agent.py` uses `server.setup_fnc = prewarm` to load Silero VAD when the worker starts.
- The first greeting uses prerecorded audio files from `agents/main-bot/audio`, so the initial greeting does not need a first LLM/TTS round trip unless playback fails.
- Runtime LLM/TTS warmup runs after room connection and is bounded so it should not block call flow for long.

These optimizations do not prevent Cloud scale-to-zero. They only reduce latency after the cloud worker starts.

## Ways to reduce perceived delay

No-cost options:

- For development and repeated testing, run a local worker and keep it alive:

```bash
cd /Users/romangarkun/Documents/Проекты/LiveKit/agents/main-bot
UV_CACHE_DIR=/tmp/uv-cache uv run src/agent.py dev
```

- For terminal-only behavior tests, use console mode:

```bash
cd /Users/romangarkun/Documents/Проекты/LiveKit/agents/main-bot
UV_CACHE_DIR=/tmp/uv-cache uv run src/agent.py console
```

- For frontend/mobile clients, enable LiveKit instant connect / pre-connect audio so the user can start speaking while the agent connection is still being established.

Paid / plan-dependent options:

- Upgrade off the free Build plan if always-on or lower cold-start behavior is required.
- Check LiveKit Cloud Dashboard project limits and plan features. Current public docs say cold starts are specifically a Build-plan behavior and paid plans provide additional deployment features such as instant rollback. Exact always-on behavior should be confirmed in the dashboard or with LiveKit support for the selected plan.

## What not to do

- Do not try to keep the agent warm by repeatedly creating fake rooms or sessions. That can create unnecessary usage and may conflict with billing rules.
- Do not remove shutdown/cleanup logic just to keep sessions open. Billing for deployed agents starts after the agent connects to the room and stops when the room ends or the agent disconnects.

## Docs checked

- `/deploy/agents/managing-deployments.md`
- `/deploy/admin/quotas-and-limits.md`
- `/deploy/admin/billing.md`
- `/agents/build/audio.md`
- `/agents/logic-structure/sessions.md`
