"""
重建 KnowledgeSource ↔ Component 关联

从 ChromaDB 的 PDF source 列表创建/更新 Neo4j KnowledgeSource 节点，
并用模糊匹配关联到原理图中的 Component 节点。

用法:
    python rebuild_knowledge_links.py
"""

import sys
import os
import re
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import chromadb
from neo4j import GraphDatabase
from dotenv import load_dotenv

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# PDF 文件名 → MPN 关键词映射
# 一个 PDF 可能覆盖多个 MPN 前缀
PDF_MPN_MAP = {
    'tps7a47.pdf': ['TPS7A47', 'TPS7A4700', 'TPS7A4701'],
    'tlv733p-q1.pdf': ['TLV733'],
    'tps389006.pdf': ['TPS389'],
    'tps63070.pdf': ['TPS63070'],
    'sn74lvc1g34.pdf': ['SN74LVC1G34', 'SN74LVC'],
}

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "SecretPassword123")


def get_chroma_sources() -> dict:
    """获取 ChromaDB 中每个 PDF 的 chunk 数"""
    client = chromadb.HttpClient(host='localhost', port=8000)
    col = client.get_collection('hardware_knowledge')
    all_meta = col.get(include=['metadatas'])
    
    sources = {}
    for m in all_meta['metadatas']:
        src = m.get('source', 'unknown')
        sources[src] = sources.get(src, 0) + 1
    
    return sources


def rebuild_links():
    """重建所有 KnowledgeSource 和 HAS_KNOWLEDGE 关联"""
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    chroma_sources = get_chroma_sources()
    
    total_ks = 0
    total_links = 0
    
    with driver.session() as session:
        # 1. 清除旧的 KnowledgeSource 和 HAS_KNOWLEDGE
        session.run("MATCH (k:KnowledgeSource) DETACH DELETE k")
        logger.info("Cleared existing KnowledgeSource nodes")
        
        # 2. 为每个 PDF 创建 KnowledgeSource 并关联 Component
        for pdf_name, chunk_count in chroma_sources.items():
            mpn_keywords = PDF_MPN_MAP.get(pdf_name, [])
            if not mpn_keywords:
                # 从文件名推断 MPN
                base = pdf_name.replace('.pdf', '').upper()
                mpn_keywords = [base]
            
            primary_mpn = mpn_keywords[0]
            
            # 创建 KnowledgeSource 节点
            session.run("""
                CREATE (k:KnowledgeSource {
                    mpn: $mpn,
                    source: $pdf,
                    chunk_count: $chunks,
                    keywords: $keywords
                })
            """, mpn=primary_mpn, pdf=pdf_name, chunks=chunk_count,
                keywords=','.join(mpn_keywords))
            total_ks += 1
            logger.info(f"Created KnowledgeSource: {primary_mpn} ({pdf_name}, {chunk_count} chunks)")
            
            # 关联匹配的 Component
            for keyword in mpn_keywords:
                # 在 Model 字段中搜索
                result = session.run("""
                    MATCH (c:Component)
                    WHERE c.Model IS NOT NULL AND c.Model CONTAINS $keyword
                    WITH DISTINCT c
                    MATCH (k:KnowledgeSource {mpn: $mpn})
                    MERGE (k)-[:HAS_KNOWLEDGE]->(c)
                    RETURN count(c) AS cnt
                """, keyword=keyword, mpn=primary_mpn)
                record = result.single()
                cnt = record['cnt'] if record else 0
                if cnt > 0:
                    total_links += cnt
                    logger.info(f"  Linked '{keyword}' → {cnt} components")
        
        # 3. 验证
        ks_count = session.run("MATCH (k:KnowledgeSource) RETURN count(k) AS n").single()['n']
        link_count = session.run("MATCH ()-[r:HAS_KNOWLEDGE]->() RETURN count(r) AS n").single()['n']
        logger.info(f"\nDone! KnowledgeSource: {ks_count}, HAS_KNOWLEDGE: {link_count}")
    
    driver.close()
    return total_ks, total_links


if __name__ == '__main__':
    ks, links = rebuild_links()
    print(f"\n✅ Rebuilt: {ks} KnowledgeSource nodes, {links} HAS_KNOWLEDGE relations")
