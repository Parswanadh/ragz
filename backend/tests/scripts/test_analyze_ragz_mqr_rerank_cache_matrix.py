from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from analyze_ragz_mqr_rerank_cache_matrix import (  # noqa: E402
    MatrixAnalysisError,
    analyze,
)
from run_multi_query_benchmark import retrieval_matrix_conditions  # noqa: E402


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _matrix(tmp_path: Path) -> Path:
    _write_json(tmp_path / "manifest.json", {"status": "completed", "condition_matrix": True})
    query_ids = ("q1", "q2")
    for spec in retrieval_matrix_conditions():
        directory = tmp_path / spec.condition_id
        directory.mkdir()
        cache_hits = spec.query_count if spec.cache_mode == "warm" else 0
        cache_misses = 0 if spec.cache_mode == "warm" else spec.query_count
        rows = [
            {
                "query_id": query_id,
                "repetition": repetition,
                "error": None,
                "answerable": True,
                "expansion_count": spec.query_count,
                "rerank_candidate_pool": spec.rerank_candidate_pool,
                "embedding_cache_hits": cache_hits,
                "embedding_cache_misses": cache_misses,
            }
            for repetition in (1, 2)
            for query_id in query_ids
        ]
        warmups = [
            {
                "query_id": query_id,
                "warmup": 1,
                "elapsed_ms": 120.0,
                "embedding_cache_hits": 0,
                "embedding_cache_misses": spec.query_count,
                "stage_timings_ms": {"dense_embedding": 100.0},
                "error": None,
            }
            for query_id in query_ids
        ]
        mean = 50.0 if spec.cache_mode == "warm" else 100.0 + spec.query_count
        _write_jsonl(directory / "per_query.jsonl", rows)
        _write_jsonl(directory / "warmups.jsonl", warmups)
        _write_json(
            directory / "summary.json",
            {
                "query_count": 2,
                "repetitions": 2,
                "quality_observations": 4,
                "condition": {
                    "query_count": spec.query_count,
                    "rerank_candidate_pool": spec.rerank_candidate_pool,
                    "cache_mode": spec.cache_mode,
                },
                "mean_recall_at_k": 1.0,
                "mean_reciprocal_rank": 0.9,
                "mean_ndcg_at_k": 0.95,
                "abstention": {"f1": 1.0},
                "latency_ms": {"mean": mean, "p50": mean, "p95": mean + 5, "p99": mean + 8},
                "embedding_cache": {"hits": cache_hits * 4, "misses": cache_misses * 4},
                "atomic_latency_ms": {"stages": {}},
                "warmup_atomic_latency_ms": {"stages": {}},
            },
        )
    return tmp_path


def test_analyzer_validates_matrix_and_computes_cache_blends(tmp_path: Path) -> None:
    result = analyze(_matrix(tmp_path))

    assert result["status"] == "completed"
    assert len(result["conditions"]) == 15
    blend = result["cache_blended_mean_latency_ms"]["q1"]
    assert blend["0.0"] == pytest.approx(101.0)
    assert blend["0.5"] == pytest.approx(75.5)
    assert "q1_rerank-off_cache-warm" in result["pareto_condition_ids"]


def test_analyzer_rejects_cache_state_drift(tmp_path: Path) -> None:
    root = _matrix(tmp_path)
    path = root / "q3_rerank-off_cache-warm" / "per_query.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]["embedding_cache_hits"] = 0
    _write_jsonl(path, rows)

    with pytest.raises(MatrixAnalysisError, match="cache state"):
        analyze(root)
