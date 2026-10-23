"""Hermes Agent 运行代理（HTTP + SSE 透传）。

产品前端不直连 Hermes 网关：网关密钥只留在服务端，前端沿用「HTTP + SSE」范式。

    POST /api/v1/agent/runs                     创建一次 run
    GET  /api/v1/agent/runs/{run_id}/events     SSE 事件流（message.delta / tool.* / approval.request）
    POST /api/v1/agent/runs/{run_id}/approval   提交审批决定（once / session / always / deny）
    GET  /api/v1/agent/runs/{run_id}            查询状态

灰度阶段：本路由与既有 `/api/v1/chat`、`/ws/chat` 并存，前端可自行选择引擎。
"""
import asyncio
import json
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

# ---------------------------------------------------------------- 指标 / 观测
# 验收门要看「成功率 / P95 / 审批次数 / 回退次数」，内存计数重启即丢，
# 所以直接追加 JSONL，读取时按窗口聚合。
METRICS_FILE = os.getenv("HERMES_METRICS_FILE", "/data/schematic_agent/logs/agent_runs.jsonl")
_METRICS_LOCK = threading.Lock()
# 审批看门狗：前端 180s 自动拒绝；用户可能直接关页面，后端更晚一点兜底 deny。
APPROVAL_TIMEOUT = float(os.getenv("HERMES_APPROVAL_TIMEOUT", "300"))

# run_id → 元信息（project / session），进程内即可：只用于打点和排障。
_RUNS: Dict[str, Dict[str, Any]] = {}
_RUNS_LOCK = threading.Lock()
_MAX_RUNS = 2000


def _remember_run(run_id: str, project_id: Optional[str], conversation: str) -> None:
    with _RUNS_LOCK:
        if len(_RUNS) >= _MAX_RUNS:
            for key in list(_RUNS.keys())[: _MAX_RUNS // 4]:
                _RUNS.pop(key, None)
        _RUNS[run_id] = {"project_id": project_id, "conversation": conversation, "created": time.time()}


def _run_meta(run_id: str) -> Dict[str, Any]:
    with _RUNS_LOCK:
        return dict(_RUNS.get(run_id) or {})


def _record_metrics(record: Dict[str, Any]) -> None:
    """打点失败绝不能影响主链路。"""
    try:
        record.setdefault("ts", time.time())
        line = json.dumps(record, ensure_ascii=False)
        os.makedirs(os.path.dirname(METRICS_FILE) or ".", exist_ok=True)
        with _METRICS_LOCK:
            with open(METRICS_FILE, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception:
        pass


def _parse_event(raw: bytes) -> Dict[str, Any]:
    """解析单个 SSE 事件块；event: 名可能只在行首，payload 里也可能带 event。"""
    name = ""
    data_lines = []
    for line in raw.decode("utf-8", "ignore").splitlines():
        if line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    payload: Dict[str, Any] = {}
    if data_lines:
        try:
            payload = json.loads("\n".join(data_lines))
        except ValueError:
            payload = {}
    if name and not payload.get("event"):
        payload["event"] = name
    return payload


class RunTrace:
    """旁路观测：只读事件流做统计，不阻塞、不影响透传。"""

    def __init__(self, run_id: str, project_id: Optional[str]) -> None:
        self.run_id = run_id
        self.project_id = project_id
        self.started = time.time()
        self.tools = 0
        self.approvals = 0
        self.choices = []
        self.status = "stream_closed"
        self.finished = False
        self.watchdogs = {}

    def consume(self, raw: bytes) -> None:
        try:
            event = _parse_event(raw)
            name = event.get("event", "")
            if name == "tool.started":
                self.tools += 1
            elif name == "approval.request":
                self.approvals += 1
                request_id = event.get("request_id")
                if request_id and request_id not in self.watchdogs:
                    self.watchdogs[request_id] = asyncio.ensure_future(self._auto_deny(request_id))
            elif name == "approval.responded":
                request_id = event.get("request_id")
                choice = event.get("choice")
                if choice:
                    self.choices.append(choice)
                task = self.watchdogs.pop(request_id, None)
                if task and not task.done():
                    task.cancel()
            elif name in ("run.completed", "run.failed", "run.cancelled", "run.stopped"):
                self.status = name.split(".", 1)[1]
                self.finish()
        except Exception:
            pass

    async def _auto_deny(self, request_id: str) -> None:
        """审批无人应答时后端兜底拒绝（绝不自动放行）。

        先记账再发请求：approval.responded 事件可能在我们 POST 的 await 期间到达并
        cancel 掉本任务，如果先 POST 后记账，自动拒绝就会在指标里消失。
        """
        try:
            await asyncio.sleep(APPROVAL_TIMEOUT)
        except asyncio.CancelledError:
            raise
        # 到点了：无论后面的请求成功与否，都要留下「超时自动拒绝」的证据
        self.choices.append("auto_deny")
        _record_metrics({
            "kind": "approval_timeout", "run_id": self.run_id,
            "request_id": request_id, "project_id": self.project_id,
            "timeout_s": APPROVAL_TIMEOUT,
        })
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                await client.post(
                    f"{_base_url()}/runs/{self.run_id}/approval",
                    json={"choice": "deny", "request_id": request_id},
                    headers=_headers(),
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

    def finish(self) -> None:
        if self.finished:
            return
        self.finished = True
        for task in self.watchdogs.values():
            if not task.done():
                task.cancel()
        self.watchdogs.clear()
        _record_metrics({
            "kind": "run",
            "run_id": self.run_id,
            "project_id": self.project_id,
            "status": self.status,
            "duration_s": round(time.time() - self.started, 2),
            "tools": self.tools,
            "approvals": self.approvals,
            "choices": self.choices,
        })


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
    data = _safe_json(resp)
    if isinstance(data, dict) and data.get("run_id"):
        _remember_run(str(data["run_id"]), payload.project_id, conversation)
    return data


@router.get("/runs/{run_id}/events")
async def stream_events(run_id: str, last_seq: Optional[int] = None) -> StreamingResponse:
    run_id = _validate_run_id(run_id)
    headers = _headers()
    url = f"{_base_url()}/runs/{run_id}/events"
    if last_seq and last_seq > 0:
        # 刷新页面后续流：让上游只补发断点之后的事件，避免 delta 重复
        url = f"{url}?last_seq={int(last_seq)}"

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

    trace = RunTrace(run_id, _run_meta(run_id).get("project_id"))
    buffer = b""

    async def relay():
        nonlocal buffer
        try:
            async for chunk in upstream.aiter_raw():
                if not chunk:
                    continue
                buffer += chunk
                while b"\n\n" in buffer:
                    raw_event, buffer = buffer.split(b"\n\n", 1)
                    trace.consume(raw_event)
                yield chunk
        finally:
            # 客户端断开也要落一条（status=stream_closed），否则「用户关页面」在指标里消失
            trace.finish()
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


# ------------------------------------------------------------------ 打点 / 汇总
class TelemetryEvent(BaseModel):
    """前端侧事件（回退、渲染失败等），后端只落盘不做业务判断。"""

    event: str = Field(..., max_length=64)
    detail: Optional[str] = Field(default=None, max_length=500)
    project_id: Optional[str] = Field(default=None, max_length=64)
    run_id: Optional[str] = Field(default=None, max_length=80)


@router.post("/telemetry")
async def telemetry(payload: TelemetryEvent) -> Any:
    _record_metrics({
        "kind": "telemetry",
        "event": payload.event,
        "detail": payload.detail or "",
        "project_id": payload.project_id,
        "run_id": payload.run_id,
    })
    return {"ok": True}


def _percentile(values: list, ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * ratio))))
    return round(ordered[index], 2)


