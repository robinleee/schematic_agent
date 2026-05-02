"""
白名单管理

支持：
- 从 Neo4j 加载白名单
- 添加/查询/删除白名单条目
- 违规检查时自动过滤已白名单的条目

白名单节点：`ReviewWhitelist {rule, refdes, status, reason, added_by, added_at}`
"""

from __future__ import annotations

from typing import Any
from datetime import datetime

from agent_system.schemas import WhitelistEntry


class WhitelistManager:
    """白名单管理器"""

    def __init__(self, neo4j_driver: Any):
        self.driver = neo4j_driver
        self._cache: dict[tuple[str, str], WhitelistEntry] = {}
        self._loaded = False

    def load(self) -> dict[tuple[str, str], WhitelistEntry]:
        """从 Neo4j 加载所有白名单条目到内存缓存"""
        self._cache.clear()

        cypher = """
        MATCH (w:ReviewWhitelist)
        RETURN w.rule AS rule_id,
               w.refdes AS refdes,
               w.status AS status,
               w.reason AS reason,
               w.added_by AS added_by,
               w.added_at AS added_at
        """

        with self.driver.session() as session:
            results = list(session.run(cypher))

        for r in results:
            key = (r["rule_id"], r["refdes"])
            entry = WhitelistEntry(
                rule_id=r["rule_id"],
                refdes=r["refdes"],
                status=r["status"] or "IGNORE",
                reason=r["reason"],
                added_by=r["added_by"] or "system",
                added_at=r["added_at"] or datetime.now().isoformat(),
            )
            self._cache[key] = entry

        self._loaded = True
        return self._cache

    def is_whitelisted(self, rule_id: str, refdes: str) -> bool:
        """检查指定规则+器件是否已在白名单中"""
        if not self._loaded:
            self.load()
        return (rule_id, refdes) in self._cache

    def filter_violations(self, violations: list) -> list:
        """过滤掉已在白名单中的违规项"""
        if not self._loaded:
            self.load()

        filtered = []
        skipped = 0
        for v in violations:
            key = (v.rule_id, v.refdes)
            if key in self._cache:
                skipped += 1
                continue
            filtered.append(v)

        if skipped:
            print(f"[Whitelist] 已过滤 {skipped} 个白名单违规")
        return filtered

    def add(self, entry: WhitelistEntry) -> bool:
        """添加白名单条目到 Neo4j"""
        cypher, params = entry.to_cypher()

        try:
            with self.driver.session() as session:
                session.run(cypher, **params)

            # 更新缓存
            key = (entry.rule_id, entry.refdes)
            self._cache[key] = entry
            return True
        except Exception as e:
            print(f"[Whitelist] 添加失败: {e}")
            return False

    def add_by_violation(
        self,
        violation: Any,
        reason: str = "",
        added_by: str = "engineer",
    ) -> bool:
        """根据违规项快速添加到白名单"""
        entry = WhitelistEntry(
            rule_id=violation.rule_id,
            refdes=violation.refdes,
            status="IGNORE",
            reason=reason or violation.description[:200],
            added_by=added_by,
        )
        return self.add(entry)

    def remove(self, rule_id: str, refdes: str) -> bool:
        """从 Neo4j 删除白名单条目"""
        cypher = """
        MATCH (w:ReviewWhitelist {rule: $rule_id, refdes: $refdes})
        DELETE w
        """

        try:
            with self.driver.session() as session:
                session.run(cypher, rule_id=rule_id, refdes=refdes)

            # 更新缓存
            key = (rule_id, refdes)
            self._cache.pop(key, None)
            return True
        except Exception as e:
            print(f"[Whitelist] 删除失败: {e}")
            return False

    def list_all(self) -> list[WhitelistEntry]:
        """列出所有白名单条目"""
        if not self._loaded:
            self.load()
        return list(self._cache.values())

    def count(self) -> int:
        """白名单条目数"""
        if not self._loaded:
            self.load()
        return len(self._cache)

    def clear_cache(self):
        """清空内存缓存（强制下次重新加载）"""
        self._cache.clear()
        self._loaded = False
