"""Offline tests for API dependency factories (no live Neo4j / LLM / Chroma)."""
import importlib
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))                   # hardware_ai_expert/
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))  # repo root

from hardware_ai_expert.api import dependencies as deps  # noqa: E402

FACTORIES = [
    deps.get_neo4j_driver, deps.get_llm_client, deps.get_react_agent,
    deps.get_knowledge_router, deps.get_hitl_manager, deps.get_review_engine,
    deps.get_etl_bridge,
]


@pytest.fixture(autouse=True)
def fresh_caches(monkeypatch):
    """Factories are lru_cached; never leak a fake singleton into other tests."""
    from neo4j import GraphDatabase

    def no_live_driver(*args, **kwargs):
        raise AssertionError("live Neo4j driver requested")

    monkeypatch.setattr(GraphDatabase, "driver", no_live_driver)
    for factory in FACTORIES:
        factory.cache_clear()
    yield
    for factory in FACTORIES:
        factory.cache_clear()


class FakeSession:
    def __init__(self, driver):
        self.driver = driver

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, query):
        self.driver.queries.append(query)
        if self.driver.fail:
            raise RuntimeError("connection refused")
        return self
    def single(self):
        return {"1": 1}


class FakeDriver:
    def __init__(self, fail=False):
        self.fail = fail
        self.queries = []

    def session(self):
        return FakeSession(self)


# ------------------------------------------------------------------ neo4j
def test_neo4j_driver_without_password_is_none(monkeypatch):
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)
    assert deps.get_neo4j_driver() is None


def test_neo4j_driver_connects_with_env_and_is_cached(monkeypatch):
    from neo4j import GraphDatabase
    calls = []
    fake = FakeDriver()

    def driver(uri, auth):
        calls.append((uri, auth))
        return fake

    monkeypatch.setattr(GraphDatabase, "driver", driver)
    monkeypatch.setenv("NEO4J_URI", "bolt://fake-host:1")
    monkeypatch.setenv("NEO4J_USER", "tester")
    monkeypatch.setenv("NEO4J_PASSWORD", "secret")
    assert deps.get_neo4j_driver() is fake
    assert deps.get_neo4j_driver() is fake
    assert calls == [("bolt://fake-host:1", ("tester", "secret"))]
    assert fake.queries == ["RETURN 1"]


def test_neo4j_driver_failed_probe_is_none(monkeypatch):
    from neo4j import GraphDatabase
    monkeypatch.setattr(GraphDatabase, "driver", lambda uri, auth: FakeDriver(fail=True))
    monkeypatch.setenv("NEO4J_PASSWORD", "secret")
    assert deps.get_neo4j_driver() is None


# ------------------------------------------------------------------ simple singletons
SIMPLE = [
    (deps.get_llm_client, "agent_system.llm_client", "LLMClient"),
    (deps.get_react_agent, "agent_system.react_agent", "ReActAgent"),
    (deps.get_hitl_manager, "agent_system.hitl_workflow", "HITLManager"),
]
# get_etl_bridge is deliberately not covered: agent_system.etl_web_bridge defines
# ETLWebExecutor, not ETLWebBridge, so the factory can only ever return None.


@pytest.mark.parametrize("factory,module_name,cls_name", SIMPLE)
def test_singleton_factory_success_and_cache(monkeypatch, factory, module_name, cls_name):
    module = importlib.import_module(module_name)
    created = []

    class Fake:
        def __init__(self):
            created.append(self)

    monkeypatch.setattr(module, cls_name, Fake)
    first = factory()
    assert isinstance(first, Fake)
    assert factory() is first
    assert len(created) == 1


@pytest.mark.parametrize("factory,module_name,cls_name", SIMPLE)
def test_singleton_factory_failure_returns_none(monkeypatch, factory, module_name, cls_name):
    module = importlib.import_module(module_name)

    def broken():
        raise RuntimeError("backend down")

    monkeypatch.setattr(module, cls_name, broken)
    assert factory() is None


# ------------------------------------------------------------------ keyed factories
def test_knowledge_router_is_keyed_by_ownership(monkeypatch):
    module = importlib.import_module("agent_system.knowledge_router")

    class FakeRouter:
        def __init__(self, project_id=None, shared=False):
            self.project_id, self.shared = project_id, shared

    monkeypatch.setattr(module, "KnowledgeRouter", FakeRouter)
    a = deps.get_knowledge_router("A")
    b = deps.get_knowledge_router("B")
    shared = deps.get_knowledge_router(None, True)
    assert (a.project_id, b.project_id) == ("A", "B")
    assert a is not b
    assert shared.shared is True and shared.project_id is None
    assert deps.get_knowledge_router("A") is a


def test_knowledge_router_failure_returns_none(monkeypatch):
    module = importlib.import_module("agent_system.knowledge_router")

    def broken(**kwargs):
        raise RuntimeError("chroma down")

    monkeypatch.setattr(module, "KnowledgeRouter", broken)
    assert deps.get_knowledge_router("A") is None


def test_review_engine_needs_driver(monkeypatch):
    monkeypatch.setattr(deps, "get_neo4j_driver", lambda: None)
    assert deps.get_review_engine("A") is None


def test_review_engine_built_per_project(monkeypatch):
    module = importlib.import_module("agent_system.review_engine")
    driver = object()

    class FakeEngine:
        def __init__(self, neo4j_driver, project_id=None):
            self.neo4j_driver, self.project_id = neo4j_driver, project_id

    monkeypatch.setattr(deps, "get_neo4j_driver", lambda: driver)
    monkeypatch.setattr(module, "ReviewRuleEngine", FakeEngine)
    a = deps.get_review_engine("A")
    assert a.neo4j_driver is driver and a.project_id == "A"
    assert deps.get_review_engine("B").project_id == "B"
    assert deps.get_review_engine("A") is a


def test_review_engine_failure_returns_none(monkeypatch):
    module = importlib.import_module("agent_system.review_engine")

    def broken(**kwargs):
        raise RuntimeError("bad rules")

    monkeypatch.setattr(deps, "get_neo4j_driver", lambda: object())
    monkeypatch.setattr(module, "ReviewRuleEngine", broken)
    assert deps.get_review_engine(None) is None
