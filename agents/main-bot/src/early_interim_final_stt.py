from __future__ import annotations

import asyncio
import logging
import re
import weakref
from contextlib import suppress
from dataclasses import replace
from difflib import SequenceMatcher
from typing import Any

from livekit.agents import (
    DEFAULT_API_CONNECT_OPTIONS,
    APIConnectOptions,
    stt,
)
from livekit.agents.types import NOT_GIVEN, NotGivenOr
from livekit.agents.utils import AudioBuffer

logger = logging.getLogger("early_interim_final_stt")

_WHITESPACE_RE = re.compile(r"\s+")


class EarlyInterimFinalSTT(stt.STT):
    """Provider-agnostic STT wrapper that finalizes a held interim after EOS."""

    def __init__(
        self,
        wrapped: stt.STT,
        *,
        delay_sec: float = 0.15,
        min_stable_interims: int = 1,
    ) -> None:
        super().__init__(capabilities=wrapped.capabilities)
        self._wrapped = wrapped
        self._delay_sec = max(0.0, delay_sec)
        self._min_stable_interims = max(1, min_stable_interims)
        self._recognize_metrics_needed = False
        self._streams: weakref.WeakSet[EarlyInterimFinalStream] = weakref.WeakSet()

        wrapped.on("metrics_collected", self._on_metrics_collected)
        wrapped.on("error", self._on_error)

    @property
    def model(self) -> str:
        return self._wrapped.model

    @property
    def provider(self) -> str:
        return self._wrapped.provider

    @property
    def delay_sec(self) -> float:
        return self._delay_sec

    @property
    def min_stable_interims(self) -> int:
        return self._min_stable_interims

    @property
    def wrapped(self) -> stt.STT:
        return self._wrapped

    async def _recognize_impl(
        self,
        buffer: AudioBuffer,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions,
    ) -> stt.SpeechEvent:
        return await self._wrapped.recognize(
            buffer,
            language=language,
            conn_options=conn_options,
        )

    def stream(
        self,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> EarlyInterimFinalStream:
        stream = EarlyInterimFinalStream(
            stt_obj=self,
            inner_stream=self._wrapped.stream(
                language=language,
                conn_options=conn_options,
            ),
            delay_sec=self._delay_sec,
            min_stable_interims=self._min_stable_interims,
        )
        self._streams.add(stream)
        return stream

    def notify_local_end_of_speech(self, *, ended_at: float | None = None) -> None:
        """Notify active STT streams that local VAD has detected speech end."""

        for stream in list(self._streams):
            stream.notify_local_end_of_speech(ended_at=ended_at)

    async def aclose(self) -> None:
        await self._wrapped.aclose()

    def prewarm(self) -> None:
        self._wrapped.prewarm()

    def _on_metrics_collected(self, metrics: Any) -> None:
        self.emit("metrics_collected", metrics)

    def _on_error(self, error: Any) -> None:
        self.emit("error", error)


class EarlyInterimFinalStream(stt.SpeechStream):
    def __init__(
        self,
        *,
        stt_obj: EarlyInterimFinalSTT,
        inner_stream: stt.SpeechStream,
        delay_sec: float,
        min_stable_interims: int,
    ) -> None:
        super().__init__(
            stt=stt_obj,
            conn_options=inner_stream._conn_options,
        )
        self._inner_stream = inner_stream
        self._delay_sec = max(0.0, delay_sec)
        self._min_stable_interims = max(1, min_stable_interims)
        self._state_lock = asyncio.Lock()
        self._forward_input_task: asyncio.Task[None] | None = None
        self._pending_eos_task: asyncio.Task[None] | None = None
        self._local_eos_task: asyncio.Task[None] | None = None
        self._notify_tasks: set[asyncio.Task[None]] = set()
        self._pending_eos: stt.SpeechEvent | None = None
        self._last_interim: stt.SpeechEvent | None = None
        self._last_interim_normalized_text = ""
        self._last_interim_stable_count = 0
        self._last_synthetic_text = ""
        self._final_seen = False
        self._synthetic_committed = False
        self._speech_ended = False
        self._local_eos_deadline: float | None = None
        self._local_eos_due = False

    async def _run(self) -> None:
        self._forward_input_task = asyncio.create_task(
            self._forward_input(),
            name="EarlyInterimFinalStream._forward_input",
        )
        try:
            async with self._inner_stream:
                async for ev in self._inner_stream:
                    await self._handle_event(ev)
        finally:
            await self._flush_pending_eos()
            await self._cancel_pending_eos_task()
            await self._cancel_local_eos_task()
            await _cancel_tasks(self._notify_tasks)
            if self._forward_input_task is not None:
                self._forward_input_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self._forward_input_task
                self._forward_input_task = None

    async def _forward_input(self) -> None:
        try:
            async for data in self._input_ch:
                try:
                    if isinstance(data, stt.RecognizeStream._FlushSentinel):
                        self._inner_stream.flush()
                    else:
                        self._inner_stream.push_frame(data)
                except RuntimeError:
                    return
        finally:
            with suppress(RuntimeError):
                self._inner_stream.end_input()

    async def _handle_event(self, ev: stt.SpeechEvent) -> None:
        if ev.type == stt.SpeechEventType.START_OF_SPEECH:
            async with self._state_lock:
                await self._cancel_pending_eos_task_locked()
                await self._cancel_local_eos_task_locked()
                self._reset_segment_locked()
                self._event_ch.send_nowait(ev)
            return

        if ev.type == stt.SpeechEventType.INTERIM_TRANSCRIPT:
            async with self._state_lock:
                if self._pending_eos is not None:
                    await self._cancel_pending_eos_task_locked()
                    self._pending_eos = None
                if self._speech_ended:
                    self._reset_segment_locked()
                if _event_text(ev):
                    self._remember_interim_locked(ev)
                self._event_ch.send_nowait(ev)
                self._emit_due_local_synthetic_final_locked()
            return

        if ev.type == stt.SpeechEventType.FINAL_TRANSCRIPT:
            async with self._state_lock:
                if self._synthetic_committed:
                    self._log_late_final_locked(ev)
                    return

                self._final_seen = True
                await self._cancel_pending_eos_task_locked()
                await self._cancel_local_eos_task_locked()
                self._clear_local_eos_locked()
                self._event_ch.send_nowait(ev)
                self._last_interim = None
                if self._pending_eos is not None:
                    self._emit_pending_eos_locked()
            return

        if ev.type == stt.SpeechEventType.END_OF_SPEECH:
            async with self._state_lock:
                if (
                    self._final_seen
                    or self._synthetic_committed
                    or self._last_interim is None
                ):
                    self._event_ch.send_nowait(ev)
                    self._speech_ended = True
                    return

                self._pending_eos = ev
                await self._cancel_pending_eos_task_locked()
                self._pending_eos_task = asyncio.create_task(
                    self._delayed_emit_synthetic_final(),
                    name="EarlyInterimFinalStream._delayed_emit_synthetic_final",
                )
            return

        self._event_ch.send_nowait(ev)

    def notify_local_end_of_speech(self, *, ended_at: float | None = None) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning(
                "cannot notify local VAD end of speech without a running event loop"
            )
            return

        task = loop.create_task(
            self._notify_local_end_of_speech(ended_at=ended_at),
            name="EarlyInterimFinalStream._notify_local_end_of_speech",
        )
        self._notify_tasks.add(task)
        task.add_done_callback(self._notify_tasks.discard)

    async def _notify_local_end_of_speech(
        self, *, ended_at: float | None = None
    ) -> None:
        async with self._state_lock:
            if self._final_seen or self._synthetic_committed:
                return

            await self._cancel_local_eos_task_locked()
            self._local_eos_due = False
            self._local_eos_deadline = (
                asyncio.get_running_loop().time() + self._delay_sec
            )
            self._local_eos_task = asyncio.create_task(
                self._delayed_emit_local_synthetic_final(ended_at=ended_at),
                name="EarlyInterimFinalStream._delayed_emit_local_synthetic_final",
            )
            logger.debug(
                "local VAD end of speech received for early interim final",
                extra={
                    "delay_sec": self._delay_sec,
                    "min_stable_interims": self._min_stable_interims,
                    "ended_at": ended_at,
                    "has_interim": self._last_interim is not None,
                    "interim_stable_count": self._last_interim_stable_count,
                },
            )

    async def _delayed_emit_synthetic_final(self) -> None:
        try:
            await asyncio.sleep(self._delay_sec)
            async with self._state_lock:
                self._emit_synthetic_final_and_pending_eos_locked()
                self._pending_eos_task = None
        except asyncio.CancelledError:
            return

    async def _delayed_emit_local_synthetic_final(
        self, *, ended_at: float | None = None
    ) -> None:
        try:
            await asyncio.sleep(self._delay_sec)
            async with self._state_lock:
                self._local_eos_task = None
                self._local_eos_due = True
                emitted = self._emit_synthetic_final_locked(source="local_vad")
                if not emitted:
                    logger.debug(
                        "local VAD early interim final waiting for next interim",
                        extra={
                            "delay_sec": self._delay_sec,
                            "min_stable_interims": self._min_stable_interims,
                            "ended_at": ended_at,
                            "has_interim": self._last_interim is not None,
                            "interim_stable_count": self._last_interim_stable_count,
                            "final_seen": self._final_seen,
                        },
                    )
        except asyncio.CancelledError:
            return

    async def _flush_pending_eos(self) -> None:
        async with self._state_lock:
            self._emit_synthetic_final_and_pending_eos_locked()

    def _emit_synthetic_final_and_pending_eos_locked(self) -> None:
        if self._pending_eos is None:
            return
        self._emit_synthetic_final_locked(source="stt_eos")
        self._emit_pending_eos_locked()

    def _emit_due_local_synthetic_final_locked(self) -> bool:
        if self._local_eos_deadline is None:
            return False
        if asyncio.get_running_loop().time() >= self._local_eos_deadline:
            self._local_eos_due = True
        if not self._local_eos_due:
            return False
        return self._emit_synthetic_final_locked(source="local_vad")

    def _emit_synthetic_final_locked(self, *, source: str) -> bool:
        if self._last_interim is None or self._final_seen or self._synthetic_committed:
            return False

        text = _event_text(self._last_interim)
        if not text:
            return False
        if self._last_interim_stable_count < self._min_stable_interims:
            logger.debug(
                "early interim final skipped: interim is not stable enough",
                extra={
                    "delay_sec": self._delay_sec,
                    "source": source,
                    "request_id": self._last_interim.request_id,
                    "characters_count": len(text),
                    "interim_stable_count": self._last_interim_stable_count,
                    "min_stable_interims": self._min_stable_interims,
                },
            )
            return False

        synthetic = replace(
            self._last_interim,
            type=stt.SpeechEventType.FINAL_TRANSCRIPT,
        )
        self._event_ch.send_nowait(synthetic)
        self._synthetic_committed = True
        self._final_seen = True
        self._last_synthetic_text = text
        self._clear_local_eos_locked()
        logger.info(
            "early interim final created",
            extra={
                "delay_sec": self._delay_sec,
                "source": source,
                "request_id": synthetic.request_id,
                "characters_count": len(text),
                "interim_stable_count": self._last_interim_stable_count,
                "min_stable_interims": self._min_stable_interims,
            },
        )
        return True

    def _emit_pending_eos_locked(self) -> None:
        if self._pending_eos is None:
            return
        self._event_ch.send_nowait(self._pending_eos)
        self._pending_eos = None
        self._speech_ended = True

    async def _cancel_pending_eos_task(self) -> None:
        async with self._state_lock:
            await self._cancel_pending_eos_task_locked()

    async def _cancel_pending_eos_task_locked(self) -> None:
        task = self._pending_eos_task
        if task is None:
            return
        self._pending_eos_task = None
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def _cancel_local_eos_task(self) -> None:
        async with self._state_lock:
            await self._cancel_local_eos_task_locked()

    async def _cancel_local_eos_task_locked(self) -> None:
        task = self._local_eos_task
        if task is None:
            return
        self._local_eos_task = None
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    def _clear_local_eos_locked(self) -> None:
        self._local_eos_deadline = None
        self._local_eos_due = False

    def _remember_interim_locked(self, ev: stt.SpeechEvent) -> None:
        text = _event_text(ev)
        normalized_text = _normalize_text(text)
        if _texts_equivalent(self._last_interim_normalized_text, normalized_text):
            self._last_interim_stable_count += 1
        else:
            self._last_interim_stable_count = 1
        self._last_interim = ev
        self._last_interim_normalized_text = normalized_text

    def _reset_segment_locked(self) -> None:
        self._pending_eos = None
        self._last_interim = None
        self._last_interim_normalized_text = ""
        self._last_interim_stable_count = 0
        self._last_synthetic_text = ""
        self._final_seen = False
        self._synthetic_committed = False
        self._speech_ended = False
        self._clear_local_eos_locked()

    def _log_late_final_locked(self, ev: stt.SpeechEvent) -> None:
        text = _event_text(ev)
        if _texts_equivalent(self._last_synthetic_text, text):
            logger.info(
                "late final transcript suppressed after early interim final",
                extra={
                    "request_id": ev.request_id,
                    "characters_count": len(text),
                },
            )
            return
        logger.warning(
            "late final transcript differs after early interim final; suppressing to avoid duplicate user turn",
            extra={
                "request_id": ev.request_id,
                "synthetic_text": self._last_synthetic_text,
                "late_final_text": text,
            },
        )

    async def aclose(self) -> None:
        self._input_ch.close()
        await self._cancel_pending_eos_task()
        await self._inner_stream.aclose()
        await super().aclose()


def should_wrap_stt(
    stt_obj: stt.STT,
    *,
    enabled: bool,
    turn_detection_mode: str,
    logger_: logging.Logger = logger,
) -> bool:
    if not enabled:
        return False
    if turn_detection_mode != "vad":
        logger_.warning(
            "early interim final STT wrapper disabled: TURN_DETECTION_MODE is not vad",
            extra={"turn_detection_mode": turn_detection_mode},
        )
        return False

    capabilities = stt_obj.capabilities
    if not capabilities.streaming or not capabilities.interim_results:
        logger_.warning(
            "early interim final STT wrapper disabled: STT lacks streaming interim support",
            extra={
                "streaming": capabilities.streaming,
                "interim_results": capabilities.interim_results,
            },
        )
        return False
    return True


def wrap_stt_if_enabled(
    stt_obj: stt.STT,
    *,
    enabled: bool,
    delay_sec: float,
    min_stable_interims: int = 1,
    turn_detection_mode: str,
    logger_: logging.Logger = logger,
) -> stt.STT:
    if not should_wrap_stt(
        stt_obj,
        enabled=enabled,
        turn_detection_mode=turn_detection_mode,
        logger_=logger_,
    ):
        return stt_obj

    wrapped = EarlyInterimFinalSTT(
        stt_obj,
        delay_sec=delay_sec,
        min_stable_interims=min_stable_interims,
    )
    logger_.info(
        "early interim final STT wrapper enabled",
        extra={
            "delay_sec": wrapped.delay_sec,
            "min_stable_interims": wrapped.min_stable_interims,
            "provider": stt_obj.provider,
            "model": stt_obj.model,
        },
    )
    return wrapped


def _event_text(ev: stt.SpeechEvent) -> str:
    if not ev.alternatives:
        return ""
    return (ev.alternatives[0].text or "").strip()


def _normalize_text(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text.strip().lower())


def _texts_equivalent(left: str, right: str) -> bool:
    normalized_left = _normalize_text(left)
    normalized_right = _normalize_text(right)
    if not normalized_left or not normalized_right:
        return normalized_left == normalized_right
    if normalized_left == normalized_right:
        return True
    return SequenceMatcher(None, normalized_left, normalized_right).ratio() >= 0.92


async def _cancel_tasks(tasks: set[asyncio.Task[None]]) -> None:
    if not tasks:
        return
    pending = list(tasks)
    tasks.clear()
    for task in pending:
        task.cancel()
    for task in pending:
        with suppress(asyncio.CancelledError):
            await task
