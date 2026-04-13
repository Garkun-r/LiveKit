import httpx
from datetime import datetime, timezone
from urllib.parse import urlparse

from config import AGENT_NAME, N8N_WEBHOOK_TOKEN, N8N_WEBHOOK_URL


async def send_session_to_n8n(payload: dict) -> None:
    if not N8N_WEBHOOK_URL:
        print("[n8n] N8N_WEBHOOK_URL is empty, skip export", flush=True)
        return
    parsed = urlparse(N8N_WEBHOOK_URL)
    if not parsed.hostname or parsed.hostname == "your-n8n-domain":
        print(
            "[n8n] N8N_WEBHOOK_URL looks like a placeholder, set a real URL in .env.local",
            flush=True,
        )
        return

    headers = {"Content-Type": "application/json"}
    if N8N_WEBHOOK_TOKEN:
        headers["Authorization"] = f"Bearer {N8N_WEBHOOK_TOKEN}"

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            N8N_WEBHOOK_URL,
            json={
                "agent_name": AGENT_NAME,
                "sent_at": datetime.now(timezone.utc).isoformat(),
                **payload,
            },
            headers=headers,
        )
        print(f"[n8n] status={resp.status_code}", flush=True)
        resp.raise_for_status()
