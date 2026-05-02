"""
电源树生成器

基于 Neo4j 图谱，从 PMIC/LDO/BUCK 器件的电源输出引脚向下游推导 [:POWERED_BY] 关系。

规则：
1. 识别供电源器件：PartType 为 PMIC/LDO/BUCK 的器件
2. 找到供电源器件连接到的所有 POWER 网络
3. 对每个 POWER 网络，找到所有非被动器件（排除 CAPACITOR/RESISTOR/INDUCTOR/DIODE）
4. 建立 (Source)-[:POWERED_BY {voltage, net}]->(Target)
5. 同一对 Source-Target 只建立一次关系（避免多引脚重复）

扩展：
- 未来可基于网络名电压层级推断多级电源树（如 12V → 5V → 3.3V → 1.8V）
- 可加入电感-电容 LC 网络过滤（识别 Buck 拓扑中的电感后端）
"""

import os
import json
from neo4j import GraphDatabase
from dotenv import load_dotenv

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT_DIR, ".env"))


def get_driver():
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD")
    return GraphDatabase.driver(uri, auth=(user, password))


POWER_SOURCE_TYPES = {"PMIC", "LDO", "BUCK"}
PASSIVE_TYPES = {"CAPACITOR", "RESISTOR", "INDUCTOR", "DIODE"}


def generate_power_tree(driver):
    """
    生成电源树 [:POWERED_BY] 关系

    返回统计信息 dict
    """
    stats = {
        "power_sources_found": 0,
        "power_nets_found": 0,
        "powered_by_relations_created": 0,
        "powered_components": set(),
        "details": []
    }

    with driver.session() as session:
        # Step 1: 找到所有供电源器件
        source_result = session.run("""
            MATCH (c:Component)
            WHERE c.PartType IN $source_types
            RETURN c.RefDes as refdes, c.PartType as parttype, c.Model as model
            ORDER BY c.RefDes
        """, source_types=list(POWER_SOURCE_TYPES))

        sources = [(rec["refdes"], rec["parttype"], rec["model"]) for rec in source_result]
        stats["power_sources_found"] = len(sources)
        print(f"[PowerTree] 发现 {len(sources)} 个供电源器件:")
        for ref, pt, model in sources:
            print(f"  {ref} [{pt}] {model[:50]}")

        if not sources:
            print("[PowerTree] ⚠️ 未找到供电源器件（PartType=PMIC/LDO/BUCK），电源树生成中止")
            return stats

        # Step 2: 对每个供电源，找到其 POWER 引脚连接的网络
        all_relations = []  # (source_ref, target_ref, net_name, voltage)

        for refdes, parttype, model in sources:
            # 找到该器件连接到的所有 POWER 网络
            # 策略：器件的 POWER 引脚，或任何连接到 POWER/非GROUND 网络的引脚
            net_result = session.run("""
                MATCH (c:Component {RefDes: $refdes})-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
                WHERE n.NetType = 'POWER'
                  AND n.Name <> 'DGND'
                  AND NOT n.Name STARTS WITH 'GND'
                RETURN DISTINCT n.Name as net_name, n.VoltageLevel as voltage, n.NetType as net_type
            """, refdes=refdes)

            nets = [(rec["net_name"], rec["voltage"], rec["net_type"]) for rec in net_result]
            stats["power_nets_found"] += len(nets)

            for net_name, voltage, net_type in nets:
                # 跳过 GROUND 网络（不是供电，是回流）
                if net_type == "GROUND":
                    continue

                # 找到这个网络上的所有非被动器件（排除供电源自己）
                target_result = session.run("""
                    MATCH (n:Net {Name: $net_name})<-[:CONNECTS_TO]-(p:Pin)<-[:HAS_PIN]-(c:Component)
                    WHERE c.RefDes <> $source_ref
                      AND NOT c.PartType IN $passive_types
                    RETURN DISTINCT c.RefDes as target_ref, c.PartType as target_type
                """, net_name=net_name, source_ref=refdes, passive_types=list(PASSIVE_TYPES))

                targets = [(rec["target_ref"], rec["target_type"]) for rec in target_result]

                if targets:
                    relation_info = {
                        "source": refdes,
                        "net": net_name,
                        "voltage": voltage,
                        "target_count": len(targets),
                        "targets": [t[0] for t in targets]
                    }
                    stats["details"].append(relation_info)

                    for target_ref, target_type in targets:
                        all_relations.append((refdes, target_ref, net_name, voltage))
                        stats["powered_components"].add(target_ref)

        # Step 3: 去重并批量创建关系
        unique_relations = list(set(all_relations))
        stats["powered_by_relations_created"] = len(unique_relations)

        print(f"\n[PowerTree] 共发现 {len(unique_relations)} 个唯一 [:POWERED_BY] 关系")
        print(f"[PowerTree] 涉及 {len(stats['powered_components'])} 个被供电器件")

        if unique_relations:
            # 批量创建关系
            batch_size = 500
            created = 0
            for i in range(0, len(unique_relations), batch_size):
                batch = unique_relations[i:i + batch_size]
                session.run("""
                    UNWIND $relations AS rel
                    MATCH (src:Component {RefDes: rel.source})
                    MATCH (tgt:Component {RefDes: rel.target})
                    MERGE (src)-[r:POWERED_BY]->(tgt)
                    ON CREATE SET r.voltage = rel.voltage, r.net = rel.net, r.created_at = datetime()
                    ON MATCH SET r.voltage = rel.voltage, r.net = rel.net
                """, relations=[
                    {"source": s, "target": t, "net": n, "voltage": v}
                    for s, t, n, v in batch
                ])
                created += len(batch)
                print(f"  ... 已创建 {created}/{len(unique_relations)} 个关系")

            print(f"\n[PowerTree] ✅ 电源树生成完成，共创建 {created} 个 [:POWERED_BY] 关系")

            # 输出样本
            print("\n[PowerTree] 样本关系:")
            sample_result = session.run("""
                MATCH (src:Component)-[r:POWERED_BY]->(tgt:Component)
                RETURN src.RefDes as src, r.voltage as v, r.net as net, tgt.RefDes as tgt, tgt.PartType as tgt_type
                LIMIT 10
            """)
            for rec in sample_result:
                print(f"  {rec['src']} --[{rec['v'] or 'N/A'} | {rec['net']}]--> {rec['tgt']} [{rec['tgt_type']}]")
        else:
            print("[PowerTree] ⚠️ 未生成任何 [:POWERED_BY] 关系")

    return stats


