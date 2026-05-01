# Directus-настройки LiveKit-робота

Эта схема делает Directus основным источником настроек LLM/TTS/STT/Turn для
рабочего звонка. `.env.local` остается bootstrap-слоем: подключение к LiveKit,
доступ к Directus, секреты провайдеров, egress, n8n, incident logging и
процессные safety-настройки.

## Что остается в env

Активными в env остаются:

- `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`;
- `AGENT_NAME`;
- `ROBOT_RUNTIME_PROFILE=base|asterisk|mac`;
- `DIRECTUS_URL`, `DIRECTUS_TOKEN`, `DIRECTUS_REQUEST_TIMEOUT_SEC`;
- `ROBOT_SETTINGS_CACHE_TTL_SEC`, `ROBOT_SETTINGS_SNAPSHOT_FILE`,
  `ROBOT_SETTINGS_USE_DIRECTUS`;
- API-ключи и credential refs провайдеров: `GOOGLE_API_KEY`, `XAI_API_KEY`,
  `DEEPGRAM_API_KEY`, `ELEVENLABS_API_KEY` / `ELEVEN_API_KEY`,
  `MINIMAX_API_KEY`, `COSYVOICE_API_KEY`, `GOOGLE_TTS_CREDENTIALS_*`,
  `SBER_SALUTESPEECH_AUTH_KEY`, `VOICEKIT_*`, `YANDEX_SPEECHKIT_API_KEY`;
- `N8N_*`, `INCIDENT_*`, `EGRESS_*`;
- process/system параметры: health endpoint, локальный аудио-кэш,
  prerecorded safety prompts, watchdog.

Provider/model/tuning переменные типа `LLM_PROVIDER`, `TTS_PROVIDER`,
`STT_PROVIDER`, `GEMINI_*`, `XAI_MODEL`, `ELEVENLABS_MODEL`,
`STT_DEEPGRAM_MODEL`, `TURN_*` считаются legacy. Они оставлены в коде как
аварийный fallback для тестов и cold-start сценариев без Directus/snapshot, но
не должны управлять обычным production-звонком.

`EGRESS_*` остаются env-defaults, но конкретный Directus-профиль может
переопределить маршрут через `config_json.egress=direct|proxy`. Это нужно для
Asterisk-профилей, где тот же провайдер может идти через proxy, а в cloud/base
оставаться с обычным маршрутом.

## Что живет в Directus

Основные таблицы:

- `robot_component_profiles` - профили компонентов. Один профиль описывает один
  набор настроек, например `llm_xai`, `tts_elevenlabs_v3`,
  `stt_deepgram_ru_phone`, `turn_fast_phone`.
- `robot_setting_fields` - каталог доступных полей для UI: тип значения,
  контрол, options, описание на русском.
- `robot_runtime_profiles` - среды процесса: `base`, `asterisk`, `mac`.
  `base` является основной/cloud-конфигурацией.
- `robot_profile_bindings` - выбор профилей для владельца:
  `runtime.base.llm.primary -> llm_xai`.
- `robot_project_profiles` - клиентские/project overrides по DID.

Личный кабинет может хранить выбор профилей либо в `robot_profile_bindings`,
либо в прямых колонках `robot_runtime_profiles` / `robot_project_profiles`
(`llm_profile`, `tts_profile`, `stt_profile`, `turn_profile`,
`fast_llm_profile`, `complex_llm_profile`). Явные rows в
`robot_profile_bindings` имеют приоритет над прямыми колонками.

Если Codex добавляет новый параметр модуля, он должен добавить:

1. поле в `robot_setting_fields`;
2. ключ в нужный `config_json` профиля, если значение должно сразу быть видно и
   применяться без ручного добавления через UI;
3. чтение этого ключа в коде сборки компонента.

Секретные значения в Directus не хранятся. В профилях используются ссылки:
`api_key_ref`, `credentials_ref`, `auth_key_ref`, `api_key_env_name`.

Для Asterisk заведены proxy-варианты:

- `llm_xai_proxy`;
- `llm_google_proxy`;
- `stt_deepgram_proxy`;
- `tts_elevenlabs_v3_proxy`.

Все они содержат `egress=proxy`. Runtime `asterisk` выбирает эти профили через
bindings, включая `llm_routing.fast=llm_xai_proxy` и
`llm_routing.complex=llm_google_proxy`.

## Порядок наследования

Для каждого звонка агент резолвит настройки в порядке:

1. `project` по DID входящего SIP/телефонного маршрута;
2. `runtime`, выбранный переменной `ROBOT_RUNTIME_PROFILE`;
3. `base`.

Если у project задан профиль только для TTS, то LLM/STT/Turn берутся из runtime
или `base`. Если runtime не переопределяет TTS, используется `base`.

`base` считается основной/cloud-конфигурацией. Отдельный runtime
`livekit_cloud` может оставаться в базе как совместимость/алиас, но обычный
cloud-процесс должен запускаться с `ROBOT_RUNTIME_PROFILE=base`.

## Cache И Snapshot

Агент не обязан дергать Directus на каждый звонок. Настройки грузятся через
in-memory cache с TTL `ROBOT_SETTINGS_CACHE_TTL_SEC`.

Если Directus недоступен:

1. используется последний in-memory cache;
2. при cold start читается `config/robot_settings_snapshot.json`;
3. если нет и snapshot, код возвращается к legacy env defaults.

Snapshot не содержит секретов. Это локальная non-secret копия профилей,
bindings, runtime/project profiles и field catalog. Обновлять snapshot нужно
после изменений Directus-профилей, которые должны пережить cold start без сети.

## LLM Fallback

LLM fallback теперь принадлежит LLM-профилю:

- `fallback_provider`;
- `fallback_model`;
- `use_livekit_fallback_adapter`;
- `attempt_timeout_sec`;
- `max_retry_per_llm`;
- `retry_interval_sec`;
- `retry_on_chunk_sent`.

Отдельный профиль `fallback_google_lite` больше не является источником backup
модели для LLM. Он оставлен как legacy/future operational fallback, но основная
логика смотрит в выбранный LLM-профиль.

Fast/Complex routing работает так:

- `llm_routing.fast` выбирает LLM-профиль для fast route;
- `llm_routing.complex` выбирает LLM-профиль для complex route;
- fallback каждой route берется из выбранного LLM-профиля.

Если routing profiles не заданы, используется single-LLM flow через
`llm.primary`.

## Runtime Flow

На старте job:

1. `ctx.connect()`;
2. `wait_for_participant()` и извлечение DID;
3. резолв prompt;
4. резолв robot settings по `project -> runtime -> base`;
5. сборка LLM/TTS/STT/Turn/session по resolved settings.

Это важно: настройки клиента из личного кабинета должны быть известны до сборки
pipeline, иначе звонок не сможет реально переключить голос, модель или STT.

## Проверка

Read-only проверка:

```bash
cd agents/main-bot
uv run python scripts/verify_robot_settings_directus.py --env-file .env.local
```

Скрипт не пишет в Directus и не печатает секреты. Он проверяет обязательные
bindings, наличие LLM fallback-полей, snapshot на secret-like ключи и активные
legacy provider env-настройки.
