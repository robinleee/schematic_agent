"""
Review Rule Engine - 审查规则引擎总控

三层架构入口：
- Layer 1 (Template): 通过 TemplateRegistry 调用检查逻辑
- Layer 2 (Config): 通过 YAML/JSON 加载规则实例
- Layer 3 (Knowledge): 预留 Datasheet 自动提取扩展点

用法：
    from agent_system.review_engine import ReviewRuleEngine
    engine = ReviewRuleEngine(driver, config_path="config/default_rules.yaml")
    violations = engine.run_rules()
    report = engine.generate_report(violations)
"""

from __future__ import annotations

import os
import yaml
from pathlib import Path
from typing import Any

from agent_system.schemas import Violation, RuleConfig
from agent_system.review_engine.templates.base import RuleContext, TemplateRegistry
from agent_system.review_engine.whitelist import WhitelistManager

# 自动导入并注册所有内置模板
import agent_system.review_engine.templates.decap  # noqa: F401
import agent_system.review_engine.templates.pullup  # noqa: F401
import agent_system.review_engine.templates.esd    # noqa: F401
import agent_system.review_engine.templates.pinmux  # noqa: F401
import agent_system.review_engine.templates.amr    # noqa: F401


# ============================================
# 规则配置管理器
# ============================================

class RuleConfigManager:
    """规则配置管理器：加载、解析、管理 RuleConfig"""

    def __init__(self):
        self._rules: dict[str, RuleConfig] = {}

    def load_from_file(self, path: str | Path):
        """从 YAML/JSON 文件加载规则配置"""
        path = Path(path)

        if not path.exists():
            raise FileNotFoundError(f"规则配置文件不存在: {path}")

        if path.suffix in (".yaml", ".yml"):
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        elif path.suffix == ".json":
            import json
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            raise ValueError(f"不支持的配置文件格式: {path.suffix}")

        rules_data = data.get("rules", [])
        for rule_data in rules_data:
            rule = RuleConfig(**rule_data)
            self._rules[rule.id] = rule

        print(f"[RuleConfig] 已加载 {len(self._rules)} 条规则配置")

    def get(self, rule_id: str) -> RuleConfig | None:
        return self._rules.get(rule_id)

    def list_rules(self, enabled_only: bool = True) -> list[RuleConfig]:
        rules = list(self._rules.values())
        if enabled_only:
            rules = [r for r in rules if r.enabled]
        return rules

    def add_rule(self, rule: RuleConfig):
        self._rules[rule.id] = rule

    def export_to_file(self, path: str | Path):
        """导出规则到 YAML 文件"""
        path = Path(path)
        data = {"rules": [r.model_dump() for r in self._rules.values()]}
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, sort_keys=False)


# ============================================
# ReviewRuleEngine 总控
# ============================================

