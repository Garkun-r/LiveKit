-- Add profile bindings and make base runtime the source of inherited defaults.
--
-- Safe migration properties:
-- - operates only on the new robot settings tables and Directus metadata;
-- - does not alter CallerID, clients, bot_configurations, prompt cache, or robot_incidents;
-- - preserves current selected profiles by moving them into robot_profile_bindings;
-- - renames the old cloud runtime key to livekit_cloud and creates base as
--   the inherited "Основная" profile.

begin;

create temp table robot_runtime_selectors_before (
    old_runtime_key text primary key,
    runtime_key text not null,
    llm_profile text,
    fast_llm_profile text,
    complex_llm_profile text,
    tts_profile text,
    stt_profile text,
    turn_profile text,
    fallback_profile text
) on commit drop;

insert into robot_runtime_selectors_before (
    old_runtime_key,
    runtime_key,
    llm_profile,
    fast_llm_profile,
    complex_llm_profile,
    tts_profile,
    stt_profile,
    turn_profile,
    fallback_profile
)
select
    runtime_key,
    case when runtime_key = 'cloud' then 'livekit_cloud' else runtime_key end,
    llm_profile,
    fast_llm_profile,
    complex_llm_profile,
    tts_profile,
    stt_profile,
    turn_profile,
    fallback_profile
from public.robot_runtime_profiles;

create temp table robot_base_selectors (
    llm_profile text,
    fast_llm_profile text,
    complex_llm_profile text,
    tts_profile text,
    stt_profile text,
    turn_profile text,
    fallback_profile text
) on commit drop;

insert into robot_base_selectors (
    llm_profile,
    fast_llm_profile,
    complex_llm_profile,
    tts_profile,
    stt_profile,
    turn_profile,
    fallback_profile
)
select
    coalesce(
        (select llm_profile from robot_runtime_selectors_before where old_runtime_key = 'cloud'),
        (select llm_profile from robot_runtime_selectors_before where old_runtime_key = 'livekit_cloud'),
        'llm_xai'
    ),
    coalesce(
        (select fast_llm_profile from robot_runtime_selectors_before where old_runtime_key = 'cloud'),
        (select fast_llm_profile from robot_runtime_selectors_before where old_runtime_key = 'livekit_cloud')
    ),
    coalesce(
        (select complex_llm_profile from robot_runtime_selectors_before where old_runtime_key = 'cloud'),
        (select complex_llm_profile from robot_runtime_selectors_before where old_runtime_key = 'livekit_cloud')
    ),
    coalesce(
        (select tts_profile from robot_runtime_selectors_before where old_runtime_key = 'cloud'),
        (select tts_profile from robot_runtime_selectors_before where old_runtime_key = 'livekit_cloud'),
        'tts_elevenlabs_v3'
    ),
    coalesce(
        (select stt_profile from robot_runtime_selectors_before where old_runtime_key = 'cloud'),
        (select stt_profile from robot_runtime_selectors_before where old_runtime_key = 'livekit_cloud'),
        'stt_deepgram_ru_phone'
    ),
    coalesce(
        (select turn_profile from robot_runtime_selectors_before where old_runtime_key = 'cloud'),
        (select turn_profile from robot_runtime_selectors_before where old_runtime_key = 'livekit_cloud'),
        'turn_fast_phone'
    ),
    coalesce(
        (select fallback_profile from robot_runtime_selectors_before where old_runtime_key = 'cloud'),
        (select fallback_profile from robot_runtime_selectors_before where old_runtime_key = 'livekit_cloud'),
        'fallback_google_lite'
    );

update public.robot_runtime_profiles
set runtime_key = 'livekit_cloud',
    display_name = 'LiveKit Cloud',
    environment = 'livekit_cloud',
    updated_at = now()
where runtime_key = 'cloud'
  and not exists (
      select 1 from public.robot_runtime_profiles where runtime_key = 'livekit_cloud'
  );

