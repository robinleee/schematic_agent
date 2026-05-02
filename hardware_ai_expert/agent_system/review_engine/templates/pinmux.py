# -*- coding: utf-8 -*-
"""
引脚悬空与网络错连检查模板

检查三类问题：
1. OpenDrain 引脚上拉检查：通过器件型号和网络名推断 OD 引脚，检查是否有上拉电阻
2. POWER/GND 引脚连接检查：通过关系查询检查 IC 电源引脚是否连接到正确的网络
3. NC 引脚悬空检查：检查 NC 标记的网络是否意外连接到器件

注意：当前 Neo4j 中 Pin 节点只有 Number/Id 属性，没有 Name/Net/Type。
因此所有检查通过网络级别和器件级别推断实现。
"""

from __future__ import annotations

from typing import Optional

from agent_system.review_engine.templates.base import RuleTemplate, RuleContext, TemplateRegistry
from agent_system.schemas import Violation


# ============================================
# 辅助函数
# ============================================

def is_od_component(part_type: str, model: str) -> bool:
    """
    判断器件是否为 OpenDrain 类型

    判断依据：
    - PartType 含 "OD"（如 "ODWR", "ODPWR", "OD Buffer"）
    - Model 名含 "OD"（器件型号标注）
    """
    search_str = f"{part_type or ''} {model or ''}".upper()
    od_patterns = ["OD", "OPEN_DRAIN", "OPENDRN"]
    return any(p in search_str for p in od_patterns)


def is_power_net(net_name: Optional[str]) -> bool:
    """判断网络是否为电源网络"""
    if not net_name:
        return False
    s = net_name.upper()
    power_patterns = ["VCC", "VDD", "VIN", "VBAT", "PWR", "3V3", "5V", "1V8", "2V5", "12V", "24V"]
    return any(p in s for p in power_patterns)


def is_gnd_net(net_name: Optional[str]) -> bool:
    """判断网络是否为地网络"""
    if not net_name:
        return False
    s = net_name.upper()
    gnd_patterns = ["GND", "VSS", "AGND", "DGND"]
    return any(p in s for p in gnd_patterns)


def is_signal_net(net_name: Optional[str]) -> bool:
    """判断网络是否为信号网络（既不是电源也不是地）"""
    return net_name is not None and not is_power_net(net_name) and not is_gnd_net(net_name)


def is_nc_net(net_name: Optional[str]) -> bool:
    """判断网络是否为 NC（Not Connected）网络"""
    if not net_name:
        return False
    s = net_name.upper()
    return s == "NC" or s.startswith("NC_") or "_NC" in s


def is_pullup_on_net(driver, net_name: str) -> bool:
    """
    检查网络上是否存在上拉电阻

    通过查找连接到该网络的电阻器件来判断。
    """
    if not net_name:
        return False

    cypher = """
    MATCH (n:Net {Name: $net_name})<-[:CONNECTS_TO]-(p:Pin)<-[:HAS_PIN]-(c:Component)
    WHERE c.PartType CONTAINS 'RES'
    RETURN c.RefDes AS refdes, c.Value AS value
    LIMIT 10
    """

    try:
        with driver.session() as session:
            resistors = list(session.run(cypher, {"net_name": net_name}))

        for res in resistors:
            val = res.get("value", "") or ""
            # 过滤 DNP 电阻
            if val.upper().startswith("DNP"):
                continue
            return True
    except Exception:
        pass

    return False


# ============================================
# PinMuxCheckTemplate
# ============================================

