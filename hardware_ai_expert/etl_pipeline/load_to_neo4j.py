import json
import os
from neo4j import GraphDatabase
from dotenv import load_dotenv

# 加载项目根目录的 .env 文件
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT_DIR, ".env"))


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
            print("Indexes and uniqueness constraints verified.")

    def batch_insert_components(self, components_list):
        """
        使用 UNWIND 极速批量注入节点数据
        """
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
            print(f"Successfully processed {record['inserted_count']} component nodes.")


if __name__ == "__main__":
    # 从环境变量读取数据库配置
    NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
    NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

    if not NEO4J_PASSWORD:
        print("Error: NEO4J_PASSWORD not set. Please configure it in .env file.")
        exit(1)

    # 读取 graph_components.json
    json_file_path = os.path.join(ROOT_DIR, "data", "output", "graph_components.json")
    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            data_dict = json.load(f)
            components_data = list(data_dict.values())
    except FileNotFoundError:
        print(f"Error: File not found: {json_file_path}")
        exit(1)

    print("Connecting to Neo4j and initializing...")
    db = HardwareGraphDB(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
    
    try:
        db.create_indexes()
        print(f"Preparing to insert {len(components_data)} component records...")
        db.batch_insert_components(components_data)
        print("Component nodes injection completed.")
    except Exception as e:
        print(f"Database error: {e}")
    finally:
        db.close()
