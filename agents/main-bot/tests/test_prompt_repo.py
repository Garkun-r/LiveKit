# ruff: noqa: RUF001
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest

import prompt_repo


class _DirectusResponse:
    def __init__(
        self,
        payload: dict[str, Any],
        status_code: int = 200,
        *,
        method: str = "GET",
        url: str = "https://directus.example/items/test",
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.request = httpx.Request(method, url)

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "Directus request failed",
                request=self.request,
                response=httpx.Response(self.status_code, request=self.request),
            )


class _DirectusHttpClient:
    def __init__(
        self,
        rows_by_collection: dict[str, list[dict[str, Any]]],
        *,
        status_by_collection: dict[str, int] | None = None,
    ) -> None:
        self.rows_by_collection = rows_by_collection
        self.status_by_collection = status_by_collection or {}
        self.requests = []
        self.writes = []

    async def get(self, path: str, *, params: dict[str, Any]) -> _DirectusResponse:
        collection = path.rsplit("/", 1)[-1]
        self.requests.append((collection, dict(params)))
        status_code = self.status_by_collection.get(collection)
        if status_code is not None:
            return _DirectusResponse({"errors": []}, status_code=status_code)
        rows = list(self.rows_by_collection.get(collection, []))
        for key, value in params.items():
            if not key.startswith("filter[") or not key.endswith("][_eq]"):
                continue
            field = key[len("filter[") : -len("][_eq]")]
            rows = [
                row
                for row in rows
                if str(row.get(field)).lower() == str(value).lower()
            ]
        limit = int(params.get("limit", "1"))
        return _DirectusResponse({"data": rows[:limit]})

    async def post(self, path: str, *, json: dict[str, Any]) -> _DirectusResponse:
        collection = path.rsplit("/", 1)[-1]
        self.writes.append(("post", collection, dict(json)))
        status_code = self.status_by_collection.get(collection)
        if status_code is not None:
            return _DirectusResponse(
                {"errors": []},
                status_code=status_code,
                method="POST",
            )

        rows = self.rows_by_collection.setdefault(collection, [])
        next_id = max([int(row.get("id", 0) or 0) for row in rows] + [0]) + 1
        row = {"id": next_id, **json}
        rows.append(row)
        return _DirectusResponse({"data": row}, method="POST")

    async def patch(self, path: str, *, json: dict[str, Any]) -> _DirectusResponse:
        collection, row_id = path.rsplit("/", 2)[-2:]
        self.writes.append(("patch", collection, row_id, dict(json)))
        status_code = self.status_by_collection.get(collection)
        if status_code is not None:
            return _DirectusResponse(
                {"errors": []},
                status_code=status_code,
                method="PATCH",
            )

        rows = self.rows_by_collection.setdefault(collection, [])
        for row in rows:
            if str(row.get("id")) == str(row_id):
                row.update(json)
                return _DirectusResponse({"data": row}, method="PATCH")
        return _DirectusResponse({"errors": []}, status_code=404, method="PATCH")


class _ErrorDirectusClient:
    async def __aenter__(self) -> "_ErrorDirectusClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def fetch_cached_prompt(self, caller_id: str):
        raise httpx.TimeoutException("timeout")

    async def save_cached_prompt(self, *, caller_id: str, prompt_template):
        raise AssertionError("save should not be called")


@pytest.fixture(autouse=True)
def reset_prompt_repo(monkeypatch):
    prompt_repo.clear_prompt_cache()
    monkeypatch.setattr(prompt_repo, "DIRECTUS_URL", "")
    monkeypatch.setattr(prompt_repo, "DIRECTUS_TOKEN", "")
    monkeypatch.setattr(prompt_repo, "DIRECTUS_PROMPT_CACHE_TTL_SEC", 300.0)
    yield
    prompt_repo.clear_prompt_cache()


@pytest.fixture()
def prompt_file(tmp_path, monkeypatch):
    path = tmp_path / "prompt.txt"
    path.write_text("base prompt", encoding="utf-8")
    monkeypatch.setattr(prompt_repo, "PROMPT_FILE", path)
    return path


def _fixed_now(_: ZoneInfo) -> datetime:
    return datetime(2026, 4, 29, 17, 55)


def _directus_factory(http_client: _DirectusHttpClient):
    def factory() -> prompt_repo.DirectusPromptClient:
        return prompt_repo.DirectusPromptClient(
            base_url="https://directus.example",
            token="token",
            timeout_sec=2.0,
            http_client=http_client,
        )

    return factory


def _enable_directus(monkeypatch) -> None:
    monkeypatch.setattr(prompt_repo, "DIRECTUS_URL", "https://directus.example")
    monkeypatch.setattr(prompt_repo, "DIRECTUS_TOKEN", "token")


