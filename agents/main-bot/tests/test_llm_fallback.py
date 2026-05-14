import asyncio

import pytest
from livekit.agents import (
    DEFAULT_API_CONNECT_OPTIONS,
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    llm,
)

import agent


class _FakeLLM(llm.LLM):
    def __init__(
        self,
        *,
        provider: str,
        model: str,
        behavior: str,
        call_order: list[str] | None = None,
    ) -> None:
        super().__init__()
        self._provider = provider
        self._model = model
        self.behavior = behavior
        self.call_order = call_order
        self.calls = 0
        self.seen_timeouts: list[float] = []
        self.seen_max_retries: list[int] = []
        self.seen_retry_intervals: list[float] = []
        self.seen_tools: list[list[object]] = []

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model(self) -> str:
        return self._model

    def chat(
        self,
        *,
        chat_ctx: llm.ChatContext,
        tools: list[llm.Tool] | None = None,
        conn_options=DEFAULT_API_CONNECT_OPTIONS,
        parallel_tool_calls=agent.NOT_GIVEN,
        tool_choice=agent.NOT_GIVEN,
        extra_kwargs=agent.NOT_GIVEN,
    ) -> llm.LLMStream:
        self.calls += 1
        if self.call_order is not None:
            self.call_order.append(self.model)
        self.seen_timeouts.append(conn_options.timeout)
        self.seen_max_retries.append(conn_options.max_retry)
        self.seen_retry_intervals.append(conn_options.retry_interval)
        self.seen_tools.append(list(tools or []))
        return _FakeLLMStream(
            self,
            chat_ctx=chat_ctx,
            tools=tools or [],
            conn_options=conn_options,
        )


class _FakeLLMStream(llm.LLMStream):
    async def _run(self) -> None:
        fake_llm = self._llm
        behavior = fake_llm.behavior
        if behavior == "timeout":
            await asyncio.sleep(0)
            raise APITimeoutError("primary timed out")
        if behavior == "api_500":
            raise APIStatusError("primary failed", status_code=500)
        if behavior == "network":
            raise APIConnectionError("network failed")
        if behavior == "chunk_then_fail":
            self._event_ch.send_nowait(
                llm.ChatChunk(
                    id=fake_llm.model,
                    delta=llm.ChoiceDelta(role="assistant", content="partial"),
                )
            )
            raise APIConnectionError("failed after first chunk")

        self._event_ch.send_nowait(
            llm.ChatChunk(
                id=fake_llm.model,
                delta=llm.ChoiceDelta(role="assistant", content=fake_llm.model),
            )
        )


class _FakePromptHandle:
    def __init__(self, *, done: bool = True) -> None:
        self._done = asyncio.Event()
        if done:
            self._done.set()
        self.stopped = False
        self.interrupted = False

    def done(self) -> bool:
        return self._done.is_set()

    def finish(self) -> None:
        self._done.set()

    def stop(self) -> None:
        self.stopped = True
        self.finish()

    def interrupt(self, *, force: bool = False) -> None:
        self.interrupted = force
        self.finish()

    async def wait_for_playout(self) -> None:
        await self._done.wait()


class _FakeBackgroundAudio:
    def __init__(self, handle: _FakePromptHandle | None = None) -> None:
        self.handle = handle or _FakePromptHandle()
        self.played: list[str] = []

    def play(self, audio: str, *, loop: bool = False) -> _FakePromptHandle:
        self.played.append(audio)
        return self.handle


class _FakePromptSession:
    def __init__(self) -> None:
        self.agent_state = "listening"
        self.current_speech = None
        self.say_calls: list[dict[str, object]] = []
        self.handle = _FakePromptHandle()

    def say(
        self,
        text: str,
        *,
        audio,
        allow_interruptions: bool,
        add_to_chat_ctx: bool,
    ) -> _FakePromptHandle:
        self.say_calls.append(
            {
                "text": text,
                "audio": audio,
                "allow_interruptions": allow_interruptions,
                "add_to_chat_ctx": add_to_chat_ctx,
            }
        )
        return self.handle


class _FakeVoiceAudioCache:
    def __init__(self, path) -> None:
        self.path = path
        self.calls: list[dict[str, object]] = []

    async def get_or_create(self, *, kind: str, text: str, legacy_path=None):
        self.calls.append({"kind": kind, "text": text, "legacy_path": legacy_path})
        return self.path


class _FakeIncidentLog:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def record_nowait(self, incident_type: str, **kwargs) -> None:
        self.records.append({"incident_type": incident_type, **kwargs})


