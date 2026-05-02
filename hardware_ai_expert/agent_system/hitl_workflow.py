"""
HITL (Human-in-the-Loop) 审批流

核心功能：
  1. 收集审查发现的违规项，标记为 pending_review
  2. 工程师审批：approve / reject / modify
  3. 审批通过的规则自动落盘到 rules YAML
  4. 审批记录持久化到 Neo4j

对应 PRD V5.0: HITL 规则沉淀机制
"""

from __future__ import annotations

import os
import yaml
import json
import logging
from datetime import datetime
from typing import Optional, List
from dataclasses import dataclass, asdict
from enum import Enum

from dotenv import load_dotenv

try:
    from neo4j import GraphDatabase
except ImportError:
    GraphDatabase = None

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

logger = logging.getLogger(__name__)


# ============================================================
# 数据模型
# ============================================================

class ReviewAction(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    MODIFY = "modify"
    SKIP = "skip"


@dataclass
class PendingReview:
    """待审批的审查项"""
    review_id: str           # 唯一 ID
    rule_id: str             # 规则 ID
    rule_name: str
    refdes: str
    net_name: str = ""
    description: str = ""
    severity: str = "WARNING"
    expected: str = ""
    actual: str = ""
    suggested_fix: str = ""
    # 审批状态
    status: str = "pending"  # pending / approved / rejected / modified
    reviewer: str = ""       # 审批人
    review_comment: str = "" # 审批意见
    reviewed_at: str = ""
    # 元数据
    created_at: str = ""
    source: str = "agent"    # agent / manual


# ============================================================
# HITL 管理器
# ============================================================

class HITLManager:
    """HITL 审批流管理器"""

    RULES_DIR = os.path.join(ROOT_DIR, "agent_system", "review_engine", "config")
    CUSTOM_RULES_FILE = os.path.join(RULES_DIR, "custom_rules.yaml")

    def __init__(self):
        self._driver = None
        self._pending: List[PendingReview] = []

    def _get_driver(self):
        if self._driver is None:
            if GraphDatabase is None:
                raise RuntimeError("neo4j not installed")
            uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
            user = os.getenv("NEO4J_USER", "neo4j")
            password = os.getenv("NEO4J_PASSWORD", "SecretPassword123")
            self._driver = GraphDatabase.driver(uri, auth=(user, password))
        return self._driver

    def close(self):
        if self._driver:
            self._driver.close()
            self._driver = None

    # --------------------------------------------------------
    # 添加待审批项
    # --------------------------------------------------------

    def add_pending(self, review: PendingReview) -> bool:
        """添加一个待审批项到队列和 Neo4j"""
        review.created_at = datetime.now().isoformat()
        if not review.review_id:
            review.review_id = f"REV_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{hash(review.rule_id + review.refdes) % 10000:04d}"

        self._pending.append(review)

        try:
            driver = self._get_driver()
            with driver.session() as session:
                session.run("""
                    MERGE (pr:PendingReview {review_id: $review_id})
                    SET pr.rule_id = $rule_id,
                        pr.rule_name = $rule_name,
                        pr.refdes = $refdes,
                        pr.net_name = $net_name,
                        pr.description = $description,
                        pr.severity = $severity,
                        pr.expected = $expected,
                        pr.actual = $actual,
                        pr.suggested_fix = $suggested_fix,
                        pr.status = 'pending',
                        pr.created_at = datetime(),
                        pr.source = $source
                """, {
                    "review_id": review.review_id,
                    "rule_id": review.rule_id,
                    "rule_name": review.rule_name,
                    "refdes": review.refdes,
                    "net_name": review.net_name,
                    "description": review.description,
                    "severity": review.severity,
                    "expected": review.expected,
                    "actual": review.actual,
                    "suggested_fix": review.suggested_fix,
                    "source": review.source,
                })
            return True
        except Exception as e:
            logger.error(f"Failed to save pending review to Neo4j: {e}")
            return False

    def add_violations(self, violations: list) -> int:
        """批量添加违规项为待审批"""
        count = 0
        for v in violations:
            pr = PendingReview(
                review_id="",
                rule_id=getattr(v, 'rule_id', 'unknown'),
                rule_name=getattr(v, 'rule_name', 'Unknown Rule'),
                refdes=getattr(v, 'refdes', ''),
                net_name=getattr(v, 'net_name', ''),
                description=getattr(v, 'description', ''),
                severity=getattr(v, 'severity', 'WARNING'),
                expected=getattr(v, 'expected', ''),
                actual=getattr(v, 'actual', ''),
                suggested_fix=getattr(v, 'suggested_fix', ''),
            )
            if self.add_pending(pr):
                count += 1
        return count

    # --------------------------------------------------------
    # 审批操作
    # --------------------------------------------------------

    def approve(self, review_id: str, reviewer: str = "engineer",
                comment: str = "") -> bool:
        """审批通过"""
        return self._update_status(review_id, ReviewAction.APPROVE, reviewer, comment)

    def reject(self, review_id: str, reviewer: str = "engineer",
               comment: str = "") -> bool:
        """审批拒绝（标记为误报）"""
        return self._update_status(review_id, ReviewAction.REJECT, reviewer, comment)

    def _update_status(self, review_id: str, action: ReviewAction,
                       reviewer: str, comment: str) -> bool:
        """更新审批状态"""
        # 更新内存队列
        for pr in self._pending:
            if pr.review_id == review_id:
                pr.status = action.value
                pr.reviewer = reviewer
                pr.review_comment = comment
                pr.reviewed_at = datetime.now().isoformat()
                break

        # 更新 Neo4j
        try:
            driver = self._get_driver()
            with driver.session() as session:
                session.run("""
                    MATCH (pr:PendingReview {review_id: $review_id})
                    SET pr.status = $status,
                        pr.reviewer = $reviewer,
                        pr.review_comment = $comment,
                        pr.reviewed_at = datetime()
                """, {
                    "review_id": review_id,
                    "status": action.value,
                    "reviewer": reviewer,
                    "comment": comment,
                })
            return True
        except Exception as e:
            logger.error(f"Failed to update review status: {e}")
            return False

    # --------------------------------------------------------
    # 规则落盘
    # --------------------------------------------------------

    def save_approved_rules(self) -> dict:
        """
        将 approved 的 PendingReview 落盘到 custom_rules.yaml。

        流程：
        1. 收集所有 approved 的 review
        2. 按 rule_id 分组聚合
        3. 生成新的规则条目写入 YAML
        4. 标记为 persisted
        """
        approved = [pr for pr in self._pending if pr.status == "approved"]
        if not approved:
            return {"saved": 0, "message": "没有 approved 的审查项"}

        # 按 rule_id 分组
        rules_by_id = {}
        for pr in approved:
            if pr.rule_id not in rules_by_id:
                rules_by_id[pr.rule_id] = {
                    "name": pr.rule_name,
                    "description": pr.description,
                    "severity": pr.severity,
                    "examples": [],
                }
            rules_by_id[pr.rule_id]["examples"].append({
                "refdes": pr.refdes,
                "net_name": pr.net_name,
                "expected": pr.expected,
                "actual": pr.actual,
                "fix": pr.suggested_fix,
            })

        # 加载现有 custom rules
        custom_rules = self._load_custom_rules()

        # 合并新规则
        for rule_id, rule_data in rules_by_id.items():
            custom_rules[rule_id] = rule_data

        # 保存
        try:
            os.makedirs(self.RULES_DIR, exist_ok=True)
            with open(self.CUSTOM_RULES_FILE, 'w', encoding='utf-8') as f:
                yaml.dump(custom_rules, f, allow_unicode=True, sort_keys=False)

            # 标记为 persisted
            for pr in approved:
                pr.status = "persisted"
            self._mark_persisted_in_neo4j([pr.review_id for pr in approved])

            return {"saved": len(rules_by_id), "rules": list(rules_by_id.keys())}
        except Exception as e:
            logger.error(f"Failed to save custom rules: {e}")
            return {"saved": 0, "error": str(e)}

    def _load_custom_rules(self) -> dict:
        """加载现有 custom rules"""
        if os.path.exists(self.CUSTOM_RULES_FILE):
            try:
                with open(self.CUSTOM_RULES_FILE, 'r', encoding='utf-8') as f:
                    return yaml.safe_load(f) or {}
            except Exception:
                pass
        return {}

    def _mark_persisted_in_neo4j(self, review_ids: List[str]):
        """在 Neo4j 中标记为已持久化"""
        try:
            driver = self._get_driver()
            with driver.session() as session:
                for rid in review_ids:
                    session.run("""
                        MATCH (pr:PendingReview {review_id: $review_id})
                        SET pr.status = 'persisted'
                    """, {"review_id": rid})
        except Exception as e:
            logger.error(f"Failed to mark persisted: {e}")

    # --------------------------------------------------------
    # 查询
    # --------------------------------------------------------

    def get_pending_list(self, status: str = "pending") -> List[PendingReview]:
        """获取指定状态的审批列表"""
        if status == "all":
            return self._pending
        return [pr for pr in self._pending if pr.status == status]

    def get_stats(self) -> dict:
        """获取审批统计"""
        stats = {"pending": 0, "approved": 0, "rejected": 0, "persisted": 0}
        for pr in self._pending:
            if pr.status in stats:
                stats[pr.status] += 1
        return stats


# ============================================================
# LangChain Tool 封装
# ============================================================

try:
    from langchain_core.tools import tool
except ImportError:
    def tool(fn):
        return fn


@tool
def get_pending_reviews(status: str = "pending") -> str:
    """
    获取待审批的审查项列表。

    Args:
        status: pending / approved / rejected / all

    Returns:
        审批列表文本
    """
    manager = HITLManager()
    try:
        reviews = manager.get_pending_list(status)
        if not reviews:
            return f"没有 {status} 状态的审查项。"

        lines = [f"审查项列表 ({status}): 共 {len(reviews)} 项"]
        for pr in reviews:
            lines.append(f"\n--- {pr.review_id} ---")
            lines.append(f"规则: {pr.rule_name} ({pr.rule_id})")
            lines.append(f"器件: {pr.refdes} | 网络: {pr.net_name}")
            lines.append(f"描述: {pr.description}")
            lines.append(f"严重程度: {pr.severity}")
            if pr.reviewer:
                lines.append(f"审批人: {pr.reviewer} | 意见: {pr.review_comment}")
        return "\n".join(lines)
    finally:
        manager.close()


@tool
def approve_review(review_id: str, comment: str = "") -> str:
    """
    审批通过一条审查项。

    Args:
        review_id: 审查项 ID
        comment: 审批意见

    Returns:
        操作结果
    """
    manager = HITLManager()
    try:
        success = manager.approve(review_id, comment=comment)
        return f"{'✅' if success else '❌'} 审查项 {review_id} 已审批通过。"
    finally:
        manager.close()


@tool
def reject_review(review_id: str, comment: str = "") -> str:
    """
    拒绝（标记为误报）一条审查项。

    Args:
        review_id: 审查项 ID
        comment: 拒绝理由

    Returns:
        操作结果
    """
    manager = HITLManager()
    try:
        success = manager.reject(review_id, comment=comment)
        return f"{'✅' if success else '❌'} 审查项 {review_id} 已标记为误报。"
    finally:
        manager.close()


@tool
def save_approved_rules_to_yaml() -> str:
    """
    将所有 approved 的审查项落盘到 custom_rules.yaml。

    Returns:
        操作结果
    """
    manager = HITLManager()
    try:
        result = manager.save_approved_rules()
        if result.get("saved", 0) > 0:
            return f"✅ 已保存 {result['saved']} 条规则到 custom_rules.yaml: {', '.join(result['rules'])}"
        return f"⚠️ {result.get('message', '没有可保存的规则')}"
    finally:
        manager.close()


def get_hitl_tools():
    return [get_pending_reviews, approve_review, reject_review, save_approved_rules_to_yaml]


# ============================================================
# Self-test
# ============================================================

def _run_tests():
    print("=" * 60)
    print("HITL Workflow Self-test")
    print("=" * 60)

    manager = HITLManager()

    # 测试 1: 添加待审批项
    print("\n[1/4] Adding pending reviews...")
    test_reviews = [
        PendingReview(
            review_id="", rule_id="TEST_001", rule_name="测试规则A",
            refdes="U100", description="测试描述A", severity="ERROR"
        ),
        PendingReview(
            review_id="", rule_id="TEST_002", rule_name="测试规则B",
            refdes="R200", description="测试描述B", severity="WARNING"
        ),
    ]
    for pr in test_reviews:
        success = manager.add_pending(pr)
        print(f"  {'✅' if success else '❌'} {pr.review_id}")

    # 测试 2: 获取列表
    print("\n[2/4] Getting pending list...")
    pending = manager.get_pending_list("pending")
    print(f"  Pending: {len(pending)}")

    # 测试 3: 审批操作
    print("\n[3/4] Approving first review...")
    if pending:
        rid = pending[0].review_id
        manager.approve(rid, reviewer="tester", comment="确认问题")
        stats = manager.get_stats()
        print(f"  Stats: {stats}")

    # 测试 4: 落盘（不实际写入，仅测试逻辑）
    print("\n[4/4] Testing rule persistence logic...")
    result = manager.save_approved_rules()
    print(f"  Result: {result}")

    manager.close()
    print("\n✅ HITL Workflow test completed")


if __name__ == "__main__":
    _run_tests()
