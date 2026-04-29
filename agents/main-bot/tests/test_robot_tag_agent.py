import asyncio

import pytest
from livekit.agents import DEFAULT_API_CONNECT_OPTIONS, AgentSession, llm
from livekit.agents.types import NOT_GIVEN

from agent import Assistant


class _StaticLLM(llm.LLM):
    def __init__(self, chunks: list[str]) -> None:
        super().__init__()
        self._chunks = chunks

    @property
    def provider(self) -> str:
        return "static-test"

    @property
    def model(self) -> str:
        return "static-test-llm"

    def chat(
        self,
        *,
        chat_ctx: llm.ChatContext,
        tools: list[llm.Tool] | None = None,
        conn_options=DEFAULT_API_CONNECT_OPTIONS,
        parallel_tool_calls=NOT_GIVEN,
        tool_choice=NOT_GIVEN,
        extra_kwargs=NOT_GIVEN,
    ) -> llm.LLMStream:
        return _StaticLLMStream(
            self,
            chat_ctx=chat_ctx,
            tools=tools or [],
            conn_options=conn_options,
        )


class _StaticLLMStream(llm.LLMStream):
    async def _run(self) -> None:
        static_llm = self._llm
        for index, content in enumerate(static_llm._chunks):
            self._event_ch.send_nowait(
                llm.ChatChunk(
                    id=f"static-test-{index}",
                    delta=llm.ChoiceDelta(role="assistant", content=content),
                )
            )


class _FakeTagRunner:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def run(self, parsed, *, speech_handle_id, interrupted):
        self.calls.append(
            {
                "parsed": parsed,
                "speech_handle_id": speech_handle_id,
                "interrupted": interrupted,
            }
        )
        return {"status": "ok"}


async def _wait_for_runner_call(runner: _FakeTagRunner) -> None:
    for _ in range(20):
        if runner.calls:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("robot tag runner was not called")


def _assistant_texts(result) -> list[str]:
    return [
        event.item.text_content
        for event in result.events
        if getattr(event.item, "type", None) == "message"
        and getattr(event.item, "role", None) == "assistant"
    ]


@pytest.mark.asyncio
async def test_tagged_response_is_hidden_from_history_and_runner_called() -> None:
    runner = _FakeTagRunner()
    async with (
        _StaticLLM(["До свидания. ", "[STATUS: END]"]) as test_llm,
        AgentSession(llm=test_llm) as session,
    ):
        await session.start(Assistant(tag_skill_runner=runner, prompt="test prompt"))

        result = await session.run(user_input="bye")
        await _wait_for_runner_call(runner)

    assert _assistant_texts(result) == ["До свидания."]
    parsed = runner.calls[0]["parsed"]
    assert parsed.raw_text == "До свидания. [STATUS: END]"
    assert parsed.clean_text == "До свидания."
    assert parsed.selected.action == "status_end"


@pytest.mark.asyncio
async def test_question_before_tag_is_hidden_and_not_selected() -> None:
    runner = _FakeTagRunner()
    async with (
        _StaticLLM(["Когда вам удобно? ", "[STATUS: END]"]) as test_llm,
        AgentSession(llm=test_llm) as session,
    ):
        await session.start(Assistant(tag_skill_runner=runner, prompt="test prompt"))

        result = await session.run(user_input="call me")
        await _wait_for_runner_call(runner)

    assert _assistant_texts(result) == ["Когда вам удобно?"]
    parsed = runner.calls[0]["parsed"]
    assert parsed.selected is None
    assert parsed.ignored[0].reason == "question_before_tag"


def test_end_call_tool_is_not_registered() -> None:
    assistant = Assistant(prompt="test prompt")

    tool_names = [
        str(getattr(getattr(tool, "info", None), "name", "") or "")
        for tool in assistant.tools
    ]
    assert "end_call" not in tool_names
    assert not hasattr(assistant, "end_call")