@pytest.mark.asyncio
async def test_resolve_prompt_uses_file_without_trunk_number(prompt_file):
    result = await prompt_repo.resolve_prompt_for_call(sip_trunk_number=None)

    assert result.prompt == "base prompt"
    assert result.source == "file:no_sip_trunk_number"


@pytest.mark.asyncio
async def test_resolve_prompt_uses_file_without_directus_config(prompt_file):
    result = await prompt_repo.resolve_prompt_for_call(sip_trunk_number="+15550100")

    assert result.prompt == "base prompt"
    assert result.source == "file:no_directus_config"


@pytest.mark.asyncio
async def test_resolve_prompt_uses_directus_cached_template(
    prompt_file, monkeypatch
):
    _enable_directus(monkeypatch)
    http_client = _DirectusHttpClient(
        {
            "client_prompt_cache": [
                {
                    "caller_id": "+15550100",
                    "client_id": 7,
                    "prompt_template": (
                        "cached prompt\n"
                        f"{prompt_repo._CURRENT_DATETIME_PLACEHOLDER}"
                    ),
                    "timezone": "Europe/Kaliningrad",
                    "active": True,
                }
            ],
        }
    )

    result = await prompt_repo.resolve_prompt_for_call(
        sip_trunk_number="+15550100",
        sip_client_number="+15550101",
        directus_client_factory=_directus_factory(http_client),
        now_factory=_fixed_now,
    )

    assert result.source == "directus:cache"
    assert result.sip_trunk_number == "+15550100"
    assert result.sip_client_number == "+15550101"
    assert "cached prompt" in result.prompt
    assert "- Дата: 29 апреля 2026 г." in result.prompt
    assert "- День недели: среда" in result.prompt


@pytest.mark.asyncio
async def test_resolve_prompt_uses_memory_cache_without_second_http_call(
    prompt_file, monkeypatch
):
    _enable_directus(monkeypatch)
    http_client = _DirectusHttpClient(
        {
            "client_prompt_cache": [
                {
                    "caller_id": "+15550100",
                    "client_id": 7,
                    "prompt_template": "cached prompt",
                    "timezone": "Europe/Kaliningrad",
                    "active": True,
                }
            ],
        }
    )

    first = await prompt_repo.resolve_prompt_for_call(
        sip_trunk_number="+15550100",
        directus_client_factory=_directus_factory(http_client),
    )
    second = await prompt_repo.resolve_prompt_for_call(
        sip_trunk_number="+15550100",
        directus_client_factory=_directus_factory(http_client),
    )

    assert first.source == "directus:cache"
    assert second.source == "directus:memory_cache"
    assert len(http_client.requests) == 1


@pytest.mark.asyncio
async def test_resolve_prompt_builds_live_prompt_on_cache_miss(
    prompt_file, monkeypatch
):
    _enable_directus(monkeypatch)
    http_client = _DirectusHttpClient(
        {
            "client_prompt_cache": [],
            "CallerID": [{"CallerID": "+15550100", "client_id": 7}],
            "bot_configurations": [
                {
                    "client_id": 7,
                    "system_prompt": "specific strategy",
                    "examples": "dialogue example",
                    "skills_name": "skill_info+questions",
                }
            ],
            "clients": [
                {
                    "id": 7,
                    "add_info": "client knowledge",
                    "company_website": "https://example.com",
                    "company_extra": "company card",
                }
            ],
            "clients_prompt": [
                {"name": "global_rules", "text": "global rules text"},
                {"name": "skill_info+questions", "text": "skills text"},
            ],
            "webparsing": [{"url": "example.com", "text": "website knowledge"}],
            "transfer_number": [
                {"client_id": 7, "disc": "TR1", "direction": "Sales"},
            ],
        }
    )

    result = await prompt_repo.resolve_prompt_for_call(
        sip_trunk_number="+15550100",
        directus_client_factory=_directus_factory(http_client),
        now_factory=_fixed_now,
    )

    assert result.source == "directus:live"
    assert "global rules text" in result.prompt
    assert "skills text" in result.prompt
    assert "client knowledge" in result.prompt
    assert "website knowledge" in result.prompt
    assert "company card" in result.prompt
    assert "| TR1 | Sales |" in result.prompt
    assert "specific strategy" in result.prompt
    assert "dialogue example" in result.prompt
    assert len(http_client.writes) == 1
    method, collection, payload = http_client.writes[0]
    assert method == "post"
    assert collection == "client_prompt_cache"
    assert payload["caller_id"] == "+15550100"
    assert payload["client_id"] == 7
    assert payload["active"] is True
    assert payload["last_error"] is None
    assert len(payload["source_hash"]) == 64
    assert "global rules text" in payload["prompt_template"]
    assert prompt_repo._CURRENT_DATETIME_PLACEHOLDER in payload["prompt_template"]


