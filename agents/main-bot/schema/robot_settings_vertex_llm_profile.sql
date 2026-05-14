-- Add Directus LLM profiles for Gemini 3.1 Flash-Lite and Vertex AI backups.
--
-- This migration stores only non-secret runtime settings. Provider credentials
-- stay in env / LiveKit Cloud secrets and are referenced only by non-secret
-- *_ref metadata fields.

insert into public.robot_setting_fields (
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
    'llm.location',
    'llm',
    'provider_profile',
    'LLM Vertex location',
    'Vertex AI location/endpoint for Google Gemini LLM profiles. Use eu for the tested European multi-region endpoint; Gemini 3 Flash Preview requires global.',
    'string',
    'select',
    '{
      "choices": [
        {"value": "eu", "label": "Europe multi-region"},
        {"value": "global", "label": "Global"},
        {"value": "us", "label": "United States multi-region"},
        {"value": "europe-west1", "label": "Belgium"},
        {"value": "europe-west2", "label": "London"},
        {"value": "europe-west3", "label": "Frankfurt"},
        {"value": "europe-west4", "label": "Netherlands"},
        {"value": "europe-west6", "label": "Zurich"},
        {"value": "europe-north1", "label": "Finland"},
        {"value": "europe-central2", "label": "Warsaw"},
        {"value": "europe-west8", "label": "Milan"},
        {"value": "europe-southwest1", "label": "Madrid"},
        {"value": "europe-west9", "label": "Paris"}
      ]
    }'::jsonb,
    to_jsonb('eu'::text),
    '{}'::jsonb,
    '{}'::jsonb,
    25,
    false,
    false,
    true,
    1
  ),
  (
    'llm.fallback_location',
    'llm',
    'provider_profile',
    'Fallback Vertex location',
    'Vertex AI location for the fallback LLM when fallback_provider is google_vertex.',
    'string',
    'select',
    '{
      "choices": [
        {"value": "eu", "label": "Europe multi-region"},
        {"value": "global", "label": "Global"},
        {"value": "us", "label": "United States multi-region"}
      ]
    }'::jsonb,
    to_jsonb('eu'::text),
    '{}'::jsonb,
    '{"fallback_provider":"google_vertex"}'::jsonb,
    88,
    true,
    false,
    true,
    1
  ),
  (
    'llm.fallback_egress',
    'llm',
    'provider_profile',
    'Fallback network route',
    'Network route for the fallback LLM: direct or proxy. Use proxy only for profiles that must route through the external proxy.',
    'string',
    'select',
    '{"choices":[{"value":"direct","label":"Direct"},{"value":"proxy","label":"Proxy"}]}'::jsonb,
    to_jsonb('direct'::text),
    '{}'::jsonb,
    '{}'::jsonb,
    89,
    true,
    false,
    true,
    1
  )
on conflict (setting_key) do update
set options_json = excluded.options_json,
    default_value = excluded.default_value,
    description = excluded.description,
    ui_control = excluded.ui_control,
    visible_when_json = excluded.visible_when_json,
    requires_restart = excluded.requires_restart,
    active = true,
    updated_at = now();

update public.robot_setting_fields
set options_json = '{"choices":["google","google_vertex","xai"]}'::jsonb,
    updated_at = now()
where setting_key = 'llm.provider';

update public.robot_setting_fields
set options_json = '{
      "choices": [
        {"value": "google", "label": "Google Gemini"},
        {"value": "google_vertex", "label": "Google Vertex Gemini"},
        {"value": "xai", "label": "xAI Grok"}
      ]
    }'::jsonb,
    updated_at = now()
where setting_key = 'llm.fallback_provider';

update public.robot_setting_fields
set default_value = to_jsonb('gemini-3.1-flash-lite'::text),
    options_json = '{
      "choices": [
        {"value": "gemini-3.1-flash-lite", "label": "Gemini 3.1 Flash Lite"},
        {"value": "gemini-3.1-flash-lite-preview", "label": "Gemini 3.1 Flash Lite Preview"},
        {"value": "gemini-3-flash-preview", "label": "Gemini 3 Flash Preview"},
        {"value": "grok-4-1-fast-non-reasoning-latest", "label": "Grok 4.1 Fast"}
      ]
    }'::jsonb,
    updated_at = now()
