-- Directus runtime permissions for prompt assembly.
--
-- Run this on the VPS database used by Directus when the LiveKit agent starts
-- reading new prompt-related fields or collections.
--
-- This script updates the Directus role/policy metadata only. It does not add
-- business columns such as clients.first_step; create missing columns in a
-- separate explicit schema migration first.

do $$
begin
    if exists (select 1 from pg_roles where rolname = 'directus_user') then
        grant usage on schema public to directus_user;
        grant select on
            public."CallerID",
            public.bot_configurations,
            public.clients,
            public.clients_prompt,
            public.webparsing,
            public.transfer_number,
            public.client_prompt_cache
            to directus_user;

        grant insert, update on public.client_prompt_cache to directus_user;
    end if;
end $$;

do $$
declare
    livekit_policy uuid;
    permission_row record;
    existing_fields text;
    merged_fields text;
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

    create temp table livekit_prompt_permissions (
        collection text not null,
        action text not null,
        fields text not null
    ) on commit drop;

    insert into livekit_prompt_permissions (collection, action, fields)
    values
        ('CallerID', 'read', 'CallerID,client_id'),
        (
            'bot_configurations',
            'read',
            'client_id,system_prompt,examples,skills_name,first_step_text,llm_intro'
        ),
        (
            'clients',
            'read',
            'id,add_info,company_website,company_extra,first_step'
        ),
        ('clients_prompt', 'read', 'name,text'),
        ('webparsing', 'read', 'url,text'),
        ('transfer_number', 'read', 'client_id,disc,direction'),
        (
            'client_prompt_cache',
            'read',
            'id,caller_id,client_id,prompt_template,timezone,source_hash,active,last_error,date_updated'
        ),
        (
            'client_prompt_cache',
            'create',
            'caller_id,client_id,prompt_template,timezone,source_hash,active,last_error,date_updated'
        ),
        (
            'client_prompt_cache',
            'update',
            'caller_id,client_id,prompt_template,timezone,source_hash,active,last_error,date_updated'
        );

    for permission_row in
        select collection, action, fields
        from livekit_prompt_permissions
    loop
        select string_agg(fields, ',')
        into existing_fields
        from public.directus_permissions
        where collection = permission_row.collection
          and action = permission_row.action
          and policy = livekit_policy;

        if exists (
            select 1
            from regexp_split_to_table(coalesce(existing_fields, ''), ',') as field
            where btrim(field) = '*'
        ) then
            merged_fields := '*';
        else
            select string_agg(field, ',' order by first_seen)
            into merged_fields
            from (
                select field, min(position) as first_seen
                from (
                    select btrim(field) as field, ordinality as position
                    from regexp_split_to_table(
                        coalesce(existing_fields, ''),
                        ','
                    ) with ordinality as existing(field, ordinality)
                    union all
                    select btrim(field) as field, 1000 + ordinality as position
                    from regexp_split_to_table(
                        permission_row.fields,
                        ','
                    ) with ordinality as expected(field, ordinality)
                ) as combined
                where field <> ''
                group by field
            ) as deduped;
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
        select
            permission_row.collection,
            permission_row.action,
            null,
            null,
            null,
            permission_row.fields,
            livekit_policy
        where not exists (
            select 1
            from public.directus_permissions
            where collection = permission_row.collection
              and action = permission_row.action
              and policy = livekit_policy
        );

        update public.directus_permissions
        set fields = coalesce(merged_fields, permission_row.fields)
        where collection = permission_row.collection
          and action = permission_row.action
          and policy = livekit_policy;
    end loop;
end $$;
