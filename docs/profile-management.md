# Profile Management

This is the operating runbook for LiveKit robot LLM, TTS, STT, and turn profiles.
Read this before changing provider/model/voice settings.

## Source Of Truth

Production provider selection is stored in Directus, not in active env files.

Runtime resolution order for each call:

```text
project by DID -> ROBOT_RUNTIME_PROFILE runtime -> base runtime
```

If Directus is unavailable, the agent falls back to:

```text
last in-memory cache -> agents/main-bot/config/robot_settings_snapshot.json -> legacy env defaults
```

Env remains the bootstrap and secret layer:

- LiveKit connection and `AGENT_NAME`;
- Directus URL/token and request timeouts;
- provider credentials and credential refs;
- egress defaults;
- safety and diagnostic settings.

Do not store API keys, tokens, service-account JSON, or private URLs in Directus
profiles, docs, tests, or the snapshot. Profiles may use non-secret references
such as `api_key_ref`, `credentials_ref`, `auth_key_ref`, or `api_key_env_name`.

## Directus Tables

- `robot_component_profiles`: reusable component profiles. One row describes one
  LLM, TTS, STT, turn, fallback, or related runtime component.
- `robot_profile_bindings`: assigns component profiles to an owner and slot, for
  example `runtime.base.tts.primary -> tts_elevenlabs_v3`.
- `robot_runtime_profiles`: runtime identities such as `base`, `mac`,
  `asterisk`, and `livekit_cloud`.
- `robot_project_profiles`: project/client/DID overrides.
- `robot_setting_fields`: UI field catalog. It describes editable fields; it is
  not the source of actual runtime values.

Direct `*_profile` columns on runtime/project rows are transitional
compatibility fields. Explicit `robot_profile_bindings` rows win over those
columns.

## How To Change A Profile

1. Edit or add the non-secret values in `robot_component_profiles.config_json`.
2. If a new setting key should appear in UI, add it to `robot_setting_fields`.
3. Assign the profile through `robot_profile_bindings`.
4. Keep credentials in env or LiveKit Cloud secrets.
5. Run read-only verification.
6. Export and compare the local snapshot if cold-start fallback must match
   Directus.

Use project bindings for client/DID-specific behavior. Do not fork deployment env
or code for client-specific prompt, voice, STT, TTS, LLM, transfer, or workflow
facts.

## Snapshot Workflow

The snapshot is a local, non-secret copy of Directus settings for cold start
fallback. It is not updated automatically when Directus changes.

After changing production Directus profiles:

```bash
cd agents/main-bot
uv run python scripts/export_robot_settings_snapshot.py --env-file .env.local
uv run python scripts/verify_robot_settings_directus.py --env-file .env.local --compare-snapshot
```

For CI or review checks without writing:

```bash
cd agents/main-bot
uv run python scripts/export_robot_settings_snapshot.py --env-file .env.local --check
```

If `--check` fails, Directus and the local snapshot differ. Either export the
snapshot intentionally or explain why the cold-start fallback should stay
different.

## Runtime Code Rules

When adding or editing provider builders:

- read non-secret model, voice, language, endpoint, latency, fallback, and tuning
  values from the selected `ComponentSelection.config`;
- use env only as a fallback for legacy cold-start behavior and secrets;
- do not rename env variables unless the task explicitly requires it;
- preserve the realtime voice flow: startup, room join, STT callbacks, turn
  detection, LLM streaming, TTS streaming, and fallback timing;
- add a focused test showing that `ComponentSelection.config` is actually used.

Current builder entrypoints:

- LLM: `build_llm_client_for_branch()` and provider builders in
  `agents/main-bot/src/agent.py`;
- TTS: `build_tts()`;
- STT: `build_stt()`;
- settings resolver: `agents/main-bot/src/robot_settings.py`;
- model routing rules: `agents/main-bot/src/routing/model_router_config.yaml`.

`agents/main-bot/src/providers.py` is not part of the active runtime settings
path and must not be used as a source of truth for supported providers. The
active provider list is defined by Directus component profiles plus the builder
branches above.

## Verification Checklist

Minimum checks after profile or builder changes:

```bash
cd agents/main-bot
uv run python scripts/verify_robot_settings_directus.py --env-file .env.local
uv run python -m pytest tests/test_robot_settings.py tests/test_robot_settings_agent_integration.py
```

If builder behavior changed, also run the relevant provider tests, for example:

```bash
uv run python -m pytest tests/test_tbank_tts.py tests/test_tbank_stt.py tests/test_yandex_stt.py tests/test_sber_tts.py
```

Before deploying, make sure the effective runtime profile is the intended one:

```bash
uv run python scripts/verify_robot_settings_directus.py --env-file .env.local --runtime base
uv run python scripts/verify_robot_settings_directus.py --env-file .env.local --runtime asterisk
```
