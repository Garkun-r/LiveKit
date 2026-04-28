from __future__ import annotations

import asyncio
import logging
import re
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

    def __init__(self, wrapped: stt.STT, *, delay_sec: float = 0.15) -> None:
        super().__init__(capabilities=wrapped.capabilities)
        self._wrapped = wrapped
        self._delay_sec = max(0.0, delay_sec)
        self._recognize_metrics_needed = False

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
        return EarlyInterimFinalStream(
            stt_obj=self,
            inner_stream=self._wrapped.stream(
                language=language,
                conn_options=conn_options,
            ),
            delay_sec=self._delay_sec,
        )

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
    ) -> None:
        super().__init__(
            stt=stt_obj,
            conn_options=inner_stream._conn_options,
        )
        self._inner_stream = inner_stream
        self._delay_sec = max(0.0, delay_sec)
        self._state_lock = asyncio.Lock()
        self._forward_input_task: asyncio.Task[None] | None = None
        self._pending_eos_task: asyncio.Task[None] | None = None
        self._pending_eos: stt.SpeechEvent | None = None
        self._last_interim: stt.SpeechEvent | None = None
        self._last_synthetic_text = ""
        self._final_seen = False
        self._synthetic_committed = False
        self._speech_ended = False

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
                    self._last_interim = ev
                self._event_ch.send_nowait(ev)
            return

        if ev.type == stt.SpeechEventType.FINAL_TRANSCRIPT:
            async with self._state_lock:
                if self._synthetic_committed:
                    self._log_late_final_locked(ev)
                    return

                self._final_seen = True
                await self._cancel_pending_eos_task_locked()
                self._event_ch.send_nowait(ev)
                self._last_interim = None
                if self._pending_eos is not None:
                    self._emit_pending_eos_locked()
            return

        if ev.type == stt.SpeechEventType.END_OF_SPEECH:
            async with self._state_lock:
                if self._final_seen or self._last_interim is None:
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

    async def _delayed_emit_synthetic_final(self) -> None:
        try:
            await asyncio.sleep(self._delay_sec)
            async with self._state_lock:
                self._emit_synthetic_final_and_pending_eos_locked()
                self._pending_eos_task = None
        except asyncio.CancelledError:
            return

    async def _flush_pending_eos(self) -> None:
        async with self._state_lock:
            self._emit_synthetic_final_and_pending_eos_locked()

    def _emit_synthetic_final_and_pending_eos_locked(self) -> None:
        if self._pending_eos is None:
            return
        if self._last_interim is not None and not self._final_seen:
            text = _event_text(self._last_interim)
            if text:
                synthetic = replace(
                    self._last_interim,
                    type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                )
                self._event_ch.send_nowait(synthetic)
                self._synthetic_committed = True
                self._last_synthetic_text = text
                logger.info(
                    "early interim final created",
                    extra={
                        "delay_sec": self._delay_sec,
                        "request_id": synthetic.request_id,
                        "characters_count": len(text),
                    },
                )
        self._emit_pending_eos_locked()

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

    def _reset_segment_locked(self) -> None:
        self._pending_eos = None
        self._last_interim = None
        self._last_synthetic_text = ""
        self._final_seen = False
        self._synthetic_committed = False
        self._speech_ended = False

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

    wrapped = EarlyInterimFinalSTT(stt_obj, delay_sec=delay_sec)
    logger_.info(
        "early interim final STT wrapper enabled",
        extra={
            "delay_sec": wrapped.delay_sec,
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
