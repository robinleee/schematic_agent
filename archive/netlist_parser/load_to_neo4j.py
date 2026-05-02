import json
import os
from neo4j import GraphDatabase

class HardwareGraphDB:
    def __init__(self, uri, user, password):
        # 建立与 Neo4j 数据库的连接
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self.driver.close()

    def create_indexes(self):
        """
        创建索引：这是图谱能达到毫秒级响应的关键！
        为 Component 节点的 RefDes 字段创建唯一性约束和索引。
        """
        query = """
        CREATE CONSTRAINT refdes_unique IF NOT EXISTS 
        FOR (c:Component) REQUIRE c.RefDes IS UNIQUE
        """
        with self.driver.session() as session:
            session.run(query)
            print("✅ 索引及唯一性约束检查完毕！")

    def batch_insert_components(self, components_list):
        """
        使用 UNWIND 极速批量注入节点数据
        """
        # Cypher 注入语句解释：
        # UNWIND: 把 Python 传进来的大列表展开，一次性在内存里处理
        # MERGE: 相当于“有则更新，无则创建”，保证多次运行脚本不会产生重复的 U1, C120
        # SET: 动态挂载我们在 pstchip.dat 里挖出来的物理参数
        query = """
        UNWIND $components AS comp
        MERGE (c:Component {RefDes: comp.RefDes})
        SET c.Model = comp.Model,
            c.Value = comp.Value,
            c.PartType = comp.PartType
        RETURN count(c) AS inserted_count
        """
        
        with self.driver.session() as session:
            result = session.run(query, components=components_list)
            record = result.single()
            print(f"✅ 成功处理/注入 {record['inserted_count']} 个元器件节点！")

# ==========================================
# 执行主逻辑
# ==========================================
if __name__ == "__main__":
    # 1. 数据库连接配置 (请修改为您 Docker 启动时设置的密码)
    NEO4J_URI = "bolt://localhost:7687"
    NEO4J_USER = "neo4j"
    NEO4J_PASSWORD = "SecretPassword123" 

    # 2. 读取我们准备好的血肉数据
    # 使用脚本所在目录的绝对路径，避免相对路径问题
    script_dir = os.path.dirname(os.path.abspath(__file__))
    json_file_path = os.path.join(script_dir, "output", "graph_components.json")
    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            data_dict = json.load(f)
            # 因为您的 JSON 是字典套字典 {"R30898": {...}, "U30004": {...}}
            # 我们需要把它转换成列表 [{...}, {...}] 传给 UNWIND
            components_data = list(data_dict.values())
    except FileNotFoundError:
        print(f"❌ 找不到文件 {json_file_path}，请检查路径。")
        exit(1)

    # 3. 启动注入引擎
    print("🚀 开始连接图数据库并初始化...")
    db = HardwareGraphDB(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
    
    try:
        db.create_indexes()
        print(f"📦 准备注入 {len(components_data)} 条元器件数据...")
        db.batch_insert_components(components_data)
        print("🎉 器件节点 (Nodes) 注入全流程完成！")
    except Exception as e:
        print(f"❌ 数据库操作发生错误: {e}")
    finally:
        db.close()