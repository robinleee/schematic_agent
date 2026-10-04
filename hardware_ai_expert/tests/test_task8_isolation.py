"""Offline isolation contract: stores are in-memory; never open live Neo4j."""
import pytest

from agent_system import knowledge_router as kr
from agent_system.graph_rag.indexers.vector_indexer import Neo4jVectorIndexer
from agent_system.graph_rag.schemas import VectorChunk
from agent_system.graph_rag.pipeline import GraphRAGPipeline
from agent_system.hitl_workflow import HITLManager, PendingReview
from agent_system.review_engine.engine import ReviewRuleEngine


class Collection:
    def __init__(self):
        self.rows = {}

    def add(self, documents, embeddings, metadatas, ids):
        for key, doc, meta in zip(ids, documents, metadatas):
            self.rows[key] = (doc, meta)

    def get(self, where, include):
        return {"ids": [key for key, (_, meta) in self.rows.items()
                        if match(meta, where)]}

    def delete(self, ids):
        for key in ids:
            del self.rows[key]

    def query(self, query_embeddings, n_results, where, include):
        rows = [(doc, meta) for doc, meta in self.rows.values() if match(meta, where)]
        rows = rows[:n_results]
        return {"documents": [[doc for doc, _ in rows]],
                "metadatas": [[meta for _, meta in rows]],
                "distances": [[0.1 for _ in rows]]}


def match(meta, clause):
    if "$or" in clause:
        return any(match(meta, item) for item in clause["$or"])
    if "$and" in clause:
        return all(match(meta, item) for item in clause["$and"])
    return all(meta.get(key) == value["$eq"] for key, value in clause.items())


class Chroma:
    def __init__(self):
        self.cols = {name: Collection() for name in
                     (kr.LocalRAGRetriever.COLLECTION, kr.ChromaDBTier2Retriever.COLLECTION)}

    def get_collection(self, name):
        return self.cols[name]


@pytest.fixture
def store(monkeypatch):
    store = Chroma()
    monkeypatch.setattr(kr, "_get_chroma_client", lambda: store)
    monkeypatch.setattr(kr, "embed", lambda *a, **kw: [0.1])
    return store


def test_chroma_ab_shared_legacy_delete_and_rebuild(store):
    a, b = (kr.LocalRAGRetriever(pid) for pid in ("A", "B"))
    shared = kr.LocalRAGRetriever(shared=True)
    for retriever, content in ((a, "A private"), (b, "B private"),
                               (shared, "explicit shared")):
        assert retriever.add_chunk(kr.DatasheetChunk("MPN", 1, content))
    col = store.cols[kr.LocalRAGRetriever.COLLECTION]
    col.rows["legacy"] = ("unowned legacy", {"mpn": "MPN"})
    for retriever, expected in ((a, {"A private", "explicit shared"}),
                                (b, {"B private", "explicit shared"}),
                                (shared, {"explicit shared"})):
        assert {r.content for r in retriever.search("MPN", "query")} == expected
    counts = kr.delete_project_vectors("A")
    assert counts[kr.LocalRAGRetriever.COLLECTION] == 1
    assert "legacy" in col.rows
    assert {r.content for r in b.search("MPN", "query")} == {"B private", "explicit shared"}
    assert a.add_chunk(kr.DatasheetChunk("MPN", 1, "A rebuilt"))
    assert {r.content for r in a.search("MPN", "query")} == {"A rebuilt", "explicit shared"}


def test_tier2_does_not_promote_unowned_records_to_shared(store):
    col = store.cols[kr.ChromaDBTier2Retriever.COLLECTION]
    for key, scope, pid in (("a", "project", "A"), ("b", "project", "B"),
                            ("s", "shared", ""), ("legacy", None, None)):
        col.rows[key] = (key, {"mpn": "MPN", "source": key,
                               "scope": scope, "project_id": pid})
    assert kr.ChromaDBTier2Retriever("A").search("MPN", "query").content.find("[MPN") >= 0
    a = kr.ChromaDBTier2Retriever("A")
    b = kr.ChromaDBTier2Retriever("B")
    assert "a" in a.search("MPN", "query").content
    assert "b" not in a.search("MPN", "query").content
    assert "b" in b.search("MPN", "query").content
    assert "legacy" not in b.search("MPN", "query").content


