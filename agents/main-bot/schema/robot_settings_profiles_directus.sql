-- Directus/Postgres storage for robot settings profiles.
--
-- Safe migration properties:
-- - creates only new public.robot_* tables;
-- - does not alter CallerID, clients, bot_configurations, prompt cache, or
--   existing voice runtime tables;
-- - stores settings and UI schema, not provider API keys or secrets;
-- - grants the Livekit service role read-only access for future runtime usage.

create or replace function public.robot_touch_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

create table if not exists public.robot_setting_definitions (
    id bigserial primary key,
    setting_key text not null unique,
    module text not null,
    scope text not null default 'provider_profile',
    label text not null,
    description text,
    value_type text not null,
    ui_control text not null default 'input',
    options_json jsonb not null default '{}'::jsonb,
    default_value jsonb,
    validation_json jsonb not null default '{}'::jsonb,
    visible_when_json jsonb not null default '{}'::jsonb,
    sort integer not null default 100,
    requires_restart boolean not null default false,
    sensitive boolean not null default false,
    active boolean not null default true,
    schema_version integer not null default 1,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint robot_setting_definitions_value_type_check check (
        value_type in ('string', 'number', 'integer', 'boolean', 'json', 'array', 'object')
    )
);

create table if not exists public.robot_provider_profiles (
    id bigserial primary key,
    profile_key text not null unique,
    kind text not null,
    provider text not null,
    display_name text not null,
    description text,
    status text not null default 'draft',
    config_json jsonb not null default '{}'::jsonb,
    schema_version integer not null default 1,
    active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint robot_provider_profiles_kind_check check (
        kind in ('llm', 'tts', 'stt', 'turn', 'fallback', 'voice_prompts', 'egress', 'general')
    ),
    constraint robot_provider_profiles_status_check check (
        status in ('draft', 'published', 'archived')
    )
);

create table if not exists public.robot_deployment_profiles (
    id bigserial primary key,
    deployment_key text not null unique,
    display_name text not null,
    agent_name text not null,
    environment text not null,
    status text not null default 'draft',
    default_llm_profile text,
    default_tts_profile text,
    default_stt_profile text,
    config_json jsonb not null default '{}'::jsonb,
    active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint robot_deployment_profiles_status_check check (
        status in ('draft', 'published', 'archived')
    )
);

create table if not exists public.robot_project_profiles (
    id bigserial primary key,
    profile_key text not null unique,
    display_name text not null,
    client_id text,
    did text,
    deployment_key text,
    status text not null default 'draft',
    llm_profile text,
    tts_profile text,
    stt_profile text,
    prompt_source text,
    greeting_source text,
    config_json jsonb not null default '{}'::jsonb,
    active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint robot_project_profiles_status_check check (
        status in ('draft', 'published', 'archived')
    )
);

create index if not exists robot_setting_definitions_module_idx
    on public.robot_setting_definitions (module);
create index if not exists robot_setting_definitions_scope_idx
    on public.robot_setting_definitions (scope);
create index if not exists robot_provider_profiles_kind_provider_idx
    on public.robot_provider_profiles (kind, provider);
create index if not exists robot_provider_profiles_status_idx
    on public.robot_provider_profiles (status);
create index if not exists robot_deployment_profiles_environment_idx
    on public.robot_deployment_profiles (environment);
create index if not exists robot_project_profiles_client_id_idx
    on public.robot_project_profiles (client_id);
create index if not exists robot_project_profiles_did_idx
    on public.robot_project_profiles (did);
create index if not exists robot_project_profiles_deployment_key_idx
    on public.robot_project_profiles (deployment_key);

drop trigger if exists robot_setting_definitions_touch_updated_at
    on public.robot_setting_definitions;
create trigger robot_setting_definitions_touch_updated_at
before update on public.robot_setting_definitions
for each row execute function public.robot_touch_updated_at();

drop trigger if exists robot_provider_profiles_touch_updated_at
    on public.robot_provider_profiles;
create trigger robot_provider_profiles_touch_updated_at
before update on public.robot_provider_profiles
for each row execute function public.robot_touch_updated_at();

drop trigger if exists robot_deployment_profiles_touch_updated_at
    on public.robot_deployment_profiles;
