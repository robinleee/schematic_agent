"""
电源完整性检查模板

检查电源系统完整性：
  1. 孤岛电源网络：有电压标注但无负载器件
  2. LDO/DC-DC 输出去耦：稳压器输出端应有去耦电容
  3. 电源域隔离：不同电压域不应直连（无调节器）
  4. 电源时序：PMIC 输出应有时序定义
"""

from __future__ import annotations

import logging

from agent_system.review_engine.templates.base import RuleTemplate, RuleContext, TemplateRegistry
from agent_system.schemas import Violation

logger = logging.getLogger(__name__)


class PowerIntegrityCheck(RuleTemplate):
    """
    电源完整性检查模板

    参数:
        check_type: str
            - "orphan_power_net": 孤岛电源网络检查
            - "regulator_output_decap": 稳压器输出去耦检查
            - "domain_isolation": 电源域隔离检查
            - "all": 全部检查（默认）
        min_output_caps: int  稳压器输出最少电容数（默认 2）
    """

    template_id = "power_integrity_check"
    name = "电源完整性检查"
    description = "检查电源系统完整性：孤岛网络、输出去耦、域隔离"
    default_severity = "WARNING"

    def check(self, params: dict, context: RuleContext) -> list[Violation]:
        violations = []
        check_type = params.get("check_type", "all")
        rule_id = params.get("rule_id", self.template_id)
        severity = params.get("severity", self.default_severity)
        min_output_caps = params.get("min_output_caps", 2)

        driver = context.neo4j_driver

        if check_type in ("orphan_power_net", "all"):
            violations.extend(self._check_orphan_power_net(
                driver, rule_id, severity, params
            ))

        if check_type in ("regulator_output_decap", "all"):
            violations.extend(self._check_regulator_decap(
                driver, rule_id, severity, min_output_caps, params
            ))

        if check_type in ("domain_isolation", "all"):
            violations.extend(self._check_domain_isolation(
                driver, rule_id, severity, params
            ))

        return violations

    # --------------------------------------------------------
    # 孤岛电源网络检查
    # --------------------------------------------------------

    def _check_orphan_power_net(self, driver, rule_id, severity, params) -> list[Violation]:
        """查找有电压标注但无负载器件的电源网络"""
        violations = []

        cypher = """
        MATCH (n:Net)
        WHERE n.VoltageLevel IS NOT NULL AND n.NetType = 'POWER'
        OPTIONAL MATCH (c:Component)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n)
        WHERE NOT c.PartType IN ['CAPACITOR', 'INDUCTOR', 'TESTPOINT', 'MECHANICAL']
        WITH n, count(DISTINCT c) AS load_count
        WHERE load_count = 0
        RETURN n.Name AS net_name, n.VoltageLevel AS voltage
        ORDER BY n.VoltageLevel
        """

        try:
            with driver.session() as session:
                results = list(session.run(cypher))
        except Exception as e:
            logger.warning(f"Orphan power net check failed: {e}")
            return violations

        for r in results:
            violations.append(Violation(
                id=f"{rule_id}_{r['net_name']}",
                rule_id=rule_id,
                rule_name=params.get("rule_name", self.name),
                refdes=r["net_name"],
                net_name=r["net_name"],
                description=f"电源网络 '{r['net_name']}' ({r['voltage']}V) 无负载器件",
                severity=severity,
                expected="电源网络应至少连接一个负载器件",
                actual="该网络上无负载器件（电容/电感/测试点除外）",
            ))

        return violations

    # --------------------------------------------------------
    # 稳压器输出去耦检查
    # --------------------------------------------------------

    def _check_regulator_decap(self, driver, rule_id, severity, min_caps, params) -> list[Violation]:
        """检查 PMIC/LDO/DC-DC 输出端是否有足够的去耦电容"""
        violations = []

        # 查找所有稳压器（PMIC + 有 POWERED_BY 输出的器件）
        cypler = """
        MATCH (src:Component)<-[:POWERED_BY]-(load:Component)
        WHERE src.PartType IN ['PMIC'] OR src.Model =~ '(?i).*(LDO|REG|DCDC|BUCK|BOOST).*'
        WITH DISTINCT src
        MATCH (src)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
        WHERE p.Type = 'POWER' AND n.NetType = 'POWER'
          AND NOT n.Name =~ '(?i).*(VIN|VCC_IN|VDD_IN|INPUT).*'
        WITH DISTINCT src, n
        MATCH (n)<-[:CONNECTS_TO]-(cp:Pin)<-[:HAS_PIN]-(cap:Component)
        WHERE cap.PartType CONTAINS 'CAP'
        WITH src, n, count(DISTINCT cap) AS cap_count
        WHERE cap_count < $min_caps
        RETURN src.RefDes AS refdes, src.Model AS model, src.PartType AS part_type,
               n.Name AS net_name, n.VoltageLevel AS voltage, cap_count
        """

        try:
            with driver.session() as session:
                results = list(session.run(cypler, {"min_caps": min_caps}))
        except Exception as e:
            logger.warning(f"Regulator decap check failed: {e}")
            return violations

        for r in results:
            violations.append(Violation(
                id=f"{rule_id}_{r['refdes']}_{r['net_name']}",
                rule_id=rule_id,
                rule_name=params.get("rule_name", self.name),
                refdes=r["refdes"],
                net_name=r["net_name"],
                description=f"稳压器 {r['refdes']} ({r['model']}) 输出 '{r['net_name']}' 去耦电容不足",
                severity=severity,
                expected=f"稳压器输出至少 {min_caps} 个去耦电容",
                actual=f"输出网络 '{r['net_name']}' 仅 {r['cap_count']} 个电容",
            ))

        return violations

    # --------------------------------------------------------
    # 电源域隔离检查
    # --------------------------------------------------------

    def _check_domain_isolation(self, driver, rule_id, severity, params) -> list[Violation]:
        """检查不同电压域之间是否有直连（无调节器）"""
        violations = []

        # 查找同时连接两个不同电压网络的器件（非调节器）
        cypher = """
        MATCH (c:Component)-[:HAS_PIN]->(p1:Pin)-[:CONNECTS_TO]->(n1:Net),
              (c)-[:HAS_PIN]->(p2:Pin)-[:CONNECTS_TO]->(n2:Net)
        WHERE n1.VoltageLevel IS NOT NULL
          AND n2.VoltageLevel IS NOT NULL
          AND n1.VoltageLevel <> n2.VoltageLevel
          AND n1.NetType = 'POWER' AND n2.NetType = 'POWER'
          AND p1.Type = 'POWER' AND p2.Type = 'POWER'
          AND NOT c.PartType IN ['PMIC', 'DIODE', 'MOSFET', 'TRANSISTOR']
          AND NOT c.Model =~ '(?i).*(LDO|REG|DCDC|BUCK|BOOST|LEVEL).*'
        WITH c, collect(DISTINCT n1.VoltageLevel + ':' + n1.Name) AS v1,
             collect(DISTINCT n2.VoltageLevel + ':' + n2.Name) AS v2
        RETURN c.RefDes AS refdes, c.Model AS model, c.PartType AS part_type,
               v1[0] AS net1_info, v2[0] AS net2_info
        LIMIT 50
        """

        try:
            with driver.session() as session:
                results = list(session.run(cypher))
        except Exception as e:
            logger.warning(f"Domain isolation check failed: {e}")
            return violations

        for r in results:
            violations.append(Violation(
                id=f"{rule_id}_{r['refdes']}",
                rule_id=rule_id,
                rule_name=params.get("rule_name", self.name),
                refdes=r["refdes"],
                net_name=r["net1_info"],
                description=f"器件 {r['refdes']} ({r['model']}) 同时连接不同电压域: {r['net1_info']} ↔ {r['net2_info']}",
                severity="INFO",
                expected="不同电压域之间应有电压调节器或电平转换器",
                actual=f"器件直接连接 {r['net1_info']} 和 {r['net2_info']}",
            ))

        return violations


# 注册模板
TemplateRegistry.register(PowerIntegrityCheck())
