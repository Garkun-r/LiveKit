# Слепок текущей LiveKit-системы

Дата слепка: 2026-05-08.

Этот документ можно целиком отправить сотруднику или загрузить в нейросеть как
контекст для обсуждения текущей архитектуры. Он описывает фактическую систему
по текущему checkout репозитория, без секретов и без содержимого `.env.local`.

Важное ограничение: production Directus может содержать более свежие runtime и
project overrides. Ниже раздел "Текущие профили" основан на
`agents/main-bot/config/robot_settings_snapshot.json`, то есть на локальном
non-secret snapshot для cold start.

## Как Использовать С Нейросетью

Можно начать с такого запроса:

```text
Изучи этот слепок LiveKit-системы. Объясни мне простыми словами, как сейчас
работает звонок от входящего SIP до ответа робота, какие настройки берутся из
Directus, где менять LLM/TTS/STT, какие есть fallback и диагностика, и какие
файлы надо читать перед изменениями.
```

Если нужно разбирать конкретную проблему, добавляйте:

```text
Опирайся только на этот слепок. Если информации недостаточно, скажи, какие
файлы или логи нужно открыть. Не предлагай менять prompt, если проблема не про
prompt.
```

## Короткая Картина

Это монорепозиторий для LiveKit voice agents. Сейчас основной рабочий агент один:

```text
agents/main-bot
```

Главная точка входа:

```text
agents/main-bot/src/agent.py
```

Агент обслуживает realtime voice pipeline:

```text
SIP/LiveKit room
  -> LiveKit AgentServer job
  -> resolve SIP DID and caller
  -> resolve prompt from Directus or file fallback
  -> resolve robot settings from Directus or snapshot/env fallback
  -> build STT + LLM + TTS + turn handling
  -> run AgentSession
  -> export session to Directus and optionally n8n
  -> write incidents to Directus/Postgres through shared incident contract
```

## Главные Файлы

```text
README.md                                      repo overview
AGENTS.md                                     правила работы с проектом
agents/main-bot/src/agent.py                  основной LiveKit agent runtime
agents/main-bot/src/config.py                 env defaults and legacy fallbacks
agents/main-bot/src/robot_settings.py         Directus/snapshot settings resolver
agents/main-bot/src/prompt_repo.py            Directus prompt resolver and cache
agents/main-bot/src/routing/model_router.py   fast/complex LLM router
agents/main-bot/src/routing/model_router_config.yaml
agents/main-bot/src/egress.py                 per-provider direct/proxy routing
agents/main-bot/src/incident_logger.py        robot incident logging contract
agents/main-bot/src/session_export.py         call session export
agents/main-bot/src/robot_tags.py             hidden tag parser/sanitizer
agents/main-bot/src/robot_skills.py           tag action runtime/placeholders
agents/main-bot/config/robot_settings_snapshot.json
agents/main-bot/.env.example                  bootstrap env example
agents/main-bot/env/*.env.example             mac/cloud/asterisk env profiles
agents/main-bot/livekit.toml                  LiveKit Cloud project/agent config
agents/main-bot/Dockerfile                    Cloud/container image
shared/webhooks/codex_diagnostics.py          post-call Codex diagnostic worker
docs/robot-settings-directus.md               Directus settings model
docs/robot-diagnostics.md                     incident logging contract
docs/codex-call-diagnostics.md                post-call Codex diagnostics
docs/deployment-profiles.md                   mac/cloud/asterisk env profiles
docs/local-livekit-server.md                  local Asterisk/LiveKit runbook
docs/cloud/README.md                          LiveKit Cloud runbook
```

## Runtime Entry Flow

`agent.py` loads `.env.local`, constructs an `AgentServer`, prewarms Silero VAD,
and registers:

```python
@server.rtc_session(agent_name=AGENT_NAME)
async def my_agent(ctx: JobContext):
    ...
```

For each LiveKit job:

1. `ctx.connect()` joins the room.
2. `ctx.wait_for_participant()` waits briefly for the SIP/user participant.
3. SIP attributes are parsed into:
   - `sip_trunk_number` / DID;
   - `gateway_number`;
   - `sip_client_number`;
   - trace and SIP call identifiers for diagnostics.
4. `resolve_prompt_for_call()` builds the LLM instructions.
5. `resolve_robot_settings_for_call()` resolves component profiles.
6. The agent builds LLM, STT, TTS, turn handling, fallback, voice prompts, and
   incident logger.
7. `AgentSession.start()` starts realtime STT -> LLM -> TTS.
8. Initial greeting is played from prerecorded/cache audio when available, or
   generated through TTS as fallback.
9. Event handlers collect transcript, metrics, usage, tag events, close reason,
   slow-response incidents, provider fallback incidents, and session errors.