create trigger robot_deployment_profiles_touch_updated_at
before update on public.robot_deployment_profiles
for each row execute function public.robot_touch_updated_at();

drop trigger if exists robot_project_profiles_touch_updated_at
    on public.robot_project_profiles;
create trigger robot_project_profiles_touch_updated_at
before update on public.robot_project_profiles
for each row execute function public.robot_touch_updated_at();

comment on table public.robot_setting_definitions is
    'Schema/manifest records used by a settings UI to render controls for robot modules.';
comment on table public.robot_provider_profiles is
    'Provider-specific LLM, TTS, STT, fallback, turn, voice, and egress profile configs. Secrets are stored outside this table.';
comment on table public.robot_deployment_profiles is
    'Deployment-level robot profile records for cloud, asterisk, mac, and future workers.';
comment on table public.robot_project_profiles is
    'Project/client/DID-level profile bindings and overrides for robot runtime config.';

do $$
begin
    if exists (select 1 from pg_roles where rolname = 'directus_user') then
        grant usage on schema public to directus_user;
        grant select, insert, update, delete on
            public.robot_setting_definitions,
            public.robot_provider_profiles,
            public.robot_deployment_profiles,
            public.robot_project_profiles
            to directus_user;

        grant usage, select on sequence
            public.robot_setting_definitions_id_seq,
            public.robot_provider_profiles_id_seq,
            public.robot_deployment_profiles_id_seq,
            public.robot_project_profiles_id_seq
            to directus_user;
    end if;
end $$;

insert into public.directus_collections (
    collection,
    icon,
    note,
    hidden,
    singleton,
    accountability,
    collapse
) values
    (
        'robot_setting_definitions',
        'settings',
        'Schema records for robot settings UI controls. No secrets.',
        false,
        false,
        'all',
        'open'
    ),
    (
        'robot_provider_profiles',
        'tune',
        'Provider-specific robot profiles for LLM, TTS, STT, turn, fallback, voice, and egress settings. No secrets.',
        false,
        false,
        'all',
        'open'
    ),
    (
        'robot_deployment_profiles',
        'cloud_queue',
        'Deployment profiles for cloud, asterisk, mac, and future LiveKit workers.',
        false,
        false,
        'all',
        'open'
    ),
    (
        'robot_project_profiles',
        'account_tree',
        'Project/client/DID profile bindings and runtime overrides. No secrets.',
        false,
        false,
        'all',
        'open'
    )
