from __future__ import annotations

import pytest

from scripts.analyze_ragz_mqr_triad_campaign import (
    distribution,
    dominates,
    percentile,
)


def test_distribution_reports_interpolated_tail() -> None:
    values = [1.0, 2.0, 3.0, 4.0]

    assert percentile(values, 0.5) == 2.5
    assert distribution(values) == {
        "observations": 4,
        "mean": 2.5,
        "p50": 2.5,
        "p95": pytest.approx(3.85),
        "p99": pytest.approx(3.97),
        "min": 1.0,
        "max": 4.0,
    }


def test_pareto_dominance_maximizes_quality_and_minimizes_p95() -> None:
    def row(recall: float, mrr: float, ndcg: float, p95: float) -> dict[str, object]:
        return {
            "retrieval": {
                "recall_at_5": recall,
                "mrr_at_5": mrr,
                "ndcg_at_5": ndcg,
            },
            "latency_ms": {
                "retrieval_without_benchmark_rate_wait": {"p95": p95}
            },
        }

    assert dominates(row(0.7, 0.8, 0.75, 500), row(0.6, 0.8, 0.7, 600))
    assert not dominates(row(0.7, 0.7, 0.75, 500), row(0.6, 0.8, 0.7, 600))
