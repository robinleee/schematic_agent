#!/usr/bin/env python3
"""对 bench_engines.py 的结果做「严格复评」，生成对比报告。

为什么要复评：legacy /chat 在 Agent 内部失败时仍返回 success=true，
正文是「## 处理失败\n\nLLM 决策调用失败…」（30 字符）。只看 HTTP 状态会把
失败算成成功，所以这里按「正文可用性」重新判分：

1. 长度门槛：qa ≥ 40 字，graph/review/diagnosis ≥ 80 字（去空白）；
2. 失败标记：处理失败 / 调用失败 / 模型服务 / Traceback / Error:；
3. 终态：legacy 要求 status=success，hermes 要求 completed。

用法：
    .venv/bin/python scripts/bench_report.py logs/bench/baseline-20261027.json
    .venv/bin/python scripts/bench_report.py --jsonl logs/bench_runs.jsonl --since "2026-10-27T15:09"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

MIN_CHARS = {"qa": 40}
MIN_CHARS_DEFAULT = 80
FAIL_MARKERS = (
    "处理失败",
    "处理异常",
    "调用失败",
    "模型服务",
    "Traceback",
    "Error:",
    "执行失败",
    "内部错误",
    "分析异常",
    "分析超时",
    "无效工具",
)
OK_STATUS = {"legacy": {"success"}, "hermes": {"completed"}}
MIN_SAMPLES = 20


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


def strict_ok(row: Dict[str, Any]) -> bool:
    if str(row.get("status")) not in OK_STATUS.get(row["engine"], set()):
        return False
    text = (row.get("sample") or "").strip()
    # sample 截断到 400 字，长度判断用 chars 字段（全文长度）
    length = int(row.get("chars") or 0)
    floor = MIN_CHARS.get(row.get("category"), MIN_CHARS_DEFAULT)
    if length < floor:
        return False
    head = text[:200]
    return not any(marker in head for marker in FAIL_MARKERS)


def summarize(rows: List[Dict[str, Any]], engine: str) -> Dict[str, Any]:
    mine = [r for r in rows if r["engine"] == engine]
    good = [r for r in mine if strict_ok(r)]
    durations = [r["duration_s"] for r in good]
    by_cat: Dict[str, Any] = {}
    for cat in sorted({r["category"] for r in mine}):
        subset = [r for r in mine if r["category"] == cat]
        cat_good = [r for r in subset if strict_ok(r)]
        ds = [r["duration_s"] for r in cat_good]
        by_cat[cat] = {
            "runs": len(subset),
            "ok": len(cat_good),
            "success_rate": round(len(cat_good) / len(subset), 3) if subset else None,
            "p50_s": round(percentile(ds, 50), 2) if ds else None,
            "tools_avg": round(sum(r["tools"] for r in cat_good) / len(cat_good), 2) if cat_good else None,
        }
    return {
        "runs": len(mine),
        "ok": len(good),
        "success_rate": round(len(good) / len(mine), 3) if mine else None,
        "p50_s": round(percentile(durations, 50), 2) if durations else None,
        "p95_s": round(percentile(durations, 95), 2) if durations else None,
        "max_s": round(max(durations), 2) if durations else None,
        "tools_avg": round(sum(r["tools"] for r in mine) / len(mine), 2) if mine else None,
        "tools_max": max((r["tools"] for r in mine), default=None),
        "by_category": by_cat,
        "failed_tasks": [r["task_id"] for r in mine if not strict_ok(r)],
    }


def gate(legacy: Dict[str, Any], hermes: Dict[str, Any]) -> Dict[str, Any]:
    if not legacy.get("runs") or not hermes.get("runs"):
        return {"verdict": "not_comparable", "checks": {}, "p95_ratio": None}
    lp, hp = legacy.get("p95_s"), hermes.get("p95_s")
    ratio = round(hp / lp, 2) if (lp and hp) else None
    checks = {
        "samples": legacy["runs"] >= MIN_SAMPLES and hermes["runs"] >= MIN_SAMPLES,
        "success_rate": (
            legacy["success_rate"] is not None
            and hermes["success_rate"] is not None
            and hermes["success_rate"] >= legacy["success_rate"]
        ),
        "p95": ratio is not None and ratio <= 1.5,
    }
    if not checks["samples"] and checks["success_rate"] and checks["p95"]:
        verdict = "insufficient_samples"
    elif all(checks.values()):
        verdict = "pass"
    else:
        verdict = "fail"
    return {"verdict": verdict, "checks": checks, "p95_ratio": ratio}


def render(rows: List[Dict[str, Any]], meta: Dict[str, Any]) -> str:
    legacy = summarize(rows, "legacy")
    hermes = summarize(rows, "hermes")
    g = gate(legacy, hermes)
    out = [
        "# 两引擎同负载基线（严格复评）",
        "",
        f"- 时间：{meta.get('started', '?')} → {meta.get('finished', '?')}",
        f"- 项目：{meta.get('project', '?')}  轮数/任务：{meta.get('repeat', '?')}",
        "- 判分：终态正确 + 正文长度达标 + 无失败标记（legacy 的 success 不可信）",
        "",
        "## 汇总",
        "",
        "| 引擎 | runs | 严格成功 | 成功率 | p50 | p95 | max | 工具均值 | 工具最多 | 失败的题 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, s in (("legacy", legacy), ("hermes", hermes)):
        out.append(
            f"| {name} | {s['runs']} | {s['ok']} | {s['success_rate']} | {s['p50_s']}s | "
            f"{s['p95_s']}s | {s['max_s']}s | {s['tools_avg']} | {s['tools_max']} | "
            f"{','.join(s['failed_tasks']) or '-'} |"
        )
    out += [
        "",
        f"**p95 比值（hermes/legacy）**：{g['p95_ratio']}（门 ≤1.5）  ",
        f"**验收门**：{g['verdict']}  ",
        f"- 样本量 ≥{MIN_SAMPLES}/引擎：{'PASS' if g['checks']['samples'] else 'PENDING'}"
        f"（{legacy['runs']} / {hermes['runs']}）",
        f"- 成功率不劣化：{'PASS' if g['checks']['success_rate'] else 'FAIL'}",
        f"- p95 ≤1.5×：{'PASS' if g['checks']['p95'] else 'FAIL'}",
        "",
        "## 分类（严格成功样本的 p50 / 工具均值）",
        "",
        "| 类别 | legacy | hermes |",
        "|---|---|---|",
    ]
    for cat in sorted({r["category"] for r in rows}):
        l = legacy["by_category"].get(cat, {})
        h = hermes["by_category"].get(cat, {})
        out.append(
            f"| {cat} | p50 {l.get('p50_s')}s / 工具 {l.get('tools_avg')} / 成功 {l.get('ok')}/{l.get('runs')} "
            f"| p50 {h.get('p50_s')}s / 工具 {h.get('tools_avg')} / 成功 {h.get('ok')}/{h.get('runs')} |"
        )
    out += ["", "## 明细", "", "| 任务 | 引擎 | 终态 | 耗时 | 工具 | 字数 | 严格判定 | 备注 |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        note = (r.get("error") or "").replace("|", "/")[:50]
        if not note and not strict_ok(r):
            note = (r.get("sample") or "")[:40].replace("\n", " ")
        out.append(
            f"| {r['task_id']} | {r['engine']} | {r['status']} | {r['duration_s']}s | {r['tools']} | "
            f"{r['chars']} | {'✅' if strict_ok(r) else '❌'} | {note} |"
        )
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("json_file", nargs="?", help="bench_engines.py --out-json 产物")
    ap.add_argument("--jsonl", default="")
    ap.add_argument("--since", default="")
    ap.add_argument("--until", default="")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    if args.json_file:
        with open(args.json_file, encoding="utf-8") as fh:
            payload = json.load(fh)
        rows = payload["rows"]
        meta = payload.get("meta", {})
    elif args.jsonl:
        rows = []
        for line in open(args.jsonl, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            ts = str(row.get("ts") or "")
            if args.since and ts < args.since:
                continue
            if args.until and ts > args.until:
                continue
            rows.append(row)
        meta = {"started": args.since or "?", "finished": args.until or datetime.now().isoformat(timespec="seconds")}
    else:
        print("需要 json 文件或 --jsonl", file=sys.stderr)
        return 64
    rows = [r for r in rows if r.get("engine") in ("legacy", "hermes")]
    text = render(rows, meta)
    print(text)
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"[report] 已写 {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
