#!/usr/bin/env python3
"""Offline, isolated cosine retrieval benchmark. Never connects to production indexes."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import resource
import statistics
import time
from pathlib import Path

GOLDEN = Path(__file__).with_name("graphrag_golden.json")


def score_ranking(ranked: list[str], relevance: dict[str, int]) -> dict[str, float]:
    """Recall divides by all relevant sources; NDCG uses graded relevance."""
    if not relevance or any(v <= 0 for v in relevance.values()):
        raise ValueError("expected positive relevance grades")
    def dcg(grades):
        return sum((2 ** grade - 1) / math.log2(rank + 2)
                   for rank, grade in enumerate(grades))
    top = ranked[:10]
    first = {}
    for rank, source in enumerate(top, 1):
        first.setdefault(source, rank)
    ideal = dcg(sorted(relevance.values(), reverse=True)[:10])
    return {
        "recall@5": len(set(top[:5]) & relevance.keys()) / len(relevance),
        "recall@10": len(set(top) & relevance.keys()) / len(relevance),
        "mrr": max((1 / rank for source, rank in first.items()
                    if source in relevance), default=0.0),
        "ndcg@10": dcg([relevance.get(source, 0) if first[source] == rank else 0
                        for rank, source in enumerate(top, 1)]) / ideal,
    }


def load_golden(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    docs = data["documents"]
    if not docs or len({d["source"] for d in docs}) != len(docs):
        raise ValueError("document sources must be unique")
    sources = {d["source"] for d in docs}
    if not data["queries"] or len({q["id"] for q in data["queries"]}) != len(data["queries"]):
        raise ValueError("query ids must be unique")
    for query in data["queries"]:
        if not query["answer"] or not query["relevance"] or not set(query["relevance"]) <= sources:
            raise ValueError("golden answer and source relevance are required")
        score_ranking([], query["relevance"])
    return data


def benchmark(model_path: str, golden: Path = GOLDEN) -> dict:
    # Caller must supply a local directory. No model name / remote resolution.
    path = Path(model_path).resolve()
    if not path.is_dir() or not (path / "config.json").is_file():
        raise FileNotFoundError(f"local model snapshot with config.json unavailable: {path}")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    from sentence_transformers import SentenceTransformer

    data = load_golden(golden)
    digest = hashlib.sha256(golden.read_bytes()).hexdigest()
    started = time.perf_counter()
    model = SentenceTransformer(str(path), local_files_only=True)
    load_ms = (time.perf_counter() - started) * 1000
    texts = [d["text"] for d in data["documents"]]
    started = time.perf_counter()
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    index_ms = (time.perf_counter() - started) * 1000
    dim = int(model.get_sentence_embedding_dimension())
    if any(len(v) != dim or not all(math.isfinite(float(x)) for x in v)
           or not any(v) for v in vectors):
        raise ValueError("invalid document embedding")
    details = []
    for q in data["queries"]:
        started = time.perf_counter()
        vector = model.encode([q["query"]], normalize_embeddings=True,
                              show_progress_bar=False)[0]
        if len(vector) != dim or not all(math.isfinite(float(x)) for x in vector) or not any(vector):
            raise ValueError("invalid query embedding")
        ranked = sorted(zip((d["source"] for d in data["documents"]), vectors),
                        key=lambda row: (-float(row[1] @ vector), row[0]))
        latency_ms = (time.perf_counter() - started) * 1000
        sources = [row[0] for row in ranked[:10]]
        details.append({"id": q["id"], "sources": sources, "latency_ms": latency_ms,
                        "metrics": score_ranking(sources, q["relevance"])})
    keys = ("recall@5", "recall@10", "mrr", "ndcg@10")
    return {
        "model": str(path), "dimension": dim, "golden_sha256": digest,
        "documents": len(texts), "queries": len(details), "load_ms": load_ms,
        "index_ms": index_ms, "latency_p50_ms": statistics.median(d["latency_ms"] for d in details),
        "latency_p95_ms": sorted(d["latency_ms"] for d in details)[
            math.ceil(len(details) * .95) - 1],
        "peak_rss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "metrics": {k: statistics.mean(d["metrics"][k] for d in details) for k in keys},
        "details": details,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", action="append", required=True,
                        help="Local sentence-transformers directory; repeat for comparison")
    parser.add_argument("--golden", type=Path, default=GOLDEN)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    reports = []
    for name in args.model:
        try:
            reports.append(benchmark(name, args.golden))
        except (FileNotFoundError, ImportError, OSError, ValueError) as exc:
            reports.append({"model": name, "status": "blocked", "reason": str(exc)})
    output = {"mode": "offline-isolated", "reports": reports}
    text = json.dumps(output, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if all("metrics" in r for r in reports) else 2


if __name__ == "__main__":
    raise SystemExit(main())
