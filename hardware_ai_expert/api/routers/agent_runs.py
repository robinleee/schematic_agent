"""Hermes Agent 运行代理（HTTP + SSE 透传）。

产品前端不直连 Hermes 网关：网关密钥只留在服务端，前端沿用「HTTP + SSE」范式。

    POST /api/v1/agent/runs                     创建一次 run
    GET  /api/v1/agent/runs/{run_id}/events     SSE 事件流（message.delta / tool.* / approval.request）
    POST /api/v1/agent/runs/{run_id}/approval   提交审批决定（once / session / always / deny）
    GET  /api/v1/agent/runs/{run_id}            查询状态

灰度阶段：本路由与既有 `/api/v1/chat`、`/ws/chat` 并存，前端可自行选择引擎。
"""
import os
import re
import threading
import time
import uuid
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/agent", tags=["agent"])

RUN_ID_RE = re.compile(r"^run_[0-9a-f]{8,64}$")
IDENT_RE = re.compile(r"^[\w.\-]{1,64}$")
DEFAULT_BASE = "http://127.0.0.1:8642/p/schematic/v1"
DEFAULT_ENV_FILE = "/data/hermes/profiles/schematic/.env"
# 上游 SSE 可能长时间静默（模型思考），read 超时给足；连接超时要短。
_TIMEOUT = httpx.Timeout(connect=10.0, read=600.0, write=30.0, pool=10.0)

# 会话 → 项目 绑定（一会话一项目）。进程内存储：单 worker 部署足够；
# 多 worker / 多副本部署需换成 Redis 或库表。
_SESSIONS: Dict[str, Dict[str, Any]] = {}
_SESSIONS_LOCK = threading.Lock()
_SESSION_TTL = float(os.getenv("HERMES_SESSION_TTL", "86400"))
_MAX_SESSIONS = 2000


def _engine_enabled() -> bool:
    return os.getenv("HERMES_ENGINE_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")


def _prune_sessions(now: float) -> None:
    if len(_SESSIONS) < _MAX_SESSIONS:
        return
    for key, item in list(_SESSIONS.items()):
        if now - item["ts"] > _SESSION_TTL:
            _SESSIONS.pop(key, None)
    if len(_SESSIONS) >= _MAX_SESSIONS:  # 仍然太满：丢最旧的一半
        for key, _ in sorted(_SESSIONS.items(), key=lambda kv: kv[1]["ts"])[: _MAX_SESSIONS // 2]:
            _SESSIONS.pop(key, None)


def _bind_session(session_id: str, project_id: Optional[str]) -> None:
    """同一会话不允许跨项目；首次请求绑定，后续不一致直接拒绝。"""
    if not session_id:
        return
    now = time.time()
    with _SESSIONS_LOCK:
        _prune_sessions(now)
        item = _SESSIONS.get(session_id)
        if item and now - item["ts"] <= _SESSION_TTL:
            if item["project_id"] != project_id:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"会话已绑定项目 {item['project_id'] or '(全库)'}，"
                        f"不能切换到 {project_id or '(全库)'}；请新建会话"
                    ),
                )
            item["ts"] = now
            return
        _SESSIONS[session_id] = {"project_id": project_id, "ts": now}


def _session_key(user_id: Optional[str], project_id: Optional[str], conversation_id: str) -> str:
    user = user_id if user_id and IDENT_RE.match(user_id) else "web"
    project = project_id if project_id and IDENT_RE.match(project_id) else "all"
    conversation = conversation_id if IDENT_RE.match(conversation_id) else uuid.uuid4().hex
    return f"{user}:{project}:{conversation}"