10. On close/cancel/error, session data is exported and incident writes are
    drained best-effort.

## Settings Model

Runtime env is the bootstrap layer. It keeps:

- LiveKit connection and `AGENT_NAME`;
- Directus URL/token and request timeouts;
- provider credentials via env names;
- egress route defaults;
- n8n/session export settings;
- incident logging settings;
- safety knobs such as prerecorded audio, watchdog, health port.

Provider/model/tuning selection should normally come from Directus component
profiles, not active env variables. The old env variables still exist in
`config.py` as fallbacks for tests and cold start.

Settings resolution order per call:

```text
project by DID -> runtime profile by ROBOT_RUNTIME_PROFILE -> base
```

If Directus is unavailable:

```text
last in-memory cache -> config/robot_settings_snapshot.json -> legacy env defaults
```

Snapshot does not contain secrets. It contains component profiles, runtime
profiles, project profiles, bindings, and UI field metadata.

## Текущие Профили В Snapshot

Snapshot has no project profiles. Runtime bindings currently are:

```text
runtime=base
  llm.primary        -> llm_gemini
  llm_routing.fast  -> llm_xai
  llm_routing.complex -> llm_gemini
  stt.primary        -> stt_deepgram_flux_multilingual_direct
  tts.primary        -> tts_elevenlabs_v3
  turn.selected      -> turn_fast_phone

runtime=asterisk
  llm.primary        -> llm_xai_proxy
  llm_routing.fast  -> llm_xai_proxy
  llm_routing.complex -> llm_xai_proxy
  stt.primary        -> stt_yandex_ru
  tts.primary        -> tts_tbank_ru
```

Important profile values from snapshot:

```text
llm_gemini
  provider: google
  model: gemini-3-flash-preview
  fallback: google / gemini-3.1-flash-lite-preview
  use_livekit_fallback_adapter: true
  attempt_timeout_sec: 2.5

llm_xai
  provider: xai
  model: grok-4-1-fast-non-reasoning-latest
  tools disabled
  fallback: google / gemini-3.1-flash-lite-preview
  use_livekit_fallback_adapter: true

stt_deepgram_flux_multilingual_direct
  provider: deepgram
  model: flux-general-multi
  language: ru
  api_version: v2
  eot_threshold: 0.7
  eot_timeout_ms: 5000

stt_yandex_ru
  provider: yandex
  model: general
  language: ru-RU
  chunk_ms: 50
  eou_sensitivity: high

tts_elevenlabs_v3
  provider: elevenlabs
  model: eleven_v3
  output_format: pcm_24000
  voice_id is non-secret profile metadata
  custom HTTP stream path enabled

tts_tbank_ru
  provider: tbank
  voice_name: anna
  format: linear16
  sample_rate: 24000

turn_fast_phone
  detection_mode: vad
  endpointing_mode: fixed
  min_endpointing_delay: 0.25
  max_endpointing_delay: 0.5
  preemptive_generation: true
  early_interim_final_enabled: true
  early_interim_final_delay_sec: 0.15
```

Production Directus may override these by DID/project.

## Prompt Resolution

Prompt logic is in `prompt_repo.py`.

Resolution:

```text
SIP DID / trunk number
  -> Directus client_prompt_cache if fresh
  -> build live prompt from Directus collections
  -> save prompt cache best-effort
  -> render current_datetime block
  -> fallback to src/prompt.txt if missing/error
```

Directus prompt sources include:

- caller mapping collection;
- bot configuration;
- client row;
- client prompt blocks;
- web parsing text;
- transfer number rows;
- client-specific initial greeting.

Rendered prompt includes a timezone-aware current datetime block. This is the
source of truth for words like "сегодня", "завтра", "сейчас".

If prompt lookup fails, the call continues with file prompt and writes
`prompt_lookup_failed` incident.

## LLM Pipeline

Supported LLM providers in code:

```text
google -> direct Gemini API through livekit.plugins.google.LLM with patched GenAI client
xai    -> livekit.plugins.xai.responses.LLM
```

The agent can run in two modes:

1. Single LLM flow via `llm.primary`.
2. Routed flow via `llm_routing.fast` and `llm_routing.complex`.

Routing is rule-based in `model_router_config.yaml`:

- exact short phrases like "да", "алло", "здравствуйте" route to fast;
- words around operator/manager/specialist route to fast;
- otherwise complex.

The router can also respect a `fast_model` flag in message `extra`.

Fallback:

- preferred current profile path uses LiveKit `FallbackAdapter` if
  `use_livekit_fallback_adapter=true`;
- legacy manual path still exists and retries first-token timeout before
  switching to fallback;
- fallback events are logged as `provider_fallback`.

xAI tools are disabled by default to avoid Responses API tool coupling errors
and reduce first-token latency.

## STT Pipeline

Supported STT providers:

