#!/usr/bin/env python3
"""P0 修复脚本 — 批量建 DESCRIBES 关系 + 写入 voltage_rating

P0-2: VectorChunk → Component [:DESCRIBES] 桥接
P0-3: MPN Decoder 结果批量写入 Neo4j Component.voltage_rating
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

from neo4j import GraphDatabase

NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "SecretPassword123"


# 封装到默认耐压的映射（常见贴片电容）
_PACKAGE_VOLTAGE = {
    "01005": 6.3,
    "0201": 10.0,
    "0402": 16.0,
    "0603": 25.0,
    "0805": 50.0,
    "1206": 50.0,
    "1210": 50.0,
    "1812": 50.0,
}


def _infer_capacitor_props(model: str, value: str) -> dict:
    """从 Model/Value 字段推断电容参数（当 MPN Decoder 失败时）"""
    import re
    props = {}

    # 从 Model 提取封装: CAP_C0402_..., CAP_C0603_...
    pkg_match = re.search(r'C(\d{4})', model.upper())
    if pkg_match:
        pkg_code = pkg_match.group(1)
        # 映射封装代码
        pkg_map = {"0402": "0402", "0603": "0603", "0805": "0805", "1206": "1206",
                   "1210": "1210", "0201": "0201", "01005": "01005"}
        package = pkg_map.get(pkg_code, "")
        if package:
            props["package"] = package
            voltage = _PACKAGE_VOLTAGE.get(package)
            if voltage:
                props["voltage_rating"] = voltage

    # 从 Model 提取电容值: _0.1UF_, _10NF_, _1UF_
    cap_match = re.search(r'_(\d+\.?\d*)(UF|NF|PF)_', model.upper())
    if cap_match:
        val_str = cap_match.group(1)
        unit = cap_match.group(2)
        try:
            val = float(val_str)
            if unit == "UF":
                props["capacitance"] = val * 1e6  # pF
            elif unit == "NF":
                props["capacitance"] = val * 1e3
            elif unit == "PF":
                props["capacitance"] = val
        except ValueError:
            pass

    # 只有同时获得 voltage_rating 才返回
    if "voltage_rating" in props:
        return props
    return {}


def fix_describes_relationships(driver):
    """P0-2: 为 VectorChunk 建立 DESCRIBES 关系到 Component"""
    print("\n" + "=" * 60)
    print("P0-2: 建立 VectorChunk → Component [:DESCRIBES] 关系")
    print("=" * 60)

    # Step 1: 统计 VectorChunk
    with driver.session() as session:
        vc_count = session.run("MATCH (vc:VectorChunk) RETURN count(vc) AS cnt").single()["cnt"]
        print(f"  VectorChunk 总数: {vc_count}")

    # Step 2: 基于 source 字段匹配 Component（case-insensitive）
    # VectorChunk.source = "tps7a47.pdf" → 匹配 Component.Model containing "TPS7A47"
    cypher_exact = """
    MATCH (vc:VectorChunk)
    WHERE vc.source IS NOT NULL AND vc.source <> 'test.pdf'
    WITH vc, split(vc.source, '.')[0] AS mpn_lower
    MATCH (c:Component)
    WHERE toLower(c.Model) CONTAINS mpn_lower
    MERGE (vc)-[r:DESCRIBES]->(c)
    SET r.rel_type = 'datasheet_spec',
        r.confidence = 0.9,
        r.created_at = datetime()
    RETURN count(r) AS created
    """

    with driver.session() as session:
        result = session.run(cypher_exact)
        created = result.single()["created"]
        print(f"  Case-insensitive DESCRIBES: {created} 条")

    # Step 3: 反向匹配 — Component.Model 前缀匹配 source
    cypher_reverse = """
    MATCH (vc:VectorChunk)
    WHERE vc.source IS NOT NULL AND vc.source <> 'test.pdf'
    WITH vc, split(vc.source, '.')[0] AS mpn_lower
    MATCH (c:Component)
    WHERE mpn_lower CONTAINS toLower(c.Model)
    AND NOT (vc)-[:DESCRIBES]->(c)
    MERGE (vc)-[r:DESCRIBES]->(c)
    SET r.rel_type = 'datasheet_spec',
        r.confidence = 0.7,
        r.created_at = datetime()
    RETURN count(r) AS created
    """

    with driver.session() as session:
        result = session.run(cypher_reverse)
        created = result.single()["created"]
        print(f"  反向匹配 DESCRIBES: +{created} 条")

    # Step 4: 通过 KnowledgeSource 中转
    # KnowledgeSource.mpn → VectorChunk.source → Component
    cypher_via_ks = """
    MATCH (ks:KnowledgeSource)-[:HAS_KNOWLEDGE]->(c:Component)
    WHERE ks.mpn IS NOT NULL
    WITH DISTINCT c, ks.mpn AS mpn
    MATCH (vc:VectorChunk)
    WHERE toLower(vc.source) STARTS WITH toLower(mpn)
    AND NOT (vc)-[:DESCRIBES]->(c)
    MERGE (vc)-[r:DESCRIBES]->(c)
    SET r.rel_type = 'knowledge_link',
        r.confidence = 0.85,
        r.created_at = datetime()
    RETURN count(r) AS created
    """

    with driver.session() as session:
        result = session.run(cypher_via_ks)
        created = result.single()["created"]
        print(f"  KnowledgeSource 中转 DESCRIBES: +{created} 条")

    # Step 4: 统计
    with driver.session() as session:
        total = session.run("MATCH ()-[r:DESCRIBES]->() RETURN count(r) AS cnt").single()["cnt"]
        components = session.run(
            "MATCH (c:Component)<-[:DESCRIBES]-() RETURN count(DISTINCT c) AS cnt"
        ).single()["cnt"]
        print(f"  ✅ DESCRIBES 总计: {total} 条, 覆盖 {components} 个 Component")


def fix_voltage_rating(driver):
    """P0-3: MPN Decoder 结果批量写入 Neo4j Component.voltage_rating"""
    print("\n" + "=" * 60)
    print("P0-3: 写入 MPN Decoder 结果到 Neo4j")
    print("=" * 60)

    from agent_system.mpn_decoder import MPNDecoder
    decoder = MPNDecoder()

    # Step 1: 获取所有器件
    with driver.session() as session:
        # 电容 + 电阻
        result = session.run("""
            MATCH (c:Component)
            WHERE c.PartType IN ['CAPACITOR', 'RESISTOR'] AND c.Model IS NOT NULL
            RETURN c.RefDes AS refdes, c.Model AS model, c.PartType AS part_type, c.Value AS value
        """)
        components = [dict(r) for r in result]

    print(f"  待处理器件: {len(components)}")

    # Step 2: 解码并写入
    updated = 0
    skipped = 0
    cap_voltage = 0
    res_power = 0
    from_value = 0

    for comp in components:
        model = comp["model"]
        refdes = comp["refdes"]
        part_type = comp["part_type"]
        value = comp.get("value")

        props = {}

        # 尝试 1: MPN Decoder
        decoded = decoder.decode(model)
        if decoded and decoded.confidence > 0.5:
            if part_type == "CAPACITOR" and decoded.voltage_rating_v is not None:
                props["voltage_rating"] = decoded.voltage_rating_v
                props["capacitance"] = decoded.capacitance_pf
                props["package"] = decoded.package
                props["tolerance"] = decoded.tolerance
                props["temp_characteristic"] = decoded.temp_characteristic
                cap_voltage += 1
            elif part_type == "RESISTOR" and decoded.power_rating_w is not None:
                props["power_rating"] = decoded.power_rating_w
                props["resistance"] = decoded.resistance_ohm
                props["package"] = decoded.package
                props["tolerance"] = decoded.tolerance
                res_power += 1

        # 尝试 2: 从 Model/Value 字段推断（MPN Decoder 失败时）
        if not props and part_type == "CAPACITOR":
            props = _infer_capacitor_props(model, value)
            if props:
                from_value += 1

        if not props:
            skipped += 1
            continue

        # 写入 Neo4j
        set_clause = ", ".join([f"c.{k} = ${k}" for k in props.keys()])
        props["_refdes"] = refdes
        cypher = f"MATCH (c:Component {{RefDes: $_refdes}}) SET {set_clause}"

        try:
            with driver.session() as session:
                session.run(cypher, props)
            updated += 1
        except Exception as e:
            logger.debug(f"写入失败 {refdes}: {e}")

    print(f"  ✅ 已写入: {updated} 个器件")
    print(f"    电容(含 voltage_rating): {cap_voltage}")
    print(f"    电阻(含 power_rating): {res_power}")
    print(f"    从 Model/Value 推断: {from_value}")
    print(f"    跳过(无法解码): {skipped}")

    # Step 3: 验证
    with driver.session() as session:
        vr_count = session.run(
            "MATCH (c:Component) WHERE c.voltage_rating IS NOT NULL RETURN count(c) AS cnt"
        ).single()["cnt"]
        pr_count = session.run(
            "MATCH (c:Component) WHERE c.power_rating IS NOT NULL RETURN count(c) AS cnt"
        ).single()["cnt"]
        print(f"  验证: voltage_rating={vr_count}, power_rating={pr_count}")


if __name__ == "__main__":
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    try:
        fix_describes_relationships(driver)
        fix_voltage_rating(driver)

        # 最终统计
        print("\n" + "=" * 60)
        print("最终状态")
        print("=" * 60)
        with driver.session() as session:
            describes = session.run("MATCH ()-[r:DESCRIBES]->() RETURN count(r) AS cnt").single()["cnt"]
            vr = session.run("MATCH (c:Component) WHERE c.voltage_rating IS NOT NULL RETURN count(c) AS cnt").single()["cnt"]
            pr = session.run("MATCH (c:Component) WHERE c.power_rating IS NOT NULL RETURN count(c) AS cnt").single()["cnt"]
            power_vl = session.run("MATCH (n:Net {NetType:'POWER'}) WHERE n.VoltageLevel IS NOT NULL RETURN count(n) AS cnt").single()["cnt"]
            power_total = session.run("MATCH (n:Net {NetType:'POWER'}) RETURN count(n) AS cnt").single()["cnt"]

            print(f"  DESCRIBES: {describes} 条")
            print(f"  voltage_rating: {vr} 个 Component")
            print(f"  power_rating: {pr} 个 Component")
            print(f"  POWER 电压覆盖: {power_vl}/{power_total} ({100*power_vl/power_total:.1f}%)")

    finally:
        driver.close()