def _env_file_key() -> str:
    """本地开发便利：从 schematic profile 的 .env 读网关密钥。生产应直接注入环境变量。"""
    path = os.getenv("HERMES_ENV_FILE", DEFAULT_ENV_FILE)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("API_SERVER_KEY="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def _base_url() -> str:
    return os.getenv("HERMES_API_BASE", DEFAULT_BASE).rstrip("/")


def _headers() -> Dict[str, str]:
    key = os.getenv("HERMES_API_KEY", "").strip() or _env_file_key()
    if not key:
        raise HTTPException(status_code=503, detail="Hermes 网关密钥未配置（HERMES_API_KEY）")
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _bound_project() -> Optional[str]:
    """灰度期一个部署只服务一个项目；请求里的 project_id 必须与之一致。"""
    value = os.getenv("HERMES_BOUND_PROJECT", "legacy").strip()
    return value or None


def _check_project(project_id: Optional[str]) -> None:
    bound = _bound_project()
    if bound and project_id and project_id != bound:
        raise HTTPException(
            status_code=409,
            detail=f"项目 {project_id} 不在本会话的绑定范围内（当前绑定 {bound}）",
        )


def _validate_run_id(run_id: str) -> str:
    if not RUN_ID_RE.match(run_id):
        raise HTTPException(status_code=400, detail="非法的 run_id")
    return run_id


def _upstream_error(exc: httpx.HTTPError) -> HTTPException:
    return HTTPException(status_code=502, detail=f"Hermes 网关不可用：{exc.__class__.__name__}")


class RunCreateRequest(BaseModel):
    input: str = Field(..., min_length=1, description="用户输入")
    session_id: Optional[str] = Field(default=None, max_length=128, description="前端会话id（conversation）")
    user_id: Optional[str] = Field(default=None, max_length=64)
    project_id: Optional[str] = None
    model: Optional[str] = None


class ApprovalRequest(BaseModel):
    choice: str = Field(..., description="once / session / always / deny")
    request_id: Optional[str] = Field(default=None, max_length=256)
    scope: Optional[str] = None


@router.get("/health")
async def agent_health() -> Dict[str, Any]:
    """前端灰度开关依据：是否开启 + 上游网关是否可达。"""
    enabled = _engine_enabled()
    upstream = False
    detail = ""
    if enabled:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{_base_url()}/models", headers=_headers())
            upstream = resp.status_code < 400
            detail = "" if upstream else _decode_json(resp.content or b"{}").get("error", f"HTTP {resp.status_code}")
        except HTTPException as exc:
            detail = str(exc.detail)
        except httpx.HTTPError as exc:
            detail = exc.__class__.__name__
    return {
        "enabled": enabled,
        "upstream": upstream,
        "detail": detail,
        "bound_project": _bound_project(),
        "base_url": _base_url(),
    }


@router.post("/runs")
async def create_run(payload: RunCreateRequest) -> Any:
    if not _engine_enabled():
        raise HTTPException(status_code=503, detail="Hermes 引擎灰度未开启（HERMES_ENGINE_ENABLED=0）")
    _check_project(payload.project_id)
    conversation = payload.session_id or uuid.uuid4().hex
    _bind_session(conversation, payload.project_id)

    body: Dict[str, Any] = {
        "input": payload.input,
        "session_id": _session_key(payload.user_id, payload.project_id, conversation),
    }
    if payload.model:
        body["model"] = payload.model

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(f"{_base_url()}/runs", json=body, headers=_headers())
    except httpx.HTTPError as exc:
        raise _upstream_error(exc)

    if resp.status_code >= 400:
        return JSONResponse(status_code=resp.status_code, content=_safe_json(resp))
    return _safe_json(resp)


@router.get("/runs/{run_id}/events")
async def stream_events(run_id: str) -> StreamingResponse:
    run_id = _validate_run_id(run_id)
    headers = _headers()
    url = f"{_base_url()}/runs/{run_id}/events"

    client = httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        request = client.build_request("GET", url, headers={**headers, "Accept": "text/event-stream"})
        upstream = await client.send(request, stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        raise _upstream_error(exc)

    if upstream.status_code >= 400:
        raw = await upstream.aread()
        await upstream.aclose()
        await client.aclose()
        return JSONResponse(status_code=upstream.status_code, content=_decode_json(raw))

    async def relay():
        try:
            async for chunk in upstream.aiter_raw():
                if chunk:
                    yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        relay(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/runs/{run_id}/approval")
async def submit_approval(run_id: str, payload: ApprovalRequest) -> Any:
    run_id = _validate_run_id(run_id)
    body: Dict[str, Any] = {"choice": payload.choice}
    if payload.request_id:
        body["request_id"] = payload.request_id
    if payload.scope:
        body["scope"] = payload.scope

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{_base_url()}/runs/{run_id}/approval", json=body, headers=_headers()
            )
    except httpx.HTTPError as exc:
        raise _upstream_error(exc)

    if resp.status_code >= 400:
        return JSONResponse(status_code=resp.status_code, content=_safe_json(resp))
    return _safe_json(resp)


@router.post("/runs/{run_id}/stop")
async def stop_run(run_id: str) -> Any:
    """中断运行中的 run（Hermes 侧 hard interrupt，含回收子进程）。"""
    run_id = _validate_run_id(run_id)
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(f"{_base_url()}/runs/{run_id}/stop", headers=_headers())
    except httpx.HTTPError as exc:
        raise _upstream_error(exc)

    if resp.status_code >= 400:
        return JSONResponse(status_code=resp.status_code, content=_safe_json(resp))
    return _safe_json(resp)


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> Any:
    run_id = _validate_run_id(run_id)
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(f"{_base_url()}/runs/{run_id}", headers=_headers())
    except httpx.HTTPError as exc:
        raise _upstream_error(exc)

    if resp.status_code >= 400:
        return JSONResponse(status_code=resp.status_code, content=_safe_json(resp))
    return _safe_json(resp)


def _decode_json(raw: bytes) -> Any:
    import json

    try:
        return json.loads(raw.decode("utf-8") or "{}")
    except ValueError:
        return {"error": raw.decode("utf-8", "replace")[:500]}


def _safe_json(resp: httpx.Response) -> Any:
    return _decode_json(resp.content or b"{}")
