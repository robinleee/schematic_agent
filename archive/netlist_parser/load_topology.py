import json
import os
from neo4j import GraphDatabase

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
            print("✅ 引脚(Pin)与网络(Net)的约束及索引建立完毕！")

    def batch_insert_topology(self, triplets_list):
        """
        一次性注入: Pin 节点、Net 节点，以及 HAS_PIN 和 CONNECTS_TO 两种关系
        """
        # Cypher 核心逻辑：
        # 1. MATCH: 找到之前已经建好的 Component
        # 2. MERGE Pin: 用 "位号_引脚号" 拼成唯一 ID (例如 "C120_1")
        # 3. MERGE Net: 用网络名去重
        # 4. MERGE 关系: 建立两条关键的有向边
        query = """
        UNWIND $triplets AS trip
        
        // 1. 匹配已经存在的器件节点
        MATCH (c:Component {RefDes: trip.Component_RefDes})
        
        // 2. 创建或匹配引脚节点 (拼装全局唯一 ID)
        MERGE (p:Pin {Id: trip.Component_RefDes + '_' + trip.Pin_Number})
        ON CREATE SET p.Number = trip.Pin_Number
        
        // 3. 建立: 器件 -> 拥有 -> 引脚 的关系
        MERGE (c)-[:HAS_PIN]->(p)
        
        // 4. 创建或匹配网络节点
        MERGE (n:Net {Name: trip.Net_Name})
        
        // 5. 建立: 引脚 -> 连接到 -> 网络 的电气拓扑关系
        MERGE (p)-[:CONNECTS_TO]->(n)
        
        RETURN count(p) AS processed_pins
        """
        
        with self.driver.session() as session:
            result = session.run(query, triplets=triplets_list)
            record = result.single()
            print(f"✅ 成功处理拓扑连线，涉及 {record['processed_pins']} 个引脚连接动作！")

# ==========================================
# 执行主逻辑
# ==========================================
if __name__ == "__main__":
    NEO4J_URI = "bolt://localhost:7687"
    NEO4J_USER = "neo4j"
    NEO4J_PASSWORD = "SecretPassword123"

    # 从 topology_triplets.json 文件读取拓扑三元组数据
    script_dir = os.path.dirname(os.path.abspath(__file__))
    topology_file = os.path.join(script_dir, "..", "output", "topology_triplets.json")

    print(f"📂 正在从文件加载拓扑数据: {topology_file}")
    with open(topology_file, 'r', encoding='utf-8') as f:
        triplets = json.load(f)

    print("🚀 开始连接图数据库并初始化拓扑注入...")
    db = HardwareTopologyDB(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)

    try:
        db.create_topology_indexes()
        print(f"📦 准备注入 {len(triplets)} 条拓扑关系...")
        db.batch_insert_topology(triplets)
        print("🎉 物理拓扑连线 (Relationships) 注入全流程完成！")
    except Exception as e:
        print(f"❌ 数据库操作发生错误: {e}")
    finally:
        db.close()