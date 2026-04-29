from __future__ import annotations

import base64
import copy
import hmac
import json
import time
from dataclasses import dataclass

_DEFAULT_TOKEN_TTL_SEC = 600
_TOKEN_REFRESH_SKEW_SEC = 60


def _urlsafe_b64encode(data: bytes) -> bytes:
    return base64.urlsafe_b64encode(data).rstrip(b"=")


def _urlsafe_b64decode(data: str) -> bytes:
    raw = data.strip().encode("utf-8")
    padding = b"=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw + padding)


def generate_voicekit_jwt(
    *,
    api_key: str,
    secret_key: str,
    scope: str,
    expires_in: int = _DEFAULT_TOKEN_TTL_SEC,
    now: int | None = None,
    payload: dict[str, object] | None = None,
) -> str:
    """Generate T-Bank VoiceKit HS256 JWT.

    The T-Bank examples use the API key as JWT `kid`, the requested VoiceKit
    scope as `aud`, and sign with the base64url-decoded secret key.
    """

    issued_at = int(time.time() if now is None else now)
    header = {
        "alg": "HS256",
        "typ": "JWT",
        "kid": api_key,
    }
    jwt_payload = copy.deepcopy(payload) if payload is not None else {}
    jwt_payload.setdefault("iss", "livekit-agent")
    jwt_payload.setdefault("sub", "livekit-agent")
    jwt_payload["aud"] = scope
    jwt_payload["exp"] = issued_at + expires_in

    header_bytes = json.dumps(header, separators=(",", ":")).encode("utf-8")
    payload_bytes = json.dumps(jwt_payload, separators=(",", ":")).encode("utf-8")
    signing_input = _urlsafe_b64encode(header_bytes) + b"." + _urlsafe_b64encode(
        payload_bytes
    )
    signature = hmac.new(
        _urlsafe_b64decode(secret_key),
        msg=signing_input,
        digestmod="sha256",
    )
    return (
        signing_input + b"." + _urlsafe_b64encode(signature.digest())
    ).decode("utf-8")


@dataclass
class _CachedToken:
    token: str
    expires_at: int


class VoiceKitAuth:
    def __init__(
        self,
        *,
        api_key: str,
        secret_key: str,
        token_ttl_sec: int = _DEFAULT_TOKEN_TTL_SEC,
    ) -> None:
        self._api_key = api_key
        self._secret_key = secret_key
        self._token_ttl_sec = token_ttl_sec
        self._cache: dict[str, _CachedToken] = {}

    def authorization_metadata(self, scope: str) -> tuple[tuple[str, str], ...]:
        token = self._token_for_scope(scope)
        return (("authorization", f"Bearer {token}"),)

    def _token_for_scope(self, scope: str) -> str:
        now = int(time.time())
        cached = self._cache.get(scope)
        if cached is not None and cached.expires_at - _TOKEN_REFRESH_SKEW_SEC > now:
            return cached.token

        token = generate_voicekit_jwt(
            api_key=self._api_key,
            secret_key=self._secret_key,
            scope=scope,
            expires_in=self._token_ttl_sec,
            now=now,
        )
        self._cache[scope] = _CachedToken(
            token=token,
            expires_at=now + self._token_ttl_sec,
        )
        return token
