"""
AMR 数据合并器 — 将 MPN 解码器生成的数据转换为 FileBasedAMRSource 兼容格式

同时合并 TI Datasheet 提取的 AMR 数据

用法:
    python3 merge_amr_data.py
"""

from __future__ import annotations

import os
import sys
import yaml
import logging
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def load_mpn_amr_data():
    """加载 MPN 解码器生成的 amr_data.yaml"""
    path = os.path.join(ROOT, "amr_data.yaml")
    if not os.path.exists(path):
        logger.warning(f"MPN AMR data not found: {path}")
        return []
    
    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    
    caps = data.get("capacitors", [])
    res = data.get("resistors", [])
    logger.info(f"Loaded MPN AMR data: {len(caps)} capacitors, {len(res)} resistors")
    return caps + res


def load_ti_amr_data():
    """加载 TI Datasheet 提取的 AMR 数据"""
    path = os.path.join(ROOT, "agent_system", "ti_amr_data.yaml")
    if not os.path.exists(path):
        logger.warning(f"TI AMR data not found: {path}")
        return []
    
    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    
    components = data.get("components", [])
    logger.info(f"Loaded TI AMR data: {len(components)} components")
    return components


def convert_to_file_based_format(mpn_entries, ti_entries):
    """转换为 FileBasedAMRSource 兼容格式
    
    FileBasedAMRSource 期望:
    components:
      MPN_PATTERN:
        parameters:
          cap_voltage_rating: {value: 16.0}
          res_power_rating: {value: 0.0625}
          voltage_min: {value: 2.0}
          voltage_max: {value: 16.0}
    """
    result = {}
    
    # 处理 MPN 解码器数据
    for entry in mpn_entries:
        mpn = entry.get("mpn_pattern", "")
        category = entry.get("category", "")
        confidence = entry.get("confidence", 0.0)
        params = {}
        
        if category == "capacitor":
            v_rating = entry.get("voltage_rating_V")
            if v_rating is not None:
                params["cap_voltage_rating"] = {"value": float(v_rating)}
            cap = entry.get("capacitance")
            if cap:
                params["capacitance"] = {"value": cap}
            cap_pf = entry.get("capacitance_pf")
            if cap_pf is not None:
                params["capacitance_pf"] = {"value": float(cap_pf)}
            pkg = entry.get("package")
            if pkg:
                params["package"] = {"value": pkg}
            temp = entry.get("temp_characteristic")
            if temp:
                params["temp_characteristic"] = {"value": temp}
        
        elif category == "resistor":
            power = entry.get("power_rating_W")
            if power is not None:
                params["res_power_rating"] = {"value": float(power)}
            resistance = entry.get("resistance_ohm")
            if resistance is not None:
                params["resistance_ohm"] = {"value": float(resistance)}
            pkg = entry.get("package")
            if pkg:
                params["package"] = {"value": pkg}
        
        if params:
            params["_source"] = {"value": entry.get("source", "mpn_decoder")}
            params["_voltage_source"] = {"value": entry.get("voltage_source", "decoded")}
            params["_confidence"] = {"value": confidence}
            result[mpn] = {"parameters": params}
    
    # 处理 TI Datasheet 数据
    for comp in ti_entries:
        mpn = comp.get("mpn", "")
        amr = comp.get("absolute_maximum_ratings", {})
        rec = comp.get("recommended_operating_conditions", {})
        
        params = {}
        
        # 从 AMR 提取电压范围
        vin_range = amr.get("Supply voltage at VIN") or amr.get("Voltage range VIN, PS/SYNC, EN, VSEL")
        if vin_range:
            params["voltage_min"] = {"value": float(vin_range.get("min", 0))}
            params["voltage_max"] = {"value": float(vin_range.get("max", 0))}
        
        # 从推荐工作条件提取
        for key, val in rec.items():
            if "supply voltage" in key.lower() or "vin" in key.lower():
                params["v_supply_min"] = {"value": float(val.get("min", 0))}
                params["v_supply_max"] = {"value": float(val.get("max", 0))}
                break
        
        # 从 AMR 提取温度范围
        for key, val in amr.items():
            if "temperature" in key.lower() and "junction" in key.lower():
                params["t_junction_min"] = {"value": float(val.get("min", 0))}
                params["t_junction_max"] = {"value": float(val.get("max", 0))}
                break
        
        if params:
            params["_source"] = {"value": "ti_datasheet"}
            params["_confidence"] = {"value": comp.get("confidence", 0.8)}
            params["_amr_raw"] = {"value": amr}
            if mpn in result:
                # 合并：TI 数据优先级更高
                existing = result[mpn].get("parameters", {})
                existing.update(params)
                result[mpn]["parameters"] = existing
            else:
                result[mpn] = {"parameters": params}
    
    return result


def main():
    mpn_entries = load_mpn_amr_data()
    ti_entries = load_ti_amr_data()
    
    merged = convert_to_file_based_format(mpn_entries, ti_entries)
    
    # 统计
    cap_count = sum(1 for v in merged.values() if "cap_voltage_rating" in v.get("parameters", {}))
    res_count = sum(1 for v in merged.values() if "res_power_rating" in v.get("parameters", {}))
    ic_count = sum(1 for v in merged.values() if "voltage_min" in v.get("parameters", {}))
    
    output = {
        "metadata": {
            "description": "AMR data for schematic_agent - generated from MPN decoder + TI datasheets",
            "total_components": len(merged),
            "capacitors_with_voltage": cap_count,
            "resistors_with_power": res_count,
            "ics_with_voltage_range": ic_count,
        },
        "components": merged,
    }
    
    # 写入 FileBasedAMRSource 期望的路径
    output_dir = os.path.join(ROOT, "agent_system", "review_engine", "config")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "amr_data.yaml")
    
    with open(output_path, 'w', encoding='utf-8') as f:
        yaml.dump(output, f, default_flow_style=False, allow_unicode=True)
    
    logger.info(f"Merged AMR data written to {output_path}")
    
    print(f"\n{'='*60}")
    print(f"AMR 数据合并结果")
    print(f"{'='*60}")
    print(f"MPN 解码器条目: {len(mpn_entries)}")
    print(f"TI Datasheet 条目: {len(ti_entries)}")
    print(f"合并后唯一器件: {len(merged)}")
    print(f"  电容（有耐压）: {cap_count}")
    print(f"  电阻（有功率）: {res_count}")
    print(f"  IC（有电压范围）: {ic_count}")
    print(f"\n输出: {output_path}")


if __name__ == "__main__":
    main()