def _voice_prompt_manager(
    *,
    tmp_path,
    session: _FakePromptSession | None = None,
    background_audio: _FakeBackgroundAudio | None = None,
    voice_audio_cache=None,
    response_delay_sec: float = 0.01,
    response_delay_post_gap_sec: float = 0.0,
    client_silence_first_sec: float | None = None,
    client_silence_sec: float = 0.01,
    client_silence_stt_grace_sec: float = 0.0,
    client_silence_max_prompts: int = 2,
    client_silence_audio_paths=None,
    speech_playout_timeout_sec: float = 12.0,
    is_closed=lambda: False,
    is_end_call_scheduled=lambda: False,
    is_client_disconnected=lambda: False,
    client_disconnect_info=lambda: {},
    on_client_silence_timeout=None,
    incident_log=None,
) -> tuple[agent.VoicePromptManager, _FakePromptSession, _FakeBackgroundAudio]:
    response_delay_audio = tmp_path / "response_delay.wav"
    client_silence_audio = tmp_path / "client_silence.wav"
    response_delay_audio.write_bytes(b"fake")
    client_silence_audio.write_bytes(b"fake")
    if client_silence_audio_paths is None:
        client_silence_audio_paths = (client_silence_audio,)
    session = session or _FakePromptSession()
    background_audio = background_audio or _FakeBackgroundAudio()
    if on_client_silence_timeout is None:

        async def on_client_silence_timeout() -> None:
            return None

    manager = agent.VoicePromptManager(
        session=session,
        background_audio=background_audio,
        voice_audio_cache=voice_audio_cache,
        response_delay_prompt=agent.VoicePromptSpec(
            kind="response_delay",
            audio_paths=(response_delay_audio,),
            phrase="Секундочку.",
        ),
        client_silence_prompt=agent.VoicePromptSpec(
            kind="client_silence",
            audio_paths=tuple(client_silence_audio_paths),
            phrase="Алло.",
            prefer_prerecorded=True,
        ),
        response_delay_sec=response_delay_sec,
        response_delay_post_gap_sec=response_delay_post_gap_sec,
        client_silence_first_sec=(
            client_silence_sec
            if client_silence_first_sec is None
            else client_silence_first_sec
        ),
        client_silence_sec=client_silence_sec,
        client_silence_stt_grace_sec=client_silence_stt_grace_sec,
        client_silence_max_prompts=client_silence_max_prompts,
        is_closed=is_closed,
        is_end_call_scheduled=is_end_call_scheduled,
        on_client_silence_timeout=on_client_silence_timeout,
        is_client_disconnected=is_client_disconnected,
        client_disconnect_info=client_disconnect_info,
        speech_playout_timeout_sec=speech_playout_timeout_sec,
        incident_log=incident_log,
    )
    return manager, session, background_audio


async def _wait_until(predicate, *, timeout: float = 0.3) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("condition was not reached before timeout")
        await asyncio.sleep(0.005)


async def _collect_text(adapter: llm.LLM) -> str:
    parts: list[str] = []
    async with adapter.chat(chat_ctx=llm.ChatContext.empty(), tools=[]) as stream:
        async for chunk in stream:
            if chunk.delta and chunk.delta.content:
                parts.append(chunk.delta.content)
    return "".join(parts)


@pytest.mark.asyncio
async def test_fallback_adapter_timeout_goes_to_backup() -> None:
    call_order: list[str] = []
    primary = _FakeLLM(
        provider="xai",
        model="fast-primary",
        behavior="timeout",
        call_order=call_order,
    )
    backup = _FakeLLM(
        provider="google",
        model="fast-backup",
        behavior="success",
        call_order=call_order,
    )
    adapter = llm.FallbackAdapter(
        [primary, backup],
        attempt_timeout=0.01,
        max_retry_per_llm=0,
        retry_interval=0.3,
        retry_on_chunk_sent=False,
    )

    assert await _collect_text(adapter) == "fast-backup"
    assert call_order[:2] == ["fast-primary", "fast-backup"]
    assert backup.calls == 1
    assert primary.seen_timeouts[0] == 0.01
    assert primary.seen_max_retries[0] == 0
    assert primary.seen_retry_intervals[0] == 0.3


@pytest.mark.asyncio
async def test_fallback_adapter_api_error_goes_to_backup() -> None:
    call_order: list[str] = []
    primary = _FakeLLM(
        provider="google",
        model="complex-primary",
        behavior="api_500",
        call_order=call_order,
    )
    backup = _FakeLLM(
        provider="google",
        model="complex-backup",
        behavior="success",
        call_order=call_order,
    )
    adapter = llm.FallbackAdapter(
        [primary, backup],
        attempt_timeout=0.01,
        max_retry_per_llm=0,
        retry_interval=0.3,
        retry_on_chunk_sent=False,
    )

    assert await _collect_text(adapter) == "complex-backup"
    assert call_order[:2] == ["complex-primary", "complex-backup"]
    assert backup.calls == 1