class PinMuxCheckTemplate(RuleTemplate):
    """
    引脚悬空与网络错连检查模板

    支持三种检查类型（通过 params 控制开关）：

    1. OpenDrain 引脚上拉检查 (check_od_pullup)
       - 查找 OD 引脚（PartType/NetName 含 "OD"）
       - 检查其网络是否有上拉电阻
       - 无上拉则报 ERROR

    2. POWER/GND 引脚连接检查 (check_power_gnd)
       - 查找 POWER 引脚，检查是否连接到电源网络
       - 查找 GND 引脚，检查是否连接到地网络
       - 错接则报 ERROR

    3. NC 引脚连接检查 (check_nc)
       - 查找 NC 引脚
       - 检查 NC 引脚是否意外连接到非 NC 网络
       - 意外连接则报 WARNING

    参数:
        check_od_pullup: bool  是否检查 OD 引脚上拉
        check_power_gnd: bool  是否检查 POWER/GND 引脚连接
        check_nc: bool         是否检查 NC 引脚悬空
    """

    template_id = "pinmux_check"
    name = "引脚悬空与网络错连检查"
    description = "检查 OD 引脚上拉、POWER/GND 连接、NC 引脚悬空"
    default_severity = "ERROR"

    def check(self, params: dict, context: RuleContext) -> list[Violation]:
        violations = []

        check_od_pullup = params.get("check_od_pullup", True)
        check_power_gnd = params.get("check_power_gnd", True)
        check_nc = params.get("check_nc", False)
        rule_id = params.get("rule_id", self.template_id)
        severity = params.get("severity", self.default_severity)
        rule_name = params.get("rule_name", self.name)

        driver = context.neo4j_driver

        if check_od_pullup:
            violations.extend(
                self._check_od_pullup(driver, rule_id, rule_name, severity)
            )

        if check_power_gnd:
            violations.extend(
                self._check_power_gnd(driver, rule_id, rule_name, severity)
            )

        if check_nc:
            violations.extend(
                self._check_nc_pins(driver, rule_id, rule_name, severity)
            )

        return violations

    def _check_od_pullup(
        self,
        driver,
        rule_id: str,
        rule_name: str,
        severity: str,
    ) -> list[Violation]:
        """
        检查 OpenDrain 器件的网络是否有上拉电阻

        策略：查找 PartType/Model 含 "OD" 的器件，检查其所有信号网络
        是否配置了上拉电阻。
        """
        violations = []

        # 查找 OD 器件及其连接的网络
        cypher = """
        MATCH (c:Component)
        WHERE c.PartType CONTAINS 'OD'
           OR c.Model CONTAINS 'OD'
        MATCH (c)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
        WHERE NOT n.Name CONTAINS 'GND'
          AND NOT n.Name CONTAINS 'VSS'
          AND NOT n.Name CONTAINS 'VDD'
          AND NOT n.Name CONTAINS 'VCC'
        RETURN c.RefDes AS refdes,
               c.PartType AS part_type,
               n.Name AS net_name
        LIMIT 500
        """

        try:
            with driver.session() as session:
                od_nets = list(session.run(cypher))
        except Exception as e:
            print(f"[PinMux] OD 器件查询失败: {e}")
            return violations

        checked_nets = set()
        for item in od_nets:
            net_name = item["net_name"] or ""
            if net_name in checked_nets:
                continue
            checked_nets.add(net_name)

            # 检查该网络是否有上拉电阻
            if not is_pullup_on_net(driver, net_name):
                violations.append(Violation(
                    id=f"{rule_id}_OD_PULLUP_{net_name}",
                    rule_id=rule_id,
                    rule_name=rule_name,
                    refdes=item["refdes"] or "UNKNOWN",
                    net_name=net_name,
                    description=f"OpenDrain 器件网络 '{net_name}' 缺少上拉电阻",
                    severity=severity,
                    expected="OD 引脚应通过上拉电阻连接到电源",
                    actual="未检测到上拉电阻",
                ))

        return violations

    def _check_power_gnd(
        self,
        driver,
        rule_id: str,
        rule_name: str,
        severity: str,
    ) -> list[Violation]:
        """
        检查 IC 器件的电源引脚是否连接到正确的网络

        策略：查找 IC/MCU/FPGA 类器件，检查其连接的电源/地网络
        是否正确。通过网络名推断。
        """
        violations = []

        # 查找 IC 类器件及其连接的网络
        cypher = """
        MATCH (c:Component)
        WHERE ANY(pt IN ['IC', 'MCU', 'FPGA', 'SOC', 'CPU', 'PMIC', 'LDO'] WHERE c.PartType CONTAINS pt)
        MATCH (c)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
        RETURN c.RefDes AS refdes,
               c.PartType AS part_type,
               n.Name AS net_name
        LIMIT 1000
        """

        try:
            with driver.session() as session:
                ic_pins = list(session.run(cypher))
        except Exception as e:
            print(f"[PinMux] IC 引脚查询失败: {e}")
            return violations

        # 按器件分组统计
        from collections import defaultdict
        component_nets = defaultdict(list)
        for item in ic_pins:
            refdes = item["refdes"] or "UNKNOWN"
            component_nets[refdes].append({
                "part_type": item.get("part_type", ""),
                "net_name": item.get("net_name", ""),
            })

        # 检查每个器件是否有电源和地连接
        for refdes, nets in component_nets.items():
            has_power = any(is_power_net(n["net_name"]) for n in nets)
            has_gnd = any(is_gnd_net(n["net_name"]) for n in nets)

            # 简化检查：IC 至少应有一个电源和一个地连接
            # 实际设计中某些引脚可能悬空，这里只做基础检查
            if not has_power:
                violations.append(Violation(
                    id=f"{rule_id}_PWR_MISSING_{refdes}",
                    rule_id=rule_id,
                    rule_name=rule_name,
                    refdes=refdes,
                    net_name="",
                    description=f"器件 {refdes} 未检测到电源网络连接",
                    severity="WARNING",  # 降级为 WARNING，因为可能遗漏
                    expected="IC 器件应至少连接到一个电源网络",
                    actual="未找到 VCC/VDD 等电源网络",
                ))

            if not has_gnd:
                violations.append(Violation(
                    id=f"{rule_id}_GND_MISSING_{refdes}",
                    rule_id=rule_id,
                    rule_name=rule_name,
                    refdes=refdes,
                    net_name="",
                    description=f"器件 {refdes} 未检测到地网络连接",
                    severity="WARNING",
                    expected="IC 器件应至少连接到一个地网络",
                    actual="未找到 GND/VSS 等地网络",
                ))

        return violations

    def _check_nc_pins(
        self,
        driver,
        rule_id: str,
        rule_name: str,
        severity: str,
    ) -> list[Violation]:
        """
        检查 NC 网络是否意外连接到器件

        策略：查找网络名含 "NC" 的网络，检查是否连接了器件
        （NC 网络应该是悬空的）。
        """
        violations = []

        # 查找 NC 网络及其连接的器件
        cypher = """
        MATCH (n:Net)
        WHERE n.Name = 'NC'
           OR n.Name STARTS WITH 'NC_'
           OR n.Name CONTAINS '_NC'
        MATCH (n)<-[:CONNECTS_TO]-(p:Pin)<-[:HAS_PIN]-(c:Component)
        RETURN n.Name AS net_name,
               c.RefDes AS refdes,
               c.PartType AS part_type
        LIMIT 500
        """

        try:
            with driver.session() as session:
                nc_connections = list(session.run(cypher))
        except Exception as e:
            print(f"[PinMux] NC 网络查询失败: {e}")
            return violations

        for item in nc_connections:
            net_name = item["net_name"] or ""
            refdes = item["refdes"] or "UNKNOWN"
            part_type = item.get("part_type", "")

            # NC 网络不应连接到非 NC 引脚
            # 这里简单检查：NC 网络连接了器件即为可疑
            violations.append(Violation(
                id=f"{rule_id}_NC_CONNECT_{refdes}_{net_name}",
                rule_id=rule_id,
                rule_name=rule_name,
                refdes=refdes,
                net_name=net_name,
                description=f"NC 网络 '{net_name}' 连接到器件 {refdes}",
                severity="INFO",  # 降级为 INFO，因为 NC 连接可能是设计意图
                expected="NC 网络应保持悬空",
                actual=f"连接到器件 {refdes}({part_type})",
            ))

        return violations


