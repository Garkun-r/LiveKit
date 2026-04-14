import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    RunContext,
    cli,
    function_tool,
    inference,
    room_io,
)
from livekit.agents.llm import ChatMessage
from livekit.plugins import ai_coustics, noise_cancellation, silero, elevenlabs, google
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from config import (
    AGENT_NAME,
    GEMINI_MAX_OUTPUT_TOKENS,
    GEMINI_MODEL,
    GEMINI_THINKING_LEVEL,
    GEMINI_TOP_P,
    GEMINI_TEMPERATURE,
    GOOGLE_API_KEY,
)
from prompt_repo import get_active_prompt
from session_export import send_session_to_n8n

logger = logging.getLogger("agent")

load_dotenv(".env.local")


def safe_dump(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): safe_dump(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [safe_dump(item) for item in value]
    if hasattr(value, "model_dump"):
        try:
            return safe_dump(value.model_dump())
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        try:
            return {str(key): safe_dump(item) for key, item in vars(value).items()}
        except Exception:
            pass
    return str(value)


def build_google_llm() -> google.LLM:
    if not GOOGLE_API_KEY:
        raise RuntimeError("GOOGLE_API_KEY is not set. Configure it in .env.local")

    # Direct Gemini API configuration (not LiveKit Inference).
    return google.LLM(
        model=GEMINI_MODEL,
        api_key=GOOGLE_API_KEY,
        temperature=GEMINI_TEMPERATURE,
        max_output_tokens=GEMINI_MAX_OUTPUT_TOKENS,
        top_p=GEMINI_TOP_P,
        thinking_config={"thinking_level": GEMINI_THINKING_LEVEL},
    )


class Assistant(Agent):
    def __init__(
        self,
        request_end_call: Callable[[RunContext, str], Awaitable[str]],
    ) -> None:
        self._request_end_call = request_end_call
        prompt = get_active_prompt()
        super().__init__(
            instructions=(
                f"{prompt}\n\n"
                "Дополнительное правило: когда разговор логически завершен и ты уже "
                "сказала финальную прощальную фразу, вызови tool end_call.\n"
                "После вызова end_call не добавляй новых реплик пользователю."
            )
        )

    @function_tool
    async def end_call(self, context: RunContext, reason: str = "conversation_completed") -> str:
        """Use only when the conversation is logically finished and no more questions are expected.

        Rules:
        - Call only after a final goodbye phrase.
        - Never call in the middle of consultation.
        - If the user asks a new question, continue dialogue and do not call this tool.
        - After this tool call, do not produce additional user-facing text.
        """
        return await self._request_end_call(context, reason)


server = AgentServer()


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session(agent_name=AGENT_NAME)
async def my_agent(ctx: JobContext):
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }

    session_started_at = datetime.now(timezone.utc)

    transcript_items = []
    usage_updates = []
    metrics_events = []
    close_info = {"reason": None, "error": None}
    close_event = asyncio.Event()
    user_activity_event = asyncio.Event()
    user_activity_count = 0
    end_call_task: asyncio.Task | None = None
    end_call_grace_sec = 6.0
    export_wait_sec = 20.0
    export_task: asyncio.Task | None = None

    session = AgentSession(
        stt=inference.STT(
            model="deepgram/nova-3",
            language="ru",
        ),
        llm=build_google_llm(),
        tts=elevenlabs.TTS(
            voice_id="wF58OrxELqJ5nFJxXiva",
            model="eleven_flash_v2_5",
        ),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
    )

    @session.on("conversation_item_added")
    def on_conversation_item_added(ev):
        try:
            item = ev.item
            if not isinstance(item, ChatMessage):
                return

            transcript_items.append({
                "type": "conversation_item",
                "role": getattr(item, "role", None),
                "text": getattr(item, "text_content", None),
                "interrupted": getattr(item, "interrupted", None),
                "created_at": getattr(item, "created_at", None),
                "metrics": safe_dump(getattr(item, "metrics", None)),
            })
        except Exception as e:
            logger.exception("conversation_item_added handler failed: %s", e)

    @session.on("user_input_transcribed")
    def on_user_input_transcribed(ev):
        nonlocal user_activity_count, end_call_task
        try:
            transcript_items.append({
                "type": "user_input_transcribed",
                "transcript": getattr(ev, "transcript", None),
                "is_final": getattr(ev, "is_final", None),
                "language": getattr(ev, "language", None),
                "speaker_id": getattr(ev, "speaker_id", None),
            })
            transcript = (getattr(ev, "transcript", None) or "").strip()
            if transcript:
                # Any new user speech cancels a pending auto-hangup timer.
                user_activity_count += 1
                user_activity_event.set()
                if end_call_task and not end_call_task.done():
                    end_call_task.cancel()
                    end_call_task = None
        except Exception as e:
            logger.exception("user_input_transcribed handler failed: %s", e)

    @session.on("session_usage_updated")
    def on_session_usage_updated(ev):
        try:
            usage_updates.append(safe_dump(getattr(ev, "usage", None)))
        except Exception as e:
            logger.exception("session_usage_updated handler failed: %s", e)

    @session.on("metrics_collected")
    def on_metrics_collected(ev):
        try:
            metrics_events.append(safe_dump(getattr(ev, "metrics", None)))
        except Exception as e:
            logger.exception("metrics_collected handler failed: %s", e)

    async def export_session_data():
        ended_at = datetime.now(timezone.utc)

        payload = {
            "agent_name": AGENT_NAME,
            "room_name": ctx.room.name,
            "started_at": session_started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "duration_sec": (ended_at - session_started_at).total_seconds(),
            "close": close_info,
            "transcript_items": transcript_items,
            "usage_updates": usage_updates,
            "metrics_events": metrics_events,
            "summary": {
                "transcript_count": len(transcript_items),
                "usage_update_count": len(usage_updates),
                "metrics_count": len(metrics_events),
            },
        }

        logger.info("sending session data to n8n")
        await send_session_to_n8n(payload)
        logger.info("session data sent to n8n")

    async def delete_room_safely(reason: str) -> None:
        try:
            close_info["reason"] = f"end_call:{reason}"
            logger.info("ending call by deleting room", extra={"room": ctx.room.name})
            await ctx.delete_room(ctx.room.name)
            # In console mode delete_room is a no-op; explicit shutdown ensures
            # the job actually exits and export flow can finish.
            ctx.shutdown(reason=f"end_call:{reason}")
        except Exception as e:
            logger.exception("failed to delete room: %s", e)
            ctx.shutdown(reason=f"end_call_failed:{reason}")

    async def request_end_call(context: RunContext, reason: str) -> str:
        nonlocal end_call_task
        if end_call_task and not end_call_task.done():
            return "END_CALL_ALREADY_SCHEDULED"

        requested_activity = user_activity_count
        end_call_requested_at = asyncio.get_running_loop().time()

        async def end_after_farewell() -> None:
            try:
                # Prevent cutting the final assistant phrase.
                await context.wait_for_playout()
            except Exception as e:
                logger.exception("wait_for_playout failed before end_call: %s", e)
                return

            if user_activity_count != requested_activity:
                logger.info("end_call canceled: user spoke during final playout")
                return

            # Grace timeout is counted from end_call request moment to avoid
            # stacking "playout duration + full grace period".
            elapsed = asyncio.get_running_loop().time() - end_call_requested_at
            remaining_grace = max(0.0, end_call_grace_sec - elapsed)
            try:
                # If the grace window has already passed while the final phrase
                # was playing, end the room immediately.
                if remaining_grace <= 0:
                    await delete_room_safely(reason)
                    return

                user_activity_event.clear()
                # Fallback grace period: if user resumes talking, keep the call open.
                await asyncio.wait_for(user_activity_event.wait(), timeout=remaining_grace)
                logger.info("end_call canceled: user resumed speech")
                return
            except asyncio.TimeoutError:
                await delete_room_safely(reason)
            except asyncio.CancelledError:
                logger.info("end_call timer canceled")
            except Exception as e:
                logger.exception("end_call timer failed: %s", e)

        end_call_task = asyncio.create_task(end_after_farewell())
        return "END_CALL_SCHEDULED"

    @session.on("close")
    def on_close(ev):
        if close_event.is_set():
            return
        close_info["reason"] = str(getattr(ev, "reason", None))
        err = getattr(ev, "error", None)
        close_info["error"] = str(err) if err else None
        close_event.set()

    await session.start(
        agent=Assistant(request_end_call=request_end_call),
        room=ctx.room,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=lambda params: (
                    noise_cancellation.BVCTelephony()
                    if params.participant.kind
                    == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                    else ai_coustics.audio_enhancement(
                        model=ai_coustics.EnhancerModel.QUAIL_VF_L
                    )
                ),
            ),
        ),
    )

    async def export_best_effort(timeout_sec: float) -> None:
        nonlocal export_task
        if export_task is None:
            export_task = asyncio.create_task(export_session_data())
        try:
            await asyncio.wait_for(asyncio.shield(export_task), timeout=timeout_sec)
        except asyncio.TimeoutError:
            logger.warning("n8n export timed out after %ss", timeout_sec)
        except asyncio.CancelledError:
            # Preserve cancellation semantics for outer handler, but do not lose
            # the in-flight export task. It will be awaited again in cancel path.
            raise
        except BaseException as e:
            logger.exception("n8n export failed: %s", e)

    try:
        await ctx.connect()
        await session.generate_reply(
            instructions=(
                "Сразу после подключения поприветствуй клиента одной фразой: "
                "Здравствуйте! Это компания Кофемастер! Чем могу помочь?"
            )
        )
        await close_event.wait()
        await export_best_effort(timeout_sec=export_wait_sec)
    except asyncio.CancelledError:
        # Python 3.13: CancelledError is a BaseException, and LiveKit will cancel the entrypoint
        # during shutdown. Best-effort export should still complete quickly.
        asyncio.current_task().uncancel()
        logger.warning("entrypoint cancelled; exporting session data to n8n before exit")
        try:
            await asyncio.wait_for(close_event.wait(), timeout=0.8)
        except BaseException:
            pass
        if close_info["reason"] is None:
            close_info["reason"] = "entrypoint_cancelled"
        await export_best_effort(timeout_sec=export_wait_sec)
        try:
            await asyncio.wait_for(asyncio.shield(session.aclose()), timeout=1.0)
        except BaseException:
            pass
    finally:
        if end_call_task and not end_call_task.done():
            end_call_task.cancel()
        if export_task and not export_task.done():
            try:
                await asyncio.wait_for(asyncio.shield(export_task), timeout=export_wait_sec)
            except asyncio.TimeoutError:
                logger.warning("n8n export timed out after %ss in finalizer", export_wait_sec)
            except BaseException as e:
                logger.exception("n8n export finalizer failed: %s", e)


if __name__ == "__main__":
    cli.run_app(server)
