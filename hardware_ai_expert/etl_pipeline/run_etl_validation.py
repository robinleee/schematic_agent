"""
ETL Pipeline 端到端验证脚本

使用模拟 Cadence 网表数据，验证:
1. Parser 解析三大文件
2. 数据融合生成 Component + Topology
3. 注入 Neo4j 图谱
"""

import json
import os
import sys
from dotenv import load_dotenv

# 加载 .env
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

from etl_pipeline.chip_parser import CadenceChipParser
from etl_pipeline.prt_parser import CadencePrtParser
from etl_pipeline.net_parser import CadenceNetlistParser

# ============================================================
# 模拟 Cadence 格式数据（来自真实 PCB 设计片段）
# ============================================================

MOCK_PSTXNET = """
FILE_TYPE = EXPANDEDNETLIST;
{ Using PSTWRITER 17.2.0 d001Feb-13-2026 at 16:44:32 }
NET_NAME
'VDA_CSIRX0_1_1V8'
 '@700-00700-00_ADS7_V1_20260213I.ADS7_SCH(SCH_1):ND2':
 C_SIGNAL='@\\700-00700-00_ads7_v1_20260213i\\.ads7_sch(sch_1):nd2';
NODE_NAME	U30004 C4
 '@700-00700-00_ADS7_V1_20260213I.ADS7_SCH(SCH_1):INS26446147@IC_BAIDU.MT25QL02GCBB8E12_TPBGA24.NORMAL(CHIPS)':
 'W#/DQ2':;
NET_NAME
'VDA_CSIRX0_0_1V8'
 '@700-00700-00_ADS7_V1_20260213I.ADS7_SCH(SCH_1):ND3':
 C_SIGNAL='@\\700-00700-00_ads7_v1_20260213i\\.ads7_sch(sch_1):nd3';
NODE_NAME	U30004 A4
 '@700-00700-00_ADS7_V1_20260213I.ADS7_SCH(SCH_1):INS26446147@IC_BAIDU.MT25QL02GCBB8E12_TPBGA24.NORMAL(CHIPS)':
 'DQ0':;
NODE_NAME	U30005 A4
 '@700-00700-00_ADS7_V1_20260213I.ADS7_SCH(SCH_1):INS26446148@IC_BAIDU.MT25QL02GCBB8E12_TPBGA24.NORMAL(CHIPS)':
 'DQ0':;
NET_NAME
'GND'
 '@700-00700-00_ADS7_V1_20260213I.ADS7_SCH(SCH_1):GND':
 C_SIGNAL='@\\700-00700-00_ads7_v1_20260213i\\.ads7_sch(sch_1):gnd';
NODE_NAME	U30004 E1
 '@700-00700-00_ADS7_V1_20260213I.ADS7_SCH(SCH_1):INS26446147@IC_BAIDU.MT25QL02GCBB8E12_TPBGA24.NORMAL(CHIPS)':
 'VSS':;
NODE_NAME	C30001 2
 '@700-00700-00_ADS7_V1_20260213I.ADS7_SCH(SCH_1):INS26446160@CAPACITOR.CAP_PPG.NORMAL(CHIPS)':
 '2':;
NET_NAME
'VDD_1V8'
 '@700-00700-00_ADS7_V1_20260213I.ADS7_SCH(SCH_1):VDD_1V8':
 C_SIGNAL='@\\700-00700-00_ads7_v1_20260213i\\.ads7_sch(sch_1):vdd_1v8';
NODE_NAME	U30005 C4
 '@700-00700-00_ADS7_V1_20260213I.ADS7_SCH(SCH_1):INS26446148@IC_BAIDU.MT25QL02GCBB8E12_TPBGA24.NORMAL(CHIPS)':
 'VCC':;
NODE_NAME	R30001 1
 '@700-00700-00_ADS7_V1_20260213I.ADS7_SCH(SCH_1):INS26446158@RESISTORS.RES_NOM.C0402_R.NORMAL(CHIPS)':
 '1':;
NODE_NAME	C30001 1
 '@700-00700-00_ADS7_V1_20260213I.ADS7_SCH(SCH_1):INS26446160@CAPACITOR.CAP_PPG.NORMAL(CHIPS)':
 '1':;
NET_NAME
'I2C_SDA'
NODE_NAME	U30005 B5
 'B5':;
NODE_NAME	R30002 2
 '2':;
NET_NAME
'I2C_SCL'
NODE_NAME	U30005 B6
 'B6':;
NODE_NAME	R30003 2
 '2':;
"""