@pytest.mark.asyncio
async def test_fallback_adapter_network_error_goes_to_backup() -> None:
    call_order: list[str] = []
    primary = _FakeLLM(
        provider="google",
        model="complex-primary",
        behavior="network",
        call_order=call_order,
    )
    backup = _FakeLLM(
        provider="google",
        model="complex-backup",
        behavior="success",
        call_order=call_order,
    )
    adapter = llm.FallbackAdapter(
        [primary, backup],
        attempt_timeout=0.01,
        max_retry_per_llm=0,
        retry_interval=0.3,
        retry_on_chunk_sent=False,
    )

    assert await _collect_text(adapter) == "complex-backup"
    assert call_order[:2] == ["complex-primary", "complex-backup"]
    assert backup.calls == 1


@pytest.mark.asyncio
async def test_fallback_adapter_all_llms_unavailable_raises() -> None:
    primary = _FakeLLM(provider="xai", model="fast-primary", behavior="network")
    backup = _FakeLLM(provider="google", model="fast-backup", behavior="api_500")
    adapter = llm.FallbackAdapter(
        [primary, backup],
        attempt_timeout=0.01,
        max_retry_per_llm=0,
        retry_interval=0.3,
        retry_on_chunk_sent=False,
    )

    with pytest.raises(APIConnectionError, match="all LLMs failed"):
        await _collect_text(adapter)


@pytest.mark.asyncio
async def test_fallback_adapter_does_not_retry_after_chunk_by_default() -> None:
    primary = _FakeLLM(provider="xai", model="fast-primary", behavior="chunk_then_fail")
    backup = _FakeLLM(provider="google", model="fast-backup", behavior="success")
    adapter = llm.FallbackAdapter(
        [primary, backup],
        attempt_timeout=0.01,
        max_retry_per_llm=0,
        retry_interval=0.3,
        retry_on_chunk_sent=False,
    )

    with pytest.raises(APIConnectionError, match="failed after first chunk"):
        await _collect_text(adapter)
    assert primary.calls == 1
    assert backup.calls == 0


def test_build_fast_branch_fallback_uses_xai_primary_and_google_backup(
    monkeypatch,
) -> None:
    def fake_build(provider: str, model_name: str | None = None) -> _FakeLLM:
        return _FakeLLM(
            provider=provider,
            model=model_name or f"{provider}-default",
            behavior="success",
        )

    monkeypatch.setattr(agent, "USE_LIVEKIT_FALLBACK_ADAPTER", True)
    monkeypatch.setattr(agent, "FAST_LLM_BACKUP_PROVIDER", "google")
    monkeypatch.setattr(agent, "FAST_LLM_BACKUP_MODEL", "gemini-lite")
    monkeypatch.setattr(agent, "build_llm_for_provider", fake_build)

    client, metadata = agent.build_llm_client_for_branch(
        branch="fast",
        primary_provider="xai",
        primary_model="grok-fast",
    )

    assert isinstance(client, llm.FallbackAdapter)
    assert metadata.branch == "fast"
    assert metadata.primary_provider == "xai"
    assert metadata.primary_model == "grok-fast"
    assert metadata.backup_provider == "google"
    assert metadata.backup_model == "gemini-lite"
    assert metadata.uses_fallback_adapter is True


def test_build_complex_branch_fallback_uses_vertex_backup_for_google_primary(
    monkeypatch,
) -> None:
    build_calls: list[
        tuple[str, str | None, agent.ComponentSelection | None]
    ] = []

    def fake_build(
        provider: str,
        model_name: str | None = None,
        llm_profile: agent.ComponentSelection | None = None,
    ) -> _FakeLLM:
        build_calls.append((provider, model_name, llm_profile))
        return _FakeLLM(
            provider=provider,
            model=model_name or f"{provider}-default",
            behavior="success",
        )

    monkeypatch.setattr(agent, "USE_LIVEKIT_FALLBACK_ADAPTER", True)
    monkeypatch.setattr(agent, "COMPLEX_LLM_BACKUP_PROVIDER", "google")
    monkeypatch.setattr(agent, "COMPLEX_LLM_BACKUP_MODEL", "gemini-lite")
    monkeypatch.setattr(agent, "build_llm_for_provider", fake_build)

    client, metadata = agent.build_llm_client_for_branch(
        branch="complex",
        primary_provider="google",
        primary_model="gemini-flash",
    )

    assert isinstance(client, llm.FallbackAdapter)
    assert metadata.branch == "complex"
    assert metadata.primary_provider == "google"
    assert metadata.primary_model == "gemini-flash"
    assert metadata.backup_provider == "google_vertex"
    assert metadata.backup_model == "gemini-lite"
    assert metadata.uses_fallback_adapter is True
    backup_provider, backup_model, backup_profile = build_calls[1]
    assert backup_provider == "google_vertex"
    assert backup_model == "gemini-lite"
    assert backup_profile is not None
    assert backup_profile.config == {
        "provider": "google_vertex",
        "model": "gemini-lite",
        "location": "eu",
    }


