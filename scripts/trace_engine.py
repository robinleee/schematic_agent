#!/usr/bin/env python3
"""抓一次引擎运行的完整 SSE 事件序列，用于排轮次/工具冗余。

用法：
  .venv/bin/python scripts/trace_engine.py --task C2 --engine hermes
  .venv/bin/python scripts/trace_engine.py --task C2 --engine legacy --out logs/trace/c2-legacy.jsonl

产物：JSONL，每行一个事件 {t, event, data}。跑完打印工具调用序列摘要。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List

import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bench_engines import TASKS  # noqa: E402


def parse_block(lines: List[str]) -> Dict[str, Any]:
    name = ""
    data: List[str] = []
    for line in lines:
        if line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    payload: Dict[str, Any] = {}
    if data:
        try:
            payload = json.loads("\n".join(data))
        except ValueError:
            payload = {"_raw": "\n".join(data)}
    if name and not payload.get("event"):
        payload["event"] = name
    return payload


def brief(event: Dict[str, Any]) -> str:
    name = event.get("event", "?")
    if name == "tool.started":
        tool = event.get("tool") or event.get("name") or "?"
        args = event.get("arguments") or event.get("args") or {}
        if isinstance(args, dict):
            arg_s = json.dumps(args, ensure_ascii=False)
        else:
            arg_s = str(args)
        return f"tool.started {tool} {arg_s[:160]}"
    if name == "tool.finished":
        tool = event.get("tool") or event.get("name") or "?"
        ms = event.get("duration_ms")
        ok = event.get("ok")
        return f"tool.finished {tool} ok={ok} {ms}ms"
    if name == "message.delta":
        return ""
    return name


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--engine", default="hermes", choices=["hermes", "legacy"])
    ap.add_argument("--project", default="legacy")
    ap.add_argument("--base", default=os.getenv("SCHEMATIC_API_BASE", "http://127.0.0.1:8501"))
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    task = next((t for t in TASKS if t["id"] == args.task), None)
    if not task:
        print(f"未知任务 {args.task}；可选 {[t['id'] for t in TASKS]}", file=sys.stderr)
        return 64

    out = args.out or f"logs/trace/{args.task}-{args.engine}-{datetime.now():%H%M%S}.jsonl"
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)

    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    started = time.monotonic()
    rows: List[Dict[str, Any]] = []
    text: List[str] = []
    final_status = "stream_closed"

    with httpx.Client(timeout=httpx.Timeout(900.0)) as client:
        if args.engine == "legacy":
            resp = client.post(
                f"{args.base}/api/v1/chat",
                json={"query": task["prompt"], "project_id": args.project},
            )
            elapsed = time.monotonic() - started
            payload = resp.json() if resp.content else {}
            data = payload.get("data") or {}
            rows.append({"t": round(elapsed, 2), "event": "legacy.http", "data": payload})
            text.append(str(data.get("report") or ""))
            final_status = str(data.get("status") or "?")
            run_id = None
        else:
            resp = client.post(
                f"{args.base}/api/v1/agent/runs",
                json={
                    "input": task["prompt"],
                    "project_id": args.project,
                    "session_id": f"trace-{stamp}-{uuid.uuid4().hex[:6]}",
                },
            )
            payload = resp.json() or {}
            run_id = payload.get("run_id")
            if not run_id:
                print(f"未拿到 run_id: {payload}", file=sys.stderr)
                return 1
            buffer: List[str] = []
            with client.stream("GET", f"{args.base}/api/v1/agent/runs/{run_id}/events") as stream:
                for line in stream.iter_lines():
                    if line == "":
                        if not buffer:
                            continue
                        event = parse_block(buffer)
                        buffer = []
                        t = round(time.monotonic() - started, 2)
                        rows.append({"t": t, "event": event.get("event", "?"), "data": event})
                        if event.get("event") == "message.delta":
                            text.append(str(event.get("delta") or event.get("text") or ""))
                        if event.get("event", "").startswith("run."):
                            final_status = event["event"].split(".", 1)[1]
                        continue
                    buffer.append(line)

    with open(out, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    total = round(time.monotonic() - started, 2)
    tools = [r for r in rows if r["event"] == "tool.started"]
    print(f"# {args.task}/{args.engine} status={final_status} total={total}s tools={len(tools)} run_id={run_id}")
    print(f"# 事件 {len(rows)} 条 → {out}")
    print(f"# 正文 {len(''.join(text))} 字")
    for i, r in enumerate(tools, 1):
        d = r["data"]
        tool = d.get("tool") or d.get("name") or "?"
        args_s = d.get("arguments") or d.get("args") or {}
        args_s = json.dumps(args_s, ensure_ascii=False) if isinstance(args_s, dict) else str(args_s)
        print(f"{i:2d}. [{r['t']:7.2f}s] {tool:<28} {args_s[:200]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
