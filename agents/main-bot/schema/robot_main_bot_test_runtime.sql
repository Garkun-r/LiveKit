-- Add an isolated Directus runtime profile for the LiveKit Cloud test agent.
--
-- This seed is intentionally conservative:
-- - it creates or refreshes only the runtime identity fields for main_bot_test;
-- - it copies base profile bindings only where a main_bot_test binding is missing;
-- - it does not overwrite existing main_bot_test bindings, so test experiments survive reruns.

insert into public.robot_runtime_profiles (
    runtime_key,
    display_name,
    agent_name,
    environment,
    status,
    llm_profile,
    fast_llm_profile,
    complex_llm_profile,
    tts_profile,
    stt_profile,
    turn_profile,
    fallback_profile,
    override_json,
    active
) values (
    'main_bot_test',
    'Main Bot Test',
    'main-bot-test',
    'cloud-test',
    'draft',
    null,
    null,
    null,
    null,
    null,
    null,
    null,
    '{}'::jsonb,
    true
)
on conflict (runtime_key) do update set
    display_name = excluded.display_name,
    agent_name = excluded.agent_name,
    environment = excluded.environment,
    override_json = coalesce(public.robot_runtime_profiles.override_json, '{}'::jsonb),
    updated_at = now();

insert into public.robot_profile_bindings (
    owner_type,
    owner_key,
    category,
    slot,
    profile_key,
    note,
    sort,
    active
)
select
    'runtime',
    'main_bot_test',
    base.category,
    base.slot,
    base.profile_key,
    'Initial main_bot_test binding copied from base. Change this binding for test experiments instead of editing shared production component profiles.',
    base.sort,
    true
from public.robot_profile_bindings as base
where base.owner_type = 'runtime'
  and base.owner_key = 'base'
  and base.active is true
on conflict (owner_type, owner_key, category, slot) do nothing;

update public.directus_collections
set note = 'Среды запуска: base, livekit_cloud, main_bot_test, asterisk, mac. Сама среда хранит идентичность и override_json; выбор профилей хранится в robot_profile_bindings.'
where collection = 'robot_runtime_profiles';

update public.directus_fields
set note = 'base/livekit_cloud/main_bot_test/asterisk/mac или ключ клиентского профиля.'
where collection = 'robot_profile_bindings'
  and field = 'owner_key';

do $$
begin
    if not exists (
        select 1
        from public.robot_runtime_profiles
        where runtime_key = 'main_bot_test'
          and agent_name = 'main-bot-test'
          and environment = 'cloud-test'
    ) then
        raise exception 'main_bot_test runtime profile was not created correctly';
    end if;
end $$;
