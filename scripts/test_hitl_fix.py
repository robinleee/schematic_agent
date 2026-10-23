#!/usr/bin/env python3
"""验证 HITL 审批工具修复：状态失败时不谎报成功 + 项目作用域生效。

用法：cd hardware_ai_expert && PYTHONPATH=. ../.venv/bin/python ../scripts/test_hitl_fix.py
"""
import os
import sys
import time

os.environ.setdefault("PYTHONPATH", ".")

from agent_system.hitl_workflow import (  # noqa: E402
    HITLManager,
    PendingReview,
    approve_review,
    reject_review,
    get_pending_reviews,
)

PID = "legacy"
TAG = f"TESTFIX_{int(time.time())}"
FAILS = []


def check(label, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {label}{(' | ' + detail) if detail else ''}")
    if not cond:
        FAILS.append(label)


def add_review(rid, rule_id="TEST_RULE_FIX"):
    m = HITLManager(project_id=PID)
    try:
        ok = m.add_pending(PendingReview(
            review_id=rid, rule_id=rule_id, rule_name="联调测试规则",
            refdes="U1", net_name="VCC_TEST", description="仅用于验证审批工具",
            severity="INFO",
        ))
        return ok
    finally:
        m.close()


def status_of(rid):
    m = HITLManager(project_id=PID)
    try:
        rows = m.load_pending("all")
        for r in rows:
            if r.review_id == rid:
                return r.status
        return None
    finally:
        m.close()


def cleanup(*rids):
    from neo4j import GraphDatabase
    drv = GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD")),
    )
    with drv.session() as s:
        s.run("MATCH (pr:PendingReview) WHERE pr.review_id IN $ids DETACH DELETE pr", {"ids": list(rids)})
    drv.close()


def main():
    r1, r2 = f"{TAG}_A", f"{TAG}_B"
    try:
        check("建单 A（项目作用域）", add_review(r1))
        check("建单 B（项目作用域）", add_review(r2))

        out = approve_review.invoke({"review_id": r1, "comment": "同意", "project_id": PID})
        print("   approve#1 ->", out)
        check("批准成功时显示 ✅", out.startswith("✅"), out)
        check("DB 状态变为 approved", status_of(r1) == "approved", str(status_of(r1)))

        out = approve_review.invoke({"review_id": r1, "comment": "再来一次", "project_id": PID})
        print("   approve#2 ->", out)
        check("重复批准显示 ❌ 且说明未更新", out.startswith("❌") and "未更新" in out, out)

        out = reject_review.invoke({"review_id": r2, "comment": "误报", "project_id": PID})
        print("   reject   ->", out)
        check("拒绝成功时显示 ✅", out.startswith("✅"), out)
        check("DB 状态变为 rejected", status_of(r2) == "rejected", str(status_of(r2)))

        out = approve_review.invoke({"review_id": "NO_SUCH_REVIEW_XYZ", "project_id": PID})
        print("   不存在 ->", out)
        check("不存在的 ID 显示 ❌ 且给出原因", out.startswith("❌") and "不存在" in out, out)

        out = get_pending_reviews.invoke({"status": "all", "project_id": PID})
        check("项目作用域能读到刚建的单", r1 in out and r2 in out, out.splitlines()[0] if out else "")

        out_shared = get_pending_reviews.invoke({"status": "all"})
        check("不传 project_id 时只读 shared 作用域", TAG not in out_shared,
              out_shared.splitlines()[0] if out_shared else "")
    finally:
        cleanup(r1, r2)
        left = status_of(r1)
        check("清理测试数据", left is None, str(left))

    print("\n" + ("全部通过" if not FAILS else f"失败 {len(FAILS)} 项: {FAILS}"))
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
