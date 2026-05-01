-- Rename robot settings storage to permanent names and make override semantics explicit.
--
-- Safe migration properties:
-- - renames only the new robot settings tables/metadata created for the settings UI;
-- - does not alter CallerID, clients, bot_configurations, prompt cache, or robot_incidents;
-- - removes migration suffixes from profile keys;
-- - converts runtime/project config_json into override_json: only profile-specific
--   settings overrides belong there; missing keys fall back to selected component profiles.

begin;

create temp table robot_profile_key_renames (
    old_key text primary key,
    new_key text not null unique
) on commit drop;

insert into robot_profile_key_renames (old_key, new_key)
values
    ('llm_xai_default', 'llm_xai'),
    ('llm_google_gemini_default', 'llm_gemini'),
    ('tts_elevenlabs_v3_default', 'tts_elevenlabs_v3'),
    ('tts_google_gemini_default', 'tts_google_gemini'),
    ('tts_vertex_gemini_default', 'tts_vertex_gemini'),
    ('tts_minimax_ru_default', 'tts_minimax_ru'),
    ('tts_cosyvoice_plus_default', 'tts_cosyvoice_plus'),
    ('tts_sber_default', 'tts_sber_ru'),
    ('stt_deepgram_ru_default', 'stt_deepgram_ru_phone'),
    ('stt_google_ru_default', 'stt_google_ru'),
    ('stt_yandex_default', 'stt_yandex_ru'),
    ('turn_current_env', 'turn_fast_phone'),
    ('fallback_llm_current_env', 'fallback_google_lite');

do $$
begin
    if to_regclass('public.robot_setting_fields') is null
       and to_regclass('public.robot_setting_definitions') is not null then
        alter table public.robot_setting_definitions rename to robot_setting_fields;
    end if;

    if to_regclass('public.robot_component_profiles') is null
       and to_regclass('public.robot_provider_profiles') is not null then
        alter table public.robot_provider_profiles rename to robot_component_profiles;
    end if;

    if to_regclass('public.robot_runtime_profiles') is null
       and to_regclass('public.robot_deployment_profiles') is not null then
        alter table public.robot_deployment_profiles rename to robot_runtime_profiles;
    end if;
end $$;

do $$
begin
    if to_regclass('public.robot_setting_definitions_id_seq') is not null
       and to_regclass('public.robot_setting_fields_id_seq') is null then
        alter sequence public.robot_setting_definitions_id_seq rename to robot_setting_fields_id_seq;
    end if;

    if to_regclass('public.robot_provider_profiles_id_seq') is not null
       and to_regclass('public.robot_component_profiles_id_seq') is null then
        alter sequence public.robot_provider_profiles_id_seq rename to robot_component_profiles_id_seq;
    end if;

    if to_regclass('public.robot_deployment_profiles_id_seq') is not null
       and to_regclass('public.robot_runtime_profiles_id_seq') is null then
        alter sequence public.robot_deployment_profiles_id_seq rename to robot_runtime_profiles_id_seq;
    end if;
end $$;

