#!/usr/bin/env python3
"""Task 13: read-only, opt-in local-service latency baseline (no simulated services).

Run: .venv/bin/python scripts/benchmark_task13.py [--live --project-id ISOLATED_ID]
Optionally add --api-url http://127.0.0.1:8501. JSON is printed to stdout;
--output writes the same JSON to a caller-chosen path. Never indexes or writes DB data.
Agent/chat are intentionally blocked: their tools cannot be certified read-only.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hardware_ai_expert"))

SCENARIOS = ("graph_tools", "graph_query", "review", "graphrag", "api", "agent",
             "websocket_chat", "websocket_ping", "graph_10_concurrent")
DEFAULT_REVIEW_RULE_IDS = ("POWER_NET_ORPHAN",)


def percentile(values, percent):
    """Linear interpolation between adjacent ordered observations."""
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percent / 100
    low = int(rank)
    return ordered[low] + (ordered[min(low + 1, len(ordered) - 1)] - ordered[low]) * (rank - low)


def unavailable(reason, status="unavailable"):
    return dict(status=status, reason=reason, samples=0, p50_ms=None, p95_ms=None,
                first_response_p50_ms=None, first_response_p95_ms=None,
                total_ms=None, token_count=None, tool_call_count=None, concurrency=None)


def measure(fn, repeats=5, concurrency=1):
    """Record completed calls only; error samples never enter latency statistics."""
    started = time.perf_counter()

    def one(_):
        begin = time.perf_counter()
        first, tokens, tools = fn()
        return (time.perf_counter() - begin) * 1000, first, tokens, tools

    try:
        if concurrency == 1:
            observations = [one(i) for i in range(repeats)]
        else:
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                observations = list(pool.map(one, range(repeats)))
    except Exception as exc:
        return unavailable(f"{type(exc).__name__}: {exc}", "degraded")
    durations = [row[0] for row in observations]
    firsts = [row[1] for row in observations if row[1] is not None]
    tokens = [row[2] for row in observations]
    tools = [row[3] for row in observations]
    return dict(status="ok", reason=None, samples=len(durations),
                p50_ms=percentile(durations, 50), p95_ms=percentile(durations, 95),
                first_response_p50_ms=percentile(firsts, 50),
                first_response_p95_ms=percentile(firsts, 95),
                total_ms=(time.perf_counter() - started) * 1000,
                token_count=sum(tokens) if all(t is not None for t in tokens) else None,
                tool_call_count=sum(tools) if all(t is not None for t in tools) else None,
                concurrency=concurrency)


def local_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("API URL must use a loopback host")
    return parsed


def port_open(host, port):
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def build_review_engine(driver, project_id):
    """Build the project-scoped review engine lazily for live benchmarks."""
    from agent_system.review_engine import ReviewRuleEngine

    return ReviewRuleEngine(driver, project_id=project_id)


class ReadOnlyDriver:
    """Force every Review session to use Neo4j's read access mode."""

    def __init__(self, driver, access_mode):
        self.driver = driver
        self.access_mode = access_mode

    def session(self, *args, **kwargs):
        return self.driver.session(*args, **{**kwargs, "default_access_mode": self.access_mode})


def run_review_benchmark(driver, args):
    """Benchmark a deliberately small, project-scoped, read-only review."""
    rule_ids = getattr(args, "review_rule_ids", None) or DEFAULT_REVIEW_RULE_IDS
    engine = build_review_engine(driver, project_id=args.project_id)
    configured = {rule.id for rule in engine.list_rules(enabled_only=True)}
    if not rule_ids or len(rule_ids) > 3 or any(rid not in configured for rid in rule_ids):
        raise ValueError("select 1-3 enabled review rule IDs from the configured rules")

    def review_read():
        # ReviewRuleEngine scopes every template query to project_id and rejects
        # write clauses.  Keep the benchmark narrow by default; callers can
        # opt into another explicitly selected rule with --review-rule-id.
        engine.run_rules(rule_ids=list(rule_ids), enabled_only=True)
        return None, None, None

    return measure(review_read, args.repeats)


