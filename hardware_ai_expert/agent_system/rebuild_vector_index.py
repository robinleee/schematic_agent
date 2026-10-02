"""Rebuild the GraphRAG vector index using the new default embedding model
(bge-m3, 1024-dim) into a separate index (chunk_embedding_v2), without
touching the legacy 384-dim all-MiniLM index or its VectorChunk nodes.

Re-embeds text already stored on existing VectorChunk nodes and writes fresh
VectorChunk nodes (new ids) scoped as 'shared', so old and new sit side by
side until the old one is explicitly retired.

Usage:
    cd hardware_ai_expert
    source ../.venv/bin/activate
    python3 -m agent_system.rebuild_vector_index
"""
from __future__ import annotations

import logging
import os
import sys
import uuid
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv
load_dotenv(str(ROOT_DIR / ".env"))


def main():
    from neo4j import GraphDatabase
    from agent_system.graph_rag.schemas import VectorChunk, GraphRAGConfig
    from agent_system.graph_rag.indexers.vector_indexer import Neo4jVectorIndexer

    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD")
    if not password:
        raise RuntimeError("NEO4J_PASSWORD is required")

    driver = GraphDatabase.driver(uri, auth=(user, password))
    config = GraphRAGConfig(neo4j_uri=uri, neo4j_user=user, neo4j_password=password)
    indexer = Neo4jVectorIndexer(driver, config)
    logger.info("target index=%s model=%s dim=%s", indexer.INDEX_NAME,
                config.embedding_model, config.embedding_dim)

    with driver.session() as session:
        rows = list(session.run(
            "MATCH (vc:VectorChunk) WHERE vc.text IS NOT NULL "
            "RETURN vc.text AS text, vc.source AS source, vc.chunk_index AS chunk_index"
        ))
    logger.info("found %d legacy chunks with text to re-embed", len(rows))
    if not rows:
        logger.warning("nothing to migrate; exiting")
        return

    chunks = [
        VectorChunk(
            id=str(uuid.uuid4()),
            text=row["text"],
            source=row["source"] or "",
            chunk_index=row["chunk_index"] or 0,
            scope="shared",
        )
        for row in rows
    ]

    indexer.create_index()
    indexer.index_chunks(chunks)
    logger.info("indexed %d chunks into %s", len(chunks), indexer.INDEX_NAME)

    with driver.session() as session:
        count = session.run(
            "MATCH (vc:VectorChunk) WHERE vc.embedding_model = $model "
            "RETURN count(vc) AS c",
            {"model": config.embedding_model},
        ).single()["c"]
    logger.info("verified %d VectorChunk nodes tagged with model=%s", count, config.embedding_model)
    driver.close()


if __name__ == "__main__":
    main()
