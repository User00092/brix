from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time


class RemoteAccessTokens:
    def __init__(self, secret: str, ttl_seconds: int = 300) -> None:
        if len(secret) < 32:
            raise ValueError("BRIX_SECRET_KEY must be at least 32 characters")
        self.secret = secret.encode()
        self.ttl_seconds = ttl_seconds

    def create(self, session_id: str) -> tuple[str, int]:
        expires = int(time.time()) + self.ttl_seconds
        payload = base64.urlsafe_b64encode(json.dumps({"sid": session_id, "exp": expires}, separators=(",", ":")).encode()).decode().rstrip("=")
        signature = hmac.new(self.secret, payload.encode(), hashlib.sha256).hexdigest()
        return f"{payload}.{signature}", expires

    def verify(self, token: str, session_id: str) -> bool:
        try:
            payload, signature = token.rsplit(".", 1)
            expected = hmac.new(self.secret, payload.encode(), hashlib.sha256).hexdigest()
            raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
            data = json.loads(raw)
            return hmac.compare_digest(signature, expected) and data["sid"] == session_id and int(data["exp"]) >= int(time.time())
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            return False