def run(args):
    results = {name: unavailable("requires --live and isolated --project-id") for name in SCENARIOS}
    results["agent"] = unavailable("Agent may call mutating tools; live execution not read-only safe")
    results["websocket_chat"] = unavailable("WebSocket chat runs the same potentially mutating Agent")
    report = dict(schema_version=1, captured_at=datetime.now(timezone.utc).isoformat(),
                  mode="live-read-only" if args.live else "offline-preflight",
                  project_id=args.project_id, repeats=args.repeats,
                  targets={"graph_tools": "application graph tools (not run without scoped read-only guarantees)",
                           "graph_query": "MATCH (Component) scoped count, read transaction",
                           "review": f"project-scoped read-only run_rules "
                                     f"({', '.join(getattr(args, 'review_rule_ids', None) or DEFAULT_REVIEW_RULE_IDS)})",
                           "graphrag": "project-scoped local query",
                           "api": "GET /api/v1/health",
                           "agent": "POST /api/v1/chat (blocked)",
                           "websocket_chat": "/ws/chat chat (blocked)",
                           "websocket_ping": "/ws/chat ping/pong (transport only)",
                           "graph_10_concurrent": "10 simultaneous scoped read transactions"},
                  results=results)
    if not args.live:
        return report
    if not args.project_id or args.project_id == "default":
        raise ValueError("--live requires a non-default, isolated --project-id")
    results["api"] = unavailable("pass --api-url for local API preflight")
    results["websocket_ping"] = unavailable("pass --api-url for local WebSocket preflight")

    # Explicit credentials; never use application defaults or mutate the selected project.
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    parsed = urlparse(uri)
    if parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("Neo4j must be on loopback")
    if not os.getenv("NEO4J_PASSWORD"):
        reason = "NEO4J_PASSWORD not configured"
    elif not port_open(parsed.hostname, parsed.port or 7687):
        reason = "Neo4j port unreachable"
    else:
        try:
            from neo4j import GraphDatabase
            from neo4j import READ_ACCESS
            driver = GraphDatabase.driver(uri, auth=(os.getenv("NEO4J_USER", "neo4j"),
                                                       os.environ["NEO4J_PASSWORD"]),
                                          connection_timeout=2)
            driver.verify_connectivity()

            def graph_read():
                with driver.session(default_access_mode=READ_ACCESS) as session:
                    row = session.run(
                        "MATCH (c:Component {project_id: $pid}) RETURN count(c) AS n",
                        pid=args.project_id).single()
                    if row is None or row["n"] < 1:
                        raise RuntimeError("isolated project has no Component fixture")
                return None, None, 0

            results["graph_query"] = measure(graph_read, args.repeats)
            results["graph_tools"] = unavailable(
                "graph tools use global project selection and default-access sessions; "
                "cannot enforce read-only scoped access", "degraded")
            barrier = threading.Barrier(10, timeout=5)

            def concurrent_read():
                barrier.wait()
                return graph_read()

            results["graph_10_concurrent"] = measure(concurrent_read, 10, 10)
            try:
                results["review"] = run_review_benchmark(
                    ReadOnlyDriver(driver, READ_ACCESS), args)
            except Exception as exc:
                # Missing review dependencies and graph infrastructure failures
                # must not look like a clean zero-violation benchmark.
                results["review"] = unavailable(
                    f"{type(exc).__name__}: {exc}", "degraded")
            try:
                from agent_system.graph_rag.pipeline import GraphRAGPipeline
                pipeline = GraphRAGPipeline(driver=driver, project_id=args.project_id)

                def rag_read():
                    matches = pipeline.query("decoupling capacitor", mode="local", top_k=5)
                    if not matches:
                        raise RuntimeError("no retrieval results for isolated project")
                    return None, None, None

                # Embedding may load/download a model; only run when explicitly enabled.
                if args.graphrag:
                    results["graphrag"] = measure(rag_read, args.repeats)
                else:
                    results["graphrag"] = unavailable(
                        "pass --graphrag to opt in to local embedding/model loading")
            except Exception as exc:
                results["graphrag"] = unavailable(f"{type(exc).__name__}: {exc}", "degraded")
            driver.close()
            reason = None
        except Exception as exc:
            reason = f"Neo4j unavailable: {type(exc).__name__}: {exc}"
    if reason:
        for name in ("graph_tools", "graph_query", "graph_10_concurrent", "review", "graphrag"):
            results[name] = unavailable(reason, "degraded")

    if args.api_url:
        parsed = local_url(args.api_url)
        if not port_open(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)):
            reason = "API port unreachable"
            results["api"] = unavailable(reason, "degraded")
            results["websocket_ping"] = unavailable(reason, "degraded")
        else:
            import httpx

            def api_read():
                response = httpx.get(args.api_url.rstrip("/") + "/api/v1/health", timeout=5)
                response.raise_for_status()
                return None, None, None

            results["api"] = measure(api_read, args.repeats)
            try:
                from websockets.sync.client import connect
                ws_url = args.api_url.replace("http://", "ws://").replace("https://", "wss://").rstrip("/") + "/ws/chat"

                def ws_ping():
                    start = time.perf_counter()
                    with connect(ws_url, open_timeout=5, close_timeout=2) as ws:
                        ws.send(json.dumps({"type": "ping"}))
                        message = json.loads(ws.recv(timeout=5))
                        if message.get("type") != "pong":
                            raise RuntimeError("expected pong")
                        first = (time.perf_counter() - start) * 1000
                    return first, None, None

                results["websocket_ping"] = measure(ws_ping, args.repeats)
            except ImportError:
                results["websocket_ping"] = unavailable("websockets.sync not installed")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="opt in to local read-only service calls")
    parser.add_argument("--project-id", help="isolated non-default test project")
    parser.add_argument("--api-url", help="local FastAPI base URL (optional)")
    parser.add_argument("--graphrag", action="store_true", help="opt in to model-backed local retrieval")
    parser.add_argument(
        "--review-rule-id",
        dest="review_rule_ids",
        action="append",
        help=("enabled project-scoped review rule to benchmark; may be repeated (max 3) "
              f"(default: {DEFAULT_REVIEW_RULE_IDS[0]})"),
    )
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.repeats < 1 or args.repeats > 100:
        parser.error("--repeats must be between 1 and 100")
    try:
        report = run(args)
    except ValueError as exc:
        parser.error(str(exc))
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
