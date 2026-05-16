# Current LiveKit Cloud state

Snapshot taken: 2026-05-11 with read-only `lk` commands from
`/Users/romangarkun/Documents/Проекты/LiveKit/agents/main-bot`.

This snapshot intentionally does not include secret values. `lk agent secrets`
shows names and timestamps only.

## 2026-05-15 test agent addendum

- Test Cloud config: `agents/main-bot/livekit.test.toml`
- Test agent ID: `CA_tCPh4SqnPqkQ`
- Test region: `eu-central`
- Test identity: `AGENT_NAME=main-bot-test`,
  `ROBOT_RUNTIME_PROFILE=main_bot_test`
- Deploy logs showed the worker registered as `main-bot-test`.
- SIP was not changed: the existing dispatch rule still targets `main-bot`.

## CLI and local config

- CLI version: `lk 2.16.0`
- Agent working directory: `/Users/romangarkun/Documents/Проекты/LiveKit/agents/main-bot`
- Cloud config file: `agents/main-bot/livekit.toml`
- Configured project subdomain: `jcallio-g451240m`
- Configured agent ID: `CA_oaEZ279sgQGr`
- CLI default project: `jcallio`

## Project

- Project name: `jcallio`
- Project ID: `p_3y86a27dg6q`
- Project URL: `wss://jcallio-g451240m.livekit.cloud`
- API key: present in local CLI project list, not recorded here.

## Agent deployment

- Agent ID: `CA_oaEZ279sgQGr`
- Region: `eu-central`
- Current version: `QVi3bHhnuoSL`
- Deployed at: `2026-05-09T20:18:25Z`
- Status during snapshot: `Running`
- CPU limit/current: `6m / 4000m`
- Memory limit/current: `1.2 / 8GB`
- Replicas: `1 / 1 / 8`

## Telephony

Inbound SIP trunks:

- `ST_f4AVPiYx6Kvm`
- Name: `vhod`
- Numbers: empty
- Allowed addresses: `87.226.145.66/32`
- Allowed numbers: empty
- Authentication: empty
- Encryption: `DISABLE`
- Headers: `X-DID=jcall.did`

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

Important: Cloud SIP dispatch currently targets `main-bot`. The deployed
worker must register the same `AGENT_NAME`, unless the dispatch rule is changed
at the same time.

LiveKit Phone Numbers:

- Total phone numbers: `0`

## Runtime resources

- Active rooms: none during snapshot.
- Active ingress resources: none during snapshot.
- `lk egress list` returned completed `room_composite` recordings, including
  recordings from 2026-05-08 through 2026-05-11. No active egress error was
  visible in the snapshot output.

## Cloud secret names

Core/runtime:

- `AGENT_NAME`
- `AGENT_MAX_CONCURRENT_JOBS`
- `AGENT_NUM_IDLE_PROCESSES`
- `ROBOT_RUNTIME_PROFILE`
- `ROBOT_SETTINGS_CACHE_TTL_SEC`
- `ROBOT_SETTINGS_SNAPSHOT_FILE`
- `ROBOT_SETTINGS_USE_DIRECTUS`

Directus, prompt, logs, incidents:

- `DIRECTUS_URL`
- `DIRECTUS_TOKEN`
- `DIRECTUS_REQUEST_TIMEOUT_SEC`
- `DIRECTUS_PROMPT_CACHE_TTL_SEC`
- `DIRECTUS_DEFAULT_TIMEZONE`
- `DIRECTUS_COLLECTION_CALLER_ID`
- `DIRECTUS_COLLECTION_BOT_CONFIGURATIONS`
- `DIRECTUS_COLLECTION_CLIENTS`
- `DIRECTUS_COLLECTION_CLIENTS_PROMPT`
- `DIRECTUS_COLLECTION_WEBPARSING`
- `DIRECTUS_COLLECTION_TRANSFER_NUMBER`
- `DIRECTUS_COLLECTION_CLIENT_PROMPT_CACHE`
- `RAW_CALL_LOG_LEVEL`
- `RAW_CALL_LOG_BATCH_SIZE`
- `INCIDENT_LOG_ENABLED`
- `INCIDENT_LOG_TRANSPORT`
- `INCIDENT_ENVIRONMENT`
- `INCIDENT_DB_TIMEOUT_SEC`
- `N8N_WEBHOOK_URL`

