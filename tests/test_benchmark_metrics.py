"""Unit tests for benchmark metric computation.

These test pure math — no services needed. Wrong metrics = wrong conclusions
about the memory architecture, so these are the highest-priority tests.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add benchmarks/ to path so we can import directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmarks.metrics import compute_summary, mrr, precision_at_k


# ── precision@5 ─────────────────────────────────────────────────────────────


class TestPrecisionAtK:
    def test_all_relevant(self):
        """All 5 results are relevant (score >= 2.0)."""
        scores = [3.0, 3.0, 2.0, 2.0, 3.0]
        assert precision_at_k(scores, k=5) == 1.0

    def test_none_relevant(self):
        """No results meet the threshold."""
        scores = [1.0, 0.0, 1.0, 0.0, 1.0]
        assert precision_at_k(scores, k=5) == 0.0

    def test_partial_relevant(self):
        """3 of 5 results are relevant."""
        scores = [3.0, 2.0, 1.0, 2.0, 0.0]
        assert precision_at_k(scores, k=5) == 0.6

    def test_fewer_than_k_results(self):
        """Only 2 results returned, but k=5. Denominator is still 5."""
        scores = [3.0, 3.0]
        assert precision_at_k(scores, k=5) == 0.4

    def test_empty_results(self):
        """No results at all."""
        scores = []
        assert precision_at_k(scores, k=5) == 0.0

    def test_custom_threshold(self):
        """Using a lower threshold (1.0) makes more results count as relevant."""
        scores = [1.0, 1.5, 0.5, 2.0, 3.0]
        assert precision_at_k(scores, k=5, threshold=1.0) == 0.8

    def test_exactly_at_threshold(self):
        """Score exactly at threshold counts as relevant."""
        scores = [2.0, 2.0, 2.0, 2.0, 2.0]
        assert precision_at_k(scores, k=5, threshold=2.0) == 1.0

    def test_k_equals_1(self):
        """precision@1: only the first result matters."""
        scores = [3.0, 0.0, 0.0]
        assert precision_at_k(scores, k=1) == 1.0


# ── MRR ──────────────────────────────────────────────────────────────────────


class TestMRR:
    def test_first_result_relevant(self):
        """Best case: first result is relevant."""
        scores = [3.0, 1.0, 0.0]
        assert mrr(scores) == 1.0

    def test_second_result_relevant(self):
        """First result irrelevant, second is relevant."""
        scores = [1.0, 3.0, 0.0]
        assert mrr(scores) == 0.5

    def test_third_result_relevant(self):
        scores = [0.0, 1.0, 2.0]
        assert mrr(scores) == pytest.approx(1 / 3)

    def test_no_relevant_results(self):
        scores = [0.0, 1.0, 1.0]
        assert mrr(scores) == 0.0

    def test_empty_results(self):
        scores = []
        assert mrr(scores) == 0.0

    def test_custom_threshold(self):
        """With threshold=1.0, the first result (1.5) is relevant."""
        scores = [1.5, 0.0, 3.0]
        assert mrr(scores, threshold=1.0) == 1.0

    def test_all_relevant(self):
        """All relevant: MRR is 1.0 (first result counts)."""
        scores = [3.0, 3.0, 3.0]
        assert mrr(scores) == 1.0


# ── compute_summary ──────────────────────────────────────────────────────────


class TestComputeSummary:
    def test_empty_results(self):
        summary = compute_summary([])
        assert summary["precision_at_5"] == 0.0
        assert summary["mrr"] == 0.0
        assert summary["avg_latency_ms"] == 0.0
        assert summary["total_tokens"] == 0
        assert summary["by_query_type"] == {}

    def test_single_result(self):
        results = [{
            "provider": "test",
            "query": "q1",
            "query_type": "factual",
            "scores": [3.0, 2.0, 1.0, 0.0, 0.0],
            "latency_ms": 100,
            "tokens_used": 50,
        }]
        summary = compute_summary(results)
        assert summary["precision_at_5"] == 0.4
        assert summary["mrr"] == 1.0
        assert summary["avg_latency_ms"] == 100.0
        assert summary["total_tokens"] == 50
        assert "factual" in summary["by_query_type"]

    def test_multiple_query_types(self):
        results = [
            {"query_type": "factual", "scores": [3.0, 3.0, 3.0, 3.0, 3.0], "latency_ms": 100, "tokens_used": 10},
            {"query_type": "preference", "scores": [0.0, 0.0, 0.0, 0.0, 0.0], "latency_ms": 200, "tokens_used": 20},
        ]
        summary = compute_summary(results)
        assert summary["by_query_type"]["factual"]["precision_at_5"] == 1.0
        assert summary["by_query_type"]["preference"]["precision_at_5"] == 0.0
        # Overall is the average
        assert summary["precision_at_5"] == 0.5
        assert summary["total_tokens"] == 30
        assert summary["avg_latency_ms"] == 150.0

    def test_missing_fields_default_gracefully(self):
        """Results with missing optional fields don't crash."""
        results = [{"query_type": "factual"}]
        summary = compute_summary(results)
        assert summary["precision_at_5"] == 0.0
        assert summary["mrr"] == 0.0
