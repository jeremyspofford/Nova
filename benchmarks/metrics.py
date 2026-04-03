"""Metric computation for memory retrieval benchmarks.

Precision@K and MRR are the core metrics. Both use a relevance threshold
to separate "relevant" from "not relevant" based on the 0-3 judge scores.
"""

from __future__ import annotations

from collections import defaultdict


def precision_at_k(scores: list[float], k: int = 5, threshold: float = 2.0) -> float:
    """Fraction of top-K results that are relevant (score >= threshold).

    If fewer than k results, denominator is still k — this penalizes
    providers that return sparse results.
    """
    top_k = scores[:k]
    relevant = sum(1 for s in top_k if s >= threshold)
    return relevant / k


def mrr(scores: list[float], threshold: float = 2.0) -> float:
    """Mean Reciprocal Rank: 1/rank of the first relevant result.

    Returns 0.0 if no result meets the relevance threshold.
    """
    for i, s in enumerate(scores):
        if s >= threshold:
            return 1.0 / (i + 1)
    return 0.0


def compute_summary(results: list[dict], top_k: int = 5, threshold: float = 2.0) -> dict:
    """Aggregate metrics across all test case results for a single provider.

    Args:
        results: List of per-case result dicts, each with keys:
            provider, query, query_type, scores, latency_ms, tokens_used.
        top_k: K value for precision@K.
        threshold: Relevance score threshold.

    Returns:
        Summary dict with precision_at_5, mrr, avg_latency_ms, total_tokens,
        and by_query_type breakdowns.
    """
    if not results:
        return {
            "precision_at_5": 0.0,
            "mrr": 0.0,
            "avg_latency_ms": 0.0,
            "total_tokens": 0,
            "by_query_type": {},
        }

    p_at_k_values: list[float] = []
    mrr_values: list[float] = []
    latencies: list[float] = []
    total_tokens = 0

    by_type: dict[str, dict[str, list]] = defaultdict(lambda: {
        "p_at_k": [],
        "mrr": [],
        "latencies": [],
    })

    for r in results:
        scores = r.get("scores", [])
        qt = r.get("query_type", "unknown")
        lat = r.get("latency_ms", 0)
        tokens = r.get("tokens_used", 0)

        p = precision_at_k(scores, k=top_k, threshold=threshold)
        m = mrr(scores, threshold=threshold)

        p_at_k_values.append(p)
        mrr_values.append(m)
        latencies.append(lat)
        total_tokens += tokens

        by_type[qt]["p_at_k"].append(p)
        by_type[qt]["mrr"].append(m)
        by_type[qt]["latencies"].append(lat)

    by_query_type = {}
    for qt, data in sorted(by_type.items()):
        by_query_type[qt] = {
            "precision_at_5": round(_mean(data["p_at_k"]), 4),
            "mrr": round(_mean(data["mrr"]), 4),
            "avg_latency_ms": round(_mean(data["latencies"]), 1),
            "n": len(data["p_at_k"]),
        }

    return {
        "precision_at_5": round(_mean(p_at_k_values), 4),
        "mrr": round(_mean(mrr_values), 4),
        "avg_latency_ms": round(_mean(latencies), 1),
        "total_tokens": total_tokens,
        "by_query_type": by_query_type,
    }


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)
