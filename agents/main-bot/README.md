<a href="https://livekit.io/">
  <img src="./.github/assets/livekit-mark.png" alt="LiveKit logo" width="100" height="100">
</a>

# LiveKit Agents Starter - Python

A complete starter project for building voice AI apps with [LiveKit Agents for Python](https://github.com/livekit/agents) and [LiveKit Cloud](https://cloud.livekit.io/).

The starter project includes:

- A simple voice AI assistant, ready for extension and customization
- A voice AI pipeline built on [LiveKit Inference](https://docs.livekit.io/agents/models/inference)
  with [models](https://docs.livekit.io/agents/models) from OpenAI, Cartesia, and Deepgram. More than 50 other model providers are supported, including [Realtime models](https://docs.livekit.io/agents/models/realtime)
- Eval suite based on the LiveKit Agents [testing & evaluation framework](https://docs.livekit.io/agents/start/testing/)
- [LiveKit Turn Detector](https://docs.livekit.io/agents/logic/turns/turn-detector/) for contextually-aware speaker detection, with multilingual support
- [Background voice cancellation](https://docs.livekit.io/transport/media/noise-cancellation/)
- Deep session insights from LiveKit [Agent Observability](https://docs.livekit.io/deploy/observability/)
- A Dockerfile ready for [production deployment to LiveKit Cloud](https://docs.livekit.io/deploy/agents/)

This starter app is compatible with any [custom web/mobile frontend](https://docs.livekit.io/frontends/) or [telephony](https://docs.livekit.io/telephony/).

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

Create a project from this template with the LiveKit CLI (recommended):

```bash
lk cloud auth
lk agent init my-agent --template agent-starter-python
```

The CLI clones the template and configures your environment. Then follow the rest of this guide from [Run the agent](#run-the-agent).

<details>
<summary>Alternative: Manual setup without the CLI</summary>

Clone the repository and install dependencies to a virtual environment:

```console
cd agent-starter-python
uv sync
```

Sign up for [LiveKit Cloud](https://cloud.livekit.io/) then set up the environment by copying `.env.example` to `.env.local` and filling in the required keys:

- `LIVEKIT_URL`
- `LIVEKIT_API_KEY`
- `LIVEKIT_API_SECRET`

You can load the LiveKit environment automatically using the [LiveKit CLI](https://docs.livekit.io/intro/basics/cli/):

```bash
lk cloud auth
lk app env -w -d .env.local
```

</details>

## Run the agent

Before your first run, you must download certain models such as [Silero VAD](https://docs.livekit.io/agents/logic/turns/vad/) and the [LiveKit turn detector](https://docs.livekit.io/agents/logic/turns/turn-detector/):

```console
uv run python src/agent.py download-files
```

Next, run this command to speak to your agent directly in your terminal:

```console
uv run python src/agent.py console
```

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
XAI_EGRESS=proxy
DEEPGRAM_EGRESS=direct
MINIMAX_TTS_EGRESS=direct
COSYVOICE_TTS_EGRESS=direct
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

## Production provider changes

The provider sections below document supported configuration options. They do
not authorize an agent to change production defaults or business behavior.

Do not switch LLM/STT/TTS provider, model, voice, prompt, fallback, timeout,
retry policy, latency guard, turn logic, or workflow behavior without explicit
owner approval. If a provider is slow, blocked, rate-limited, or failing,
diagnose the root cause first. Any provider/model/fallback switch must be
proposed with quality, latency, cost, reliability, and rollback tradeoffs before
implementation.

To switch LLM provider, set `LLM_PROVIDER`:

1. `LLM_PROVIDER=google` - direct Gemini API path (default).
2. `LLM_PROVIDER=xai` - xAI Grok via `livekit.plugins.xai.responses.LLM`.

xAI Grok example:

```console
LLM_PROVIDER=xai
XAI_API_KEY=<your_xai_api_key>
XAI_MODEL=grok-4-1-fast-non-reasoning-latest
XAI_TEMPERATURE=0.3
# Optional: force Europe region endpoint
XAI_BASE_URL=https://eu-west-1.api.x.ai/v1
# Disable function tools for every LLM provider.
LLM_ENABLE_TOOLS=false
# xAI also has a provider-specific tools flag for compatibility.
XAI_ENABLE_TOOLS=false
```

To switch TTS provider, set `TTS_PROVIDER`:

1. `TTS_PROVIDER=elevenlabs` - ElevenLabs TTS.
2. `TTS_PROVIDER=google` - `livekit.plugins.google.TTS` (Google Cloud streaming path).
3. `TTS_PROVIDER=vertex` - Vertex Gemini API streaming path (`google.genai`, `vertexai=True`).
4. `TTS_PROVIDER=minimax` - official `livekit.plugins.minimax.TTS` path (`speech-2.8-turbo`).
5. `TTS_PROVIDER=cosyvoice` - custom Alibaba CosyVoice WebSocket path.

ElevenLabs `eleven_v3` custom HTTP streaming path:

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

To switch STT provider, set `STT_PROVIDER`:

1. `STT_PROVIDER=deepgram` - Deepgram plugin STT (default, requires `DEEPGRAM_API_KEY`).
2. `STT_PROVIDER=inference` - LiveKit Agent Gateway STT.
3. `STT_PROVIDER=google` - Google Cloud STT plugin (uses Google credentials).
4. `STT_PROVIDER=yandex` - Yandex SpeechKit v3 direct gRPC STT (requires `YANDEX_SPEECHKIT_API_KEY`).

If you see `429 Too Many Requests` from `agent-gateway.livekit.cloud` for STT, either:

1. Set `STT_PROVIDER=google` (recommended if Google credentials are already configured), or
2. Keep `STT_PROVIDER=inference` and enable `STT_INFERENCE_INCLUDE_GOOGLE_FALLBACK=true`.

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

MiniMax example:

```console
TTS_PROVIDER=minimax
MINIMAX_API_KEY=<your_minimax_api_key>
MINIMAX_TTS_MODEL=speech-2.8-turbo
MINIMAX_TTS_VOICE_ID=moss_audio_43d3c43e-3a2d-11f1-b47e-928b88df9451
MINIMAX_TTS_FORMAT=mp3
```

STT failover example:

```console
STT_PROVIDER=inference
STT_INFERENCE_MODEL=deepgram/nova-3
STT_INFERENCE_INCLUDE_GOOGLE_FALLBACK=true
# Optional: keep empty for fastest 429 failover to Google STT.
STT_INFERENCE_FALLBACK_MODEL=
```

Deepgram STT example (default):

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

If this model is rejected by current API in your region/project, the agent auto-falls back to `GOOGLE_TTS_FALLBACK_MODEL` (default: `gemini-2.5-flash-tts`).

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

To reduce "hung" turns (long silence after user speech), tune these guards:

```console
USE_LIVEKIT_FALLBACK_ADAPTER=false
LLM_FIRST_TOKEN_TIMEOUT_SEC=2.5
LLM_RETRY_DELAY_SEC=0.3
TURN_MIN_ENDPOINTING_DELAY=0.25
TURN_MAX_ENDPOINTING_DELAY=1.0
TURN_DETECTION_MODE=vad
TURN_ENDPOINTING_MODE=dynamic
PREEMPTIVE_GENERATION=true
REPLY_WATCHDOG_SEC=9.0
```

`TURN_DETECTION_MODE=vad` detects the end of speech, but LiveKit still needs a
final STT transcript to commit the user turn. If a streaming STT provider sends
a good interim transcript and delays the final flag, enable the universal early
interim final wrapper:

```console
STT_EARLY_INTERIM_FINAL_ENABLED=true
STT_EARLY_INTERIM_FINAL_DELAY_SEC=0.15
STT_EARLY_INTERIM_FINAL_MIN_STABLE_INTERIMS=1
```

This wrapper is provider-agnostic and is applied after the selected STT or STT
fallback chain. It only activates for streaming STT providers that support
interim transcripts and with `TURN_DETECTION_MODE=vad`. It uses the local
LiveKit/Silero VAD `speaking -> listening` transition as the deadline source:
if the provider final flag has not arrived after the configured delay, the
latest stable interim transcript is emitted as a synthetic final.
`STT_EARLY_INTERIM_FINAL_MIN_STABLE_INTERIMS=2` is safer for providers whose
first interim can change materially. Keep it opt-in because a synthetic final
can be slightly less accurate than a late provider final.

To make cloud updates seamless, keep secrets sync + deploy in one flow:

```console
uv run python scripts/sync_cloud_secrets.py --working-dir .
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

## Frontend & Telephony

Get started quickly with our pre-built frontend starter apps, or add telephony support:

| Platform | Link | Description |
|----------|----------|-------------|
| **Web** | [`livekit-examples/agent-starter-react`](https://github.com/livekit-examples/agent-starter-react) | Web voice AI assistant with React & Next.js |
| **iOS/macOS** | [`livekit-examples/agent-starter-swift`](https://github.com/livekit-examples/agent-starter-swift) | Native iOS, macOS, and visionOS voice AI assistant |
| **Flutter** | [`livekit-examples/agent-starter-flutter`](https://github.com/livekit-examples/agent-starter-flutter) | Cross-platform voice AI assistant app |
| **React Native** | [`livekit-examples/voice-assistant-react-native`](https://github.com/livekit-examples/voice-assistant-react-native) | Native mobile app with React Native & Expo |
| **Android** | [`livekit-examples/agent-starter-android`](https://github.com/livekit-examples/agent-starter-android) | Native Android app with Kotlin & Jetpack Compose |
| **Web Embed** | [`livekit-examples/agent-starter-embed`](https://github.com/livekit-examples/agent-starter-embed) | Voice AI widget for any website |
| **Telephony** | [Documentation](https://docs.livekit.io/telephony/) | Add inbound or outbound calling to your agent |

For advanced customization, see the [complete frontend guide](https://docs.livekit.io/frontends/).

## Tests and evals

This project includes a complete suite of evals, based on the LiveKit Agents [testing & evaluation framework](https://docs.livekit.io/agents/start/testing/). To run them, use `pytest`.

```console
uv run pytest
```

## Using this template repo for your own project

Once you've started your own project based on this repo, you should:

1. **Check in your `uv.lock`**: This file is currently untracked for the template, but you should commit it to your repository for reproducible builds and proper configuration management. (The same applies to `livekit.toml`, if you run your agents in LiveKit Cloud)

2. **Remove the git tracking test**: Delete the "Check files not tracked in git" step from `.github/workflows/tests.yml` since you'll now want this file to be tracked. These are just there for development purposes in the template repo itself.

3. **Add your own repository secrets**: You must [add secrets](https://docs.github.com/en/actions/how-tos/writing-workflows/choosing-what-your-workflow-does/using-secrets-in-github-actions) for `LIVEKIT_URL`, `LIVEKIT_API_KEY`, and `LIVEKIT_API_SECRET` so that the tests can run in CI.

## Deploying to production

This project is production-ready and includes a working `Dockerfile`. To deploy it to LiveKit Cloud or another environment, see the [deploying to production](https://docs.livekit.io/deploy/agents/) guide.

### Sync env to Cloud secrets

If you use direct Gemini and provider keys from `.env.local`, sync them to LiveKit Cloud before deploy:

```console
cd agents/main-bot
uv run python scripts/sync_cloud_secrets.py --env-file .env.local
lk agent deploy
```

The sync command updates secrets as a full set (`--overwrite`) to keep Cloud env aligned with your local env file.
It syncs non-empty keys from `.env.local` automatically, but filters out LiveKit connection credentials (`LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`), global proxy vars, and any `<PROVIDER>_EGRESS=proxy` values.
For local/self-hosted deploys, keep proxy routing explicit in the production env for services that must go through the VPS proxy.

## Self-hosted LiveKit

You can also self-host LiveKit instead of using LiveKit Cloud. See the [self-hosting](https://docs.livekit.io/transport/self-hosting/local/) guide for more information. If you choose to self-host, you'll need to also use [model plugins](https://docs.livekit.io/agents/models/#plugins) instead of LiveKit Inference and will need to remove the [LiveKit Cloud noise cancellation](https://docs.livekit.io/transport/media/noise-cancellation/) plugin.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
