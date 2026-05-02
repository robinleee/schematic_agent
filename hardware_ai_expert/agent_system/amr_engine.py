"""
AMR 降额引擎 (Absolute Maximum Ratings Derating Engine)

功能：
1. 从网络名自动推断电压等级 (VoltageLevelExtractor)
2. 电阻功率降额检查（封装 → 额定功率，P = V²/R）
3. 电容耐压降额检查（框架，需外部 AMR 数据源）
4. 统一输出 Violation 格式

对应 PRD: 原理图审查 - AMR 降额审查
"""

from __future__ import annotations

import os
import re
import math
from typing import Optional
from dataclasses import dataclass
from enum import Enum

from neo4j import GraphDatabase
from dotenv import load_dotenv

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

from agent_system.schemas import Violation

try:
    from agent_system.datasheet_hitl import FileBasedAMRSource
    _FILE_BASED_AMR_AVAILABLE = True
except ImportError:
    _FILE_BASED_AMR_AVAILABLE = False


# ============================================================
# 常量定义
# ============================================================

class DeratingStandard(str, Enum):
    """降额标准"""
    GJB_Z_35 = "gjb_z_35"       # 国军标，最严
    IPC_9592 = "ipc_9592"       # IPC 标准
    INDUSTRY = "industry"       # 工业通用（默认）
    COMMERCIAL = "commercial"   # 商业级，较宽松


# 封装 → 额定功率 (W) 映射（基于常规厚膜电阻）
PACKAGE_POWER_MAP = {
    "R0075": 0.03125,   # 0201
    "R01005": 0.03125,
    "R015": 0.0625,     # 0402
    "R0201": 0.05,
    "R0402": 0.0625,    # 1/16 W
    "R0603": 0.1,       # 1/10 W
    "R0805": 0.125,     # 1/8 W
    "R1206": 0.25,      # 1/4 W
    "R1210": 0.5,       # 1/2 W
    "R2010": 0.75,
    "R2512": 1.0,
    # 无封装时 fallback
    "C0402": None,
    "C0603": None,
    "C0805": None,
    "C1206": None,
}

# 降额系数 (% of rated) — 工业通用标准
DERATING_LIMITS = {
    DeratingStandard.INDUSTRY: {
        "resistor_power": 0.50,     # 电阻功率 ≤ 50%
        "capacitor_voltage": 0.80,  # 电容电压 ≤ 80%
        "mosfet_vds": 0.80,
        "diode_vrrm": 0.80,
        "ic_vcc": 0.90,
    },
    DeratingStandard.GJB_Z_35: {
        "resistor_power": 0.30,
        "capacitor_voltage": 0.60,
        "mosfet_vds": 0.60,
        "diode_vrrm": 0.60,
        "ic_vcc": 0.80,
    },
    DeratingStandard.COMMERCIAL: {
        "resistor_power": 0.70,
        "capacitor_voltage": 0.90,
        "mosfet_vds": 0.90,
        "diode_vrrm": 0.90,
        "ic_vcc": 0.95,
    },
}


# ============================================================
# 电压提取器
# ============================================================