@router.get("/metrics/summary")
async def metrics_summary(days: float = 7.0) -> Any:
    """按时间窗聚合 run 指标：成功率、P50/P95 耗时、审批与回退计数。

    只读 JSONL，文件不存在就是空窗口（灰度前天然可用）。
    """
    since = time.time() - max(0.0, days) * 86400
    runs = []
    approval_timeouts = 0
    telemetry = []
    try:
        if os.path.exists(METRICS_FILE):
            with open(METRICS_FILE, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if float(row.get("ts") or 0) < since:
                        continue
                    kind = row.get("kind")
                    if kind == "run":
                        runs.append(row)
                    elif kind == "approval_timeout":
                        approval_timeouts += 1
                    elif kind == "telemetry":
                        telemetry.append(row)
    except OSError:
        pass

    durations = [float(r.get("duration_s") or 0) for r in runs]
    by_status: Dict[str, int] = {}
    choices: Dict[str, int] = {}
    tools_total = 0
    approvals_total = 0
    for row in runs:
        status = str(row.get("status") or "unknown")
        by_status[status] = by_status.get(status, 0) + 1
        tools_total += int(row.get("tools") or 0)
        approvals_total += int(row.get("approvals") or 0)
        for choice in row.get("choices") or []:
            choices[str(choice)] = choices.get(str(choice), 0) + 1

    fallbacks: Dict[str, int] = {}
    for row in telemetry:
        event = str(row.get("event") or "")
        if "fallback" in event:
            fallbacks[event] = fallbacks.get(event, 0) + 1

    total = len(runs)
    completed = by_status.get("completed", 0)
    return {
        "window_days": days,
        "runs": total,
        "completed": completed,
        "success_rate": round(completed / total, 4) if total else 0.0,
        "by_status": by_status,
        "duration_p50_s": _percentile(durations, 0.5),
        "duration_p95_s": _percentile(durations, 0.95),
        "tools_avg": round(tools_total / total, 2) if total else 0.0,
        "approvals": approvals_total,
        "approval_choices": choices,
        "approval_timeouts": approval_timeouts,
        "fallbacks": fallbacks,
        "fallback_total": sum(fallbacks.values()),
        "metrics_file": METRICS_FILE,
    }