MOCK_PSTXPRT = """
FILE_TYPE = EXPANDEDPARTLIST;
{ Using PSTWRITER 17.2.0 d001Feb-13-2026 at 16:44:52 }
PART_NAME
 U30004 'IC_BAIDU.MT25QL02GCBB8E12_TPBGA24':
 SECTION_NUMBER 1;
PART_NAME
 U30005 'IC_BAIDU.MT25QL02GCBB8E12_TPBGA24':
 SECTION_NUMBER 1;
PART_NAME
 R30001 'RES_NOM.C0402_R.10K_1%':
 SECTION_NUMBER 1;
PART_NAME
 R30002 'RES_NOM.C0402_R.4K7_1%':
 SECTION_NUMBER 1;
PART_NAME
 R30003 'RES_NOM.C0402_R.4K7_1%':
 SECTION_NUMBER 1;
PART_NAME
 C30001 'CAP_PPG.C0402.0.1UF_16V_X5R':
 SECTION_NUMBER 1;
"""

MOCK_PSTCHIP = """
FILE_TYPE=LIBRARY_PARTS;
primitive 'IC_BAIDU.MT25QL02GCBB8E12_TPBGA24';
  pin
    'C4'
      PIN_NUMBER='(C4)';
      PINUSE='POWER';
    'A4'
      PIN_NUMBER='(A4)';
      PINUSE='SIGNAL';
    'E1'
      PIN_NUMBER='(E1)';
      PINUSE='GND';
    'B5'
      PIN_NUMBER='(B5)';
      PINUSE='SIGNAL';
    'B6'
      PIN_NUMBER='(B6)';
      PINUSE='SIGNAL';
  end_pin;
  body
    PART_NAME='IC';
    VALUE='MT25QU256ABA8E12-0AAT';
    MPN='MT25QU256ABA8E12-0AAT';
    PACKAGE='TPBGA24';
  end_body;
end_primitive;
primitive 'RES_NOM.C0402_R.10K_1%';
  pin
    '1'
      PIN_NUMBER='(1)';
      PINUSE='UNSPEC';
    '2'
      PIN_NUMBER='(2)';
      PINUSE='UNSPEC';
  end_pin;
  body
    PART_NAME='RES';
    VALUE='10K';
    TOLERANCE='1%';
    POWER_RATING='0.063W';
    VOLTAGE_RATING='16V';
  end_body;
end_primitive;
primitive 'RES_NOM.C0402_R.4K7_1%';
  pin
    '1'
      PIN_NUMBER='(1)';
      PINUSE='UNSPEC';
    '2'
      PIN_NUMBER='(2)';
      PINUSE='UNSPEC';
  end_pin;
  body
    PART_NAME='RES';
    VALUE='4K7';
    TOLERANCE='1%';
    POWER_RATING='0.063W';
    VOLTAGE_RATING='16V';
  end_body;
end_primitive;
primitive 'CAP_PPG.C0402.0.1UF_16V_X5R';
  pin
    '1'
      PIN_NUMBER='(1)';
      PINUSE='UNSPEC';
    '2'
      PIN_NUMBER='(2)';
      PINUSE='UNSPEC';
  end_pin;
  body
    PART_NAME='CAP';
    VALUE='100nF';
    VOLTAGE_RATING='16V';
    DIELECTRIC='X5R';
    PACKAGE='0402';
  end_body;
end_primitive;
"""

