import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from build_networking_anythingllm_dataset import segment_id  # noqa: E402
from build_networking_benchmark import load_query_set  # noqa: E402
from run_multi_query_benchmark import (  # noqa: E402
    bootstrap_ci,
    create_output_directory,
    paired_summary,
    percentile,
    ranking_metrics,
    safe_query_record,
)


def test_query_set_requires_original_alternatives_and_page_qrels(tmp_path: Path) -> None:
    path = tmp_path / "queries.json"
    path.write_text(
        json.dumps(
            [
                {
                    "query_id": "q01",
                    "query": "Why does a long path need a larger TCP window?",
                    "alternatives": ["TCP bandwidth delay product", "TCP window scaling"],
                    "relevant": [
                        {"book_id": "book-1", "pages": [10, 11]},
                        {"book_id": "book-2", "pages": [20]},
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    loaded = load_query_set(path)

    assert loaded[0]["query_id"] == "q01"
    assert loaded[0]["relevant"][0]["pages"] == [10, 11]


@pytest.mark.parametrize(
    "record",
    [
        {"query_id": "q", "query": "x", "alternatives": [], "relevant": []},
        {"query_id": "q", "query": "x", "alternatives": ["a"], "relevant": []},
        {
            "query_id": "q",
            "query": "x",
            "alternatives": ["a", "b", "c"],
            "relevant": [{"book_id": "b", "pages": [1]}],
        },
    ],
)
def test_query_set_rejects_incomplete_or_unbounded_records(
    tmp_path: Path, record: dict[str, object]
) -> None:
    path = tmp_path / "queries.json"
    path.write_text(json.dumps([record]), encoding="utf-8")

    with pytest.raises(ValueError):
        load_query_set(path)


def test_query_set_allows_explicit_unanswerable_without_qrels(tmp_path: Path) -> None:
    path = tmp_path / "queries.json"
    path.write_text(
        json.dumps(
            [
                {
                    "query_id": "q-off",
                    "query": "Which chapter specifies a protocol absent from the corpus?",
                    "alternatives": ["absent protocol specification", "unsupported protocol"],
                    "answerable": False,
                    "relevant": [],
                }
            ]
        ),
        encoding="utf-8",
    )

    loaded = load_query_set(path)

    assert loaded[0]["answerable"] is False
    assert loaded[0]["relevant"] == []


def test_ranking_metrics_use_page_level_evidence() -> None:
    result = ranking_metrics(
        retrieved=["book-1:99", "book-1:10", "book-2:20", "book-1:11"],
        relevant={"book-1:10", "book-1:11", "book-3:30"},
        k=3,
    )

    assert result["recall_at_k"] == pytest.approx(1 / 3)
    assert result["reciprocal_rank"] == pytest.approx(1 / 2)
    assert 0 < result["ndcg_at_k"] < 1


def test_ranking_metrics_count_repeated_page_only_once() -> None:
    result = ranking_metrics(
        retrieved=["book-1:10", "book-1:10", "book-1:10"],
        relevant={"book-1:10"},
        k=3,
    )

    assert result == {
        "recall_at_k": 1.0,
        "reciprocal_rank": 1.0,
        "ndcg_at_k": 1.0,
    }


def test_percentile_uses_linear_interpolation() -> None:
    assert percentile([10.0, 20.0, 30.0, 40.0], 0.5) == pytest.approx(25.0)
    assert percentile([10.0, 20.0, 30.0, 40.0], 0.95) == pytest.approx(38.5)
    assert percentile([], 0.95) is None


def test_bootstrap_interval_is_deterministic_for_seed() -> None:
    first = bootstrap_ci([0.0, 0.1, 0.2], seed=42, samples=1_000)
    second = bootstrap_ci([0.0, 0.1, 0.2], seed=42, samples=1_000)

    assert first == second
    assert first is not None and first[0] <= first[1]


def test_output_directory_must_be_new(tmp_path: Path) -> None:
    output = tmp_path / "run"
    create_output_directory(output)
    assert output.is_dir()

    with pytest.raises(FileExistsError):
        create_output_directory(output)


def test_safe_record_never_contains_query_or_alternatives() -> None:
    record = safe_query_record(
        query_id="q01",
        mode="multi",
        retrieved=[{"evidence_id": "book-1:10", "rank": 1, "score": 0.9}],
        metrics={"recall_at_k": 1.0, "reciprocal_rank": 1.0, "ndcg_at_k": 1.0},
        elapsed_ms=12.5,
        expansion_count=3,
        error=None,
    )

    assert "query" not in record
    assert "alternatives" not in record
    assert record["query_id"] == "q01"
    assert record["expansion_count"] == 3
    assert record["answerable"] is True
    assert record["no_answer"] is False


def test_paired_summary_excludes_unanswerable_and_error_rows(tmp_path: Path) -> None:
    for mode, answerable_score in (("single", 0.25), ("multi", 0.75)):
        output = tmp_path / mode
        output.mkdir()
        rows = [
            safe_query_record(
                query_id="q-answerable",
                mode=mode,
                retrieved=[],
                metrics={
                    "recall_at_k": answerable_score,
                    "reciprocal_rank": answerable_score,
                    "ndcg_at_k": answerable_score,
                },
                elapsed_ms=1.0,
                expansion_count=1,
                error=None,
                answerable=True,
            ),
            safe_query_record(
                query_id="q-off-corpus",
                mode=mode,
                retrieved=[],
                metrics=None,
                elapsed_ms=1.0,
                expansion_count=1,
                error=None,
                answerable=False,
                no_answer=True,
            ),
            safe_query_record(
                query_id="q-error",
                mode=mode,
                retrieved=[],
                metrics=None,
                elapsed_ms=1.0,
                expansion_count=1,
                error="UpstreamError",
                answerable=True,
                no_answer=None,
            ),
        ]
        (output / "per_query.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )

    summary = paired_summary(tmp_path, seed=42)

    for metric in summary["metrics"].values():
        assert metric["paired_query_count"] == 1
        assert metric["mean_delta"] == pytest.approx(0.5)


def test_anythingllm_segment_ids_are_stable_at_boundaries() -> None:
    assert segment_id("book-1", 1, pages_per_segment=20) == "book-1-pages-0001-0020"
    assert segment_id("book-1", 20, pages_per_segment=20) == "book-1-pages-0001-0020"
    assert segment_id("book-1", 21, pages_per_segment=20) == "book-1-pages-0021-0040"
