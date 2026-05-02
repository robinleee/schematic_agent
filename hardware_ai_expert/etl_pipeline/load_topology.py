import json
import os
import re
from neo4j import GraphDatabase
from dotenv import load_dotenv

# 加载项目根目录的 .env 文件
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT_DIR, ".env"))


# ============================================================
# 网络属性推断规则
# ============================================================

VOLTAGE_PATTERNS = [
    (r'(?i)3V3|3\.3V', '3.3V'),
    (r'(?i)1V8|1\.8V', '1.8V'),
    (r'(?i)1V2|1\.2V', '1.2V'),
    (r'(?i)1V0|1\.0V', '1.0V'),
    (r'(?i)5V\b', '5V'),
    (r'(?i)12V', '12V'),
    (r'(?i)0V9|0\.9V', '0.9V'),
    (r'(?i)0V85|0\.85V', '0.85V'),
    (r'(?i)0V75|0\.75V', '0.75V'),
    (r'(?i)VBAT|BATT', 'VBAT'),
]


def infer_net_properties(net_name: str) -> dict:
    """
    根据网络名推断 VoltageLevel 和 NetType

    Returns:
        {'VoltageLevel': str|None, 'NetType': str}
    """
    name_upper = net_name.upper()

    # 推断 VoltageLevel
    voltage = None
    for pattern, v in VOLTAGE_PATTERNS:
        if re.search(pattern, name_upper):
            voltage = v
            break

    # 推断 NetType
    if 'GND' in name_upper or 'VSS' in name_upper:
        net_type = 'GROUND'
    elif voltage or 'VCC' in name_upper or 'VDD' in name_upper or 'VIN' in name_upper or 'VOUT' in name_upper:
        net_type = 'POWER'
    elif 'I2C' in name_upper or 'SDA' in name_upper or 'SCL' in name_upper:
        net_type = 'BUS'
    elif 'SPI' in name_upper or 'MOSI' in name_upper or 'MISO' in name_upper or 'SCK' in name_upper:
        net_type = 'BUS'
    elif 'UART' in name_upper or 'TX' in name_upper or 'RX' in name_upper:
        net_type = 'BUS'
    elif 'USB' in name_upper or 'DP' in name_upper or 'DM' in name_upper:
        net_type = 'BUS'
    elif 'HDMI' in name_upper or 'TMDS' in name_upper:
        net_type = 'BUS'
    elif 'PCIE' in name_upper or 'MIPI' in name_upper:
        net_type = 'BUS'
    elif 'CLK' in name_upper or 'OSC' in name_upper:
        net_type = 'CLOCK'
    elif 'RST' in name_upper or 'RESET' in name_upper:
        net_type = 'CONTROL'
    elif 'NC' in name_upper or 'DNU' in name_upper:
        net_type = 'NC'
    else:
        net_type = 'SIGNAL'

    return {'VoltageLevel': voltage, 'NetType': net_type}


class HardwareTopologyDB:
    def __init__(self, uri, user, password):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self.driver.close()

    def create_topology_indexes(self):
        """
        为 Pin 和 Net 创建索引，这是保证 MERGE 语句极速执行的生命线！
        """
        queries = [
            "CREATE CONSTRAINT pin_id_unique IF NOT EXISTS FOR (p:Pin) REQUIRE p.Id IS UNIQUE",
            "CREATE CONSTRAINT net_name_unique IF NOT EXISTS FOR (n:Net) REQUIRE n.Name IS UNIQUE"
        ]
        with self.driver.session() as session:
            for q in queries:
                session.run(q)
            print("Pin and Net indexes/constraints verified.")

    def batch_insert_topology(self, triplets_list):
        """
        一次性注入: Pin 节点、Net 节点，以及 HAS_PIN 和 CONNECTS_TO 两种关系
        增强：自动推断 Net 的 VoltageLevel 和 NetType
        """
        # 预处理：为每个 triplet 添加推断属性
        enriched_triplets = []
        for trip in triplets_list:
            enriched = dict(trip)
            props = infer_net_properties(trip['Net_Name'])
            enriched['_inferred_voltage'] = props['VoltageLevel']
            enriched['_inferred_type'] = props['NetType']
            enriched_triplets.append(enriched)

        query = """
        UNWIND $triplets AS trip

        // 1. 匹配已经存在的器件节点
        MATCH (c:Component {RefDes: trip.Component_RefDes})

        // 2. 创建或匹配引脚节点 (拼装全局唯一 ID)
        MERGE (p:Pin {Id: trip.Component_RefDes + '_' + trip.Pin_Number})
        ON CREATE SET p.Number = trip.Pin_Number

        // 3. 建立: 器件 -> 拥有 -> 引脚 的关系
        MERGE (c)-[:HAS_PIN]->(p)

        // 4. 创建或匹配网络节点（带属性推断）
        MERGE (n:Net {Name: trip.Net_Name})
        ON CREATE SET n.VoltageLevel = trip._inferred_voltage,
                      n.NetType = trip._inferred_type
        ON MATCH SET n.VoltageLevel = COALESCE(n.VoltageLevel, trip._inferred_voltage),
                     n.NetType = COALESCE(n.NetType, trip._inferred_type)

        // 5. 建立: 引脚 -> 连接到 -> 网络 的电气拓扑关系
        MERGE (p)-[:CONNECTS_TO]->(n)

        RETURN count(p) AS processed_pins
        """

        with self.driver.session() as session:
            result = session.run(query, triplets=enriched_triplets)
            record = result.single()
            print(f"Successfully processed {record['processed_pins']} pin connections.")

            # 统计 NetType 分布
            stats = session.run("""
                MATCH (n:Net)
                RETURN n.NetType AS nt, count(n) AS cnt
                ORDER BY cnt DESC
            """)
            print("\nNetType 分布:")
            for row in stats:
                print(f"  {row['nt'] or 'N/A'}: {row['cnt']}")

            # 统计 VoltageLevel 分布
            vstats = session.run("""
                MATCH (n:Net)
                WHERE n.VoltageLevel IS NOT NULL
                RETURN n.VoltageLevel AS vl, count(n) AS cnt
                ORDER BY cnt DESC
            """)
            print("\nVoltageLevel 分布 (已推断):")
            for row in vstats:
                print(f"  {row['vl']}: {row['cnt']}")


if __name__ == "__main__":
    # 从环境变量读取数据库配置
    NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
    NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

    if not NEO4J_PASSWORD:
        print("Error: NEO4J_PASSWORD not set. Please configure it in .env file.")
        exit(1)

    # 读取 topology_triplets.json
    topology_file = os.path.join(ROOT_DIR, "data", "output", "topology_triplets.json")

    print(f"Loading topology data from: {topology_file}")
    try:
        with open(topology_file, 'r', encoding='utf-8') as f:
            triplets = json.load(f)
    except FileNotFoundError:
        print(f"Error: File not found: {topology_file}")
        exit(1)

    print("Connecting to Neo4j and initializing topology injection...")
    db = HardwareTopologyDB(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)

    try:
        db.create_topology_indexes()
        print(f"Preparing to insert {len(triplets)} topology records...")
        db.batch_insert_topology(triplets)
        print("Topology relationships injection completed.")
    except Exception as e:
        print(f"Database error: {e}")
    finally:
        db.close()
