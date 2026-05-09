import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from google.protobuf.json_format import MessageToDict
from livekit import api

from config import (
    CALL_RECORDING_ENABLED,
    CALL_RECORDING_FINALIZE_POLL_SEC,
    CALL_RECORDING_FINALIZE_TIMEOUT_SEC,
    CALL_RECORDING_PREFIX,
    CALL_RECORDING_S3_ACCESS_KEY,
    CALL_RECORDING_S3_BUCKET,
    CALL_RECORDING_S3_ENDPOINT,
    CALL_RECORDING_S3_FORCE_PATH_STYLE,
    CALL_RECORDING_S3_REGION,
    CALL_RECORDING_S3_SECRET_KEY,
    DIRECTUS_REQUEST_TIMEOUT_SEC,
    DIRECTUS_TOKEN,
    DIRECTUS_URL,
    LIVEKIT_API_KEY,
    LIVEKIT_API_SECRET,
    LIVEKIT_URL,
)


@dataclass(frozen=True)
class RecordingHandle:
    egress_id: str
    room_name: str
    object_key: str
    started_at: str


ACTIVE_EGRESS_STATUSES = {
    api.EgressStatus.EGRESS_STARTING,
    api.EgressStatus.EGRESS_ACTIVE,
    api.EgressStatus.EGRESS_ENDING,
}
PENDING_RECORDING_STATUSES = {"", "starting", "active", "ending"}


def _recording_configured() -> bool:
    return bool(
        CALL_RECORDING_ENABLED
        and LIVEKIT_URL
        and LIVEKIT_API_KEY
        and LIVEKIT_API_SECRET
        and CALL_RECORDING_S3_ENDPOINT
        and CALL_RECORDING_S3_BUCKET
        and CALL_RECORDING_S3_ACCESS_KEY
        and CALL_RECORDING_S3_SECRET_KEY
    )


def _directus_configured() -> bool:
    return bool(DIRECTUS_URL and DIRECTUS_TOKEN)


def _object_key(room_name: str, started_at: datetime) -> str:
    safe_room = (
        "".join(
            char if char.isalnum() or char in {"-", "_", "."} else "_"
            for char in room_name
        ).strip("_")
        or "room"
    )
    stamp = started_at.strftime("%Y%m%dT%H%M%SZ")
    prefix = CALL_RECORDING_PREFIX or "livekit"
    return f"{prefix}/{safe_room}/{stamp}.mp3"


def _egress_status_name(value: int) -> str:
    try:
        return api.EgressStatus.Name(value).removeprefix("EGRESS_").lower()
    except Exception:
        return str(value)


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _message_to_dict(value: Any) -> dict[str, Any]:
    try:
        return MessageToDict(value, preserving_proto_field_name=True)
    except Exception:
        return {}


def _ns_timestamp_to_iso(value: Any) -> str | None:
    if not value:
        return None
    if hasattr(value, "ToDatetime"):
        return value.ToDatetime(tzinfo=timezone.utc).isoformat()
    try:
        return datetime.fromtimestamp(
            int(value) / 1_000_000_000, tz=timezone.utc
        ).isoformat()
    except Exception:
        return None


