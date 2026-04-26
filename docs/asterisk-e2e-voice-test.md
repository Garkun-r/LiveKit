# Asterisk E2E Voice Test

This runbook describes the reproducible SIP/Asterisk test for the LiveKit
voice agent with prerecorded user audio. It uses the existing Asterisk latency
test dialplan and does not change production routing.

## Purpose

Use this test after voice pipeline changes to verify the real path:

```text
Asterisk test context -> LiveKit SIP trunk -> LiveKit room -> main-bot agent
```

The current test audio says "подскажите адрес" and later "нет спасибо". The
expected normal result is:

- the call reaches LiveKit through the `livekit` SIP endpoint;
- the agent receives and transcribes both user phrases;
- the router logs the selected LLM branch (`fast` or `complex`);
- normal primary LLM is used, with no fallback event unless a fault is injected;
- the watchdog does not create duplicate replies;
- no STT, LLM, TTS, SIP, or LiveKit session error is logged.

Known provider constraint:

- Gemini rejects HTTP deadlines below 10 seconds. Keep
  `GEMINI_HTTP_TIMEOUT_SEC=10.0` or higher for this test. This is separate from
  the LiveKit fallback attempt target.

## Existing Asterisk Test Route

The server-side test route already exists in Asterisk:

- Context: `lk-start`
- Extension: `312388`
- After-answer subroutine: `lk-after-answer`
- LiveKit endpoint: `PJSIP/312388@livekit`
- Test audio playback: `Playback(custom/ask_address)`
- Recording prefix: `/var/spool/asterisk/monitor/lk-test-`

Current test audio on the Asterisk server:

```text
/var/lib/asterisk/sounds/custom/ask_address.wav
```

Known format from the server:

- WAV / RIFF
- PCM signed 16-bit little-endian
- mono
- 8000 Hz
- duration: about 31.104 seconds

Do not delete, overwrite, or regenerate this file from this repository.

## Preflight

Start the local agent so the current working tree can accept LiveKit dispatches:

```bash
cd agents/main-bot
uv run python src/agent.py dev 2>&1 | tee ../../logs/livekit-agent-e2e-$(date +%Y%m%d-%H%M%S).log
```

In another terminal, run a dry-run check:

```bash
cd /Users/romangarkun/Documents/Проекты/LiveKit
agents/main-bot/scripts/run_asterisk_audio_e2e_test.sh --dry-run
```

The dry run verifies:

- SSH access to Asterisk;
- Asterisk active channel count;
- `312388@lk-start`;
- `s@lk-after-answer`;
- the prerecorded audio file path and format.

## Run The Test

Run one test call only:

```bash
cd /Users/romangarkun/Documents/Проекты/LiveKit
agents/main-bot/scripts/run_asterisk_audio_e2e_test.sh --run | tee logs/asterisk-e2e-$(date +%Y%m%d-%H%M%S).log
```

The script originates:

```text
Local/312388@lk-start
```

It refuses to run if Asterisk already has active calls unless
`ALLOW_ACTIVE_CALLS=1` is set explicitly.

## Logs To Inspect

Asterisk:

```bash
ssh -p 39001 root@87.226.145.66 'tail -n 200 /var/log/asterisk/messages.log'
ssh -p 39001 root@87.226.145.66 'ls -lt /var/spool/asterisk/monitor/lk-test-* | head'
```

LiveKit local agent log markers:

- `room connected`
- `participant connected`
- `user_input_transcribed`
- `[MODEL_ROUTER] selected_model="fast|complex"`
- `llm fallback adapter configured`
- `llm availability changed`
- `reply watchdog fired`
- `reply watchdog skipped`
- `agent session error`
- `metrics_collected`

The current implementation logs `chunk_sent` as `null` for
`llm_availability_changed` because the installed LiveKit event does not expose a
chunk-sent flag.

## Success Criteria

- Asterisk originates exactly one test call through `lk-start`.
- LiveKit creates one room for the SIP participant.
- The transcript contains "подскажите адрес".
- The agent answers with the configured address information.
- The transcript contains "нет спасибо".
- The agent does not produce duplicate or competing replies.
- No normal-path LLM fallback occurs.
- Watchdog does not fire during normal primary-model response, or if it fires,
  it does not create a second LLM reply.
- Asterisk records are created under `/var/spool/asterisk/monitor/lk-test-*`.

## Problem Signals

- `core show channels count` is non-zero before the test.
- `312388@lk-start` or `s@lk-after-answer` is missing.
- `ask_address.wav` is missing or not 8 kHz mono WAV.
- The local agent does not log room/participant connection.
- The transcript misses either phrase.
- `agent session error` logs unrecoverable STT, LLM, TTS, or SIP errors.
- `reply watchdog fired` is followed by duplicate assistant replies.
- `llm availability changed` appears during the normal no-fault test.
- `end_call` causes a second `[MODEL_ROUTER]` pass for the same user transcript.
  Terminal tools should stop tool-reply continuation with LiveKit `StopResponse`.
- Gemini backup fails with a `thought_signature` error after a non-terminal tool
  call exists in chat history. This indicates the fallback crossed an unsafe
  tool-call context and should be handled in the tools refactor before
  production.

## LLM Fallback Test

Only run fallback fault injection in a local/test environment. Do not change
LiveKit Cloud secrets or production Asterisk config for this.

Safe options:

- run the local agent with temporary local env overrides for the primary model;
- keep backup model envs pointed at the known Gemini backup;
- use the same `lk-start` Asterisk test call;
- restore the local env immediately after the test.

Example shape:

```bash
cd agents/main-bot
FAST_LLM_PROVIDER=xai \
FAST_LLM_BACKUP_PROVIDER=google \
COMPLEX_LLM_PROVIDER=google \
COMPLEX_LLM_BACKUP_PROVIDER=google \
USE_LIVEKIT_FALLBACK_ADAPTER=true \
uv run python src/agent.py dev
```

Do not invent model IDs in this runbook. Use the current values from
`config.py`, `.env.example`, `.env.local`, or the fallback architecture note.

Expected fallback log markers:

- branch-specific primary and backup models are configured;
- `llm availability changed` identifies the failed branch/provider/model;
- final response comes from that branch's backup model;
- `retry_on_chunk_sent=false` prevents unsafe fallback after a first chunk.

## Rollback

This test does not modify Asterisk config. If local env overrides were used,
close the local agent process and start it again with the normal `.env.local`.
