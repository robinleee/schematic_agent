"""
网络电压标注扩展 — 从网络名模式 + 电源关系推断 VoltageLevel

策略：
1. 扩展命名规则（P-format、PVCC、VDD_xxx 等）
2. 从已标注的电源网络传播电压（同一器件的电源引脚相连）
3. 从 PMIC/LDO 输出推断

用法:
    python3 expand_voltage_annotation.py [--dry-run] [--apply]
"""

from __future__ import annotations

import os
import re
import sys
import logging
from collections import defaultdict
from typing import Optional, Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASS = "SecretPassword123"


# ============================================================
# 规则1: 网络名模式匹配
# ============================================================

# 扩展的电压命名模式（按优先级排序）
VOLTAGE_NAME_RULES = [
    # === P-format: 0P8=0.8V, 1P2=1.2V ===
    (r'(?<=[A-Z])(\d)P(\d)(?:V?)\b', 'P-format'),
    
    # === 标准 V-format: 3V3, 1V8, 0V9 ===
    (r'(?:^|[_\-])(\d)V(\d+)(?:[_\-]|$)', 'V-format'),
    
    # === VDD/VCC + voltage ===
    (r'(?:VDDQ?|VCC|AVDD|DVDD|IOVDD|PVDD)[_\-]?(\d+)V?(\d+)?(?:[_\-]|$)', 'VDD/VCC'),
    
    # === 显式 x.xV ===
    (r'(\d+\.\d+)V(?:[_\-]|$)', 'explicit_V'),
    
    # === SWREG/SW + voltage ===
    (r'(?:SWREG|SW)(\d)P(\d)', 'SWREG'),
]

# 已知 CPU 电源轨电压映射
KNOWN_RAIL_VOLTAGES = {
    # CPU VCCIN (Intel/AMD main power rail)
    r'PVCCIN(?!F)': '1.0',      # PVCCIN but NOT PVCCINF
    r'PVCCINF': '1.0',          # PVCCINF (VCCIN FIVR)
    r'PVCCINFAON': '1.0',       # PVCCIN FIVR Always-On
    r'PVCCD': '1.0',            # VCCD (digital)
    r'PVCCFA': '1.8',           # FAVCC (analog frontend)
    r'PVCCHV': '1.8',           # HV domain
    r'VDDHA': '1.8',            # High-voltage analog domain
    r'VDDA': '1.8',             # Analog VDD
    r'VDDIO': '3.3',            # IO VDD (typically 3.3V)
    
    # Battery
    r'VBAT': '3.3',             # Battery backup (CR2032 = 3V, system = 3.3V)
    r'VBAT_RTC': '3.0',         # RTC battery
    
    # Common PMIC outputs
    r'VDDQ': '1.2',             # DDR VDDQ
    r'VTT': '0.6',              # DDR VTT (half of VDDQ)
    r'VPP': '2.5',              # DDR VPP
    
    # LDO/Regulator outputs
    r'INTVCC': '5.0',           # Internal VCC of switching regulator
    r'VREF': '1.25',            # Voltage reference
}

# Component-type-based voltage inference
# If a net connects to a known PMIC/LDO output pin, infer voltage
PMIC_OUTPUT_VOLTAGES = {
    'TPS63070': 5.0,    # Buck-boost, adjustable but commonly 5V
    'TPS389006': None,  # Voltage supervisor, not a regulator
    'TLV733P': 3.3,     # LDO, commonly 3.3V variant
    'TPS7A47': None,    # Adjustable LDO, need feedback
}


def extract_voltage_from_name(net_name: str) -> Tuple[Optional[str], Optional[str]]:
    """
    从网络名推断电压，返回 (voltage_str, rule_name)
    """
    name_upper = net_name.upper()
    
    # 1. 已知电源轨映射
    for pattern, voltage in KNOWN_RAIL_VOLTAGES.items():
        if re.search(pattern, name_upper):
            # 确保不是 EN/PWRGD/SENSOR 等控制信号
            if any(kw in name_upper for kw in ['PWRGD', 'PWROK', 'SENSOR', 'ALERT', 'EN_R_', 'EN_LV']):
                continue
            return voltage, f'known_rail:{pattern}'
    
    # 2. 正则模式匹配
    for pattern, rule_name in VOLTAGE_NAME_RULES:
        m = re.search(pattern, name_upper)
        if m:
            groups = m.groups()
            if len(groups) == 2:
                voltage = f'{groups[0]}.{groups[1]}'
            else:
                voltage = groups[0]
            # 验证合理性
            try:
                v = float(voltage)
                if 0.1 <= v <= 60:  # 合理电压范围
                    return voltage, rule_name
            except ValueError:
                continue
    
    return None, None