insert into public.robot_runtime_profiles (
    runtime_key,
    display_name,
    agent_name,
    environment,
    status,
    llm_profile,
    fast_llm_profile,
    complex_llm_profile,
    tts_profile,
    stt_profile,
    turn_profile,
    fallback_profile,
    override_json,
    active
)
select
    'base',
    'Основная',
    coalesce(
        (select agent_name from public.robot_runtime_profiles where runtime_key = 'livekit_cloud'),
        (select agent_name from public.robot_runtime_profiles where runtime_key = 'asterisk'),
        'main-bot'
    ),
    'base',
    'draft',
    null,
    null,
    null,
    null,
    null,
    null,
    null,
    '{}'::jsonb,
    true
where not exists (
    select 1 from public.robot_runtime_profiles where runtime_key = 'base'
);

update public.robot_runtime_profiles
set display_name = case runtime_key
        when 'base' then 'Основная'
        when 'livekit_cloud' then 'LiveKit Cloud'
        when 'asterisk' then 'Asterisk'
        when 'mac' then 'Mac'
        else display_name
    end,
    environment = case runtime_key
        when 'base' then 'base'
        when 'livekit_cloud' then 'livekit_cloud'
        else environment
    end,
    llm_profile = null,
    fast_llm_profile = null,
    complex_llm_profile = null,
    tts_profile = null,
    stt_profile = null,
    turn_profile = null,
    fallback_profile = null,
    override_json = coalesce(override_json, '{}'::jsonb),
    updated_at = now()
where runtime_key in ('base', 'livekit_cloud', 'asterisk', 'mac');

create table if not exists public.robot_profile_bindings (
    id bigserial primary key,
    owner_type text not null,
    owner_key text not null,
    category text not null,
    slot text not null,
    profile_key text not null references public.robot_component_profiles(profile_key)
        on update cascade
        on delete restrict,
    note text,
    sort integer not null default 100,
    active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint robot_profile_bindings_owner_type_check check (
        owner_type in ('runtime', 'project')
    ),
    constraint robot_profile_bindings_category_check check (
        category in ('llm', 'llm_routing', 'tts', 'stt', 'turn', 'fallback', 'voice_prompts', 'egress', 'general')
    ),
    constraint robot_profile_bindings_slot_check check (
        slot in ('primary', 'backup', 'third', 'selected', 'fast', 'complex')
    ),
    constraint robot_profile_bindings_unique_slot unique (
        owner_type,
        owner_key,
        category,
        slot
    )
);

create index if not exists robot_profile_bindings_owner_idx
    on public.robot_profile_bindings (owner_type, owner_key);
create index if not exists robot_profile_bindings_profile_key_idx
    on public.robot_profile_bindings (profile_key);
create index if not exists robot_profile_bindings_category_slot_idx
    on public.robot_profile_bindings (category, slot);

drop trigger if exists robot_profile_bindings_touch_updated_at
    on public.robot_profile_bindings;
create trigger robot_profile_bindings_touch_updated_at
before update on public.robot_profile_bindings
for each row execute function public.robot_touch_updated_at();

comment on table public.robot_profile_bindings is
    'Назначения component profiles для основной конфигурации, сред запуска и клиентских профилей. Если назначения нет, применяется наследование.';
comment on column public.robot_profile_bindings.owner_type is
    'runtime для base/livekit_cloud/asterisk/mac или project для client/project/DID profile.';
comment on column public.robot_profile_bindings.owner_key is
    'Ключ владельца: runtime_key из robot_runtime_profiles или profile_key из robot_project_profiles.';
comment on column public.robot_profile_bindings.category is
    'Категория настройки: llm, llm_routing, tts, stt, turn, fallback и т.д.';
comment on column public.robot_profile_bindings.slot is
    'Роль профиля внутри категории: primary, backup, third, selected, fast или complex.';

