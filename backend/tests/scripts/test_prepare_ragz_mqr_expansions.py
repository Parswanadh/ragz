from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from prepare_ragz_mqr_expansions import (  # noqa: E402
    SourceQuery,
    load_source_queries,
    prepare_expansions,
)

from ragz.modules.retrieval.query_expansion import ExpandedQueries  # noqa: E402


class _Expander:
    def __init__(self, count: int = 5) -> None:
        self.count = count

    async def expand(self, query: str, *, model: str) -> ExpandedQueries:
        queries = (query, "exact", "terms", "mechanism", "evidence")[: self.count]
        return ExpandedQueries(queries, prompt_tokens=10, completion_tokens=5)


def _source() -> SourceQuery:
    return SourceQuery(
        query_id="q1",
        query="private question",
        answerable=True,
        relevant=({"book_id": "book", "pages": [4]},),
        query_type="direct",
        expected_answer="private answer",
    )


def test_load_source_queries_maps_document_and_page_qrels(tmp_path: Path) -> None:
    path = tmp_path / "queries.jsonl"
    path.write_text(
        json.dumps(
            {
                "query_id": "q1",
                "query": "question",
                "answerable": True,
                "expected_doc_ids": ["book"],
                "evidence_pages": [5, 4, 5],
                "question_type": "direct",
                "expected_answer": "answer",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    [row] = load_source_queries(path)
    assert row.relevant == ({"book_id": "book", "pages": [4, 5]},)
    assert row.expected_answer == "answer"


async def test_prepare_expansions_keeps_text_private_and_metrics_public() -> None:
    private, public = await prepare_expansions(
        [_source()], expander=_Expander(), model="gpt-5.6-luna", retries=0
    )

    assert private[0]["query"] == "private question"
    assert private[0]["alternatives"] == ["exact", "terms", "mechanism", "evidence"]
    serialized_public = json.dumps(public)
    assert "private question" not in serialized_public
    assert "private answer" not in serialized_public
    assert "exact" not in serialized_public
    assert public[0]["expansion_count"] == 5
    assert public[0]["error_code"] is None


async def test_prepare_expansions_completes_short_output_with_safe_perspectives() -> None:
    private, public = await prepare_expansions(
        [_source()], expander=_Expander(count=3), model="gpt-5.6-luna", retries=0
    )

    assert len(private[0]["alternatives"]) == 4
    assert public[0]["error_code"] is None
    assert public[0]["expansion_count"] == 5
    assert public[0]["fallback_count"] == 2