where setting_key = 'llm.fallback_model';

with desired_profiles (
  profile_key,
  provider,
  display_name,
  description,
  config_json
) as (
  values
    (
      'llm_gemini_31_flash_lite',
      'google',
      'Gemini 3.1 Flash Lite',
      'Direct Gemini API profile using the GA gemini-3.1-flash-lite model. Backup is Vertex AI Gemini 3.1 Flash Lite on eu.',
      '{
        "api_key_ref": "GOOGLE_API_KEY",
        "provider": "google",
        "model": "gemini-3.1-flash-lite",
        "egress": "direct",
        "temperature": 0.7,
        "max_output_tokens": 512,
        "top_p": 1,
        "thinking_level": "minimal",
        "fallback_provider": "google_vertex",
        "fallback_model": "gemini-3.1-flash-lite",
        "fallback_location": "eu",
        "fallback_egress": "direct",
        "use_livekit_fallback_adapter": true,
        "attempt_timeout_sec": 2.5,
        "max_retry_per_llm": 0,
        "retry_interval_sec": 0.3,
        "retry_on_chunk_sent": false
      }'::jsonb
    ),
    (
      'llm_gemini_vertex_31_flash_lite',
      'google_vertex',
      'Gemini 3.1 Flash Lite · Vertex EU',
      'Vertex AI Gemini LLM profile using the GA gemini-3.1-flash-lite model on the eu endpoint. Backup is direct Gemini API.',
      '{
        "credentials_ref": "GOOGLE_TTS_CREDENTIALS_FILE or GOOGLE_APPLICATION_CREDENTIALS",
        "provider": "google_vertex",
        "model": "gemini-3.1-flash-lite",
        "location": "eu",
        "egress": "direct",
        "temperature": 0.7,
        "max_output_tokens": 512,
        "top_p": 1,
        "thinking_level": "minimal",
        "fallback_provider": "google",
        "fallback_model": "gemini-3.1-flash-lite",
        "fallback_egress": "direct",
        "use_livekit_fallback_adapter": true,
        "attempt_timeout_sec": 2.5,
        "max_retry_per_llm": 0,
        "retry_interval_sec": 0.3,
        "retry_on_chunk_sent": false
      }'::jsonb
    ),
    (
      'llm_gemini_vertex_3_flash',
      'google_vertex',
      'Gemini 3 Flash · Vertex Global',
      'Vertex AI Gemini 3 Flash Preview profile. Gemini 3 Flash is still preview and currently uses model ID gemini-3-flash-preview on global. Backup is Vertex AI Gemini 3.1 Flash Lite on eu.',
      '{
        "credentials_ref": "GOOGLE_TTS_CREDENTIALS_FILE or GOOGLE_APPLICATION_CREDENTIALS",
        "provider": "google_vertex",
        "model": "gemini-3-flash-preview",
        "location": "global",
        "egress": "direct",
        "temperature": 0.7,
        "max_output_tokens": 512,
        "top_p": 1,
        "thinking_level": "minimal",
        "fallback_provider": "google_vertex",
        "fallback_model": "gemini-3.1-flash-lite",
        "fallback_location": "eu",
        "fallback_egress": "direct",
        "use_livekit_fallback_adapter": true,
        "attempt_timeout_sec": 2.5,
        "max_retry_per_llm": 0,
        "retry_interval_sec": 0.3,
        "retry_on_chunk_sent": false
      }'::jsonb
    ),
    (
      'llm_gemini_31_flash_lite_proxy',
      'google',
      'Gemini 3.1 Flash Lite · Proxy',
      'Proxy-routed Gemini API profile using the GA gemini-3.1-flash-lite model. Backup is proxy-routed Vertex AI Gemini 3.1 Flash Lite on eu.',
      '{
        "api_key_ref": "GOOGLE_API_KEY",
        "provider": "google",
        "model": "gemini-3.1-flash-lite",
        "egress": "proxy",
        "temperature": 0.7,
        "max_output_tokens": 512,
        "top_p": 1,
        "thinking_level": "minimal",
        "fallback_provider": "google_vertex",
        "fallback_model": "gemini-3.1-flash-lite",
        "fallback_location": "eu",
        "fallback_egress": "proxy",
        "use_livekit_fallback_adapter": true,
        "attempt_timeout_sec": 2.5,
        "max_retry_per_llm": 0,
        "retry_interval_sec": 0.3,
        "retry_on_chunk_sent": false
      }'::jsonb
    )
)
insert into public.robot_component_profiles (
  profile_key,
  kind,
  provider,
  display_name,
  description,
  status,
  config_json,
  active,
  schema_version
)
select
  profile_key,
  'llm',
  provider,
  display_name,
  description,
  'published',
  config_json,
  true,
  1