with base_bindings(category, slot, profile_key, sort, note) as (
    select 'llm', 'primary', llm_profile, 10, 'Основной LLM-профиль из текущего env' from robot_base_selectors where llm_profile is not null
    union all
    select 'llm_routing', 'fast', fast_llm_profile, 20, 'Быстрый LLM-профиль из текущего env' from robot_base_selectors where fast_llm_profile is not null
    union all
    select 'llm_routing', 'complex', complex_llm_profile, 30, 'Сложный LLM-профиль из текущего env' from robot_base_selectors where complex_llm_profile is not null
    union all
    select 'tts', 'primary', tts_profile, 40, 'Основной TTS-профиль из текущего env' from robot_base_selectors where tts_profile is not null
    union all
    select 'stt', 'primary', stt_profile, 50, 'Основной STT-профиль из текущего env' from robot_base_selectors where stt_profile is not null
    union all
    select 'turn', 'selected', turn_profile, 60, 'Профиль пауз и перебиваний из текущего env' from robot_base_selectors where turn_profile is not null
    union all
    select 'fallback', 'selected', fallback_profile, 70, 'Профиль fallback из текущего env' from robot_base_selectors where fallback_profile is not null
)
insert into public.robot_profile_bindings (
    owner_type,
    owner_key,
    category,
    slot,
    profile_key,
    sort,
    note
)
select
    'runtime',
    'base',
    category,
    slot,
    profile_key,
    sort,
    note
from base_bindings
on conflict (owner_type, owner_key, category, slot) do update set
    profile_key = excluded.profile_key,
    sort = excluded.sort,
    note = excluded.note,
    active = true,
    updated_at = now();

with runtime_diff_bindings(category, slot, profile_key, runtime_key, sort, note) as (
    select 'llm', 'primary', old.llm_profile, old.runtime_key, 10, 'Отличие среды от основной LLM-конфигурации'
    from robot_runtime_selectors_before old, robot_base_selectors base
    where old.runtime_key <> 'base'
      and old.llm_profile is not null
      and old.llm_profile is distinct from base.llm_profile
    union all
    select 'llm_routing', 'fast', old.fast_llm_profile, old.runtime_key, 20, 'Отличие среды: быстрый LLM-профиль'
    from robot_runtime_selectors_before old, robot_base_selectors base
    where old.runtime_key <> 'base'
      and old.fast_llm_profile is not null
      and old.fast_llm_profile is distinct from base.fast_llm_profile
    union all
    select 'llm_routing', 'complex', old.complex_llm_profile, old.runtime_key, 30, 'Отличие среды: сложный LLM-профиль'
    from robot_runtime_selectors_before old, robot_base_selectors base
    where old.runtime_key <> 'base'
      and old.complex_llm_profile is not null
      and old.complex_llm_profile is distinct from base.complex_llm_profile
    union all
    select 'tts', 'primary', old.tts_profile, old.runtime_key, 40, 'Отличие среды от основной TTS-конфигурации'
    from robot_runtime_selectors_before old, robot_base_selectors base
    where old.runtime_key <> 'base'
      and old.tts_profile is not null
      and old.tts_profile is distinct from base.tts_profile
    union all
    select 'stt', 'primary', old.stt_profile, old.runtime_key, 50, 'Отличие среды от основной STT-конфигурации'
    from robot_runtime_selectors_before old, robot_base_selectors base
    where old.runtime_key <> 'base'
      and old.stt_profile is not null
      and old.stt_profile is distinct from base.stt_profile
    union all
    select 'turn', 'selected', old.turn_profile, old.runtime_key, 60, 'Отличие среды по паузам и перебиваниям'
    from robot_runtime_selectors_before old, robot_base_selectors base
    where old.runtime_key <> 'base'
      and old.turn_profile is not null
      and old.turn_profile is distinct from base.turn_profile
    union all
    select 'fallback', 'selected', old.fallback_profile, old.runtime_key, 70, 'Отличие среды по fallback-профилю'
    from robot_runtime_selectors_before old, robot_base_selectors base
    where old.runtime_key <> 'base'
      and old.fallback_profile is not null
      and old.fallback_profile is distinct from base.fallback_profile
)
insert into public.robot_profile_bindings (
    owner_type,
    owner_key,
    category,
    slot,
    profile_key,
    sort,
    note
)
select
    'runtime',
    runtime_key,
    category,
    slot,
    profile_key,
    sort,
    note
from runtime_diff_bindings
on conflict (owner_type, owner_key, category, slot) do update set
    profile_key = excluded.profile_key,
    sort = excluded.sort,
    note = excluded.note,
    active = true,
    updated_at = now();

