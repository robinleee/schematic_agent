"""
真实 Cadence 网表 ETL — 批量注入 Neo4j

使用 netlist_parser/netlist/ 下的真实 pstxnet/prt/chip 文件
"""

import os
import sys
import json
import time
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT_DIR, ".env"))

from neo4j import GraphDatabase
from etl_pipeline.net_parser import CadenceNetlistParser
from etl_pipeline.prt_parser import CadencePrtParser
from etl_pipeline.chip_parser import CadenceChipParser

NETLIST_DIR = "/data/schematic_agent/netlist_parser/netlist"
BATCH_SIZE = 1000


def read_files():
    """读取三大文件"""
    print("📂 读取网表文件...")
    with open(os.path.join(NETLIST_DIR, "pstxnet.dat"), "r", encoding="latin-1") as f:
        pstxnet = f.read()
    with open(os.path.join(NETLIST_DIR, "pstxprt.dat"), "r", encoding="latin-1") as f:
        pstxprt = f.read()
    with open(os.path.join(NETLIST_DIR, "pstchip.dat"), "r", encoding="latin-1") as f:
        pstchip = f.read()
    print(f"  pstxnet: {len(pstxnet):,} chars")
    print(f"  pstxprt: {len(pstxprt):,} chars")
    print(f"  pstchip: {len(pstchip):,} chars")
    return pstxnet, pstxprt, pstchip


def parse_all(pstxnet, pstxprt, pstchip):
    """解析三大文件"""
    print("\n🔍 解析网表...")
    net_parser = CadenceNetlistParser()
    prt_parser = CadencePrtParser()
    chip_parser = CadenceChipParser()

    t0 = time.time()
    net_topology = net_parser.parse_pstxnet(pstxnet)
    ref_to_prim = prt_parser.parse_pstxprt(pstxprt)
    chip_library = chip_parser.parse_pstchip(pstchip)
    t1 = time.time()

    print(f"  Topology triplets: {len(net_topology):,}")
    print(f"  RefDes -> Primitive: {len(ref_to_prim):,}")
    print(f"  Chip library: {len(chip_library):,}")
    print(f"  Parse time: {t1-t0:.1f}s")
    return net_topology, ref_to_prim, chip_library


def fuse_components(net_topology, ref_to_prim, chip_library):
    """融合器件数据"""
    print("\n🔧 融合器件属性...")
    graph_components = {}

    for triplet in net_topology:
        refdes = triplet["Component_RefDes"]
        if refdes not in graph_components:
            primitive_name = ref_to_prim.get(refdes)
            props = chip_library.get(primitive_name, {}).get("Properties", {})
            graph_components[refdes] = {
                "RefDes": refdes,
                "Model": primitive_name,
                "Value": props.get("VALUE", "N/A"),
                "PartType": props.get("PART_NAME", "N/A"),
                "MPN": props.get("PART_NUMBER", None),
                "Package": props.get("JEDEC_TYPE", None),
            }

    print(f"  Fused components: {len(graph_components):,}")

    # 按类型统计
    type_counts = {}
    for comp in graph_components.values():
        pt = comp["PartType"] or "UNKNOWN"
        type_counts[pt] = type_counts.get(pt, 0) + 1
    print("  器件类型分布:")
    for pt, cnt in sorted(type_counts.items(), key=lambda x: -x[1])[:10]:
        print(f"    {pt}: {cnt:,}")
    if len(type_counts) > 10:
        print(f"    ... and {len(type_counts)-10} more types")

    return graph_components


def clear_and_init_neo4j(driver):
    """清空 Neo4j 并初始化约束"""
    print("\n🗑️  清空 Neo4j 并初始化...")
    with driver.session() as session:
        # 清空（保留约束）
        result = session.run("MATCH (n) RETURN count(n) as cnt")
        before = result.single()["cnt"]
        print(f"  清空前节点数: {before:,}")

        session.run("MATCH (n) DETACH DELETE n")

        result = session.run("MATCH (n) RETURN count(n) as cnt")
        after = result.single()["cnt"]
        print(f"  清空后节点数: {after:,}")

        # 确保约束存在
        constraints = [
            "CREATE CONSTRAINT component_refdes IF NOT EXISTS FOR (c:Component) REQUIRE c.RefDes IS UNIQUE",
            "CREATE CONSTRAINT pin_id IF NOT EXISTS FOR (p:Pin) REQUIRE p.Id IS UNIQUE",
            "CREATE CONSTRAINT net_name IF NOT EXISTS FOR (n:Net) REQUIRE n.Name IS UNIQUE",
        ]
        for c in constraints:
            try:
                session.run(c)
            except Exception:
                pass
    print("  ✅ Neo4j 已清空")


