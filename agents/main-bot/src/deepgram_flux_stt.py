from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from typing import Any

import aiohttp
from livekit.agents import (
    DEFAULT_API_CONNECT_OPTIONS,
    APIConnectionError,
    APIConnectOptions,
)
from livekit.agents.utils import is_given
from livekit.plugins import deepgram
from livekit.plugins.deepgram import stt_v2
from livekit.plugins.deepgram.stt_v2 import SpeechStreamv2

logger = logging.getLogger("deepgram_flux_stt")

_DEEPGRAM_INFERENCE_PREFIX = "deepgram/"
_FLUX_MULTILINGUAL_MODEL = "flux-general-multi"


def normalize_deepgram_flux_model(model: str) -> str:
    normalized = (model or "").strip()
    if normalized.startswith(_DEEPGRAM_INFERENCE_PREFIX):
        normalized = normalized[len(_DEEPGRAM_INFERENCE_PREFIX) :]
    return normalized


def is_deepgram_flux_model(model: str) -> bool:
    return normalize_deepgram_flux_model(model).startswith("flux-")


def normalize_language_hints(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        parts = value.replace("\n", ",").split(",")
    elif isinstance(value, Sequence):
        parts = [str(item) for item in value]
    else:
        parts = [str(value)]
    return [part.strip() for part in parts if part and part.strip()]


def build_deepgram_flux_ws_url(
    *,
    base_url: str,
    model: str,
    sample_rate: int,
    language_hints: Sequence[str] = (),
    mip_opt_out: bool = False,
    eager_eot_threshold: float | None = None,
    eot_threshold: float | None = None,
    eot_timeout_ms: int | None = None,
    keyterm: str | Sequence[str] | None = None,
    tags: Sequence[str] = (),
) -> str:
    live_config = _deepgram_flux_live_config(
        model=model,
        sample_rate=sample_rate,
        language_hints=language_hints,
        mip_opt_out=mip_opt_out,
        eager_eot_threshold=eager_eot_threshold,
        eot_threshold=eot_threshold,
        eot_timeout_ms=eot_timeout_ms,
        keyterm=keyterm,
        tags=tags,
    )
    return stt_v2._to_deepgram_url(live_config, base_url=base_url, websocket=True)


class DeepgramFluxSTT(deepgram.STTv2):
    def __init__(
        self,
        *,
        model: str = _FLUX_MULTILINGUAL_MODEL,
        language: str = "en",
        language_hints: Sequence[str] = (),
        **kwargs: Any,
    ) -> None:
        normalized_model = normalize_deepgram_flux_model(model)
        normalized_hints = normalize_language_hints(language_hints)
        if normalized_hints and normalized_model != _FLUX_MULTILINGUAL_MODEL:
            raise ValueError("language_hints are supported only with flux-general-multi")

        super().__init__(model=normalized_model, **kwargs)
        self._opts.language = (language or "en").strip() or "en"
        self._language_hints = normalized_hints

    @property
    def language_hints(self) -> tuple[str, ...]:
        return tuple(self._language_hints)

    def stream(
        self,
        *,
        language=stt_v2.NOT_GIVEN,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> DeepgramFluxSpeechStream:
        if is_given(language):
            self._opts.language = str(language)
        stream = DeepgramFluxSpeechStream(
            stt=self,
            conn_options=conn_options,
            opts=self._opts,
            api_key=self._api_key,
            http_session=self._ensure_session(),
            base_url=self._opts.endpoint_url,
            language_hints=self._language_hints,
        )
        self._streams.add(stream)
        return stream


class DeepgramFluxSpeechStream(SpeechStreamv2):
    def __init__(
        self,
        *,
        language_hints: Sequence[str],
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._language_hints = list(language_hints)

    async def _connect_ws(self) -> aiohttp.ClientWebSocketResponse:
        url = build_deepgram_flux_ws_url(
            base_url=self._opts.endpoint_url,
            model=self._opts.model,
            sample_rate=self._opts.sample_rate,
            language_hints=self._language_hints,
            mip_opt_out=self._opts.mip_opt_out,
            eager_eot_threshold=(
                self._opts.eager_eot_threshold
                if is_given(self._opts.eager_eot_threshold)
                else None
            ),
            eot_threshold=(
                self._opts.eot_threshold if is_given(self._opts.eot_threshold) else None
            ),
            eot_timeout_ms=(
                self._opts.eot_timeout_ms
                if is_given(self._opts.eot_timeout_ms)
                else None
            ),
            keyterm=self._opts.keyterm,
            tags=self._opts.tags if is_given(self._opts.tags) else [],
        )
        try:
            ws = await asyncio.wait_for(
                self._session.ws_connect(
                    url,
                    headers={"Authorization": f"Token {self._api_key}"},
                    heartbeat=30.0,
                ),
                self._conn_options.timeout,
            )
            ws_headers = {
                k: v
                for k, v in ws._response.headers.items()
                if k.startswith("dg-") or k == "Date"
            }
            logger.debug(
                "Established new Deepgram Flux STT WebSocket connection",
                extra={"headers": ws_headers},
            )
        except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as e:
            raise APIConnectionError("failed to connect to deepgram") from e
        return ws


def _deepgram_flux_live_config(
    *,
    model: str,
    sample_rate: int,
    language_hints: Sequence[str],
    mip_opt_out: bool,
    eager_eot_threshold: float | None,
    eot_threshold: float | None,
    eot_timeout_ms: int | None,
    keyterm: str | Sequence[str] | None,
    tags: Sequence[str],
) -> dict[str, Any]:
    live_config: dict[str, Any] = {
        "model": normalize_deepgram_flux_model(model),
        "sample_rate": sample_rate,
        "encoding": "linear16",
        "mip_opt_out": mip_opt_out,
    }
    hints = normalize_language_hints(language_hints)
    if hints:
        live_config["language_hint"] = hints
    if eager_eot_threshold is not None:
        live_config["eager_eot_threshold"] = eager_eot_threshold
    if eot_threshold is not None:
        live_config["eot_threshold"] = eot_threshold
    if eot_timeout_ms is not None:
        live_config["eot_timeout_ms"] = eot_timeout_ms
    if keyterm:
        live_config["keyterm"] = keyterm
    if tags:
        live_config["tag"] = list(tags)
    return live_config
