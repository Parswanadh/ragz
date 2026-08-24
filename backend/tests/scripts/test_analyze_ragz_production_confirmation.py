from __future__ import annotations

import pytest

from scripts.analyze_ragz_production_confirmation import _paired, distribution


def test_distribution_interpolates_tail_percentiles() -> None:
    result = distribution([1.0, 2.0, 3.0, 4.0])

    assert result["mean"] == 2.5
    assert result["p50"] == 2.5
    assert result["p95"] == pytest.approx(3.85)


def test_paired_matches_order_repetition_and_query() -> None:
    rows = []
    for order in ("forward", "reverse"):
        for repetition in range(1, 6):
            for count, recall, elapsed in ((1, 0.5, 10.0), (3, 0.6, 15.0)):
                rows.append(
                    {
                        "mode": f"{order}_q{count}_rerank-off_cache-off",
                        "query_id": "q1",
                        "repetition": repetition,
                        "expansion_count": count,
                        "answerable": True,
                        "elapsed_ms": elapsed,
                        "metrics": {
                            "recall_at_k": recall,
                            "reciprocal_rank": recall,
                            "ndcg_at_k": recall,
                        },
                    }
                )

    result = _paired(rows, cache="off", seed=7)

    assert result["recall_at_k"]["paired_observations"] == 10
    assert result["recall_at_k"]["mean_q3_minus_q1"] == pytest.approx(0.1)
    assert result["elapsed_ms"]["mean_q3_minus_q1"] == 5.0
