from __future__ import annotations

import pytest

from scripts.analyze_large_books_open_source_followup import interval_id, ranking_metrics


def test_interval_id_boundaries() -> None:
    assert interval_id("book", 1) == "book-pages-0001-0020"
    assert interval_id("book", 20) == "book-pages-0001-0020"
    assert interval_id("book", 21) == "book-pages-0021-0040"


def test_interval_ranking_metrics_deduplicate_hits() -> None:
    recall, mrr, ndcg = ranking_metrics(
        ["a", "a", "b", "c"], {"b", "c"}, k=5
    )

    assert recall == 1.0
    assert mrr == 0.5
    assert 0 < ndcg < 1
    with pytest.raises(ValueError):
        interval_id("book", 0)
