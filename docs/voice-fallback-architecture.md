# Voice fallback architecture decisions

This document records the agreed architecture decisions before changing the
runtime fallback code for the LiveKit voice agent.

## General goal

- Final goal: implement LLM fallback, then verify and test it locally.
- Priority: balance stability and low latency, with latency being critical for
  live voice calls.
- The system must not leave the caller in long silence.
- All timeout and retry values must live in config/env, not as hardcoded runtime
  constants.

## What must not break

Preserve the existing business logic:

- current prompt assembly;
- fast/complex routing;
- light/complex model selection;
- current skills;
- current dialogue handling;
- current integrations;
- current custom ElevenLabs v3 TTS plugin behavior;
- anything that is not directly related to the fallback mechanism.

Allowed future changes:

- only the LLM fallback/model substitution mechanism;
- later, TTS/STT fallback;
- config variables, if old variables no longer match the new architecture.

## Preferred LLM fallback strategy

Fallback must be implemented separately inside each routing branch:

- fast branch: fast primary -> fast backup
- complex branch: complex primary -> complex backup

Do not create one global fallback chain for all requests if that breaks
fast/complex routing. The current fast/complex decision logic must remain in
place. The current manual retry/fallback code may be replaced if the new
implementation preserves the rest of the business logic.

Implementation note: the first refactor keeps `Assistant.llm_node` as the place
where routing and provider-specific tool handling live, and moves the actual
model failover inside branch-local LiveKit `llm.FallbackAdapter` instances. The
rollback flag is `USE_LIVEKIT_FALLBACK_ADAPTER=false`.

## Current models and available providers

Current state:

- Production currently uses Gemini Flash as the primary model.
- xAI is used as the fast model.
- Currently available providers: Gemini/Google and xAI.
- Do not use OpenAI as a backup provider yet, because the appropriate model is
  not confirmed.
- Do not use OpenRouter yet.
- At this stage, backup should use Gemini Lite / Gemini Flash Lite if the
  corresponding model is available in config.

Exact model IDs must come from the current config, `.env.example`, or
`.env.local`. Do not invent model IDs during implementation.

## Tools / function calling

- Current tool calls are not the focus of this task.
- Tool/tool-call architecture is planned as a separate refactor.
- Do not use xAI with enabled tool calls for this fallback task, because it adds
  approximately one second of latency.
- For the xAI fast path, tool calls must remain disabled if the current
  architecture already disables them.
- Codex must not enable tool calls on xAI as part of fallback work.
- Codex must not restructure tools/function calling without a separate task.
- Terminal tools must not trigger an extra LLM continuation. `end_call` uses
  LiveKit `StopResponse` after scheduling call closure so the SDK does not
  create a second tool-reply generation for the same user turn.
- E2E testing on 2026-04-26 showed a production risk when a fast-branch xAI
  timeout falls back to Gemini after non-terminal tool-call history exists:
  Gemini can reject the request with a missing `thought_signature` error. Treat
  cross-provider fallback after future non-terminal tools as not production-ready
  until the planned tools refactor defines a safe context strategy.

## Timeout / retry decisions

Recommended initial defaults, to be exposed through config/env:

```env
USE_LIVEKIT_FALLBACK_ADAPTER=true
LLM_ATTEMPT_TIMEOUT_SEC=2.5
LLM_MAX_RETRY_PER_LLM=0
LLM_RETRY_INTERVAL_SEC=0.3
LLM_RETRY_ON_CHUNK_SENT=false
GEMINI_HTTP_TIMEOUT_SEC=10.0
FAST_LLM_BACKUP_PROVIDER=google
FAST_LLM_BACKUP_MODEL=<from config/env>
COMPLEX_LLM_BACKUP_PROVIDER=google
COMPLEX_LLM_BACKUP_MODEL=<from config/env>
```

For live voice, do not retry the same model before fallback. On timeout,
API error, network error, or provider error, move directly to the backup model.

Provider compatibility note: the installed Gemini client rejects HTTP deadlines
below 10 seconds. Keep `GEMINI_HTTP_TIMEOUT_SEC` at `10.0` or higher even when
the LiveKit fallback attempt target remains around 2.5 seconds.

If a model already started sending chunks and then failed, do not enable unsafe
retry with another model without separate verification. Follow LiveKit behavior
with `retry_on_chunk_sent=false`.

Old variables such as `LLM_FIRST_TOKEN_TIMEOUT_SEC` and
`LLM_FALLBACK_TIMEOUT_SEC` may be replaced with the new variables if that makes
the implementation cleaner.

## Filler/emergency phrases

Allowed phrases:

- "Секундочку, проверяю."
- "Уточняю информацию."
- "Извините, перезвоните ещё раз, вас плохо слышно."

Requirements:

- Provide a mechanism for pre-synthesized/prerecorded audio for filler and
  emergency phrases.
- The user will add the audio files later.
- Future code must support paths to these files through config/env.
- TBD: whether filler phrases should be added to chat context.
- If filler is used only to cover technical delay, prefer not adding it to LLM
  context, but this is not final without separate confirmation.

## TTS fallback

- Primary TTS today: ElevenLabs v3 through the custom plugin.
- Backup TTS candidate: MiniMax, because it has a similar or same voice.
- Keep the fallback voice as similar as possible.
- Runtime TTS fallback is needed, but it may be implemented as a separate stage
  if that reduces risk for the first LLM fallback refactor.
- Emergency prerecorded audio path is still required, because TTS itself can
  fail.

## STT fallback

- Primary STT today: Deepgram Nova 3.
- STT fallback is needed.
- The concrete backup STT is not selected yet.
- Fast backup STT options need to be tested.
- STT fallback may be implemented as a separate stage if that reduces risk for
  the first LLM fallback refactor.

## Watchdog / latency guard

- The exact watchdog implementation is not fixed yet.
- A guard is needed to prevent long silence after the caller speaks.
- The current watchdog must be studied before changes.
- Do not blindly start a parallel `generate_reply` if it can create duplicate
  answers.
- Preferred future approach: on delay, play filler/pre-synthesized audio without
  creating a second competing LLM reply.

## Future implementation plan

1. Make a minimal, safe LLM fallback refactor first.
2. Preserve fast/complex routing.
3. Preserve prompt assembly.
4. Preserve current business logic.
5. Replace only the model substitution/fallback mechanism.
6. Move timeout/retry settings to config/env.
7. Add fallback logging:
   - trace_id / room / call id, if available;
   - branch: fast or complex;
   - primary provider/model;
   - backup provider/model;
   - fallback reason;
   - elapsed_ms before fallback;
   - final provider/model.
8. Add local/fault-injection tests:
   - primary timeout;
   - provider/API error;
   - network error;
   - backup success;
   - all LLM unavailable;
   - failure after first chunk, if testable;
   - fast branch fallback;
   - complex branch fallback.

## TBD

- Exact model IDs for Gemini primary and Gemini Lite backup.
- Whether fast and complex branches need one shared backup or different backup
  models.
- Whether filler phrases should be added to chat context.
- Which STT to use as backup for Deepgram Nova 3.
- Whether to connect MiniMax TTS fallback in the first refactor or as a separate
  stage.
- Whether a feature flag is needed for quick rollback to the old fallback
  scheme.
- Whether old env variables must be preserved for backward compatibility.
- Safe Gemini fallback behavior after tool-call history, especially when the
  previous model/provider was xAI.
