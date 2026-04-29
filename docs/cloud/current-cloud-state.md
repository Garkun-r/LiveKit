# Current LiveKit Cloud state

Snapshot taken: 2026-04-24 11:25:02 +07.

This snapshot was collected with read-only `lk` commands. It intentionally does not include secret values.

## CLI and local config

- CLI version: `lk 2.16.0`
- Agent working directory: `/Users/romangarkun/Documents/Проекты/LiveKit/agents/main-bot`
- Cloud config file: `agents/main-bot/livekit.toml`
- Configured project subdomain: `jcallio-g451240m`
- Configured agent ID: `CA_oaEZ279sgQGr`
- Local `.env.example` includes empty placeholders only.
- Local `.env.local` exists, but secret values were not read into this document.

## Project

- Project name: `jcallio`
- Project ID: `p_3y86a27dg6q`
- Project URL: `wss://jcallio-g451240m.livekit.cloud`
- API key: present in local `lk project list`; not recorded here except as masked `APIUYU...nxD`
- CLI default project: `jcallio`

## Agent deployment

- Agent ID: `CA_oaEZ279sgQGr`
- Region: `eu-central`
- Current version: `v20260421162443`
- Deployed at: `2026-04-21T16:27:25Z`
- Status during snapshot: `Sleeping`
- CPU limit/current: `0m / 2000m`
- Memory limit/current: `0 / 4GB`
- Replicas: `0 / 1 / 1`
- Versions listed: only `v20260421162443`, marked current and available

## Telephony

Inbound SIP trunks:

- `ST_f4AVPiYx6Kvm`
- Name: `vhod`
- Numbers: empty
- Allowed addresses: `87.226.145.66/32`
- Allowed numbers: empty
- Authentication: empty
- Encryption: `DISABLE`

Outbound SIP trunks:

- None listed.

Dispatch rules:

- Rule ID: `SDR_E7TJA8EkkxKj`
- Name: `main_bot`
- Trunk: `ST_f4AVPiYx6Kvm`
- Type: `Individual (Caller)`
- Room name pattern: `_<caller>_<random>`
- PIN: empty
- Attributes: `map[]`
- Agents: `main-bot`

LiveKit Phone Numbers:

- Total phone numbers: `0`

## Active runtime resources

- Active rooms: none.
- Active ingress resources: none.
- Active egress resources: none.

## Cloud secret names

The following names exist in LiveKit Cloud for the current agent. Values were not retrieved and cannot be retrieved with `lk agent secrets`.

Core/runtime:

- `AGENT_NAME`
- `POSTGRES_DSN`
- `N8N_WEBHOOK_URL`
- `PREEMPTIVE_GENERATION`
- `REPLY_WATCHDOG_SEC`
- `TURN_DETECTION_MODE`
- `TURN_ENDPOINTING_MODE`
- `TURN_MIN_ENDPOINTING_DELAY`
- `TURN_MAX_ENDPOINTING_DELAY`

LLM:

- `LLM_PROVIDER`
- `FAST_LLM_PROVIDER`
- `COMPLEX_LLM_PROVIDER`
- `LLM_FIRST_TOKEN_TIMEOUT_SEC`
- `LLM_RETRY_DELAY_SEC`
- `GOOGLE_API_KEY`
- `GEMINI_MODEL`
- `GEMINI_FALLBACK_MODEL`
- `GEMINI_TEMPERATURE`
- `GEMINI_MAX_OUTPUT_TOKENS`
- `GEMINI_TOP_P`
- `GEMINI_THINKING_LEVEL`
- `XAI_API_KEY`
- `XAI_MODEL`
- `XAI_TEMPERATURE`
- `XAI_BASE_URL`

STT:

- `STT_PROVIDER`
- `DEEPGRAM_API_KEY`
- `STT_DEEPGRAM_MODEL`
- `STT_DEEPGRAM_LANGUAGE`
- `STT_DEEPGRAM_ENDPOINTING_MS`
- `STT_INFERENCE_MODEL`
- `STT_INFERENCE_FALLBACK_MODEL`
- `STT_INFERENCE_LANGUAGE`
- `STT_INFERENCE_INCLUDE_GOOGLE_FALLBACK`
- `STT_GOOGLE_MODEL`
- `STT_GOOGLE_LANGUAGE`
- `STT_GOOGLE_LOCATION`

