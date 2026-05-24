"""
电压兼容性检查模板

检查器件引脚电压与网络电压的兼容性：
  - 过压检测：网络电压超过器件最大耐压
  - 欠压检测：网络电压低于器件最低工作电压
"""

from __future__ import annotations

import re
import logging

from agent_system.review_engine.templates.base import RuleTemplate, RuleContext, TemplateRegistry
from agent_system.schemas import Violation

logger = logging.getLogger(__name__)


class VoltageCompatibilityCheck(RuleTemplate):
    """
    器件电压兼容性检查模板

    参数:
        max_overvoltage_ratio: float  允许的过压比例（默认 1.1，即 10% 余量）
        check_type: str
            - "overvoltage": 过压检查
            - "undervoltage": 欠压检查
            - "all": 全部检查（默认）
        applicable_parts: list  检查的器件类型（默认 IC/PMIC/MCU 等）
    """

    template_id = "voltage_compatibility_check"
    name = "器件电压兼容性检查"
    description = "检查器件引脚电压与网络电压的兼容性"
    default_severity = "ERROR"

    def check(self, params: dict, context: RuleContext) -> list[Violation]:
        violations = []
        check_type = params.get("check_type", "all")
        max_overvoltage_ratio = params.get("max_overvoltage_ratio", 1.1)
        applicable_parts = params.get("applicable_parts",
                                       ["IC", "PMIC", "MCU", "FPGA", "SOC", "DRAM", "FLASH"])
        rule_id = params.get("rule_id", self.template_id)
        severity = params.get("severity", self.default_severity)

        driver = context.neo4j_driver

        if check_type in ("overvoltage", "all"):
            violations.extend(self._check_overvoltage(
                driver, rule_id, severity, max_overvoltage_ratio, applicable_parts, params
            ))

        if check_type in ("undervoltage", "all"):
            violations.extend(self._check_undervoltage(
                driver, rule_id, severity, applicable_parts, params
            ))

        return violations

    def _check_overvoltage(self, driver, rule_id, severity, max_ratio, applicable_parts, params) -> list[Violation]:
        """过压检查：网络电压 > 器件耐压"""
        violations = []

        # 查询有电压标注的电源网络和连接的 IC
        # 使用 AMR 数据中的 voltage_rating
        part_filter = " OR ".join([f"c.PartType CONTAINS '{pt}'" for pt in applicable_parts])

        cypher = f"""
        MATCH (c:Component)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
        WHERE ({part_filter})
          AND n.VoltageLevel IS NOT NULL
          AND n.NetType = 'POWER'
          AND c.voltage_rating IS NOT NULL
        RETURN c.RefDes AS refdes, c.Model AS model, c.PartType AS part_type,
               c.voltage_rating AS voltage_rating,
               n.Name AS net_name, n.VoltageLevel AS net_voltage,
               p.Number AS pin_number
        """

        try:
            with driver.session() as session:
                results = list(session.run(cypher))
        except Exception as e:
            logger.warning(f"Overvoltage check query failed: {e}")
            return violations

        for r in results:
            net_voltage = self._parse_voltage(r["net_voltage"])
            voltage_rating = self._parse_voltage(r["voltage_rating"])

            if net_voltage is None or voltage_rating is None:
                continue

            # 允许一定过压余量
            if net_voltage > voltage_rating * max_ratio:
                violations.append(Violation(
                    id=f"{rule_id}_{r['refdes']}_{r['net_name']}",
                    rule_id=rule_id,
                    rule_name=params.get("rule_name", self.name),
                    refdes=r["refdes"],
                    net_name=r["net_name"],
                    description=f"器件 {r['refdes']} ({r['model']}) 在 {r['net_name']} 上可能过压",
                    severity=severity,
                    expected=f"工作电压 ≤ {voltage_rating:.1f}V × {max_ratio} = {voltage_rating * max_ratio:.1f}V",
                    actual=f"网络电压 {net_voltage:.1f}V, 器件耐压 {voltage_rating:.1f}V",
                ))

        return violations

    def _check_undervoltage(self, driver, rule_id, severity, applicable_parts, params) -> list[Violation]:
        """欠压检查：网络电压 < 器件最低工作电压"""
        violations = []

        # 使用 min_voltage 属性（如果有）
        part_filter = " OR ".join([f"c.PartType CONTAINS '{pt}'" for pt in applicable_parts])

        cypher = f"""
        MATCH (c:Component)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
        WHERE ({part_filter})
          AND n.VoltageLevel IS NOT NULL
          AND n.NetType = 'POWER'
          AND c.min_voltage IS NOT NULL
        RETURN c.RefDes AS refdes, c.Model AS model, c.PartType AS part_type,
               c.min_voltage AS min_voltage,
               n.Name AS net_name, n.VoltageLevel AS net_voltage
        """

        try:
            with driver.session() as session:
                results = list(session.run(cypher))
        except Exception as e:
            logger.warning(f"Undervoltage check query failed: {e}")
            return violations

        for r in results:
            net_voltage = self._parse_voltage(r["net_voltage"])
            min_voltage = self._parse_voltage(r["min_voltage"])

            if net_voltage is None or min_voltage is None:
                continue

            if net_voltage < min_voltage * 0.9:  # 10% 余量
                violations.append(Violation(
                    id=f"{rule_id}_{r['refdes']}_{r['net_name']}_undervoltage",
                    rule_id=rule_id,
                    rule_name=params.get("rule_name", self.name),
                    refdes=r["refdes"],
                    net_name=r["net_name"],
                    description=f"器件 {r['refdes']} ({r['model']}) 在 {r['net_name']} 上可能欠压",
                    severity="WARNING",
                    expected=f"工作电压 ≥ {min_voltage:.1f}V",
                    actual=f"网络电压 {net_voltage:.1f}V, 器件最低 {min_voltage:.1f}V",
                ))

        return violations

    @staticmethod
    def _parse_voltage(value) -> float | None:
        """解析电压值为浮点数"""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        s = str(value).strip()
        # 移除 V 后缀
        s = re.sub(r'[Vv]$', '', s)
        # 处理 3V3 → 3.3, 1V8 → 1.8
        m = re.match(r'^(\d+)[Vv](\d+)$', s)
        if m:
            return float(f"{m.group(1)}.{m.group(2)}")
        try:
            return float(s)
        except ValueError:
            return None


# 注册模板
TemplateRegistry.register(VoltageCompatibilityCheck())