def test_build_branch_fallback_uses_profile_backup_route(monkeypatch) -> None:
    build_calls: list[
        tuple[str, str | None, agent.ComponentSelection | None]
    ] = []

    def fake_build(
        provider: str,
        model_name: str | None = None,
        llm_profile: agent.ComponentSelection | None = None,
    ) -> _FakeLLM:
        build_calls.append((provider, model_name, llm_profile))
        return _FakeLLM(
            provider=provider,
            model=model_name or f"{provider}-default",
            behavior="success",
        )

    monkeypatch.setattr(agent, "USE_LIVEKIT_FALLBACK_ADAPTER", False)
    monkeypatch.setattr(agent, "build_llm_for_provider", fake_build)
    primary_profile = agent.ComponentSelection(
        category="llm",
        slot="primary",
        profile_key="llm_gemini_31_flash_lite_proxy",
        kind="llm",
        provider="google",
        config={
            "provider": "google",
            "model": "gemini-3.1-flash-lite",
            "fallback_provider": "google_vertex",
            "fallback_model": "gemini-3.1-flash-lite",
            "fallback_location": "eu",
            "fallback_egress": "proxy",
            "use_livekit_fallback_adapter": True,
        },
        source_owner_type="runtime",
        source_owner_key="base",
    )

    client, metadata = agent.build_llm_client_for_branch(
        branch="complex",
        primary_provider="google",
        primary_profile=primary_profile,
    )

    assert isinstance(client, llm.FallbackAdapter)
    assert metadata.backup_provider == "google_vertex"
    assert metadata.backup_model == "gemini-3.1-flash-lite"
    assert metadata.uses_fallback_adapter is True
    assert len(build_calls) == 2
    backup_provider, backup_model, backup_profile = build_calls[1]
    assert backup_provider == "google_vertex"
    assert backup_model == "gemini-3.1-flash-lite"
    assert backup_profile is not None
    assert backup_profile.config == {
        "provider": "google_vertex",
        "model": "gemini-3.1-flash-lite",
        "location": "eu",
        "egress": "proxy",
    }


def test_llm_fallback_same_provider_risk_ignores_vertex_backup() -> None:
    assert (
        agent.llm_fallback_same_provider_risk(
            agent.LLMBranchMetadata(
                branch="fast",
                primary_provider="Gemini",
                primary_model="gemini-3.1-flash-lite",
                backup_provider="Vertex AI",
                backup_model="gemini-3.1-flash-lite",
                uses_fallback_adapter=True,
            )
        )
        is False
    )


def test_llm_fallback_same_provider_risk_records_incident() -> None:
    incident_log = _FakeIncidentLog()
    metadata = agent.LLMBranchMetadata(
        branch="complex",
        primary_provider="Gemini",
        primary_model="gemini-3-flash-preview",
        backup_provider="Gemini",
        backup_model="gemini-3.1-flash-lite",
        uses_fallback_adapter=True,
    )

    agent.record_llm_fallback_configuration_incidents(
        {"complex": metadata},
        incident_log,
    )

    assert [item["incident_type"] for item in incident_log.records] == [
        "llm_fallback_same_provider"
    ]
    assert incident_log.records[0]["payload"]["branch"] == "complex"
    assert (
        incident_log.records[0]["payload"]["risk"]
        == "provider_account_quota_wide_failure"
    )


@pytest.mark.asyncio
async def test_missing_prerecorded_audio_does_not_crash(tmp_path) -> None:
    missing_path = tmp_path / "missing.wav"

    played = await agent.play_prerecorded_audio(
        session=object(),
        audio_path=missing_path,
        sample_rate=24000,
        allow_interruptions=False,
        add_to_chat_ctx=False,
    )

    assert played is False


@pytest.mark.asyncio
async def test_response_delay_prompt_fires_after_timer(tmp_path) -> None:
    manager, _, background_audio = _voice_prompt_manager(tmp_path=tmp_path)

    manager.start_response_delay_timer()
    await asyncio.sleep(0.05)
    await manager.aclose()

    assert background_audio.played == [str(tmp_path / "response_delay.wav")]


