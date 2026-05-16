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
4. The worker loads matching `robot_incidents` rows by target, call window,
   room, caller, or DID.
5. The worker creates a `robot_call_audits` row.
6. The worker collects a small read-only LiveKit CLI snapshot.
7. The worker reads the matching Directus `robot_call_sessions` row and compact
   `robot_call_raw_logs` rows by `call_session` or `room_name`. This gives
   Codex the runtime chain for the call: prompt resolve, STT/VAD, TTS, user
   state changes, errors, disconnects, and export logs.
8. The worker calculates deterministic `diagnostic_signals`, including
   `short_call_no_dialog`, `no_transcript_items`, `no_tag_events`,
   `user_speech_state_seen`, `initial_greeting_playback_log_seen`,
   `room_seen_in_livekit_snapshot`, and `egress_active_in_livekit_snapshot`.
9. The worker also builds investigation input for Codex:
   `problem_signals`, `evidence_timeline`, and `latency_chains`.
   `problem_signals` names the likely problem classes to investigate.
   `evidence_timeline` is a compact proof chain from raw logs, transcript,
   metrics, tag events, incidents, and LiveKit snapshot. `latency_chains`
   precomputes turn lifecycle steps such as user final transcript, response
   creation, LLM metrics, TTS first audio, playback start, interruption, and
   replacement playback.
10. The worker reads the matching Directus `client_prompt_cache` row by
   DID/trunk and attaches the rendered prompt context to the audit input when
   available. This lets Codex verify facts from client `add_info` and the
   actual cached production prompt, not only `agents/main-bot/src/prompt.txt`.
11. The worker runs:

   ```console
   codex exec --sandbox read-only --ephemeral --json --output-schema shared/webhooks/codex_diagnostics_report.schema.json
   ```

12. The worker writes the full report back to Directus.
13. If the matched rule's `telegram_policy` allows it, the worker calls the n8n
   audit-notification webhook. n8n sends a Russian Telegram brief to the same
   chat and through the same bot/token path as low-score aftercall alerts. The
   brief includes a link to the specific `robot_call_audits` item in Directus
   and an inline button labeled `отправить полный отчет`. The brief also shows
   the call start/end time and, when n8n passes it, a link to the exact
   `AFTER CALL` execution that launched diagnostics. Each top finding must
   name the dialog stage, approximate turn/time, exact tag/value/event when
   relevant, concrete evidence, and an implementation idea.
14. When that button is pressed, n8n receives the Telegram callback, asks the
    worker for the full report by `audit_id`, and sends the full Russian report
    back to the same chat. The full report is chunked for Telegram limits and
    includes the sections for timeline, pauses/delays, errors/incidents,
    anomalies, root-cause analysis, recommendations, implementation ideas,
    missing evidence, and the no-auto-fix guarantee.

## Report Quality Contract

Reports should reduce follow-up questions from a non-technical owner. The first
Telegram message is a short decision brief, not a compressed full report. It
shows the outcome, the top 1-2 issues, the practical action, and one short proof
line. Long evidence, source names, raw metric values, and file paths belong in
the full report opened by the inline button.

```text
Итог:
One plain-language outcome sentence.

Главное:
1. Short title
   Смысл: what happened and what it means.
   Где: dialog stage and approximate turn/time.
   Почему важно: business or UX impact.
   Что сделать: concrete implementation idea.
   Почему верю: one short evidence line from transcript/logs.
```

The full report must still preserve:

- where in the dialog it happened: greeting, qualification, main request,
  closing, or after the conversation looked finished;
- the approximate timestamp/turn and adjacent phrases, especially for pauses;
- the exact object: tag name/value/action, event name, metric, node, code path,
  or "not visible in supplied data";
- the source of truth that was checked: `prompt_context.rendered_prompt`,
  `transcript_items`, `metrics_events`, a specific repo file, or "not available";
- evidence versus inference;
- what evidence is still missing if the cause is uncertain;
- the concrete implementation idea: what to inspect or change next.

Every important finding must include a `root_cause_analysis` object in the
Codex JSON. This is mandatory even when the cause is uncertain. The block must
answer:

- `symptom`: what the owner or client noticed;
- `expected`: what the robot should have done;
- `actual`: what transcript/raw logs/metrics/tag events show happened;
- `chain_break`: the nearest broken point, such as STT, VAD, LLM, TTS,
  interruption, prompt, tag parser, Directus, LiveKit room, n8n export, or
  aftercall;
- `checked_hypotheses`: versions checked with `confirmed`, `rejected`, or
  `uncertain`;
