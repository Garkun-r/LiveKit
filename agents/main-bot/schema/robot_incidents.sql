create table if not exists public.robot_incidents (
    id bigserial primary key,
    created_at timestamptz not null default now(),
    environment text not null,
    source text not null,
    severity text not null check (severity in ('info', 'warning', 'error', 'critical')),
    incident_type text not null,
    status text not null default 'open',
    caller_phone text,
    did text,
    trace_id text,
    room_name text,
    job_id text,
    sip_call_id text,
    component text,
    provider text,
    model text,
    latency_ms integer,
    error_type text,
    description text not null,
    fingerprint text,
    payload jsonb not null default '{}'::jsonb
);

create index if not exists robot_incidents_created_at_idx
    on public.robot_incidents (created_at desc);

create index if not exists robot_incidents_status_created_at_idx
    on public.robot_incidents (status, created_at desc);

create index if not exists robot_incidents_type_created_at_idx
    on public.robot_incidents (incident_type, created_at desc);

create index if not exists robot_incidents_room_name_idx
    on public.robot_incidents (room_name)
    where room_name is not null;

create index if not exists robot_incidents_caller_phone_idx
    on public.robot_incidents (caller_phone)
    where caller_phone is not null;

create index if not exists robot_incidents_payload_gin_idx
    on public.robot_incidents using gin (payload);

comment on table public.robot_incidents is
    'Best-effort diagnostic log for LiveKit robot incidents and abnormal runtime events.';

comment on column public.robot_incidents.environment is
    'Runtime label: cloud, local, staging, or another deployment name.';

comment on column public.robot_incidents.source is
    'Emitter name, for example livekit_agent, plugin, webhook, or future asterisk monitor.';

comment on column public.robot_incidents.incident_type is
    'Stable machine-readable incident name such as provider_fallback or slow_response.';

comment on column public.robot_incidents.payload is
    'Sanitized JSON payload with event-specific diagnostics.';
