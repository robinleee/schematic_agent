"""
AMR 降额检查模板

检查器件的绝对最大额定值（AMR）降额情况：
- 电阻功率降额：封装 → 额定功率，P = V²/R，最坏情况估算
- 电容耐压降额：工作电压 ≤ 额定耐压 × 降额系数

复用 agent_system.amr_engine 中的：
- VoltageLevelExtractor：网络电压标注
- ResistorPowerChecker：电阻功率检查
- CapacitorVoltageChecker：电容耐压检查（需 AMR 数据源）
"""

from __future__ import annotations

import os
from typing import Any

from agent_system.review_engine.templates.base import RuleTemplate, RuleContext, TemplateRegistry
from agent_system.schemas import Violation

# 复用 AMR 引擎的核心组件
import sys
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT_DIR)

from agent_system.amr_engine import (
    VoltageLevelExtractor,
    ResistorPowerChecker,
    CapacitorVoltageChecker,
    DeratingStandard,
    parse_resistance,
    get_package_from_model,
    get_resistor_power_rating,
)


# ============================================
# AMR 降额检查模板
# ============================================

class AMRCheckTemplate(RuleTemplate):
    """
    AMR 降额检查模板

    参数:
        standard: str     降额标准 (industry/gjb_z_35/commercial)，默认 industry
        check_resistor_power: bool  是否检查电阻功率（默认 True）
        check_capacitor_voltage: bool 是否检查电容耐压（默认 True）
        min_voltage_v: float  最小电压阈值（V），低于此电压的检查项跳过（默认 0.1V）
    """

    template_id = "amr_check"
    name = "AMR 降额检查"
    description = "检查电阻功率和电容耐压的降额情况"
    default_severity = "WARNING"

    def check(self, params: dict, context: RuleContext) -> list[Violation]:
        violations = []

        standard_name = params.get("standard", "industry")
        check_resistor = params.get("check_resistor_power", True)
        check_capacitor = params.get("check_capacitor_voltage", True)
        min_voltage = params.get("min_voltage_v", 0.1)
        rule_id = params.get("rule_id", self.template_id)
        severity = params.get("severity", self.default_severity)
        rule_name = params.get("rule_name", self.name)

        # 解析降额标准
        try:
            standard = DeratingStandard(standard_name)
        except ValueError:
            standard = DeratingStandard.INDUSTRY

        driver = context.neo4j_driver

        # 1. 标注网络电压
        print(f"[AMR] 开始 AMR 降额检查（标准: {standard.value}）")
        annotated = VoltageLevelExtractor.batch_annotate_neo4j(driver)
        print(f"[AMR] 已标注 {annotated} 个网络的电压")

        # 2. 检查电阻功率降额
        if check_resistor:
            violations.extend(
                self._check_resistor_power(driver, standard, min_voltage, rule_id, rule_name, severity)
            )

        # 3. 检查电容耐压降额（数据源不完整，跳过）
        if check_capacitor:
            cap_violations = self._check_capacitor_voltage(driver, standard, min_voltage, rule_id, rule_name, severity)
            if cap_violations:
                violations.extend(cap_violations)

        return violations

    def _check_resistor_power(
        self,
        driver: Any,
        standard: DeratingStandard,
        min_voltage: float,
        rule_id: str,
        rule_name: str,
        severity: str,
    ) -> list[Violation]:
        """检查电阻功率降额"""
        violations = []

        checker = ResistorPowerChecker(standard=standard)

        # 查询所有电阻器件
        cypher = """
        MATCH (c:Component)
        WHERE c.PartType CONTAINS 'RES'
          AND c.Value IS NOT NULL
          AND c.Value <> ''
          AND NOT c.Value STARTS WITH 'DNP'
          AND NOT c.Value STARTS WITH 'NC'
        RETURN c.RefDes AS refdes,
               c.Value AS value,
               c.Model AS model
        LIMIT 2000
        """

        with driver.session() as session:
            resistors = list(session.run(cypher))

        print(f"[AMR] 检查 {len(resistors)} 个电阻器件")

        for res in resistors:
            refdes = res["refdes"]
            value_str = res.get("value", "")
            model = res.get("model", "")

            # 解析电阻值
            resistance = parse_resistance(value_str)
            if resistance is None:
                continue

            # 提取封装
            package = get_package_from_model(model) if model else None
            power_rated = get_resistor_power_rating(package)

            if power_rated is None:
                # 无法获取额定功率，跳过
                continue

            # 获取该电阻所在网络的电压（取最高）
            cypher_voltage = """
            MATCH (c:Component {RefDes: $refdes})-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
            WHERE n.VoltageLevel IS NOT NULL
            WITH n,
                 CASE
                   WHEN toString(n.VoltageLevel) CONTAINS 'V'
                     THEN toFloat(replace(toString(n.VoltageLevel), 'V', ''))
                   ELSE toFloat(n.VoltageLevel)
                 END AS v_num
            RETURN v_num AS voltage
            ORDER BY v_num DESC
            LIMIT 1
            """

            with driver.session() as session:
                result = list(session.run(cypher_voltage, {"refdes": refdes}))

            if not result:
                continue

            voltage = result[0]["voltage"]
            if voltage is None or voltage < min_voltage:
                continue

            # 执行降额检查
            result_obj = checker.check_component(refdes, resistance, power_rated, voltage)

            if not result_obj.passed:
                ratio_str = f"{result_obj.derating_ratio * 100:.1f}%" if result_obj.derating_ratio else "无法计算"
                violations.append(Violation(
                    id=f"{rule_id}_{refdes}",
                    rule_id=rule_id,
                    rule_name=rule_name,
                    refdes=refdes,
                    net_name="",
                    description=f"电阻 {refdes} 功率降额超标: {result_obj.detail}",
                    severity=severity,
                    expected=f"降额率 ≤ {result_obj.limit_ratio * 100:.0f}%",
                    actual=f"降额率 {ratio_str}",
                ))

        print(f"[AMR] 电阻功率检查完成: {len(violations)} 个违规")
        return violations

    def _check_capacitor_voltage(
        self,
        driver: Any,
        standard: DeratingStandard,
        min_voltage: float,
        rule_id: str,
        rule_name: str,
        severity: str,
    ) -> list[Violation]:
        """检查电容耐压降额（当前 AMR 数据源不完整，跳过）"""
        # CapacitorVoltageChecker 依赖 AMRDataSource.get_capacitor_voltage_rating()
        # 当前 AMRDataSource 返回 None，因此跳过高风险误报
        print("[AMR] 电容耐压检查：AMR 数据源不完整，跳过（需接入料号库/Datasheet）")
        return []


