-- Directus metadata and role permissions for public.robot_incidents.
--
-- Run after robot_incidents.sql on the VPS database used by Directus.
-- This script assumes the Directus app role is named "Livekit" and grants
-- create/read access through the first policy attached to that role.

do $$
begin
    if exists (select 1 from pg_roles where rolname = 'directus_user') then
        grant usage on schema public to directus_user;
        grant select, insert on public.robot_incidents to directus_user;

        if exists (
            select 1
            from pg_class
            where relkind = 'S'
              and relnamespace = 'public'::regnamespace
              and relname = 'robot_incidents_id_seq'
        ) then
            grant usage, select on sequence public.robot_incidents_id_seq
                to directus_user;
        end if;
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
    'robot_incidents',
    'report_problem',
    'Robot diagnostic incidents written by LiveKit agent through Directus API.',
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
select
    'robot_incidents',
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
from (
    values
        ('id', null, 'input', null, true, true, 1, 'half', false, true),
        ('created_at', null, 'datetime', 'datetime', false, false, 2, 'half', false, true),
        ('environment', null, 'input', null, false, false, 3, 'half', true, true),
        ('source', null, 'input', null, false, false, 4, 'half', true, true),
        ('severity', null, 'input', null, false, false, 5, 'half', true, true),
        ('incident_type', null, 'input', null, false, false, 6, 'half', true, true),
        ('status', null, 'input', null, false, false, 7, 'half', true, true),
        ('caller_phone', null, 'input', null, false, false, 8, 'half', false, true),
        ('did', null, 'input', null, false, false, 9, 'half', false, true),
        ('trace_id', null, 'input', null, false, false, 10, 'half', false, true),
        ('room_name', null, 'input', null, false, false, 11, 'half', false, true),
        ('job_id', null, 'input', null, false, false, 12, 'half', false, true),
        ('sip_call_id', null, 'input', null, false, false, 13, 'half', false, true),
        ('component', null, 'input', null, false, false, 14, 'half', false, true),
        ('provider', null, 'input', null, false, false, 15, 'half', false, true),
        ('model', null, 'input', null, false, false, 16, 'half', false, true),
        ('latency_ms', null, 'input', null, false, false, 17, 'half', false, true),
        ('error_type', null, 'input', null, false, false, 18, 'half', false, true),
        ('description', null, 'input-multiline', null, false, false, 19, 'full', true, true),
        ('fingerprint', null, 'input', null, false, false, 20, 'half', false, true),
        ('payload', null, 'input-code', null, false, false, 21, 'full', true, true)
) as metadata(
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
    where existing.collection = 'robot_incidents'
      and existing.field = metadata.field
);

do $$
declare
    livekit_policy uuid;
    create_fields text := 'created_at,environment,source,severity,incident_type,status,caller_phone,did,trace_id,room_name,job_id,sip_call_id,component,provider,model,latency_ms,error_type,description,fingerprint,payload';
    read_fields text := 'id,created_at,environment,source,severity,incident_type,status,caller_phone,did,trace_id,room_name,job_id,sip_call_id,component,provider,model,latency_ms,error_type,description,fingerprint,payload';
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

    insert into public.directus_permissions (
        collection,
        action,
        permissions,
        validation,
        presets,
        fields,
        policy
    )
    select 'robot_incidents', 'create', null, null, null, create_fields, livekit_policy
    where not exists (
        select 1
        from public.directus_permissions
        where collection = 'robot_incidents'
          and action = 'create'
          and policy = livekit_policy
    );

    insert into public.directus_permissions (
        collection,
        action,
        permissions,
        validation,
        presets,
        fields,
        policy
    )
    select 'robot_incidents', 'read', null, null, null, read_fields, livekit_policy
    where not exists (
        select 1
        from public.directus_permissions
        where collection = 'robot_incidents'
          and action = 'read'
          and policy = livekit_policy
    );

    update public.directus_permissions
    set fields = create_fields
    where collection = 'robot_incidents'
      and action = 'create'
      and policy = livekit_policy;

    update public.directus_permissions
    set fields = read_fields
    where collection = 'robot_incidents'
      and action = 'read'
      and policy = livekit_policy;
end $$;
