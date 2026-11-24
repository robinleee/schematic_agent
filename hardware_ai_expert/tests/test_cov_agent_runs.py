"""Offline tests for the Hermes agent-run proxy router.

Every upstream call goes through ``httpx.MockTransport``; the metrics JSONL is
redirected to ``tmp_path``.  Nothing here touches a live gateway or ``logs/``.
"""
import asyncio
import json
import os
import sys
import time

import httpx
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))                   # hardware_ai_expert/
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))  # repo root

from fastapi.testclient import TestClient  # noqa: E402

from hardware_ai_expert.api.main import app  # noqa: E402
from hardware_ai_expert.api.routers import agent_runs  # noqa: E402

BASE = "/api/v1/agent"
UPSTREAM = "http://hermes.test/p/schematic/v1"
RUN_ID = "run_0123456789abcdef"
_RealAsyncClient = httpx.AsyncClient


class Upstream:
    """Records requests and answers with a test-provided handler."""

    def __init__(self):
        self.requests = []
        self.handler = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.handler is None:
            raise AssertionError(f"unexpected upstream call: {request.url}")
        return self.handler(request)


@pytest.fixture
def upstream(monkeypatch, tmp_path):
    monkeypatch.setenv("API_SECURITY_MODE", "offline")
    monkeypatch.delenv("API_CORS_ORIGINS", raising=False)
    monkeypatch.setenv("HERMES_API_KEY", "test-key")
    monkeypatch.setenv("HERMES_API_BASE", UPSTREAM + "/")
    monkeypatch.setenv("HERMES_BOUND_PROJECT", "legacy")
    monkeypatch.setenv("HERMES_ENGINE_ENABLED", "1")
    monkeypatch.setenv("HERMES_ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setattr(agent_runs, "METRICS_FILE", str(tmp_path / "logs" / "agent_runs.jsonl"))
    monkeypatch.setattr(agent_runs, "_SESSIONS", {})
    monkeypatch.setattr(agent_runs, "_RUNS", {})

    fake = Upstream()

    def client_factory(*args, **kwargs):
        kwargs.pop("transport", None)
        return _RealAsyncClient(transport=httpx.MockTransport(fake), timeout=kwargs.get("timeout"))

    monkeypatch.setattr(agent_runs.httpx, "AsyncClient", client_factory)
    return fake


@pytest.fixture
def client(upstream):
    return TestClient(app)


def read_metrics():
    path = agent_runs.METRICS_FILE
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def write_metrics(rows):
    os.makedirs(os.path.dirname(agent_runs.METRICS_FILE), exist_ok=True)
    with open(agent_runs.METRICS_FILE, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write((row if isinstance(row, str) else json.dumps(row)) + "\n")


# ------------------------------------------------------------------ health
def test_health_upstream_ok(client, upstream):
    upstream.handler = lambda req: httpx.Response(200, json={"data": []})
    body = client.get(BASE + "/health").json()
    assert body == {
        "enabled": True, "upstream": True, "detail": "",
        "bound_project": "legacy", "base_url": UPSTREAM,
    }
    req = upstream.requests[0]
    assert str(req.url) == UPSTREAM + "/models"
    assert req.headers["authorization"] == "Bearer test-key"


def test_health_upstream_error_payload(client, upstream):
    upstream.handler = lambda req: httpx.Response(401, json={"error": "bad key"})
    body = client.get(BASE + "/health").json()
    assert body["upstream"] is False
    assert body["detail"] == "bad key"


def test_health_upstream_error_without_message(client, upstream):
    upstream.handler = lambda req: httpx.Response(500, content=b"")
    body = client.get(BASE + "/health").json()
    assert body["upstream"] is False
    assert body["detail"] == "HTTP 500"


def test_health_connect_error(client, upstream):
    def boom(req):
        raise httpx.ConnectError("refused", request=req)
    upstream.handler = boom
    body = client.get(BASE + "/health").json()
    assert body["upstream"] is False
    assert body["detail"] == "ConnectError"


def test_health_missing_key_reports_detail(client, upstream, monkeypatch):
    monkeypatch.setenv("HERMES_API_KEY", "")
    body = client.get(BASE + "/health").json()
    assert body["upstream"] is False
    assert "HERMES_API_KEY" in body["detail"]
    assert upstream.requests == []


def test_health_disabled_skips_upstream(client, upstream, monkeypatch):
    monkeypatch.setenv("HERMES_ENGINE_ENABLED", "off")
    monkeypatch.setenv("HERMES_BOUND_PROJECT", "  ")
    body = client.get(BASE + "/health").json()
    assert body["enabled"] is False
    assert body["upstream"] is False
    assert body["bound_project"] is None
    assert upstream.requests == []


# ------------------------------------------------------------------ create run
def test_create_run_success_forwards_body_and_remembers_run(client, upstream):
    upstream.handler = lambda req: httpx.Response(200, json={"run_id": RUN_ID, "status": "started"})
    resp = client.post(BASE + "/runs", json={
        "input": "check pullups", "session_id": "conv-1", "user_id": "alice",
        "project_id": "legacy", "model": "m1",
    })
    assert resp.status_code == 200
    assert resp.json() == {"run_id": RUN_ID, "status": "started"}
    sent = json.loads(upstream.requests[0].content)
    assert sent == {"input": "check pullups", "session_id": "alice:legacy:conv-1", "model": "m1"}
    assert str(upstream.requests[0].url) == UPSTREAM + "/runs"
    assert agent_runs._run_meta(RUN_ID)["project_id"] == "legacy"
    assert agent_runs._run_meta(RUN_ID)["conversation"] == "conv-1"


def test_create_run_session_key_sanitises_identifiers(client, upstream):
    upstream.handler = lambda req: httpx.Response(200, json={"ok": True})
    resp = client.post(BASE + "/runs", json={"input": "hi", "session_id": "bad id!", "user_id": "a b"})
    assert resp.status_code == 200
    key = json.loads(upstream.requests[0].content)["session_id"]
    user, project, conversation = key.split(":")
    assert user == "web" and project == "all"
    assert conversation != "bad id!" and len(conversation) == 32
    assert "model" not in json.loads(upstream.requests[0].content)
    # no run_id in the payload: nothing remembered
    assert agent_runs._RUNS == {}


def test_create_run_disabled_returns_503(client, upstream, monkeypatch):
    monkeypatch.setenv("HERMES_ENGINE_ENABLED", "0")
    resp = client.post(BASE + "/runs", json={"input": "hi"})
    assert resp.status_code == 503
    assert "HERMES_ENGINE_ENABLED" in resp.json()["detail"]


def test_create_run_wrong_project_returns_409(client, upstream):
    resp = client.post(BASE + "/runs", json={"input": "hi", "project_id": "other"})
    assert resp.status_code == 409
    assert "legacy" in resp.json()["detail"]
    assert upstream.requests == []


def test_create_run_unbound_deployment_accepts_any_project(client, upstream, monkeypatch):
    monkeypatch.setenv("HERMES_BOUND_PROJECT", "")
    upstream.handler = lambda req: httpx.Response(200, json={"run_id": RUN_ID})
    resp = client.post(BASE + "/runs", json={"input": "hi", "project_id": "board-a"})
    assert resp.status_code == 200


def test_create_run_session_cannot_switch_project(client, upstream, monkeypatch):
    monkeypatch.setenv("HERMES_BOUND_PROJECT", "")
    upstream.handler = lambda req: httpx.Response(200, json={"run_id": RUN_ID})
    first = client.post(BASE + "/runs", json={"input": "a", "session_id": "s1", "project_id": "p1"})
    assert first.status_code == 200
    again = client.post(BASE + "/runs", json={"input": "b", "session_id": "s1", "project_id": "p1"})
    assert again.status_code == 200
    switched = client.post(BASE + "/runs", json={"input": "c", "session_id": "s1", "project_id": "p2"})
    assert switched.status_code == 409
    assert "p1" in switched.json()["detail"] and "p2" in switched.json()["detail"]
    to_all = client.post(BASE + "/runs", json={"input": "c", "session_id": "s1"})
    assert to_all.status_code == 409
    assert "(全库)" in to_all.json()["detail"]
    assert len(upstream.requests) == 2


def test_create_run_missing_key_returns_503(client, upstream, monkeypatch):
    monkeypatch.setenv("HERMES_API_KEY", "")
    resp = client.post(BASE + "/runs", json={"input": "hi"})
    assert resp.status_code == 503
    assert upstream.requests == []


def test_create_run_key_from_env_file(client, upstream, monkeypatch, tmp_path):
    env_file = tmp_path / "hermes.env"
    env_file.write_text("OTHER=1\nAPI_SERVER_KEY= file-key \n", encoding="utf-8")
    monkeypatch.setenv("HERMES_API_KEY", "")
    monkeypatch.setenv("HERMES_ENV_FILE", str(env_file))
    upstream.handler = lambda req: httpx.Response(200, json={})
    assert client.post(BASE + "/runs", json={"input": "hi"}).status_code == 200
    assert upstream.requests[0].headers["authorization"] == "Bearer file-key"


def test_env_file_without_key_returns_empty(monkeypatch, tmp_path):
    env_file = tmp_path / "hermes.env"
    env_file.write_text("FOO=bar\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_ENV_FILE", str(env_file))
    assert agent_runs._env_file_key() == ""


def test_create_run_upstream_error_status_passthrough(client, upstream):
    upstream.handler = lambda req: httpx.Response(429, json={"error": "busy"})
    resp = client.post(BASE + "/runs", json={"input": "hi"})
    assert resp.status_code == 429
    assert resp.json() == {"error": "busy"}


def test_create_run_upstream_non_json_body(client, upstream):
    upstream.handler = lambda req: httpx.Response(500, content=b"<html>oops</html>")
    resp = client.post(BASE + "/runs", json={"input": "hi"})
    assert resp.status_code == 500
    assert resp.json() == {"error": "<html>oops</html>"}


def test_create_run_transport_error_returns_502(client, upstream):
    def boom(req):
        raise httpx.ReadTimeout("slow", request=req)
    upstream.handler = boom
    resp = client.post(BASE + "/runs", json={"input": "hi"})
    assert resp.status_code == 502
    assert "ReadTimeout" in resp.json()["detail"]


def test_create_run_rejects_empty_input(client, upstream):
    assert client.post(BASE + "/runs", json={"input": ""}).status_code == 422


# ------------------------------------------------------------------ run_id validation
@pytest.mark.parametrize("method,suffix,body", [
    ("get", "", None),
    ("post", "/stop", None),
    ("post", "/approval", {"choice": "once"}),
    ("get", "/events", None),
])
@pytest.mark.parametrize("bad_id", ["run_XYZ", "run_123", "abc_0123456789"])
def test_invalid_run_id_returns_400(client, upstream, method, suffix, body, bad_id):
    url = f"{BASE}/runs/{bad_id}{suffix}"
    resp = client.get(url) if method == "get" else client.post(url, json=body)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "非法的 run_id"
    assert upstream.requests == []


# ------------------------------------------------------------------ approval / stop / status
def test_approval_forwards_choice_request_and_scope(client, upstream):
    upstream.handler = lambda req: httpx.Response(200, json={"accepted": True})
    resp = client.post(f"{BASE}/runs/{RUN_ID}/approval",
                       json={"choice": "session", "request_id": "req-1", "scope": "tool"})
    assert resp.status_code == 200
    assert resp.json() == {"accepted": True}
    req = upstream.requests[0]
    assert str(req.url) == f"{UPSTREAM}/runs/{RUN_ID}/approval"
    assert json.loads(req.content) == {"choice": "session", "request_id": "req-1", "scope": "tool"}


def test_approval_minimal_body(client, upstream):
    upstream.handler = lambda req: httpx.Response(200, json={})
    client.post(f"{BASE}/runs/{RUN_ID}/approval", json={"choice": "deny"})
    assert json.loads(upstream.requests[0].content) == {"choice": "deny"}


def test_approval_requires_choice_field(client, upstream):
    assert client.post(f"{BASE}/runs/{RUN_ID}/approval", json={}).status_code == 422
    assert upstream.requests == []


def test_approval_unknown_choice_is_left_to_upstream(client, upstream):
    """The proxy does not whitelist choices; the gateway's rejection is relayed."""
    upstream.handler = lambda req: httpx.Response(400, json={"error": "invalid choice"})
    resp = client.post(f"{BASE}/runs/{RUN_ID}/approval", json={"choice": "yolo"})
    assert resp.status_code == 400
    assert resp.json() == {"error": "invalid choice"}
    assert json.loads(upstream.requests[0].content)["choice"] == "yolo"


def test_approval_transport_error_returns_502(client, upstream):
    def boom(req):
        raise httpx.ConnectError("down", request=req)
    upstream.handler = boom
    resp = client.post(f"{BASE}/runs/{RUN_ID}/approval", json={"choice": "once"})
    assert resp.status_code == 502


def test_approval_missing_key_returns_503(client, upstream, monkeypatch):
    monkeypatch.setenv("HERMES_API_KEY", "")
    resp = client.post(f"{BASE}/runs/{RUN_ID}/approval", json={"choice": "once"})
    assert resp.status_code == 503


@pytest.mark.parametrize("status,payload", [(200, {"stopped": True}), (404, {"error": "no run"})])
def test_stop_run(client, upstream, status, payload):
    upstream.handler = lambda req: httpx.Response(status, json=payload)
    resp = client.post(f"{BASE}/runs/{RUN_ID}/stop")
    assert resp.status_code == status
    assert resp.json() == payload
    assert upstream.requests[0].method == "POST"
    assert str(upstream.requests[0].url) == f"{UPSTREAM}/runs/{RUN_ID}/stop"


def test_stop_run_transport_error(client, upstream):
    def boom(req):
        raise httpx.ConnectError("down", request=req)
    upstream.handler = boom
    assert client.post(f"{BASE}/runs/{RUN_ID}/stop").status_code == 502


@pytest.mark.parametrize("status,payload", [(200, {"status": "running"}), (404, {"error": "gone"})])
def test_get_run(client, upstream, status, payload):
    upstream.handler = lambda req: httpx.Response(status, json=payload)
    resp = client.get(f"{BASE}/runs/{RUN_ID}")
    assert resp.status_code == status
    assert resp.json() == payload
    assert upstream.requests[0].method == "GET"


def test_get_run_transport_error(client, upstream):
    def boom(req):
        raise httpx.ConnectError("down", request=req)
    upstream.handler = boom
    resp = client.get(f"{BASE}/runs/{RUN_ID}")
    assert resp.status_code == 502
    assert "ConnectError" in resp.json()["detail"]


# ------------------------------------------------------------------ SSE relay
class _ChunkStream(httpx.AsyncByteStream):
    """Unread upstream body delivered in pieces (as a real SSE socket would)."""

    def __init__(self, chunks):
        self._chunks = chunks

    async def __aiter__(self):
        for chunk in self._chunks:
            yield chunk


def _stream_response(body, size=17):
    chunks = [b""] + [body[i:i + size] for i in range(0, len(body), size)]
    return httpx.Response(200, stream=_ChunkStream(chunks),
                          headers={"content-type": "text/event-stream"})


def _sse(*events):
    out = b""
    for name, data in events:
        out += f"event: {name}\ndata: {json.dumps(data)}\n\n".encode()
    return out


def test_events_relay_and_trace_metrics(client, upstream):
    agent_runs._remember_run(RUN_ID, "legacy", "conv")
    body = _sse(
        ("message.delta", {"text": "hi"}),
        ("tool.started", {"tool": "query_graph"}),
        ("tool.started", {"tool": "review"}),
        ("approval.request", {"request_id": "r1"}),
        ("approval.responded", {"request_id": "r1", "choice": "once"}),
        ("run.completed", {}),
    )
    upstream.handler = lambda req: _stream_response(body)
    resp = client.get(f"{BASE}/runs/{RUN_ID}/events", params={"last_seq": 7})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.headers["cache-control"] == "no-cache, no-transform"
    assert resp.content == body
    req = upstream.requests[0]
    assert str(req.url) == f"{UPSTREAM}/runs/{RUN_ID}/events?last_seq=7"
    assert req.headers["accept"] == "text/event-stream"

    runs = [r for r in read_metrics() if r["kind"] == "run"]
    assert len(runs) == 1
    rec = runs[0]
    assert rec["engine"] == "hermes" and rec["source"] == "sse"
    assert rec["status"] == "completed"
    assert rec["tools"] == 2 and rec["approvals"] == 1
    assert rec["choices"] == ["once"]
    assert rec["project_id"] == "legacy" and rec["run_id"] == RUN_ID


def test_events_client_disconnect_records_stream_closed(client, upstream):
    upstream.handler = lambda req: _stream_response(_sse(("message.delta", {"t": 1})))
    resp = client.get(f"{BASE}/runs/{RUN_ID}/events", params={"last_seq": 0})
    assert resp.status_code == 200
    assert "last_seq" not in str(upstream.requests[0].url)
    runs = [r for r in read_metrics() if r["kind"] == "run"]
    assert [r["status"] for r in runs] == ["stream_closed"]
    assert runs[0]["project_id"] is None


def test_events_upstream_error_status(client, upstream):
    upstream.handler = lambda req: httpx.Response(404, json={"error": "unknown run"})
    resp = client.get(f"{BASE}/runs/{RUN_ID}/events")
    assert resp.status_code == 404
    assert resp.json() == {"error": "unknown run"}
    assert read_metrics() == []


def test_events_transport_error_returns_502(client, upstream):
    def boom(req):
        raise httpx.ConnectError("down", request=req)
    upstream.handler = boom
    resp = client.get(f"{BASE}/runs/{RUN_ID}/events")
    assert resp.status_code == 502


def test_events_missing_key_returns_503(client, upstream, monkeypatch):
    monkeypatch.setenv("HERMES_API_KEY", "")
    assert client.get(f"{BASE}/runs/{RUN_ID}/events").status_code == 503


# ------------------------------------------------------------------ parsing / trace units
def test_parse_event_variants():
    assert agent_runs._parse_event(b"event: tool.started\ndata: {\"a\": 1}") == {"a": 1, "event": "tool.started"}
    assert agent_runs._parse_event(b"event: x\ndata: {\"event\": \"y\"}") == {"event": "y"}
    assert agent_runs._parse_event(b"event: run.failed\ndata: not-json") == {"event": "run.failed"}
    assert agent_runs._parse_event(b": comment only") == {}
    assert agent_runs._parse_event(b"data: {\"a\":\ndata: 2}") == {"a": 2}


def test_run_trace_failure_and_finish_idempotent(upstream):
    trace = agent_runs.RunTrace(RUN_ID, "legacy")
    trace.consume(b"event: run.failed\ndata: {}")
    trace.consume(b"event: run.completed\ndata: {}")  # already finished: no second record
    trace.finish()
    runs = read_metrics()
    assert len(runs) == 1 and runs[0]["status"] == "failed"
    # responded without a choice / unknown request id is harmless
    trace2 = agent_runs.RunTrace(RUN_ID, None)
    trace2.consume(b"event: approval.responded\ndata: {\"request_id\": \"nope\"}")
    assert trace2.choices == []


def test_auto_deny_records_timeout_and_posts_deny(upstream, monkeypatch):
    monkeypatch.setattr(agent_runs, "APPROVAL_TIMEOUT", 0)
    upstream.handler = lambda req: httpx.Response(200, json={})

    async def scenario():
        trace = agent_runs.RunTrace(RUN_ID, "legacy")
        trace.consume(b"event: approval.request\ndata: {\"request_id\": \"r9\"}")
        assert "r9" in trace.watchdogs
        await asyncio.wait_for(trace.watchdogs["r9"], timeout=5)
        return trace

    trace = asyncio.run(scenario())
    assert trace.choices == ["auto_deny"]
    timeouts = [r for r in read_metrics() if r["kind"] == "approval_timeout"]
    assert timeouts and timeouts[0]["request_id"] == "r9" and timeouts[0]["timeout_s"] == 0
    req = upstream.requests[0]
    assert str(req.url) == f"{UPSTREAM}/runs/{RUN_ID}/approval"
    assert json.loads(req.content) == {"choice": "deny", "request_id": "r9"}


def test_auto_deny_swallows_upstream_failure(upstream, monkeypatch):
    monkeypatch.setattr(agent_runs, "APPROVAL_TIMEOUT", 0)

    def boom(req):
        raise httpx.ConnectError("down", request=req)
    upstream.handler = boom

    async def scenario():
        trace = agent_runs.RunTrace(RUN_ID, None)
        await trace._auto_deny("r1")
        return trace

    assert asyncio.run(scenario()).choices == ["auto_deny"]


def test_approval_response_cancels_watchdog(upstream):
    async def scenario():
        trace = agent_runs.RunTrace(RUN_ID, None)
        trace.consume(b"event: approval.request\ndata: {\"request_id\": \"r1\"}")
        task = trace.watchdogs["r1"]
        trace.consume(b"event: approval.responded\ndata: {\"request_id\": \"r1\", \"choice\": \"always\"}")
        await asyncio.sleep(0)
        return trace, task

    trace, task = asyncio.run(scenario())
    assert task.cancelled()
    assert trace.choices == ["always"]
    assert trace.watchdogs == {}


def test_record_metrics_never_raises(monkeypatch, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setattr(agent_runs, "METRICS_FILE", str(blocker / "sub" / "m.jsonl"))
    agent_runs._record_metrics({"kind": "run"})  # makedirs fails under a file: swallowed


def test_record_engine_run_schema(upstream):
    agent_runs.record_engine_run("legacy", "success", 1.234, tools=2, approvals=None,
                                 choices=("once",), project_id="p", run_id="r", source="chat")
    agent_runs.record_engine_run("legacy", "error", 0)
    rows = read_metrics()
    assert rows[0]["duration_s"] == 1.23 and rows[0]["tools"] == 2 and rows[0]["approvals"] == 0
    assert rows[0]["choices"] == ["once"] and rows[0]["run_id"] == "r" and rows[0]["source"] == "chat"
    assert "run_id" not in rows[1] and "source" not in rows[1]
    assert all("ts" in r for r in rows)


# ------------------------------------------------------------------ session / run bookkeeping
def test_bind_session_empty_id_is_noop(upstream):
    agent_runs._bind_session("", "p")
    assert agent_runs._SESSIONS == {}


def test_bind_session_expired_binding_can_rebind(upstream, monkeypatch):
    monkeypatch.setattr(agent_runs, "_SESSION_TTL", 10.0)
    agent_runs._SESSIONS["s"] = {"project_id": "p1", "ts": time.time() - 100}
    agent_runs._bind_session("s", "p2")
    assert agent_runs._SESSIONS["s"]["project_id"] == "p2"


def test_prune_sessions_drops_expired_then_oldest(upstream, monkeypatch):
    monkeypatch.setattr(agent_runs, "_MAX_SESSIONS", 4)
    monkeypatch.setattr(agent_runs, "_SESSION_TTL", 50.0)
    now = 1000.0
    agent_runs._SESSIONS.update({
        "old": {"project_id": None, "ts": now - 100},
        "a": {"project_id": None, "ts": now - 3},
        "b": {"project_id": None, "ts": now - 2},
        "c": {"project_id": None, "ts": now - 1},
    })
    agent_runs._prune_sessions(now)
    assert set(agent_runs._SESSIONS) == {"a", "b", "c"}
    agent_runs._SESSIONS["d"] = {"project_id": None, "ts": now}
    agent_runs._prune_sessions(now)  # still full, nothing expired: oldest half dropped
    assert set(agent_runs._SESSIONS) == {"c", "d"}
    agent_runs._prune_sessions(now)  # below the cap: untouched
    assert set(agent_runs._SESSIONS) == {"c", "d"}


def test_remember_run_evicts_oldest_quarter(upstream, monkeypatch):
    monkeypatch.setattr(agent_runs, "_MAX_RUNS", 4)
    for i in range(4):
        agent_runs._remember_run(f"r{i}", None, "c")
    agent_runs._remember_run("r4", "p", "c")
    assert list(agent_runs._RUNS) == ["r1", "r2", "r3", "r4"]
    assert agent_runs._run_meta("missing") == {}


# ------------------------------------------------------------------ telemetry / metrics
def test_telemetry_is_recorded(client, upstream):
    resp = client.post(BASE + "/telemetry", json={"event": "fallback.legacy", "project_id": "legacy"})
    assert resp.status_code == 200 and resp.json() == {"ok": True}
    rows = read_metrics()
    assert rows[0]["kind"] == "telemetry" and rows[0]["event"] == "fallback.legacy"
    assert rows[0]["detail"] == "" and rows[0]["run_id"] is None


def test_telemetry_rejects_oversized_event(client, upstream):
    assert client.post(BASE + "/telemetry", json={"event": "x" * 65}).status_code == 422


def test_metrics_summary_empty_window(client, upstream):
    body = client.get(BASE + "/metrics/summary").json()
    assert body["runs"] == 0 and body["success_rate"] == 0.0
    assert body["by_engine"] == {} and body["acceptance"]["comparable"] is False
    assert body["duration_p95_s"] == 0.0 and body["tools_avg"] == 0.0
    assert body["metrics_file"] == agent_runs.METRICS_FILE


def test_metrics_summary_aggregates(client, upstream):
    now = time.time()
    rows = []
    for d in (1.0, 2.0, 3.0, 4.0):
        rows.append({"kind": "run", "engine": "legacy", "status": "success", "duration_s": d,
                     "tools": 1, "approvals": 0, "ts": now})
    rows.append({"kind": "run", "engine": "legacy", "status": "error", "duration_s": 9.0, "ts": now})
    rows.append({"kind": "run", "run_id": "run_x", "status": "completed", "duration_s": 5.0,
                 "tools": 3, "approvals": 2, "choices": ["once", "deny"], "ts": now})
    rows.append({"kind": "run", "engine": "hermes", "status": "stream_closed", "duration_s": 50.0, "ts": now})
    rows.append({"kind": "run", "status": None, "ts": now})
    rows.append({"kind": "approval_timeout", "ts": now})
    rows.append({"kind": "telemetry", "event": "fallback.classic", "ts": now})
    rows.append({"kind": "telemetry", "event": "render_error", "ts": now})
    rows.append({"kind": "run", "engine": "legacy", "status": "success", "duration_s": 1.0})  # no ts
    rows.append({"kind": "run", "engine": "legacy", "status": "success", "ts": now - 30 * 86400})
    rows.append("not json")
    rows.append("")
    write_metrics(rows)

    body = client.get(BASE + "/metrics/summary", params={"days": 7}).json()
    assert body["runs"] == 8
    assert body["completed"] == 5
    assert body["success_rate"] == round(5 / 8, 4)
    assert body["skipped_no_ts"] == 1 and body["skipped_out_of_window"] == 1
    assert body["approval_timeouts"] == 1
    assert body["fallbacks"] == {"fallback.classic": 1} and body["fallback_total"] == 1
    assert body["approval_choices"] == {"once": 1, "deny": 1}
    assert body["approvals"] == 2
    assert body["by_status"]["unknown"] == 1

    legacy = body["by_engine"]["legacy"]
    assert legacy["runs"] == 5 and legacy["completed"] == 4 and legacy["failed"] == 1
    assert legacy["duration_p95_s"] == 4.0          # successful runs only
    assert legacy["duration_p95_all_s"] == 9.0
    hermes = body["by_engine"]["hermes"]
    assert hermes["runs"] == 2 and hermes["completed"] == 1 and hermes["stream_closed"] == 1
    assert hermes["duration_p50_s"] == 5.0
    assert body["by_engine"]["unknown"]["runs"] == 1

    acc = body["acceptance"]
    assert acc["comparable"] is True and acc["sample_sufficient"] is False
    assert acc["legacy_p95_s"] == 4.0 and acc["hermes_p95_s"] == 5.0
    assert acc["p95_ratio"] == 1.25 and acc["p95_within_1_5x"] is True
    assert acc["success_rate_not_worse"] is False


def test_metrics_summary_zero_legacy_latency(client, upstream):
    now = time.time()
    write_metrics([
        {"kind": "run", "engine": "legacy", "status": "error", "duration_s": 1.0, "ts": now},
        {"kind": "run", "engine": "hermes", "status": "completed", "duration_s": 2.0, "ts": now},
    ])
    acc = client.get(BASE + "/metrics/summary").json()["acceptance"]
    assert acc["legacy_p95_s"] == 0.0
    assert acc["p95_ratio"] is None and acc["p95_within_1_5x"] is False
    assert acc["success_rate_not_worse"] is True


def test_percentile_helper():
    assert agent_runs._percentile([], 0.95) == 0.0
    assert agent_runs._percentile([3.0, 1.0, 2.0], 0.5) == 2.0
    assert agent_runs._percentile([1.234], 0.95) == 1.23
