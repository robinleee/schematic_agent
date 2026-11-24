#!/usr/bin/env python3
"""P1 联调：走 Hermes HTTP API 触发写工具审批，验证 approval.request → 批准 → 工具执行。

用法：
  python3 hermes_approval_probe.py                 # 批准一次
  python3 hermes_approval_probe.py --choice deny   # 拒绝
"""
import argparse
import json
import sys
import threading
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8642/p/schematic/v1"
KEY = "schematic-svc-key-2026-1023-a7f3c1"
HDRS = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}

PROMPT = (
    "调用 submit_hitl_decision 工具，参数 review_id=TEST-001，decision=approve，"
    "comment=P1 联调。调用后把工具的原始返回原样贴出来，不要改写。"
)


def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers=HDRS, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def stream_events(run_id, on_event, timeout=240):
    req = urllib.request.Request(f"{BASE}/runs/{run_id}/events", headers={**HDRS, "Accept": "text/event-stream"})
    deadline = time.time() + timeout
    with urllib.request.urlopen(req, timeout=timeout) as r:
        event = None
        for raw in r:
            if time.time() > deadline:
                break
            line = raw.decode("utf-8", "replace").rstrip("\n")
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                payload = line[5:].strip()
                try:
                    data = json.loads(payload)
                except Exception:
                    data = payload
                if on_event(event, data) is False:
                    break
            elif line == "":
                event = None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--choice", default="once")
    args = ap.parse_args()

    status, created = post("/runs", {"input": PROMPT, "session_id": f"probe-{int(time.time())}"})
    print(f"[create] {status} {json.dumps(created, ensure_ascii=False)[:300]}")
    if status >= 300:
        return 1
    run_id = created.get("run_id") or created.get("id")
    print(f"[run_id] {run_id}")

    seen = {"approval": False, "done": False}

    def on_event(event, data):
        if isinstance(data, dict):
            etype = data.get("event") or data.get("type") or event
            summary = {k: v for k, v in data.items() if k in ("event", "type", "status", "choices", "request_id", "message_id", "delta")}
            print(f"[event] {etype} {json.dumps(summary, ensure_ascii=False)[:400]}")
        else:
            print(f"[event] {event} {str(data)[:200]}")
        if (event == "approval.request") or (isinstance(data, dict) and data.get("event") == "approval.request"):
            seen["approval"] = True
            choices = data.get("choices") if isinstance(data, dict) else None
            rid = data.get("request_id") if isinstance(data, dict) else None
            print(f"[approval] choices={choices} request_id={rid}")
            body = {"choice": args.choice}
            if rid:
                body["request_id"] = rid
            st, resp = post(f"/runs/{run_id}/approval", body)
            print(f"[approve] {st} {json.dumps(resp, ensure_ascii=False)[:300]}")
        if isinstance(data, dict) and data.get("event") in ("run.completed", "run.failed", "run.cancelled", "done"):
            seen["done"] = True
            return False
        return True

    try:
        stream_events(run_id, on_event)
    except Exception as exc:
        print(f"[stream-error] {exc}")

    time.sleep(2)
    req = urllib.request.Request(f"{BASE}/runs/{run_id}", headers=HDRS)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            final = json.loads(r.read().decode())
        print("[final]", json.dumps(final, ensure_ascii=False)[:1500])
    except Exception as exc:
        print("[final-error]", exc)
    print(f"[summary] approval_seen={seen['approval']} done={seen['done']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
