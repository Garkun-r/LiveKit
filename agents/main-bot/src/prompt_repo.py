from .db import get_pool
from .config import AGENT_NAME

DEFAULT_PROMPT = """
Ты полезный голосовой AI-агент.
Отвечай кратко, вежливо и по делу.
"""

async def get_active_prompt() -> str:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                select prompt_text
                from agent_prompts
                where agent_name = $1 and is_active = true
                order by updated_at desc
                limit 1
                """,
                AGENT_NAME,
            )
            if row and row["prompt_text"]:
                return row["prompt_text"]
    except Exception as e:
        print(f"[prompt_repo] fallback to default prompt, reason: {e}")

    return DEFAULT_PROMPT