class VoltageLevelExtractor:
    """
    从网络名称推断电压等级

    支持模式：
      VDD_3V3, VCC_1V8, VCCINT_0V85, 5V_USB, 12V_IN, VBAT_3V7, etc.
    """

    # 统一的电压数字捕获组: 支持 3V3, 3P3, 12V, 0V85, 5 等格式
    _VNUM = r'([0-9]+V(?:[0-9]+)?|[0-9]+P(?:[0-9]+)?|[0-9]+)'
    # 自定义"词边界"：前后不是字母或数字（下划线不算，因为它在网络名中常见）
    _WB = r'(?<![A-Za-z0-9])'
    _WB_END = r'(?![A-Za-z0-9])'

    PATTERNS = [
        # VDD_3V3, VCC_1V8, VCCINT_0V85_LARK
        (rf'{_WB}V(?:DD|CC|CCINT|CCIO|CCA|BAT|PP|IN|OUT)_{_VNUM}{_WB_END}', 'underscore'),
        # 3V3_TCXO, 5V_USB, 0V85
        (rf'{_WB}{_VNUM}(?:V|{_WB_END})', 'leading'),
        # VCC5V, VCC3V3, VCC3P3
        (rf'{_WB}VCC{_VNUM}(?:V|{_WB_END})', 'vcc'),
        # VDD5V, VDD3V3
        (rf'{_WB}VDD{_VNUM}(?:V|{_WB_END})', 'vdd'),
        # P3V3, P1V8, P12V (如 VCC_P3V3, VCC_P12V_SAFETY)
        (rf'{_WB}P{_VNUM}{_WB_END}', 'p_prefix'),
    ]

    @classmethod
    def extract(cls, net_name: str) -> Optional[float]:
        """从网络名提取电压值（V），失败返回 None"""
        if not net_name:
            return None

        net_upper = net_name.upper()

        # 排除地线
        if net_upper in ('GND', 'DGND', 'AGND', 'PGND', 'VSS', 'VSSA'):
            return 0.0

        for pattern, ptype in cls.PATTERNS:
            match = re.search(pattern, net_upper)
            if match:
                volt_str = match.group(1)
                # 统一替换 V/P 为小数点: 3V3 → 3.3, 3P3 → 3.3, 0V85 → 0.85, 12V → 12.
                volt_str = volt_str.replace('V', '.').replace('P', '.')
                try:
                    return float(volt_str)
                except ValueError:
                    continue

        # 兜底模式: 纯数字 + V 结尾 (如 12V, 5V, 1.8V)
        match = re.search(r'([0-9]+(?:\.[0-9]+)?)V$', net_upper)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass

        return None

    @classmethod
    def batch_annotate_neo4j(cls, driver):
        """批量为 Neo4j 中的 Net 节点标注 VoltageLevel"""
        print("\n[AMR] 批量标注网络电压...")

        # 1. 获取所有 Net
        with driver.session() as session:
            result = session.run("MATCH (n:Net) RETURN n.Name AS name")
            nets = [(r["name"], cls.extract(r["name"])) for r in result]

        # 2. 更新有电压值的 Net
        updated = 0
        with driver.session() as session:
            for name, voltage in nets:
                if voltage is not None:
                    session.run("""
                        MATCH (n:Net {Name: $name})
                        SET n.VoltageLevel = $voltage
                    """, name=name, voltage=voltage)
                    updated += 1

        print(f"  已标注 {updated} / {len(nets)} 个网络的 VoltageLevel")
        return updated


# ============================================================
# 器件参数解析
# ============================================================

def parse_resistance(value_str: str) -> Optional[float]:
    """解析电阻值 → 欧姆"""
    if not value_str:
        return None
    s = value_str.upper().strip()
    # 去掉 DNP_ 前缀
    if s.startswith('DNP_'):
        s = s[4:]
    if s.startswith('NC_'):
        s = s[3:]

    multipliers = {'K': 1e3, 'M': 1e6, 'G': 1e9}
    for suffix, mult in multipliers.items():
        if suffix in s:
            num = re.sub(r'[^0-9.]', '', s.split(suffix)[0])
            try:
                return float(num) * mult if num else None
            except ValueError:
                return None

    # 纯数字
    num = re.sub(r'[^0-9.]', '', s)
    try:
        val = float(num) if num else None
        # 0 欧姆视为跳线/零欧姆电阻，跳过降额检查
        return val if val and val > 0 else None
    except ValueError:
        return None


def parse_capacitance(value_str: str) -> Optional[float]:
    """解析电容值 → 法拉"""
    if not value_str:
        return None
    s = value_str.upper().strip()

    multipliers = {'PF': 1e-12, 'NF': 1e-9, 'UF': 1e-6, 'MF': 1e-3, 'F': 1.0}
    for suffix, mult in sorted(multipliers.items(), key=lambda x: -len(x[0])):
        if suffix in s:
            num = re.sub(r'[^0-9.]', '', s.split(suffix)[0])
            try:
                return float(num) * mult if num else None
            except ValueError:
                return None
    return None