# 注册模板
TemplateRegistry.register(AMRCheckTemplate())


# ============================================
# Self-test（不需要真实 Neo4j）
# ============================================

if __name__ == "__main__":
    print("[AMRCheckTemplate] Self-test")
    print("  注意：完整功能测试需要 Neo4j 连接，以下仅验证导入和解析逻辑")

    # 验证模板注册
    tmpl = TemplateRegistry.get("amr_check")
    assert tmpl is not None, "模板未注册"
    assert tmpl.template_id == "amr_check"
    print("  ✅ 模板注册验证通过")

    # 验证 AMR 引擎组件导入
    from agent_system.amr_engine import (
        VoltageLevelExtractor,
        ResistorPowerChecker,
        DeratingStandard,
        parse_resistance,
        get_package_from_model,
    )
    print("  ✅ AMR 引擎组件导入成功")

    # 验证电压提取逻辑
    test_cases = [
        ("VDD_3V3", 3.3),
        ("VCC_1V8", 1.8),
        ("5V_USB", 5.0),
        ("P3V3_AUX", 3.3),
        ("GND", 0.0),
    ]
    for net, expected in test_cases:
        actual = VoltageLevelExtractor.extract(net)
        assert abs((actual or 0) - expected) < 0.01, f"电压提取失败: {net}"
    print("  ✅ 电压提取逻辑验证通过")

    # 验证电阻解析
    assert abs(parse_resistance("10k") - 10000) < 1
    assert abs(parse_resistance("4.7k") - 4700) < 1
    print("  ✅ 电阻解析逻辑验证通过")

    # 验证封装提取
    assert get_package_from_model("719_RES_PPG_R0402_DISCRETE_10K_") == "R0402"
    print("  ✅ 封装提取逻辑验证通过")

    print("[AMRCheckTemplate] All tests passed")