"""
批量生成 AMR 数据 — 从 Neo4j 器件描述解码参数 + 生成 amr_data.yaml

用法:
    python3 generate_amr_data.py [--output amr_data.yaml] [--min-confidence 0.5]
"""

from __future__ import annotations

import sys
import os
import json
import yaml
import argparse
import logging
from collections import defaultdict

# 确保能 import 项目模块
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agent_system.mpn_decoder import MPNDecoder, AMRDataGenerator

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def fetch_components_from_neo4j():
    """从 Neo4j 拉取所有被动器件"""
    from neo4j import GraphDatabase
    
    NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
    NEO4J_PASS = os.environ.get("NEO4J_PASS", "SecretPassword123")
    
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    components = []
    
    with driver.session() as session:
        # 获取所有被动器件
        result = session.run("""
            MATCH (c:Component)
            WHERE c.PartType IN ['CAPACITOR', 'RESISTOR', 'INDUCTOR', 'DIODE', 'MOSFET']
            RETURN c.RefDes as refdes, c.Model as model, c.PartType as parttype, c.Value as value
            ORDER BY c.PartType, c.Model
        """)
        for record in result:
            components.append({
                "refdes": record["refdes"],
                "model": record["model"] or "",
                "part_type": record["parttype"],
                "value": record["value"] or "",
            })
    
    driver.close()
    logger.info(f"Fetched {len(components)} passive components from Neo4j")
    return components


def generate_amr_data(components, min_confidence=0.5):
    """批量解码并生成 AMR 数据"""
    decoder = MPNDecoder()
    generator = AMRDataGenerator()
    
    stats = defaultdict(int)
    amr_entries = []
    decode_results = []
    
    # 去重：相同 Model 只解码一次
    seen_models = {}
    for comp in components:
        model = comp["model"]
        if model not in seen_models:
            seen_models[model] = comp
    
    logger.info(f"Unique models to decode: {len(seen_models)}")
    
    for model, comp in seen_models.items():
        pt = comp["part_type"]
        
        # 优先用 Neo4j 描述解码
        decoded = decoder.decode_neo4j_description(model, pt)
        
        # 如果描述解码失败，尝试标准 MPN 解码
        if decoded.confidence < 0.5:
            decoded2 = decoder.decode(model)
            if decoded2.confidence > decoded.confidence:
                decoded = decoded2
        
        # 生成 AMR 条目
        amr = generator.generate_amr_entry(decoded)
        
        decode_results.append({
            "model": model,
            "part_type": pt,
            "decoded": decoded.to_dict(),
            "amr": amr,
        })
        
        if decoded.capacitance:
            stats["cap_decoded"] += 1
        if decoded.resistance:
            stats["res_decoded"] += 1
        if decoded.voltage_rating:
            stats["voltage_decoded"] += 1
        if decoded.package:
            stats["package_decoded"] += 1
        if amr:
            stats["amr_generated"] += 1
            if amr["confidence"] >= min_confidence:
                amr_entries.append(amr)
        
        stats["total"] += 1
    
    logger.info(f"Decode stats: {dict(stats)}")
    logger.info(f"AMR entries (confidence >= {min_confidence}): {len(amr_entries)}")
    
    return amr_entries, decode_results, dict(stats)


def main():
    parser = argparse.ArgumentParser(description="Generate AMR data from Neo4j components")
    parser.add_argument("--output", default="amr_data.yaml", help="Output YAML file")
    parser.add_argument("--min-confidence", type=float, default=0.5, help="Minimum confidence threshold")
    parser.add_argument("--json-report", default="amr_decode_report.json", help="Detailed decode report")
    args = parser.parse_args()
    
    # 1. 从 Neo4j 拉取器件
    components = fetch_components_from_neo4j()
    
    # 2. 批量解码
    amr_entries, decode_results, stats = generate_amr_data(components, args.min_confidence)
    
    # 3. 按 category 分组写入 YAML
    amr_yaml = {
        "metadata": {
            "source": "mpn_decoder_batch",
            "total_unique_models": stats.get("total", 0),
            "amr_entries": len(amr_entries),
            "min_confidence": args.min_confidence,
        },
        "capacitors": [e for e in amr_entries if e["category"] == "capacitor"],
        "resistors": [e for e in amr_entries if e["category"] == "resistor"],
    }
    
    output_path = os.path.join(ROOT, args.output)
    with open(output_path, "w") as f:
        yaml.dump(amr_yaml, f, default_flow_style=False, allow_unicode=True)
    logger.info(f"AMR data written to {output_path}")
    
    # 4. 详细报告
    report_path = os.path.join(ROOT, args.json_report)
    with open(report_path, "w") as f:
        json.dump(decode_results, f, indent=2, ensure_ascii=False)
    logger.info(f"Decode report written to {report_path}")
    
    # 5. 打印摘要
    print("\n" + "=" * 60)
    print("AMR 数据生成摘要")
    print("=" * 60)
    print(f"Neo4j 被动器件总数: {len(components)}")
    print(f"唯一 Model 数: {stats.get('total', 0)}")
    print(f"容值解码成功: {stats.get('cap_decoded', 0)}")
    print(f"阻值解码成功: {stats.get('res_decoded', 0)}")
    print(f"电压解码成功: {stats.get('voltage_decoded', 0)}")
    print(f"封装解码成功: {stats.get('package_decoded', 0)}")
    print(f"AMR 条目生成: {len(amr_entries)} (confidence >= {args.min_confidence})")
    print(f"  - 电容: {len(amr_yaml['capacitors'])}")
    print(f"  - 电阻: {len(amr_yaml['resistors'])}")


if __name__ == "__main__":
    main()