# 注册模板
TemplateRegistry.register(PinMuxCheckTemplate())


# ============================================
# Self-test
# ============================================

if __name__ == "__main__":
    print("[PinMuxCheckTemplate] Self-test")

    # 测试 is_od_component
    assert is_od_component("ODWR", "OD_MODEL") is True
    assert is_od_component("BUFFER", "OD_EN") is True
    assert is_od_component("REG", "VOUT") is False
    print("  ✅ is_od_component 测试通过")

    # 测试 is_power_net
    assert is_power_net("VDD_3V3") is True
    assert is_power_net("VCC_5V") is True
    assert is_power_net("3V3") is True
    assert is_power_net("GND") is False
    assert is_power_net("SDA") is False
    print("  ✅ is_power_net 测试通过")

    # 测试 is_gnd_net
    assert is_gnd_net("GND") is True
    assert is_gnd_net("AGND") is True
    assert is_gnd_net("VSS") is True
    assert is_gnd_net("VDD_3V3") is False
    assert is_gnd_net("SCL") is False
    print("  ✅ is_gnd_net 测试通过")

    # 测试 is_signal_net
    assert is_signal_net("SDA") is True
    assert is_signal_net("I2C_SCL") is True
    assert is_signal_net("VDD_3V3") is False
    assert is_signal_net("GND") is False
    assert is_signal_net(None) is False
    print("  ✅ is_signal_net 测试通过")

    # 测试 is_nc_net
    assert is_nc_net("NC") is True
    assert is_nc_net("NC_1") is True
    assert is_nc_net("GPIO_NC") is True
    assert is_nc_net("GPIO_A0") is False
    assert is_nc_net("VCC") is False
    print("  ✅ is_nc_net 测试通过")

    # 测试模板注册
    tmpl = TemplateRegistry.get("pinmux_check")
    assert tmpl is not None
    assert tmpl.template_id == "pinmux_check"
    print("  ✅ 模板注册测试通过")

    print("[PinMuxCheckTemplate] All tests passed")