insert into public.robot_profile_bindings (
    owner_type,
    owner_key,
    category,
    slot,
    profile_key,
    sort,
    note
)
select 'project', profile_key, 'llm', 'primary', llm_profile, 10, 'Клиентское отличие LLM-профиля'
from public.robot_project_profiles
where llm_profile is not null
on conflict (owner_type, owner_key, category, slot) do update set
    profile_key = excluded.profile_key,
    sort = excluded.sort,
    note = excluded.note,
    active = true,
    updated_at = now();

insert into public.robot_profile_bindings (
    owner_type,
    owner_key,
    category,
    slot,
    profile_key,
    sort,
    note
)
select 'project', profile_key, 'tts', 'primary', tts_profile, 40, 'Клиентское отличие TTS-профиля'
from public.robot_project_profiles
where tts_profile is not null
on conflict (owner_type, owner_key, category, slot) do update set
    profile_key = excluded.profile_key,
    sort = excluded.sort,
    note = excluded.note,
    active = true,
    updated_at = now();

insert into public.robot_profile_bindings (
    owner_type,
    owner_key,
    category,
    slot,
    profile_key,
    sort,
    note
)
select 'project', profile_key, 'stt', 'primary', stt_profile, 50, 'Клиентское отличие STT-профиля'
from public.robot_project_profiles
where stt_profile is not null
on conflict (owner_type, owner_key, category, slot) do update set
    profile_key = excluded.profile_key,
    sort = excluded.sort,
    note = excluded.note,
    active = true,
    updated_at = now();

insert into public.robot_profile_bindings (
    owner_type,
    owner_key,
    category,
    slot,
    profile_key,
    sort,
    note
)
select 'project', profile_key, 'turn', 'selected', turn_profile, 60, 'Клиентское отличие профиля пауз и перебиваний'
from public.robot_project_profiles
where turn_profile is not null
on conflict (owner_type, owner_key, category, slot) do update set
    profile_key = excluded.profile_key,
    sort = excluded.sort,
    note = excluded.note,
    active = true,
    updated_at = now();

insert into public.robot_profile_bindings (
    owner_type,
    owner_key,
    category,
    slot,
    profile_key,
    sort,
    note
)
select 'project', profile_key, 'fallback', 'selected', fallback_profile, 70, 'Клиентское отличие fallback-профиля'
from public.robot_project_profiles
where fallback_profile is not null
on conflict (owner_type, owner_key, category, slot) do update set
    profile_key = excluded.profile_key,
    sort = excluded.sort,
    note = excluded.note,
    active = true,
    updated_at = now();

do $$
begin
    if exists (select 1 from pg_roles where rolname = 'directus_user') then
        grant select, insert, update, delete on public.robot_profile_bindings to directus_user;
        grant usage, select on sequence public.robot_profile_bindings_id_seq to directus_user;
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
) values (
    'robot_profile_bindings',
    'link',
    'Назначения профилей для основной конфигурации, сред запуска и клиентов. Если назначения нет, применяется наследование.',
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
    searchable,
    note
)
select *
from (
    values
        ('robot_profile_bindings', 'id', null, 'input', null, true, true, 1, 'half', false, true, null),
        ('robot_profile_bindings', 'owner_type', null, 'select-dropdown', null, false, false, 2, 'half', true, true, 'runtime или project.'),
        ('robot_profile_bindings', 'owner_key', null, 'input', null, false, false, 3, 'half', true, true, 'base/livekit_cloud/asterisk/mac или ключ клиентского профиля.'),
        ('robot_profile_bindings', 'category', null, 'select-dropdown', null, false, false, 4, 'half', true, true, 'Категория: llm, llm_routing, tts, stt, turn, fallback.'),
        ('robot_profile_bindings', 'slot', null, 'select-dropdown', null, false, false, 5, 'half', true, true, 'primary, backup, third, selected, fast или complex.'),
        ('robot_profile_bindings', 'profile_key', null, 'input', null, false, false, 6, 'half', true, true, 'Ключ из robot_component_profiles.'),
        ('robot_profile_bindings', 'note', null, 'input-multiline', null, false, false, 7, 'full', false, true, 'Пояснение, зачем назначен этот профиль.'),
        ('robot_profile_bindings', 'sort', null, 'input', null, false, false, 8, 'half', true, true, null),
        ('robot_profile_bindings', 'active', null, 'boolean', null, false, false, 9, 'half', true, true, null),
        ('robot_profile_bindings', 'created_at', null, 'datetime', 'datetime', true, false, 10, 'half', false, true, null),
        ('robot_profile_bindings', 'updated_at', null, 'datetime', 'datetime', true, false, 11, 'half', false, true, null)
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
    searchable,
    note
)
where not exists (
    select 1
    from public.directus_fields as existing
    where existing.collection = new_fields.collection
      and existing.field = new_fields.field
);

