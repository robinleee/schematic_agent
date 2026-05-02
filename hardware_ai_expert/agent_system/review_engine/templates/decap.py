"""
去耦电容检查模板

检查电源引脚是否配置了足够数量和正确容值的去耦电容。
"""

from __future__ import annotations

import re
from typing import Any

from agent_system.review_engine.templates.base import RuleTemplate, RuleContext, TemplateRegistry
from agent_system.schemas import Violation


# ============================================
# 容值解析工具
# ============================================

def parse_capacitance(value_str: str) -> float | None:
    """解析电容值 → 法拉"""
    if not value_str:
        return None
    s = value_str.upper().strip()

    multipliers = {"PF": 1e-12, "NF": 1e-9, "UF": 1e-6, "MF": 1e-3, "F": 1.0}
    for suffix, mult in sorted(multipliers.items(), key=lambda x: -len(x[0])):
        if suffix in s:
            num = re.sub(r"[^0-9.]", "", s.split(suffix)[0])
            try:
                return float(num) * mult if num else None
            except ValueError:
                return None
    return None


def normalize_cap_value(value_str: str) -> str | None:
    """将容值统一归一化为字符串（如 0.1uF）用于比较"""
    farad = parse_capacitance(value_str)
    if farad is None:
        return None
    if farad >= 1e-6:
        return f"{farad / 1e-6:.1f}uF".replace(".0", "")
    elif farad >= 1e-9:
        return f"{farad / 1e-9:.1f}nF".replace(".0", "")
    else:
        return f"{farad / 1e-12:.1f}pF".replace(".0", "")


# ============================================
# DecapCheckTemplate
# ============================================