def generate_power_tree_from_voltage_nets(driver):
    """
    扩展：基于电压网络的层级推断更完整的电源树

    即使没有 PMIC/LDO PartType，也可以从网络电压层级推断：
    - 高电压网络（12V, 5V）→ 低电压网络（3.3V, 1.8V）的器件关联
    - 但需要器件之间的物理连接，目前信息不足

    此函数作为未来扩展保留。
    """
    pass


def print_power_tree_summary(driver):
    """打印电源树摘要统计"""
    with driver.session() as session:
        print("\n" + "=" * 60)
        print("电源树摘要")
        print("=" * 60)

        # 供电源器件统计
        r = session.run("""
            MATCH (c:Component)-[:POWERED_BY]->()
            RETURN c.PartType as pt, count(DISTINCT c) as cnt
            ORDER BY cnt DESC
        """)
        print("\n供电源类型分布:")
        for rec in r:
            print(f"  {rec['pt']}: {rec['cnt']}")

        # 被供电器件统计
        r = session.run("""
            MATCH ()-[:POWERED_BY]->(c:Component)
            RETURN c.PartType as pt, count(DISTINCT c) as cnt
            ORDER BY cnt DESC
        """)
        print("\n被供电类型分布 (Top 10):")
        for rec in r:
            print(f"  {rec['pt']}: {rec['cnt']}")

        # 按电压等级统计
        r = session.run("""
            MATCH ()-[r:POWERED_BY]->()
            RETURN r.voltage as v, count(*) as cnt
            ORDER BY cnt DESC
            LIMIT 10
        """)
        print("\n电压等级分布 (Top 10):")
        for rec in r:
            print(f"  {rec['v'] or 'N/A'}: {rec['cnt']}")

        # 最大供电来源
        r = session.run("""
            MATCH (c:Component)-[r:POWERED_BY]->()
            RETURN c.RefDes as ref, c.Model as model, count(r) as cnt
            ORDER BY cnt DESC
            LIMIT 5
        """)
        print("\n供电最多的器件 (Top 5):")
        for rec in r:
            print(f"  {rec['ref']} [{rec['model'][:40]}]: {rec['cnt']} 个负载")


if __name__ == "__main__":
    driver = get_driver()
    try:
        stats = generate_power_tree(driver)
        if stats["powered_by_relations_created"] > 0:
            print_power_tree_summary(driver)
    finally:
        driver.close()
