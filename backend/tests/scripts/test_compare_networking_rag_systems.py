import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from compare_networking_rag_systems import (  # noqa: E402
    aggregate,
    evidence_to_segment,
    segment_id,
)


def test_segment_mapping_uses_physical_page_intervals() -> None:
    assert segment_id("book", 1) == "book-pages-0001-0020"
    assert segment_id("book", 20) == "book-pages-0001-0020"
    assert evidence_to_segment("book:21") == "book-pages-0021-0040"


def test_aggregate_macro_averages_queries_before_system_score() -> None:
    rows = [
        {
            "query_id": "q1",
            "answerable": True,
            "no_answer": False,
            "metrics": {"recall_at_k": 1.0, "mrr_at_k": 1.0, "ndcg_at_k": 1.0},
            "latency_ms": 1.0,
            "error": None,
        },
        {
            "query_id": "q1",
            "answerable": True,
            "no_answer": False,
            "metrics": {"recall_at_k": 0.0, "mrr_at_k": 0.0, "ndcg_at_k": 0.0},
            "latency_ms": 2.0,
            "error": None,
        },
        {
            "query_id": "q2",
            "answerable": True,
            "no_answer": False,
            "metrics": {"recall_at_k": 1.0, "mrr_at_k": 1.0, "ndcg_at_k": 1.0},
            "latency_ms": 3.0,
            "error": None,
        },
        {
            "query_id": "off",
            "answerable": False,
            "no_answer": True,
            "metrics": None,
            "latency_ms": 4.0,
            "error": None,
        },
    ]

    result = aggregate(rows)

    assert result["recall_at_5"] == pytest.approx(0.75)
    assert result["abstention"]["f1"] == 1.0
    assert result["query_count"] == 3