def propagate_voltage_via_connections(driver) -> Dict[str, str]:
    """
    策略2: 从已标注的网络通过连接关系传播电压
    如果两个网络通过 0Ω 电阻或电感连接，它们电压相同
    """
    propagated = {}
    
    with driver.session() as session:
        # 查找 0Ω 电阻连接的网络对
        # 注意：0Ω 电阻连到 GND 的不应传播电压
        result = session.run("""
            MATCH (r:Component)-[:HAS_PIN]->(p1:Pin)-[:CONNECTS_TO]->(n1:Net),
                  (r)-[:HAS_PIN]->(p2:Pin)-[:CONNECTS_TO]->(n2:Net)
            WHERE r.PartType = 'RESISTOR' 
              AND n1 <> n2
              AND n1.VoltageLevel IS NOT NULL
              AND n2.VoltageLevel IS NULL
              AND n1.NetType <> 'GROUND'
              AND r.Value CONTAINS '0 '
            RETURN n1.Name AS src_net, n1.VoltageLevel AS voltage, 
                   n2.Name AS dst_net
        """)
        
        for record in result:
            src = record['src_net']
            voltage = record['voltage']
            dst = record['dst_net']
            if dst not in propagated:
                propagated[dst] = (voltage, f'via_zero_ohm:{src}')
        
        # 查找电感/铁氧体珠连接的网络
        result = session.run("""
            MATCH (r:Component)-[:HAS_PIN]->(p1:Pin)-[:CONNECTS_TO]->(n1:Net),
                  (r)-[:HAS_PIN]->(p2:Pin)-[:CONNECTS_TO]->(n2:Net)
            WHERE r.PartType IN ['INDUCTOR', 'FERRITE_BEAD', 'PASSIVE']
              AND n1 <> n2
              AND n1.VoltageLevel IS NOT NULL
              AND n2.VoltageLevel IS NULL
              AND n1.NetType = 'POWER'
            RETURN DISTINCT n1.Name AS src_net, n1.VoltageLevel AS voltage,
                   n2.Name AS dst_net
        """)
        
        for record in result:
            dst = record['dst_net']
            voltage = record['voltage']
            src = record['src_net']
            if dst not in propagated:
                propagated[dst] = (voltage, f'via_inductor:{src}')
    
    return propagated


def main():
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Preview only, don't write to Neo4j")
    parser.add_argument("--apply", action="store_true", help="Apply changes to Neo4j")
    args = parser.parse_args()
    
    # ========================================
    # Phase 1: 网络名推断
    # ========================================
    logger.info("Phase 1: Extracting voltage from net names...")
    
    name_results = {}  # net_name -> (voltage, rule)
    with driver.session() as session:
        result = session.run("""
            MATCH (n:Net) WHERE n.VoltageLevel IS NULL AND n.NetType = 'POWER'
            RETURN n.Name AS name
        """)
        unannotated = [r['name'] for r in result]
    
    logger.info(f"Unannotated POWER nets: {len(unannotated)}")
    
    for name in unannotated:
        voltage, rule = extract_voltage_from_name(name)
        if voltage:
            # Validate and normalize
            try:
                v_float = float(voltage)
                if v_float < 0.1:  # Skip 0V/near-zero
                    continue
                voltage = f"{v_float:.1f}"  # Normalize to e.g. "1.0", "3.3"
            except ValueError:
                continue
            name_results[name] = (voltage, rule)
    
    logger.info(f"Name-based extraction: {len(name_results)} nets")
    
    # ========================================
    # Phase 2: 连接关系传播
    # ========================================
    logger.info("Phase 2: Propagating voltage via connections...")
    propagated = propagate_voltage_via_connections(driver)
    logger.info(f"Propagation-based: {len(propagated)} nets")
    
    # Merge (name-based takes priority)
    all_results = {}
    all_results.update({k: v for k, v in propagated.items() if k not in name_results})
    all_results.update(name_results)
    
    # ========================================
    # Statistics
    # ========================================
    by_rule = defaultdict(int)
    by_voltage = defaultdict(int)
    for name, (voltage, rule) in all_results.items():
        by_rule[rule.split(':')[0]] += 1
        by_voltage[voltage] += 1
    
    print(f"\n{'='*60}")
    print(f"电压标注扩展结果")
    print(f"{'='*60}")
    print(f"未标注 POWER 网络: {len(unannotated)}")
    print(f"新标注: {len(all_results)}")
    print(f"覆盖率提升: {(792+len(all_results))*100//1195}% → target 80%+")
    
    print(f"\n按规则:")
    for rule, cnt in sorted(by_rule.items(), key=lambda x: -x[1]):
        print(f"  {rule}: {cnt}")
    
    print(f"\n按电压:")
    for v, cnt in sorted(by_voltage.items(), key=lambda x: float(x[0])):
        print(f"  {v}V: {cnt}")
    
    # Show samples
    print(f"\n示例:")
    for name, (voltage, rule) in list(all_results.items())[:15]:
        print(f"  {name} -> {voltage}V ({rule})")
    
    # ========================================
    # Apply to Neo4j
    # ========================================
    if args.apply and not args.dry_run:
        logger.info("Applying to Neo4j...")
        with driver.session() as session:
            for name, (voltage, rule) in all_results.items():
                session.run("""
                    MATCH (n:Net {Name: $name})
                    SET n.VoltageLevel = $voltage
                """, name=name, voltage=voltage)
        logger.info(f"Applied {len(all_results)} voltage annotations to Neo4j")
    else:
        logger.info("Dry run - no changes written. Use --apply to write to Neo4j.")
    
    driver.close()


if __name__ == "__main__":
    main()
