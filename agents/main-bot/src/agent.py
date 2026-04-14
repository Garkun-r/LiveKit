import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    cli,
    inference,
    room_io,
)
from livekit.agents.llm import ChatMessage
from livekit.plugins import ai_coustics, noise_cancellation, silero, elevenlabs
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from config import AGENT_NAME
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


class Assistant(Agent):
    def __init__(self) -> None:
        prompt = get_active_prompt()
        super().__init__(instructions=prompt)


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
    export_started = False

    session = AgentSession(
        stt=inference.STT(
            model="deepgram/nova-3",
            language="ru",
        ),
        llm=inference.LLM(
            model="google/gemini-3-flash-preview",
            extra_kwargs={
                "temperature": 0.2,
                "max_completion_tokens": 300,
            },
        ),
        tts=elevenlabs.TTS(
            voice_id="wF58OrxELqJ5nFJxXiva",
            model="eleven_multilingual_v2",
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
        try:
            transcript_items.append({
                "type": "user_input_transcribed",
                "transcript": getattr(ev, "transcript", None),
                "is_final": getattr(ev, "is_final", None),
                "language": getattr(ev, "language", None),
                "speaker_id": getattr(ev, "speaker_id", None),
            })
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

    @session.on("close")
    def on_close(ev):
        nonlocal export_started
        if export_started:
            return
        close_info["reason"] = str(getattr(ev, "reason", None))
        err = getattr(ev, "error", None)
        close_info["error"] = str(err) if err else None
        close_event.set()

    await session.start(
        agent=Assistant(),
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
        nonlocal export_started
        if export_started:
            return
        export_started = True

        export_task = asyncio.create_task(export_session_data())
        try:
            await asyncio.wait_for(asyncio.shield(export_task), timeout=timeout_sec)
        except asyncio.TimeoutError:
            logger.warning("n8n export timed out after %ss", timeout_sec)
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
        await export_best_effort(timeout_sec=8.0)
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
        await export_best_effort(timeout_sec=8.0)
        try:
            await asyncio.wait_for(asyncio.shield(session.aclose()), timeout=1.0)
        except BaseException:
            pass


if __name__ == "__main__":
    cli.run_app(server)
