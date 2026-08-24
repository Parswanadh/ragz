from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.run_ragz_matrix_triad import (
    build_context,
    citation_metrics,
    condition_id,
    load_private_cases,
    ranking_conditions,
    ranking_match_kind,
    structured_provider_call,
    summarize,
)


def test_frozen_ranking_matrix_has_twelve_unique_conditions() -> None:
    values = [condition_id(*condition) for condition in ranking_conditions()]

    assert len(values) == 12
    assert len(set(values)) == 12
    assert values[0] == "q1_rerank-off_cache-off"
    assert values[-1] == "q5_rerank-50_cache-off"


def test_ranking_match_accepts_only_reordering_inside_equal_score_ties() -> None:
    expected = [
        {"evidence_id": "a", "rank": 1, "score": 1.0},
        {"evidence_id": "b", "rank": 2, "score": 0.25},
        {"evidence_id": "c", "rank": 3, "score": 0.25},
    ]
    tied = [
        {"evidence_id": "a", "rank": 1, "score": 1.0},
        {"evidence_id": "c", "rank": 2, "score": 0.25},
        {"evidence_id": "b", "rank": 3, "score": 0.25},
    ]
    changed = [*tied[:2], {"evidence_id": "d", "rank": 3, "score": 0.25}]
    score_changed = [*tied[:2], {"evidence_id": "d", "rank": 3, "score": 0.2}]

    assert ranking_match_kind(expected, expected) == "exact"
    assert ranking_match_kind(tied, expected) == "score_tie_equivalent"
    assert (
        ranking_match_kind(changed, expected)
        == "score_profile_equivalent_boundary_tie"
    )
    assert ranking_match_kind(score_changed, expected) == "drift"
    assert ranking_match_kind(tied, None) == "screen_repair"


async def test_structured_provider_call_retries_schema_parse_once() -> None:
    class Usage:
        def as_dict(self) -> dict[str, int]:
            return {"input_tokens": 1, "cached_input_tokens": 0, "output_tokens": 1}

    class Response:
        payload = {"ok": True}
        usage = Usage()

    class Client:
        calls = 0

        def response(self, **_kwargs: object) -> Response:
            self.calls += 1
            return Response()

    class Runner:
        calls = 0

        @classmethod
        def structured_response(cls, _payload: object) -> dict[str, bool]:
            cls.calls += 1
            if cls.calls == 1:
                raise RuntimeError("malformed")
            return {"ok": True}

    client = Client()
    parsed, usage, retries = await structured_provider_call(
        client=client,
        runner=Runner,
        attempts=2,
        model="m",
        system="s",
        user="u",
        name="rag_answer",
        schema={},
        max_output_tokens=100,
    )

    assert parsed == {"ok": True}
    assert usage["input_tokens"] == 1
    assert retries == 1
    assert client.calls == 2


@pytest.mark.parametrize("query_count", [0, 2, 4, 6])
def test_condition_id_rejects_unsupported_query_count(query_count: int) -> None:
    with pytest.raises(ValueError, match="query_count"):
        condition_id(query_count, None)


def test_context_is_bounded_and_returns_only_sent_ids() -> None:
    context, ids = build_context(
        [
            {"chunk_id": "doc:1:0", "text": "a" * 1_900},
            {"chunk_id": "doc:2:0", "text": "b" * 1_900},
        ],
        max_chars=2_000,
    )

    assert len(context) <= 2_000
    assert ids == ["doc:1:0", "doc:2:0"]
    assert "chunk_id=doc:1:0" in context


def test_citation_metrics_distinguish_validity_and_evidence() -> None:
    metrics = citation_metrics(
        {
            "citations": [
                {"marker": 1, "chunk_id": "doc:7:0"},
                {"marker": 2, "chunk_id": "invented:1:0"},
            ]
        },
        valid_ids={"doc:7:0", "doc:8:0"},
        relevant_pages={"doc:7", "doc:9"},
    )

    assert metrics["citation_validity"] == 0.5
    assert metrics["citation_evidence_precision"] == 1.0
    assert metrics["citation_evidence_recall"] == 0.5


def test_private_case_loader_requires_four_alternatives(tmp_path: Path) -> None:
    path = tmp_path / "queries.json"
    path.write_text(
        json.dumps(
            [
                {
                    "query_id": "q1",
                    "query": "private",
                    "alternatives": ["a", "b"],
                    "answerable": True,
                    "expected_answer": "private",
                    "relevant": [],
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="four alternatives"):
        load_private_cases(path)


def test_summary_uses_answerable_rows_for_triad_and_all_rows_for_abstention() -> None:
    judge = {
        "context_relevance": 0.9,
        "groundedness": 0.8,
        "answer_relevance": 0.7,
        "correctness": 0.6,
        "citation_entailment": 0.5,
        "citation_precision": 0.4,
        "citation_completeness": 0.3,
    }
    rows = [
        {
            "answerable": True,
            "abstained": False,
            "judge": judge,
            "timings_ms": {"total": 10.0},
            "error_codes": [],
        },
        {
            "answerable": False,
            "abstained": True,
            "judge": {name: 0.0 for name in judge},
            "timings_ms": {"total": 20.0},
            "error_codes": [],
        },
    ]

    result = summarize(rows)

    assert result["rag_triad"]["context_relevance"] == 0.9
    assert result["rag_triad"]["secondary_composite"] == pytest.approx(0.8)
    assert result["answer_abstention"]["f1"] == 1.0
    assert result["latency_ms"]["total"]["mean_ms"] == 15.0