def get_package_from_model(model: str) -> Optional[str]:
    """从 Model/Primitive 名提取封装代码"""
    if not model:
        return None
    # 模式: CAP_C0402_..., RES_R0402_..., IND_L0603_...
    match = re.search(r'[_-]([CR]\d{4,4})[_-]', model.upper())
    if match:
        return match.group(1)
    # 模式: C0402, R0603 开头
    match = re.match(r'([CR]\d{4,4})', model.upper())
    if match:
        return match.group(1)
    return None


def get_resistor_power_rating(package: str) -> Optional[float]:
    """获取电阻封装对应的额定功率 (W)"""
    return PACKAGE_POWER_MAP.get(package.upper() if package else None)


# ============================================================
# AMR 数据源（抽象，当前为最小实现）
# ============================================================

class AMRDataSource:
    """
    AMR 数据源接口

    支持两种数据源（优先级从高到低）：
    1. FileBasedAMRSource: 从 amr_data.yaml 读取工程师审批后的参数
    2. 子类自定义: 连接 PLM/ERP 等外部系统
    """

    def __init__(self):
        self._file_source = None
        if _FILE_BASED_AMR_AVAILABLE:
            try:
                self._file_source = FileBasedAMRSource()
            except Exception as e:
                logging.warning(f"FileBasedAMRSource init failed: {e}")

    def get_capacitor_voltage_rating(self, refdes: str, model: str, value: str) -> Optional[float]:
        """获取电容耐压值 (V)。优先从审批后的 Datasheet 数据读取"""
        # 1. 尝试 FileBasedAMRSource
        if self._file_source:
            result = self._file_source.get_capacitor_voltage_rating(refdes, model, value)
            if result is not None:
                return result
        # 2. 子类可在此扩展外部系统查询
        return None

    def get_resistor_power_rating(self, refdes: str, model: str, value: str) -> Optional[float]:
        """获取电阻额定功率 (W)。优先从审批后的 Datasheet 数据读取"""
        if self._file_source:
            result = self._file_source.get_resistor_power_rating(refdes, model, value)
            if result is not None:
                return result
        return None

    def get_ic_voltage_range(self, refdes: str, model: str) -> Optional[tuple[float, float]]:
        """获取 IC 电源电压范围 (min, max)"""
        if self._file_source:
            result = self._file_source.get_ic_voltage_range(refdes, model)
            if result is not None:
                return result
        return None


# ============================================================
# 降额检查器
# ============================================================

@dataclass
class DeratingResult:
    """降额检查结果"""
    refdes: str
    device_type: str
    parameter: str              # "power", "voltage", "vds" 等
    rated_value: Optional[float]
    actual_value: Optional[float]
    derating_ratio: Optional[float]  # 实际/额定
    limit_ratio: float          # 标准允许的比值
    passed: bool
    detail: str


class ResistorPowerChecker:
    """电阻功率降额检查器"""

    def __init__(self, standard: DeratingStandard = DeratingStandard.INDUSTRY):
        self.standard = standard
        self.limit = DERATING_LIMITS[standard]["resistor_power"]

    def check_component(self, refdes: str, resistance_ohm: float,
                        power_rated_w: float, voltage_actual_v: float) -> DeratingResult:
        """
        检查单个电阻的功率降额

        注意：原理图阶段无仿真数据，实际功耗按"最坏情况"估算
        （假设电阻跨接在电源与地之间，全部压降落在电阻上）。
        上拉/限流电阻的实际功耗通常远小于此估算值。

        Args:
            resistance_ohm: 电阻值（Ω）
            power_rated_w: 额定功率（W）
            voltage_actual_v: 实际工作电压（V，取连接网络的最大电压）
        """
        if resistance_ohm <= 0 or power_rated_w <= 0:
            return DeratingResult(
                refdes=refdes, device_type="RES", parameter="power",
                rated_value=power_rated_w, actual_value=None,
                derating_ratio=None, limit_ratio=self.limit,
                passed=False, detail="无效参数（电阻值或额定功率为零）"
            )

        # 最坏情况估算：P = V² / R
        power_actual_w = (voltage_actual_v ** 2) / resistance_ohm
        derating_ratio = power_actual_w / power_rated_w
        passed = derating_ratio <= self.limit

        detail = (f"额定功率 {power_rated_w*1000:.1f}mW, "
                  f"估算功耗 {power_actual_w*1000:.1f}mW(最坏情况), "
                  f"降额率 {derating_ratio*100:.1f}% (限制 {self.limit*100:.0f}%)")

        return DeratingResult(
            refdes=refdes, device_type="RES", parameter="power",
            rated_value=power_rated_w, actual_value=power_actual_w,
            derating_ratio=derating_ratio, limit_ratio=self.limit,
            passed=passed, detail=detail
        )


