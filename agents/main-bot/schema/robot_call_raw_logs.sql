create table if not exists public.robot_call_raw_logs (
    id bigserial primary key,
    created_at timestamptz not null default now(),
    event_time timestamptz not null default now(),
    call_session bigint references public.robot_call_sessions(id) on delete set null,
    source text not null default 'livekit_agent',
    agent_name text,
    runtime_profile text,
    room_name text,
    session_id text,
    job_id text,
    trace_id text,
    sip_call_id text,
    sequence bigint not null default 0,
    level text not null default 'INFO',
    logger_name text,
    message text,
    raw_text text,
    module text,
    function_name text,
    line_no integer,
    task_name text,
    payload jsonb not null default '{}'::jsonb
);

create index if not exists robot_call_raw_logs_room_time_idx
    on public.robot_call_raw_logs (room_name, event_time, sequence)
    where room_name is not null;

create index if not exists robot_call_raw_logs_session_time_idx
    on public.robot_call_raw_logs (session_id, event_time, sequence)
    where session_id is not null;

create index if not exists robot_call_raw_logs_call_session_idx
    on public.robot_call_raw_logs (call_session, event_time, sequence)
    where call_session is not null;

create index if not exists robot_call_raw_logs_level_idx
    on public.robot_call_raw_logs (level)
    where level is not null;

comment on table public.robot_call_raw_logs is
    'Per-call raw LiveKit agent log lines captured during the call, separate from aftercall JSON.';

comment on column public.robot_call_raw_logs.raw_text is
    'Preformatted redacted log line including exception text when available.';