def _ns_duration_to_sec(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return int(value) / 1_000_000_000
    except Exception:
        return None


async def _directus_request(
    method: str, path: str, body: dict[str, Any]
) -> dict[str, Any] | None:
    if not _directus_configured():
        return None

    timeout = max(float(DIRECTUS_REQUEST_TIMEOUT_SEC or 2.0), 5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.request(
            method,
            f"{DIRECTUS_URL.rstrip('/')}{path}",
            headers={
                "Authorization": f"Bearer {DIRECTUS_TOKEN}",
                "Content-Type": "application/json",
            },
            json=body,
        )
        resp.raise_for_status()
        return resp.json().get("data")


async def _directus_get(path: str, params: dict[str, Any]) -> dict[str, Any] | None:
    if not _directus_configured():
        return None

    timeout = max(float(DIRECTUS_REQUEST_TIMEOUT_SEC or 2.0), 5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(
            f"{DIRECTUS_URL.rstrip('/')}{path}",
            params={
                key: value for key, value in params.items() if value not in (None, "")
            },
            headers={"Authorization": f"Bearer {DIRECTUS_TOKEN}"},
        )
        resp.raise_for_status()
        return resp.json()


async def _find_recording_id(egress_id: str, object_key: str) -> str | None:
    if not _directus_configured():
        return None

    timeout = max(float(DIRECTUS_REQUEST_TIMEOUT_SEC or 2.0), 5.0)
    params = {
        "limit": 1,
        "fields": "id",
        "filter[_or][0][egress_id][_eq]": egress_id,
        "filter[_or][1][object_key][_eq]": object_key,
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(
            f"{DIRECTUS_URL.rstrip('/')}/items/robot_call_recordings",
            params=params,
            headers={"Authorization": f"Bearer {DIRECTUS_TOKEN}"},
        )
        resp.raise_for_status()
        return (resp.json().get("data") or [{}])[0].get("id")


async def upsert_recording(payload: dict[str, Any]) -> None:
    existing_id = await _find_recording_id(payload["egress_id"], payload["object_key"])
    if existing_id:
        await _directus_request(
            "PATCH",
            f"/items/robot_call_recordings/{existing_id}",
            payload,
        )
    else:
        await _directus_request("POST", "/items/robot_call_recordings", payload)


def _file_result_object_key(file_info: Any, fallback: str) -> str:
    return _first_non_empty(
        getattr(file_info, "filename", ""),
        getattr(file_info, "filepath", ""),
        fallback,
    )


def recording_payload_from_egress(
    handle: RecordingHandle,
    info: api.EgressInfo,
) -> dict[str, Any]:
    file_info = info.file_results[0] if info.file_results else None
    object_key = (
        _file_result_object_key(file_info, handle.object_key)
        if file_info
        else handle.object_key
    )
    body: dict[str, Any] = {
        "source": "livekit_egress",
        "room_name": _first_non_empty(handle.room_name, getattr(info, "room_name", "")),
        "session_id": _first_non_empty(
            handle.room_name, getattr(info, "room_name", "")
        ),
        "egress_id": handle.egress_id,
        "status": _egress_status_name(info.status),
        "storage_provider": "minio",
        "storage_bucket": CALL_RECORDING_S3_BUCKET,
        "object_key": object_key,
        "file_name": object_key.rsplit("/", 1)[-1] if object_key else "",
        "mime_type": "audio/mpeg",
        "started_at": handle.started_at,
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "error": info.error or None,
        "payload": {"egress": _message_to_dict(info)},
    }
    if file_info:
        body["file_size"] = file_info.size or None
        body["duration_sec"] = _ns_duration_to_sec(file_info.duration)
        ended_at = _ns_timestamp_to_iso(file_info.ended_at)
        if ended_at:
            body["ended_at"] = ended_at
    if info.status in ACTIVE_EGRESS_STATUSES and not file_info:
        body.pop("ended_at", None)
    return body


async def start_room_recording(room_name: str) -> RecordingHandle | None:
    if not _recording_configured():
        return None

    started = datetime.now(timezone.utc)
    object_key = _object_key(room_name, started)
    lk = api.LiveKitAPI(
        url=LIVEKIT_URL,
        api_key=LIVEKIT_API_KEY,
        api_secret=LIVEKIT_API_SECRET,
    )
    try:
        info = await lk.egress.start_room_composite_egress(
            api.RoomCompositeEgressRequest(
                room_name=room_name,
                audio_only=True,
                audio_mixing=api.AudioMixing.DEFAULT_MIXING,
                file_outputs=[
                    api.EncodedFileOutput(
                        file_type=api.EncodedFileType.MP3,
                        filepath=object_key,
                        s3=api.S3Upload(
                            access_key=CALL_RECORDING_S3_ACCESS_KEY,
                            secret=CALL_RECORDING_S3_SECRET_KEY,
                            region=CALL_RECORDING_S3_REGION,
                            endpoint=CALL_RECORDING_S3_ENDPOINT,
                            bucket=CALL_RECORDING_S3_BUCKET,
                            force_path_style=CALL_RECORDING_S3_FORCE_PATH_STYLE,
                        ),
                    )
                ],
            )
        )
    finally:
        await lk.aclose()

    handle = RecordingHandle(
        egress_id=info.egress_id,
        room_name=room_name,
        object_key=object_key,
        started_at=started.isoformat(),
    )
    try:
        await upsert_recording(
            {
                "source": "livekit_egress",
                "room_name": room_name,
                "session_id": room_name,
                "egress_id": handle.egress_id,
                "status": _egress_status_name(info.status),
                "storage_provider": "minio",
                "storage_bucket": CALL_RECORDING_S3_BUCKET,
                "object_key": object_key,
                "file_name": object_key.rsplit("/", 1)[-1],
                "mime_type": "audio/mpeg",
                "started_at": handle.started_at,
                "payload": {"egress": _message_to_dict(info)},
            }
        )
    except Exception as exc:
        print(f"[recording] initial Directus upsert failed: {exc}", flush=True)
    return handle


async def _list_egress(egress_id: str) -> api.EgressInfo | None:
    lk = api.LiveKitAPI(
        url=LIVEKIT_URL,
        api_key=LIVEKIT_API_KEY,
        api_secret=LIVEKIT_API_SECRET,
    )
    try:
        response = await lk.egress.list_egress(
            api.ListEgressRequest(egress_id=egress_id)
        )
    finally:
        await lk.aclose()
    return response.items[0] if response.items else None


async def finalize_room_recording(handle: RecordingHandle | None) -> None:
    if not handle:
        return

    deadline = asyncio.get_running_loop().time() + max(
        CALL_RECORDING_FINALIZE_TIMEOUT_SEC, 0
    )
    info: api.EgressInfo | None = None
    while True:
        info = await _list_egress(handle.egress_id)
        if info is None or info.status not in ACTIVE_EGRESS_STATUSES:
            break
        if asyncio.get_running_loop().time() >= deadline:
            break
        await asyncio.sleep(max(CALL_RECORDING_FINALIZE_POLL_SEC, 0.5))

    if info is None:
        return

    body = recording_payload_from_egress(handle, info)
    try:
        await upsert_recording(body)
    except Exception as exc:
        print(f"[recording] final Directus upsert failed: {exc}", flush=True)


async def refresh_recording_metadata(handle: RecordingHandle) -> bool:
    info = await _list_egress(handle.egress_id)
    if info is None:
        return False
    await upsert_recording(recording_payload_from_egress(handle, info))
    return True


def _recording_row_needs_reconcile(row: dict[str, Any]) -> bool:
    if not row.get("egress_id"):
        return False
    status = str(row.get("status") or "").strip().lower()
    return (
        status in PENDING_RECORDING_STATUSES
        or not row.get("ended_at")
        or not row.get("file_size")
    )


async def reconcile_pending_recordings(limit: int = 200) -> dict[str, int]:
    result = await _directus_get(
        "/items/robot_call_recordings",
        {
            "sort": "-created_at",
            "limit": max(1, min(int(limit), 500)),
            "fields": "id,room_name,session_id,egress_id,status,object_key,started_at,ended_at,file_size",
        },
    )
    rows = result.get("data") if isinstance(result, dict) else []
    summary = {"checked": 0, "updated": 0, "skipped": 0, "missing": 0, "failed": 0}
    for row in rows or []:
        if not _recording_row_needs_reconcile(row):
            summary["skipped"] += 1
            continue
        summary["checked"] += 1
        handle = RecordingHandle(
            egress_id=str(row.get("egress_id") or ""),
            room_name=_first_non_empty(row.get("room_name"), row.get("session_id")),
            object_key=str(row.get("object_key") or ""),
            started_at=_first_non_empty(
                row.get("started_at"), datetime.now(timezone.utc).isoformat()
            ),
        )
        try:
            updated = await refresh_recording_metadata(handle)
            summary["updated" if updated else "missing"] += 1
        except Exception as exc:
            summary["failed"] += 1
            print(
                f"[recording] reconcile failed egress_id={handle.egress_id}: {exc}",
                flush=True,
            )
    return summary