def batch_insert_components(driver, components):
    """批量插入 Component 节点"""
    print(f"\n📦 插入 Component 节点 ({len(components):,})...")
    comps_list = list(components.values())

    total = 0
    t0 = time.time()
    with driver.session() as session:
        for i in range(0, len(comps_list), BATCH_SIZE):
            batch = comps_list[i:i+BATCH_SIZE]
            session.run("""
                UNWIND $comps AS comp
                MERGE (c:Component {RefDes: comp.RefDes})
                SET c.Model = comp.Model,
                    c.Value = comp.Value,
                    c.PartType = comp.PartType,
                    c.MPN = comp.MPN,
                    c.Package = comp.Package
            """, comps=batch)
            total += len(batch)
            if (i // BATCH_SIZE + 1) % 10 == 0:
                print(f"  ... {total:,} / {len(comps_list):,}")
    t1 = time.time()
    print(f"  ✅ {total:,} Component 节点 ({t1-t0:.1f}s)")


def batch_insert_topology(driver, topology):
    """批量插入 Pin + Net 拓扑关系"""
    print(f"\n🔗 插入拓扑关系 ({len(topology):,} triplets)...")

    total = 0
    t0 = time.time()
    with driver.session() as session:
        for i in range(0, len(topology), BATCH_SIZE):
            batch = topology[i:i+BATCH_SIZE]
            session.run("""
                UNWIND $triplets AS t
                MATCH (c:Component {RefDes: t.Component_RefDes})
                MERGE (p:Pin {Id: t.Component_RefDes + '_' + t.Pin_Number})
                SET p.Number = t.Pin_Number
                MERGE (c)-[:HAS_PIN]->(p)
                MERGE (n:Net {Name: t.Net_Name})
                MERGE (p)-[:CONNECTS_TO]->(n)
            """, triplets=batch)
            total += len(batch)
            if (i // BATCH_SIZE + 1) % 10 == 0:
                print(f"  ... {total:,} / {len(topology):,}")
    t1 = time.time()
    print(f"  ✅ {total:,} 拓扑关系 ({t1-t0:.1f}s)")


def verify_graph(driver):
    """验证图谱统计"""
    print("\n🔍 图谱验证...")
    with driver.session() as session:
        stats = {}
        for label in ["Component", "Pin", "Net"]:
            result = session.run(f"MATCH (n:{label}) RETURN count(n) as cnt")
            stats[label] = result.single()["cnt"]

        result = session.run("MATCH ()-[r:HAS_PIN]->() RETURN count(r) as cnt")
        stats["HAS_PIN"] = result.single()["cnt"]

        result = session.run("MATCH ()-[r:CONNECTS_TO]->() RETURN count(r) as cnt")
        stats["CONNECTS_TO"] = result.single()["cnt"]

        total = sum(stats.values())

        print(f"  节点统计:")
        print(f"    Component: {stats['Component']:,}")
        print(f"    Pin: {stats['Pin']:,}")
        print(f"    Net: {stats['Net']:,}")
        print(f"  关系统计:")
        print(f"    HAS_PIN: {stats['HAS_PIN']:,}")
        print(f"    CONNECTS_TO: {stats['CONNECTS_TO']:,}")
        print(f"  总计: {stats['Component'] + stats['Pin'] + stats['Net']:,} 节点, {stats['HAS_PIN'] + stats['CONNECTS_TO']:,} 关系")

        # 抽样验证
        print("\n  抽样验证:")
        result = session.run("""
            MATCH (c:Component)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
            RETURN c.RefDes AS refdes, p.Number AS pin, n.Name AS net
            LIMIT 5
        """)
        for r in result:
            print(f"    {r['refdes']} Pin {r['pin']} -> Net '{r['net']}'")

    return stats


def save_outputs(graph_components, net_topology):
    """保存输出文件"""
    output_dir = os.path.join(ROOT_DIR, "data", "output")
    os.makedirs(output_dir, exist_ok=True)

    comp_file = os.path.join(output_dir, "graph_components.json")
    topo_file = os.path.join(output_dir, "topology_triplets.json")

    with open(comp_file, "w", encoding="utf-8") as f:
        json.dump(graph_components, f, ensure_ascii=False, indent=2)
    print(f"\n💾 Saved: {comp_file} ({len(graph_components):,} components)")

    with open(topo_file, "w", encoding="utf-8") as f:
        json.dump(net_topology, f, ensure_ascii=False, indent=2)
    print(f"💾 Saved: {topo_file} ({len(net_topology):,} triplets)")


def main():
    print("=" * 60)
    print("  Real Cadence Netlist ETL")
    print("=" * 60)
    print(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Source: {NETLIST_DIR}")

    # 1. 读取
    pstxnet, pstxprt, pstchip = read_files()

    # 2. 解析
    net_topology, ref_to_prim, chip_library = parse_all(pstxnet, pstxprt, pstchip)

    # 3. 融合
    graph_components = fuse_components(net_topology, ref_to_prim, chip_library)

    # 4. 连接 Neo4j
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD")

    print(f"\n🌐 连接 Neo4j: {uri}")
    driver = GraphDatabase.driver(uri, auth=(user, password))

    try:
        # 5. 清空 + 初始化
        clear_and_init_neo4j(driver)

        # 6. 批量插入
        batch_insert_components(driver, graph_components)
        batch_insert_topology(driver, net_topology)

        # 7. 验证
        stats = verify_graph(driver)

        # 8. 保存输出
        save_outputs(graph_components, net_topology)

        print("\n" + "=" * 60)
        print("✅ Real ETL completed successfully!")
        print("=" * 60)

    finally:
        driver.close()


if __name__ == "__main__":
    main()