- `root_cause`: the most likely technical cause with evidence;
- `code_or_logic_reference`: the function, file, log message, or "not visible
  in supplied data";
- `what_this_was_not`: likely but rejected causes;
- `evidence_timeline`: short timestamped proof chain;
- `changes_to_make`: concrete action in code, prompt, logging, or settings;
- `missing_evidence`: what must be logged next time if the cause is not fully
  proven.

Symptom-only findings are invalid. If Codex writes "delay", "robot was silent",
"late answer", "client said Алло", "wrong answer", "wrong company name",
"missing tag", "no Codex report", "no raw logs", or "strange close", it must
also explain the nearest technical cause. If the cause cannot be proven, it
must list the checked versions and the missing evidence.

For latency, silence, "Алло", and interruption findings, Codex must inspect
`latency_chains` first. A correct finding should distinguish these cases:

- slow LLM or slow TTS;
- playback started late after audio was ready;
- a reply was generated but canceled before first audio;
- the client spoke over the robot after playback had already started;
- `slow_response` did not fire because the metric was measured from the last
  short "Алло" rather than from the first useful question.

Example mechanism:

```text
Проблема:
Клиент ждал первый полезный ответ.

Почему так произошло:
Робот начал готовить ответ, но клиент сказал "Алло" до первого аудио.
Interruption logic отменил еще не прозвучавший ответ. Потом робот создал новый
ответ и начал говорить через 1.25 сек.

Что это НЕ было:
Это не долгий LLM: LLM ответил за 568 ms.
Это не n8n/export: задержка была внутри live conversation.

Доказательная цепочка:
08:59:28 вопрос клиента
08:59:29 speech created
08:59:29 llm metrics
08:59:30 клиент сказал "Алло"
08:59:31 assistant_interrupted
08:59:32 new_playback_started
```

For example, a tag finding should name the exact tag and explain whether the
current repository logic hides it, ignores it, or still routes it to an action.
If the exact tag is not present in the aftercall payload or logs, the report
must say that explicitly instead of guessing.

For knowledge-base facts, `prompt_context.rendered_prompt` has priority over
the repository fallback prompt. If that context is unavailable, the report must
lower confidence and list the missing prompt context as missing evidence.

For no-dialog or "robot was silent" calls, Codex must not stop at "there is no
transcript". It must inspect `robot_call_sessions`, `robot_call_raw_logs`,
`diagnostic_signals`, and the LiveKit snapshot, then explain:

- what the robot was expected to do first;
- what actually happened in the runtime chain;
- where the chain most likely broke: SIP/room join, prompt resolve, initial
  greeting, STT/VAD, LLM, TTS/playout, tag parser, close, export, or aftercall;
- which logs prove it;
- what is still not provable;
- what instrumentation or implementation change would make the next diagnosis
  conclusive.

TTS warmup is not proof that the caller heard the greeting. If greeting/playout
logs are absent, the report must say whether this is a real absence in runtime
or an instrumentation gap.

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
- `telegram_policy`: `anomaly_brief` always sends a brief, `critical_only`
  sends only for `critical` verdicts, and `silent` writes Directus only.
- `cooldown_sec`: skips new audits for the same rule and target while a recent
  audit is still inside the cooldown window. Exact duplicate calls are also
  skipped by `dedupe_key`.

`robot_call_audits` stores queued/running/completed/failed audit jobs and the
Codex report.

## VPS Secrets

Do not store these in Directus. Put them in the VPS service env file or another
server-side secret store:

