import pytest

import prompt_repo


class _AcquireContext:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Pool:
    def __init__(self, row=None, error=None):
        self.conn = _Conn(row=row, error=error)

    def acquire(self):
        return _AcquireContext(self.conn)


class _Conn:
    def __init__(self, row=None, error=None):
        self.row = row
        self.error = error
        self.calls = []

    async def fetchrow(self, query, trunk_number):
        self.calls.append((query, trunk_number))
        if self.error:
            raise self.error
        return self.row


@pytest.fixture()
def prompt_file(tmp_path, monkeypatch):
    path = tmp_path / "prompt.txt"
    path.write_text("base prompt", encoding="utf-8")
    monkeypatch.setattr(prompt_repo, "PROMPT_FILE", path)
    return path


@pytest.mark.asyncio
async def test_resolve_prompt_uses_file_without_trunk_number(prompt_file):
    result = await prompt_repo.resolve_prompt_for_call(sip_trunk_number=None)

    assert result.prompt == "base prompt"
    assert result.source == "file:no_sip_trunk_number"


@pytest.mark.asyncio
async def test_resolve_prompt_uses_postgres_prompt(prompt_file, monkeypatch):
    pool = _Pool(row={"prompt": "db prompt"})
    monkeypatch.setattr(prompt_repo, "POSTGRES_DSN", "postgres://example")
    monkeypatch.setattr(
        prompt_repo, "PROMPT_LOOKUP_SQL", "select prompt from prompts where trunk = $1"
    )

    async def pool_factory():
        return pool

    result = await prompt_repo.resolve_prompt_for_call(
        sip_trunk_number="+15550100",
        sip_client_number="+15550101",
        pool_factory=pool_factory,
    )

    assert result.prompt == "db prompt"
    assert result.source == "postgres"
    assert result.sip_trunk_number == "+15550100"
    assert result.sip_client_number == "+15550101"
    assert pool.conn.calls == [
        ("select prompt from prompts where trunk = $1", "+15550100")
    ]


@pytest.mark.asyncio
async def test_resolve_prompt_does_not_require_file_when_postgres_prompt_exists(
    tmp_path, monkeypatch
):
    pool = _Pool(row={"prompt": "db prompt"})
    monkeypatch.setattr(prompt_repo, "PROMPT_FILE", tmp_path / "missing-prompt.txt")
    monkeypatch.setattr(prompt_repo, "POSTGRES_DSN", "postgres://example")
    monkeypatch.setattr(
        prompt_repo, "PROMPT_LOOKUP_SQL", "select prompt from prompts where trunk = $1"
    )

    async def pool_factory():
        return pool

    result = await prompt_repo.resolve_prompt_for_call(
        sip_trunk_number="+15550100",
        pool_factory=pool_factory,
    )

    assert result.prompt == "db prompt"
    assert result.source == "postgres"


@pytest.mark.asyncio
async def test_resolve_prompt_falls_back_when_lookup_fails(prompt_file, monkeypatch):
    monkeypatch.setattr(prompt_repo, "POSTGRES_DSN", "postgres://example")
    monkeypatch.setattr(
        prompt_repo, "PROMPT_LOOKUP_SQL", "select prompt from prompts where trunk = $1"
    )

    async def pool_factory():
        return _Pool(error=RuntimeError("database unavailable"))

    result = await prompt_repo.resolve_prompt_for_call(
        sip_trunk_number="+15550100",
        pool_factory=pool_factory,
    )

    assert result.prompt == "base prompt"
    assert result.source == "file:lookup_error"
    assert "database unavailable" in result.error


@pytest.mark.asyncio
async def test_resolve_prompt_falls_back_when_prompt_not_found(
    prompt_file, monkeypatch
):
    monkeypatch.setattr(prompt_repo, "POSTGRES_DSN", "postgres://example")
    monkeypatch.setattr(
        prompt_repo, "PROMPT_LOOKUP_SQL", "select prompt from prompts where trunk = $1"
    )

    async def pool_factory():
        return _Pool(row=None)

    result = await prompt_repo.resolve_prompt_for_call(
        sip_trunk_number="+15550100",
        pool_factory=pool_factory,
    )

    assert result.prompt == "base prompt"
    assert result.source == "file:not_found"