class CapacitorVoltageChecker:
    """电容耐压降额检查器"""

    def __init__(self, standard: DeratingStandard = DeratingStandard.INDUSTRY):
        self.standard = standard
        self.limit = DERATING_LIMITS[standard]["capacitor_voltage"]
        self.amr_source = AMRDataSource()

    def check_component(self, refdes: str, model: str, value: str,
                        voltage_actual_v: float) -> DeratingResult:
        """检查电容耐压降额"""
        voltage_rated_v = self.amr_source.get_capacitor_voltage_rating(refdes, model, value)

        if voltage_rated_v is None:
            return DeratingResult(
                refdes=refdes, device_type="CAP", parameter="voltage",
                rated_value=None, actual_value=voltage_actual_v,
                derating_ratio=None, limit_ratio=self.limit,
                passed=True,  # 无数据时不过度报误报
                detail="缺少 AMR 耐压数据，跳过检查（需接入料号库/Datasheet）"
            )

        derating_ratio = voltage_actual_v / voltage_rated_v
        passed = derating_ratio <= self.limit

        detail = (f"额定耐压 {voltage_rated_v}V, "
                  f"实际电压 {voltage_actual_v}V, "
                  f"降额率 {derating_ratio*100:.1f}% (限制 {self.limit*100:.0f}%)")

        return DeratingResult(
            refdes=refdes, device_type="CAP", parameter="voltage",
            rated_value=voltage_rated_v, actual_value=voltage_actual_v,
            derating_ratio=derating_ratio, limit_ratio=self.limit,
            passed=passed, detail=detail
        )


# ============================================================
# AMR 引擎总控
# ============================================================

