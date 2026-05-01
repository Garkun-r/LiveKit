# Voice fallback architecture decisions

This document records the agreed architecture decisions before changing the
runtime fallback code for the LiveKit voice agent.

Current status: production provider/model/tuning settings are moving to
Directus. Env variables in this document are retained as legacy fallback names
and examples; the active source of truth for LLM fallback is the selected
Directus LLM profile.

## General goal

- Final goal: implement LLM fallback, then verify and test it locally.
- Priority: balance stability and low latency, with latency being critical for
  live voice calls.
- The system must not leave the caller in long silence.
- All timeout and retry values must live in Directus LLM profiles or legacy
  config/env fallback, not as hardcoded runtime constants.

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

Recommended initial defaults, now stored in each Directus LLM profile:

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

Directus field mapping:

- `fallback_provider` replaces `FAST_LLM_BACKUP_PROVIDER` /
  `COMPLEX_LLM_BACKUP_PROVIDER` for the selected route profile.
- `fallback_model` replaces `FAST_LLM_BACKUP_MODEL` /
  `COMPLEX_LLM_BACKUP_MODEL`.
- `use_livekit_fallback_adapter` replaces `USE_LIVEKIT_FALLBACK_ADAPTER`.
- `attempt_timeout_sec`, `max_retry_per_llm`, `retry_interval_sec`, and
  `retry_on_chunk_sent` replace the matching env tuning knobs.

The separate `fallback` profile is legacy/future operational fallback. LLM
backup model selection belongs to the LLM profile itself.

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

Voice prompt catalog:

- `response_delay`: "Секундочку." Plays if the caller finished speaking and the
  assistant stays silent past `VOICE_RESPONSE_DELAY_SEC`.
- `client_silence`: "Алло." Plays if the assistant is listening and the caller
  stays silent past `VOICE_CLIENT_SILENCE_SEC`.
- `emergency`: "Извините, перезвоните ещё раз." Plays for unrecoverable runtime
  errors.
- Future prompts: `tool_wait`, `transfer`, and `farewell` are reserved for
  explicit business triggers, but must not be wired until those flows exist.

Requirements:

- Voice prompts must use pre-synthesized/prerecorded audio files from
  `agents/main-bot/audio`, with paths configurable through env.
- Technical prompts must not be added to LLM chat context.
- Only one technical prompt may play at a time. New user speech cancels pending
  prompt timers and stops active short prompts.
- Do not blindly start a parallel `generate_reply` to cover silence; use audio
  prompts for perceived latency and keep `REPLY_WATCHDOG_SEC` as a later recovery
  path for stuck scheduling.

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

- The response-delay prompt timer starts when the caller stops speaking, using
  `user_state_changed: speaking -> listening`.
- If the assistant starts speaking before the timer fires, the prompt is skipped.
- If the timer fires while the assistant is still silent/thinking, play
  `response_delay` through LiveKit `BackgroundAudioPlayer` on-demand playback.
- The assistant TTS pipeline must wait for an active technical prompt to finish
  before releasing the normal answer, so prompt audio and assistant audio do not
  overlap.
- The client-silence prompt starts only while the assistant is listening and no
  `end_call` is scheduled.

## Future tool prompts

- Tool prompts must be explicit business triggers, not a blanket rule for every
  function call.
- A future long-running tool should call the shared voice-prompt manager before
  the slow operation if the business flow requires "Проверяю информацию."
- If an LLM-generated pre-tool phrase already played, the tool path should use
  `ctx.wait_for_playout()` and avoid a duplicate prerecorded prompt.

## Future implementation plan

1. Make a minimal, safe LLM fallback refactor first.
2. Preserve fast/complex routing.
3. Preserve prompt assembly.
4. Preserve current business logic.
5. Replace only the model substitution/fallback mechanism.
6. Move timeout/retry settings to Directus LLM profiles, with env kept only as
   legacy fallback.
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
- Which STT to use as backup for Deepgram Nova 3.
- Whether to connect MiniMax TTS fallback in the first refactor or as a separate
  stage.
- Whether a feature flag is needed for quick rollback to the old fallback
  scheme.
- Whether old env variables must be preserved for backward compatibility.
- Safe Gemini fallback behavior after tool-call history, especially when the
  previous model/provider was xAI.