@pytest.mark.asyncio
async def test_response_delay_prompt_uses_voice_audio_cache(tmp_path) -> None:
    cached_path = tmp_path / "cached.wav"
    cached_path.write_bytes(b"fake")
    voice_audio_cache = _FakeVoiceAudioCache(cached_path)
    manager, _, background_audio = _voice_prompt_manager(
        tmp_path=tmp_path,
        voice_audio_cache=voice_audio_cache,
    )

    manager.start_response_delay_timer()
    await asyncio.sleep(0.05)
    await manager.aclose()

    assert background_audio.played == [str(cached_path)]
    assert voice_audio_cache.calls == [
        {
            "kind": "response_delay",
            "text": "Секундочку.",
            "legacy_path": tmp_path / "response_delay.wav",
        }
    ]


@pytest.mark.asyncio
async def test_response_delay_prompt_skips_if_agent_is_speaking(tmp_path) -> None:
    session = _FakePromptSession()
    session.agent_state = "speaking"
    manager, _, background_audio = _voice_prompt_manager(
        tmp_path=tmp_path,
        session=session,
    )

    manager.start_response_delay_timer()
    await asyncio.sleep(0.05)
    await manager.aclose()

    assert background_audio.played == []


@pytest.mark.asyncio
async def test_user_speech_cancels_pending_response_delay_prompt(tmp_path) -> None:
    manager, _, background_audio = _voice_prompt_manager(
        tmp_path=tmp_path,
        response_delay_sec=0.05,
    )

    manager.start_response_delay_timer()
    manager.on_user_started_speaking()
    await asyncio.sleep(0.08)
    await manager.aclose()

    assert background_audio.played == []


@pytest.mark.asyncio
async def test_response_delay_prompt_does_not_repeat_for_same_user_turn(
    tmp_path,
) -> None:
    manager, _, background_audio = _voice_prompt_manager(tmp_path=tmp_path)

    manager.start_response_delay_timer()
    await asyncio.sleep(0.05)
    manager.start_response_delay_timer()
    await asyncio.sleep(0.05)
    await manager.aclose()

    assert background_audio.played == [str(tmp_path / "response_delay.wav")]


@pytest.mark.asyncio
async def test_client_silence_prompt_uses_background_audio(tmp_path) -> None:
    close_reasons: list[str] = []

    async def on_client_silence_timeout() -> None:
        close_reasons.append("client_silence_timeout")

    manager, session, background_audio = _voice_prompt_manager(
        tmp_path=tmp_path,
        on_client_silence_timeout=on_client_silence_timeout,
    )

    manager.on_agent_finished_speaking()
    await _wait_until(lambda: len(background_audio.played) == 1)
    await manager.aclose()

    assert background_audio.played == [str(tmp_path / "client_silence.wav")]
    assert session.say_calls == []
    assert close_reasons == []


@pytest.mark.asyncio
async def test_client_silence_prompt_timeout_stops_background_audio(tmp_path) -> None:
    handle = _FakePromptHandle(done=False)
    background_audio = _FakeBackgroundAudio(handle=handle)
    manager, _, _ = _voice_prompt_manager(
        tmp_path=tmp_path,
        background_audio=background_audio,
        speech_playout_timeout_sec=0.01,
    )

    manager.on_agent_finished_speaking()
    await _wait_until(lambda: handle.stopped)
    await manager.aclose()

    assert background_audio.played == [str(tmp_path / "client_silence.wav")]


@pytest.mark.asyncio
async def test_client_silence_prompts_twice_then_requests_close(tmp_path) -> None:
    close_reasons: list[str] = []

    async def on_client_silence_timeout() -> None:
        close_reasons.append("client_silence_timeout")

    manager, session, background_audio = _voice_prompt_manager(
        tmp_path=tmp_path,
        on_client_silence_timeout=on_client_silence_timeout,
    )

    manager.on_agent_finished_speaking()
    await _wait_until(lambda: close_reasons == ["client_silence_timeout"])
    await manager.aclose()

    assert background_audio.played == [
        str(tmp_path / "client_silence.wav"),
        str(tmp_path / "client_silence.wav"),
    ]
    assert session.say_calls == []


