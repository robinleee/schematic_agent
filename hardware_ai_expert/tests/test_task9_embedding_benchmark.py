import importlib.util
from pathlib import Path

import pytest

from agent_system.graph_rag.indexers.vector_indexer import Neo4jVectorIndexer
from agent_system.graph_rag.schemas import GraphRAGConfig, VectorChunk


SCRIPT = Path(__file__).resolve().parents[1] / "tools/graphrag_retrieval_benchmark.py"
spec = importlib.util.spec_from_file_location("retrieval_benchmark", SCRIPT)
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


class Session:
    def __init__(self, indexes=None, meta=None):
        self.indexes = indexes or []
        self.meta = meta
        self.writes = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def run(self, cypher, params=None):
        if cypher.startswith("SHOW INDEXES"):
            return self.indexes
        if cypher.startswith("MATCH (m:VectorIndexMetadata"):
            class Result:
                def __init__(self, record):
                    self.record = record

                def single(self):
                    return self.record
            return Result(self.meta)
        self.writes.append((cypher, params))
        class Result:
            def consume(self):
                pass
        return Result()


class Driver:
    def __init__(self, session):
        self.value = session

    def session(self):
        return self.value


def indexer(session, dim=2):
    return Neo4jVectorIndexer(Driver(session),
                             GraphRAGConfig(embedding_model="test-model", embedding_dim=dim))


def verified_session(dim=2):
    return Session(
        [{"type": "VECTOR", "options": {"indexConfig": {"vector.dimensions": dim}}}],
        {"model": "test-model", "dimension": dim, "scope": "shared+project"})


@pytest.mark.parametrize("vectors", [[[0, 0]], [[1]], [[float("nan"), 1]]])
def test_invalid_vectors_do_not_write(vectors):
    session = verified_session()
    obj = indexer(session)
    obj._embedding_fn = lambda texts: vectors
    with pytest.raises(ValueError):
        obj.index_chunks([VectorChunk("id", "text")])
    assert not session.writes


def test_model_loading_error_does_not_write():
    session = verified_session()
    obj = indexer(session)
    def broken(texts):
        raise RuntimeError("model unavailable")
    obj._embedding_fn = broken
    with pytest.raises(RuntimeError, match="model unavailable"):
        obj.index_chunks([VectorChunk("id", "text")])
    assert not session.writes


@pytest.mark.parametrize("session", [
    Session([{"type": "VECTOR", "options": {"indexConfig": {"vector.dimensions": 2}}}]),
    Session([{"type": "VECTOR", "options": {"indexConfig": {"vector.dimensions": 3}}}]),
    Session([{"type": "VECTOR", "options": {"indexConfig": {"vector.dimensions": 2}}}],
            {"model": "other", "dimension": 2, "scope": "shared+project"}),
])
def test_legacy_wrong_dimension_or_model_refuses_write(session):
    obj = indexer(session)
    obj._embedding_fn = lambda texts: [[1, 0]]
    with pytest.raises(RuntimeError):
        obj.index_chunks([VectorChunk("id", "text")])
    assert not session.writes


def test_existing_index_never_recreated(monkeypatch):
    session = verified_session()
    obj = indexer(session)
    monkeypatch.setattr("agent_system.embedding.get_actual_embedding_dim", lambda _: 2)
    obj.create_index()
    assert not session.writes
    assert obj._check_index(session, create=True)


def test_dimension_mismatch_blocks_create(monkeypatch):
    session = Session()
    obj = indexer(session)
    monkeypatch.setattr("agent_system.embedding.get_actual_embedding_dim", lambda _: 3)
    with pytest.raises(ValueError, match="dimension"):
        obj.create_index()
    assert not session.writes


def test_metrics_and_fixed_golden():
    golden = bench.load_golden(bench.GOLDEN)
    assert len(golden["queries"]) == 7
    scores = bench.score_ranking(["noise", "a", "a", "b"], {"a": 2, "b": 1})
    assert scores["recall@5"] == 1
    assert scores["recall@10"] == 1
    assert scores["mrr"] == .5
    assert scores["ndcg@10"] == pytest.approx(
            ((2**2 - 1) / 1.584962500721156 + (2**1 - 1) / 2.321928094887362) /
        ((2**2 - 1) + (2**1 - 1) / 1.584962500721156))
    assert bench.score_ranking([], {"a": 1})["mrr"] == 0
