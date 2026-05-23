"""
KnowledgeSource 自动关联脚本

按 MPN 前缀匹配，将 KnowledgeSource 节点关联到 Component 节点。
支持增量运行（不重复创建已有关联）。

用法：
    python -m agent_system.rebuild_knowledge_links
"""

import sys
import os

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from agent_system.graph_tools import _run_cypher


def rebuild_knowledge_links() -> dict:
    """重建 KnowledgeSource → Component 关联

    Returns:
        dict: {created: int, total: int, details: list}
    """
    # 1. 清除旧关联
    _run_cypher("MATCH ()-[r:HAS_KNOWLEDGE]->() DELETE r")
    
    # 2. 前缀匹配创建新关联
    result = _run_cypher("""
        MATCH (c:Component), (ks:KnowledgeSource)
        WHERE c.Value STARTS WITH ks.mpn
        MERGE (c)-[:HAS_KNOWLEDGE]->(ks)
        RETURN c.RefDes AS refdes, c.Value AS value, ks.mpn AS ks_mpn
    """)
    
    details = [{"refdes": r["refdes"], "value": r["value"], "ks_mpn": r["ks_mpn"]} for r in result]
    
    return {
        "created": len(details),
        "total": len(details),
        "details": details,
    }


if __name__ == "__main__":
    result = rebuild_knowledge_links()
    print(f"创建关联: {result['created']}")
    for d in result["details"]:
        print(f"  {d['refdes']} ({d['value']}) -> {d['ks_mpn']}")