on conflict (collection) do update set
    icon = excluded.icon,
    note = excluded.note,
    hidden = false,
    singleton = false,
    accountability = excluded.accountability,
    collapse = excluded.collapse;

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
        ('robot_setting_definitions', 'id', null, 'input', null, true, true, 1, 'half', false, true),
        ('robot_setting_definitions', 'setting_key', null, 'input', null, false, false, 2, 'half', true, true),
        ('robot_setting_definitions', 'module', null, 'input', null, false, false, 3, 'half', true, true),
        ('robot_setting_definitions', 'scope', null, 'input', null, false, false, 4, 'half', true, true),
        ('robot_setting_definitions', 'label', null, 'input', null, false, false, 5, 'half', true, true),
        ('robot_setting_definitions', 'description', null, 'input-multiline', null, false, false, 6, 'full', false, true),
        ('robot_setting_definitions', 'value_type', null, 'select-dropdown', null, false, false, 7, 'half', true, true),
        ('robot_setting_definitions', 'ui_control', null, 'input', null, false, false, 8, 'half', true, true),
        ('robot_setting_definitions', 'options_json', null, 'input-code', null, false, false, 9, 'full', true, true),
        ('robot_setting_definitions', 'default_value', null, 'input-code', null, false, false, 10, 'full', false, true),
        ('robot_setting_definitions', 'validation_json', null, 'input-code', null, false, false, 11, 'full', true, true),
        ('robot_setting_definitions', 'visible_when_json', null, 'input-code', null, false, false, 12, 'full', true, true),
        ('robot_setting_definitions', 'sort', null, 'input', null, false, false, 13, 'half', true, true),
        ('robot_setting_definitions', 'requires_restart', null, 'boolean', null, false, false, 14, 'half', true, true),
        ('robot_setting_definitions', 'sensitive', null, 'boolean', null, false, false, 15, 'half', true, true),
        ('robot_setting_definitions', 'active', null, 'boolean', null, false, false, 16, 'half', true, true),
        ('robot_setting_definitions', 'schema_version', null, 'input', null, false, false, 17, 'half', true, true),
        ('robot_setting_definitions', 'created_at', null, 'datetime', 'datetime', true, false, 18, 'half', false, true),
        ('robot_setting_definitions', 'updated_at', null, 'datetime', 'datetime', true, false, 19, 'half', false, true),

        ('robot_provider_profiles', 'id', null, 'input', null, true, true, 1, 'half', false, true),
        ('robot_provider_profiles', 'profile_key', null, 'input', null, false, false, 2, 'half', true, true),
        ('robot_provider_profiles', 'kind', null, 'select-dropdown', null, false, false, 3, 'half', true, true),
        ('robot_provider_profiles', 'provider', null, 'input', null, false, false, 4, 'half', true, true),
        ('robot_provider_profiles', 'display_name', null, 'input', null, false, false, 5, 'half', true, true),
        ('robot_provider_profiles', 'description', null, 'input-multiline', null, false, false, 6, 'full', false, true),
        ('robot_provider_profiles', 'status', null, 'select-dropdown', null, false, false, 7, 'half', true, true),
        ('robot_provider_profiles', 'config_json', null, 'input-code', null, false, false, 8, 'full', true, true),
        ('robot_provider_profiles', 'schema_version', null, 'input', null, false, false, 9, 'half', true, true),
        ('robot_provider_profiles', 'active', null, 'boolean', null, false, false, 10, 'half', true, true),
        ('robot_provider_profiles', 'created_at', null, 'datetime', 'datetime', true, false, 11, 'half', false, true),
        ('robot_provider_profiles', 'updated_at', null, 'datetime', 'datetime', true, false, 12, 'half', false, true),

        ('robot_deployment_profiles', 'id', null, 'input', null, true, true, 1, 'half', false, true),
        ('robot_deployment_profiles', 'deployment_key', null, 'input', null, false, false, 2, 'half', true, true),
        ('robot_deployment_profiles', 'display_name', null, 'input', null, false, false, 3, 'half', true, true),
        ('robot_deployment_profiles', 'agent_name', null, 'input', null, false, false, 4, 'half', true, true),
        ('robot_deployment_profiles', 'environment', null, 'input', null, false, false, 5, 'half', true, true),
        ('robot_deployment_profiles', 'status', null, 'select-dropdown', null, false, false, 6, 'half', true, true),
        ('robot_deployment_profiles', 'default_llm_profile', null, 'input', null, false, false, 7, 'half', false, true),
        ('robot_deployment_profiles', 'default_tts_profile', null, 'input', null, false, false, 8, 'half', false, true),
        ('robot_deployment_profiles', 'default_stt_profile', null, 'input', null, false, false, 9, 'half', false, true),
        ('robot_deployment_profiles', 'config_json', null, 'input-code', null, false, false, 10, 'full', true, true),
        ('robot_deployment_profiles', 'active', null, 'boolean', null, false, false, 11, 'half', true, true),
        ('robot_deployment_profiles', 'created_at', null, 'datetime', 'datetime', true, false, 12, 'half', false, true),
        ('robot_deployment_profiles', 'updated_at', null, 'datetime', 'datetime', true, false, 13, 'half', false, true),

        ('robot_project_profiles', 'id', null, 'input', null, true, true, 1, 'half', false, true),
        ('robot_project_profiles', 'profile_key', null, 'input', null, false, false, 2, 'half', true, true),
        ('robot_project_profiles', 'display_name', null, 'input', null, false, false, 3, 'half', true, true),
        ('robot_project_profiles', 'client_id', null, 'input', null, false, false, 4, 'half', false, true),
        ('robot_project_profiles', 'did', null, 'input', null, false, false, 5, 'half', false, true),
        ('robot_project_profiles', 'deployment_key', null, 'input', null, false, false, 6, 'half', false, true),
        ('robot_project_profiles', 'status', null, 'select-dropdown', null, false, false, 7, 'half', true, true),
        ('robot_project_profiles', 'llm_profile', null, 'input', null, false, false, 8, 'half', false, true),
        ('robot_project_profiles', 'tts_profile', null, 'input', null, false, false, 9, 'half', false, true),
        ('robot_project_profiles', 'stt_profile', null, 'input', null, false, false, 10, 'half', false, true),
        ('robot_project_profiles', 'prompt_source', null, 'input', null, false, false, 11, 'half', false, true),
        ('robot_project_profiles', 'greeting_source', null, 'input', null, false, false, 12, 'half', false, true),
        ('robot_project_profiles', 'config_json', null, 'input-code', null, false, false, 13, 'full', true, true),
        ('robot_project_profiles', 'active', null, 'boolean', null, false, false, 14, 'half', true, true),
        ('robot_project_profiles', 'created_at', null, 'datetime', 'datetime', true, false, 15, 'half', false, true),
        ('robot_project_profiles', 'updated_at', null, 'datetime', 'datetime', true, false, 16, 'half', false, true)
) as metadata(
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
    from public.directus_fields existing
    where existing.collection = metadata.collection
      and existing.field = metadata.field
);

