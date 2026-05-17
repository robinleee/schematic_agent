"""
知识库初始化脚本 — 批量导入硬件设计知识到 ChromaDB

内容来源：
1. 内置设计规则（硬编码的硬件设计最佳实践）
2. AMR 降额规范
3. Datasheet 提取的关键参数

用法:
    python3 initialize_knowledge_base.py [--verbose]
"""

from __future__ import annotations

import os
import sys
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ============================================================
# 内置硬件设计知识库
# ============================================================

DESIGN_RULES = {
    "i2c": [
        {
            "title": "I2C Pull-up Resistor Selection",
            "content": """I2C pull-up resistor selection guidelines:

Standard Mode (100kHz): Rp = 1kΩ ~ 10kΩ
Fast Mode (400kHz): Rp = 1kΩ ~ 4.7kΩ  
High-Speed Mode (3.4MHz): Rp = 200Ω ~ 1kΩ

Calculation: Rp(min) = (Vdd - 0.4V) / 3mA
             Rp(max) = t_r / (0.8473 × C_b)

Where t_r is the rise time and C_b is total bus capacitance.
For typical 3.3V bus with 200pF capacitance: Rp ≈ 4.7kΩ

Common issues:
- Too large Rp: slow rise time, communication errors
- Too small Rp: excessive current, driver cannot pull down
- Multiple devices: Rp decreases (parallel resistors)""",
            "category": "i2c"
        },
        {
            "title": "I2C Bus Voltage Level",
            "content": """I2C bus voltage requirements:
- Standard/Fast mode: Vdd range 2.0V to 5.5V
- I2C devices must tolerate bus voltage
- Voltage translation needed between 1.8V and 3.3V domains
- Use bidirectional level shifters (e.g., PCA9306)
- Pull-up resistors connect to the higher voltage side""",
            "category": "i2c"
        },
    ],
    "power": [
        {
            "title": "Decoupling Capacitor Placement",
            "content": """Decoupling capacitor best practices:

Placement rules:
- Place 100nF X7R capacitor within 2mm of each IC power pin
- Add 1~10µF bulk capacitor per power rail
- Use wide and short traces from cap to power pin
- Via placement: between cap and IC, not between cap and power plane

Capacitor selection by frequency:
- Low frequency (<1MHz): 1~10µF ceramic or tantalum
- Medium frequency (1~100MHz): 100nF X7R 0402
- High frequency (>100MHz): 1~10nF X7R 0201/0402

Common mistakes:
- Placing decoupling caps too far from pins
- Using Y5V/Z5U dielectrics (poor temperature/voltage stability)
- Missing bulk capacitors for transient response""",
            "category": "power"
        },
        {
            "title": "Power Supply Sequencing",
            "content": """Power sequencing requirements:
- Core voltage (VDD) must be stable before I/O voltage (VDDIO)
- Typical sequence: VDD_CORE → VDD_IO → VDDA
- Use PMIC with built-in sequencer or discrete supervisor
- Ramp rate: typically 0.5~5mV/µs
- Maximum delay between rails: consult datasheet

Reset requirements:
- Hold reset low until all power rails are stable
- Minimum reset pulse width: typically 1~100ms
- Use voltage supervisor (TPS38xx) for reliable detection""",
            "category": "power"
        },
        {
            "title": "LDO vs Buck Regulator Selection",
            "content": """Voltage regulator selection guide:

LDO (Low Dropout Regulator):
- Use when: Vout close to Vin, low noise required, Iout < 500mA
- Efficiency = Vout/Vin (can be very low for large dropout)
- Output noise: typically 10~100µVrms
- Best for: analog circuits, RF, precision ADC/DAC reference

Buck (Step-down) Regulator:
- Use when: large Vin-Vout difference, Iout > 500mA, efficiency matters
- Efficiency: typically 85~95%
- Output ripple: 10~100mVpp (needs LC filter for sensitive loads)
- Best for: digital core, high-current rails

Buck-Boost:
- Use when: Vin can be above or below Vout (battery powered)
- Efficiency: typically 80~90%""",
            "category": "power"
        },
        {
            "title": "PCB Power Plane Design",
            "content": """PCB power plane design guidelines:

Layer stackup:
- Dedicated power and ground planes on adjacent layers
- Power plane provides low-inductance distribution
- Ground plane under signal traces for return path

Via placement:
- Add ground vias near every component ground pin
- Use multiple vias for high-current paths (>1A)
- Stitching vias around board edges for EMI

PDN (Power Distribution Network) analysis:
- Target impedance: Z = ΔV/ΔI
- For 1.0V rail with 5% tolerance and 5A transient: Z < 10mΩ
- Use multiple capacitor values in parallel for wideband impedance""",
            "category": "power"
        },
    ],
    "esd": [
        {
            "title": "ESD Protection Design",
            "content": """ESD protection design guidelines:

Interface protection:
- USB: TVS diode with Vcl < 5.5V, capacitance < 1pF for high-speed
- Ethernet: TVS with Vcl < 6V, support common-mode protection
- HDMI: Low-capacitance TVS (<0.5pF) on each differential pair
- GPIO: General TVS or Zener, Vcl within IC abs max rating

Placement rules:
- TVS diode within 5mm of connector pin
- TVS between connector and series resistor
- Ground connection must be short and direct to chassis ground

Clamping voltage selection:
- Vcl must be below IC absolute maximum voltage
- Typical margin: Vcl < 80% of IC abs max
- For 3.3V I/O with 6V abs max: use TVS with Vcl < 5V

Common mistakes:
- Placing TVS after series resistor (wrong - must be before)
- Using TVS with too high clamping voltage
- No separate chassis ground for TVS discharge""",
            "category": "esd"
        },
    ],
    "thermal": [
        {
            "title": "Thermal Design Guidelines",
            "content": """Thermal management best practices:

Junction temperature limits:
- Commercial: 0°C to 85°C
- Industrial: -40°C to 105°C  
- Automotive: -40°C to 125°C or 150°C

Thermal resistance path: Tj = Ta + Pd × (θjc + θcs + θsa)
- θjc: junction-to-case (from datasheet)
- θcs: case-to-heatsink (0.1~1.0°C/W with thermal paste)
- θsa: heatsink-to-ambient (depends on heatsink + airflow)

PCB thermal design:
- Use thermal vias under IC pads (4-6 vias for QFN)
- Copper pour on adjacent layers for heat spreading
- 2oz copper for high-current traces
- Avoid thermal relief pads for power components""",
            "category": "thermal"
        },
    ],
    "si": [
        {
            "title": "Signal Integrity Basics",
            "content": """Signal integrity design rules:

Impedance matching:
- Single-ended: 50Ω for RF, 55Ω for DDR
- Differential: 100Ω differential (50Ω single-ended)
- Controlled impedance requires stackup design with PCB vendor

Termination:
- Series termination: at source, value = Ztrace - Zdriver
- Parallel termination: at load, value = Ztrace
- Differential: 100Ω across pair or 50Ω each to Vref

Crosstalk reduction:
- Increase spacing between critical signals (3× trace width minimum)
- Route high-speed signals on inner layers between ground planes
- Avoid parallel runs of unrelated signals > 500mil
- Guard traces with ground vias for sensitive signals""",
            "category": "si"
        },
    ],
    "ddr": [
        {
            "title": "DDR Layout Guidelines",
            "content": """DDR memory interface layout rules:

Signal grouping:
- Data group: DQ[0-7], DQS, DM per byte lane
- Address/Command group: A[0-15], BA[0-2], CAS#, RAS#, WE#, CS#
- Clock group: CK/CK#, differential pair

Length matching:
- Within byte lane: ±10ps (DQ to DQS)
- Between byte lanes: ±25ps
- Address/command to clock: ±25ps
- Use serpentining for length matching

Power requirements:
- VDD: 1.2V (DDR4) / 1.1V (DDR5) with ±30mV tolerance
- VDDQ: same as VDD
- VTT: VDDQ/2, must be able to sink and source current
- VREF: VDDQ/2, use precision resistor divider or VREF buffer

Decoupling:
- 1× 100nF per 2 data pins
- Bulk: 4.7µF per VDD pin
- VTT: 1× 100nF per termination resistor + 10µF bulk""",
            "category": "ddr"
        },
    ],
    "pcie": [
        {
            "title": "PCIe Design Guidelines",
            "content": """PCI Express interface design rules:

Signal requirements:
- Differential pairs: TX+/TX-, RX+/RX-
- Impedance: 85Ω differential (±10%)
- AC coupling capacitors: 75~200nF on TX pairs only

Length matching:
- Within pair: <5mil skew
- Between pairs: <10mil skew
- Total route length per spec (Gen3: <12 inches)

Power:
- PCIe slot power: +12V, +3.3V, +3.3Vaux
- Maximum per slot: 12V@5A (60W) or 3.3V@3A (10W)
- Active-state power management (ASPM) for power savings""",
            "category": "pcie"
        },
    ],
    "usb": [
        {
            "title": "USB Interface Design",
            "content": """USB interface design guidelines:

Signal requirements:
- USB 2.0: D+/D- differential, 480Mbps max
- USB 3.x: TX+/TX-, RX+/RX- SuperSpeed pairs
- Impedance: 90Ω differential (±10%)

Pull-up/pull-down resistors:
- Full-speed device: 1.5kΩ D+ to VCC
- Low-speed device: 1.5kΩ D- to VCC  
- Host: 15kΩ D+ and D- to GND

Power:
- USB 2.0: 5V, 500mA per port
- USB 3.0: 5V, 900mA per port
- USB-C: 5V, up to 3A (15W) or 5A with PD

ESD protection:
- TVS on D+/D- with Vcl < 5.5V
- Low capacitance (<1pF) for USB 3.x SuperSpeed pairs
- Place TVS within 5mm of connector""",
            "category": "usb"
        },
    ],
}

