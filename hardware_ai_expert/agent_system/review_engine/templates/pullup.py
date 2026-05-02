"""
上拉/终端电阻检查模板

检查总线是否配置了合理的上拉电阻或终端电阻。
支持两种模式：
- pullup: 上拉电阻，检查阻值是否在 [min_ohm, max_ohm] 范围内
- termination: 终端电阻，检查阻值是否接近 expected_ohm（含容差）
"""

from __future__ import annotations

import re
from typing import Literal

from agent_system.review_engine.templates.base import RuleTemplate, RuleContext, TemplateRegistry
from agent_system.schemas import Violation


# ============================================
# 阻值解析工具
# ============================================

def parse_resistance(value_str: str) -> float | None:
    """解析电阻值 → 欧姆"""
    if not value_str:
        return None
    s = value_str.upper().strip()

    # 跳过 DNP/NC 标记
    if s.startswith("DNP_"):
        s = s[4:]
    if s.startswith("NC_"):
        s = s[3:]

    multipliers = {"K": 1e3, "M": 1e6, "G": 1e9}
    for suffix, mult in multipliers.items():
        if suffix in s:
            num = re.sub(r"[^0-9.]", "", s.split(suffix)[0])
            try:
                return float(num) * mult if num else None
            except ValueError:
                return None

    # 纯数字
    num = re.sub(r"[^0-9.]", "", s)
    try:
        val = float(num) if num else None
        # 0 欧姆视为跳线，跳过
        return val if val and val > 0 else None
    except ValueError:
        return None


def format_ohm(ohm: float) -> str:
    """格式化阻值显示"""
    if ohm >= 1e6:
        return f"{ohm / 1e6:.2f}MΩ"
    elif ohm >= 1e3:
        return f"{ohm / 1e3:.1f}kΩ"
    return f"{ohm:.1f}Ω"


# ============================================
# PullupCheckTemplate
# ============================================

