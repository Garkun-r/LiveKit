import base64
import hashlib
import hmac
import json

from tbank_auth import VoiceKitAuth, generate_voicekit_jwt


def _decode_segment(segment: str) -> dict:
    raw = segment.encode("utf-8")
    raw += b"=" * (-len(raw) % 4)
    return json.loads(base64.urlsafe_b64decode(raw))


def test_generate_voicekit_jwt_uses_tbank_header_scope_and_hmac_signature() -> None:
    api_key = "test-api-key"
    secret_key = base64.urlsafe_b64encode(b"test-secret").decode("utf-8").rstrip("=")
    token = generate_voicekit_jwt(
        api_key=api_key,
        secret_key=secret_key,
        scope="tinkoff.cloud.stt",
        now=1000,
    )

    header_segment, payload_segment, signature_segment = token.split(".")

    assert _decode_segment(header_segment) == {
        "alg": "HS256",
        "typ": "JWT",
        "kid": api_key,
    }
    payload = _decode_segment(payload_segment)
    assert payload["aud"] == "tinkoff.cloud.stt"
    assert payload["exp"] == 1600

    expected_signature = hmac.new(
        b"test-secret",
        msg=f"{header_segment}.{payload_segment}".encode(),
        digestmod=hashlib.sha256,
    ).digest()
    expected_signature_segment = base64.urlsafe_b64encode(expected_signature).rstrip(
        b"="
    )
    assert signature_segment.encode("utf-8") == expected_signature_segment


def test_voicekit_auth_caches_tokens_per_scope(monkeypatch) -> None:
    secret_key = base64.urlsafe_b64encode(b"test-secret").decode("utf-8").rstrip("=")
    timestamps = iter([1000, 1001, 1002])
    monkeypatch.setattr("tbank_auth.time.time", lambda: next(timestamps))
    auth = VoiceKitAuth(api_key="test-api-key", secret_key=secret_key)

    first = auth.authorization_metadata("tinkoff.cloud.stt")
    second = auth.authorization_metadata("tinkoff.cloud.stt")
    third = auth.authorization_metadata("tinkoff.cloud.tts")

    assert first == second
    assert third != first
    assert first[0][0] == "authorization"
    assert first[0][1].startswith("Bearer ")