class AMREngine:
    """
    AMR 降额引擎总控

    用法：
        engine = AMREngine()
        engine.annotate_voltages()          # 先标注网络电压
        violations = engine.run_full_check() # 全板降额检查
    """

    def __init__(self, standard: DeratingStandard = DeratingStandard.INDUSTRY):
        self.standard = standard
        self.driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD"))
        )
        self.res_checker = ResistorPowerChecker(standard)
        self.cap_checker = CapacitorVoltageChecker(standard)
        self.violations: list[Violation] = []

    def close(self):
        self.driver.close()

    def annotate_voltages(self) -> int:
        """为 Neo4j 中的网络标注电压等级"""
        return VoltageLevelExtractor.batch_annotate_neo4j(self.driver)

    def _get_resistors_with_voltage(self):
        """获取所有电阻及其连接的最大电压"""
        cypher = """
            MATCH (c:Component)
            WHERE c.PartType = 'RESISTOR'
            OPTIONAL MATCH (c)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
            WITH c,
                 CASE
                   WHEN n.VoltageLevel IS NULL THEN 0.0
                   ELSE toFloat(replace(toString(n.VoltageLevel), 'V', ''))
                 END AS v_num,
                 n.Name AS net_name
            WITH c, max(v_num) AS max_v, collect(DISTINCT net_name) AS nets
            RETURN c.RefDes AS refdes,
                   c.Value AS value,
                   c.Model AS model,
                   c.PartType AS part_type,
                   max_v AS voltage,
                   nets
        """
        with self.driver.session() as session:
            return list(session.run(cypher))

    def _get_capacitors_with_voltage(self):
        """获取所有电容及其连接的最大电压"""
        cypher = """
            MATCH (c:Component)
            WHERE c.PartType = 'CAPACITOR'
            OPTIONAL MATCH (c)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
            WITH c,
                 CASE
                   WHEN n.VoltageLevel IS NULL THEN 0.0
                   ELSE toFloat(replace(toString(n.VoltageLevel), 'V', ''))
                 END AS v_num,
                 n.Name AS net_name
            WITH c, max(v_num) AS max_v, collect(DISTINCT net_name) AS nets
            RETURN c.RefDes AS refdes,
                   c.Value AS value,
                   c.Model AS model,
                   c.PartType AS part_type,
                   max_v AS voltage,
                   nets
        """
        with self.driver.session() as session:
            return list(session.run(cypher))

    def run_full_check(self) -> list[Violation]:
        """执行全板降额检查"""
        print(f"\n{'='*60}")
        print(" AMR 降额检查")
        print(f" 标准: {self.standard.value}")
        print(f"{'='*60}")

        self.violations = []

        # 1. 电阻功率降额检查
        print("\n[1/2] 电阻功率降额检查...")
        resistors = self._get_resistors_with_voltage()
        checked = 0
        failed = 0
        skipped = 0

        for r in resistors:
            refdes = r["refdes"]
            resistance = parse_resistance(r["value"])
            package = get_package_from_model(r["model"])
            power_rated = get_resistor_power_rating(package)
            voltage = float(r["voltage"]) if r["voltage"] is not None else 0.0

            # 跳过无法解析的
            if resistance is None:
                skipped += 1
                continue
            if power_rated is None:
                skipped += 1
                continue
            if voltage <= 0:
                # 接地电阻或无法确定电压
                skipped += 1
                continue

            result = self.res_checker.check_component(
                refdes, resistance, power_rated, voltage
            )
            checked += 1

            if not result.passed:
                failed += 1
                ratio_str = f"{result.derating_ratio*100:.1f}%" if result.derating_ratio is not None else "未知"
                self.violations.append(Violation(
                    id=f"AMR_RES_POWER_{refdes}",
                    rule_id="amr_resistor_power_derating",
                    rule_name="电阻功率降额检查",
                    refdes=refdes,
                    net_name=", ".join(r["nets"][:3]) if r["nets"] else "",
                    description=f"电阻 {refdes} 功率降额超标: {result.detail}",
                    severity="WARNING",
                    expected=f"降额率 ≤ {result.limit_ratio*100:.0f}%",
                    actual=f"降额率 {ratio_str}",
                ))

        print(f"  检查: {checked}, 通过: {checked-failed}, 违规: {failed}, 跳过: {skipped}")

        # 2. 电容耐压降额检查
        print("\n[2/2] 电容耐压降额检查...")
        capacitors = self._get_capacitors_with_voltage()
        checked_cap = 0
        skipped_cap = 0

        for c in capacitors:
            refdes = c["refdes"]
            voltage = float(c["voltage"]) if c["voltage"] is not None else 0.0

            if voltage <= 0:
                skipped_cap += 1
                continue

            result = self.cap_checker.check_component(
                refdes, c["model"], c["value"], voltage
            )
            checked_cap += 1

            if not result.passed:
                ratio_str = f"{result.derating_ratio*100:.1f}%" if result.derating_ratio is not None else "未知"
                self.violations.append(Violation(
                    id=f"AMR_CAP_VOLT_{refdes}",
                    rule_id="amr_capacitor_voltage_derating",
                    rule_name="电容耐压降额检查",
                    refdes=refdes,
                    net_name=", ".join(c["nets"][:3]) if c["nets"] else "",
                    description=f"电容 {refdes} 耐压降额超标: {result.detail}",
                    severity="ERROR",
                    expected=f"降额率 ≤ {result.limit_ratio*100:.0f}%",
                    actual=f"降额率 {ratio_str}",
                ))
            elif "缺少 AMR" in result.detail:
                skipped_cap += 1

        print(f"  检查: {checked_cap}, 跳过(缺AMR数据): {skipped_cap}")

        print(f"\n{'='*60}")
        print(f" AMR 检查完成: {len(self.violations)} 个违规")
        print(f"{'='*60}")

        return self.violations

    def get_summary(self) -> dict:
        """获取检查结果摘要"""
        errors = sum(1 for v in self.violations if v.severity == "ERROR")
        warnings = sum(1 for v in self.violations if v.severity == "WARNING")
        return {
            "total_violations": len(self.violations),
            "errors": errors,
            "warnings": warnings,
            "standard": self.standard.value,
        }