from desired_profiles
on conflict (profile_key) do update
set provider = excluded.provider,
    display_name = excluded.display_name,
    description = excluded.description,
    status = excluded.status,
    config_json = excluded.config_json,
    active = true,
    schema_version = excluded.schema_version,
    updated_at = now();

update public.robot_setting_fields
set default_value = to_jsonb('gemini-3.1-flash-lite'::text),
    updated_at = now()
where setting_key in ('fallback.fast_backup_model', 'fallback.complex_backup_model')
  and default_value = to_jsonb('gemini-3.1-flash-lite-preview'::text);

update public.robot_component_profiles
set config_json = jsonb_set(
    config_json,
    '{fallback_model}',
    to_jsonb('gemini-3.1-flash-lite'::text),
    true
  ),
  updated_at = now()
where kind = 'llm'
  and config_json ->> 'fallback_model' = 'gemini-3.1-flash-lite-preview';

update public.robot_component_profiles
set config_json = jsonb_set(
    config_json,
    '{model}',
    to_jsonb('gemini-3.1-flash-lite'::text),
    true
  ),
  updated_at = now()
where kind = 'llm'
  and config_json ->> 'model' = 'gemini-3.1-flash-lite-preview';

update public.robot_component_profiles
set config_json = jsonb_set(
    jsonb_set(
      config_json,
      '{fast_backup_model}',
      to_jsonb('gemini-3.1-flash-lite'::text),
      true
    ),
    '{complex_backup_model}',
    to_jsonb('gemini-3.1-flash-lite'::text),
    true
  ),
  updated_at = now()
where kind = 'fallback'
  and (
    config_json ->> 'fast_backup_model' = 'gemini-3.1-flash-lite-preview'
    or config_json ->> 'complex_backup_model' = 'gemini-3.1-flash-lite-preview'
  );

update public.robot_component_profiles
set config_json = config_json || '{
    "fallback_provider": "google_vertex",
    "fallback_model": "gemini-3.1-flash-lite",
    "fallback_location": "eu",
    "fallback_egress": "direct"
  }'::jsonb,
  updated_at = now()
where profile_key = 'llm_gemini';

update public.robot_component_profiles
set config_json = config_json || '{
    "fallback_provider": "google_vertex",
    "fallback_model": "gemini-3.1-flash-lite",
    "fallback_location": "eu",
    "fallback_egress": "proxy"
  }'::jsonb,
  updated_at = now()
where profile_key = 'llm_google_proxy';

update public.robot_component_profiles
set config_json = config_json || '{
    "fast_backup_provider": "google_vertex",
    "fast_backup_model": "gemini-3.1-flash-lite",
    "complex_backup_provider": "google_vertex",
    "complex_backup_model": "gemini-3.1-flash-lite",
    "use_livekit_adapter": true
  }'::jsonb,
  updated_at = now()
where profile_key = 'fallback_google_lite';

update public.robot_profile_bindings
set profile_key = 'llm_gemini_31_flash_lite',
  note = 'Base/cloud: быстрая ветка Gemini 3.1 Flash Lite с Vertex fallback',
  updated_at = now()
where owner_type = 'runtime'
  and owner_key = 'base'
  and category = 'llm_routing'
  and slot = 'fast';

update public.robot_setting_fields
set default_value = to_jsonb('google_vertex'::text),
  updated_at = now()
where setting_key in (
  'fallback.fast_backup_provider',
  'fallback.complex_backup_provider',
  'llm.fallback_provider'
);
