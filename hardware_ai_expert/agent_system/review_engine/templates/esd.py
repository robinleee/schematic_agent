"""
ESD 保护检查模板

检查外部接口（连接器）的信号线是否配置了 ESD/TVS 保护器件。
"""

from __future__ import annotations

from agent_system.review_engine.templates.base import RuleTemplate, RuleContext, TemplateRegistry
from agent_system.schemas import Violation


# ============================================
# ESDCheckTemplate
# ============================================

class ESDCheckTemplate(RuleTemplate):
    """
    ESD/TVS 保护检查模板

    参数:
        interface_types: list[str]    接口类型标识
        net_patterns: list[str]       网络名称匹配模式
        connector_prefixes: list[str] 连接器位号前缀（默认 ["J", "P", "CON"]）
        max_capacitance_pf: float     ESD 器件最大允许电容（pF），用于选型参考
        check_all_signals: bool       是否检查所有信号引脚（默认 True）
    """

    template_id = "esd_check"
    name = "ESD/TVS 保护检查"
    description = "检查外部接口信号线是否配置了 ESD/TVS 保护器件"
    default_severity = "WARNING"

    def check(self, params: dict, context: RuleContext) -> list[Violation]:
        violations = []

        interface_types = params.get("interface_types", [])
        net_patterns = params.get("net_patterns", [])
        connector_prefixes = params.get("connector_prefixes", ["J", "P", "CON"])
        max_cap_pf = params.get("max_capacitance_pf", 5.0)
        rule_id = params.get("rule_id", self.template_id)
        severity = params.get("severity", self.default_severity)
        rule_name = params.get("rule_name", self.name)

        driver = context.neo4j_driver

        # ============================================
        # 策略：先定位目标网络，再检查网络上是否有 ESD 保护
        # ============================================

        target_nets = set()

        # 1. 按网络名模式匹配目标网络
        if net_patterns:
            cypher_nets = """
            MATCH (n:Net)
            WHERE ANY(pattern IN $patterns WHERE n.Name CONTAINS pattern)
            RETURN n.Name AS net_name
            """
            with driver.session() as session:
                for r in session.run(cypher_nets, {"patterns": net_patterns}):
                    target_nets.add(r["net_name"])

        # 2. 按连接器前缀查找关联网络（作为补充）
        if connector_prefixes:
            cypher_conn_nets = """
            MATCH (c:Component)
            WHERE ANY(prefix IN $prefixes WHERE c.RefDes STARTS WITH prefix)
            MATCH (c)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
            WHERE p.Type = 'SIGNAL'
               OR (p.Type IS NULL AND NOT n.Name IN ['GND', 'DGND', 'AGND', 'VSS'])
            RETURN DISTINCT n.Name AS net_name
            """
            with driver.session() as session:
                for r in session.run(cypher_conn_nets, {"prefixes": connector_prefixes}):
                    # 如果 net_patterns 存在，只保留匹配的网络
                    # 如果 net_patterns 为空，保留所有连接器关联的网络
                    if not net_patterns or any(pat in r["net_name"] for pat in net_patterns):
                        target_nets.add(r["net_name"])

        if not target_nets:
            return violations

        # 3. 对每个目标网络检查 ESD 保护
        for net_name in sorted(target_nets):
            # 跳过电源/地/NC
            if self._is_power_or_gnd(net_name):
                continue

            # 查找网络上的 ESD/TVS 器件
            cypher_esd = """
            MATCH (n:Net {Name: $net_name})<-[:CONNECTS_TO]-(p:Pin)<-[:HAS_PIN]-(c:Component)
            WHERE c.PartType CONTAINS 'ESD'
               OR c.PartType CONTAINS 'TVS'
               OR c.Model CONTAINS 'ESD'
               OR c.Model CONTAINS 'TVS'
            RETURN c.RefDes AS esd_refdes, c.Value AS esd_value, c.Model AS esd_model
            """

            with driver.session() as session:
                esd_devices = list(session.run(cypher_esd, {"net_name": net_name}))

            if not esd_devices:
                # 查找该网络关联的连接器（用于报告）
                cypher_conn = """
                MATCH (n:Net {Name: $net_name})<-[:CONNECTS_TO]-(p:Pin)<-[:HAS_PIN]-(c:Component)
                WHERE ANY(prefix IN $prefixes WHERE c.RefDes STARTS WITH prefix)
                RETURN c.RefDes AS conn_refdes, c.PartType AS conn_type
                LIMIT 1
                """
                with driver.session() as session:
                    conn_result = list(session.run(cypher_conn, {"net_name": net_name, "prefixes": connector_prefixes}))

                if conn_result:
                    conn = conn_result[0]
                    refdes = conn["conn_refdes"]
                    part_type = conn.get("conn_type", "")
                    desc = f"连接器 {refdes}({part_type}) 的信号网络 '{net_name}' 缺少 ESD/TVS 保护"
                else:
                    refdes = "网络"
                    desc = f"信号网络 '{net_name}' 缺少 ESD/TVS 保护"

                violations.append(Violation(
                    id=f"{rule_id}_{net_name}",
                    rule_id=rule_id,
                    rule_name=rule_name,
                    refdes=refdes,
                    net_name=net_name,
                    description=desc,
                    severity=severity,
                    expected=f"应配置 ESD/TVS 保护器件 (电容 < {max_cap_pf}pF)",
                    actual="未找到 ESD/TVS 保护器件",
                ))

        return violations

    @staticmethod
    def _is_power_or_gnd(net_name: str) -> bool:
        """判断网络是否为电源、地或 NC"""
        if not net_name:
            return False
        upper = net_name.upper()
        # NC / No Connect
        if upper == "NC" or upper.startswith("NC_"):
            return True
        power_keywords = [
            "GND", "DGND", "AGND", "PGND", "VSS", "VSSA",
            "VCC", "VDD", "VPP", "VIN", "VOUT", "VBAT",
        ]
        return any(kw in upper for kw in power_keywords)


# 注册模板
TemplateRegistry.register(ESDCheckTemplate())


# ============================================
# Self-test
# ============================================

if __name__ == "__main__":
    print("[ESDCheckTemplate] Self-test")

    # 测试电源/地判断
    assert ESDCheckTemplate._is_power_or_gnd("GND") is True
    assert ESDCheckTemplate._is_power_or_gnd("VDD_3V3") is True
    assert ESDCheckTemplate._is_power_or_gnd("USB_DP") is False
    assert ESDCheckTemplate._is_power_or_gnd("I2C_SDA") is False
    print("  ✅ 电源/地判断测试通过")

    # 测试模板注册
    tmpl = TemplateRegistry.get("esd_check")
    assert tmpl is not None
    assert tmpl.template_id == "esd_check"
    print("  ✅ 模板注册测试通过")

    print("[ESDCheckTemplate] All tests passed")
