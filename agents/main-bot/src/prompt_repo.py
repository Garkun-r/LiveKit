import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import POSTGRES_DSN, PROMPT_LOOKUP_SQL, PROMPT_LOOKUP_TIMEOUT_SEC
from db import get_pool

logger = logging.getLogger("prompt_repo")
PROMPT_FILE = Path(__file__).with_name("prompt.txt")


@dataclass(frozen=True)
class PromptResolution:
    prompt: str
    source: str
    sip_trunk_number: str | None = None
    sip_client_number: str | None = None
    error: str | None = None


def get_active_prompt() -> str:
    if not PROMPT_FILE.exists():
        raise FileNotFoundError(f"Prompt file not found: {PROMPT_FILE}")

    content = PROMPT_FILE.read_text(encoding="utf-8").strip()
    if not content:
        raise ValueError("Prompt file is empty")

    return content


def _coerce_prompt(row: Any) -> str | None:
    if row is None:
        return None
    if isinstance(row, str):
        return row.strip() or None
    if isinstance(row, dict):
        value = row.get("prompt")
    else:
        try:
            value = row["prompt"]
        except (KeyError, TypeError):
            try:
                value = row[0]
            except (IndexError, TypeError):
                value = None
    if value is None:
        return None
    prompt = str(value).strip()
    return prompt or None


async def fetch_prompt_by_trunk_number(
    sip_trunk_number: str,
    *,
    pool_factory: Callable[[], Awaitable[Any]] = get_pool,
) -> str | None:
    if not POSTGRES_DSN:
        raise RuntimeError("POSTGRES_DSN is not set")
    if not PROMPT_LOOKUP_SQL:
        raise RuntimeError("PROMPT_LOOKUP_SQL is not set")

    pool = await pool_factory()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(PROMPT_LOOKUP_SQL, sip_trunk_number)

    return _coerce_prompt(row)


async def resolve_prompt_for_call(
    *,
    sip_trunk_number: str | None,
    sip_client_number: str | None = None,
    pool_factory: Callable[[], Awaitable[Any]] = get_pool,
) -> PromptResolution:
    normalized_trunk_number = (sip_trunk_number or "").strip() or None
    normalized_client_number = (sip_client_number or "").strip() or None

    if not normalized_trunk_number:
        return PromptResolution(
            prompt=get_active_prompt(),
            source="file:no_sip_trunk_number",
            sip_client_number=normalized_client_number,
        )

    try:
        prompt = await asyncio.wait_for(
            fetch_prompt_by_trunk_number(
                normalized_trunk_number,
                pool_factory=pool_factory,
            ),
            timeout=PROMPT_LOOKUP_TIMEOUT_SEC,
        )
    except Exception as e:
        logger.warning(
            "failed to resolve prompt from postgres; using file prompt: %s",
            e,
            extra={
                "sip_trunk_number": normalized_trunk_number,
                "sip_client_number": normalized_client_number,
            },
        )
        return PromptResolution(
            prompt=get_active_prompt(),
            source="file:lookup_error",
            sip_trunk_number=normalized_trunk_number,
            sip_client_number=normalized_client_number,
            error=str(e),
        )

    if not prompt:
        return PromptResolution(
            prompt=get_active_prompt(),
            source="file:not_found",
            sip_trunk_number=normalized_trunk_number,
            sip_client_number=normalized_client_number,
        )

    return PromptResolution(
        prompt=prompt,
        source="postgres",
        sip_trunk_number=normalized_trunk_number,
        sip_client_number=normalized_client_number,
    )