@pytest.mark.asyncio
async def test_resolve_prompt_updates_existing_inactive_cache_row(
    prompt_file, monkeypatch
):
    _enable_directus(monkeypatch)
    http_client = _DirectusHttpClient(
        {
            "client_prompt_cache": [
                {
                    "id": 42,
                    "caller_id": "+15550100",
                    "client_id": 7,
                    "prompt_template": "old prompt",
                    "timezone": "Europe/Kaliningrad",
                    "active": False,
                }
            ],
            "CallerID": [{"CallerID": "+15550100", "client_id": 7}],
            "bot_configurations": [
                {
                    "client_id": 7,
                    "system_prompt": "specific strategy",
                    "examples": "dialogue example",
                    "skills_name": "skill_info+questions",
                }
            ],
            "clients": [
                {
                    "id": 7,
                    "add_info": "client knowledge",
                    "company_website": "",
                    "company_extra": "",
                }
            ],
            "clients_prompt": [
                {"name": "global_rules", "text": "global rules text"},
                {"name": "skill_info+questions", "text": "skills text"},
            ],
            "transfer_number": [],
        }
    )

    result = await prompt_repo.resolve_prompt_for_call(
        sip_trunk_number="+15550100",
        directus_client_factory=_directus_factory(http_client),
    )

    assert result.source == "directus:live"
    assert len(http_client.writes) == 1
    method, collection, row_id, payload = http_client.writes[0]
    assert method == "patch"
    assert collection == "client_prompt_cache"
    assert row_id == "42"
    assert payload["active"] is True
    assert "skills text" in payload["prompt_template"]


@pytest.mark.asyncio
async def test_resolve_prompt_builds_live_prompt_when_cache_collection_missing(
    prompt_file, monkeypatch
):
    _enable_directus(monkeypatch)
    http_client = _DirectusHttpClient(
        {
            "CallerID": [{"CallerID": "+15550100", "client_id": 7}],
            "bot_configurations": [
                {
                    "client_id": 7,
                    "system_prompt": "specific strategy",
                    "examples": "dialogue example",
                    "skills_name": "skill_info+questions",
                }
            ],
            "clients": [
                {
                    "id": 7,
                    "add_info": "client knowledge",
                    "company_website": "",
                    "company_extra": "",
                }
            ],
            "clients_prompt": [
                {"name": "global_rules", "text": "global rules text"},
                {"name": "skill_info+questions", "text": "skills text"},
            ],
            "transfer_number": [],
        },
        status_by_collection={"client_prompt_cache": 404},
    )

    result = await prompt_repo.resolve_prompt_for_call(
        sip_trunk_number="+15550100",
        directus_client_factory=_directus_factory(http_client),
    )

    assert result.source == "directus:live"
    assert "global rules text" in result.prompt


@pytest.mark.asyncio
async def test_live_prompt_omits_transfer_directory_when_transfers_are_empty(
    prompt_file, monkeypatch
):
    _enable_directus(monkeypatch)
    http_client = _DirectusHttpClient(
        {
            "client_prompt_cache": [],
            "CallerID": [{"CallerID": "+15550100", "client_id": 7}],
            "bot_configurations": [
                {
                    "client_id": 7,
                    "system_prompt": "specific strategy",
                    "examples": "dialogue example",
                    "skills_name": "skill_info+questions",
                }
            ],
            "clients": [
                {
                    "id": 7,
                    "add_info": "client knowledge",
                    "company_website": "",
                    "company_extra": "",
                }
            ],
            "clients_prompt": [
                {"name": "global_rules", "text": "global rules text"},
                {"name": "skill_info+questions", "text": "skills text"},
            ],
            "transfer_number": [],
        }
    )

    result = await prompt_repo.resolve_prompt_for_call(
        sip_trunk_number="+15550100",
        directus_client_factory=_directus_factory(http_client),
    )

    assert result.source == "directus:live"
    assert "<transfer_directory>" not in result.prompt


@pytest.mark.asyncio
async def test_resolve_prompt_falls_back_when_directus_fails(
    prompt_file, monkeypatch
):
    _enable_directus(monkeypatch)

    result = await prompt_repo.resolve_prompt_for_call(
        sip_trunk_number="+15550100",
        directus_client_factory=lambda: _ErrorDirectusClient(),
    )

    assert result.prompt == "base prompt"
    assert result.source == "file:lookup_error"
    assert "timeout" in result.error