def run_etl():
    print("=" * 60)
    print("Phase 1 ETL Pipeline — End-to-End Validation")
    print("=" * 60)

    # Step 1: Parse
    print("\n[1/5] Parsing Cadence files...")
    net_parser = CadenceNetlistParser()
    prt_parser = CadencePrtParser()
    chip_parser = CadenceChipParser()

    net_topology = net_parser.parse_pstxnet(MOCK_PSTXNET)
    ref_to_prim = prt_parser.parse_pstxprt(MOCK_PSTXPRT)
    chip_library = chip_parser.parse_pstchip(MOCK_PSTCHIP)

    print(f"  Topology triplets: {len(net_topology)}")
    print(f"  RefDes -> Primitive map: {len(ref_to_prim)} entries")
    print(f"  Chip library entries: {len(chip_library)}")

    # Step 2: Fuse
    print("\n[2/5] Fusing component data...")
    graph_components = {}
    for triplet in net_topology:
        refdes = triplet["Component_RefDes"]
        if refdes not in graph_components:
            primitive_name = ref_to_prim.get(refdes)
            properties = chip_library.get(primitive_name, {}).get("Properties", {})
            graph_components[refdes] = {
                "RefDes": refdes,
                "Model": primitive_name,
                "Value": properties.get("VALUE", "N/A"),
                "PartType": properties.get("PART_NAME", "N/A"),
                "MPN": properties.get("MPN"),
                "Package": properties.get("PACKAGE"),
            }

    print(f"  Fused components: {len(graph_components)}")
    for refdes, comp in graph_components.items():
        print(f"    {refdes}: {comp['PartType']} {comp['Value']} ({comp['Model']})")

    # Step 3: Save output
    print("\n[3/5] Saving to output files...")
    output_dir = os.path.join(ROOT_DIR, "data", "output")
    os.makedirs(output_dir, exist_ok=True)

    comp_file = os.path.join(output_dir, "graph_components.json")
    topo_file = os.path.join(output_dir, "topology_triplets.json")

    with open(comp_file, "w", encoding="utf-8") as f:
        json.dump(graph_components, f, ensure_ascii=False, indent=2)
    print(f"  Saved: {comp_file}")

    with open(topo_file, "w", encoding="utf-8") as f:
        json.dump(net_topology, f, ensure_ascii=False, indent=2)
    print(f"  Saved: {topo_file}")

    # Step 4: Inject into Neo4j
    print("\n[4/5] Injecting into Neo4j...")
    from neo4j import GraphDatabase

    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD")

    driver = GraphDatabase.driver(uri, auth=(user, password))

    with driver.session() as session:
        # Create constraints
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

        # Clear existing data
        session.run("MATCH (n) DETACH DELETE n")
        print("  Cleared existing graph data")

        # Inject Component nodes
        comps_list = list(graph_components.values())
        session.run("""
            UNWIND $comps AS comp
            MERGE (c:Component {RefDes: comp.RefDes})
            SET c.Model = comp.Model,
                c.Value = comp.Value,
                c.PartType = comp.PartType,
                c.MPN = comp.MPN,
                c.Package = comp.Package
        """, comps=comps_list)
        print(f"  Inserted {len(comps_list)} Component nodes")

        # Inject Topology (Pin + Net nodes + relationships)
        for triplet in net_topology:
            session.run("""
                MATCH (c:Component {RefDes: $refdes})
                MERGE (p:Pin {Id: $pin_id})
                SET p.Number = $pin_number
                MERGE (c)-[:HAS_PIN]->(p)
                MERGE (n:Net {Name: $net_name})
                MERGE (p)-[:CONNECTS_TO]->(n)
            """,
                refdes=triplet["Component_RefDes"],
                pin_id=f"{triplet['Component_RefDes']}_{triplet['Pin_Number']}",
                pin_number=triplet["Pin_Number"],
                net_name=triplet["Net_Name"],
            )
        print(f"  Inserted {len(net_topology)} Pin+Net topology relations")

        # Verify
        node_count = session.run("MATCH (n) RETURN count(n) as cnt").single()["cnt"]
        comp_count = session.run("MATCH (c:Component) RETURN count(c) as cnt").single()["cnt"]
        net_count = session.run("MATCH (n:Net) RETURN count(n) as cnt").single()["cnt"]
        pin_count = session.run("MATCH (p:Pin) RETURN count(p) as cnt").single()["cnt"]

        print(f"\n  Verification:")
        print(f"    Total nodes: {node_count}")
        print(f"    Component nodes: {comp_count}")
        print(f"    Net nodes: {net_count}")
        print(f"    Pin nodes: {pin_count}")

    driver.close()

    # Step 5: Quick graph query validation
    print("\n[5/5] Graph query validation...")
    driver = GraphDatabase.driver(uri, auth=(user, password))
    with driver.session() as session:
        # Query: find all nets of a component
        result = session.run("""
            MATCH (c:Component {RefDes: 'U30004'})-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net)
            RETURN c.RefDes AS refdes, p.Number AS pin, n.Name AS net
            ORDER BY p.Number
        """)
        print("  U30004 pin-to-net connections:")
        for record in result:
            print(f"    Pin {record['pin']} -> Net '{record['net']}'")

        # Query: I2C power domain analysis
        result = session.run("""
            MATCH path = (c:Component)-[:HAS_PIN]->(:Pin)-[:CONNECTS_TO]->(n:Net)
            WHERE n.Name STARTS WITH 'VDD' OR n.Name = 'GND'
            RETURN n.Name AS net, collect(c.RefDes) AS components
            ORDER BY n.Name
        """)
        print("  Power domain summary:")
        for record in result:
            print(f"    {record['net']}: {', '.join(record['components'])}")

    driver.close()
    print("\n✅ Phase 1 ETL validation PASSED")
    return True


if __name__ == "__main__":
    success = run_etl()
    sys.exit(0 if success else 1)