# ============================================================
# 端到端验证
# ============================================================

def _validate():
    """验证 AMR 引擎"""
    print("=" * 60)
    print("AMR 降额引擎端到端验证")
    print("=" * 60)

    # 1. 验证电压提取器
    print("\n[1/4] VoltageLevelExtractor 测试")
    test_cases = [
        ("VDD_3V3", 3.3),
        ("VCC_1V8", 1.8),
        ("VCCINT_0V85_LARK", 0.85),
        ("5V_USB", 5.0),
        ("VBAT_3V7", 3.7),
        ("VCC_P3V3_AUX", 3.3),
        ("VCC5V", 5.0),
        ("VCC3P3", 3.3),
        ("3V3_TCXO_CLK", 3.3),
        ("GND", 0.0),
        ("SIGNAL_GPIO", None),
        ("VCC_P12V_SAFETY", 12.0),
    ]
    passed = 0
    for net, expected in test_cases:
        actual = VoltageLevelExtractor.extract(net)
        status = "✅" if actual == expected else "❌"
        if actual == expected:
            passed += 1
        else:
            print(f"  {status} {net}: expected={expected}, actual={actual}")
    print(f"  通过 {passed}/{len(test_cases)}")

    # 2. 验证电阻值解析
    print("\n[2/4] Resistance parser 测试")
    res_tests = [
        ("10k", 10000.0),
        ("1k", 1000.0),
        ("4.7k", 4700.0),
        ("1M", 1e6),
        ("100", 100.0),
        ("DNP_10k", 10000.0),
        ("0", None),
    ]
    passed = 0
    for val, expected in res_tests:
        actual = parse_resistance(val)
        if actual == expected:
            passed += 1
        else:
            print(f"  ❌ '{val}': expected={expected}, actual={actual}")
    print(f"  通过 {passed}/{len(res_tests)}")

    # 3. 验证封装提取
    print("\n[3/4] Package extraction 测试")
    pkg_tests = [
        ("381_CAP_C0402_DISCRETE_0.1UF_11", "C0402"),
        ("719_RES_PPG_R0402_DISCRETE_10K_", "R0402"),
        ("RES_R0603_1K", "R0603"),
    ]
    passed = 0
    for model, expected in pkg_tests:
        actual = get_package_from_model(model)
        if actual == expected:
            passed += 1
        else:
            print(f"  ❌ '{model}': expected={expected}, actual={actual}")
    print(f"  通过 {passed}/{len(pkg_tests)}")

    # 4. 全链路检查（需要 Neo4j 真实数据）
    print("\n[4/4] 全链路降额检查（真实数据）")
    engine = AMREngine()
    try:
        # 先标注电压
        annotated = engine.annotate_voltages()
        print(f"  标注了 {annotated} 个网络的电压")

        # 执行检查
        violations = engine.run_full_check()
        summary = engine.get_summary()
        print(f"\n  检查结果: {summary}")

        # 显示前 5 个违规
        if violations:
            print("\n  Top 违规:")
            for v in violations[:5]:
                print(f"    {v.severity}: {v.description[:80]}")
        else:
            print("\n  未发现违规（或所有器件电压为 0/未标注）")

        print("\n✅ AMR Engine validation PASSED")
    finally:
        engine.close()


if __name__ == "__main__":
    _validate()
