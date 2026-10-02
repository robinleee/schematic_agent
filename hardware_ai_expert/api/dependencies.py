"""Dependency injection for API."""
import os
import logging
from functools import lru_cache
from typing import Optional, Any


@lru_cache()
def get_neo4j_driver():
    """Get Neo4j driver singleton."""
    try:
        from neo4j import GraphDatabase
        uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD")
        if not password:
            return None
        driver = GraphDatabase.driver(uri, auth=(user, password))
        # Test connection
        with driver.session() as session:
            session.run("RETURN 1").single()
        return driver
    except Exception as e:
        logging.getLogger(__name__).warning("Neo4j unavailable")
        return None


@lru_cache()
def get_llm_client():
    """Get LLM client singleton."""
    try:
        from agent_system.llm_client import LLMClient
        return LLMClient()
    except Exception as e:
        logging.getLogger(__name__).warning("LLM client unavailable")
        return None


@lru_cache()
def get_react_agent():
    """Get ReActAgent singleton."""
    try:
        from agent_system.react_agent import ReActAgent
        return ReActAgent()
    except Exception as e:
        logging.getLogger(__name__).warning("ReActAgent unavailable")
        return None


@lru_cache()
def get_knowledge_router(project_id: Optional[str] = None, shared: bool = False):
    """Get a router keyed by ownership context; never reuse A's router for B."""
    try:
        from agent_system.knowledge_router import KnowledgeRouter
        return KnowledgeRouter(project_id=project_id, shared=shared)
    except Exception as e:
        logging.getLogger(__name__).warning("KnowledgeRouter unavailable")
        return None


@lru_cache()
def get_hitl_manager():
    """Get HITLManager singleton."""
    try:
        from agent_system.hitl_workflow import HITLManager
        return HITLManager()
    except Exception as e:
        logging.getLogger(__name__).warning("HITLManager unavailable")
        return None


@lru_cache()
def get_review_engine(project_id: Optional[str] = None):
    """Get a review engine keyed by project ownership context."""
    try:
        from agent_system.review_engine import ReviewRuleEngine
        driver = get_neo4j_driver()
        if driver is None:
            return None
        return ReviewRuleEngine(neo4j_driver=driver, project_id=project_id)
    except Exception as e:
        logging.getLogger(__name__).warning("ReviewRuleEngine unavailable")
        return None


@lru_cache()
def get_etl_bridge():
    """Get ETLWebBridge singleton."""
    try:
        from agent_system.etl_web_bridge import ETLWebBridge
        return ETLWebBridge()
    except Exception as e:
        logging.getLogger(__name__).warning("ETLWebBridge unavailable")
        return None
