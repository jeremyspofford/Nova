"""Tests for hybrid search RRF fusion."""
from __future__ import annotations

import pytest

from app.retrieval import RawResult, _reciprocal_rank_fusion, RRF_K


def _raw(id: str, rank: int, source: str) -> RawResult:
    return RawResult(
        id=id, content=f"content-{id}", metadata={}, created_at=None,
        rank=rank, source=source,
    )


def test_rrf_basic_fusion():
    """Documents appearing in both vector and keyword results get boosted."""
    results = [
        _raw("a", rank=1, source="vector"),
        _raw("b", rank=2, source="vector"),
        _raw("c", rank=3, source="vector"),
        _raw("a", rank=2, source="keyword"),   # 'a' appears in both
        _raw("d", rank=1, source="keyword"),
        _raw("c", rank=3, source="keyword"),   # 'c' appears in both
    ]
    fused = _reciprocal_rank_fusion(results, limit=3, vector_weight=1.0, keyword_weight=1.0)

    # 'a' should rank highest: vector rank 1 + keyword rank 2
    assert fused[0].id == "a"
    assert fused[0].vector_rank == 1
    assert fused[0].keyword_rank == 2

    # Verify score calculation for 'a'
    expected_score = 1.0 / (RRF_K + 1) + 1.0 / (RRF_K + 2)
    assert abs(fused[0].score - expected_score) < 1e-10


def test_rrf_respects_limit():
    """Only top N results are returned."""
    results = [_raw(str(i), rank=i, source="vector") for i in range(10)]
    fused = _reciprocal_rank_fusion(results, limit=3, vector_weight=1.0, keyword_weight=1.0)
    assert len(fused) == 3


def test_rrf_weight_bias():
    """Higher vector weight boosts vector-only results over keyword-only."""
    results = [
        _raw("vec-only", rank=1, source="vector"),
        _raw("kw-only", rank=1, source="keyword"),
    ]
    fused = _reciprocal_rank_fusion(results, limit=2, vector_weight=2.0, keyword_weight=1.0)

    # With 2x vector weight, vec-only should rank first
    assert fused[0].id == "vec-only"
    assert fused[1].id == "kw-only"


def test_rrf_empty_results():
    """Empty input returns empty output."""
    fused = _reciprocal_rank_fusion([], limit=10, vector_weight=1.0, keyword_weight=1.0)
    assert fused == []


def test_rrf_preserves_content_and_metadata():
    """Fused results carry through content and metadata from raw results."""
    results = [
        RawResult(id="x", content="hello world", metadata={"key": "val"},
                  created_at="2025-01-01", rank=1, source="vector"),
    ]
    fused = _reciprocal_rank_fusion(results, limit=5, vector_weight=1.0, keyword_weight=1.0)
    assert len(fused) == 1
    assert fused[0].content == "hello world"
    assert fused[0].metadata == {"key": "val"}
