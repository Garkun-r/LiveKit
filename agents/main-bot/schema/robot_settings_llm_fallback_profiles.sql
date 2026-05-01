-- Move LLM backup/fallback knobs into LLM component profiles.
-- The fallback component profile remains available for future operational fallback
-- policy, but LLM model fallback is owned by each LLM profile.

insert into robot_setting_fields (
  setting_key,
  module,
  scope,
  label,
  description,
  value_type,
  ui_control,
  options_json,
  default_value,
  validation_json,
  visible_when_json,
  sort,
  requires_restart,
  sensitive,
  active,
  schema_version
)
values
  (
    'llm.fallback_provider',
    'llm',
    'profile',
    'Провайдер запасной модели',
    'Провайдер, который используется как резерв для этого LLM-профиля. Обычно google, если основная модель xAI или Gemini.',
    'string',
    'select',
    '{"choices":[{"value":"google","label":"Google Gemini"},{"value":"xai","label":"xAI Grok"}]}'::jsonb,
    to_jsonb('google'::text),
    '{}'::jsonb,
    '{}'::jsonb,
    86,
    true,
    false,
    true,
    1
  ),
  (
    'llm.fallback_model',
    'llm',
    'profile',
    'Запасная модель',
    'Модель, которая используется как резерв внутри этого LLM-профиля. Например, легкая Gemini-модель для быстрого восстановления ответа.',
    'string',
    'select',
    '{"choices":[{"value":"gemini-3.1-flash-lite-preview","label":"Gemini 3.1 Flash Lite Preview"},{"value":"gemini-3-flash-preview","label":"Gemini 3 Flash Preview"},{"value":"grok-4-1-fast-non-reasoning-latest","label":"Grok 4.1 Fast"}]}'::jsonb,
    to_jsonb('gemini-3.1-flash-lite-preview'::text),
    '{}'::jsonb,
    '{}'::jsonb,
    87,
    true,
    false,
    true,
    1
  ),
  (
    'llm.use_livekit_fallback_adapter',
    'llm',
    'profile',
    'LiveKit FallbackAdapter',
    'Если включено, LiveKit сам переключает этот LLM-профиль на запасную модель при ошибке или таймауте.',
    'boolean',
    'toggle',
    '{}'::jsonb,
    to_jsonb(true),
    '{}'::jsonb,
    '{}'::jsonb,
    88,
    true,
    false,
    true,
    1
  ),
  (
    'llm.attempt_timeout_sec',
    'llm',
    'profile',
    'Таймаут попытки LLM',
    'Сколько секунд ждать текущую LLM-попытку перед переключением на запасную модель через LiveKit FallbackAdapter.',
    'number',
    'slider',
    '{}'::jsonb,
    to_jsonb(2.5),
    '{"min":0.5,"max":15,"step":0.1}'::jsonb,
    '{}'::jsonb,
    90,
    true,
    false,
    true,
    1
  ),
  (
    'llm.max_retry_per_llm',
    'llm',
    'profile',
    'Повторы на одну LLM',
    'Сколько повторов делать на той же LLM перед переходом дальше по fallback-цепочке. Для живого звонка обычно 0.',
    'integer',
    'number',
    '{}'::jsonb,
    to_jsonb(0),
    '{"min":0,"max":3,"step":1}'::jsonb,
    '{}'::jsonb,
    92,
    true,
    false,
    true,
    1
  ),
  (
    'llm.retry_interval_sec',
    'llm',
    'profile',
    'Пауза между повторами LLM',
    'Пауза между retry-попытками LLM. Используется только если повторы больше нуля.',
    'number',
    'slider',
    '{}'::jsonb,
    to_jsonb(0.3),
    '{"min":0,"max":3,"step":0.1}'::jsonb,
    '{}'::jsonb,
    94,
    true,
    false,
    true,
    1
  ),
  (
    'llm.retry_on_chunk_sent',
    'llm',
    'profile',
    'Fallback после первого чанка',
    'Разрешает переключаться на другую LLM даже если первая уже начала отдавать текст. Для голосового звонка безопаснее держать выключенным.',
    'boolean',
    'toggle',
    '{}'::jsonb,
    to_jsonb(false),
    '{}'::jsonb,
    '{}'::jsonb,
    96,
    true,
    false,
    true,
    1
  ),
  (
    'llm_routing.fast_profile',
    'llm_routing',
    'binding',
    'Быстрая LLM',
    'LLM-профиль для быстрых коротких реплик. Fallback берется из выбранного LLM-профиля.',
    'string',
    'select',
    '{"source":"robot_component_profiles","filter":{"kind":"llm"}}'::jsonb,
    to_jsonb(''::text),
    '{}'::jsonb,
    '{}'::jsonb,
    110,
    true,
    false,
    true,
    1
  ),
  (
    'llm_routing.complex_profile',
    'llm_routing',
    'binding',
    'Умная LLM',
    'LLM-профиль для сложных реплик и основного рассуждения. Fallback берется из выбранного LLM-профиля.',
    'string',
    'select',
    '{"source":"robot_component_profiles","filter":{"kind":"llm"}}'::jsonb,
    to_jsonb(''::text),
    '{}'::jsonb,
    '{}'::jsonb,
    112,
    true,
    false,
    true,
    1
  )
on conflict (setting_key) do update
set
  label = excluded.label,
  description = excluded.description,
  value_type = excluded.value_type,
  ui_control = excluded.ui_control,
  options_json = excluded.options_json,
  default_value = excluded.default_value,
  validation_json = excluded.validation_json,
  visible_when_json = excluded.visible_when_json,
  sort = excluded.sort,
  requires_restart = excluded.requires_restart,
  sensitive = excluded.sensitive,
  active = excluded.active,
  schema_version = excluded.schema_version;

with fallback as (
  select config_json
  from robot_component_profiles
  where profile_key = 'fallback_google_lite'
  limit 1
)
update robot_component_profiles p
set config_json =
  p.config_json
  || jsonb_build_object(
    'fallback_provider', coalesce(f.config_json->>'complex_backup_provider', 'google'),
    'fallback_model', coalesce(f.config_json->>'complex_backup_model', 'gemini-3.1-flash-lite-preview'),
    'use_livekit_fallback_adapter', coalesce((f.config_json->>'use_livekit_adapter')::boolean, true),
    'attempt_timeout_sec', 2.5,
    'max_retry_per_llm', 0,
    'retry_interval_sec', 0.3,
    'retry_on_chunk_sent', false
  )
from fallback f
where p.kind = 'llm';
