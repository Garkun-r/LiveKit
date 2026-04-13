import httpx
from datetime import datetime, timezone
from .config import N8N_WEBHOOK_URL, N8N_WEBHOOK_TOKEN, AGENT_NAME

async def send_session_summary(payload: dict):
    if not N8N_WEBHOOK_URL:
        print("[session_export] N8N_WEBHOOK_URL is empty, skip export")
        return

    body = {
        "agent_name": AGENT_NAME,
        "sent_at": datetime.now(timezone.utc).isoformat(),
        **payload,
    }

    headers = {"Content-Type": "application/json"}
    if N8N_WEBHOOK_TOKEN:
        headers["Authorization"] = f"Bearer {N8N_WEBHOOK_TOKEN}"

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(N8N_WEBHOOK_URL, json=body, headers=headers)
        print(f"[session_export] status={resp.status_code}")
        resp.raise_for_status()