class Session:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def run(self, cypher, params):
        self.calls.append((cypher, params))
        class Result(list):
            def consume(self):
                pass
        return Result()


def test_vector_search_filters_both_primary_and_fallback(monkeypatch):
    session = Session()
    class Driver:
        def session(self):
            return session
    indexer = Neo4jVectorIndexer(Driver())
    monkeypatch.setattr(indexer, "_check_index", lambda session: True)
    monkeypatch.setattr(indexer, "embed_query", lambda _: [0.1])
    indexer.search("test", project_id="A")
    indexer._fallback_text_search("a'b", project_id="B")
    assert "node.project_id = $project_id" in session.calls[0][0]
    assert "node.scope = 'shared'" in session.calls[0][0]
    assert session.calls[0][1]["project_id"] == "A"
    assert "vc.project_id = $project_id" in session.calls[1][0]
    assert "a'b" not in session.calls[1][0]
    assert session.calls[1][1]["kw0"] == "a'b"


def test_project_graphrag_fails_closed_on_global_and_graph():
    pipeline = GraphRAGPipeline(project_id="A")
    class Local:
        def retrieve(self, query, top_k, project_id=None):
            assert project_id == "A"
            return []
    pipeline._local_retriever = Local()
    for mode in ("graph", "global", "auto", "local"):
        assert pipeline.query("U1234", mode=mode) == []


def test_vector_chunk_ownership_is_persisted(monkeypatch):
    session = Session()
    class Driver:
        def session(self):
            return session
    indexer = Neo4jVectorIndexer(Driver())
    monkeypatch.setattr(indexer, "_check_index", lambda session: True)
    indexer.embed_texts = lambda texts: [[0.1] * indexer.config.embedding_dim for _ in texts]
    indexer.index_chunks([VectorChunk("1", "private", scope="project", project_id="A")])
    assert session.calls[0][1]["records"][0]["project_id"] == "A"
    assert "vc.project_id = r.project_id" in session.calls[0][0]


def test_pending_review_requires_owner_and_scopes_approval():
    session = Session()
    class Driver:
        def session(self):
            return session
    with pytest.raises(ValueError):
        HITLManager().add_pending(PendingReview(review_id="unowned", rule_id="R",
                                                rule_name="R", refdes="C1"))
    a = HITLManager(project_id="A")
    a._driver = Driver()
    assert a.add_pending(PendingReview(review_id="A-1", rule_id="R",
                                       rule_name="R", refdes="C1"))
    assert session.calls[0][1]["scope"] == "project"
    assert session.calls[0][1]["project_id"] == "A"
    a.approve("B-1")
    assert "pr.project_id = $project_id" in session.calls[1][0]
    assert session.calls[1][1]["project_id"] == "A"


def test_selected_project_review_fails_before_unscoped_rule_queries():
    engine = ReviewRuleEngine(neo4j_driver=None, project_id="A")
    with pytest.raises(RuntimeError, match="unscoped"):
        engine.run_rules()


def test_delete_project_never_cleans_other_owners(monkeypatch, store):
    from agent_system.etl_web_bridge import ETLWebExecutor
    from neo4j import GraphDatabase

    class Result:
        def single(self):
            return {"deleted": 2}

    class GraphSession(Session):
        def run(self, cypher, params):
            self.calls.append((cypher, params))
            return Result()

    session = GraphSession()
    class Driver:
        def session(self):
            return session
        def close(self):
            pass
    monkeypatch.setattr(GraphDatabase, "driver", lambda *args, **kwargs: Driver())
    col = store.cols[kr.LocalRAGRetriever.COLLECTION]
    for pid in ("A", "B"):
        col.rows[pid] = (pid, {"scope": "project", "project_id": pid})
    col.rows["shared"] = ("shared", {"scope": "shared", "project_id": ""})
    executor = ETLWebExecutor()
    with pytest.raises(ValueError):
        executor.delete_project("")
    assert executor.delete_project("A")["deleted_vectors"][kr.LocalRAGRetriever.COLLECTION] == 1
    assert set(col.rows) == {"B", "shared"}
    assert all(params["pid"] == "A" for _, params in session.calls)
    assert "n.project_id = $pid" in session.calls[0][0]
