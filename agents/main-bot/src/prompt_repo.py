# ruff: noqa: RUF001
import hashlib
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from config import (
    DIRECTUS_COLLECTION_BOT_CONFIGURATIONS,
    DIRECTUS_COLLECTION_CALLER_ID,
    DIRECTUS_COLLECTION_CLIENT_PROMPT_CACHE,
    DIRECTUS_COLLECTION_CLIENTS,
    DIRECTUS_COLLECTION_CLIENTS_PROMPT,
    DIRECTUS_COLLECTION_TRANSFER_NUMBER,
    DIRECTUS_COLLECTION_WEBPARSING,
    DIRECTUS_DEFAULT_TIMEZONE,
    DIRECTUS_PROMPT_CACHE_TTL_SEC,
    DIRECTUS_REQUEST_TIMEOUT_SEC,
    DIRECTUS_TOKEN,
    DIRECTUS_URL,
)

logger = logging.getLogger("prompt_repo")
PROMPT_FILE = Path(__file__).with_name("prompt.txt")

_CURRENT_DATETIME_PLACEHOLDER = "{{CURRENT_DATETIME_BLOCK}}"
_URL_PROTOCOL_RE = re.compile(r"^https?://", re.IGNORECASE)
_MONTH_NAMES = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
_WEEKDAY_NAMES = (
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
)


@dataclass(frozen=True)
class PromptResolution:
    prompt: str
    source: str
    sip_trunk_number: str | None = None
    sip_client_number: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class _PromptTemplate:
    template: str
    timezone: str
    source: str
    client_id: str | int | None = None


@dataclass
class _PromptCacheEntry:
    template: _PromptTemplate
    expires_at: float


class DirectusPromptClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout_sec: float,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout_sec = timeout_sec
        self._http_client = http_client
        self._owns_client = http_client is None

    async def __aenter__(self) -> "DirectusPromptClient":
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                base_url=self._base_url,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=self._timeout_sec,
            )
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._owns_client and self._http_client is not None:
            await self._http_client.aclose()

    async def fetch_cached_prompt(self, caller_id: str) -> _PromptTemplate | None:
        try:
            row = await self._fetch_one(
                DIRECTUS_COLLECTION_CLIENT_PROMPT_CACHE,
                filters={
                    "caller_id": caller_id,
                    "active": True,
                },
                fields=[
                    "id",
                    "caller_id",
                    "client_id",
                    "prompt_template",
                    "timezone",
                    "active",
                ],
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code not in {403, 404}:
                raise
            logger.info("Directus prompt cache is unavailable; building live prompt")
            return None
        if not row:
            return None

        template = _string_value(row.get("prompt_template"))
        if not template:
            return None

        return _PromptTemplate(
            template=template,
            timezone=_string_value(row.get("timezone")) or DIRECTUS_DEFAULT_TIMEZONE,
            source="directus:cache",
            client_id=_relation_id(row.get("client_id")),
        )

    async def save_cached_prompt(
        self,
        *,
        caller_id: str,
        prompt_template: _PromptTemplate,
    ) -> None:
        if self._http_client is None:
            raise RuntimeError("Directus client is not open")

        payload = {
            "caller_id": caller_id,
            "client_id": prompt_template.client_id,
            "prompt_template": prompt_template.template,
            "timezone": prompt_template.timezone,
            "source_hash": _template_hash(prompt_template.template),
            "active": True,
            "last_error": None,
            "date_updated": datetime.now(timezone.utc).isoformat(),
        }

        existing = await self._fetch_one(
            DIRECTUS_COLLECTION_CLIENT_PROMPT_CACHE,
            filters={"caller_id": caller_id},
            fields=["id", "caller_id"],
        )
        if existing:
            row_id = existing.get("id")
            if row_id in (None, ""):
                raise RuntimeError("Directus prompt cache row has no id")
            response = await self._http_client.patch(
                f"/items/{quote(DIRECTUS_COLLECTION_CLIENT_PROMPT_CACHE, safe='')}/"
                f"{quote(str(row_id), safe='')}",
                json=payload,
            )
        else:
            response = await self._http_client.post(
                f"/items/{quote(DIRECTUS_COLLECTION_CLIENT_PROMPT_CACHE, safe='')}",
                json=payload,
            )
        response.raise_for_status()

    async def build_live_prompt(self, caller_id: str) -> _PromptTemplate | None:
        caller_row = await self._fetch_one(
            DIRECTUS_COLLECTION_CALLER_ID,
            filters={"CallerID": caller_id},
            fields=["CallerID", "client_id"],
        )
        if not caller_row:
            return None

        client_id = _relation_id(caller_row.get("client_id"))
        if client_id is None:
            raise RuntimeError("Directus CallerID row has no client_id")

        bot_config = await self._fetch_one(
            DIRECTUS_COLLECTION_BOT_CONFIGURATIONS,
            filters={"client_id": client_id},
            fields=["client_id", "system_prompt", "examples", "skills_name"],
        )
        if not bot_config:
            raise RuntimeError("Directus bot configuration not found")

        client = await self._fetch_client(client_id)
        if not client:
            raise RuntimeError("Directus client row not found")

        skills_name = _string_value(bot_config.get("skills_name"))
        global_rules = await self._fetch_prompt_block("global_rules")
        skill_prompt = await self._fetch_prompt_block(skills_name)
        if not global_rules:
            raise RuntimeError("Directus global_rules prompt block not found")
        if not skill_prompt:
            raise RuntimeError("Directus skills prompt block not found")

        website = _string_value(client.get("company_website"))
        website_text = await self._fetch_website_text(website)
        transfer_rows = await self._fetch_many(
            DIRECTUS_COLLECTION_TRANSFER_NUMBER,
            filters={"client_id": client_id},
            fields=["disc", "direction"],
            limit=500,
        )

        template = build_prompt_template(
            global_rules=global_rules,
            skill_prompt=skill_prompt,
            add_info=_string_value(client.get("add_info")),
            website_text=website_text,
            company_extra=_string_value(client.get("company_extra")),
            transfer_rows=transfer_rows,
            system_prompt=_string_value(bot_config.get("system_prompt")),
            examples=_string_value(bot_config.get("examples")),
        )

        return _PromptTemplate(
            template=template,
            timezone=DIRECTUS_DEFAULT_TIMEZONE,
            source="directus:live",
            client_id=client_id,
        )

    async def _fetch_client(self, client_id: str | int) -> dict[str, Any] | None:
        client = await self._fetch_one(
            DIRECTUS_COLLECTION_CLIENTS,
            filters={"id": client_id},
            fields=["id", "add_info", "company_website"],
        )
        if not client:
            return None

        try:
            extra_client = await self._fetch_one(
                DIRECTUS_COLLECTION_CLIENTS,
                filters={"id": client_id},
                fields=["id", "company_extra"],
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code not in {400, 403}:
                raise
            logger.info("Directus clients.company_extra is unavailable; retrying")
            return client

        if extra_client:
            client["company_extra"] = extra_client.get("company_extra")
        return client

    async def _fetch_prompt_block(self, name: str | None) -> str:
        if not name:
            return ""
        row = await self._fetch_one(
            DIRECTUS_COLLECTION_CLIENTS_PROMPT,
            filters={"name": name},
            fields=["name", "text"],
        )
        if not row:
            return ""
        return _string_value(row.get("text"))

    async def _fetch_website_text(self, company_website: str) -> str:
        if not company_website:
            return ""

        candidates = []
        stripped = company_website.strip()
        without_protocol = _URL_PROTOCOL_RE.sub("", stripped).strip("/")
        for candidate in (without_protocol, stripped):
            if candidate and candidate not in candidates:
                candidates.append(candidate)

        for candidate in candidates:
            row = await self._fetch_one(
                DIRECTUS_COLLECTION_WEBPARSING,
                filters={"url": candidate},
                fields=["url", "text"],
            )
            if row:
                return _string_value(row.get("text"))

        return ""

    async def _fetch_one(
        self,
        collection: str,
        *,
        filters: dict[str, Any],
        fields: list[str],
    ) -> dict[str, Any] | None:
        rows = await self._fetch_many(
            collection,
            filters=filters,
            fields=fields,
            limit=1,
        )
        return rows[0] if rows else None

    async def _fetch_many(
        self,
        collection: str,
        *,
        filters: dict[str, Any],
        fields: list[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        if self._http_client is None:
            raise RuntimeError("Directus client is not open")

        params: dict[str, Any] = {
            "limit": str(limit),
            "fields": ",".join(fields),
        }
        for field, value in filters.items():
            params[f"filter[{field}][_eq]"] = _directus_filter_value(value)

        response = await self._http_client.get(
            f"/items/{quote(collection, safe='')}",
            params=params,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data")
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
        if isinstance(data, dict):
            return [data]
        return []


_prompt_cache: dict[str, _PromptCacheEntry] = {}


def get_active_prompt() -> str:
    if not PROMPT_FILE.exists():
        raise FileNotFoundError(f"Prompt file not found: {PROMPT_FILE}")

    content = PROMPT_FILE.read_text(encoding="utf-8").strip()
    if not content:
        raise ValueError("Prompt file is empty")

    return content


def build_prompt_template(
    *,
    global_rules: str,
    skill_prompt: str,
    add_info: str,
    website_text: str,
    company_extra: str,
    transfer_rows: list[dict[str, Any]],
    system_prompt: str,
    examples: str,
) -> str:
    transfer_directory_block = _build_transfer_directory_block(transfer_rows)
    sections = [
        (
            "Ты — голосовой ИИ-робот компании. Клиент уже услышал приветствие "
            "в начале звонка. Не повторяй приветствие, сразу отвечай по сути "
            "вопроса. Твоя задача — вести диалог, используя данные и инструкции "
            "из блоков ниже."
        ),
        f"<global_rules>\n{global_rules.strip()}\n</global_rules>",
        f"<scenarios and skills>\n{skill_prompt.strip()}\n</scenarios and skills>",
        (
            "<knowledge_base>\n"
            "(База знаний: цены, услуги, условия. Ищи ответы ТОЛЬКО тут)\n\n"
            "База знаний клиента (приоритет знаний):\n"
            f"{add_info.strip()}\n\n"
            "База знаний сайта:\n"
            f"{website_text.strip()}\n\n"
            "Карточка компании из интернета (если знаний недостаточно):\n"
            f"{company_extra.strip()}\n"
            "</knowledge_base>"
        ),
    ]
    if transfer_directory_block:
        sections.append(transfer_directory_block)
    sections.extend(
        [
            _CURRENT_DATETIME_PLACEHOLDER,
            (
                "<specific_instructions>\n"
                "(ПЕРСОНАЛЬНАЯ СТРАТЕГИЯ КОМПАНИИ: Цели звонка, "
                "Логика Лид/Перевод, Презентация)\n"
                f"{system_prompt.strip()}\n"
                "</specific_instructions>"
            ),
            (
                "<dialogue_examples>\n"
                "(Примеры правильного формата диалогов с тегами)\n"
                f"{examples.strip()}\n"
                "</dialogue_examples>"
            ),
            (
                "ВАЖНОЕ НАПОМИНАНИЕ:\n"
                "1. Не используй ВНЕШНИЕ инструменты поиска (интернет, веб, API).\n"
                "   Тег [GEO_SEARCH: ...] — это НЕ внешний поиск, а обязательный "
                "служебный тег.\n"
                "   Его НУЖНО использовать по правилам SKILL C.\n"
                "2. Твоя главная цель — по каждой реплике правильно "
                "классифицировать тип и поставить нужный ТЕГ.\n"
                "3. Всегда следуй логике из <specific_instructions>."
            ),
        ]
    )
    return "\n\n".join(sections)


async def resolve_prompt_for_call(
    *,
    sip_trunk_number: str | None,
    sip_client_number: str | None = None,
    directus_client_factory: Callable[[], Any] | None = None,
    now_factory: Callable[[ZoneInfo], datetime] | None = None,
    pool_factory: Any | None = None,
) -> PromptResolution:
    del pool_factory
    normalized_trunk_number = (sip_trunk_number or "").strip() or None
    normalized_client_number = (sip_client_number or "").strip() or None

    if not normalized_trunk_number:
        return PromptResolution(
            prompt=get_active_prompt(),
            source="file:no_sip_trunk_number",
            sip_client_number=normalized_client_number,
        )

    if not DIRECTUS_URL or not DIRECTUS_TOKEN:
        return PromptResolution(
            prompt=get_active_prompt(),
            source="file:no_directus_config",
            sip_trunk_number=normalized_trunk_number,
            sip_client_number=normalized_client_number,
        )

    try:
        prompt_template = await _resolve_prompt_template(
            normalized_trunk_number,
            directus_client_factory=directus_client_factory,
        )
    except Exception as e:
        logger.warning(
            "failed to resolve prompt from Directus; using file prompt: %s",
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

    if prompt_template is None:
        return PromptResolution(
            prompt=get_active_prompt(),
            source="file:not_found",
            sip_trunk_number=normalized_trunk_number,
            sip_client_number=normalized_client_number,
        )

    return PromptResolution(
        prompt=render_prompt_template(
            prompt_template.template,
            timezone_name=prompt_template.timezone,
            now_factory=now_factory,
        ),
        source=prompt_template.source,
        sip_trunk_number=normalized_trunk_number,
        sip_client_number=normalized_client_number,
    )


async def _resolve_prompt_template(
    caller_id: str,
    *,
    directus_client_factory: Callable[[], Any] | None,
) -> _PromptTemplate | None:
    cached = _get_memory_cached_prompt(caller_id)
    if cached is not None:
        return cached

    factory = directus_client_factory or build_directus_client
    async with factory() as client:
        prompt_template = await client.fetch_cached_prompt(caller_id)
        if prompt_template is None:
            prompt_template = await client.build_live_prompt(caller_id)
            if prompt_template is not None:
                await _save_prompt_template_best_effort(
                    client=client,
                    caller_id=caller_id,
                    prompt_template=prompt_template,
                )

    if prompt_template is not None:
        _set_memory_cached_prompt(caller_id, prompt_template)
    return prompt_template


async def _save_prompt_template_best_effort(
    *,
    client: Any,
    caller_id: str,
    prompt_template: _PromptTemplate,
) -> None:
    try:
        await client.save_cached_prompt(
            caller_id=caller_id,
            prompt_template=prompt_template,
        )
    except Exception as e:
        logger.warning(
            "failed to save Directus prompt cache; continuing with live prompt: %s",
            e,
            extra={"sip_trunk_number": caller_id},
        )


def build_directus_client() -> DirectusPromptClient:
    return DirectusPromptClient(
        base_url=DIRECTUS_URL,
        token=DIRECTUS_TOKEN,
        timeout_sec=DIRECTUS_REQUEST_TIMEOUT_SEC,
    )


def render_prompt_template(
    template: str,
    *,
    timezone_name: str,
    now_factory: Callable[[ZoneInfo], datetime] | None = None,
) -> str:
    datetime_block = build_current_datetime_block(
        timezone_name=timezone_name,
        now_factory=now_factory,
    )
    if _CURRENT_DATETIME_PLACEHOLDER in template:
        return template.replace(_CURRENT_DATETIME_PLACEHOLDER, datetime_block)
    return template


def build_current_datetime_block(
    *,
    timezone_name: str,
    now_factory: Callable[[ZoneInfo], datetime] | None = None,
) -> str:
    timezone = _resolve_timezone(timezone_name)
    now = now_factory(timezone) if now_factory else datetime.now(timezone)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone)
    else:
        now = now.astimezone(timezone)

    current_date_text = f"{now.day} {_MONTH_NAMES[now.month - 1]} {now.year} г."
    current_weekday_text = _WEEKDAY_NAMES[now.weekday()]
    current_time_text = f"{now.hour:02d}:00"

    return (
        "<current_datetime>\n"
        "Сейчас локальная дата и время компании:\n"
        f"- Дата: {current_date_text}\n"
        f"- День недели: {current_weekday_text}\n"
        f"- Время: {current_time_text}\n"
        f"- Часовой пояс: {timezone.key}\n\n"
        "Этот блок является источником истины для слов:\n"
        "«сегодня», «завтра», «вчера», «сейчас», «в этот день», "
        "«на текущий момент».\n\n"
        "Если клиент спрашивает:\n"
        "- какой сегодня день недели,\n"
        "- какая сегодня дата,\n"
        "- до скольки сегодня работаете,\n"
        "- вы сегодня открыты,\n"
        "- вы сейчас работаете,\n\n"
        "сначала определи текущий день по этому блоку, затем используй график "
        "работы из <knowledge_base>.\n"
        "</current_datetime>"
    )


def clear_prompt_cache() -> None:
    _prompt_cache.clear()


def _get_memory_cached_prompt(caller_id: str) -> _PromptTemplate | None:
    entry = _prompt_cache.get(caller_id)
    if entry is None:
        return None
    if entry.expires_at <= time.monotonic():
        _prompt_cache.pop(caller_id, None)
        return None
    return _PromptTemplate(
        template=entry.template.template,
        timezone=entry.template.timezone,
        source="directus:memory_cache",
        client_id=entry.template.client_id,
    )


def _set_memory_cached_prompt(caller_id: str, template: _PromptTemplate) -> None:
    if DIRECTUS_PROMPT_CACHE_TTL_SEC <= 0:
        return
    _prompt_cache[caller_id] = _PromptCacheEntry(
        template=template,
        expires_at=time.monotonic() + DIRECTUS_PROMPT_CACHE_TTL_SEC,
    )


def _build_transfer_directory_block(rows: list[dict[str, Any]]) -> str:
    transfer_rows = []
    for row in rows:
        disc = _string_value(row.get("disc")).strip()
        direction = _string_value(row.get("direction")).strip()
        if not disc or not direction:
            continue
        transfer_rows.append(f"| {disc} | {direction} |")

    if not transfer_rows:
        return ""

    return (
        "<transfer_directory>\n"
        "(Список доступных направлений для перевода звонка)\n"
        "ИНСТРУКЦИЯ ПО ВЫБОРУ:\n"
        "1. Если клиент называет улицу/ориентир — ищи совпадение в таблице.\n"
        "2. Если совпадения нет используй GEO_SEARCH.\n"
        "3. Если клиент просит \"оператора\" или описывает проблему — ищи "
        "подходящий отдел.\n"
        "4. Добавляй тег [TRANSFER: ID] в конце ответа, если перевод необходим.\n\n"
        "ТАБЛИЦА НАПРАВЛЕНИЙ:\n"
        "| ID | Описание / Адрес |\n"
        "| :--- | :--- |\n"
        f"{chr(10).join(transfer_rows)}\n"
        "</transfer_directory>"
    )


def _resolve_timezone(timezone_name: str) -> ZoneInfo:
    normalized = (timezone_name or "").strip() or DIRECTUS_DEFAULT_TIMEZONE
    try:
        return ZoneInfo(normalized)
    except ZoneInfoNotFoundError:
        logger.warning("unknown Directus prompt timezone; using default")
        return ZoneInfo(DIRECTUS_DEFAULT_TIMEZONE)


def _relation_id(value: Any) -> str | int | None:
    if isinstance(value, dict):
        for key in ("id", "value", "key"):
            relation_value = value.get(key)
            if relation_value not in (None, ""):
                return relation_value
        return None
    if value in (None, ""):
        return None
    return value


def _string_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _directus_filter_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _template_hash(template: str) -> str:
    return hashlib.sha256(template.encode("utf-8")).hexdigest()
