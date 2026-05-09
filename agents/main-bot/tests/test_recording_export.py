from datetime import datetime, timezone
from types import SimpleNamespace

from livekit import api

import recording_export
from recording_export import RecordingHandle


def test_object_key_sanitizes_room_name(monkeypatch) -> None:
    monkeypatch.setattr(recording_export, "CALL_RECORDING_PREFIX", "livekit")

    key = recording_export._object_key(
        "client/room name",
        datetime(2026, 5, 8, 12, 34, 56, tzinfo=timezone.utc),
    )

    assert key == "livekit/client_room_name/20260508T123456Z.mp3"


def test_recording_payload_keeps_pending_egress_without_end_time() -> None:
    handle = RecordingHandle(
        egress_id="EG_1",
        room_name="room-1",
        object_key="livekit/room-1/recording.mp3",
        started_at="2026-05-08T12:00:00+00:00",
    )
    info = SimpleNamespace(
        egress_id="EG_1",
        room_name="room-1",
        status=api.EgressStatus.EGRESS_ACTIVE,
        error="",
        file_results=[],
    )

    payload = recording_export.recording_payload_from_egress(handle, info)

    assert payload["status"] == "active"
    assert payload["object_key"] == "livekit/room-1/recording.mp3"
    assert "ended_at" not in payload


def test_recording_payload_uses_file_result_metadata() -> None:
    handle = RecordingHandle(
        egress_id="EG_2",
        room_name="room-2",
        object_key="livekit/room-2/recording.mp3",
        started_at="2026-05-08T12:00:00+00:00",
    )
    info = SimpleNamespace(
        egress_id="EG_2",
        room_name="room-2",
        status=api.EgressStatus.EGRESS_COMPLETE,
        error="",
        file_results=[
            SimpleNamespace(
                filename="livekit/room-2/final.mp3",
                filepath="",
                size=12345,
                duration=7_500_000_000,
                ended_at=None,
            )
        ],
    )

    payload = recording_export.recording_payload_from_egress(handle, info)

    assert payload["status"] == "complete"
    assert payload["object_key"] == "livekit/room-2/final.mp3"
    assert payload["file_name"] == "final.mp3"
    assert payload["file_size"] == 12345
    assert payload["duration_sec"] == 7.5
    assert payload["ended_at"]