ElevenLabs TTS:

- `ELEVEN_API_KEY`
- `ELEVENLABS_API_KEY`
- `ELEVENLABS_VOICE_ID`
- `ELEVENLABS_MODEL`
- `ELEVENLABS_V3_USE_STREAM_INPUT`
- `ELEVENLABS_V3_OUTPUT_FORMAT`
- `ELEVENLABS_V3_ENABLE_LOGGING`
- `ELEVENLABS_V3_APPLY_TEXT_NORMALIZATION`
- `ELEVENLABS_V3_MIN_SENTENCE_LEN`
- `ELEVENLABS_V3_STREAM_CONTEXT_LEN`

Google/Vertex TTS:

- `GOOGLE_TTS_MODEL`
- `GOOGLE_TTS_FALLBACK_MODEL`
- `GOOGLE_TTS_LANGUAGE`
- `GOOGLE_TTS_VOICE_NAME`
- `GOOGLE_TTS_SPEAKING_RATE`
- `GOOGLE_TTS_PITCH`
- `GOOGLE_TTS_CREDENTIALS_B64`
- `GOOGLE_TTS_LOCATION`
- `GOOGLE_TTS_USE_STREAMING`
- `GOOGLE_TTS_MIN_SENTENCE_LEN`
- `GOOGLE_TTS_STREAM_CONTEXT_LEN`
- `GOOGLE_TTS_PROMPT`
- `VERTEX_TTS_MIN_SENTENCE_LEN`
- `VERTEX_TTS_STREAM_CONTEXT_LEN`

MiniMax TTS:

- `MINIMAX_API_KEY`
- `MINIMAX_TTS_MODEL`
- `MINIMAX_TTS_VOICE_ID`
- `MINIMAX_TTS_BASE_URL`
- `MINIMAX_TTS_LANGUAGE_BOOST`
- `MINIMAX_TTS_SPEED`
- `MINIMAX_TTS_VOLUME`
- `MINIMAX_TTS_PITCH`
- `MINIMAX_TTS_FORMAT`
- `MINIMAX_TTS_SAMPLE_RATE`
- `MINIMAX_TTS_BITRATE`
- `MINIMAX_TTS_CHANNEL`
- `MINIMAX_TTS_MIN_SENTENCE_LEN`
- `MINIMAX_TTS_STREAM_CONTEXT_LEN`

CosyVoice TTS:

- `COSYVOICE_PROFILE`
- `COSYVOICE_API_KEY`
- `COSYVOICE_API_KEY_ENV_NAME`
- `COSYVOICE_TTS_TRANSPORT`
- `COSYVOICE_TTS_REGION`
- `COSYVOICE_TTS_WS_URL`
- `COSYVOICE_TTS_MODEL`
- `COSYVOICE_TTS_VOICE_MODE`
- `COSYVOICE_TTS_VOICE_ID`
- `COSYVOICE_TTS_CLONE_VOICE_ID`
- `COSYVOICE_TTS_DESIGN_VOICE_ID`
- `COSYVOICE_TTS_FORMAT`
- `COSYVOICE_TTS_SAMPLE_RATE`
- `COSYVOICE_TTS_RATE`
- `COSYVOICE_TTS_PITCH`
- `COSYVOICE_TTS_VOLUME`
- `COSYVOICE_TTS_CONNECTION_REUSE`
- `COSYVOICE_TTS_PLAYBACK_ON_FIRST_CHUNK`
- `COSYVOICE_TTS_MIN_SENTENCE_LEN`
- `COSYVOICE_TTS_STREAM_CONTEXT_LEN`

## Notable drift to check later

- Cloud secret names include `STT_DEEPGRAM_ENDPOINTING_MS`, but `agents/main-bot/.env.example` should be checked whenever env templates are updated.
- Cloud secret names include `ELEVEN_API_KEY` and `ELEVENLABS_API_KEY`; verify whether both are still needed before removing either.
- No outbound SIP trunk exists, so outbound calling is not currently configured from the listed cloud resources.
- No LiveKit Phone Numbers are currently provisioned in this project.
