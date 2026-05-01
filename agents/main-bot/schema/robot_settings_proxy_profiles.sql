-- Create proxy-routed component profiles for the Asterisk runtime.
-- These profiles keep provider secrets in env and only add non-secret egress=proxy.

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
    'llm.egress',
    'llm',
    'profile',
    'Маршрут сети',
    'Как LLM-провайдер должен выходить в интернет для этого профиля: напрямую или через прокси. Для Asterisk можно выбрать proxy.',
    'string',
    'select',
    '{"choices":[{"value":"direct","label":"Direct"},{"value":"proxy","label":"Proxy"}]}'::jsonb,
    to_jsonb(''::text),
    '{}'::jsonb,
    '{}'::jsonb,
    98,
    true,
    false,
    true,
    1
  ),
  (
    'tts.egress',
    'tts',
    'profile',
    'Маршрут сети',
    'Как TTS-провайдер должен выходить в интернет для этого профиля: напрямую или через прокси. Для Asterisk можно выбрать proxy.',
    'string',
    'select',
    '{"choices":[{"value":"direct","label":"Direct"},{"value":"proxy","label":"Proxy"}]}'::jsonb,
    to_jsonb(''::text),
    '{}'::jsonb,
    '{}'::jsonb,
    98,
    true,
    false,
    true,
    1
  ),
  (
    'stt.egress',
    'stt',
    'profile',
    'Маршрут сети',
    'Как STT-провайдер должен выходить в интернет для этого профиля: напрямую или через прокси. Для Asterisk можно выбрать proxy.',
    'string',
    'select',
    '{"choices":[{"value":"direct","label":"Direct"},{"value":"proxy","label":"Proxy"}]}'::jsonb,
    to_jsonb(''::text),
    '{}'::jsonb,
    '{}'::jsonb,
    98,
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

insert into robot_component_profiles (
  profile_key,
  kind,
  provider,
  display_name,
  description,
  status,
  config_json,
  schema_version,
  active
)
select
  'llm_xai_proxy',
  kind,
  provider,
  'xAI Grok · Proxy',
  'xAI LLM profile routed through proxy for the Asterisk runtime.',
  status,
  config_json || jsonb_build_object('egress', 'proxy'),
  schema_version,
  true
from robot_component_profiles
where profile_key = 'llm_xai'
on conflict (profile_key) do update
set
  kind = excluded.kind,
  provider = excluded.provider,
  display_name = excluded.display_name,
  description = excluded.description,
  status = excluded.status,
  config_json = robot_component_profiles.config_json || jsonb_build_object('egress', 'proxy'),
  active = true,
  updated_at = now();

insert into robot_component_profiles (
  profile_key,
  kind,
  provider,
  display_name,
  description,
  status,
  config_json,
  schema_version,
  active
)
select
  'llm_google_proxy',
  kind,
  provider,
  'Google Gemini · Proxy',
  'Google Gemini LLM profile routed through proxy for the Asterisk runtime.',
  status,
  config_json || jsonb_build_object('egress', 'proxy'),
  schema_version,
  true
from robot_component_profiles
where profile_key = 'llm_gemini'
on conflict (profile_key) do update
set
  kind = excluded.kind,
  provider = excluded.provider,
  display_name = excluded.display_name,
  description = excluded.description,
  status = excluded.status,
  config_json = robot_component_profiles.config_json || jsonb_build_object('egress', 'proxy'),
  active = true,
  updated_at = now();

insert into robot_component_profiles (
  profile_key,
  kind,
  provider,
  display_name,
  description,
  status,
  config_json,
  schema_version,
  active
)
select
  'stt_deepgram_proxy',
  kind,
  provider,
  'Deepgram RU Phone · Proxy',
  'Deepgram STT profile routed through proxy for the Asterisk runtime.',
  status,
  config_json || jsonb_build_object('egress', 'proxy'),
  schema_version,
  true
from robot_component_profiles
where profile_key = 'stt_deepgram_ru_phone'
on conflict (profile_key) do update
set
  kind = excluded.kind,
  provider = excluded.provider,
  display_name = excluded.display_name,
  description = excluded.description,
  status = excluded.status,
  config_json = robot_component_profiles.config_json || jsonb_build_object('egress', 'proxy'),
  active = true,
  updated_at = now();

insert into robot_component_profiles (
  profile_key,
  kind,
  provider,
  display_name,
  description,
  status,
  config_json,
  schema_version,
  active
)
select
  'tts_elevenlabs_v3_proxy',
  kind,
  provider,
  'ElevenLabs v3 · Proxy',
  'ElevenLabs v3 TTS profile routed through proxy for the Asterisk runtime.',
  status,
  config_json || jsonb_build_object('egress', 'proxy'),
  schema_version,
  true
from robot_component_profiles
where profile_key = 'tts_elevenlabs_v3'
on conflict (profile_key) do update
set
  kind = excluded.kind,
  provider = excluded.provider,
  display_name = excluded.display_name,
  description = excluded.description,
  status = excluded.status,
  config_json = robot_component_profiles.config_json || jsonb_build_object('egress', 'proxy'),
  active = true,
  updated_at = now();

with desired(owner_type, owner_key, category, slot, profile_key, note, sort, active) as (
  values
    ('runtime', 'asterisk', 'llm', 'primary', 'llm_xai_proxy', 'Asterisk primary LLM through proxy.', 10, true),
    ('runtime', 'asterisk', 'llm_routing', 'fast', 'llm_xai_proxy', 'Asterisk fast LLM through proxy.', 20, true),
    ('runtime', 'asterisk', 'llm_routing', 'complex', 'llm_google_proxy', 'Asterisk complex LLM through proxy.', 30, true),
    ('runtime', 'asterisk', 'tts', 'primary', 'tts_elevenlabs_v3_proxy', 'Asterisk primary TTS through proxy.', 40, true),
    ('runtime', 'asterisk', 'stt', 'primary', 'stt_deepgram_proxy', 'Asterisk primary STT through proxy.', 50, true)
),
updated as (
  update robot_profile_bindings b
  set
    profile_key = d.profile_key,
    note = d.note,
    sort = d.sort,
    active = d.active,
    updated_at = now()
  from desired d
  where b.owner_type = d.owner_type
    and b.owner_key = d.owner_key
    and b.category = d.category
    and b.slot = d.slot
  returning b.owner_type, b.owner_key, b.category, b.slot
)
insert into robot_profile_bindings (
  owner_type,
  owner_key,
  category,
  slot,
  profile_key,
  note,
  sort,
  active
)
select d.owner_type, d.owner_key, d.category, d.slot, d.profile_key, d.note, d.sort, d.active
from desired d
where not exists (
  select 1
  from updated u
  where u.owner_type = d.owner_type
    and u.owner_key = d.owner_key
    and u.category = d.category
    and u.slot = d.slot
);