class DecapCheckTemplate(RuleTemplate):
    """
    电源去耦电容检查模板

    参数:
        voltage_level: str    电压等级 (如 "3.3", "1.8")
        min_count: int        最少电容数量
        required_values: list 要求的具体容值列表 (如 ["0.1uF", "10uF"])
        applicable_parts: list 适用的器件类型 (如 ["IC", "MCU", "FPGA"])
        net_patterns: list    网络名称匹配模式
        search_radius: int    搜索范围（网络跳数，默认1）
    """

    template_id = "decap_check"
    name = "电源去耦电容检查"
    description = "检查电源引脚是否配置了足够的去耦电容"
    default_severity = "WARNING"

    def check(self, params: dict, context: RuleContext) -> list[Violation]:
        violations = []

        voltage_level = params.get("voltage_level", "")
        min_count = params.get("min_count", 1)
        required_values = params.get("required_values", [])
        applicable_parts = params.get("applicable_parts", ["IC", "MCU", "FPGA", "SOC"])
        net_patterns = params.get("net_patterns", [voltage_level])
        rule_id = params.get("rule_id", self.template_id)
        severity = params.get("severity", self.default_severity)

        driver = context.neo4j_driver

        # 1. 查找目标电压网络
        cypher_nets = """
        MATCH (n:Net)
        WHERE n.VoltageLevel = $voltage_level
           OR ANY(pattern IN $patterns WHERE n.Name CONTAINS pattern)
        RETURN n.Name AS net_name, n.VoltageLevel AS voltage
        """

        with driver.session() as session:
            nets = list(session.run(cypher_nets, {
                "voltage_level": voltage_level,
                "patterns": net_patterns,
            }))

        if not nets:
            return violations

        for net_record in nets:
            net_name = net_record["net_name"]

            # 2. 查找该网络上连接的 IC 类器件
            # 策略 A: 先尝试通过 POWER 引脚查找（数据质量高时）
            cypher_ics_power = """
            MATCH (n:Net {Name: $net_name})<-[:CONNECTS_TO]-(p:Pin)<-[:HAS_PIN]-(c:Component)
            WHERE p.Type = 'POWER'
              AND ANY(pt IN $part_types WHERE c.PartType CONTAINS pt)
            RETURN DISTINCT c.RefDes AS refdes, c.PartType AS part_type, c.Model AS model
            """

            # 策略 B: Pin.Type 缺失时的兜底：直接查找网络上的所有 IC
            cypher_ics_fallback = """
            MATCH (n:Net {Name: $net_name})<-[:CONNECTS_TO]-(p:Pin)<-[:HAS_PIN]-(c:Component)
            WHERE ANY(pt IN $part_types WHERE c.PartType CONTAINS pt)
            RETURN DISTINCT c.RefDes AS refdes, c.PartType AS part_type, c.Model AS model
            """

            with driver.session() as session:
                ics = list(session.run(cypher_ics_power, {
                    "net_name": net_name,
                    "part_types": applicable_parts,
                }))

            if not ics:
                # 兜底：不限制 Pin.Type
                with driver.session() as session:
                    ics = list(session.run(cypher_ics_fallback, {
                        "net_name": net_name,
                        "part_types": applicable_parts,
                    }))

            # 3. 检查该网络上的去耦电容（网络级别检查）
            cypher_caps = """
            MATCH (n:Net {Name: $net_name})<-[:CONNECTS_TO]-(p:Pin)<-[:HAS_PIN]-(c:Component)
            WHERE c.PartType CONTAINS 'CAP'
            RETURN c.RefDes AS cap_refdes, c.Value AS cap_value, c.Model AS cap_model
            """

            with driver.session() as session:
                caps = list(session.run(cypher_caps, {"net_name": net_name}))

            cap_count = len(caps)
            cap_values = [c["cap_value"] for c in caps if c["cap_value"]]

            # 检查数量（以网络为单位）
            if cap_count < min_count:
                # 找一个代表性器件作为 refdes
                representative = ics[0]["refdes"] if ics else "网络"
                part_type = ics[0].get("part_type", "") if ics else ""

                violations.append(Violation(
                    id=f"{rule_id}_{net_name}",
                    rule_id=rule_id,
                    rule_name=params.get("rule_name", self.name),
                    refdes=representative,
                    net_name=net_name,
                    description=f"{voltage_level}V 电源网络 '{net_name}'({part_type}) 去耦电容数量不足",
                    severity=severity,
                    expected=f"至少 {min_count} 个去耦电容",
                    actual=f"找到 {cap_count} 个: {', '.join(cap_values) if cap_values else '无'}",
                ))
                continue

            # 4. 检查容值（如果有 required_values 要求）
            if required_values:
                normalized_required = set()
                for rv in required_values:
                    nv = normalize_cap_value(rv)
                    if nv:
                        normalized_required.add(nv)

                found_values = set()
                for cv in cap_values:
                    nv = normalize_cap_value(cv)
                    if nv:
                        found_values.add(nv)

                missing = normalized_required - found_values
                if missing:
                    representative = ics[0]["refdes"] if ics else "网络"
                    violations.append(Violation(
                        id=f"{rule_id}_{net_name}_value",
                        rule_id=rule_id,
                        rule_name=params.get("rule_name", self.name),
                        refdes=representative,
                        net_name=net_name,
                        description=f"{voltage_level}V 电源网络 '{net_name}' 缺少指定容值的去耦电容",
                        severity=severity,
                        expected=f"需要容值: {', '.join(sorted(normalized_required))}",
                        actual=f"实际容值: {', '.join(sorted(found_values)) if found_values else '无'}",
                    ))

        return violations


# 注册模板
TemplateRegistry.register(DecapCheckTemplate())


# ============================================
# Self-test
# ============================================

if __name__ == "__main__":
    print("[DecapCheckTemplate] Self-test")

    # 测试容值解析
    assert abs(parse_capacitance("0.1uF") - 0.1e-6) < 1e-20
    assert abs(parse_capacitance("10uF") - 10e-6) < 1e-20
    assert abs(parse_capacitance("100nF") - 100e-9) < 1e-20
    assert abs(parse_capacitance("10pF") - 10e-12) < 1e-20
    print("  ✅ 容值解析测试通过")

    assert normalize_cap_value("0.1uF") == "100nF"
    assert normalize_cap_value("100nF") == "100nF"
    assert normalize_cap_value("10uF") == "10uF"
    print("  ✅ 容值归一化测试通过")

    # 测试模板注册
    tmpl = TemplateRegistry.get("decap_check")
    assert tmpl is not None
    assert tmpl.template_id == "decap_check"
    print("  ✅ 模板注册测试通过")

    print("[DecapCheckTemplate] All tests passed")