do $$
begin
    if exists (
        select 1 from information_schema.columns
        where table_schema = 'public'
          and table_name = 'robot_runtime_profiles'
          and column_name = 'deployment_key'
    ) and not exists (
        select 1 from information_schema.columns
        where table_schema = 'public'
          and table_name = 'robot_runtime_profiles'
          and column_name = 'runtime_key'
    ) then
        alter table public.robot_runtime_profiles rename column deployment_key to runtime_key;
    end if;

    if exists (
        select 1 from information_schema.columns
        where table_schema = 'public'
          and table_name = 'robot_runtime_profiles'
          and column_name = 'default_llm_profile'
    ) and not exists (
        select 1 from information_schema.columns
        where table_schema = 'public'
          and table_name = 'robot_runtime_profiles'
          and column_name = 'llm_profile'
    ) then
        alter table public.robot_runtime_profiles rename column default_llm_profile to llm_profile;
    end if;

    if exists (
        select 1 from information_schema.columns
        where table_schema = 'public'
          and table_name = 'robot_runtime_profiles'
          and column_name = 'default_tts_profile'
    ) and not exists (
        select 1 from information_schema.columns
        where table_schema = 'public'
          and table_name = 'robot_runtime_profiles'
          and column_name = 'tts_profile'
    ) then
        alter table public.robot_runtime_profiles rename column default_tts_profile to tts_profile;
    end if;

    if exists (
        select 1 from information_schema.columns
        where table_schema = 'public'
          and table_name = 'robot_runtime_profiles'
          and column_name = 'default_stt_profile'
    ) and not exists (
        select 1 from information_schema.columns
        where table_schema = 'public'
          and table_name = 'robot_runtime_profiles'
          and column_name = 'stt_profile'
    ) then
        alter table public.robot_runtime_profiles rename column default_stt_profile to stt_profile;
    end if;

    if exists (
        select 1 from information_schema.columns
        where table_schema = 'public'
          and table_name = 'robot_runtime_profiles'
          and column_name = 'config_json'
    ) and not exists (
        select 1 from information_schema.columns
        where table_schema = 'public'
          and table_name = 'robot_runtime_profiles'
          and column_name = 'override_json'
    ) then
        alter table public.robot_runtime_profiles rename column config_json to override_json;
    end if;

    if exists (
        select 1 from information_schema.columns
        where table_schema = 'public'
          and table_name = 'robot_project_profiles'
          and column_name = 'deployment_key'
    ) and not exists (
        select 1 from information_schema.columns
        where table_schema = 'public'
          and table_name = 'robot_project_profiles'
          and column_name = 'runtime_key'
    ) then
        alter table public.robot_project_profiles rename column deployment_key to runtime_key;
    end if;

    if exists (
        select 1 from information_schema.columns
        where table_schema = 'public'
          and table_name = 'robot_project_profiles'
          and column_name = 'config_json'
    ) and not exists (
        select 1 from information_schema.columns
        where table_schema = 'public'
          and table_name = 'robot_project_profiles'
          and column_name = 'override_json'
    ) then
        alter table public.robot_project_profiles rename column config_json to override_json;
    end if;
end $$;

alter table public.robot_runtime_profiles
    add column if not exists turn_profile text,
    add column if not exists fallback_profile text;

alter table public.robot_project_profiles
    add column if not exists turn_profile text,
    add column if not exists fallback_profile text;

update public.robot_component_profiles as profile
set profile_key = rename.new_key,
    updated_at = now()
from robot_profile_key_renames as rename
where profile.profile_key = rename.old_key
  and not exists (
      select 1
      from public.robot_component_profiles as existing
      where existing.profile_key = rename.new_key
  );

update public.robot_runtime_profiles as runtime
set llm_profile = coalesce(rename.new_key, runtime.llm_profile)
from robot_profile_key_renames as rename
where runtime.llm_profile = rename.old_key;

update public.robot_runtime_profiles as runtime
set tts_profile = coalesce(rename.new_key, runtime.tts_profile)
from robot_profile_key_renames as rename
where runtime.tts_profile = rename.old_key;

update public.robot_runtime_profiles as runtime
set stt_profile = coalesce(rename.new_key, runtime.stt_profile)
from robot_profile_key_renames as rename
where runtime.stt_profile = rename.old_key;

update public.robot_runtime_profiles as runtime
set turn_profile = coalesce(rename.new_key, runtime.override_json ->> 'turn_profile')
from robot_profile_key_renames as rename
where runtime.override_json ->> 'turn_profile' = rename.old_key;

update public.robot_runtime_profiles as runtime
set fallback_profile = coalesce(rename.new_key, runtime.override_json ->> 'fallback_profile')
from robot_profile_key_renames as rename
where runtime.override_json ->> 'fallback_profile' = rename.old_key;

update public.robot_runtime_profiles
set turn_profile = coalesce(turn_profile, 'turn_fast_phone'),
    fallback_profile = coalesce(fallback_profile, 'fallback_google_lite'),
    override_json = coalesce(override_json, '{}'::jsonb)
        - 'llm_provider'
        - 'tts_provider'
        - 'stt_provider'
        - 'fast_llm_provider'
        - 'complex_llm_provider'
        - 'turn_profile'
        - 'fallback_profile',
    updated_at = now();

update public.robot_project_profiles as project
set llm_profile = coalesce(rename.new_key, project.llm_profile)
from robot_profile_key_renames as rename
where project.llm_profile = rename.old_key;

update public.robot_project_profiles as project
set tts_profile = coalesce(rename.new_key, project.tts_profile)
from robot_profile_key_renames as rename
where project.tts_profile = rename.old_key;

update public.robot_project_profiles as project
set stt_profile = coalesce(rename.new_key, project.stt_profile)
from robot_profile_key_renames as rename
where project.stt_profile = rename.old_key;

