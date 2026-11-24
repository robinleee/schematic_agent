"""Task11 offline adapter contract; no HTTP service is contacted."""
from unittest.mock import Mock

import pytest
import requests

from agent_system.knowledge_router import InternalPLMRetriever, KnowledgeRouter, RetrievalResult
from agent_system.tier3_retriever import Tier3Retriever


FIELDS = {"mpn": "part", "content": "text", "scope": "visibility",
          "project_id": "owner", "source": "origin"}


def adapter(session, project="A", **kwargs):
    return InternalPLMRetriever(
        project, endpoint="https://plm.example.test/lookup", token="test-token",
        fields=FIELDS, session=session, **kwargs,
    )


def response(status=200, **changes):
    record = {"part": "TPS5430", "text": "Public spec", "visibility": "project",
              "owner": "A", "origin": "datasheet"}
    record.update(changes)
    res = Mock(status_code=status, content=b'{"record":1}')
    res.json.return_value = record
    return res


def test_plm_hit_cache_and_project_isolation():
    session = Mock()
    session.get.return_value = response()
    a = adapter(session)
    result = a.search("TPS5430", "PRIVATE_NET")
    assert result.status == "success" and result.source == "plm:datasheet"
    assert result.retrieved_at and result.confidence == 0.8
    assert a.search("TPS5430").cached
    session.get.assert_called_once()
    assert session.get.call_args.kwargs["params"] == {"mpn": "TPS5430"}
    assert session.get.call_args.kwargs["timeout"] <= 5
    assert session.get.call_args.kwargs["allow_redirects"] is False
    assert adapter(session, project="B").search("TPS5430") is None
    assert session.get.call_count == 2


def test_plm_miss_and_denied_are_not_cached():
    session = Mock()
    session.get.side_effect = [response(404), response(owner="B"),
                               response(visibility="legacy"), response()]
    a = adapter(session)
    for reason in ("plm_not_found", "plm_forbidden", "plm_forbidden"):
        assert a.search("TPS5430") is None
        assert a.last_reason == reason
    assert a.search("TPS5430").status == "success"
    assert session.get.call_count == 4


@pytest.mark.parametrize("effect,reason,calls", [
    (requests.Timeout(), "plm_timeout", 2),
    (requests.ConnectionError(), "plm_unavailable", 2),
    (None, "plm_unauthorized", 1),
])
def test_plm_failures(effect, reason, calls):
    session = Mock()
    session.get.side_effect = effect if effect else None
    if effect is None:
        session.get.return_value = response(401)
    a = adapter(session)
    assert a.search("TPS5430") is None
    assert a.last_reason == reason
    assert session.get.call_count == calls


def test_plm_parse_and_configuration_fail_closed():
    session = Mock()
    session.get.return_value = response(text=None)
    a = adapter(session)
    assert a.search("TPS5430") is None and a.last_reason == "plm_parse_error"
    disabled = InternalPLMRetriever("A", endpoint="", token="", fields=FIELDS,
                                    session=session)
    assert disabled.search("TPS5430") is None
    assert disabled.last_reason == "plm_unconfigured"
    assert session.get.call_count == 1


def test_router_degrades_to_public_and_sends_only_mpn():
    router = KnowledgeRouter(project_id="A")
    router._graphrag = Mock(query=Mock(return_value=[]))
    router.tier1.search = Mock(return_value=[])
    router.tier1.add_chunk = Mock(return_value=True)
    router.tier2.search = Mock(return_value=None)
    router.plm = adapter(Mock(get=Mock(side_effect=requests.Timeout())))
    router.tier3 = Mock(enabled=True, search=Mock(return_value=RetrievalResult(
        status="success", tier="tier_3_public", mpn="TPS5430",
        content="spec", source="tier3:TI", confidence=0.7)))
    result = router.search("TPS5430", "PRIVATE_NET secret context")
    assert result.status == "success"
    assert result.reason == "plm_timeout"
    router.tier3.search.assert_called_once_with("TPS5430", "")
    router.tier1.add_chunk.assert_called_once()
    invalid = router.search("TPS5430 PRIVATE_NET", "context")
    assert invalid.status == "degraded" and invalid.reason == "invalid_mpn"
    assert router.tier3.search.call_count == 1


def test_tier3_disabled_no_network_and_invalid_mpn():
    retriever = Tier3Retriever()
    retriever.enabled = False
    retriever._scraper = Mock()
    assert retriever.search("TPS5430", "secret") is None
    assert retriever.last_reason == "tier3_disabled"
    retriever.enabled = True
    assert retriever.search("https://private/secret", "anything") is None
    assert retriever.last_reason == "invalid_mpn"
    retriever._scraper.scrape_html.assert_not_called()


def test_router_reports_disabled_and_unavailable_without_private_cache():
    router = KnowledgeRouter(project_id="A")
    router._graphrag = Mock(query=Mock(return_value=[]))
    router.tier1.search = Mock(return_value=[])
    router.tier1.add_chunk = Mock()
    router.tier2.search = Mock(return_value=None)
    router.plm = adapter(Mock(get=Mock(side_effect=requests.ConnectionError())))
    router.tier3 = Mock(enabled=False, search=Mock(return_value=None),
                        last_reason="tier3_disabled")
    result = router.search("TPS5430", "PRIVATE_NET")
    assert result.status == "degraded"
    assert result.reason == "tier3_disabled"
    assert result.source and result.retrieved_at and result.confidence == 0
    router.tier1.add_chunk.assert_not_called()
    router.tier3.enabled = True
    router.tier3.last_reason = "tier3_unavailable"
    result = router.search("TPS5430", "PRIVATE_NET")
    assert result.status == "degraded" and result.reason == "tier3_unavailable"
    router.tier3.search.assert_called_with("TPS5430", "")
