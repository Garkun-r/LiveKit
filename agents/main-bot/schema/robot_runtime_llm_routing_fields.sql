-- Add optional fast/complex LLM selectors to runtime profiles.
--
-- Safe migration properties:
-- - updates only robot_runtime_profiles and its Directus metadata;
-- - leaves current runtime behavior unchanged because both new fields default to null;
-- - future loader semantics: when both fields are set, use LLM routing;
--   otherwise fall back to llm_profile.

begin;

alter table public.robot_runtime_profiles
    add column if not exists fast_llm_profile text,
    add column if not exists complex_llm_profile text;

comment on column public.robot_runtime_profiles.fast_llm_profile is
    'Optional fast LLM component profile. If fast and complex profiles are both set, runtime can enable LLM routing.';
comment on column public.robot_runtime_profiles.complex_llm_profile is
    'Optional complex/main LLM component profile. If empty, runtime falls back to llm_profile.';

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
        (
            'robot_runtime_profiles',
            'fast_llm_profile',
            null,
            'input',
            null,
            false,
            false,
            8,
            'half',
            false,
            true,
            'Быстрый LLM-профиль для простых и срочных ответов. Если пусто, используется общий llm_profile.'
        ),
        (
            'robot_runtime_profiles',
            'complex_llm_profile',
            null,
            'input',
            null,
            false,
            false,
            9,
            'half',
            false,
            true,
            'Основной/сложный LLM-профиль для задач, где важнее качество рассуждения. Если пусто, используется общий llm_profile.'
        )
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
set note = case field
        when 'fast_llm_profile' then 'Быстрый LLM-профиль для простых и срочных ответов. Если пусто, используется общий llm_profile.'
        when 'complex_llm_profile' then 'Основной/сложный LLM-профиль для задач, где важнее качество рассуждения. Если пусто, используется общий llm_profile.'
        else note
    end,
    sort = case field
        when 'id' then 1
        when 'runtime_key' then 2
        when 'display_name' then 3
        when 'agent_name' then 4
        when 'environment' then 5
        when 'status' then 6
        when 'llm_profile' then 7
        when 'fast_llm_profile' then 8
        when 'complex_llm_profile' then 9
        when 'tts_profile' then 10
        when 'stt_profile' then 11
        when 'turn_profile' then 12
        when 'fallback_profile' then 13
        when 'override_json' then 14
        when 'active' then 15
        when 'created_at' then 16
        when 'updated_at' then 17
        else sort
    end
where collection = 'robot_runtime_profiles';

update public.directus_permissions
set fields = 'id,runtime_key,display_name,agent_name,environment,status,llm_profile,fast_llm_profile,complex_llm_profile,tts_profile,stt_profile,turn_profile,fallback_profile,override_json,active,created_at,updated_at'
where collection = 'robot_runtime_profiles'
  and action = 'read';

do $$
declare
    missing_columns text;
begin
    select string_agg(expected.column_name, ', ' order by expected.column_name)
    into missing_columns
    from (
        values ('fast_llm_profile'), ('complex_llm_profile')
    ) as expected(column_name)
    left join information_schema.columns as actual
      on actual.table_schema = 'public'
     and actual.table_name = 'robot_runtime_profiles'
     and actual.column_name = expected.column_name
    where actual.column_name is null;

    if missing_columns is not null then
        raise exception 'Missing robot_runtime_profiles columns: %', missing_columns;
    end if;
end $$;

commit;