@pytest.mark.asyncio
async def test_client_silence_second_prompt_uses_second_audio(tmp_path) -> None:
    close_reasons: list[str] = []
    client_silence_audio = tmp_path / "client_silence.wav"
    client_silence_second_audio = tmp_path / "client_silence2.wav"
    client_silence_second_audio.write_bytes(b"fake")
    cached_path = tmp_path / "cached.wav"
    cached_path.write_bytes(b"fake")
    voice_audio_cache = _FakeVoiceAudioCache(cached_path)

    async def on_client_silence_timeout() -> None:
        close_reasons.append("client_silence_timeout")

    manager, _, background_audio = _voice_prompt_manager(
        tmp_path=tmp_path,
        client_silence_audio_paths=(
            client_silence_audio,
            client_silence_second_audio,
        ),
        voice_audio_cache=voice_audio_cache,
        on_client_silence_timeout=on_client_silence_timeout,
    )

    manager.on_agent_finished_speaking()
    await _wait_until(lambda: close_reasons == ["client_silence_timeout"])
    await manager.aclose()

    assert background_audio.played == [
        str(client_silence_audio),
        str(client_silence_second_audio),
    ]
    assert voice_audio_cache.calls == []


@pytest.mark.asyncio
async def test_client_silence_uses_first_delay_then_repeat_delay(tmp_path) -> None:
    close_reasons: list[str] = []

    async def on_client_silence_timeout() -> None:
        close_reasons.append("client_silence_timeout")

    manager, _, background_audio = _voice_prompt_manager(
        tmp_path=tmp_path,
        client_silence_first_sec=0.04,
        client_silence_sec=0.01,
        on_client_silence_timeout=on_client_silence_timeout,
    )

    manager.on_agent_finished_speaking()
    await asyncio.sleep(0.02)

    assert background_audio.played == []

    await _wait_until(lambda: close_reasons == ["client_silence_timeout"])
    await manager.aclose()

    assert background_audio.played == [
        str(tmp_path / "client_silence.wav"),
        str(tmp_path / "client_silence.wav"),
    ]


@pytest.mark.asyncio
async def test_client_silence_prompt_waits_until_agent_has_spoken(tmp_path) -> None:
    manager, session, background_audio = _voice_prompt_manager(tmp_path=tmp_path)

    manager.start_client_silence_timer()
    await asyncio.sleep(0.05)
    await manager.aclose()

    assert background_audio.played == []
    assert session.say_calls == []


@pytest.mark.asyncio
async def test_vad_user_speech_pauses_client_silence_prompt(tmp_path) -> None:
    close_reasons: list[str] = []

    async def on_client_silence_timeout() -> None:
        close_reasons.append("client_silence_timeout")

    manager, session, background_audio = _voice_prompt_manager(
        tmp_path=tmp_path,
        on_client_silence_timeout=on_client_silence_timeout,
    )

    manager.on_agent_finished_speaking()
    manager.on_user_started_speaking()
    manager.start_client_silence_timer()
    await asyncio.sleep(0.05)
    await manager.aclose()

    assert background_audio.played == []
    assert session.say_calls == []
    assert close_reasons == []


@pytest.mark.asyncio
async def test_vad_only_user_speech_does_not_reset_client_silence_deadline(
    tmp_path,
) -> None:
    close_reasons: list[str] = []

    async def on_client_silence_timeout() -> None:
        close_reasons.append("client_silence_timeout")

    manager, session, background_audio = _voice_prompt_manager(
        tmp_path=tmp_path,
        client_silence_sec=0.05,
        client_silence_stt_grace_sec=0.03,
        on_client_silence_timeout=on_client_silence_timeout,
    )

    manager.on_agent_finished_speaking()
    await asyncio.sleep(0.04)
    manager.on_user_started_speaking()
    await asyncio.sleep(0.04)

    assert background_audio.played == []
    assert close_reasons == []

    manager.on_user_finished_speaking()
    await asyncio.sleep(0.01)

    assert background_audio.played == []

    await _wait_until(lambda: len(background_audio.played) == 1, timeout=0.05)
    await manager.aclose()

    assert background_audio.played == [str(tmp_path / "client_silence.wav")]
    assert session.say_calls == []


@pytest.mark.asyncio
async def test_stt_transcript_resets_client_silence_sequence(tmp_path) -> None:
    close_reasons: list[str] = []

    async def on_client_silence_timeout() -> None:
        close_reasons.append("client_silence_timeout")

    manager, session, background_audio = _voice_prompt_manager(
        tmp_path=tmp_path,
        on_client_silence_timeout=on_client_silence_timeout,
    )

    manager.on_agent_finished_speaking()
    await _wait_until(lambda: len(background_audio.played) == 1)
    manager.on_user_transcribed(is_final=True)
    await asyncio.sleep(0.05)

    assert close_reasons == []

    manager.on_agent_finished_speaking()
    await _wait_until(lambda: close_reasons == ["client_silence_timeout"])
    await manager.aclose()

    assert background_audio.played == [
        str(tmp_path / "client_silence.wav"),
        str(tmp_path / "client_silence.wav"),
        str(tmp_path / "client_silence.wav"),
    ]
    assert session.say_calls == []


