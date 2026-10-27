#!/usr/bin/env python3
"""两引擎同负载基线（legacy ReAct vs Hermes Agent）。

为什么需要这个脚本：灰度验收门「Hermes P95 ≤ 1.5× legacy」「成功率不劣化」
必须建立在**同一批任务**上；历史上拿「无工具简单问答」的 legacy 样本去比
「带 MCP 工具」的 Hermes 样本，比值不成立。

做法：
1. 固定任务集（简单问答 / 图谱查询 / 审查诊断），两条引擎跑同样的 prompt；
2. 每个任务独立会话（Hermes 侧不继承上下文），互不预热；
3. 逐条落 `logs/bench_runs.jsonl`，并可导出 Markdown 对比表；
4. 后端自身的 `agent_runs.jsonl` 仍会记录同一批 run（可按 run_id 交叉核对）。

用法：
    .venv/bin/python scripts/bench_engines.py                 # 全部任务各 1 轮
    .venv/bin/python scripts/bench_engines.py --repeat 3      # 每任务 3 轮
    .venv/bin/python scripts/bench_engines.py --only legacy   # 只跑一条引擎
    .venv/bin/python scripts/bench_engines.py --tasks A1,B1,C1
    .venv/bin/python scripts/bench_engines.py --out-md /tmp/bench.md

退出码：0 全部请求完成（结果好坏看表）；2 有请求级异常。
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

API_DEFAULT = os.getenv("SCHEMATIC_API", "http://127.0.0.1:8501")
PROJECT_DEFAULT = os.getenv("SCHEMATIC_PROJECT", "legacy")
LOG_FILE = os.getenv("SCHEMATIC_BENCH_LOG", "/data/schematic_agent/logs/bench_runs.jsonl")

# 任务集：A=无工具问答（2），B=带图谱工具查询（3），C=审查/诊断（2）
# expect_tools 用于判断「工具调用是否正确」，不是硬性失败条件。
TASKS: List[Dict[str, Any]] = [
    {
        "id": "A1",
        "category": "qa",
        "task_type": "query",
        "expect_tools": 0,
        "prompt": "用一句话解释什么是差分对，以及它在高速信号里的作用。",
    },
    {
        "id": "A2",
        "category": "qa",
        "task_type": "query",
        "expect_tools": 0,
        "prompt": "LDO 和 Buck 变换器的主要区别是什么？各自适合什么场景？",
    },
    {
        "id": "B1",
        "category": "graph",
        "task_type": "query",
        "expect_tools": 1,
        "prompt": "查询器件 U30004 的所有引脚，并列出每个引脚连接的网络。",
    },
    {
        "id": "B2",
        "category": "graph",
        "task_type": "query",
        "expect_tools": 1,
        "prompt": "统计当前项目的器件总数和网络总数，并说明其中电源网络有多少个。",
    },
    {
        "id": "B3",
        "category": "graph",
        "task_type": "query",
        "expect_tools": 1,
        "prompt": "分析 U13 这颗 PMIC 的下游电源链路，列出它输出的电压和主要负载。",
    },
    {
        "id": "C1",
        "category": "review",
        "task_type": "review",
        "expect_tools": 1,
        "prompt": "对当前项目执行一次设计规则审查，汇总主要违规类型和数量，按严重程度排序。",
    },
    {
        "id": "C2",
        "category": "diagnosis",
        "task_type": "diagnosis",
        "expect_tools": 1,
        "prompt": "U20187 这颗 PMIC 的输出电压异常，帮我定位可能的根因，并给出排查顺序。",
    },
]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def percentile(values: List[float], pct: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * pct / 100.0
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def record(row: Dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(LOG_FILE) or ".", exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError as exc:
        print(f"[warn] 写日志失败: {exc}", file=sys.stderr)


# ---------------------------------------------------------------- legacy 引擎


def run_legacy(client: httpx.Client, base: str, task: Dict[str, Any], project_id: str) -> Dict[str, Any]:
    """经典 ReAct 引擎：非流式 /chat，只能拿到总耗时。"""
    body = {"message": task["prompt"], "task_type": task["task_type"], "project_id": project_id}
    started = time.monotonic()
    try:
        resp = client.post(f"{base}/api/v1/chat", json=body, timeout=600.0)
    except httpx.HTTPError as exc:
        return _failure("legacy", task, time.monotonic() - started, f"{type(exc).__name__}: {exc}")

    elapsed = time.monotonic() - started
    try:
        payload = resp.json()
    except ValueError:
        return _failure("legacy", task, elapsed, f"HTTP {resp.status_code} 非 JSON")

    if resp.status_code >= 400:
        return _failure("legacy", task, elapsed, f"HTTP {resp.status_code}: {str(payload)[:300]}")

    data = payload.get("data") or {}
    report = data.get("report") or ""
    status = data.get("status") or ("success" if payload.get("success") else "error")
    tools = int(data.get("tool_call_count") or 0)
    ok = bool(payload.get("success")) and status == "success" and len(report.strip()) >= 20
    return {
        "engine": "legacy",
        "task_id": task["id"],
        "category": task["category"],
        "ok": ok,
        "status": status,
        "duration_s": round(elapsed, 2),
        "first_event_s": None,
        "tools": tools,
        "tool_expect_ok": tools >= task["expect_tools"],
        "chars": len(report),
        "approvals": 0,
        "error": None if ok else (payload.get("message") or f"report 长度 {len(report)}"),
        "run_id": None,
        "sample": report[:400],
    }


def _failure(engine: str, task: Dict[str, Any], elapsed: float, error: str) -> Dict[str, Any]:
    return {
        "engine": engine,
        "task_id": task["id"],
        "category": task["category"],
        "ok": False,
        "status": "exception",
        "duration_s": round(elapsed, 2),
        "first_event_s": None,
        "tools": 0,
        "tool_expect_ok": False,
        "chars": 0,
        "approvals": 0,
        "error": error[:500],
        "run_id": None,
        "sample": "",
    }


# ---------------------------------------------------------------- Hermes 引擎


def _parse_sse_block(lines: List[str]) -> Dict[str, Any]:
    name = ""
    data_lines: List[str] = []
    for line in lines:
        if line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    payload: Dict[str, Any] = {}
    if data_lines:
        try:
            payload = json.loads("\n".join(data_lines))
        except ValueError:
            payload = {"raw": "\n".join(data_lines)}
    if name and not payload.get("event"):
        payload["event"] = name
    return payload


def run_hermes(
    client: httpx.Client, base: str, task: Dict[str, Any], project_id: str, tag: str
) -> Dict[str, Any]:
    """Hermes 引擎：创建 run + 消费 SSE 到终态（必须消费完，后端才会落终态指标）。"""
    body = {
        "input": task["prompt"],
        "project_id": project_id,
        "session_id": f"bench-{tag}-{task['id']}-{uuid.uuid4().hex[:6]}",
    }
    started = time.monotonic()
    try:
        resp = client.post(f"{base}/api/v1/agent/runs", json=body, timeout=120.0)
    except httpx.HTTPError as exc:
        return _failure("hermes", task, time.monotonic() - started, f"{type(exc).__name__}: {exc}")
    if resp.status_code >= 400:
        detail = ""
        try:
            detail = json.dumps(resp.json(), ensure_ascii=False)[:300]
        except ValueError:
            detail = resp.text[:300]
        return _failure("hermes", task, time.monotonic() - started, f"HTTP {resp.status_code}: {detail}")

    payload = resp.json() or {}
    run_id = payload.get("run_id")
    if not run_id:
        return _failure("hermes", task, time.monotonic() - started, f"未返回 run_id: {payload}")

    first_event: Optional[float] = None
    tools = 0
    approvals = 0
    status = "stream_closed"
    text_parts: List[str] = []
    error = None
    buffer: List[str] = []

    try:
        with client.stream(
            "GET", f"{base}/api/v1/agent/runs/{run_id}/events", timeout=httpx.Timeout(600.0)
        ) as stream:
            if stream.status_code >= 400:
                stream.read()
                return _failure("hermes", task, time.monotonic() - started, f"事件流 HTTP {stream.status_code}")
            for line in stream.iter_lines():
                if line == "":
                    if not buffer:
                        continue
                    event = _parse_sse_block(buffer)
                    buffer = []
                    name = event.get("event", "")
                    if first_event is None:
                        first_event = time.monotonic() - started
                    if name == "tool.started":
                        tools += 1
                    elif name == "approval.request":
                        approvals += 1
                        _respond_approval(client, base, run_id, event.get("request_id"), "deny")
                    elif name == "message.delta":
                        delta = event.get("delta") or event.get("text") or ""
                        if isinstance(delta, str):
                            text_parts.append(delta)
                    elif name in ("run.completed", "run.failed", "run.cancelled", "run.stopped"):
                        status = name.split(".", 1)[1]
                        if name == "run.failed":
                            error = str(event.get("error") or event)[:300]
                    continue
                buffer.append(line)
            # 流结束（服务端正常关闭）也结算，避免遗漏
    except httpx.HTTPError as exc:
        error = f"SSE {type(exc).__name__}: {exc}"

    elapsed = time.monotonic() - started
    text = "".join(text_parts)
    ok = status == "completed" and len(text.strip()) >= 20
    return {
        "engine": "hermes",
        "task_id": task["id"],
        "category": task["category"],
        "ok": ok,
        "status": status,
        "duration_s": round(elapsed, 2),
        "first_event_s": round(first_event, 2) if first_event is not None else None,
        "tools": tools,
        "tool_expect_ok": tools >= task["expect_tools"],
        "chars": len(text),
        "approvals": approvals,
        "error": error if not ok else None,
        "run_id": run_id,
        "sample": text[:400],
    }


def _respond_approval(client: httpx.Client, base: str, run_id: str, request_id: Optional[str], choice: str) -> None:
    try:
        client.post(
            f"{base}/api/v1/agent/runs/{run_id}/approval",
            json={"choice": choice, "request_id": request_id},
            timeout=30.0,
        )
    except httpx.HTTPError:
        pass


# ---------------------------------------------------------------- 汇总


def summarize(rows: List[Dict[str, Any]], engine: str) -> Dict[str, Any]:
    mine = [r for r in rows if r["engine"] == engine]
    durations = [r["duration_s"] for r in mine if r["ok"]]
    overall = {
        "runs": len(mine),
        "ok": sum(1 for r in mine if r["ok"]),
        "success_rate": round(sum(1 for r in mine if r["ok"]) / len(mine), 3) if mine else None,
        "p50_s": round(percentile(durations, 50), 2) if durations else None,
        "p95_s": round(percentile(durations, 95), 2) if durations else None,
        "max_s": round(max(durations), 2) if durations else None,
        "tools_avg": round(statistics.mean([r["tools"] for r in mine]), 2) if mine else None,
        "tool_expect_rate": round(sum(1 for r in mine if r["tool_expect_ok"]) / len(mine), 3) if mine else None,
    }
    by_cat: Dict[str, Any] = {}
    for cat in sorted({r["category"] for r in mine}):
        subset = [r for r in mine if r["category"] == cat]
        ds = [r["duration_s"] for r in subset if r["ok"]]
        by_cat[cat] = {
            "runs": len(subset),
            "ok": sum(1 for r in subset if r["ok"]),
            "p50_s": round(percentile(ds, 50), 2) if ds else None,
            "p95_s": round(percentile(ds, 95), 2) if ds else None,
        }
    return {"overall": overall, "by_category": by_cat}


MIN_SAMPLES = 20


def compute_gate(legacy: Dict[str, Any], hermes: Dict[str, Any]) -> Dict[str, Any]:
    """灰度验收门（与设计文档 15.9 一致）。

    样本不足时只给趋势，不给 pass —— 避免拿 7 个任务就宣布达标。
    """
    lo, ho = legacy["overall"], hermes["overall"]
    if not lo["runs"] or not ho["runs"]:
        return {"verdict": "not_comparable", "checks": {}, "reason": "只跑了一条引擎"}
    lp, hp = lo["p95_s"], ho["p95_s"]
    ratio = round(hp / lp, 2) if (lp and hp) else None
    checks = {
        "samples": {
            "pass": lo["runs"] >= MIN_SAMPLES and ho["runs"] >= MIN_SAMPLES,
            "legacy_runs": lo["runs"],
            "hermes_runs": ho["runs"],
            "required": MIN_SAMPLES,
        },
        "success_rate": {
            "pass": ho["success_rate"] is not None and lo["success_rate"] is not None
            and ho["success_rate"] >= lo["success_rate"],
            "legacy": lo["success_rate"],
            "hermes": ho["success_rate"],
        },
        "p95": {
            "pass": ratio is not None and ratio <= 1.5,
            "legacy_s": lp,
            "hermes_s": hp,
            "ratio": ratio,
            "threshold": 1.5,
        },
        "tool_coverage": {
            # 代理指标：任务要求用工具时是否真的调了工具；内容正确性需人工/评审补
            "pass": ho["tool_expect_rate"] is not None and ho["tool_expect_rate"] >= 0.95,
            "hermes_rate": ho["tool_expect_rate"],
            "threshold": 0.95,
        },
    }
    failed = [name for name, item in checks.items() if not item["pass"]]
    if not checks["samples"]["pass"] and set(failed) <= {"samples"}:
        verdict = "insufficient_samples"
    elif failed:
        verdict = "fail"
    else:
        verdict = "pass"
    return {"verdict": verdict, "checks": checks}


def render_markdown(rows: List[Dict[str, Any]], meta: Dict[str, Any]) -> str:
    legacy = summarize(rows, "legacy")
    hermes = summarize(rows, "hermes")
    lines = [
        "# 两引擎同负载基线",
        "",
        f"- 时间：{meta['started']} → {meta['finished']}",
        f"- 接口：{meta['base']}  项目：{meta['project']}  每任务轮数：{meta['repeat']}",
        f"- 任务数：{len(meta['tasks'])}",
        "",
        "## 汇总",
        "",
        "| 引擎 | runs | 成功 | 成功率 | p50 | p95 | max | 工具均值 | 工具符合率 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for name, s in (("legacy", legacy), ("hermes", hermes)):
        o = s["overall"]
        if not o["runs"]:
            continue
        lines.append(
            f"| {name} | {o['runs']} | {o['ok']} | {o['success_rate']} | {o['p50_s']}s | "
            f"{o['p95_s']}s | {o['max_s']}s | {o['tools_avg']} | {o['tool_expect_rate']} |"
        )

    ratio = None
    lp, hp = legacy["overall"]["p95_s"], hermes["overall"]["p95_s"]
    if lp and hp:
        ratio = round(hp / lp, 2)
        lines += ["", f"**p95 比值（hermes / legacy）**：{ratio}（验收门 ≤1.5）"]

    gate = compute_gate(legacy, hermes)
    lines += ["", "## 验收门", "", f"**结论：{gate['verdict']}**", ""]
    if not gate.get("checks"):
        # 单引擎跑（--only）只做回归观察，没有可比对象，不能硬套验收门
        lines.append(f"原因：{gate.get('reason', '缺少对照引擎')}")
        return "\n".join(lines) + "\n"
    lines += ["| 检查项 | 结果 | 依据 |", "|---|---|---|"]
    c = gate["checks"]
    lines.append(f"| 样本量 ≥{c['samples']['required']}/引擎 | {'PASS' if c['samples']['pass'] else 'PENDING'} | "
                 f"legacy {c['samples']['legacy_runs']} / hermes {c['samples']['hermes_runs']} |")
    lines.append(f"| 成功率不劣化 | {'PASS' if c['success_rate']['pass'] else 'FAIL'} | "
                 f"legacy {c['success_rate']['legacy']} / hermes {c['success_rate']['hermes']} |")
    lines.append(f"| p95 ≤ {c['p95']['threshold']}× | {'PASS' if c['p95']['pass'] else 'FAIL'} | "
                 f"ratio {c['p95']['ratio']}（{c['p95']['legacy_s']}s → {c['p95']['hermes_s']}s） |")
    lines.append(f"| 工具覆盖率 ≥{c['tool_coverage']['threshold']} | {'PASS' if c['tool_coverage']['pass'] else 'FAIL'} | "
                 f"hermes {c['tool_coverage']['hermes_rate']} |")

    lines += ["", "## 分类对比（p50 / p95，秒）", "", "| 类别 | legacy | hermes |", "|---|---|---|"]
    for cat in sorted({r["category"] for r in rows}):
        l = legacy["by_category"].get(cat, {})
        h = hermes["by_category"].get(cat, {})
        lines.append(
            f"| {cat} | {l.get('p50_s')} / {l.get('p95_s')} | {h.get('p50_s')} / {h.get('p95_s')} |"
        )

    lines += ["", "## 明细", "", "| 任务 | 类别 | 引擎 | 状态 | 耗时 | 首事件 | 工具 | 字数 | 备注 |", "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        note = (r.get("error") or "").replace("|", "/")[:60]
        lines.append(
            f"| {r['task_id']} | {r['category']} | {r['engine']} | {r['status']} | {r['duration_s']}s | "
            f"{r['first_event_s'] if r['first_event_s'] is not None else '-'} | {r['tools']} | {r['chars']} | {note} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default=API_DEFAULT)
    ap.add_argument("--project", default=PROJECT_DEFAULT)
    ap.add_argument("--only", choices=["legacy", "hermes"])
    ap.add_argument("--tasks", default="", help="逗号分隔任务 id，默认全部")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--out-md", default="")
    ap.add_argument("--out-json", default="")
    args = ap.parse_args()

    base = args.base.rstrip("/")
    selected = TASKS
    if args.tasks:
        wanted = {t.strip().upper() for t in args.tasks.split(",") if t.strip()}
        selected = [t for t in TASKS if t["id"] in wanted]
        if not selected:
            print(f"未知任务 id：{args.tasks}", file=sys.stderr)
            return 64
    engines = [args.only] if args.only else ["legacy", "hermes"]

    tag = datetime.now().strftime("%Y%m%d-%H%M%S")
    started = now_iso()
    rows: List[Dict[str, Any]] = []

    print(f"[bench] {started} engines={engines} tasks={[t['id'] for t in selected]} repeat={args.repeat}", flush=True)
    with httpx.Client(timeout=httpx.Timeout(600.0)) as client:
        try:
            health = client.get(f"{base}/api/v1/health", timeout=10.0)
            print(f"[bench] health {health.status_code}", flush=True)
        except httpx.HTTPError as exc:
            print(f"[bench] 服务不可用：{exc}", file=sys.stderr)
            return 2

        for rnd in range(1, args.repeat + 1):
            for task in selected:
                for engine in engines:
                    print(f"[bench] round {rnd} {task['id']} {engine} ...", flush=True)
                    if engine == "legacy":
                        row = run_legacy(client, base, task, args.project)
                    else:
                        row = run_hermes(client, base, task, args.project, f"{tag}-r{rnd}")
                    row.update({"round": rnd, "ts": now_iso(), "project": args.project})
                    rows.append(row)
                    record(row)
                    print(
                        f"[bench]   -> {row['status']} {row['duration_s']}s tools={row['tools']} "
                        f"chars={row['chars']} ok={row['ok']}",
                        flush=True,
                    )

    meta = {
        "started": started,
        "finished": now_iso(),
        "base": base,
        "project": args.project,
        "repeat": args.repeat,
        "tasks": [t["id"] for t in selected],
    }
    md = render_markdown(rows, meta)
    print()
    print(md)

    if args.out_md:
        os.makedirs(os.path.dirname(args.out_md) or ".", exist_ok=True)
        with open(args.out_md, "w", encoding="utf-8") as fh:
            fh.write(md)
        print(f"[bench] 已写 {args.out_md}")
    if args.out_json:
        os.makedirs(os.path.dirname(args.out_json) or ".", exist_ok=True)
        summary = {e: summarize(rows, e) for e in engines}
        summary["gate"] = compute_gate(summary.get("legacy", summarize([], "legacy")),
                                       summary.get("hermes", summarize([], "hermes")))
        with open(args.out_json, "w", encoding="utf-8") as fh:
            json.dump({"meta": meta, "rows": rows, "summary": summary},
                      fh, ensure_ascii=False, indent=2)
        print(f"[bench] 已写 {args.out_json}")

    return 0 if all(r["status"] not in ("exception",) for r in rows) else 2


if __name__ == "__main__":
    sys.exit(main())
