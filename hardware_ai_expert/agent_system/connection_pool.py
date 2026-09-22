"""共享连接池 — 供 API 健康检查/状态上报复用连接单例。

提供 Neo4j 驱动与 Ollama 客户端的缓存单例，避免各 router 各自新建连接。
凭据一律来自环境变量（NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD、OLLAMA_URL），
禁止在代码中硬编码密码（见 PRD §14.1/§14.3）。
"""
from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv

# 与 agent_system 其余模块保持一致：导入时加载 hardware_ai_expert/.env
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT_DIR, ".env"))


@lru_cache()
def get_neo4j_driver():
    """返回缓存的 Neo4j 驱动单例。

    凭据缺失或驱动创建失败时抛出异常，由调用方（如 system 状态路由）
    捕获并上报为服务 error 状态。
    """
    from neo4j import GraphDatabase

    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD")
    if not password:
        raise RuntimeError("NEO4J_PASSWORD 未设置（请在 hardware_ai_expert/.env 配置）")
    return GraphDatabase.driver(uri, auth=(user, password))


@lru_cache()
def get_ollama_client():
    """返回缓存的 Ollama 客户端单例（暴露 .list() 用于健康探测）。"""
    import ollama

    host = os.getenv("OLLAMA_URL", "http://localhost:11434")
    return ollama.Client(host=host)


def close_all() -> None:
    """关闭并清空缓存的连接（用于测试/优雅退出）。"""
    if get_neo4j_driver.cache_info().currsize:
        try:
            get_neo4j_driver().close()
        except Exception:
            pass
    get_neo4j_driver.cache_clear()
    get_ollama_client.cache_clear()
