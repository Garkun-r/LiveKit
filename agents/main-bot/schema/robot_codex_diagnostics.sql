create table if not exists public.robot_diagnostic_rules (
    id bigserial primary key,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    enabled boolean not null default true,
    priority integer not null default 100,
    target text not null default 'both'
        check (target in ('cloud', 'local', 'both')),
    trigger_mode text not null
        check (trigger_mode in ('all_calls', 'incidents', 'xdid', 'caller', 'manual')),
    scope_value text,
    min_severity text not null default 'warning'
        check (min_severity in ('info', 'warning', 'error', 'critical')),
    telegram_policy text not null default 'anomaly_brief'
        check (telegram_policy in ('anomaly_brief', 'critical_only', 'silent')),
    cooldown_sec integer not null default 0 check (cooldown_sec >= 0),
    notes text
);

create table if not exists public.robot_call_audits (
    id bigserial primary key,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    status text not null default 'queued'
        check (status in ('queued', 'running', 'completed', 'failed', 'skipped')),
    target text not null check (target in ('cloud', 'local')),
    trigger_mode text not null
        check (trigger_mode in ('all_calls', 'incidents', 'xdid', 'caller', 'manual')),
    matched_rule bigint references public.robot_diagnostic_rules(id) on delete set null,
    caller_phone text,
    did text,
    xdid text,
    room_name text,
    sip_call_id text,
    started_at timestamptz,
    ended_at timestamptz,
    incident_ids jsonb not null default '[]'::jsonb,
    input_payload jsonb not null default '{}'::jsonb,
    livekit_snapshot jsonb not null default '{}'::jsonb,
    codex_thread_id text,
    codex_run_id text,
    verdict text check (verdict in ('ok', 'watch', 'needs_attention', 'critical')),
    report_markdown text,
    report_json jsonb not null default '{}'::jsonb,
    telegram_status text,
    telegram_message_id text,
    error text,
    dedupe_key text,
    audit_started_at timestamptz,
    completed_at timestamptz
);

create index if not exists robot_diagnostic_rules_enabled_idx
    on public.robot_diagnostic_rules (enabled, target, trigger_mode, priority);

create index if not exists robot_call_audits_created_at_idx
    on public.robot_call_audits (created_at desc);

create index if not exists robot_call_audits_status_created_at_idx
    on public.robot_call_audits (status, created_at desc);

create index if not exists robot_call_audits_target_created_at_idx
    on public.robot_call_audits (target, created_at desc);

create index if not exists robot_call_audits_room_name_idx
    on public.robot_call_audits (room_name)
    where room_name is not null;

create index if not exists robot_call_audits_caller_phone_idx
    on public.robot_call_audits (caller_phone)
    where caller_phone is not null;

create unique index if not exists robot_call_audits_dedupe_key_idx
    on public.robot_call_audits (dedupe_key)
    where dedupe_key is not null;

comment on table public.robot_diagnostic_rules is
    'Non-secret Directus control plane for post-call Codex diagnostics.';

comment on table public.robot_call_audits is
    'Post-call Codex diagnostic audit jobs and reports.';

comment on column public.robot_diagnostic_rules.target is
    'Which LiveKit environment this rule applies to: cloud, local, or both.';

comment on column public.robot_diagnostic_rules.trigger_mode is
    'all_calls, incidents, xdid, caller, or manual.';

comment on column public.robot_call_audits.livekit_snapshot is
    'Sanitized read-only LiveKit CLI snapshot collected by the VPS worker.';

comment on column public.robot_call_audits.report_json is
    'Structured Codex diagnostic result. Codex diagnoses only and must not auto-fix.';