AMR_DERATING_KNOWLEDGE = [
    {
        "title": "Capacitor Voltage Derating Standard",
        "content": """Capacitor voltage derating requirements:

MLCC (Multi-Layer Ceramic Capacitor):
- Class I (C0G/NP0): 50% derating recommended (operating ≤ 50% of rated voltage)
- Class II (X7R/X5R): 50% derating mandatory (DC bias effect reduces effective capacitance)
- Class III (Y5V/Z5U): 70% derating recommended (poor stability)

DC Bias Effect:
- X7R/X5R capacitors lose 30~60% capacitance at rated voltage
- Always check manufacturer's DC bias curve
- Derating to 50% typically preserves 80%+ of nominal capacitance

Temperature considerations:
- X7R: ±15% over -55°C to +125°C
- X5R: ±15% over -55°C to +85°C
- C0G: ±30ppm/°C (extremely stable)

Tantalum capacitors:
- 50% voltage derating mandatory
- Failure mode: ignition (fire risk if derating not followed)
- Recommended: use polymer tantalum for lower ESR and safer failure mode""",
        "category": "amr"
    },
    {
        "title": "Resistor Power Derating Standard",
        "content": """Resistor power derating requirements:

Thick film chip resistors:
- 50% power derating for reliable operation
- 0402: 1/16W (62.5mW) → derated to 31mW
- 0603: 1/10W (100mW) → derated to 50mW
- 0805: 1/8W (125mW) → derated to 62.5mW
- 1206: 1/4W (250mW) → derated to 125mW

Power calculation: P = V²/R or P = I²×R

Derating above 70°C ambient:
- Linear derating from 100% at 70°C to 0% at maximum temperature
- P_actual = P_rated × (T_max - T_ambient) / (T_max - 70°C)

Common issues:
- Using 0402 resistors in high-current paths (exceeds power rating)
- Forgetting AC/ripple current in power resistors
- Voltage coefficient effect in high-value resistors (>1MΩ)""",
        "category": "amr"
    },
    {
        "title": "IC Absolute Maximum Ratings",
        "content": """IC absolute maximum rating guidelines:

Key parameters:
- Supply voltage (VCC/VDD): never exceed, even momentarily
- Input voltage: must not exceed supply rail + 0.3V (without clamp)
- Junction temperature: typical max 150°C (commercial) or 125°C
- ESD rating: HBM 2000V, CDM 500V (minimum for handling)

Operating vs Absolute Maximum:
- Abs max is NOT a design target
- Recommended operating conditions are the design limits
- Margin: operate at least 20% below abs max for voltage, 25°C below max Tj

Latch-up prevention:
- Input voltage must not exceed supply by >0.3V
- Power sequencing: apply VDD before input signals
- Use Schottky clamp diodes on inputs that can exceed supply""",
        "category": "amr"
    },
]


