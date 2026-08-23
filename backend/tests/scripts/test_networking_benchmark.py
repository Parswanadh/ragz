import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from build_networking_anythingllm_dataset import query_rows, segment_id  # noqa: E402
from build_networking_benchmark import load_query_set  # noqa: E402
from run_multi_query_benchmark import (  # noqa: E402
    bootstrap_ci,
    campaign_code_provenance,
    create_output_directory,
    paired_summary,
    percentile,
    ranking_metrics,
    resolve_embedding_track,
    safe_query_record,
    summarize_stage_timings,
)
from seed_networking_comparison_lab import (  # noqa: E402
    DEFAULT_CHAT_MODEL,
    validate_lab_target,
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


def test_campaign_code_provenance_hashes_untracked_capable_inputs() -> None:
    provenance = campaign_code_provenance()

    assert len(provenance["aggregate_sha256"]) == 64
    assert "scripts/run_multi_query_benchmark.py" in provenance["files_sha256"]
    assert "scripts/embedding_benchmark_matrix.py" in provenance["files_sha256"]
    assert "src/ragz/modules/retrieval/embeddings.py" in provenance["files_sha256"]


def test_embedding_tracks_pin_model_and_dimension() -> None:
    hash_track = resolve_embedding_track("hash")
    openai_track = resolve_embedding_track("openai")

    assert (hash_track.model, hash_track.dimension) == ("deterministic-hash", 1024)
    assert openai_track.model == "text-embedding-3-small"
    assert openai_track.litellm_model_name == "ragz-openai-text-embedding-3-small-d1536"
    assert openai_track.dimension == 1536
    assert openai_track.provider_kind == "openai"
    assert openai_track.settings_backend == "litellm"
    with pytest.raises(ValueError):
        resolve_embedding_track("other")


def test_openai_embedding_tracks_validate_model_dimension_matrix() -> None:
    large = resolve_embedding_track(
        "openai",
        model="text-embedding-3-large",
        dimension=2096,
        litellm_model_name="ragz-openai-text-embedding-3-large-d2096",
    )

    assert large.model == "text-embedding-3-large"
    assert large.dimension == 2096
    assert large.litellm_model_name == "ragz-openai-text-embedding-3-large-d2096"
    assert large.dense_label == "openai-text-embedding-3-large-2096"
    with pytest.raises(ValueError):
        resolve_embedding_track(
            "openai", model="text-embedding-3-small", dimension=2096
        )
    with pytest.raises(ValueError, match="not the fixed alias"):
        resolve_embedding_track(
            "openai",
            model="text-embedding-3-large",
            dimension=2096,
            litellm_model_name="attested-large-2096",
        )
    with pytest.raises(ValueError):
        resolve_embedding_track("hash", dimension=1024)


def test_comparison_lab_pins_shared_answer_model() -> None:
    assert DEFAULT_CHAT_MODEL == "gpt-5.6-luna"


def test_safe_record_never_contains_query_or_alternatives() -> None:
    record = safe_query_record(
        query_id="q01",
        mode="multi",
        retrieved=[{"evidence_id": "book-1:10", "rank": 1, "score": 0.9}],
        metrics={"recall_at_k": 1.0, "reciprocal_rank": 1.0, "ndcg_at_k": 1.0},
        elapsed_ms=12.5,
        expansion_count=3,
        error=None,
        stage_timings_ms={"dense_embedding": 9.87654, "vector_search": 2.34567},
    )

    assert "query" not in record
    assert "alternatives" not in record
    assert record["query_id"] == "q01"
    assert record["expansion_count"] == 3
    assert record["answerable"] is True
    assert record["no_answer"] is False
    assert record["stage_timings_ms"] == {
        "dense_embedding": 9.8765,
        "vector_search": 2.3457,
    }


def test_atomic_timing_summary_excludes_errors_and_does_not_invent_stages() -> None:
    records = [
        {
            "error": None,
            "elapsed_ms": 12.0,
            "stage_timings_ms": {"dense_embedding": 8.0, "vector_search": 2.0},
        },
        {
            "error": None,
            "elapsed_ms": 16.0,
            "stage_timings_ms": {"dense_embedding": 10.0},
        },
        {
            "error": "UpstreamError",
            "elapsed_ms": 99.0,
            "stage_timings_ms": {"dense_embedding": 99.0, "failed_only": 1.0},
        },
    ]

    summary = summarize_stage_timings(records)

    assert summary["successful_observations"] == 2
    assert set(summary["stages"]) == {"dense_embedding", "vector_search"}
    assert summary["stages"]["dense_embedding"]["mean"] == 9.0
    assert summary["stages"]["dense_embedding"]["observations"] == 2
    assert summary["stages"]["vector_search"]["observations"] == 1
    assert summary["stages"]["dense_embedding"]["mean_total_share"] == pytest.approx(
        9 / 14
    )


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


def test_anythingllm_query_projection_preserves_default_answerable() -> None:
    projected = query_rows(
        [
            {"query_id": "q1", "query": "answerable", "query_type": "direct"},
            {
                "query_id": "q2",
                "query": "unsupported",
                "query_type": "off-corpus",
                "answerable": False,
            },
        ]
    )

    assert [row["answerable"] for row in projected] == [True, False]


def test_comparison_lab_requires_explicit_dedicated_database_confirmation() -> None:
    database_url = "postgresql+asyncpg://ragz:ragz@localhost/ragz_mq_lab_review"

    assert (
        validate_lab_target(
            database_url=database_url,
            environment="dev",
            confirmed_database="ragz_mq_lab_review",
        )
        == "ragz_mq_lab_review"
    )
    with pytest.raises(RuntimeError):
        validate_lab_target(
            database_url=database_url,
            environment="production",
            confirmed_database="ragz_mq_lab_review",
        )
    with pytest.raises(RuntimeError):
        validate_lab_target(
            database_url=database_url,
            environment="dev",
            confirmed_database="ragz",
        )
    with pytest.raises(RuntimeError):
        validate_lab_target(
            database_url="postgresql+asyncpg://ragz:ragz@localhost/ragz",
            environment="dev",
            confirmed_database="ragz",
        )