@pytest.mark.asyncio
async def test_interim_stt_defers_client_silence_prompt(tmp_path) -> None:
    close_reasons: list[str] = []

    async def on_client_silence_timeout() -> None:
        close_reasons.append("client_silence_timeout")

    manager, session, background_audio = _voice_prompt_manager(
        tmp_path=tmp_path,
        client_silence_sec=0.05,
        on_client_silence_timeout=on_client_silence_timeout,
    )

    manager.on_agent_finished_speaking()
    await asyncio.sleep(0.04)
    manager.on_user_transcribed(is_final=False)
    await asyncio.sleep(0.02)

    assert background_audio.played == []
    assert close_reasons == []

    manager.on_user_transcribed(is_final=True)
    await asyncio.sleep(0.05)
    await manager.aclose()

    assert background_audio.played == []
    assert session.say_calls == []
    assert close_reasons == []


@pytest.mark.asyncio
async def test_user_speech_resets_client_silence_sequence(tmp_path) -> None:
    close_reasons: list[str] = []

    async def on_client_silence_timeout() -> None:
        close_reasons.append("client_silence_timeout")

    manager, session, background_audio = _voice_prompt_manager(
        tmp_path=tmp_path,
        on_client_silence_timeout=on_client_silence_timeout,
    )

    manager.on_agent_finished_speaking()
    await _wait_until(lambda: len(background_audio.played) == 1)
    manager.on_user_started_speaking()
    manager.on_user_transcribed(is_final=True)
    await asyncio.sleep(0.05)

    assert close_reasons == []

    manager.on_agent_finished_speaking()
    await _wait_until(lambda: close_reasons == ["client_silence_timeout"])
    await manager.aclose()

    assert background_audio.played == [
        str(tmp_path / "client_silence.wav"),
        str(tmp_path / "client_silence.wav"),
        str(tmp_path / "client_silence.wav"),
    ]
    assert session.say_calls == []


@pytest.mark.asyncio
async def test_client_silence_prompt_does_not_start_during_end_call(tmp_path) -> None:
    close_reasons: list[str] = []

    async def on_client_silence_timeout() -> None:
        close_reasons.append("client_silence_timeout")

    manager, session, background_audio = _voice_prompt_manager(
        tmp_path=tmp_path,
        is_end_call_scheduled=lambda: True,
        on_client_silence_timeout=on_client_silence_timeout,
    )

    manager.on_agent_finished_speaking()
    await asyncio.sleep(0.05)
    await manager.aclose()

    assert background_audio.played == []
    assert session.say_calls == []
    assert close_reasons == []


@pytest.mark.asyncio
async def test_client_silence_prompt_does_not_resolve_audio_after_disconnect(
    tmp_path,
) -> None:
    disconnected = False
    incident_log = _FakeIncidentLog()
    voice_audio_cache = _FakeVoiceAudioCache(tmp_path / "client_silence_cached.wav")
    voice_audio_cache.path.write_bytes(b"fake")
    manager, session, background_audio = _voice_prompt_manager(
        tmp_path=tmp_path,
        voice_audio_cache=voice_audio_cache,
        client_silence_sec=0.02,
        is_client_disconnected=lambda: disconnected,
        client_disconnect_info=lambda: {
            "disconnect_time": "2026-05-12T10:02:29.224Z",
            "disconnect_reason": "CLIENT_INITIATED",
            "participant_identity": "sip_9000828563",
        },
        incident_log=incident_log,
    )

    manager.on_agent_finished_speaking()
    disconnected = True
    await asyncio.sleep(0.05)
    await manager.aclose()

    assert voice_audio_cache.calls == []
    assert background_audio.played == []
    assert session.say_calls == []
    assert [item["incident_type"] for item in incident_log.records] == [
        "voice_prompt_after_disconnect"
    ]
    assert incident_log.records[0]["payload"]["prompt_kind"] == "client_silence"
    assert incident_log.records[0]["payload"]["disconnect_reason"] == "CLIENT_INITIATED"


@pytest.mark.asyncio
async def test_client_disconnect_cancels_pending_voice_prompt_timer(tmp_path) -> None:
    manager, session, background_audio = _voice_prompt_manager(
        tmp_path=tmp_path,
        client_silence_sec=0.02,
    )

    manager.on_agent_finished_speaking()
    manager.on_client_disconnected()
    await asyncio.sleep(0.05)
    await manager.aclose()

    assert background_audio.played == []
    assert session.say_calls == []


