#!/usr/bin/env python3
"""
Neo4j Schema 初始化脚本

确保 Neo4j 数据库的约束和索引正确创建。
对应 Schemas_Design.md Section 7
"""

import sys
import os

# 添加项目根目录到 Python 路径
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from neo4j import GraphDatabase
from agent_system.schemas.graph import NEO4J_CONSTRAINTS, NEO4J_INDEXES


def get_neo4j_credentials() -> tuple[str, str, str]:
    """从 .env 文件读取 Neo4j 凭据"""
    env_path = os.path.join(ROOT_DIR, ".env")
    uri = "bolt://localhost:7687"
    user = "neo4j"
    password = "SecretPassword123"

    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    val = val.strip()
                    if key == "NEO4J_URI":
                        uri = val
                    elif key == "NEO4J_USER":
                        user = val
                    elif key == "NEO4J_PASSWORD":
                        password = val

    return uri, user, password


def initialize_schema(uri: str, user: str, password: str) -> dict:
    """
    初始化 Neo4j Schema

    创建所有约束和索引。如果已存在则跳过。

    Returns:
        统计结果 dict，包含约束/索引的创建状态
    """
    print(f"Connecting to Neo4j at {uri}...")
    driver = GraphDatabase.driver(uri, auth=(user, password))

    stats = {"constraints": {"created": 0, "skipped": 0, "failed": 0},
             "indexes": {"created": 0, "skipped": 0, "failed": 0}}

    try:
        with driver.session() as session:
            # 测试连接
            session.run("RETURN 1")
            print("✅ Connected to Neo4j")

        with driver.session() as session:
            # 创建约束
            print("\n📐 Creating constraints...")
            for constraint in NEO4J_CONSTRAINTS:
                try:
                    session.run(constraint)
                    print(f"  ✅ Created: {constraint[:70]}...")
                    stats["constraints"]["created"] += 1
                except Exception as e:
                    err_str = str(e).lower()
                    if "already exists" in err_str or "constraint already exists" in err_str:
                        print(f"  ⏭️  Skipped (already exists): {constraint[:70]}...")
                        stats["constraints"]["skipped"] += 1
                    else:
                        print(f"  ❌ Error: {e}")
                        stats["constraints"]["failed"] += 1

            # 创建索引
            print("\n📇 Creating indexes...")
            for index in NEO4J_INDEXES:
                try:
                    session.run(index)
                    print(f"  ✅ Created: {index[:70]}...")
                    stats["indexes"]["created"] += 1
                except Exception as e:
                    err_str = str(e).lower()
                    if "already exists" in err_str or "index already exists" in err_str:
                        print(f"  ⏭️  Skipped (already exists): {index[:70]}...")
                        stats["indexes"]["skipped"] += 1
                    else:
                        print(f"  ❌ Error: {e}")
                        stats["indexes"]["failed"] += 1

        # 验证约束
        print("\n🔍 Verifying constraints...")
        with driver.session() as session:
            constraints = list(session.run("SHOW CONSTRAINTS"))
            print(f"  Active constraints: {len(constraints)}")
            for c in constraints:
                print(f"    - {c['name']}: {c['type']} on {c['labelsOrTypes']}")

        # 验证索引
        print("\n🔍 Verifying indexes...")
        with driver.session() as session:
            indexes = list(session.run("SHOW INDEXES"))
            print(f"  Active indexes: {len(indexes)}")
            for idx in indexes:
                print(f"    - {idx['name']}: {idx['type']} on {idx['labelsOrTypes']}")

        print("\n✅ Neo4j Schema initialization completed.")

        return stats

    finally:
        driver.close()


def main() -> None:
    """主入口"""
    print("=" * 60)
    print("  Neo4j Schema Initialization")
    print("=" * 60)

    uri, user, password = get_neo4j_credentials()
    print(f"\nUsing credentials:")
    print(f"  URI: {uri}")
    print(f"  User: {user}")
    print(f"  (password hidden)")

    try:
        initialize_schema(uri, user, password)
    except Exception as e:
        print(f"\n❌ Failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()