update public.directus_fields
set hidden = true,
    note = 'Устаревшее поле переходного периода. Основной выбор профилей хранится в robot_profile_bindings.'
where collection in ('robot_runtime_profiles', 'robot_project_profiles')
  and field in (
      'llm_profile',
      'fast_llm_profile',
      'complex_llm_profile',
      'tts_profile',
      'stt_profile',
      'turn_profile',
      'fallback_profile'
  );

update public.directus_collections
set note = 'Среды запуска: base, livekit_cloud, asterisk, mac. Сама среда хранит идентичность и override_json; выбор профилей хранится в robot_profile_bindings.'
where collection = 'robot_runtime_profiles';

update public.directus_collections
set note = 'Профили клиента, проекта или DID. Клиентские назначения профилей хранятся в robot_profile_bindings; пустые назначения наследуются от среды и base.'
where collection = 'robot_project_profiles';

update public.directus_permissions
set fields = 'id,runtime_key,display_name,agent_name,environment,status,override_json,active,created_at,updated_at'
where collection = 'robot_runtime_profiles'
  and action = 'read';

update public.directus_permissions
set fields = 'id,profile_key,display_name,client_id,did,runtime_key,status,prompt_source,greeting_source,override_json,active,created_at,updated_at'
where collection = 'robot_project_profiles'
  and action = 'read';

insert into public.directus_permissions (
    collection,
    action,
    permissions,
    validation,
    presets,
    fields,
    policy
)
select
    'robot_profile_bindings',
    'read',
    null,
    null,
    null,
    'id,owner_type,owner_key,category,slot,profile_key,note,sort,active,created_at,updated_at',
    policy
from (
    select distinct policy
    from public.directus_permissions
    where collection = 'robot_component_profiles'
      and action = 'read'
      and policy is not null
) as policies
where not exists (
    select 1
    from public.directus_permissions
    where collection = 'robot_profile_bindings'
      and action = 'read'
      and policy = policies.policy
);

update public.directus_permissions
set fields = 'id,owner_type,owner_key,category,slot,profile_key,note,sort,active,created_at,updated_at'
where collection = 'robot_profile_bindings'
  and action = 'read';

do $$
declare
    missing_runtime text;
    base_binding_count integer;
    stale_runtime_key_count integer;
begin
    select string_agg(expected.runtime_key, ', ' order by expected.runtime_key)
    into missing_runtime
    from (
        values ('base'), ('livekit_cloud'), ('asterisk'), ('mac')
    ) as expected(runtime_key)
    left join public.robot_runtime_profiles as runtime using (runtime_key)
    where runtime.runtime_key is null;

    if missing_runtime is not null then
        raise exception 'Missing runtime profiles: %', missing_runtime;
    end if;

    select count(*)
    into base_binding_count
    from public.robot_profile_bindings
    where owner_type = 'runtime'
      and owner_key = 'base'
      and active = true;

    if base_binding_count < 5 then
        raise exception 'Expected at least 5 base profile bindings, got %', base_binding_count;
    end if;

    select count(*)
    into stale_runtime_key_count
    from public.robot_runtime_profiles
    where runtime_key = 'cloud';

    if stale_runtime_key_count > 0 then
        raise exception 'Stale runtime key cloud still exists';
    end if;
end $$;

commit;