def main():
    from agent_system.knowledge_router import KnowledgeRouter
    from agent_system.parsers.design_guide_parser import DesignGuideChunk
    
    kr = KnowledgeRouter()
    total_imported = 0
    
    # 1. Import design rules
    for topic, rules in DESIGN_RULES.items():
        for rule in rules:
            chunks = [DesignGuideChunk(
                content=rule["content"],
                title=rule["title"],
                category=rule.get("category", topic),
            )]
            n = kr.import_design_guide(
                source_id=f"builtin_{topic}",
                chunks=chunks,
                category=rule.get("category", topic),
            )
            total_imported += n
            logger.info(f"  Imported {n} chunks for {topic}/{rule['title'][:40]}")
    
    # 2. Import AMR derating knowledge
    for rule in AMR_DERATING_KNOWLEDGE:
        chunks = [DesignGuideChunk(
            content=rule["content"],
            title=rule["title"],
            category="amr",
        )]
        n = kr.import_design_guide(
            source_id=f"builtin_amr",
            chunks=chunks,
            category="amr",
        )
        total_imported += n
        logger.info(f"  Imported {n} chunks for amr/{rule['title'][:40]}")
    
    # 3. Verify with queries
    stats = kr.get_stats()
    
    print(f"\n{'='*60}")
    print(f"知识库初始化结果")
    print(f"{'='*60}")
    print(f"导入切片数: {total_imported}")
    print(f"ChromaDB 总条目: {stats['tier1_chunks']}")
    
    # Test queries
    test_queries = [
        ("I2C pull-up resistor", "i2c"),
        ("decoupling capacitor placement", "power"),
        ("ESD protection TVS", "esd"),
        ("capacitor voltage derating", "amr"),
        ("DDR VDDQ voltage", "ddr"),
        ("PCIe differential impedance", "pcie"),
    ]
    
    print(f"\n验证查询:")
    for query, topic in test_queries:
        result = kr.search(mpn=f"builtin_{topic}", query=query)
        if result and result.status == 'success':
            print(f"  ✅ [{topic}] '{query}' → conf={result.confidence:.2f}")
        else:
            print(f"  ❌ [{topic}] '{query}' → no result")
    
    print(f"\nDone! Knowledge base initialized with {stats['tier1_chunks']} chunks.")


if __name__ == "__main__":
    main()