```env
CODEX_DIAGNOSTICS_DIRECTUS_URL=https://jcall.io/directus
CODEX_DIAGNOSTICS_DIRECTUS_TOKEN=
# Optional override for the browser UI base. If unset, the worker derives
# https://.../directus/admin/content/robot_call_audits/<id> from DIRECTUS_URL.
CODEX_DIAGNOSTICS_DIRECTUS_APP_URL=https://jcall.io/directus
CODEX_DIAGNOSTICS_N8N_WEBHOOK_URL=
CODEX_DIAGNOSTICS_N8N_WEBHOOK_TOKEN=
CODEX_DIAGNOSTICS_REPO_DIR=/opt/jcall-livekit-agent/source
CODEX_DIAGNOSTICS_CODEX_BIN=codex
CODEX_DIAGNOSTICS_CODEX_TIMEOUT_SEC=900
CODEX_DIAGNOSTICS_RAW_LOG_LIMIT=500
CODEX_DIAGNOSTICS_RAW_LOG_TEXT_MAX_CHARS=1200
# On vm-pico, n8n runs inside the n8n_default Docker network. Bind to that
# bridge gateway so n8n can reach the host worker without exposing it publicly.
CODEX_DIAGNOSTICS_HOST=172.18.0.1
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

# When the worker runs on vm-pico next to n8n/Directus/Codex, use SSH to read
# the local Asterisk LiveKit from the Asterisk host. The remote command reads
# local LiveKit credentials from the Asterisk env file and runs only lk list
# commands.
CODEX_DIAGNOSTICS_LK_LOCAL_SSH_TARGET=root@87.226.145.66
CODEX_DIAGNOSTICS_LK_LOCAL_SSH_PORT=39001
CODEX_DIAGNOSTICS_LK_LOCAL_SSH_KEY=/root/.ssh/id_rsa_n8n
CODEX_DIAGNOSTICS_LK_LOCAL_REMOTE_ENV=/etc/jcall-livekit-agent/main-bot.env
CODEX_DIAGNOSTICS_LK_LOCAL_REMOTE_WORKDIR=/opt/jcall-livekit-agent/source/agents/main-bot
CODEX_DIAGNOSTICS_LK_LOCAL_REMOTE_FALLBACK_WORKDIR=/opt/jcall-livekit-agent/main-bot
CODEX_DIAGNOSTICS_LK_LOCAL_REMOTE_LK_BIN=/usr/local/bin/lk
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
uv run python shared/webhooks/codex_diagnostics.py serve
```

If running outside `agents/main-bot`, use the Python environment that has
`httpx` installed.

One-shot local fixture run:

```console
uv run python ../../shared/webhooks/codex_diagnostics.py aftercall \
  --target cloud \
  --payload-file /tmp/aftercall-payload.json
```

Manual fixture run from `agents/main-bot`:

```console
uv run python ../../shared/webhooks/codex_diagnostics.py manual \
  --target cloud \
  --payload-file /tmp/aftercall-payload.json
```

## n8n Integration

The aftercall workflow should call:

```http
POST http://172.18.0.1:18181/aftercall?target=cloud&async=1
POST http://172.18.0.1:18181/aftercall?target=local&async=1
```

Manual audit jobs use a separate endpoint and only match rules where
`trigger_mode=manual`:

```http
POST http://172.18.0.1:18181/manual?target=cloud&async=1
POST http://172.18.0.1:18181/manual?target=local&async=1
```

Use `async=1` from n8n so the aftercall webhook responds immediately while the
Codex audit continues in the worker background thread. Omit `async=1` only for
local one-shot debugging where it is acceptable to wait for `codex exec`.
The n8n HTTP node should merge execution metadata into the JSON body before
calling the worker:

```json
{
  "...original aftercall payload": "...",
  "codex_diagnostics_aftercall_execution_id": "$execution.id",
  "codex_diagnostics_aftercall_workflow_id": "$workflow.id",
  "codex_diagnostics_aftercall_url": "https://n8n.jcall.io/workflow/<workflowId>/executions/<executionId>"
}
```

This metadata is non-secret and is used only for report links.

Use `target=cloud` for LiveKit Cloud calls and `target=local` for the
self-hosted/Asterisk LiveKit path. This target controls which LiveKit endpoint
the read-only `lk` snapshot uses. Cloud can use either `lk --project ...` or
explicit `CODEX_DIAGNOSTICS_LK_CLOUD_*` credentials. Local can run directly on
the Asterisk host with `CODEX_DIAGNOSTICS_LK_LOCAL_*`; when the worker runs on
vm-pico, set `CODEX_DIAGNOSTICS_LK_LOCAL_SSH_TARGET` so the snapshot is run on
the Asterisk host and reads the existing `LIVEKIT_*` env there.

The worker sends the final Telegram brief to n8n through
`CODEX_DIAGNOSTICS_N8N_WEBHOOK_URL`; Telegram credentials remain owned by n8n.
The full-report button callback is also handled by n8n. n8n should call the
local worker endpoint:

```http
POST http://172.18.0.1:18181/telegram/full-report
Content-Type: application/json

{"audit_id": 123, "chat_id": -100...}
```

The worker returns `messages`, an array of Russian report chunks ready for
Telegram delivery.

## Safety Rules

- The worker must run Codex with `--sandbox read-only --ephemeral`.
- The worker prompt explicitly forbids code edits, prompt edits, deploys, and
  mutating LiveKit commands.
- Call transcripts and logs are treated as untrusted data.
- Directus stores rules and audit results, not API keys or Telegram bot tokens.
- Realtime call behavior must remain unchanged.
