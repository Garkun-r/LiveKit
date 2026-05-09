-- Directus metadata and runtime permissions for per-call raw LiveKit logs.
--
-- Run after robot_call_raw_logs.sql on the VPS database used by Directus.

do $$
begin
    if exists (select 1 from pg_roles where rolname = 'directus_user') then
        grant usage on schema public to directus_user;
        grant select, insert, update on public.robot_call_raw_logs to directus_user;

        if exists (select 1 from pg_class where relkind = 'S' and relname = 'robot_call_raw_logs_id_seq') then
            grant usage, select on sequence public.robot_call_raw_logs_id_seq to directus_user;
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
    'robot_call_raw_logs',
    'article',
    'Raw per-call LiveKit agent log lines captured during the call.',
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

do $$
declare
    fields text := 'id,created_at,event_time,call_session,source,agent_name,runtime_profile,room_name,session_id,job_id,trace_id,sip_call_id,sequence,level,logger_name,message,raw_text,module,function_name,line_no,task_name,payload';
begin
    insert into public.directus_fields (
        collection,
        field,
        special,
        interface,
        options,
        readonly,
        hidden,
        sort,
        width,
        required
    )
    select
        'robot_call_raw_logs',
        field,
        special,
        interface,
        options::json,
        readonly,
        hidden,
        sort,
        width,
        required
    from (
        values
            ('id', null, 'input', null, true, false, 1, 'half', false),
            ('created_at', 'date-created', 'datetime', null, true, false, 2, 'half', false),
            ('event_time', null, 'datetime', null, false, false, 3, 'half', true),
            ('call_session', 'm2o', 'select-dropdown-m2o', null, false, false, 4, 'half', false),
            ('source', null, 'input', null, false, false, 5, 'half', true),
            ('agent_name', null, 'input', null, false, false, 6, 'half', false),
            ('runtime_profile', null, 'input', null, false, false, 7, 'half', false),
            ('room_name', null, 'input', null, false, false, 8, 'half', false),
            ('session_id', null, 'input', null, false, false, 9, 'half', false),
            ('job_id', null, 'input', null, false, false, 10, 'half', false),
            ('trace_id', null, 'input', null, false, false, 11, 'half', false),
            ('sip_call_id', null, 'input', null, false, false, 12, 'half', false),
            ('sequence', null, 'input', null, false, false, 13, 'half', true),
            ('level', null, 'input', null, false, false, 14, 'half', true),
            ('logger_name', null, 'input', null, false, false, 15, 'half', false),
            ('message', null, 'input-multiline', null, false, false, 16, 'full', false),
            ('raw_text', null, 'input-multiline', null, false, false, 17, 'full', false),
            ('module', null, 'input', null, false, false, 18, 'half', false),
            ('function_name', null, 'input', null, false, false, 19, 'half', false),
            ('line_no', null, 'input', null, false, false, 20, 'half', false),
            ('task_name', null, 'input', null, false, false, 21, 'half', false),
            ('payload', null, 'input-code', null, false, false, 22, 'full', false)
    ) as values(field, special, interface, options, readonly, hidden, sort, width, required)
    where not exists (
        select 1
        from public.directus_fields existing
        where existing.collection = 'robot_call_raw_logs'
          and existing.field = values.field
    );

    update public.directus_fields
    set hidden = false
    where collection = 'robot_call_raw_logs'
      and field = any(string_to_array(fields, ','));
end $$;

do $$
declare
    admin_policy uuid;
    livekit_policy uuid;
    read_fields text := 'id,created_at,event_time,call_session,source,agent_name,runtime_profile,room_name,session_id,job_id,trace_id,sip_call_id,sequence,level,logger_name,message,raw_text,module,function_name,line_no,task_name,payload';
    write_fields text := 'event_time,call_session,source,agent_name,runtime_profile,room_name,session_id,job_id,trace_id,sip_call_id,sequence,level,logger_name,message,raw_text,module,function_name,line_no,task_name,payload';
begin
    select p.id
    into admin_policy
    from public.directus_policies p
    join public.directus_access a on a.policy = p.id
    join public.directus_roles r on r.id = a.role
    where r.name = 'admin_portal'
    order by (p.name = 'admin_portal') desc, p.name
    limit 1;

    if admin_policy is not null then
        insert into public.directus_permissions (
            collection, action, permissions, validation, presets, fields, policy
        )
        select 'robot_call_raw_logs', 'read', null, null, null, read_fields, admin_policy
        where not exists (
            select 1 from public.directus_permissions
            where collection = 'robot_call_raw_logs'
              and action = 'read'
              and policy = admin_policy
        );

        update public.directus_permissions
        set fields = read_fields
        where collection = 'robot_call_raw_logs'
          and action = 'read'
          and policy = admin_policy;
    end if;

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
        collection, action, permissions, validation, presets, fields, policy
    )
    select collection, action, null, null, null, fields, livekit_policy
    from (
        values
            ('robot_call_raw_logs', 'create', write_fields),
            ('robot_call_raw_logs', 'read', read_fields),
            ('robot_call_raw_logs', 'update', write_fields)
    ) as grants(collection, action, fields)
    where not exists (
        select 1
        from public.directus_permissions existing
        where existing.collection = grants.collection
          and existing.action = grants.action
          and existing.policy = livekit_policy
    );

    update public.directus_permissions
    set fields = case
        when action = 'read' then read_fields
        else write_fields
    end
    where collection = 'robot_call_raw_logs'
      and policy = livekit_policy;
end $$;
