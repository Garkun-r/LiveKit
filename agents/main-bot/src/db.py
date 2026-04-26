import asyncpg

from config import POSTGRES_DSN

_pool = None


async def get_pool():
    global _pool
    if _pool is None:
        if not POSTGRES_DSN:
            raise RuntimeError("POSTGRES_DSN is not set")
        _pool = await asyncpg.create_pool(dsn=POSTGRES_DSN, min_size=1, max_size=5)
    return _pool
