create table if not exists public.robot_call_sessions (
    id bigserial primary key,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    source text not null default 'livekit_agent',
    agent_name text,
    runtime_profile text,
    room_name text not null unique,
    session_id text,
    lead_session_id text,
    client_id bigint,
    client_name text,
    phone_number text,
    xdid text,
    did text,
    gateway_number text,
    sip_call_id text,
    job_id text,
    trace_id text,
    started_at timestamptz,
    ended_at timestamptz,
    duration_sec numeric,
    status text not null default 'completed',
    close_reason text,
    prompt_source text,
    chat_history text,
    transcript_items jsonb not null default '[]'::jsonb,
    tag_events jsonb not null default '[]'::jsonb,
    usage_updates jsonb not null default '[]'::jsonb,
    metrics_summary jsonb not null default '{}'::jsonb,
    payload jsonb not null default '{}'::jsonb
);

create table if not exists public.robot_call_recordings (
    id bigserial primary key,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    call_session bigint references public.robot_call_sessions(id) on delete set null,
    source text not null default 'livekit_egress',
    room_name text,
    session_id text,
    egress_id text,
    status text not null default 'completed',
    storage_provider text not null default 'minio',
    storage_bucket text,
    object_key text not null,
    file_name text,
    mime_type text not null default 'audio/mpeg',
    file_size bigint,
    duration_sec numeric,
    started_at timestamptz,
    ended_at timestamptz,
    manifest_key text,
    error text,
    payload jsonb not null default '{}'::jsonb,
    unique (egress_id),
    unique (object_key)
);

create index if not exists robot_call_sessions_started_at_idx
    on public.robot_call_sessions (started_at desc);

create index if not exists robot_call_sessions_phone_number_idx
    on public.robot_call_sessions (phone_number)
    where phone_number is not null;

create index if not exists robot_call_sessions_xdid_idx
    on public.robot_call_sessions (xdid)
    where xdid is not null;

create index if not exists robot_call_sessions_agent_name_idx
    on public.robot_call_sessions (agent_name)
    where agent_name is not null;

create index if not exists robot_call_sessions_client_id_idx
    on public.robot_call_sessions (client_id)
    where client_id is not null;

create index if not exists robot_call_recordings_room_name_idx
    on public.robot_call_recordings (room_name)
    where room_name is not null;

create index if not exists robot_call_recordings_session_id_idx
    on public.robot_call_recordings (session_id)
    where session_id is not null;

create index if not exists robot_call_recordings_call_session_idx
    on public.robot_call_recordings (call_session)
    where call_session is not null;

comment on table public.robot_call_sessions is
    'One operational row per LiveKit robot call for cabinet search, chat, logs and reports.';

comment on table public.robot_call_recordings is
    'Private MinIO/S3 objects produced by LiveKit Egress for robot call playback.';

comment on column public.robot_call_recordings.object_key is
    'Private S3/MinIO object key. Browsers must access it through a backend proxy only.';
