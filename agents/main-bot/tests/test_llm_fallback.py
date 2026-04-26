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


def test_build_complex_branch_fallback_uses_google_backup(monkeypatch) -> None:
    def fake_build(provider: str, model_name: str | None = None) -> _FakeLLM:
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
    assert metadata.backup_provider == "google"
    assert metadata.backup_model == "gemini-lite"
    assert metadata.uses_fallback_adapter is True


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
async def test_end_call_stops_tool_reply_generation() -> None:
    requested_reasons: list[str] = []

    async def request_end_call(_, reason: str) -> str:
        requested_reasons.append(reason)
        return "END_CALL_SCHEDULED"

    assistant = agent.Assistant(request_end_call=request_end_call)

    with pytest.raises(agent.StopResponse):
        await assistant.end_call._func(
            assistant,
            object(),
            "conversation_completed",
        )

    assert requested_reasons == ["conversation_completed"]