```text
deepgram  -> Deepgram plugin or custom Flux v2 WebSocket path
inference -> LiveKit inference STT, with optional Google/inference fallback chain
google    -> Google Cloud STT
yandex    -> custom Yandex SpeechKit gRPC streaming
tbank     -> custom T-Bank VoiceKit gRPC streaming
```

`build_stt()` wraps the final STT object with `EarlyInterimFinalSTT` when
enabled. That wrapper uses local VAD end-of-speech and stable interim text to
emit a synthetic final transcript if the provider is slow to finalize.

The preferred turn detection in the current snapshot is VAD. The code warns
against `turn_detection="stt"` with Google STT because it can break multi-turn
behavior.

## TTS Pipeline

Supported TTS providers:

```text
elevenlabs -> official plugin or custom eleven_v3 HTTP streaming adapter
google     -> livekit.plugins.google.TTS / Google Cloud TTS
vertex     -> custom Vertex Gemini streaming TTS path
minimax    -> LiveKit MiniMax plugin path with project patching
cosyvoice  -> custom Alibaba CosyVoice WebSocket path
tbank      -> custom T-Bank VoiceKit gRPC streaming TTS
sber       -> custom Sber SaluteSpeech gRPC streaming TTS
```

TTS text is sanitized before synthesis so hidden service tags like
`[STATUS: END]` are not spoken.

`VoiceAudioCache` caches short voice prompts by TTS profile identity. It is used
for:

- initial greeting;
- short greeting follow-up;
- response delay filler;
- client silence prompt;
- emergency fallback phrase.

If cached/generated audio is unavailable, the agent falls back to TTS where it
is safe to do so.

## Turn Handling And Voice Guards

Current behavior:

- Silero VAD is loaded in `prewarm()`;
- turn detection can be `vad`, `stt`, `manual`, or multilingual model;
- endpointing can be `fixed` or `dynamic`;
- preemptive generation can be enabled;
- `REPLY_WATCHDOG_SEC` can force a safety reply if no assistant response appears
  after a final transcript;
- response-delay audio can start after user transcript if the bot is slow;
- client-silence audio can say a short "Алло." after inactivity, repeat once,
  then quietly delete the room if STT still has no final caller text; VAD-only
  noise pauses playback but does not reset the silence sequence;
- unrecoverable errors attempt emergency audio/phrase and may end the call.

Short first user greetings like "алло", "здравствуйте", "добрый день" are
recognized and can trigger prerecorded/cache follow-up audio instead of a full
LLM response.

## Hidden Tags And Skills

The LLM may emit hidden action tags. They are removed from TTS and visible
transcriptions by `robot_tags.py`.

Supported tags:

```text
[STATUS: END]
[STATUS: SPAM]
[STATUS: INFO_CLOSE]
[STATUS: LEAD]
[STATUS: SMS_LINK]
[TRANSFER: ID]
[GEO_SEARCH: city, object/street]
```

Rules:

- all square-bracketed segments are hidden from client audio/text;
- first valid action tag wins;
- if clean text before the tag ends with `?`, the action is ignored;
- if the client interrupted the robot, the action is ignored;
- all tag decisions are exported in `tag_events`.

Current implemented side effects:

- `STATUS END/SPAM/INFO_CLOSE/LEAD` schedule room deletion/end call;
- `SMS_LINK`, `TRANSFER`, and `GEO_SEARCH` are placeholders only and just record
  structured events.

Before implementing real SMS, transfer, or geo behavior, read
`docs/robot-tags-and-skills.md` and `docs/robot-diagnostics.md`.

## Session Export

At the end of the call, `session_export.py` sends payload to:

1. Directus collection `robot_call_sessions`;
2. n8n webhook if `N8N_WEBHOOK_URL` is configured.

Payload includes:

- agent name, room name, start/end/duration;
- close reason/error;
- SIP numbers and prompt source;
- transcript items;
- tag events;
- usage and metrics;
- component metrics;
- summary counts.

Directus export is best-effort. n8n export is also best-effort and logs
`n8n_export_failed` if it fails or times out.

## Incident Logging

Incident contract is in `incident_logger.py` and `docs/robot-diagnostics.md`.

Production path writes to Directus API collection `robot_incidents`. Direct
Postgres transport exists only for dev/fallback.

Current incident types include:

```text
prompt_lookup_failed
session_start_failed
agent_session_error
provider_fallback
slow_response
reply_watchdog_fired
tool_failed
abnormal_close
n8n_export_failed
```

The logger redacts obvious secret-like values, but code should still never put
tokens, API keys, authorization headers, or full secret config into payloads.

Any new provider/plugin/tool should use this shared logger instead of inventing
a separate table or log format.

## Post-call Codex Diagnostics

