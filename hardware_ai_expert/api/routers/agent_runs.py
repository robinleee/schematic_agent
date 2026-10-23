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
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/agent", tags=["agent"])

RUN_ID_RE = re.compile(r"^run_[0-9a-f]{8,64}$")
DEFAULT_BASE = "http://127.0.0.1:8642/p/schematic/v1"
DEFAULT_ENV_FILE = "/data/hermes/profiles/schematic/.env"
# 上游 SSE 可能长时间静默（模型思考），read 超时给足；连接超时要短。
_TIMEOUT = httpx.Timeout(connect=10.0, read=600.0, write=30.0, pool=10.0)


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
    session_id: Optional[str] = Field(default=None, max_length=128)
    project_id: Optional[str] = None
    model: Optional[str] = None


class ApprovalRequest(BaseModel):
    choice: str = Field(..., description="once / session / always / deny")
    request_id: Optional[str] = Field(default=None, max_length=256)
    scope: Optional[str] = None


@router.post("/runs")
async def create_run(payload: RunCreateRequest) -> Any:
    _check_project(payload.project_id)
    body: Dict[str, Any] = {"input": payload.input}
    if payload.session_id:
        body["session_id"] = payload.session_id
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
