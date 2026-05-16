# JCall LiveKit Main Bot

Production voice agent for inbound SIP calls through LiveKit. The current code
is no longer a vanilla LiveKit starter: it resolves prompts and runtime profiles
from Directus, supports several STT/TTS/LLM providers, records call metadata,
writes per-call raw logs and incidents, and can run in Cloud, Mac, or
self-hosted Asterisk/local LiveKit profiles.

Main runtime files:

- `src/agent.py` - LiveKit entrypoint, session lifecycle, provider builders,
  turn guards, voice prompts, recording and export orchestration.
- `src/config.py` - env bootstrap defaults and legacy fallback values.
- `src/robot_settings.py` - Directus/snapshot runtime profile resolver.
- `src/prompt_repo.py` - Directus prompt assembly and prompt cache.
- `src/incident_logger.py` - shared incident logging contract.
- `src/raw_call_logs.py` - per-call Directus raw log sink.
- `src/recording_export.py` - LiveKit Egress recording indexer.
- `env/*.env.example` - flat env profile templates.

## Using coding agents

This project is designed to work with coding agents like [Claude Code](https://claude.com/product/claude-code), [Cursor](https://www.cursor.com/), and [Codex](https://openai.com/codex/).

For your convenience, LiveKit offers both a CLI and an [MCP server](https://docs.livekit.io/reference/developer-tools/docs-mcp/) that can be used to browse and search its documentation. The [LiveKit CLI](https://docs.livekit.io/intro/basics/cli/) (`lk docs`) works with any coding agent that can run shell commands. Install it for your platform:

**macOS:**

```console
brew install livekit-cli
```

**Linux:**

```console
curl -sSL https://get.livekit.io/cli | bash
```

**Windows:**

```console
winget install LiveKit.LiveKitCLI
```

The `lk docs` subcommand requires version 2.15.0 or higher. Check your version with `lk --version` and update if needed. Once installed, your coding agent can search and browse LiveKit documentation directly from the terminal:

```console
lk docs search "voice agents"
lk docs get-page /agents/start/voice-ai-quickstart
```

See the [Using coding agents](https://docs.livekit.io/intro/coding-agents/) guide for more details, including MCP server setup.

The project includes a complete [AGENTS.md](AGENTS.md) file for these assistants. You can modify this file to suit your needs. To learn more about this file, see [https://agents.md](https://agents.md).

## Dev Setup

Install dependencies from this checked-out agent directory:

```console
cd /Users/romangarkun/Documents/Проекты/LiveKit/agents/main-bot
uv sync
```

Build a local `.env.local` from the shared/profile templates and ignored
secrets:

```console
uv run python scripts/build_env.py --profile mac --secrets env/mac.secrets.env --output .env.local
```

For a one-off local Cloud-connected run you can also copy `.env.example` to
`.env.local` and fill the required keys manually, but do not commit real
secrets.

## Run the agent

Before your first run, download the local model files used by the agent:

```console
uv run python src/agent.py download-files
```

Next, run this command to speak to your agent directly in your terminal:

```console
uv run python src/agent.py console
```

## Environment profiles

This repository uses one agent codebase with separate env profiles for Mac,
LiveKit Cloud, and the self-hosted Asterisk LiveKit server. See
[`../../docs/deployment-profiles.md`](../../docs/deployment-profiles.md) and
[`env/README.md`](env/README.md).

Build the Mac `.env.local` from the shared defaults and local secrets:

```console
uv run python scripts/build_env.py --profile mac --secrets env/mac.secrets.env --output .env.local
```

The Asterisk server already has a production env at
`/etc/jcall-livekit-agent/main-bot.env`. Do not replace it without explicit
approval and a matching SIP dispatch update if `AGENT_NAME` changes.

## Runtime settings source

The production robot reads LLM/TTS/STT/Turn profiles from Directus. Keep
`.env.local` for bootstrap, secrets, Directus access, egress, n8n, incident
logging, health, and audio safety knobs.

Use `ROBOT_RUNTIME_PROFILE=base|asterisk|mac` to select the process runtime.
`base` is the default cloud configuration. For each call the agent resolves
settings in this order:

```text
project by DID -> runtime by ROBOT_RUNTIME_PROFILE -> base
```

Directus is cached in memory by `ROBOT_SETTINGS_CACHE_TTL_SEC`. If Directus is
unavailable, the agent uses the last cache, then
`config/robot_settings_snapshot.json` on cold start. See
[`../../docs/profile-management.md`](../../docs/profile-management.md) for the
operating workflow and
[`../../docs/robot-settings-directus.md`](../../docs/robot-settings-directus.md)
for the storage model and migration rules.

## Provider egress routing

For the self-hosted Asterisk/LiveKit server runbook, see
[`../../docs/local-livekit-server.md`](../../docs/local-livekit-server.md).

The local robot should not use a global `HTTPS_PROXY`. Configure egress per
provider so fast/unblocked providers can go direct and geoblocked providers can
go through the VPS Squid HTTP CONNECT proxy:

```console
EGRESS_PROXY_URL=http://66.248.207.203:15182
EGRESS_DEFAULT=direct

# Current measured defaults for the local Asterisk robot:
ELEVENLABS_EGRESS=proxy
GEMINI_EGRESS=proxy
GOOGLE_TTS_EGRESS=proxy
VERTEX_TTS_EGRESS=proxy
GOOGLE_STT_EGRESS=proxy
XAI_EGRESS=direct
DEEPGRAM_EGRESS=direct
YANDEX_STT_EGRESS=direct
TBANK_VOICEKIT_EGRESS=direct
MINIMAX_TTS_EGRESS=direct
COSYVOICE_TTS_EGRESS=direct
SBER_TTS_EGRESS=direct
LIVEKIT_INFERENCE_EGRESS=proxy
```

New providers do not need a separate proxy subsystem. Use the shared helpers in
`src/egress.py`; any provider name automatically supports an env var named
`<PROVIDER>_EGRESS=direct|proxy` (for example `OPENAI_EGRESS=proxy`). Add a
default to `_PROVIDER_DEFAULTS` only after latency/geoblock testing shows the
right production route.

When adding provider plugins, tools, or external API modules, also follow the
diagnostics contract in [`../../docs/robot-diagnostics.md`](../../docs/robot-diagnostics.md).
Use `src/incident_logger.py` for best-effort incident writes instead of creating
a separate log format. Diagnostic writes must not affect the realtime call path.

Provider client wiring checklist:

1. Pick a stable provider key, for example `openai`, `cartesia`, or `anthropic`.
2. Add `<PROVIDER>_EGRESS=direct|proxy` to `.env.example` and production env.
3. Wire the SDK through one shared helper:
   - `provider_proxy_url("<provider>")` for SDKs that accept a proxy URL.
   - `httpx_client_args("<provider>")` for httpx/Google GenAI clients.
   - `create_external_aiohttp_session("<provider>")` for aiohttp-based LiveKit clients.
   - `provider_egress_env("<provider>")` only for SDKs that read proxy variables
     during client construction.
4. For direct mode, make sure the SDK ignores global proxy env (`trust_env=False`
   or equivalent).
5. Test both routes from the Asterisk host under 10-call concurrency, then record
   the chosen default in `_PROVIDER_DEFAULTS` and this README.

## Provider profiles

Provider/model/tuning selection is now stored in Directus component profiles,
not active env variables.

LLM profiles currently support:

1. `provider=google` - direct Gemini API path.
2. `provider=google_vertex` - Gemini through Vertex AI.
3. `provider=xai` - xAI Grok via `livekit.plugins.xai.responses.LLM`.

LLM fallback also lives in each LLM profile: `fallback_provider`,
`fallback_model`, `use_livekit_fallback_adapter`, timeout, retry, and chunk
retry fields. `llm_routing.fast` and `llm_routing.complex` select primary
LLM profiles; fallback is taken from the selected profile.

TTS profiles currently support:

1. `provider=elevenlabs` - ElevenLabs TTS.
2. `provider=google` - `livekit.plugins.google.TTS` (Google Cloud streaming path).
3. `provider=vertex` - Vertex Gemini API streaming path (`google.genai`, `vertexai=True`).
4. `provider=minimax` - local prepared MiniMax WebSocket path (`speech-2.8-hd`, reusable `task_start` per call).
5. `provider=cosyvoice` - custom Alibaba CosyVoice WebSocket path.
6. `provider=tbank` - custom T-Bank VoiceKit gRPC streaming synthesis.
7. `provider=sber` - custom Sber SaluteSpeech gRPC streaming path.

The snippets below are legacy env fallback references. For production, put the
same non-secret tuning values into Directus profile `config_json` and keep only
API keys / credential refs in env.

Legacy ElevenLabs `eleven_v3` env fallback:

```console
TTS_PROVIDER=elevenlabs
ELEVENLABS_MODEL=eleven_v3
ELEVENLABS_V3_USE_STREAM_INPUT=true
ELEVENLABS_V3_OUTPUT_FORMAT=mp3_22050_32
ELEVENLABS_V3_ENABLE_LOGGING=true
ELEVENLABS_V3_REQUEST_TIMEOUT_SEC=30.0
```

Optional tuning for `eleven_v3`:

```console
# leave empty for eleven_v3: this parameter is not supported by eleven_v3
ELEVENLABS_V3_OPTIMIZE_STREAMING_LATENCY=

# sentence buffering for per-request HTTP chunks
ELEVENLABS_V3_MIN_SENTENCE_LEN=6
ELEVENLABS_V3_STREAM_CONTEXT_LEN=2

# optional voice settings
ELEVENLABS_VOICE_STABILITY=0.45
ELEVENLABS_VOICE_SIMILARITY_BOOST=0.75
ELEVENLABS_VOICE_STYLE=0.0
ELEVENLABS_VOICE_SPEED=1.0
ELEVENLABS_VOICE_USE_SPEAKER_BOOST=true
```

Notes for `eleven_v3`:

1. This path uses HTTP `POST /v1/text-to-speech/{voice_id}/stream` only (no WebSocket path).
2. It is built for low practical latency, but `eleven_v3` is still not a Flash-class realtime model.
3. Deploy near ElevenLabs edge region and your LiveKit workers to reduce RTT.

STT profiles currently support:

1. `provider=deepgram` - Deepgram plugin STT (requires `DEEPGRAM_API_KEY`).
2. `provider=inference` - LiveKit Agent Gateway STT.
3. `provider=google` - Google Cloud STT plugin (uses Google credentials).
4. `provider=yandex` - Yandex SpeechKit v3 direct gRPC STT.
5. `provider=tbank` - T-Bank VoiceKit gRPC streaming STT.

If you see `429 Too Many Requests` from `agent-gateway.livekit.cloud` for STT, either:

1. Select a Google STT profile, or
2. Use an inference STT profile with Google fallback configured in Directus/code.

Note: switching between two inference models (`deepgram/*`, `openai/*`) still uses the same LiveKit
gateway quota. For real protection from inference 429, use Google STT as fallback/provider.

Google/Vertex example:

```console
TTS_PROVIDER=google
GOOGLE_TTS_MODEL=gemini-3.1-flash-tts-preview
GOOGLE_TTS_USE_STREAMING=true
GOOGLE_TTS_LOCATION=us-central1
```

Vertex example:

```console
TTS_PROVIDER=vertex
GOOGLE_TTS_MODEL=gemini-3.1-flash-tts-preview
GOOGLE_TTS_LOCATION=global
```

If a configured Google TTS model is rejected by the current API in the selected
region/project, the agent can retry the Google TTS path with
`GOOGLE_TTS_FALLBACK_MODEL` (default: `gemini-2.5-flash-tts`).

MiniMax example:

```console
TTS_PROVIDER=minimax
MINIMAX_API_KEY=<your_minimax_api_key>
MINIMAX_TTS_MODEL=speech-2.8-hd
MINIMAX_TTS_VOICE_ID=moss_audio_43d3c43e-3a2d-11f1-b47e-928b88df9451
MINIMAX_TTS_FORMAT=mp3
MINIMAX_TTS_CONNECTION_REUSE=true
```

Sber SaluteSpeech example:

```console
TTS_PROVIDER=sber
SBER_SALUTESPEECH_AUTH_KEY=<your_sber_authorization_key>
SBER_TTS_CA_CERT_FILE=/path/to/russian-trusted-root-ca.pem
SBER_TTS_VOICE=Ost_24000
SBER_TTS_LANGUAGE=ru-RU
SBER_TTS_SAMPLE_RATE=24000
SBER_TTS_PAINT_PITCH=2
SBER_TTS_PAINT_SPEED=4
SBER_TTS_PAINT_LOUDNESS=5
SBER_TTS_MIN_SENTENCE_LEN=4
SBER_TTS_STREAM_CONTEXT_LEN=1
```

The Sber adapter sends short SSML requests over gRPC `Synthesize` and pushes PCM chunks to LiveKit as soon as Sber returns them. This keeps first-audio latency low even though Sber does not expose bidirectional text streaming.

If OAuth or gRPC TLS verification fails on a machine without Russian trusted root certificates, set `SBER_TTS_CA_CERT_FILE` to the root CA bundle used to verify Sber endpoints.

For local LiveKit with Asterisk, keep Sber traffic direct and configure these values in the local `.env.local` on the robot:

```console
SBER_TTS_EGRESS=direct
SBER_SALUTESPEECH_AUTH_KEY=<your_sber_authorization_key>
SBER_TTS_CA_CERT_FILE=/path/to/russian-trusted-root-ca.pem
```

This local path does not require LiveKit Cloud secret sync.

STT failover example:

```console
STT_PROVIDER=inference
STT_INFERENCE_MODEL=deepgram/nova-3
STT_INFERENCE_INCLUDE_GOOGLE_FALLBACK=true
# Optional: keep empty for fastest 429 failover to Google STT.
STT_INFERENCE_FALLBACK_MODEL=
```

Deepgram STT example (legacy env default; active production choice normally
comes from Directus):

```console
STT_PROVIDER=deepgram
DEEPGRAM_API_KEY=<your_deepgram_api_key>
STT_DEEPGRAM_MODEL=nova-3
STT_DEEPGRAM_LANGUAGE=ru
```

Google STT example:

```console
STT_PROVIDER=google
STT_GOOGLE_MODEL=latest_long
STT_GOOGLE_LANGUAGE=ru-RU
STT_GOOGLE_LOCATION=global
```

Yandex SpeechKit STT example:

```console
STT_PROVIDER=yandex
YANDEX_SPEECHKIT_API_KEY=<your_yandex_speechkit_api_key>
STT_YANDEX_MODEL=general
STT_YANDEX_LANGUAGE=ru-RU
STT_YANDEX_SAMPLE_RATE=16000
STT_YANDEX_CHUNK_MS=50
STT_YANDEX_EOU_SENSITIVITY=high
STT_YANDEX_MAX_PAUSE_BETWEEN_WORDS_HINT_MS=500
```

T-Bank VoiceKit STT/TTS infrastructure example:

```console
TBANK_VOICEKIT_API_KEY=<your_tbank_voicekit_api_key>
TBANK_VOICEKIT_SECRET_KEY=<your_tbank_voicekit_secret_key>
TBANK_VOICEKIT_ENDPOINT=api.tinkoff.ai:443
TBANK_VOICEKIT_AUTHORITY=
STT_PROVIDER=tbank
TTS_PROVIDER=tbank
```

If needed, provide Google credentials via `GOOGLE_TTS_CREDENTIALS_FILE` (or `GOOGLE_APPLICATION_CREDENTIALS`).

For LiveKit Cloud, prefer secret-based credentials (no file upload needed):

```console
GOOGLE_TTS_CREDENTIALS_B64=<base64 of service-account-json>
```

The agent materializes this into a temporary file at runtime and uses it for Google auth.

For lower first-byte latency in streaming mode, tune chunking:

```console
GOOGLE_TTS_MIN_SENTENCE_LEN=4
GOOGLE_TTS_STREAM_CONTEXT_LEN=1
VERTEX_TTS_MIN_SENTENCE_LEN=6
VERTEX_TTS_STREAM_CONTEXT_LEN=2
```

To reduce "hung" turns (long silence after user speech), tune these guards in
the Directus Turn/LLM profiles. The env form below is legacy fallback reference:

```console
USE_LIVEKIT_FALLBACK_ADAPTER=false
LLM_FIRST_TOKEN_TIMEOUT_SEC=2.5
LLM_RETRY_DELAY_SEC=0.3
TURN_MIN_ENDPOINTING_DELAY=0.25
TURN_MAX_ENDPOINTING_DELAY=1.0
TURN_DETECTION_MODE=vad
TURN_ENDPOINTING_MODE=dynamic
TURN_PENDING_REPLY_MIN_INTERRUPTION_WORDS=2
PREEMPTIVE_GENERATION=true
REPLY_WATCHDOG_SEC=9.0
```

`TURN_DETECTION_MODE=vad` detects the end of speech, but LiveKit still needs a
final STT transcript to commit the user turn. If a streaming STT provider sends
a good interim transcript and delays the final flag, enable the universal early
interim final wrapper:

`TURN_PENDING_REPLY_MIN_INTERRUPTION_WORDS=2` applies only while a generated
reply is pending before normal playback. It prevents one-word check-ins such as
`алло` from canceling a ready answer, then restores normal interruption handling
once the answer is actually playing.

```console
STT_EARLY_INTERIM_FINAL_ENABLED=true
STT_EARLY_INTERIM_FINAL_DELAY_SEC=0.03
STT_EARLY_INTERIM_FINAL_MIN_STABLE_INTERIMS=2
```

This wrapper is provider-agnostic and is applied after the selected STT or STT
fallback chain. It only activates for streaming STT providers that support
interim transcripts and with `TURN_DETECTION_MODE=vad`. It emits the latest
interim transcript as a synthetic final transcript after `END_OF_SPEECH` waits
for the configured delay. Keep it opt-in because a synthetic final can be
slightly less accurate than a late provider final.

To make cloud updates seamless, keep secrets sync + deploy in one flow:

```console
uv run python scripts/build_env.py --profile cloud --secrets env/cloud.secrets.env --output .env.cloud.local
uv run python scripts/sync_cloud_secrets.py --env-file .env.cloud.local
lk agent deploy
```

This avoids manual secret edits between deployments.

To run the agent for use with a frontend or telephony, use the `dev` command:

```console
uv run python src/agent.py dev
```

In production, use the `start` command:

```console
uv run python src/agent.py start
```

## Telephony

The current production path is inbound SIP through LiveKit, not a starter web
frontend. Cloud SIP dispatch currently targets agent name `main-bot`; do not
change `AGENT_NAME` without updating the matching dispatch rule. For the
self-hosted Asterisk/local LiveKit route, use
[`../../docs/local-livekit-server.md`](../../docs/local-livekit-server.md).

## Call Recordings Index

LiveKit Egress recordings are stored outside Directus in private MinIO/S3. The
agent indexes completed sessions in Directus so `/admin` and `platform` can find
the matching recording metadata and stream it through a protected backend.

For LiveKit Cloud, `CALL_RECORDING_S3_ENDPOINT` must be a public HTTPS
S3-compatible endpoint that Cloud Egress can reach. Do not use
`http://127.0.0.1:9000` there; that local MinIO endpoint is only appropriate for
the admin backend read proxy (`RECORDINGS_S3_ENDPOINT`) running on the VPS.

Apply the Directus/Postgres schema before enabling cabinet playback:

```console
sudo -u postgres psql -d voicebot -f agents/main-bot/schema/robot_call_recordings.sql
sudo -u postgres psql -d voicebot -f agents/main-bot/schema/robot_call_recordings_directus.sql
```

`send_session_to_n8n()` also best-effort upserts `robot_call_sessions` by
`room_name` when `DIRECTUS_URL` and `DIRECTUS_TOKEN` are set. Recording rows in
`robot_call_recordings` are written by the LiveKit Egress completion/indexer
path and contain the private MinIO object key.

If an agent exits before LiveKit finishes Egress finalization, refresh recording
metadata with:

```console
uv run python scripts/reconcile_recordings.py --limit 200
```

Run this periodically from a small cron/systemd timer after `CALL_RECORDING_*`,
`LIVEKIT_*`, `DIRECTUS_URL`, and `DIRECTUS_TOKEN` are available in the
environment.

## Per-Call Raw Logs

The agent captures Python logging records during each call and writes them to
Directus collection `robot_call_raw_logs` while the call is still running. This
is intentionally separate from the aftercall JSON export: if the final export is
missing or incomplete, recent per-call log lines can still be visible in
`/admin/` under `Логи LiveKit`.

Apply the schema before enabling runtime writes:

```console
sudo -u postgres psql -d voicebot -f agents/main-bot/schema/robot_call_raw_logs.sql
sudo -u postgres psql -d voicebot -f agents/main-bot/schema/robot_call_raw_logs_directus.sql
```

Runtime settings:

```env
RAW_CALL_LOG_ENABLED=true
RAW_CALL_LOG_LEVEL=INFO
RAW_CALL_LOG_FLUSH_INTERVAL_SEC=2.0
RAW_CALL_LOG_BATCH_SIZE=50
RAW_CALL_LOG_MAX_PENDING=1000
RAW_CALL_LOG_MAX_MESSAGE_CHARS=8000
RAW_CALL_LOG_MAX_EXTRA_CHARS=12000
```

Rows are redacted and truncated before upload. The writer is best-effort and
must not affect the customer-visible voice flow when Directus is slow or
unavailable.

## Tests

```console
uv run python -m pytest
```

## Deploying to production

This project includes a `Dockerfile` and `livekit.toml` for LiveKit Cloud.
Before Cloud operations, read [`../../docs/cloud/README.md`](../../docs/cloud/README.md)
and check current LiveKit docs with `lk docs`.

### Sync env to Cloud secrets

Build the Cloud env from templates and ignored Cloud secrets, sync it, then
deploy. Provider/model/tuning settings are read from Directus, not from active
env.

```console
cd agents/main-bot
uv run python scripts/build_env.py --profile cloud --secrets env/cloud.secrets.env --output .env.cloud.local
uv run python scripts/sync_cloud_secrets.py --env-file .env.cloud.local
lk agent deploy
```

The sync helper updates provided keys additively by default. It syncs all
non-empty keys from the env file except `LIVEKIT_URL`, `LIVEKIT_API_KEY`, and
`LIVEKIT_API_SECRET`, which LiveKit Cloud injects for the deployed worker. Use
`--overwrite` only for an intentional full replacement after confirming the env
file contains every required secret.

## Self-hosted LiveKit

The self-hosted Asterisk/local LiveKit path is documented in
[`../../docs/local-livekit-server.md`](../../docs/local-livekit-server.md).