do $$
declare
    livekit_policy uuid;
    collection_name text;
    read_fields text;
begin
    select p.id
    into livekit_policy
    from public.directus_policies p
    join public.directus_access a on a.policy = p.id
    join public.directus_roles r on r.id = a.role
    where r.name = 'Livekit'
    order by (p.name = 'Livekit prompt cache access') desc, p.name
    limit 1;

    if livekit_policy is null then
        raise exception 'Directus role "Livekit" has no attached policy';
    end if;

    foreach collection_name in array array[
        'robot_setting_definitions',
        'robot_provider_profiles',
        'robot_deployment_profiles',
        'robot_project_profiles'
    ]
    loop
        select string_agg(field, ',' order by sort)
        into read_fields
        from public.directus_fields
        where collection = collection_name;

        insert into public.directus_permissions (
            collection,
            action,
            permissions,
            validation,
            presets,
            fields,
            policy
        )
        select collection_name, 'read', null, null, null, read_fields, livekit_policy
        where not exists (
            select 1
            from public.directus_permissions
            where collection = collection_name
              and action = 'read'
              and policy = livekit_policy
        );

        update public.directus_permissions
        set fields = read_fields
        where collection = collection_name
          and action = 'read'
          and policy = livekit_policy;
    end loop;
end $$;

insert into public.robot_provider_profiles (
    profile_key,
    kind,
    provider,
    display_name,
    description,
    status,
    config_json
) values
    (
        'llm_xai_default',
        'llm',
        'xai',
        'xAI Grok default',
        'Draft non-secret profile based on the current robot env.',
        'draft',
        '{"model":"grok-4-1-fast-non-reasoning-latest","temperature":0.3,"base_url":"https://api.x.ai/v1","enable_tools":false}'::jsonb
    ),
    (
        'llm_google_gemini_default',
        'llm',
        'google',
        'Google Gemini default',
        'Draft non-secret Gemini profile for primary or fallback LLM use.',
        'draft',
        '{"model":"gemini-3-flash-preview","fallback_model":"gemini-3.1-flash-lite-preview","temperature":0.7,"max_output_tokens":512,"top_p":1,"thinking_level":"minimal"}'::jsonb
    ),
    (
        'tts_elevenlabs_v3_default',
        'tts',
        'elevenlabs',
        'ElevenLabs v3 default',
        'Draft non-secret ElevenLabs profile based on the current robot env.',
        'draft',
        '{"model":"eleven_v3","voice_id":"wF58OrxELqJ5nFJxXiva","output_format":"pcm_24000","use_stream_input":true,"apply_text_normalization":"auto","language":"","min_sentence_len":6,"stream_context_len":2}'::jsonb
    ),
    (
        'tts_minimax_ru_default',
        'tts',
        'minimax',
        'MiniMax Russian default',
        'Draft non-secret MiniMax profile based on the current robot env.',
        'draft',
        '{"model":"speech-2.8-turbo","voice_id":"moss_audio_43d3c43e-3a2d-11f1-b47e-928b88df9451","base_url":"https://api-uw.minimax.io","language_boost":"Russian","speed":1.2,"volume":1.0,"pitch":0,"format":"mp3","sample_rate":24000,"bitrate":128000,"channel":1,"min_sentence_len":4,"stream_context_len":1}'::jsonb
    ),
    (
        'tts_cosyvoice_plus_default',
        'tts',
        'cosyvoice',
        'CosyVoice plus default',
        'Draft non-secret CosyVoice profile based on the current robot env.',
        'draft',
        '{"profile":"cosyvoice_cn_plus_quality","transport":"websocket","region":"cn-beijing","ws_url":"wss://dashscope.aliyuncs.com/api-ws/v1/inference","model":"cosyvoice-v3.5-plus","voice_mode":"preset","voice_id":"cosyvoice-v3.5-plus-v35p0001-576e62b254ea4eafb6c184dc43f7674a","clone_voice_id":"cosyvoice-v3.5-plus-v35p0001-576e62b254ea4eafb6c184dc43f7674a","design_voice_id":"cosyvoice-v3.5-plus-v35p0001-576e62b254ea4eafb6c184dc43f7674a","format":"pcm","sample_rate":24000,"rate":1.1,"pitch":1.0,"volume":50,"connection_reuse":true,"playback_on_first_chunk":true,"min_sentence_len":4,"stream_context_len":1}'::jsonb
    ),
    (
        'stt_deepgram_ru_default',
        'stt',
        'deepgram',
        'Deepgram Russian default',
        'Draft non-secret Deepgram profile based on the current robot env.',
        'draft',
        '{"model":"nova-3","language":"ru","endpointing_ms":90}'::jsonb
    )