class PullupCheckTemplate(RuleTemplate):
    """
    上拉/终端电阻检查模板

    参数:
        net_patterns: list[str]     网络名称匹配模式
        check_mode: str             "pullup" | "termination"
        min_ohm: int                pullup 模式：最小阻值
        max_ohm: int                pullup 模式：最大阻值
        expected_ohm: int           termination 模式：目标阻值
        tolerance_pct: int          termination 模式：容差百分比
    """

    template_id = "pullup_check"
    name = "上拉/终端电阻检查"
    description = "检查总线是否配置了合理阻值的上拉或终端电阻"
    default_severity = "WARNING"

    def check(self, params: dict, context: RuleContext) -> list[Violation]:
        violations = []

        net_patterns = params.get("net_patterns", [])
        check_mode = params.get("check_mode", "pullup")
        rule_id = params.get("rule_id", self.template_id)
        severity = params.get("severity", self.default_severity)
        rule_name = params.get("rule_name", self.name)

        if not net_patterns:
            return violations

        driver = context.neo4j_driver

        # 1. 查找目标网络
        cypher_nets = """
        MATCH (n:Net)
        WHERE ANY(pattern IN $patterns WHERE n.Name CONTAINS pattern)
        RETURN n.Name AS net_name
        """

        with driver.session() as session:
            nets = list(session.run(cypher_nets, {"patterns": net_patterns}))

        for net_record in nets:
            net_name = net_record["net_name"]

            # 2. 查找网络上的电阻器件
            cypher_res = """
            MATCH (n:Net {Name: $net_name})<-[:CONNECTS_TO]-(p:Pin)<-[:HAS_PIN]-(c:Component)
            WHERE c.PartType CONTAINS 'RES'
            RETURN c.RefDes AS res_refdes, c.Value AS res_value, c.Model AS res_model
            """

            with driver.session() as session:
                resistors = list(session.run(cypher_res, {"net_name": net_name}))

            # 3. 按模式检查
            if check_mode == "termination":
                violations.extend(
                    self._check_termination(
                        net_name, resistors, params, rule_id, rule_name, severity
                    )
                )
            else:  # pullup
                violations.extend(
                    self._check_pullup(
                        net_name, resistors, params, rule_id, rule_name, severity
                    )
                )

        return violations

    def _check_pullup(
        self,
        net_name: str,
        resistors: list[dict],
        params: dict,
        rule_id: str,
        rule_name: str,
        severity: str,
    ) -> list[Violation]:
        """上拉电阻模式：检查是否有阻值在范围内的电阻"""
        violations = []
        min_ohm = params.get("min_ohm", 1000)
        max_ohm = params.get("max_ohm", 47000)

        valid_resistors = []
        for res in resistors:
            val_str = res.get("res_value", "")
            ohm = parse_resistance(val_str)
            if ohm is not None:
                valid_resistors.append((res, ohm))

        # 检查是否有任一电阻在合理范围内
        has_valid = any(min_ohm <= ohm <= max_ohm for _, ohm in valid_resistors)

        if not has_valid:
            res_descs = [
                f"{r['res_refdes']}({r['res_value']})"
                for r in resistors
            ]
            actual_str = ", ".join(res_descs) if res_descs else "无上拉电阻"

            violations.append(Violation(
                id=f"{rule_id}_{net_name}",
                rule_id=rule_id,
                rule_name=rule_name,
                refdes="总线",
                net_name=net_name,
                description=f"网络 '{net_name}' 未检测到合理阻值的上拉电阻",
                severity=severity,
                expected=f"阻值在 {format_ohm(min_ohm)} ~ {format_ohm(max_ohm)} 之间",
                actual=actual_str,
            ))

        return violations

    def _check_termination(
        self,
        net_name: str,
        resistors: list[dict],
        params: dict,
        rule_id: str,
        rule_name: str,
        severity: str,
    ) -> list[Violation]:
        """终端电阻模式：检查是否有阻值接近目标值的电阻"""
        violations = []
        expected_ohm = params.get("expected_ohm", 120)
        tolerance_pct = params.get("tolerance_pct", 5)

        tolerance_ratio = tolerance_pct / 100.0
        min_ok = expected_ohm * (1 - tolerance_ratio)
        max_ok = expected_ohm * (1 + tolerance_ratio)

        valid_resistors = []
        for res in resistors:
            val_str = res.get("res_value", "")
            ohm = parse_resistance(val_str)
            if ohm is not None:
                valid_resistors.append((res, ohm))

        has_valid = any(min_ok <= ohm <= max_ok for _, ohm in valid_resistors)

        if not has_valid:
            res_descs = [
                f"{r['res_refdes']}({r['res_value']})"
                for r in resistors
            ]
            actual_str = ", ".join(res_descs) if res_descs else "无终端电阻"

            violations.append(Violation(
                id=f"{rule_id}_{net_name}",
                rule_id=rule_id,
                rule_name=rule_name,
                refdes="总线",
                net_name=net_name,
                description=f"网络 '{net_name}' 未检测到正确阻值的终端电阻",
                severity=severity,
                expected=f"{expected_ohm}Ω ± {tolerance_pct}% ({format_ohm(min_ok)} ~ {format_ohm(max_ok)})",
                actual=actual_str,
            ))

        return violations


# 注册模板
TemplateRegistry.register(PullupCheckTemplate())


# ============================================
# Self-test
# ============================================

if __name__ == "__main__":
    print("[PullupCheckTemplate] Self-test")

    # 测试阻值解析
    assert parse_resistance("10k") == 10000.0
    assert parse_resistance("4.7k") == 4700.0
    assert parse_resistance("1M") == 1e6
    assert parse_resistance("120") == 120.0
    assert parse_resistance("DNP_10k") == 10000.0
    print("  ✅ 阻值解析测试通过")

    # 测试格式化
    assert format_ohm(1000) == "1.0kΩ"
    assert format_ohm(120) == "120.0Ω"
    print("  ✅ 阻值格式化测试通过")

    # 测试模板注册
    tmpl = TemplateRegistry.get("pullup_check")
    assert tmpl is not None
    assert tmpl.template_id == "pullup_check"
    print("  ✅ 模板注册测试通过")

    print("[PullupCheckTemplate] All tests passed")
