-- Add client-specific first LLM intro text for the LiveKit voice agent.
--
-- Run on the Directus Postgres database. The runtime reads this field through
-- the Livekit service role and never writes to bot_configurations.

alter table public.bot_configurations
    add column if not exists llm_intro text;

do $$
begin
    if exists (select 1 from pg_roles where rolname = 'directus_user') then
        grant select on public.bot_configurations to directus_user;
    end if;
end $$;

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
select
    'bot_configurations',
    'llm_intro',
    null,
    'input-multiline',
    null,
    false,
    false,
    sort_info.next_sort,
    'full',
    false,
    true,
    'Фраза, которую голосовой слой произносит перед первым ответом LLM. Если пусто, используется общий first_llm_intro.'
from (
    select coalesce(max(sort), 0) + 1 as next_sort
    from public.directus_fields
    where collection = 'bot_configurations'
) as sort_info
where not exists (
    select 1
    from public.directus_fields existing
    where existing.collection = 'bot_configurations'
      and existing.field = 'llm_intro'
);

update public.directus_fields
set interface = 'input-multiline',
    hidden = false,
    width = 'full',
    readonly = false,
    required = false,
    searchable = true,
    note = 'Фраза, которую голосовой слой произносит перед первым ответом LLM. Если пусто, используется общий first_llm_intro.'
where collection = 'bot_configurations'
  and field = 'llm_intro';

do $$
declare
    livekit_policy uuid;
    current_fields text;
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

    select fields
    into current_fields
    from public.directus_permissions
    where collection = 'bot_configurations'
      and action = 'read'
      and policy = livekit_policy
    limit 1;

    if current_fields is null then
        insert into public.directus_permissions (
            collection,
            action,
            permissions,
            validation,
            presets,
            fields,
            policy
        )
        values (
            'bot_configurations',
            'read',
            null,
            null,
            null,
            'client_id,system_prompt,examples,skills_name,first_step_text,llm_intro',
            livekit_policy
        );
    elsif not exists (
        select 1
        from regexp_split_to_table(current_fields, ',') as field
        where btrim(field) in ('*', 'llm_intro')
    ) then
        update public.directus_permissions
        set fields = current_fields || ',llm_intro'
        where collection = 'bot_configurations'
          and action = 'read'
          and policy = livekit_policy;
    end if;
end $$;