@pytest.mark.asyncio
async def test_client_silence_timeout_skips_when_agent_is_not_listening(
    tmp_path,
) -> None:
    close_reasons: list[str] = []

    async def on_client_silence_timeout() -> None:
        close_reasons.append("client_silence_timeout")

    session = _FakePromptSession()
    session.agent_state = "speaking"
    manager, session, background_audio = _voice_prompt_manager(
        tmp_path=tmp_path,
        session=session,
        on_client_silence_timeout=on_client_silence_timeout,
    )

    manager.on_agent_finished_speaking()
    await asyncio.sleep(0.05)
    await manager.aclose()

    assert background_audio.played == []
    assert session.say_calls == []
    assert close_reasons == []


@pytest.mark.asyncio
async def test_client_silence_timeout_skips_when_current_speech_is_active(
    tmp_path,
) -> None:
    close_reasons: list[str] = []

    async def on_client_silence_timeout() -> None:
        close_reasons.append("client_silence_timeout")

    session = _FakePromptSession()
    session.current_speech = _FakePromptHandle(done=False)
    manager, session, background_audio = _voice_prompt_manager(
        tmp_path=tmp_path,
        session=session,
        on_client_silence_timeout=on_client_silence_timeout,
    )

    manager.on_agent_finished_speaking()
    await asyncio.sleep(0.05)
    await manager.aclose()

    assert background_audio.played == []
    assert session.say_calls == []
    assert close_reasons == []


@pytest.mark.asyncio
async def test_user_speech_stops_active_client_silence_prompt(tmp_path) -> None:
    handle = _FakePromptHandle(done=False)
    background_audio = _FakeBackgroundAudio(handle=handle)
    manager, session, _ = _voice_prompt_manager(
        tmp_path=tmp_path,
        background_audio=background_audio,
    )

    manager.on_agent_finished_speaking()
    await _wait_until(
        lambda: background_audio.played == [str(tmp_path / "client_silence.wav")]
    )
    assert background_audio.played == [str(tmp_path / "client_silence.wav")]
    assert handle.stopped is False

    manager.on_user_started_speaking()
    await asyncio.sleep(0)
    await manager.aclose()

    assert handle.stopped is True
    assert session.say_calls == []


@pytest.mark.asyncio
async def test_wait_for_active_prompt_blocks_until_prompt_finishes(tmp_path) -> None:
    handle = _FakePromptHandle(done=False)
    manager, _, _ = _voice_prompt_manager(tmp_path=tmp_path)
    await manager._set_active_prompt("client_silence", handle)

    wait_task = asyncio.create_task(manager.wait_for_active_prompt())
    await asyncio.sleep(0)
    assert wait_task.done() is False

    handle.finish()
    await wait_task
    await manager.aclose()


@pytest.mark.asyncio
async def test_wait_for_active_prompt_waits_for_reserved_handle(tmp_path) -> None:
    handle = _FakePromptHandle(done=False)
    manager, _, _ = _voice_prompt_manager(tmp_path=tmp_path)
    assert await manager._reserve_active_prompt("client_silence") is True

    wait_task = asyncio.create_task(manager.wait_for_active_prompt())
    await asyncio.sleep(0.02)
    assert wait_task.done() is False

    await manager._set_active_prompt("client_silence", handle)
    await asyncio.sleep(0)
    assert wait_task.done() is False

    handle.finish()
    await wait_task
    await manager.aclose()


@pytest.mark.asyncio
async def test_wait_for_active_prompt_interrupts_response_delay_prompt(tmp_path) -> None:
    handle = _FakePromptHandle(done=False)
    manager, _, _ = _voice_prompt_manager(tmp_path=tmp_path)
    await manager._set_active_prompt("response_delay", handle)

    started_at = asyncio.get_running_loop().time()
    await manager.wait_for_active_prompt()
    elapsed = asyncio.get_running_loop().time() - started_at
    await manager.aclose()

    assert handle.stopped is True
    assert elapsed < 0.05


@pytest.mark.asyncio
async def test_agent_speech_interrupts_active_response_delay_prompt(tmp_path) -> None:
    handle = _FakePromptHandle(done=False)
    manager, _, _ = _voice_prompt_manager(tmp_path=tmp_path)
    await manager._set_active_prompt("response_delay", handle)

    manager.on_agent_started_speaking()
    await asyncio.sleep(0)
    await manager.aclose()

    assert handle.stopped is True


def test_end_call_tool_removed() -> None:
    assistant = agent.Assistant(prompt="test prompt")

    tool_names = [
        str(getattr(getattr(tool, "info", None), "name", "") or "")
        for tool in assistant.tools
    ]
    assert "end_call" not in tool_names
    assert not hasattr(assistant, "end_call")