update public.robot_project_profiles as project
set turn_profile = coalesce(rename.new_key, project.turn_profile)
from robot_profile_key_renames as rename
where project.turn_profile = rename.old_key;

update public.robot_project_profiles as project
set fallback_profile = coalesce(rename.new_key, project.fallback_profile)
from robot_profile_key_renames as rename
where project.fallback_profile = rename.old_key;

update public.robot_project_profiles
set override_json = coalesce(override_json, '{}'::jsonb),
    updated_at = now();

comment on table public.robot_setting_fields is
    'Справочник полей настроек для UI: ключ, тип, контрол, описание и валидация. Значения настроек здесь не хранятся.';
comment on table public.robot_component_profiles is
    'Общие профили компонентов робота: LLM, TTS, STT, turn, fallback и другие runtime-компоненты. Секреты не хранятся.';
comment on table public.robot_runtime_profiles is
    'Профили среды запуска робота: cloud, asterisk, mac. Выбирают общие component profiles и хранят только server-specific overrides.';
comment on table public.robot_project_profiles is
    'Профили клиента, проекта или DID. Могут выбирать другие component profiles и хранить project-specific overrides.';

comment on column public.robot_runtime_profiles.override_json is
    'Только уникальные переопределения этой среды запуска. Если ключ не указан, берется значение из выбранного component profile.';
comment on column public.robot_project_profiles.override_json is
    'Только уникальные переопределения проекта/клиента/DID. Если ключ не указан, берется значение из runtime profile или component profile.';

do $$
begin
    if exists (select 1 from pg_roles where rolname = 'directus_user') then
        grant select, insert, update, delete on
            public.robot_setting_fields,
            public.robot_component_profiles,
            public.robot_runtime_profiles,
            public.robot_project_profiles
            to directus_user;

        grant usage, select on sequence
            public.robot_setting_fields_id_seq,
            public.robot_component_profiles_id_seq,
            public.robot_runtime_profiles_id_seq,
            public.robot_project_profiles_id_seq
            to directus_user;
    end if;
end $$;

update public.directus_collections
set collection = 'robot_setting_fields',
    icon = 'list_alt',
    note = 'Справочник полей для UI: типы, подписи, описания, правила отображения. Значения настроек здесь не хранятся.'
where collection = 'robot_setting_definitions'
  and not exists (
      select 1 from public.directus_collections
      where collection = 'robot_setting_fields'
  );

update public.directus_collections
set collection = 'robot_component_profiles',
    icon = 'tune',
    note = 'Общие профили компонентов робота: LLM, TTS, STT, turn, fallback. Здесь лежат значения общих профилей, но не секреты.'
where collection = 'robot_provider_profiles'
  and not exists (
      select 1 from public.directus_collections
      where collection = 'robot_component_profiles'
  );

update public.directus_collections
set collection = 'robot_runtime_profiles',
    icon = 'cloud_queue',
    note = 'Профили среды запуска: cloud, asterisk, mac. Выбирают общие component profiles; override_json хранит только уникальные отличия.'
where collection = 'robot_deployment_profiles'
  and not exists (
      select 1 from public.directus_collections
      where collection = 'robot_runtime_profiles'
  );

update public.directus_collections
set note = 'Профили клиента, проекта или DID. Если поле или override не указан, берется значение из runtime profile и общих component profiles.'
where collection = 'robot_project_profiles';

update public.directus_fields
set collection = case collection
    when 'robot_setting_definitions' then 'robot_setting_fields'
    when 'robot_provider_profiles' then 'robot_component_profiles'
    when 'robot_deployment_profiles' then 'robot_runtime_profiles'
    else collection
end
where collection in (
    'robot_setting_definitions',
    'robot_provider_profiles',
    'robot_deployment_profiles'
);

update public.directus_fields
set field = case field
    when 'deployment_key' then 'runtime_key'
    when 'default_llm_profile' then 'llm_profile'
    when 'default_tts_profile' then 'tts_profile'
    when 'default_stt_profile' then 'stt_profile'
    when 'config_json' then 'override_json'
    else field
end
where collection = 'robot_runtime_profiles'
  and field in (
      'deployment_key',
      'default_llm_profile',
      'default_tts_profile',
      'default_stt_profile',
      'config_json'
  );

update public.directus_fields
set field = case field
    when 'deployment_key' then 'runtime_key'
    when 'config_json' then 'override_json'
    else field
end
where collection = 'robot_project_profiles'
  and field in ('deployment_key', 'config_json');