`shared/webhooks/codex_diagnostics.py` is a separate diagnostic worker. It does
not change realtime call behavior.

Flow:

```text
n8n aftercall payload
  -> diagnostic worker /aftercall or /manual
  -> Directus robot_diagnostic_rules
  -> related robot_incidents
  -> read-only LiveKit CLI snapshot
  -> prompt context from Directus cache when available
  -> codex exec in read-only ephemeral sandbox
  -> Directus robot_call_audits
  -> optional Telegram brief through n8n
```

The worker is diagnostic-only. It must not edit code, prompts, Directus
settings, LiveKit resources, or deploy anything.

## Egress Routing

No global proxy should be used for the agent. Provider network route is chosen
through `egress.py`.

Modes:

```text
direct
proxy
```

Common helpers:

```text
provider_proxy_url(provider)
httpx_client_args(provider)
create_external_aiohttp_session(provider)
provider_egress_env(provider)
```

Directus component profiles may override egress with `config_json.egress`.
Otherwise env defaults like `GEMINI_EGRESS`, `DEEPGRAM_EGRESS`, and
`LIVEKIT_INFERENCE_EGRESS` are used.

Do not add a new proxy subsystem for a provider. Extend `egress.py` only when a
new provider needs a stable default or alias.

## Deployment Profiles

One codebase supports three runtime profiles:

```text
mac      local development and console testing
cloud    LiveKit Cloud deployed agent
asterisk self-hosted LiveKit on the Asterisk server
```

Env files are built from:

```text
agents/main-bot/env/common.env.example
agents/main-bot/env/<profile>.env.example
ignored env/<profile>.secrets.env
```

Build examples:

```console
cd agents/main-bot
uv run python scripts/build_env.py --profile mac --secrets env/mac.secrets.env --output .env.local
uv run python scripts/build_env.py --profile cloud --secrets env/cloud.secrets.env --output .env.cloud.local
uv run python scripts/build_env.py --profile asterisk --secrets env/asterisk.secrets.env --output /tmp/main-bot.env
```

Cloud deploy flow:

```console
cd agents/main-bot
uv run python scripts/build_env.py --profile cloud --secrets env/cloud.secrets.env --output .env.cloud.local
uv run python scripts/sync_cloud_secrets.py --env-file .env.cloud.local
lk agent deploy
```

Local console test:

```console
cd agents/main-bot
uv run src/agent.py console
```

Before LiveKit Cloud operations, read `docs/cloud/README.md` and use latest
LiveKit docs through `lk docs`.

## What To Change Where

Use this map for common work:

```text
Change voice/LLM/STT/TTS choice for runtime/client
  -> Directus profiles/bindings first
  -> then update snapshot if cold-start fallback must match

Add provider tuning field
  -> Directus field catalog/schema if needed
  -> component profile config_json
  -> build_* function in agent.py
  -> tests for config/profile behavior

Add new provider
  -> agent.py builder or separate provider module
  -> egress.py route/default/aliases
  -> .env.example and env profiles for credential refs and egress
  -> incident_logger usage for failures
  -> tests

Change prompt content or client knowledge
  -> Directus prompt/client collections
  -> not src/prompt.txt, unless intentionally changing file fallback

Change hidden tag behavior
  -> robot_tags.py for parsing/sanitizing
  -> robot_skills.py for side effects
  -> docs/robot-tags-and-skills.md
  -> tests

Change post-call diagnostics
  -> shared/webhooks/codex_diagnostics.py
  -> docs/codex-call-diagnostics.md
  -> schema robot_codex_diagnostics*.sql if Directus tables change
```

## Safety Rules For New Work

- Do not store secrets in code, docs, snapshot, Directus profiles, or tests.
- Do not change `AGENT_NAME` without matching SIP dispatch/routing changes.
- Do not edit robot prompt/system prompt during diagnostics unless explicitly
  requested.
- Do not add a separate error table/log format; use `IncidentLogger`.
- Do not change startup, room join, media callbacks, turn handling, or timing
  code casually. This is a realtime voice system.
- Keep changes small and verify imports/startup/session flow after edits.
- For LiveKit API changes, check current official docs with `lk docs`.

## Good First Questions For A New Engineer

1. Which runtime is active for the issue: `base`, `mac`, or `asterisk`?
2. Which DID/project was used, and did Directus override the base runtime?
3. What prompt source was logged: Directus cache, Directus live, or file?
4. Which exact STT/LLM/TTS profiles were resolved?
5. Did any `provider_fallback`, `slow_response`, `reply_watchdog_fired`, or
   `agent_session_error` incident appear?
6. Did hidden tags appear in `tag_events`, and were they selected or ignored?
7. Did session export reach Directus/n8n?
8. Is the problem in realtime call flow, Directus settings, prompt content,
   provider credentials, egress routing, or post-call diagnostics?
