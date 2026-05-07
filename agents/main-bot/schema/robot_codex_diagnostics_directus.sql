-- Directus metadata and role permissions for Codex post-call diagnostics.
--
-- Run after robot_codex_diagnostics.sql on the VPS database used by Directus.
-- Secret values for the worker remain in VPS/systemd env, not in Directus.

do $$
begin
    if exists (select 1 from pg_roles where rolname = 'directus_user') then
        grant usage on schema public to directus_user;
        grant select, insert, update on public.robot_diagnostic_rules to directus_user;
        grant select, insert, update on public.robot_call_audits to directus_user;

        if exists (
            select 1
            from pg_class
            where relkind = 'S'
              and relnamespace = 'public'::regnamespace
              and relname = 'robot_diagnostic_rules_id_seq'
        ) then
            grant usage, select on sequence public.robot_diagnostic_rules_id_seq
                to directus_user;
        end if;

        if exists (
            select 1
            from pg_class
            where relkind = 'S'
              and relnamespace = 'public'::regnamespace
              and relname = 'robot_call_audits_id_seq'
        ) then
            grant usage, select on sequence public.robot_call_audits_id_seq
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
) values
(
    'robot_diagnostic_rules',
    'rule',
    'Non-secret switches for post-call Codex diagnostics.',
    false,
    false,
    'all',
    'open'
),
(
    'robot_call_audits',
    'fact_check',
    'Codex post-call diagnostic audit jobs and reports.',
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
from (
    values
        ('robot_diagnostic_rules', 'id', null, 'input', null, true, true, 1, 'half', false, true),
        ('robot_diagnostic_rules', 'created_at', null, 'datetime', 'datetime', false, false, 2, 'half', false, true),
        ('robot_diagnostic_rules', 'updated_at', null, 'datetime', 'datetime', false, false, 3, 'half', false, true),
        ('robot_diagnostic_rules', 'enabled', null, 'boolean', 'boolean', false, false, 4, 'half', true, true),
        ('robot_diagnostic_rules', 'priority', null, 'input', null, false, false, 5, 'half', true, true),
        ('robot_diagnostic_rules', 'target', null, 'select-dropdown', null, false, false, 6, 'half', true, true),
        ('robot_diagnostic_rules', 'trigger_mode', null, 'select-dropdown', null, false, false, 7, 'half', true, true),
        ('robot_diagnostic_rules', 'scope_value', null, 'input', null, false, false, 8, 'half', false, true),
        ('robot_diagnostic_rules', 'min_severity', null, 'select-dropdown', null, false, false, 9, 'half', true, true),
        ('robot_diagnostic_rules', 'telegram_policy', null, 'select-dropdown', null, false, false, 10, 'half', true, true),
        ('robot_diagnostic_rules', 'cooldown_sec', null, 'input', null, false, false, 11, 'half', true, true),
        ('robot_diagnostic_rules', 'notes', null, 'input-multiline', null, false, false, 12, 'full', false, true),
        ('robot_call_audits', 'id', null, 'input', null, true, true, 1, 'half', false, true),
        ('robot_call_audits', 'created_at', null, 'datetime', 'datetime', false, false, 2, 'half', false, true),
        ('robot_call_audits', 'updated_at', null, 'datetime', 'datetime', false, false, 3, 'half', false, true),
        ('robot_call_audits', 'status', null, 'select-dropdown', null, false, false, 4, 'half', true, true),
        ('robot_call_audits', 'target', null, 'select-dropdown', null, false, false, 5, 'half', true, true),
        ('robot_call_audits', 'trigger_mode', null, 'select-dropdown', null, false, false, 6, 'half', true, true),
        ('robot_call_audits', 'matched_rule', null, 'input', null, false, false, 7, 'half', false, true),
        ('robot_call_audits', 'caller_phone', null, 'input', null, false, false, 8, 'half', false, true),
        ('robot_call_audits', 'did', null, 'input', null, false, false, 9, 'half', false, true),
        ('robot_call_audits', 'xdid', null, 'input', null, false, false, 10, 'half', false, true),
        ('robot_call_audits', 'room_name', null, 'input', null, false, false, 11, 'half', false, true),
        ('robot_call_audits', 'sip_call_id', null, 'input', null, false, false, 12, 'half', false, true),
        ('robot_call_audits', 'started_at', null, 'datetime', 'datetime', false, false, 13, 'half', false, true),
        ('robot_call_audits', 'ended_at', null, 'datetime', 'datetime', false, false, 14, 'half', false, true),
        ('robot_call_audits', 'incident_ids', null, 'input-code', null, false, false, 15, 'full', true, true),
        ('robot_call_audits', 'input_payload', null, 'input-code', null, false, false, 16, 'full', true, true),
        ('robot_call_audits', 'livekit_snapshot', null, 'input-code', null, false, false, 17, 'full', true, true),
        ('robot_call_audits', 'codex_thread_id', null, 'input', null, false, false, 18, 'half', false, true),
        ('robot_call_audits', 'codex_run_id', null, 'input', null, false, false, 19, 'half', false, true),
        ('robot_call_audits', 'verdict', null, 'select-dropdown', null, false, false, 20, 'half', false, true),
        ('robot_call_audits', 'report_markdown', null, 'input-multiline', null, false, false, 21, 'full', false, true),
        ('robot_call_audits', 'report_json', null, 'input-code', null, false, false, 22, 'full', true, true),
        ('robot_call_audits', 'telegram_status', null, 'input', null, false, false, 23, 'half', false, true),
        ('robot_call_audits', 'telegram_message_id', null, 'input', null, false, false, 24, 'half', false, true),
        ('robot_call_audits', 'error', null, 'input-multiline', null, false, false, 25, 'full', false, true),
        ('robot_call_audits', 'dedupe_key', null, 'input', null, false, true, 26, 'full', false, true),
        ('robot_call_audits', 'audit_started_at', null, 'datetime', 'datetime', false, false, 27, 'half', false, true),
        ('robot_call_audits', 'completed_at', null, 'datetime', 'datetime', false, false, 28, 'half', false, true)
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
    rules_fields text := 'id,created_at,updated_at,enabled,priority,target,trigger_mode,scope_value,min_severity,telegram_policy,cooldown_sec,notes';
    audits_fields text := 'id,created_at,updated_at,status,target,trigger_mode,matched_rule,caller_phone,did,xdid,room_name,sip_call_id,started_at,ended_at,incident_ids,input_payload,livekit_snapshot,codex_thread_id,codex_run_id,verdict,report_markdown,report_json,telegram_status,telegram_message_id,error,dedupe_key,audit_started_at,completed_at';
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
    values
        ('robot_diagnostic_rules', 'read', null, null, null, rules_fields, livekit_policy),
        ('robot_diagnostic_rules', 'create', null, null, null, rules_fields, livekit_policy),
        ('robot_diagnostic_rules', 'update', null, null, null, rules_fields, livekit_policy),
        ('robot_call_audits', 'read', null, null, null, audits_fields, livekit_policy),
        ('robot_call_audits', 'create', null, null, null, audits_fields, livekit_policy),
        ('robot_call_audits', 'update', null, null, null, audits_fields, livekit_policy)
    on conflict do nothing;

    update public.directus_permissions
    set fields = rules_fields
    where collection = 'robot_diagnostic_rules'
      and action in ('read', 'create', 'update')
      and policy = livekit_policy;

    update public.directus_permissions
    set fields = audits_fields
    where collection = 'robot_call_audits'
      and action in ('read', 'create', 'update')
      and policy = livekit_policy;
end $$;