insert into public.directus_fields (
    collection,
    field,
    special,
    interface,
    display,
    readonly,
    hidden,
    sort,
    width,
    required,
    searchable
)
select *
from (
    values
        ('robot_runtime_profiles', 'turn_profile', null, 'input', null, false, false, 10, 'half', false, true),
        ('robot_runtime_profiles', 'fallback_profile', null, 'input', null, false, false, 11, 'half', false, true),
        ('robot_project_profiles', 'turn_profile', null, 'input', null, false, false, 11, 'half', false, true),
        ('robot_project_profiles', 'fallback_profile', null, 'input', null, false, false, 12, 'half', false, true)
) as new_fields (
    collection,
    field,
    special,
    interface,
    display,
    readonly,
    hidden,
    sort,
    width,
    required,
    searchable
)
where not exists (
    select 1
    from public.directus_fields as existing
    where existing.collection = new_fields.collection
      and existing.field = new_fields.field
);

update public.directus_fields
set sort = case field
    when 'id' then 1
    when 'runtime_key' then 2
    when 'display_name' then 3
    when 'agent_name' then 4
    when 'environment' then 5
    when 'status' then 6
    when 'llm_profile' then 7
    when 'tts_profile' then 8
    when 'stt_profile' then 9
    when 'turn_profile' then 10
    when 'fallback_profile' then 11
    when 'override_json' then 12
    when 'active' then 13
    when 'created_at' then 14
    when 'updated_at' then 15
    else sort
end
where collection = 'robot_runtime_profiles';

update public.directus_fields
set sort = case field
    when 'id' then 1
    when 'profile_key' then 2
    when 'display_name' then 3
    when 'client_id' then 4
    when 'did' then 5
    when 'runtime_key' then 6
    when 'status' then 7
    when 'llm_profile' then 8
    when 'tts_profile' then 9
    when 'stt_profile' then 10
    when 'turn_profile' then 11
    when 'fallback_profile' then 12
    when 'prompt_source' then 13
    when 'greeting_source' then 14
    when 'override_json' then 15
    when 'active' then 16
    when 'created_at' then 17
    when 'updated_at' then 18
    else sort
end
where collection = 'robot_project_profiles';

update public.directus_permissions
set collection = case collection
    when 'robot_setting_definitions' then 'robot_setting_fields'
    when 'robot_provider_profiles' then 'robot_component_profiles'
    when 'robot_deployment_profiles' then 'robot_runtime_profiles'
    else collection
end
where collection in (
    'robot_setting_definitions',
    'robot_provider_profiles',
    'robot_deployment_profiles'
);

update public.directus_permissions
set fields = 'id,setting_key,module,scope,label,description,value_type,ui_control,options_json,default_value,validation_json,visible_when_json,sort,requires_restart,sensitive,active,schema_version,created_at,updated_at'
where collection = 'robot_setting_fields'
  and action = 'read';

update public.directus_permissions
set fields = 'id,profile_key,kind,provider,display_name,description,status,config_json,schema_version,active,created_at,updated_at'
where collection = 'robot_component_profiles'
  and action = 'read';

update public.directus_permissions
set fields = 'id,runtime_key,display_name,agent_name,environment,status,llm_profile,tts_profile,stt_profile,turn_profile,fallback_profile,override_json,active,created_at,updated_at'
where collection = 'robot_runtime_profiles'
  and action = 'read';

update public.directus_permissions
set fields = 'id,profile_key,display_name,client_id,did,runtime_key,status,llm_profile,tts_profile,stt_profile,turn_profile,fallback_profile,prompt_source,greeting_source,override_json,active,created_at,updated_at'
where collection = 'robot_project_profiles'
  and action = 'read';

do $$
declare
    old_profiles text;
    missing_runtime_profiles text;
begin
    select string_agg(profile_key, ', ' order by profile_key)
    into old_profiles
    from public.robot_component_profiles
    where profile_key like '%\_default' escape '\'
       or profile_key like '%\_current\_env' escape '\';

    if old_profiles is not null then
        raise exception 'Old profile keys still exist: %', old_profiles;
    end if;

    select string_agg(runtime_key, ', ' order by runtime_key)
    into missing_runtime_profiles
    from public.robot_runtime_profiles
    where llm_profile is null
       or tts_profile is null
       or stt_profile is null
       or turn_profile is null
       or fallback_profile is null;

    if missing_runtime_profiles is not null then
        raise exception 'Runtime profiles missing component profile selectors: %', missing_runtime_profiles;
    end if;
end $$;

commit;
