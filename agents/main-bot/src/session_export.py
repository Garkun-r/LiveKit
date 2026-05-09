from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from config import (
    AGENT_NAME,
    DIRECTUS_REQUEST_TIMEOUT_SEC,
    DIRECTUS_TOKEN,
    DIRECTUS_URL,
    N8N_WEBHOOK_TOKEN,
    N8N_WEBHOOK_URL,
    ROBOT_RUNTIME_PROFILE,
)


def _safe_text(value) -> str | None:
    text = str(value or "").strip()
    return text or None


def _transcript_to_text(items: list | None) -> str | None:
    lines: list[str] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        role = _safe_text(item.get("role") or item.get("speaker") or item.get("participant"))
        text = _safe_text(item.get("text") or item.get("transcript") or item.get("content"))
        if not text:
            continue
        lines.append(f"{role or 'unknown'}: {text}")
    return "\n".join(lines) or None


def _session_status(payload: dict) -> str:
    close = payload.get("close") if isinstance(payload.get("close"), dict) else {}
    if close.get("error"):
        return "failed"
    return _safe_text(close.get("reason")) or "completed"


def _directus_session_payload(payload: dict) -> dict:
    sip = payload.get("sip") if isinstance(payload.get("sip"), dict) else {}
    close = payload.get("close") if isinstance(payload.get("close"), dict) else {}
    transcript_items = payload.get("transcript_items") or []
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    return {
        "source": "livekit_agent",
        "agent_name": payload.get("agent_name") or AGENT_NAME,
        "runtime_profile": ROBOT_RUNTIME_PROFILE,
        "room_name": payload.get("room_name"),
        "session_id": payload.get("room_name"),
        "client_id": payload.get("client_id"),
        "client_name": payload.get("client_name"),
        "phone_number": sip.get("sip_client_number"),
        "xdid": sip.get("sip_trunk_number") or sip.get("gateway_number"),
        "did": sip.get("sip_trunk_number") or sip.get("gateway_number"),
        "gateway_number": sip.get("gateway_number") or sip.get("sip_trunk_number"),
        "sip_call_id": sip.get("sip_call_id"),
        "trace_id": sip.get("trace_id"),
        "started_at": payload.get("started_at"),
        "ended_at": payload.get("ended_at"),
        "duration_sec": payload.get("duration_sec"),
        "status": _session_status(payload),
        "close_reason": close.get("reason"),
        "prompt_source": sip.get("prompt_source"),
        "chat_history": _transcript_to_text(transcript_items),
        "transcript_items": transcript_items,
        "tag_events": payload.get("tag_events") or [],
        "usage_updates": payload.get("usage_updates") or [],
        "metrics_summary": summary,
        "payload": {
            "close": close,
            "sip": sip,
            "metrics_events": payload.get("metrics_events") or [],
            "component_metrics_events": payload.get("component_metrics_events") or [],
        },
    }


async def send_session_to_directus(payload: dict) -> None:
    if not DIRECTUS_URL or not DIRECTUS_TOKEN:
        print("[directus] DIRECTUS_URL or DIRECTUS_TOKEN is empty, skip call session export", flush=True)
        return
    body = {key: value for key, value in _directus_session_payload(payload).items() if value is not None}
    room_name = _safe_text(body.get("room_name"))
    if not room_name:
        print("[directus] room_name is empty, skip call session export", flush=True)
        return

    headers = {
        "Authorization": f"Bearer {DIRECTUS_TOKEN}",
        "Content-Type": "application/json",
    }
    base = DIRECTUS_URL.rstrip("/")
    timeout = max(float(DIRECTUS_REQUEST_TIMEOUT_SEC or 2.0), 5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        lookup = await client.get(
            f"{base}/items/robot_call_sessions",
            params={
                "limit": 1,
                "fields": "id",
                "filter[room_name][_eq]": room_name,
            },
            headers=headers,
        )
        lookup.raise_for_status()
        rows = lookup.json().get("data") or []
        if rows:
            session_item_id = rows[0]["id"]
            resp = await client.patch(
                f"{base}/items/robot_call_sessions/{session_item_id}",
                json=body,
                headers=headers,
            )
        else:
            resp = await client.post(
                f"{base}/items/robot_call_sessions",
                json=body,
                headers=headers,
            )
        print(f"[directus] call session status={resp.status_code}", flush=True)
        resp.raise_for_status()
        if not rows:
            session_item_id = resp.json().get("data", {}).get("id")
        if session_item_id:
            try:
                await link_recordings_to_session(
                    client=client,
                    base=base,
                    headers=headers,
                    room_name=room_name,
                    session_item_id=session_item_id,
                )
            except Exception as exc:
                print(f"[directus] recording/session link failed: {exc}", flush=True)
            try:
                await link_raw_logs_to_session(
                    client=client,
                    base=base,
                    headers=headers,
                    room_name=room_name,
                    session_item_id=session_item_id,
                )
            except Exception as exc:
                print(f"[directus] raw log/session link failed: {exc}", flush=True)


async def link_recordings_to_session(
    *,
    client: httpx.AsyncClient,
    base: str,
    headers: dict[str, str],
    room_name: str,
    session_item_id: int | str,
) -> None:
    lookup = await client.get(
        f"{base}/items/robot_call_recordings",
        params={
            "limit": 20,
            "fields": "id,call_session",
            "filter[room_name][_eq]": room_name,
            "filter[call_session][_null]": "true",
        },
        headers=headers,
    )
    lookup.raise_for_status()
    rows = lookup.json().get("data") or []
    for row in rows:
        recording_id = row.get("id")
        if not recording_id:
            continue
        resp = await client.patch(
            f"{base}/items/robot_call_recordings/{recording_id}",
            json={"call_session": session_item_id},
            headers=headers,
        )
        resp.raise_for_status()
    if rows:
        print(f"[directus] linked recordings to call session count={len(rows)}", flush=True)


async def link_raw_logs_to_session(
    *,
    client: httpx.AsyncClient,
    base: str,
    headers: dict[str, str],
    room_name: str,
    session_item_id: int | str,
) -> None:
    lookup = await client.get(
        f"{base}/items/robot_call_raw_logs",
        params={
            "limit": 2000,
            "fields": "id,call_session",
            "filter[room_name][_eq]": room_name,
            "filter[call_session][_null]": "true",
        },
        headers=headers,
    )
    if lookup.status_code in {403, 404}:
        return
    lookup.raise_for_status()
    rows = lookup.json().get("data") or []
    for row in rows:
        raw_log_id = row.get("id")
        if not raw_log_id:
            continue
        resp = await client.patch(
            f"{base}/items/robot_call_raw_logs/{raw_log_id}",
            json={"call_session": session_item_id},
            headers=headers,
        )
        resp.raise_for_status()
    if rows:
        print(f"[directus] linked raw logs to call session count={len(rows)}", flush=True)


async def send_session_to_n8n(payload: dict) -> None:
    try:
        await send_session_to_directus(payload)
    except Exception as exc:
        print(f"[directus] call session export failed: {exc}", flush=True)

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
