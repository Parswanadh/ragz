import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_networking_anythingllm import batches, ranking_metrics, summarize  # noqa: E402


def test_batches_cover_values_once_and_reject_zero() -> None:
    assert list(batches(list(range(10)), 4)) == [
        [0, 1, 2, 3],
        [4, 5, 6, 7],
        [8, 9],
    ]
    with pytest.raises(ValueError):
        list(batches([1], 0))


def test_ranking_metrics_deduplicate_repeated_segments() -> None:
    metrics = ranking_metrics(["a", "a", "x", "b"], {"a", "b"}, 3)
    assert metrics["recall_at_k"] == 1.0
    assert metrics["mrr_at_k"] == 1.0
    assert 0 < metrics["ndcg_at_k"] <= 1.0


def test_summary_excludes_off_corpus_and_errors_from_quality() -> None:
    records = [
        {
            "answerable": True,
            "error": None,
            "metrics": {"recall_at_k": 1.0, "mrr_at_k": 0.5, "ndcg_at_k": 0.75},
            "no_answer": False,
            "latency_ms": 10.0,
        },
        {
            "answerable": False,
            "error": None,
            "metrics": None,
            "no_answer": True,
            "latency_ms": 20.0,
        },
        {
            "answerable": True,
            "error": "RemoteProtocolError",
            "metrics": None,
            "no_answer": False,
            "latency_ms": 30.0,
        },
    ]

    result = summarize(records, top_k=5)

    assert result["quality_observations"] == 1
    assert result["mean_recall_at_k"] == 1.0
    assert result["abstention"]["f1"] == 1.0
    assert result["errors"] == 1
