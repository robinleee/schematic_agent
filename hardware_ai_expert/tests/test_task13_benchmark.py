"""Task 13 benchmark contract tests: never contact live services."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "benchmark_task13.py"
spec = importlib.util.spec_from_file_location("task13_benchmark", SCRIPT)
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def test_percentile_interpolation_and_empty():
    assert benchmark.percentile([], 95) is None
    assert benchmark.percentile([7], 95) == 7
    assert benchmark.percentile([40, 10, 30, 20], 50) == 25
    assert benchmark.percentile([10, 20, 30, 40], 95) == pytest.approx(38.5)


def test_schema_offline_is_explicitly_unavailable():
    report = benchmark.run(SimpleNamespace(live=False, project_id=None, repeats=5))
    assert report["schema_version"] == 1
    assert report["mode"] == "offline-preflight"
    assert set(report["results"]) == set(benchmark.SCENARIOS)
    for row in report["results"].values():
        assert row["status"] == "unavailable"
        assert row["reason"]
        assert row["samples"] == 0
        assert row["p50_ms"] is None and row["p95_ms"] is None
        assert row["token_count"] is None and row["tool_call_count"] is None
        assert row["first_response_p50_ms"] is None


def test_measure_real_calls_and_first_response():
    calls = []

    def operation():
        calls.append(1)
        return 1.25, None, 2

    row = benchmark.measure(operation, repeats=3)
    assert row["status"] == "ok"
    assert row["samples"] == len(calls) == 3
    assert row["first_response_p50_ms"] == 1.25
    assert row["token_count"] is None
    assert row["tool_call_count"] == 6
    assert row["p50_ms"] is not None and row["p95_ms"] is not None
    assert row["total_ms"] >= 0


def test_error_never_reports_partial_fake_metrics():
    def broken():
        raise RuntimeError("offline")

    row = benchmark.measure(broken)
    assert row["status"] == "degraded"
    assert row["samples"] == 0
    assert row["p50_ms"] is None


def test_review_benchmark_uses_project_scope_and_restricted_rules(monkeypatch):
    calls = []

    class FakeEngine:
        def __init__(self, driver, project_id):
            calls.append(("init", driver, project_id))

        def list_rules(self, enabled_only=True):
            assert enabled_only
            return [SimpleNamespace(id="POWER_NET_ORPHAN")]

        def run_rules(self, **kwargs):
            calls.append(("run", kwargs))
            return []

    monkeypatch.setattr(benchmark, "build_review_engine",
                        lambda driver, project_id: FakeEngine(driver, project_id))
    args = SimpleNamespace(
        project_id="isolated-project",
        repeats=2,
        review_rule_ids=["POWER_NET_ORPHAN"],
    )

    row = benchmark.run_review_benchmark(object(), args)

    assert row["status"] == "ok"
    assert row["samples"] == 2
    assert calls[0][0] == "init" and calls[0][2] == "isolated-project"
    assert calls[1:] == [
        ("run", {"rule_ids": ["POWER_NET_ORPHAN"], "enabled_only": True}),
        ("run", {"rule_ids": ["POWER_NET_ORPHAN"], "enabled_only": True}),
    ]


def test_read_only_driver_forces_read_access():
    class FakeDriver:
        def session(self, **kwargs):
            return kwargs

    driver = benchmark.ReadOnlyDriver(FakeDriver(), "READ")
    assert driver.session(default_access_mode="WRITE") == {"default_access_mode": "READ"}


def test_review_benchmark_infrastructure_failure_is_degraded(monkeypatch):
    class BrokenEngine:
        def list_rules(self, enabled_only=True):
            return [SimpleNamespace(id="POWER_NET_ORPHAN")]

        def run_rules(self, **kwargs):
            raise RuntimeError("graph unavailable")

    monkeypatch.setattr(benchmark, "build_review_engine",
                        lambda driver, project_id: BrokenEngine())
    args = SimpleNamespace(
        project_id="isolated-project",
        repeats=1,
        review_rule_ids=["POWER_NET_ORPHAN"],
    )

    row = benchmark.run_review_benchmark(object(), args)

    assert row["status"] == "degraded"
    assert row["samples"] == 0
    assert "graph unavailable" in row["reason"]


@pytest.mark.parametrize("rule_ids", [["missing"], ["POWER_NET_ORPHAN"] * 4])
def test_review_benchmark_rejects_unknown_or_large_rule_selection(monkeypatch, rule_ids):
    class FakeEngine:
        def list_rules(self, enabled_only=True):
            return [SimpleNamespace(id="POWER_NET_ORPHAN")]

        def run_rules(self, **kwargs):
            pytest.fail("invalid selection must not execute")

    monkeypatch.setattr(benchmark, "build_review_engine",
                        lambda driver, project_id: FakeEngine())
    with pytest.raises(ValueError, match="1-3 enabled"):
        benchmark.run_review_benchmark(
            object(), SimpleNamespace(project_id="isolated", repeats=1, review_rule_ids=rule_ids))


@pytest.mark.parametrize("review_failure", [False, True])
def test_live_review_uses_read_only_driver_and_degrades_on_setup_failure(
    monkeypatch, review_failure,
):
    class Session:
        def __init__(self, mode):
            assert mode == "READ"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def run(self, query, **params):
            assert params["pid"] == "isolated"
            return SimpleNamespace(single=lambda: {"n": 1})

    class Driver:
        def verify_connectivity(self):
            pass

        def session(self, *, default_access_mode):
            return Session(default_access_mode)

        def close(self):
            pass

    driver = Driver()
    monkeypatch.setitem(sys.modules, "neo4j", SimpleNamespace(
        GraphDatabase=SimpleNamespace(driver=lambda *args, **kwargs: driver),
        READ_ACCESS="READ"))
    monkeypatch.setenv("NEO4J_PASSWORD", "test-only")
    monkeypatch.setattr(benchmark, "port_open", lambda *args: True)
    monkeypatch.setitem(sys.modules, "agent_system.graph_rag.pipeline",
                        SimpleNamespace(GraphRAGPipeline=lambda **kwargs: None))

    def review_run(scoped_driver, args):
        assert scoped_driver.driver is driver
        assert scoped_driver.session()  # read access is mandatory even for review
        assert args.project_id == "isolated"
        if review_failure:
            raise RuntimeError("review infrastructure down")
        return benchmark.measure(lambda: (None, None, None), args.repeats)

    monkeypatch.setattr(benchmark, "run_review_benchmark", review_run)
    report = benchmark.run(SimpleNamespace(
        live=True, project_id="isolated", repeats=1, review_rule_ids=None,
        graphrag=False, api_url=None))
    review = report["results"]["review"]
    assert review["status"] == ("degraded" if review_failure else "ok")
    assert review["samples"] == (0 if review_failure else 1)
    if review_failure:
        assert "review infrastructure down" in review["reason"]


def test_live_requires_isolated_project():
    with pytest.raises(ValueError, match="non-default"):
        benchmark.run(SimpleNamespace(live=True, project_id="default", repeats=5))


def test_only_loopback_api_is_allowed():
    with pytest.raises(ValueError, match="loopback"):
        benchmark.local_url("https://example.com")
    assert benchmark.local_url("http://127.0.0.1:8501").port == 8501
