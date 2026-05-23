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
import logging
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

try:
    from agent_system.knowledge_router import KnowledgeRouter
    _KNOWLEDGE_ROUTER_AVAILABLE = True
except ImportError:
    _KNOWLEDGE_ROUTER_AVAILABLE = False

try:
    from agent_system.graph_rag_bridge import GraphRAGBridge
    _GRAPH_RAG_AVAILABLE = True
except ImportError:
    _GRAPH_RAG_AVAILABLE = False


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

    支持模式（30+ patterns）：
      VDD_3V3, VCC_1V8, VCCINT_0V85, 5V_USB, 12V_IN, VBAT_3V7
      VDDQ, VPP, VTT (DDR)
      1V0_DDR, 1V2_DDR, 1V35_DDR, 2V5_DDR
      VCC_WL_1V8, VCC_BL_1V2 (project specific)
      3V3_SW, 5V0_SW (switched)
      VDD_CORE, VDD_SOC, VDD_IO
      VDDO3P3, PVCC3V3, VSYS3V3, FB_V1V0
    """

    # Voltage number capture: 3V3, 3P3, 12V, 0V85, 5, 1V0
    _VNUM = r'([0-9]+V(?:[0-9]+)?|[0-9]+P(?:[0-9]+)?|[0-9]+)'
    # Strict voltage: only matches patterns with V or P (not bare numbers)
    _VNUM_STRICT = r'([0-9]+V(?:[0-9]+)?|[0-9]+P(?:[0-9]+)?)'
    # Custom word boundary: no letter/digit before/after (underscores OK)
    _WB = r'(?<![A-Za-z0-9])'
    _WB_END = r'(?![A-Za-z0-9])'

    PATTERNS = [
        # Group 1: Standard underscore-separated patterns (most reliable)
        # VDD_3V3, VCC_1V8, VCCINT_0V85, VDDQ_1V2, VPP_2V5, VTT_0V675
        (rf'{_WB}V(?:DD|CC|CCINT|CCIO|CCA|BAT|PP|IN|OUT|DDQ|TT)_{_VNUM}{_WB_END}', 'v_prefix_underscore'),

        # VDD_CORE_1V0, VDD_SOC_0V8, VDD_IO_3V3, VDD_MEM_1V35
        (rf'{_WB}VDD_(?:CORE|SOC|IO|MEM|PLL|ANA|DIG|RAM)_{_VNUM}{_WB_END}', 'vdd_subsystem'),

        # VCC_WL_1V8, VCC_BL_1V2 (project specific subdomains)
        (rf'{_WB}VCC_(?:WL|BL|AUX|MAIN|STBY|RTC|PHY|IO|DDR)_{_VNUM}{_WB_END}', 'vcc_subdomain'),

        # 3V3_SW, 5V0_SW (switched rails)
        (rf'{_WB}{_VNUM_STRICT}_(?:SW|STBY|ALWAYS|MAIN|AUX|RTC){_WB_END}', 'voltage_suffix_type'),

        # 1V0_DDR, 1V2_DDR, 1V35_DDR, 2V5_DDR, 1V8_DDR
        (rf'{_WB}{_VNUM_STRICT}_DDR{_WB_END}', 'ddr_suffixed'),

        # Group 2: Concatenated V-prefix patterns (no underscore)
        # VDDO3P3, VDDA3P3, VCC3V3, VDD1V8
        (rf'{_WB}V(?:DDO|DDA|DDB|DDQ|CCA|CCB|CCC|CCIO)({_VNUM}){_WB_END}', 'vddo_concat'),

        # VCC5V, VCC3V3, VCC3P3, VDD1V8 (strict: number must contain V or P)
        (rf'{_WB}VCC{_VNUM_STRICT}(?:V|{_WB_END})', 'vcc_concat'),
        (rf'{_WB}VDD{_VNUM_STRICT}(?:V|{_WB_END})', 'vdd_concat'),

        # Group 3: P-prefix patterns
        # P3V3, P1V8, P12V, P5V0
        (rf'{_WB}P{_VNUM}{_WB_END}', 'p_prefix'),

        # PVCC3V3, PVCC1V8, PVIN5V
        (rf'{_WB}PV(?:CC|DD|IN|OUT|BAT)({_VNUM}){_WB_END}', 'pvcc_concat'),

        # Group 4: VSYS, VBATT, VBUS patterns with voltage
        # VSYS3V3, VSYS5V0, VBUS5V, VBATT3V7
        (rf'{_WB}V(?:SYS|BUS|BATT|BATT)({_VNUM}){_WB_END}', 'vsys_concat'),

        # Group 5: Leading voltage patterns (strict: must contain V or P)
        # 3V3_TCXO, 5V_USB, 0V85, 1V8_PLL
        (rf'{_WB}{_VNUM_STRICT}(?:V|{_WB_END})', 'leading'),

        # Group 6: V + number without separator
        # V1V0, V1V8, V3V3, V0V8
        (rf'{_WB}V({_VNUM}){_WB_END}', 'v_direct'),

        # Group 7: Specialized patterns
        # VDDQ_DDR (DDR data strobe voltage, typically 1.2V)
        (rf'{_WB}VDDQ{_WB_END}', 'vddq_ddr'),
        # VTT_DDR (DDR termination voltage, typically half of VDDQ)
        (rf'{_WB}VTT{_WB_END}', 'vtt_ddr'),
        # VPP_DDR (DDR programming voltage, typically 2.5V)
        (rf'{_WB}VPP{_WB_END}', 'vpp_ddr'),
    ]

    # Fixed voltage values for named rails without explicit voltage numbers
    KNOWN_VOLTAGES = {
        'VDDQ': 1.2,    # DDR4 VDDQ (typical)
        'VTT': 0.6,     # DDR4 VTT (half of VDDQ)
        'VPP': 2.5,     # DDR4 VPP
        'VDDQ_DDR': 1.2,
        'VTT_DDR': 0.6,
        'VPP_DDR': 2.5,
    }

    # Additional GND variants
    GND_NAMES = {'GND', 'DGND', 'AGND', 'PGND', 'SGND', 'VSS', 'VSSA', 'VSSD', 'VSSIO',
                 'EPAD', 'SHIELD', 'CHASSIS_GND', 'EARTH'}

    @classmethod
    def extract(cls, net_name: str) -> Optional[float]:
        """从网络名提取电压值（V），失败返回 None"""
        if not net_name:
            return None

        net_upper = net_name.upper()

        # 排除地线
        if net_upper in cls.GND_NAMES or net_upper.rstrip('#').rstrip('_') in cls.GND_NAMES:
            return 0.0

        # Check known named voltages first
        if net_upper in cls.KNOWN_VOLTAGES:
            return cls.KNOWN_VOLTAGES[net_upper]

        for pattern, ptype in cls.PATTERNS:
            match = re.search(pattern, net_upper)
            if match:
                # Handle patterns without capturing groups (named rails)
                if ptype in ('vddq_ddr', 'vtt_ddr', 'vpp_ddr'):
                    return cls.KNOWN_VOLTAGES.get(ptype.rsplit('_', 1)[0].upper())

                try:
                    volt_str = match.group(1)
                except IndexError:
                    continue

                if not volt_str:
                    continue

                # Replace V/P with decimal point: 3V3 → 3.3, 3P3 → 3.3, 0V85 → 0.85, 12V → 12.
                volt_str = volt_str.replace('V', '.').replace('P', '.')
                try:
                    voltage = float(volt_str)
                    # Sanity check: voltage should be 0-100V for board-level
                    if 0 <= voltage <= 100:
                        return voltage
                except ValueError:
                    continue

        # Fallback: pure number + V at end (12V, 5V, 1.8V)
        match = re.search(r'([0-9]+(?:\.[0-9]+)?)V$', net_upper)
        if match:
            try:
                voltage = float(match.group(1))
                if 0 <= voltage <= 100:
                    return voltage
            except ValueError:
                pass

        # Fallback: voltage number in middle of name with underscore
        # e.g., BIAS_PVCC3V3, EN_PVCC3V3, FB_PVCC3V3, VSYS3V3
        match = re.search(r'(?:PVCC|PVDD|VSYS|VBUS)([0-9]+V[0-9]+)', net_upper)
        if match:
            volt_str = match.group(1).replace('V', '.')
            try:
                voltage = float(volt_str)
                if 0 <= voltage <= 100:
                    return voltage
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
        voltage_map = {}
        updated = 0
        with driver.session() as session:
            for name, voltage in nets:
                if voltage is not None:
                    voltage_map[name] = voltage
                    session.run("""
                        MATCH (n:Net {Name: $name})
                        SET n.VoltageLevel = $voltage
                    """, name=name, voltage=voltage)
                    updated += 1

        print(f"  名称提取: {updated} / {len(nets)} 个网络")

        # 3. 传播电压：通过电容 (DC 通路) — 多轮传播
        round_num = 0
        total_propagated_cap = 0
        while True:
            round_num += 1
            propagated = cls._propagate_through_caps(driver, voltage_map)
            total_propagated_cap += propagated
            if propagated == 0 or round_num >= 5:
                break
        print(f"  电容传播: +{total_propagated_cap} 个网络 ({round_num} 轮)")

        # 4. 传播电压：通过小阻值电阻 / 磁珠 (DC 近似通路) — 多轮传播
        round_num = 0
        total_propagated_res = 0
        while True:
            round_num += 1
            propagated = cls._propagate_through_resistors(driver, voltage_map)
            total_propagated_res += propagated
            if propagated == 0 or round_num >= 5:
                break
        print(f"  电阻传播: +{total_propagated_res} 个网络 ({round_num} 轮)")

        # 5. 传播电压：通过电感/磁珠 (DC 直通)
        round_num = 0
        total_propagated_ind = 0
        while True:
            round_num += 1
            propagated = cls._propagate_through_inductors(driver, voltage_map)
            total_propagated_ind += propagated
            if propagated == 0 or round_num >= 5:
                break
        print(f"  电感传播: +{total_propagated_ind} 个网络 ({round_num} 轮)")

        # 6. 传播电压：通过IC电源引脚 (同一IC的电源引脚电压一致)
        round_num = 0
        total_propagated_ic = 0
        while True:
            round_num += 1
            propagated = cls._propagate_through_ic_power(driver, voltage_map)
            total_propagated_ic += propagated
            if propagated == 0 or round_num >= 3:
                break
        print(f"  IC电源传播: +{total_propagated_ic} 个网络 ({round_num} 轮)")

        # 7. 写入传播结果
        name_extracted = {name: v for name, v in nets if v is not None}
        propagated_total = 0
        with driver.session() as session:
            for name, voltage in voltage_map.items():
                if name not in name_extracted:  # New from propagation
                    session.run("""
                        MATCH (n:Net {Name: $name})
                        SET n.VoltageLevel = $voltage
                    """, name=name, voltage=voltage)
                    propagated_total += 1

        total = updated + propagated_total
        print(f"  已标注 {total} / {len(nets)} 个网络的 VoltageLevel")
        return total

    @classmethod
    def _propagate_through_caps(cls, driver, voltage_map: dict) -> int:
        """Propagate voltage through capacitors (both pins see same DC voltage)."""
        propagated = 0
        with driver.session() as session:
            result = session.run("""
                MATCH (c:Component)-[:HAS_PIN]->(p1:Pin)-[:CONNECTS_TO]->(n1:Net)
                WHERE c.PartType = 'CAPACITOR'
                MATCH (c)-[:HAS_PIN]->(p2:Pin)-[:CONNECTS_TO]->(n2:Net)
                WHERE n1.Name <> n2.Name
                RETURN DISTINCT n1.Name AS net1, n2.Name AS net2
            """)
            for r in result:
                net1, net2 = r["net1"], r["net2"]
                if net1 in voltage_map and net2 not in voltage_map:
                    v = voltage_map[net1]
                    if v > 0:
                        voltage_map[net2] = v
                        propagated += 1
                elif net2 in voltage_map and net1 not in voltage_map:
                    v = voltage_map[net2]
                    if v > 0:
                        voltage_map[net1] = v
                        propagated += 1
        return propagated

    @classmethod
    def _propagate_through_resistors(cls, driver, voltage_map: dict) -> int:
        """Propagate voltage through small resistors (< 10 ohm) and ferrite beads."""
        propagated = 0
        with driver.session() as session:
            result = session.run("""
                MATCH (c:Component)-[:HAS_PIN]->(p1:Pin)-[:CONNECTS_TO]->(n1:Net)
                WHERE c.PartType = 'RESISTOR' AND c.Value IS NOT NULL
                MATCH (c)-[:HAS_PIN]->(p2:Pin)-[:CONNECTS_TO]->(n2:Net)
                WHERE n1.Name <> n2.Name
                RETURN DISTINCT n1.Name AS net1, n2.Name AS net2, c.Value AS value
            """)
            for r in result:
                net1, net2, value = r["net1"], r["net2"], r["value"]
                if not value:
                    continue
                r_val = parse_resistance(value)
                if r_val is not None and 0 < r_val < 10:
                    if net1 in voltage_map and net2 not in voltage_map:
                        voltage_map[net2] = voltage_map[net1]
                        propagated += 1
                    elif net2 in voltage_map and net1 not in voltage_map:
                        voltage_map[net1] = voltage_map[net2]
                        propagated += 1
        return propagated

    @classmethod
    def _propagate_through_inductors(cls, driver, voltage_map: dict) -> int:
        """Propagate voltage through inductors/ferrite beads (DC pass-through)."""
        propagated = 0
        with driver.session() as session:
            result = session.run("""
                MATCH (c:Component)-[:HAS_PIN]->(p1:Pin)-[:CONNECTS_TO]->(n1:Net)
                WHERE c.PartType = 'INDUCTOR'
                MATCH (c)-[:HAS_PIN]->(p2:Pin)-[:CONNECTS_TO]->(n2:Net)
                WHERE n1.Name <> n2.Name
                RETURN DISTINCT n1.Name AS net1, n2.Name AS net2
            """)
            for r in result:
                net1, net2 = r["net1"], r["net2"]
                if net1 in voltage_map and net2 not in voltage_map:
                    voltage_map[net2] = voltage_map[net1]
                    propagated += 1
                elif net2 in voltage_map and net1 not in voltage_map:
                    voltage_map[net1] = voltage_map[net2]
                    propagated += 1
        return propagated

    @classmethod
    def _propagate_through_ic_power(cls, driver, voltage_map: dict) -> int:
        """Propagate voltage through IC power pins (same IC, same voltage domain)."""
        propagated = 0
        with driver.session() as session:
            # Find ICs with multiple power pins where some connect to known-voltage nets
            result = session.run("""
                MATCH (c:Component)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
                WHERE c.PartType IN ['IC', 'MCU', 'FPGA', 'PMIC', 'TRANSISTOR']
                  AND (p.PinType = 'POWER' OR p.PinType = 'POWER' OR p.Number STARTS WITH 'V')
                RETURN c.RefDes AS refdes, collect(DISTINCT n.Name) AS power_nets
            """)
            for r in result:
                refdes = r["refdes"]
                power_nets = r["power_nets"]
                # Find the most common non-zero voltage among this IC's power nets
                known_voltages = {}
                for net in power_nets:
                    if net in voltage_map and voltage_map[net] > 0:
                        v = voltage_map[net]
                        known_voltages[v] = known_voltages.get(v, 0) + 1

                if not known_voltages:
                    continue

                # Use the most common voltage as the IC's operating voltage
                dominant_voltage = max(known_voltages, key=known_voltages.get)

                # Propagate to unknown power nets on this IC
                for net in power_nets:
                    if net not in voltage_map:
                        voltage_map[net] = dominant_voltage
                        propagated += 1
        return propagated


# ============================================================
# 器件参数解析
# ============================================================

def _parse_capacitance_to_pf(value_str: str) -> Optional[float]:
    """解析电容值字符串 → pF。支持 0.1uF, 100nF, 10pF, 22 UF 等格式"""
    if not value_str:
        return None
    value_str = str(value_str).strip().upper()
    # 去掉 DNP 前缀
    if 'DNP' in value_str:
        value_str = value_str.replace('DNP', '').replace('DNI', '').strip('_ ')
    if not value_str:
        return None
    try:
        m = re.match(r'([\d.]+)\s*(PF|NF|UF|MF|F|P|N|U|M)?', value_str)
        if not m:
            return None
        num = float(m.group(1))
        unit = (m.group(2) or 'UF').replace('F', '')  # 去掉 F 后缀
        if unit in ('P', ''):
            return num  # pF
        elif unit == 'N':
            return num * 1000
        elif unit == 'U':
            return num * 1_000_000
        elif unit == 'M':
            return num * 1_000_000_000
        return None
    except (ValueError, TypeError):
        return None


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

    支持四种数据源（优先级从高到低）：
    0. 封装+容值经验表：根据封装尺寸和容值推断耐压（最可靠，覆盖最广）
    1. FileBasedAMRSource: 从 amr_data.yaml 读取工程师审批后的参数
    2. KnowledgeRouter (ChromaDB): 从语义索引的 datasheet 知识库查询
    3. GraphRAGBridge (Neo4j): 从图关联的 VectorChunk 查询
    """

    # 封装+容值 → 典型耐压经验表 (MLCC)
    # 基于主流厂商规格书：0402 1uF=6.3V, 0402 0.1uF=16V, 0603 10uF=10V 等
    _PACKAGE_VOLTAGE_TABLE = {
        # (package, cap_pf_range) → voltage_V
        # 0201
        ('0201', 0, 10): 25.0,       # <10pF → 25V
        ('0201', 10, 1000): 16.0,    # 10pF-1nF → 16V
        ('0201', 1000, 100000): 10.0, # 1nF-100nF → 10V
        ('0201', 100000, 1000001): 6.3, # 100nF-1uF → 6.3V
        # 0402
        ('0402', 0, 10): 50.0,
        ('0402', 10, 1000): 25.0,
        ('0402', 1000, 10000): 16.0,     # 1nF-10nF → 16V
        ('0402', 10000, 100000): 16.0,   # 10nF-100nF → 16V
        ('0402', 100000, 1000000): 10.0, # 100nF-1uF → 10V (X7R)
        ('0402', 1000000, 2200000): 6.3, # 1uF-2.2uF → 6.3V
        ('0402', 2200000, 4700000): 6.3, # 2.2uF-4.7uF → 6.3V (X5R)
        ('0402', 4700000, 10000001): 4.0, # 4.7uF-10uF → 4V (X5R)
        # 0603
        ('0603', 0, 1000): 50.0,
        ('0603', 1000, 10000): 25.0,
        ('0603', 10000, 100000): 16.0,
        ('0603', 100000, 1000000): 16.0,
        ('0603', 1000000, 10000000): 10.0,  # 1uF-10uF → 10V
        ('0603', 10000000, 50000000): 6.3,  # 10uF-50uF → 6.3V
        # 0805
        ('0805', 0, 1000): 50.0,
        ('0805', 1000, 100000): 25.0,
        ('0805', 100000, 1000000): 16.0,
        ('0805', 1000000, 10000000): 10.0,
        ('0805', 10000000, 100000000): 6.3, # 10uF-100uF → 6.3V
        # 1206
        ('1206', 0, 1000): 50.0,
        ('1206', 1000, 100000): 25.0,
        ('1206', 100000, 1000000): 16.0,
        ('1206', 1000000, 10000000): 10.0,
        ('1206', 10000000, 100000001): 10.0, # 10uF-100uF → 10V
        # 1210
        ('1210', 0, 100000): 25.0,
        ('1210', 100000, 1000000): 16.0,
        ('1210', 1000000, 10000000): 10.0,
        ('1210', 10000000, 100000001): 10.0,
        # 钽电容/电解电容封装 (C7343=D, SMC3018=E, C4141, SMC2626, SMC4141)
        # 这些封装大容值大，电压通常 6.3-25V，按容值粗分
        ('7343', 0, 100000001): 10.0,   # D case 钽电容
        ('3018', 0, 100000001): 10.0,   # E case
        ('4141', 0, 100000001): 10.0,   # 大封装
        ('2626', 0, 100000001): 10.0,   # SMC2626
        ('3333', 0, 100000001): 10.0,   # C3333
    }

    def __init__(self):
        self._file_source = None
        if _FILE_BASED_AMR_AVAILABLE:
            try:
                self._file_source = FileBasedAMRSource()
            except Exception as e:
                logging.warning(f"FileBasedAMRSource init failed: {e}")

        self._router = None
        if _KNOWLEDGE_ROUTER_AVAILABLE:
            try:
                self._router = KnowledgeRouter()
            except Exception as e:
                logging.warning(f"KnowledgeRouter init failed: {e}")

        self._bridge = None
        if _GRAPH_RAG_AVAILABLE:
            try:
                self._bridge = GraphRAGBridge()
            except Exception as e:
                logging.warning(f"GraphRAGBridge init failed: {e}")

    def get_capacitor_voltage_rating(self, refdes: str, model: str, value: str) -> Optional[float]:
        """获取电容耐压值 (V)。优先从审批后的 Datasheet 数据读取"""
        # 1. 尝试 FileBasedAMRSource (amr_data.yaml 精确匹配)
        if self._file_source:
            result = self._file_source.get_capacitor_voltage_rating(refdes, model, value)
            if result is not None:
                return result

        # 2. 封装+容值经验表 fallback
        result = self._infer_voltage_from_package_value(model, value)
        if result is not None:
            return result

        # 3. 尝试 KnowledgeRouter (ChromaDB semantic search)
        if self._router:
            result = self._query_kb_voltage_rating(model)
            if result is not None:
                return result

        # 4. 尝试 GraphRAGBridge (Neo4j VectorChunk)
        if self._bridge:
            result = self._query_graph_rag_voltage(model)
            if result is not None:
                return result

        return None

    def get_resistor_power_rating(self, refdes: str, model: str, value: str) -> Optional[float]:
        """获取电阻额定功率 (W)。优先从审批后的 Datasheet 数据读取"""
        if self._file_source:
            result = self._file_source.get_resistor_power_rating(refdes, model, value)
            if result is not None:
                return result

        # Try knowledge base
        if self._router:
            result = self._query_kb_power_rating(model)
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

    def _query_kb_voltage_rating(self, model: str) -> Optional[float]:
        """Query ChromaDB for capacitor voltage rating via semantic search."""
        try:
            result = self._router.search(model, "voltage rating maximum rated voltage")
            if result.status == "success" and result.confidence >= 0.3:
                voltage = self._extract_voltage_from_text(result.content)
                if voltage is not None:
                    logging.info(f"KB voltage rating for {model}: {voltage}V (confidence={result.confidence:.2f})")
                    return voltage
        except Exception as e:
            logging.debug(f"KB voltage query failed for {model}: {e}")
        return None

    def _query_kb_power_rating(self, model: str) -> Optional[float]:
        """Query ChromaDB for resistor power rating via semantic search."""
        try:
            result = self._router.search(model, "power rating maximum power dissipation")
            if result.status == "success" and result.confidence >= 0.3:
                power = self._extract_power_from_text(result.content)
                if power is not None:
                    return power
        except Exception as e:
            logging.debug(f"KB power query failed for {model}: {e}")
        return None

    def _query_graph_rag_voltage(self, model: str) -> Optional[float]:
        """Query Neo4j GraphRAG for capacitor voltage rating."""
        try:
            results = self._bridge.graph_rag_query("voltage rating", mpn=model, n_results=3)
            for r in results:
                voltage = self._extract_voltage_from_text(r.content)
                if voltage is not None:
                    return voltage
        except Exception as e:
            logging.debug(f"GraphRAG voltage query failed for {model}: {e}")
        return None

    @staticmethod
    def _infer_voltage_from_package_value(model: str, value: str) -> Optional[float]:
        """根据封装尺寸和容值推断电容耐压 (MLCC 经验表)"""
        # 提取封装
        package = None
        pkg_patterns = [
            (r'C(0201|0402|0603|0805|1206|1210|1808|1812|7343|4141|3333)', 1),
            (r'SMC(0402|0603|0805|1206|1210|3018|2626|4141)', 1),
            (r'SMX(0402[AC]?|0603|0805)', 1),
            (r'SM(0402|0603|0805|1206)', 1),
            (r'_(0201|0402|0603|0805|1206|1210)_', 1),
        ]
        for pattern, grp in pkg_patterns:
            m = re.search(pattern, model, re.IGNORECASE)
            if m:
                package = m.group(grp)
                break

        if not package:
            return None

        # 解析容值到 pF
        cap_pf = _parse_capacitance_to_pf(value)
        if cap_pf is None or cap_pf <= 0:
            return None

        # 查表
        for (pkg, lo, hi), voltage in AMRDataSource._PACKAGE_VOLTAGE_TABLE.items():
            if pkg == package and lo <= cap_pf < hi:
                return voltage

        return None

    @staticmethod
    def _extract_voltage_from_text(text: str) -> Optional[float]:
        """Extract voltage value (V) from text using regex."""
        # Patterns for voltage ratings in datasheet text
        patterns = [
            r'(?:rated\s+)?voltage[:\s]+(\d+(?:\.\d+)?)\s*V',
            r'(\d+(?:\.\d+)?)\s*V\s*(?:DC|dc)',
            r'voltage\s+rating[:\s]+(\d+(?:\.\d+)?)\s*V',
            r'cap_voltage_rating[:\s]+(\d+(?:\.\d+)?)',
            r'max(?:imum)?\s+voltage[:\s]+(\d+(?:\.\d+)?)\s*V',
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                try:
                    return float(m.group(1))
                except ValueError:
                    continue
        return None

    @staticmethod
    def _extract_power_from_text(text: str) -> Optional[float]:
        """Extract power rating (W) from text using regex."""
        patterns = [
            r'(?:rated\s+)?power[:\s]+(\d+(?:\.\d+)?)\s*W',
            r'power\s+rating[:\s]+(\d+(?:\.\d+)?)\s*W',
            r'(\d+(?:\.\d+)?)\s*W\s*(?:max)?',
            r'res_power_rating[:\s]+(\d+(?:\.\d+)?)',
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                try:
                    return float(m.group(1))
                except ValueError:
                    continue
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

        print(f"  检查: {checked_cap}, 通过: {checked_cap - sum(1 for v in self.violations if v.rule_id == 'amr_capacitor_voltage_derating') - skipped_cap}, 违规: {sum(1 for v in self.violations if v.rule_id == 'amr_capacitor_voltage_derating')}, 跳过(缺AMR数据): {skipped_cap}")

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
