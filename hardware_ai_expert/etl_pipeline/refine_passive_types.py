"""
将 Neo4j 中的 PASSIVE 节点根据 Value 细分为 CAPACITOR/RESISTOR/INDUCTOR

执行方式:
    python3 -m etl_pipeline.refine_passive_types
"""

import os
import re
from neo4j import GraphDatabase
from dotenv import load_dotenv

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

# Value 匹配模式
CAP_PATTERN = re.compile(r'(?i)^[0-9]+(\.[0-9]+)?\s*[unpμ]?f')
RES_PATTERN = re.compile(r'(?i)^[0-9]+(\.[0-9]+)?\s*[kmrΩ]?')
IND_PATTERN = re.compile(r'(?i)^[0-9]+(\.[0-9]+)?\s*[unm]?h')


def refine_passive_types():
    driver = GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD"))
    )

    try:
        # 获取所有 PASSIVE 节点
        with driver.session() as session:
            result = session.run("""
                MATCH (c:Component {PartType: 'PASSIVE'})
                RETURN c.RefDes AS refdes, c.Value AS value
            """)
            passive_nodes = [(r["refdes"], r["value"]) for r in result]

        print(f"找到 {len(passive_nodes)} 个 PASSIVE 节点")

        # 分类统计
        updates = {"CAPACITOR": [], "RESISTOR": [], "INDUCTOR": [], "UNKNOWN": []}

        for refdes, value in passive_nodes:
            if not value:
                updates["UNKNOWN"].append(refdes)
                continue

            val = value.strip().upper()
            if val.startswith("DNP") or val.startswith("NC"):
                updates["UNKNOWN"].append(refdes)
                continue

            if CAP_PATTERN.match(val):
                updates["CAPACITOR"].append(refdes)
            elif IND_PATTERN.match(val):
                updates["INDUCTOR"].append(refdes)
            elif RES_PATTERN.match(val):
                updates["RESISTOR"].append(refdes)
            else:
                updates["UNKNOWN"].append(refdes)

        # 执行更新
        with driver.session() as session:
            for new_type, refdes_list in updates.items():
                if not refdes_list:
                    continue
                print(f"  更新 {len(refdes_list)} 个节点为 {new_type}")

                # 分批更新（每批 1000）
                batch_size = 1000
                for i in range(0, len(refdes_list), batch_size):
                    batch = refdes_list[i:i+batch_size]
                    session.run("""
                        UNWIND $refdes_list AS rd
                        MATCH (c:Component {RefDes: rd})
                        SET c.PartType = $new_type
                    """, refdes_list=batch, new_type=new_type)

        print("\n更新完成:")
        for t, lst in updates.items():
            print(f"  {t}: {len(lst)}")

    finally:
        driver.close()


if __name__ == "__main__":
    refine_passive_types()
