"""Task 14: offline boundary tests; never access live services."""
import io
import asyncio
import base64

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from hardware_ai_expert.api.main import app
from hardware_ai_expert.api.security import settings
from hardware_ai_expert.api.services.uploads import stage, ETL_LIMIT
from fastapi import UploadFile, HTTPException


@pytest.mark.parametrize("origin", [
    "*", "https://allowed.example/", "https://user:password@allowed.example",
    "https://allowed.example/path", "https://allowed.example?x=1",
    "file://allowed.example", "https://allowed.example#fragment",
])
def test_cors_settings_reject_non_exact_origins(monkeypatch, origin):
    monkeypatch.setenv("API_SECURITY_MODE", "offline")
    monkeypatch.setenv("API_CORS_ORIGINS", origin)
    with pytest.raises(RuntimeError, match="exact HTTP"):
        settings()


def test_bearer_validation_rejects_lookalikes_and_blank_token():
    from hardware_ai_expert.api.security import valid_token
    assert valid_token("Bearer secret", "secret")
    for header in ("Bearer secret ", "Bearer secret-extra", "Basic secret",
                   "Bearer", "Bearer SECRET", "Bearer  secret"):
        assert not valid_token(header, "secret")
    assert not valid_token("Bearer secret", "")


@pytest.fixture
def secured(monkeypatch):
    monkeypatch.setenv("API_SECURITY_MODE", "production")
    monkeypatch.setenv("API_TOKEN", "test-only-token")
    monkeypatch.setenv("API_CORS_ORIGINS", "https://allowed.example")
    monkeypatch.setenv("NEO4J_PASSWORD", "test-only-password")
    with TestClient(app) as client:
        yield client


def test_auth_origin_preflight_and_health(secured):
    assert secured.get("/api/v1/health").status_code == 200
    denied = secured.get("/api/v1/system/status")
    assert denied.status_code == 401 and denied.headers["x-request-id"]
    assert secured.get("/api/v1/health", headers={"Origin": "https://evil.example"}).status_code == 403
    assert secured.get("/api/v1/health", headers={"Origin": "https://allowed.example"}).headers[
        "access-control-allow-origin"] == "https://allowed.example"
    assert secured.options("/api/v1/system/status", headers={
        "Origin": "https://allowed.example", "Access-Control-Request-Method": "GET"
    }).status_code == 200
    assert secured.get("/api/v1/etl/progress/missing", headers={
        "Authorization": "Bearer test-only-token"}).status_code == 404


def test_ws_rejects_unauthenticated_and_bad_origin(secured):
    with pytest.raises(WebSocketDisconnect):
        with secured.websocket_connect("/ws/chat"):
            pass
    with pytest.raises(WebSocketDisconnect):
        with secured.websocket_connect("/ws/chat", headers={
            "Authorization": "Bearer test-only-token", "Origin": "https://evil.example"}):
            pass
    with secured.websocket_connect("/ws/chat", headers={
        "Authorization": "Bearer test-only-token", "Origin": "https://allowed.example"}) as ws:
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"


def test_ws_browser_subprotocol_auth_and_no_credential_echo(secured, caplog):
    credential = "chat.bearer." + base64.urlsafe_b64encode(
        b"test-only-token").decode("ascii").rstrip("=")
    with secured.websocket_connect("/ws/chat", subprotocols=[
        "chat.v1", credential], headers={"Origin": "https://allowed.example"}) as ws:
        assert ws.accepted_subprotocol == "chat.v1"
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}
    assert credential not in caplog.text

    for protocols in (
        ["chat.v1"],
        [credential],
        ["chat.v1", "chat.bearer.invalid"],
        ["chat.v1", credential, "chat.bearer.invalid"],
        ["chat.v1", "chat.v1", credential],
    ):
        with pytest.raises(WebSocketDisconnect):
            with secured.websocket_connect("/ws/chat", subprotocols=protocols):
                pass
    with pytest.raises(WebSocketDisconnect):
        with secured.websocket_connect("/ws/chat", subprotocols=["chat.v1", credential],
                                       headers={"Origin": "https://evil.example"}):
            pass
    # An invalid offered credential must not be rescued by a valid header.
    with pytest.raises(WebSocketDisconnect):
        with secured.websocket_connect("/ws/chat", subprotocols=["chat.v1", "chat.bearer.invalid"],
                                       headers={"Authorization": "Bearer test-only-token"}):
            pass
    assert credential not in caplog.text


def test_ws_subprotocol_is_not_http_auth(secured):
    credential = "chat.bearer." + base64.urlsafe_b64encode(
        b"test-only-token").decode("ascii").rstrip("=")
    assert secured.get("/api/v1/system/status", headers={
        "Sec-WebSocket-Protocol": f"chat.v1, {credential}"}).status_code == 401


def test_ws_offline_still_allows_no_credentials(monkeypatch):
    monkeypatch.setenv("API_SECURITY_MODE", "offline")
    monkeypatch.setenv("API_CORS_ORIGINS", "https://allowed.example")
    with TestClient(app) as client:
        with client.websocket_connect("/ws/chat", subprotocols=["chat.v1"]) as ws:
            assert ws.accepted_subprotocol == "chat.v1"
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/chat", headers={
                "Origin": "https://evil.example"}):
                pass


def test_upload_path_and_oversize(monkeypatch, tmp_path):
    monkeypatch.setenv("UPLOAD_STAGING_DIR", str(tmp_path / "uploads"))
    upload = UploadFile(filename="../../outside.dat", file=io.BytesIO(b"abc"))
    path = asyncio.run(stage(upload, {".dat"}, ETL_LIMIT))
    assert path.startswith(str(tmp_path / "uploads"))
    assert ".." not in path
    from hardware_ai_expert.api.services.uploads import cleanup
    cleanup([path])
    upload = UploadFile(filename="../../outside.dat", file=io.BytesIO(b"x" * (ETL_LIMIT + 1)))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(stage(upload, {".dat"}, ETL_LIMIT))
    assert exc.value.status_code == 413
    assert list((tmp_path / "uploads").rglob("hardware-upload-*")) == []


def test_credential_startup(monkeypatch):
    monkeypatch.setenv("API_SECURITY_MODE", "production")
    monkeypatch.setenv("API_TOKEN", "token")
    monkeypatch.setenv("API_CORS_ORIGINS", "https://allowed.example")
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="NEO4J_PASSWORD"):
        with TestClient(app):
            pass
    monkeypatch.setenv("API_SECURITY_MODE", "offline")
    assert settings()[0] == "offline"
