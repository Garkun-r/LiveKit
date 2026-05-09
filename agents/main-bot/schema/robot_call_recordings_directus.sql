-- Directus metadata and runtime permissions for robot_call_sessions and
-- robot_call_recordings.
--
-- Run after robot_call_recordings.sql on the VPS database used by Directus.
-- The Livekit role may write call-session metadata and recording metadata. Use
-- a separate service user/token with the same narrow policy for the egress
-- indexer if you want to separate agent and recording writes.

do $$
begin
    if exists (select 1 from pg_roles where rolname = 'directus_user') then
        grant usage on schema public to directus_user;
        grant select, insert, update on public.robot_call_sessions to directus_user;
        grant select, insert, update on public.robot_call_recordings to directus_user;

        if exists (select 1 from pg_class where relkind = 'S' and relname = 'robot_call_sessions_id_seq') then
            grant usage, select on sequence public.robot_call_sessions_id_seq to directus_user;
        end if;
        if exists (select 1 from pg_class where relkind = 'S' and relname = 'robot_call_recordings_id_seq') then
            grant usage, select on sequence public.robot_call_recordings_id_seq to directus_user;
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
) values
    (
        'robot_call_sessions',
        'phone_in_talk',
        'LiveKit robot call sessions indexed for admin and platform playback.',
        false,
        false,
        'all',
        'open'
    ),
    (
        'robot_call_recordings',
        'graphic_eq',
        'Private MinIO/S3 recording objects created by LiveKit Egress.',
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
    admin_policy uuid;
    session_read_fields text := 'id,created_at,updated_at,source,agent_name,runtime_profile,room_name,session_id,lead_session_id,client_id,client_name,phone_number,xdid,did,gateway_number,sip_call_id,job_id,trace_id,started_at,ended_at,duration_sec,status,close_reason,prompt_source,chat_history,transcript_items,tag_events,usage_updates,metrics_summary,payload';
    recording_read_fields text := 'id,created_at,updated_at,call_session,source,room_name,session_id,egress_id,status,storage_provider,storage_bucket,object_key,file_name,mime_type,file_size,duration_sec,started_at,ended_at,manifest_key,error,payload';
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
        select collection, action, null, null, null, fields, admin_policy
        from (
            values
                ('robot_call_sessions', 'read', session_read_fields),
                ('robot_call_recordings', 'read', recording_read_fields)
        ) as grants(collection, action, fields)
        where not exists (
            select 1
            from public.directus_permissions existing
            where existing.collection = grants.collection
              and existing.action = grants.action
              and existing.policy = admin_policy
        );

        update public.directus_permissions
        set fields = case
            when collection = 'robot_call_sessions' then session_read_fields
            when collection = 'robot_call_recordings' then recording_read_fields
            else fields
        end
        where collection in ('robot_call_sessions', 'robot_call_recordings')
          and action = 'read'
          and policy = admin_policy;
    end if;
end $$;

do $$
declare
    livekit_policy uuid;
    session_fields text := 'source,agent_name,runtime_profile,room_name,session_id,lead_session_id,client_id,client_name,phone_number,xdid,did,gateway_number,sip_call_id,job_id,trace_id,started_at,ended_at,duration_sec,status,close_reason,prompt_source,chat_history,transcript_items,tag_events,usage_updates,metrics_summary,payload';
    session_read_fields text := 'id,created_at,updated_at,' || session_fields;
    recording_fields text := 'call_session,source,room_name,session_id,egress_id,status,storage_provider,storage_bucket,object_key,file_name,mime_type,file_size,duration_sec,started_at,ended_at,manifest_key,error,payload';
    recording_read_fields text := 'id,created_at,updated_at,' || recording_fields;
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
        collection, action, permissions, validation, presets, fields, policy
    )
    select collection, action, null, null, null, fields, livekit_policy
    from (
        values
            ('robot_call_sessions', 'create', session_fields),
            ('robot_call_sessions', 'read', session_read_fields),
            ('robot_call_sessions', 'update', session_fields),
            ('robot_call_recordings', 'create', recording_fields),
            ('robot_call_recordings', 'read', recording_read_fields),
            ('robot_call_recordings', 'update', recording_fields)
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
        when collection = 'robot_call_sessions' and action = 'read' then session_read_fields
        when collection = 'robot_call_sessions' then session_fields
        when collection = 'robot_call_recordings' and action = 'read' then recording_read_fields
        when collection = 'robot_call_recordings' then recording_fields
        else fields
    end
    where collection in ('robot_call_sessions', 'robot_call_recordings')
      and policy = livekit_policy;
end $$;