on conflict (profile_key) do nothing;

insert into public.robot_deployment_profiles (
    deployment_key,
    display_name,
    agent_name,
    environment,
    status,
    default_llm_profile,
    default_tts_profile,
    default_stt_profile,
    config_json
) values
    (
        'cloud',
        'LiveKit Cloud',
        'main-bot',
        'cloud',
        'draft',
        'llm_xai_default',
        'tts_elevenlabs_v3_default',
        'stt_deepgram_ru_default',
        '{"livekit_self_hosted":false}'::jsonb
    ),
    (
        'asterisk',
        'Asterisk local LiveKit',
        'main-bot',
        'asterisk',
        'draft',
        'llm_xai_default',
        'tts_elevenlabs_v3_default',
        'stt_deepgram_ru_default',
        '{"livekit_self_hosted":true}'::jsonb
    ),
    (
        'mac',
        'Mac development',
        'main-bot',
        'mac',
        'draft',
        'llm_xai_default',
        'tts_elevenlabs_v3_default',
        'stt_deepgram_ru_default',
        '{"livekit_self_hosted":false}'::jsonb
    )
on conflict (deployment_key) do nothing;

insert into public.robot_setting_definitions (
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
    sort,
    requires_restart,
    sensitive
) values
    (
        'llm.provider',
        'llm',
        'provider_profile',
        'LLM provider',
        'Primary LLM provider used by this profile.',
        'string',
        'select',
        '{"choices":["google","xai"]}'::jsonb,
        '"xai"'::jsonb,
        '{}'::jsonb,
        10,
        false,
        false
    ),
    (
        'llm.model',
        'llm',
        'provider_profile',
        'LLM model',
        'Provider model id. Keep the value provider-specific.',
        'string',
        'input',
        '{}'::jsonb,
        '"grok-4-1-fast-non-reasoning-latest"'::jsonb,
        '{}'::jsonb,
        20,
        false,
        false
    ),
    (
        'llm.temperature',
        'llm',
        'provider_profile',
        'LLM temperature',
        'Sampling temperature for the model.',
        'number',
        'slider',
        '{}'::jsonb,
        '0.3'::jsonb,
        '{"min":0,"max":2,"step":0.1}'::jsonb,
        30,
        false,
        false
    ),
    (
        'llm.enable_tools',
        'llm',
        'provider_profile',
        'Enable tools',
        'Whether this LLM profile allows function tools.',
        'boolean',
        'toggle',
        '{}'::jsonb,
        'false'::jsonb,
        '{}'::jsonb,
        40,
        false,
        false
    ),
    (
        'tts.provider',
        'tts',
        'provider_profile',
        'TTS provider',
        'Speech synthesis provider used by this voice profile.',
        'string',
        'select',
        '{"choices":["elevenlabs","google","vertex","minimax","cosyvoice","tbank","sber"]}'::jsonb,
        '"elevenlabs"'::jsonb,
        '{}'::jsonb,
        100,
        false,
        false
    ),
    (
        'tts.model',
        'tts',
        'provider_profile',
        'TTS model',
        'Provider-specific synthesis model id.',
        'string',
        'input',
        '{}'::jsonb,
        '"eleven_v3"'::jsonb,
        '{}'::jsonb,
        110,
        false,
        false
    ),
    (
        'tts.voice_id',
        'tts',
        'provider_profile',
        'Voice id',
        'Provider-specific voice id or voice name. This is not an API secret.',
        'string',
        'input',
        '{}'::jsonb,
        '""'::jsonb,
        '{}'::jsonb,
        120,
        false,
        false
    ),
    (
        'tts.speed',
        'tts',
        'provider_profile',
        'Voice speed',
        'Provider-specific speaking speed/rate where supported.',
        'number',
        'slider',
        '{}'::jsonb,
        '1.0'::jsonb,
        '{"min":0.5,"max":2,"step":0.05}'::jsonb,
        130,
        false,
        false
    ),
    (
        'stt.provider',
        'stt',
        'provider_profile',
        'STT provider',
        'Speech recognition provider used by this profile.',
        'string',
        'select',
        '{"choices":["deepgram","inference","google","yandex","tbank"]}'::jsonb,
        '"deepgram"'::jsonb,
        '{}'::jsonb,
        200,
        false,
        false
    ),
    (
        'stt.model',
        'stt',
        'provider_profile',
        'STT model',
        'Provider-specific recognition model id.',
        'string',
        'input',
        '{}'::jsonb,
        '"nova-3"'::jsonb,
        '{}'::jsonb,
        210,
        false,
        false
    ),
    (
        'stt.language',
        'stt',
        'provider_profile',
        'STT language',
        'Recognition language code.',
        'string',
        'input',
        '{}'::jsonb,
        '"ru"'::jsonb,
        '{}'::jsonb,
        220,
        false,
        false
    ),
    (
        'stt.endpointing_ms',
        'stt',
        'provider_profile',
        'Endpointing ms',
        'Silence duration before STT finalization where the provider supports it.',
        'integer',
        'slider',
        '{}'::jsonb,
        '90'::jsonb,
        '{"min":25,"max":1000,"step":5}'::jsonb,
        230,
        false,
        false
    ),
    (
        'turn.detection_mode',
        'turn',
        'provider_profile',
        'Turn detection mode',
        'How the robot decides that the user turn has ended.',
        'string',
        'select',
        '{"choices":["vad","stt","multilingual"]}'::jsonb,
        '"vad"'::jsonb,
        '{}'::jsonb,
        300,
        false,
        false
    ),
    (
        'turn.endpointing_mode',
        'turn',
        'provider_profile',
        'Endpointing mode',
        'Fixed or dynamic endpointing delay behavior.',
        'string',
        'select',
        '{"choices":["fixed","dynamic"]}'::jsonb,
        '"fixed"'::jsonb,
        '{}'::jsonb,
        310,
        false,
        false
    ),
    (
        'turn.min_endpointing_delay',
        'turn',
        'provider_profile',
        'Minimum endpointing delay',
        'Minimum delay in seconds before the robot answers.',
        'number',
        'slider',
        '{}'::jsonb,
        '0.25'::jsonb,
        '{"min":0,"max":2,"step":0.05}'::jsonb,
        320,
        false,
        false
    ),
    (
        'turn.max_endpointing_delay',
        'turn',
        'provider_profile',
        'Maximum endpointing delay',
        'Maximum delay in seconds before the robot answers.',
        'number',
        'slider',
        '{}'::jsonb,
        '0.5'::jsonb,
        '{"min":0,"max":5,"step":0.05}'::jsonb,
        330,
        false,
        false
    ),
    (
        'turn.preemptive_generation',
        'turn',
        'provider_profile',
        'Preemptive generation',
        'Whether the robot may start generation before final turn confirmation.',
        'boolean',
        'toggle',
        '{}'::jsonb,
        'true'::jsonb,
        '{}'::jsonb,
        340,
        false,
        false
    )
on conflict (setting_key) do nothing;