class ReviewRuleEngine:
    """
    审查规则引擎总控

    Args:
        neo4j_driver: Neo4j 数据库驱动
        config_path: 规则配置文件路径，None 表示不加载配置
    """

    def __init__(
        self,
        neo4j_driver: Any,
        config_path: str | None = None,
    ):
        self.driver = neo4j_driver
        self.context = RuleContext(neo4j_driver=neo4j_driver)
        self.config_manager = RuleConfigManager()
        self.whitelist = WhitelistManager(neo4j_driver)

        # 加载默认配置
        if config_path:
            self.config_manager.load_from_file(config_path)
        else:
            # 尝试加载内置默认配置
            default_path = Path(__file__).parent / "config" / "default_rules.yaml"
            if default_path.exists():
                self.config_manager.load_from_file(default_path)

    def run_rules(
        self,
        rule_ids: list[str] | None = None,
        enabled_only: bool = True,
    ) -> list[Violation]:
        """
        执行规则检查

        Args:
            rule_ids: 指定要执行的规则 ID 列表，None 表示执行全部
            enabled_only: 是否只执行启用的规则

        Returns:
            违规列表（已过滤白名单）
        """
        all_violations: list[Violation] = []

        # 获取规则列表
        if rule_ids:
            rules = []
            for rid in rule_ids:
                r = self.config_manager.get(rid)
                if r:
                    rules.append(r)
                else:
                    print(f"[ReviewEngine] 警告: 规则 '{rid}' 未找到")
        else:
            rules = self.config_manager.list_rules(enabled_only=enabled_only)

        if not rules:
            print("[ReviewEngine] 没有可执行的规则")
            return all_violations

        print(f"[ReviewEngine] 开始执行 {len(rules)} 条规则检查...")

        # 执行每个规则
        for rule in rules:
            violations = self._execute_rule(rule)
            all_violations.extend(violations)

        # 过滤白名单
        filtered = self.whitelist.filter_violations(all_violations)

        print(f"[ReviewEngine] 检查完成: {len(all_violations)} 个原始违规, "
              f"过滤后 {len(filtered)} 个")

        return filtered

    def _execute_rule(self, rule: RuleConfig) -> list[Violation]:
        """执行单条规则"""
        template = TemplateRegistry.get(rule.template_id)

        if not template:
            print(f"[ReviewEngine] 警告: 模板 '{rule.template_id}' 未注册")
            return []

        # 合并参数
        params = {
            **rule.params,
            "rule_id": rule.id,
            "rule_name": rule.name or template.name,
            "severity": rule.severity or template.default_severity,
        }

        try:
            violations = template.check(params, self.context)
            if violations:
                print(f"  [{rule.id}] {rule.name or template.name}: "
                      f"发现 {len(violations)} 个违规")
            return violations
        except Exception as e:
            print(f"[ReviewEngine] 规则 '{rule.id}' 执行失败: {e}")
            return []

    def add_rule(self, rule: RuleConfig):
        """动态添加规则"""
        self.config_manager.add_rule(rule)

    def generate_report(self, violations: list[Violation]) -> str:
        """生成 Markdown 格式审查报告"""
        if not violations:
            return "# 原理图审查报告\n\n✅ 未发现违规，所有检查项通过。\n"

        errors = [v for v in violations if v.severity == "ERROR"]
        warnings = [v for v in violations if v.severity == "WARNING"]
        infos = [v for v in violations if v.severity == "INFO"]

        lines = [
            "# 原理图审查报告\n",
            f"**检查时间:** {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
            f"**发现问题:** {len(violations)} 个\n",
            f"- 🔴 ERROR: {len(errors)} 个\n",
            f"- 🟡 WARNING: {len(warnings)} 个\n",
            f"- 🔵 INFO: {len(infos)} 个\n",
            "\n---\n",
        ]

        # 按严重程度分组输出
        for severity, items in [("ERROR", errors), ("WARNING", warnings), ("INFO", infos)]:
            if not items:
                continue
            lines.append(f"\n## {severity} 级别 ({len(items)} 个)\n")
            for v in items:
                lines.append(f"### [{v.rule_id}] {v.refdes}\n")
                lines.append(f"- **规则:** {v.rule_name}\n")
                lines.append(f"- **描述:** {v.description}\n")
                if v.net_name:
                    lines.append(f"- **网络:** {v.net_name}\n")
                lines.append(f"- **期望:** {v.expected}\n")
                lines.append(f"- **实际:** {v.actual}\n")
                lines.append("\n")

        return "".join(lines)

    def get_summary(self, violations: list[Violation]) -> dict:
        """获取检查结果摘要"""
        errors = sum(1 for v in violations if v.severity == "ERROR")
        warnings = sum(1 for v in violations if v.severity == "WARNING")
        infos = sum(1 for v in violations if v.severity == "INFO")

        # 统计按规则分组
        by_rule: dict[str, int] = {}
        for v in violations:
            by_rule[v.rule_id] = by_rule.get(v.rule_id, 0) + 1

        return {
            "total": len(violations),
            "errors": errors,
            "warnings": warnings,
            "infos": infos,
            "by_rule": by_rule,
            "whitelist_count": self.whitelist.count(),
        }

    def export_rules(self, path: str):
        """导出当前规则配置到文件"""
        self.config_manager.export_to_file(path)

    def list_templates(self) -> list[dict]:
        """列出所有可用模板"""
        return TemplateRegistry.list_templates()

    def list_rules(self, enabled_only: bool = True) -> list[RuleConfig]:
        """列出所有已加载规则"""
        return self.config_manager.list_rules(enabled_only=enabled_only)
