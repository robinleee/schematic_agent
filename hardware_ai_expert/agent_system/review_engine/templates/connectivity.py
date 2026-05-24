"""
连通性检查模板

检查原理图连通性：
  1. 悬空引脚检查：非 NC 引脚未连接网络
  2. 单端网络检查：网络仅连接一个器件引脚
  3. 总线完整性：I2C/SPI 总线应至少有主从两个器件
"""

from __future__ import annotations

import logging

from agent_system.review_engine.templates.base import RuleTemplate, RuleContext, TemplateRegistry
from agent_system.schemas import Violation

logger = logging.getLogger(__name__)


class ConnectivityCheck(RuleTemplate):
    """
    连通性检查模板

    参数:
        check_type: str
            - "floating_pin": 悬空引脚检查
            - "single_end_net": 单端网络检查
            - "bus_integrity": 总线完整性检查
            - "all": 全部检查（默认）
        exclude_nc: bool       排除 NC 引脚（默认 True）
        exclude_part_types: list  排除的器件类型
        min_bus_devices: int   总线最少器件数（默认 2）
    """

    template_id = "connectivity_check"
    name = "连通性检查"
    description = "检查原理图连通性：悬空引脚、单端网络、总线完整性"
    default_severity = "WARNING"

    def check(self, params: dict, context: RuleContext) -> list[Violation]:
        violations = []
        check_type = params.get("check_type", "all")
        rule_id = params.get("rule_id", self.template_id)
        severity = params.get("severity", self.default_severity)
        exclude_nc = params.get("exclude_nc", True)
        exclude_part_types = params.get("exclude_part_types", ["TESTPOINT", "MECHANICAL"])
        min_bus_devices = params.get("min_bus_devices", 2)

        driver = context.neo4j_driver

        if check_type in ("floating_pin", "all"):
            violations.extend(self._check_floating_pins(
                driver, rule_id, severity, exclude_nc, exclude_part_types, params
            ))

        if check_type in ("single_end_net", "all"):
            violations.extend(self._check_single_end_nets(
                driver, rule_id, severity, exclude_part_types, params
            ))

        if check_type in ("bus_integrity", "all"):
            violations.extend(self._check_bus_integrity(
                driver, rule_id, severity, min_bus_devices, params
            ))

        return violations

    # --------------------------------------------------------
    # 悬空引脚检查
    # --------------------------------------------------------

    def _check_floating_pins(self, driver, rule_id, severity, exclude_nc,
                              exclude_part_types, params) -> list[Violation]:
        """查找非 NC 引脚未连接网络的器件"""
        violations = []

        # 查找有引脚但未连接网络的 IC 类器件
        part_filter = " AND ".join([f"c.PartType <> '{pt}'" for pt in exclude_part_types])
        nc_filter = "AND NOT p.Name =~ '(?i).*(NC|DNC|NO_CONNECT).*'" if exclude_nc else ""

        cypher = f"""
        MATCH (c:Component)-[:HAS_PIN]->(p:Pin)
        WHERE c.PartType IN ['IC', 'PMIC', 'MCU', 'FPGA', 'SOC', 'DRAM', 'FLASH']
          {nc_filter}
          AND p.Type IN ['INPUT', 'OUTPUT', 'BIDIRECTIONAL', 'POWER']
          AND NOT (p)-[:CONNECTS_TO]->(:Net)
        RETURN c.RefDes AS refdes, c.PartType AS part_type,
               p.Number AS pin_number, p.Name AS pin_name, p.Type AS pin_type
        LIMIT 100
        """

        try:
            with driver.session() as session:
                results = list(session.run(cypher))
        except Exception as e:
            logger.warning(f"Floating pin check failed: {e}")
            return violations

        # 按器件聚合，避免违规过多
        by_refdes = {}
        for r in results:
            refdes = r["refdes"]
            if refdes not in by_refdes:
                by_refdes[refdes] = {"part_type": r["part_type"], "pins": []}
            by_refdes[refdes]["pins"].append(
                f"Pin {r['pin_number']}({r['pin_name']}, {r['pin_type']})"
            )

        for refdes, info in list(by_refdes.items())[:30]:  # 限制数量
            pins_str = ", ".join(info["pins"][:5])
            if len(info["pins"]) > 5:
                pins_str += f" 等 {len(info['pins'])} 个引脚"

            violations.append(Violation(
                id=f"{rule_id}_{refdes}_floating",
                rule_id=rule_id,
                rule_name=params.get("rule_name", self.name),
                refdes=refdes,
                net_name="",
                description=f"器件 {refdes} ({info['part_type']}) 有未连接的功能引脚",
                severity=severity,
                expected="功能引脚应连接到网络",
                actual=f"未连接: {pins_str}",
            ))

        return violations

    # --------------------------------------------------------
    # 单端网络检查
    # --------------------------------------------------------

    def _check_single_end_nets(self, driver, rule_id, severity,
                                exclude_part_types, params) -> list[Violation]:
        """查找仅连接一个器件引脚的网络"""
        violations = []

        part_excludes = "', '".join(exclude_part_types)

        cypher = f"""
        MATCH (c:Component)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
        WHERE NOT c.PartType IN ['{part_excludes}']
          AND NOT n.Name =~ '(?i).*(NC|DNC|NO_CONNECT).*'
        WITH n, count(DISTINCT c) AS device_count, collect(DISTINCT c.RefDes)[0..3] AS refs,
             collect(DISTINCT c.PartType)[0..3] AS types
        WHERE device_count = 1
        RETURN n.Name AS net_name, n.VoltageLevel AS voltage, n.NetType AS net_type,
               refs[0] AS refdes, types[0] AS part_type
        LIMIT 100
        """

        try:
            with driver.session() as session:
                results = list(session.run(cypher))
        except Exception as e:
            logger.warning(f"Single-end net check failed: {e}")
            return violations

        for r in results:
            # 电源网络和 GND 可能合理地只有一个连接
            if r["net_type"] == "POWER" or r["net_name"].upper() in ("GND", "VCC", "VDD"):
                continue

            violations.append(Violation(
                id=f"{rule_id}_{r['net_name']}",
                rule_id=rule_id,
                rule_name=params.get("rule_name", self.name),
                refdes=r["refdes"],
                net_name=r["net_name"],
                description=f"网络 '{r['net_name']}' 仅连接一个器件 {r['refdes']} ({r['part_type']})",
                severity="INFO",
                expected="信号网络应至少连接两个器件",
                actual=f"仅连接 {r['refdes']}",
            ))

        return violations

    # --------------------------------------------------------
    # 总线完整性检查
    # --------------------------------------------------------

    def _check_bus_integrity(self, driver, rule_id, severity, min_devices, params) -> list[Violation]:
        """检查 I2C/SPI/UART 总线是否有足够器件"""
        violations = []

        # I2C 总线：SDA + SCL
        cypher_i2c = """
        MATCH (n:Net)
        WHERE n.Name =~ '(?i).*(I2C|IIC).*(SDA|SCL|DATA|CLK).*'
           OR n.Name =~ '(?i).*(SDA|SCL).*(I2C|IIC).*'
        RETURN n.Name AS net_name
        """

        bus_nets = {}
        try:
            with driver.session() as session:
                i2c_nets = [r["net_name"] for r in session.run(cypher_i2c)]
        except Exception as e:
            logger.warning(f"Bus integrity check failed: {e}")
            return violations

        for net_name in i2c_nets:
            cypher_count = """
            MATCH (c:Component)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net {Name: $name})
            WHERE NOT c.PartType IN ['RESISTOR', 'CAPACITOR', 'TESTPOINT']
            RETURN count(DISTINCT c) AS device_count,
                   collect(DISTINCT c.RefDes)[0..5] AS refs
            """
            try:
                with driver.session() as session:
                    result = session.run(cypher_count, {"name": net_name}).single()
                    if result and result["device_count"] < min_devices:
                        violations.append(Violation(
                            id=f"{rule_id}_{net_name}_bus",
                            rule_id=rule_id,
                            rule_name=params.get("rule_name", self.name),
                            refdes=", ".join(result["refs"]) if result["refs"] else net_name,
                            net_name=net_name,
                            description=f"I2C 网络 '{net_name}' 连接器件数不足",
                            severity="INFO",
                            expected=f"I2C 总线应至少 {min_devices} 个器件（主+从）",
                            actual=f"仅 {result['device_count']} 个器件: {', '.join(result['refs'])}",
                        ))
            except Exception:
                continue

        return violations


# 注册模板
TemplateRegistry.register(ConnectivityCheck())
