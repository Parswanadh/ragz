from __future__ import annotations

import pytest

from scripts.build_large_books_anythingllm_dataset import (
    evidence_unit_id,
    page_id,
    query_and_qrel_rows,
)


def test_page_id_is_physical_and_stable() -> None:
    assert page_id("manual", 7) == "manual-page-0007"
    with pytest.raises(ValueError, match="positive"):
        page_id("manual", 0)
    assert evidence_unit_id("manual", 21, 20) == "manual-pages-0021-0040"


def test_query_projection_preserves_answerable_and_off_corpus_denominators() -> None:
    queries, qrels = query_and_qrel_rows(
        [
            {
                "query_id": "q1",
                "query": "where",
                "answerable": True,
                "expected_doc_ids": ["manual"],
                "evidence_pages": [7, 7],
                "question_type": "fact",
            },
            {
                "query_id": "q2",
                "query": "absent",
                "answerable": False,
                "expected_doc_ids": [],
                "evidence_pages": [],
            },
        ]
    )

    assert [row["answerable"] for row in queries] == [True, False]
    assert qrels == [{"query_id": "q1", "doc_id": "manual-page-0007", "relevance": 1}]


def test_query_projection_can_use_common_twenty_page_intervals() -> None:
    _queries, qrels = query_and_qrel_rows(
        [
            {
                "query_id": "q1",
                "query": "where",
                "answerable": True,
                "expected_doc_ids": ["manual"],
                "evidence_pages": [20, 21],
            }
        ],
        pages_per_document=20,
    )

    assert {row["doc_id"] for row in qrels} == {
        "manual-pages-0001-0020",
        "manual-pages-0021-0040",
    }
