"""Fail-closed API boundary. Offline mode is an explicit test/development opt-in."""
from __future__ import annotations
import base64
import hmac
import logging
import os
import time
from uuid import uuid4
from urllib.parse import urlsplit

from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

log = logging.getLogger(__name__)

# The credential is offered only on /ws/chat; the server echoes only the
# public protocol, never the credential, in the upgrade response.
CHAT_PROTOCOL = "chat.v1"
CHAT_BEARER_PREFIX = "chat.bearer."


def settings():
    mode = os.getenv("API_SECURITY_MODE", "production")
    if mode not in ("production", "offline"):
        raise RuntimeError("API_SECURITY_MODE must be production or offline")
    token = os.getenv("API_TOKEN", "")
    origins = [v.strip() for v in os.getenv("API_CORS_ORIGINS", "").split(",") if v.strip()]
    if mode == "production":
        if not token.strip():
            raise RuntimeError("API_TOKEN is required in production")
        if not origins:
            raise RuntimeError("API_CORS_ORIGINS is required in production")
        if not os.getenv("NEO4J_PASSWORD", "").strip():
            raise RuntimeError("NEO4J_PASSWORD is required in production")
    for origin in origins:
        parsed = urlsplit(origin)
        if (origin == "*" or parsed.scheme not in ("http", "https")
                or not parsed.netloc or parsed.path or parsed.query or parsed.fragment
                or parsed.username or parsed.password or origin.endswith("/")):
            raise RuntimeError("API_CORS_ORIGINS must contain exact HTTP(S) origins")
    return mode, token, origins


def valid_token(header: str, token: str) -> bool:
    scheme, sep, supplied = header.partition(" ")
    return bool(token and sep and scheme.lower() == "bearer"
                and hmac.compare_digest(supplied, token))


def valid_chat_protocol(protocols: list[str], token: str) -> bool:
    credentials = [p for p in protocols if p.startswith(CHAT_BEARER_PREFIX)]
    if protocols.count(CHAT_PROTOCOL) != 1 or len(credentials) != 1 or not token:
        return False
    expected = CHAT_BEARER_PREFIX + base64.urlsafe_b64encode(token.encode("utf-8")).decode("ascii").rstrip("=")
    return hmac.compare_digest(credentials[0], expected)


def allowed_origin(origin: str | None, origins: list[str]) -> bool:
    return origin is None or origin in origins


class SecurityBoundary:
    """Run before CORS and routing, including SPA and websocket endpoints."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        mode, token, origins = settings()
        headers = {k.lower(): v.decode("latin1") for k, v in scope.get("headers", [])}
        origin = headers.get(b"origin")
        if scope["type"] == "websocket":
            protocols = scope.get("subprotocols", [])
            has_chat_credentials = any(p.startswith(CHAT_BEARER_PREFIX) for p in protocols)
            protocol_auth = (scope.get("path") == "/ws/chat"
                             and valid_chat_protocol(protocols, token))
            header_auth = valid_token(headers.get(b"authorization", ""), token)
            if not allowed_origin(origin, origins) or (
                mode != "offline" and (
                    (has_chat_credentials and not protocol_auth)
                    or not (header_auth or protocol_auth))
            ):
                await send({"type": "websocket.close", "code": 1008})
                return
            # Handlers may negotiate only the non-secret protocol.
            if scope.get("path") == "/ws/chat" and CHAT_PROTOCOL in protocols:
                scope.setdefault("state", {})["chat_subprotocol"] = CHAT_PROTOCOL
            return await self.app(scope, receive, send)

        request_id = uuid4().hex  # never trust client-supplied identifiers
        scope.setdefault("state", {})["request_id"] = request_id
        start = time.monotonic()
        status = 500

        async def tracked_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message.setdefault("headers", []).append((b"x-request-id", request_id.encode()))
            await send(message)

        try:
            if not allowed_origin(origin, origins):
                return await JSONResponse({"detail": "Origin not allowed"}, status_code=403)(
                    scope, receive, tracked_send)
            # Preflights are validated by CORS; they do not carry bearer credentials.
            preflight = scope.get("method") == "OPTIONS" and b"access-control-request-method" in headers
            if (mode != "offline" and not preflight
                    and scope.get("path") != "/api/v1/health"
                    and not valid_token(headers.get(b"authorization", ""), token)):
                return await JSONResponse({"detail": "Unauthorized"}, status_code=401)(
                    scope, receive, tracked_send)
            cors = CORSMiddleware(self.app, allow_origins=origins, allow_methods=["*"],
                                  allow_headers=["Authorization", "Content-Type", "X-Request-ID"])
            await cors(scope, receive, tracked_send)
        finally:
            # Structured, bounded, no headers, query strings, paths or bodies.
            log.info("api_request request_id=%s status=%d duration_ms=%d",
                     request_id, status, int((time.monotonic() - start) * 1000))