LLM:

- `GOOGLE_API_KEY`
- `GEMINI_FALLBACK_MODEL`
- `GEMINI_TOP_P`
- `XAI_API_KEY`
- `XAI_MODEL`
- `XAI_EGRESS`
- `LLM_ATTEMPT_TIMEOUT_SEC`
- `LLM_MAX_RETRY_PER_LLM`
- `COMPLEX_LLM_BACKUP_PROVIDER`
- `COMPLEX_LLM_BACKUP_MODEL`

STT:

- `DEEPGRAM_API_KEY`
- `STT_DEEPGRAM_MODEL`
- `STT_GOOGLE_MODEL`
- `STT_GOOGLE_LANGUAGE`
- `STT_YANDEX_LANGUAGE`
- `STT_YANDEX_SAMPLE_RATE`
- `STT_YANDEX_CHUNK_MS`
- `STT_YANDEX_EOU_SENSITIVITY`
- `YANDEX_SPEECHKIT_API_KEY`
- `STT_EARLY_INTERIM_FINAL_MIN_STABLE_INTERIMS`

TTS and voice providers:

- `ELEVEN_API_KEY`
- `ELEVENLABS_API_KEY`
- `ELEVENLABS_VOICE_ID`
- `ELEVENLABS_MODEL`
- `ELEVENLABS_V3_ENABLE_LOGGING`
- `GOOGLE_TTS_CREDENTIALS_B64`
- `GOOGLE_TTS_LANGUAGE`
- `GOOGLE_TTS_MIN_SENTENCE_LEN`
- `GOOGLE_TTS_VOICE_NAME`
- `MINIMAX_API_KEY`
- `MINIMAX_TTS_FORMAT`
- `MINIMAX_TTS_INTENSITY`
- `MINIMAX_TTS_LANGUAGE_BOOST`
- `COSYVOICE_API_KEY`
- `COSYVOICE_TTS_MODEL`
- `COSYVOICE_TTS_SAMPLE_RATE`
- `SBER_SALUTESPEECH_AUTH_KEY`
- `VOICEKIT_API_KEY`
- `VOICEKIT_SECRET_KEY`

Voice guards:

- `VOICE_INITIAL_GREETING_PHRASE`
- `VOICE_INITIAL_GREETING_DELAY_SEC`
- `VOICE_RESPONSE_DELAY_SEC`
- `VOICE_CLIENT_SILENCE_FIRST_SEC`
- `VOICE_CLIENT_SILENCE_SEC`
- `VOICE_CLIENT_SILENCE_STT_GRACE_SEC`
- `VOICE_CLIENT_SILENCE_MAX_PROMPTS`

Call recordings:

- `CALL_RECORDING_ENABLED`
- `CALL_RECORDING_S3_ENDPOINT`
- `CALL_RECORDING_S3_BUCKET`
- `CALL_RECORDING_S3_REGION`
- `CALL_RECORDING_S3_ACCESS_KEY`
- `CALL_RECORDING_S3_SECRET_KEY`
- `CALL_RECORDING_S3_FORCE_PATH_STYLE`
- `CALL_RECORDING_PREFIX`
- `CALL_RECORDING_FINALIZE_TIMEOUT_SEC`
- `CALL_RECORDING_FINALIZE_POLL_SEC`

## Notable drift to watch

- `AGENT_NAME` value cannot be read from `lk agent secrets`; the dispatch rule
  proves only that SIP currently targets `main-bot`. Keep the Cloud env template
  aligned with that name.
- Some current Cloud secrets are legacy env fallback/tuning keys. Production
  provider/model/tuning selection should still come from Directus profiles.
- No outbound SIP trunk and no LiveKit Phone Numbers are currently provisioned.
