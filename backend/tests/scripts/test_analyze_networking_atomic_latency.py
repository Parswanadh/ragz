import hashlib
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from analyze_networking_atomic_latency import (  # noqa: E402
    aggregate_mode,
    load_endpoint_probe,
    manifest_identity,
    validate_run_records,
)
from run_embedding_endpoint_probe import summarize as summarize_endpoint_probe  # noqa: E402


def _write_run(root: Path, *, error: str | None = None) -> None:
    mode = root / "single"
    mode.mkdir(parents=True)
    rows = [
        {
            "query_id": "q1",
            "elapsed_ms": total,
            "error": error,
            "stage_timings_ms": {
                "dense_embedding": dense,
                "vector_search": search,
                "unattributed_runner": total - dense - search,
            },
        }
        for total, dense, search in ((10.0, 7.0, 2.0), (20.0, 15.0, 3.0))
    ]
    (mode / "per_query.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )


def test_aggregate_mode_reports_atomic_means_and_provider_excluded_time(
    tmp_path: Path,
) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    _write_run(first)
    _write_run(second)

    result = aggregate_mode([first, second], "single")

    assert result["observations"] == 4
    assert result["mean_ms"] == 15.0
    assert result["stages"]["dense_embedding"]["mean_ms"] == 11.0
    assert result["mean_without_dense_embedding_ms"] == 4.0
    assert result["stages"]["vector_search"]["mean_total_share"] == pytest.approx(
        2.5 / 15
    )


def test_aggregate_mode_rejects_errors_and_inconsistent_stage_schema(
    tmp_path: Path,
) -> None:
    failed = tmp_path / "failed"
    _write_run(failed, error="UpstreamError")
    with pytest.raises(ValueError, match="zero-error"):
        aggregate_mode([failed], "single")

    inconsistent = tmp_path / "inconsistent"
    _write_run(inconsistent)
    path = inconsistent / "single" / "per_query.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[1]["stage_timings_ms"].pop("vector_search")
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(ValueError, match="inconsistent"):
        aggregate_mode([inconsistent], "single")

    bad_closure = tmp_path / "bad-closure"
    _write_run(bad_closure)
    path = bad_closure / "single" / "per_query.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]["stage_timings_ms"]["dense_embedding"] += 1.0
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(ValueError, match="close"):
        aggregate_mode([bad_closure], "single")


def test_validate_run_records_rejects_duplicate_query_repetitions(tmp_path: Path) -> None:
    root = tmp_path / "run"
    _write_run(root)
    path = root / "single" / "per_query.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    for repetition, row in enumerate(rows, 1):
        row.update({"repetition": repetition, "expansion_count": 1})
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))

    validate_run_records(root, mode="single", expected_query_count=1, repetitions=2)
    rows[1]["repetition"] = 1
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(ValueError, match="duplicate"):
        validate_run_records(root, mode="single", expected_query_count=1, repetitions=2)


def test_manifest_identity_includes_every_fairness_control() -> None:
    manifest = {
        "dataset_id": "d",
        "query_set": {"count": 15, "sha256": "q"},
        "pdfs": [{"book_id": "b", "sha256": "p"}],
        "top_k": 20,
        "warmups": 2,
        "repetitions": 3,
        "embedding_model": "text-embedding-3-small",
        "embedding_dimension": 1536,
        "embedding_provider": "openai",
        "embedding_transport": "litellm",
        "embedding_proxy_fingerprint_sha256": "a" * 64,
        "dense": "openai-text-embedding-3-small-1536",
        "sparse": "fastembed-bm25",
        "fusion": "qdrant-rrf",
        "reranker": "disabled",
        "query_variants": "fixed-two-alternatives",
        "no_answer_threshold": {"value": 0.0},
        "stage_timing_schema": {"version": "retrieval-atomic-v1"},
    }

    identity = manifest_identity(manifest)

    assert set(identity) == {
        "dataset_id",
        "query_set",
        "pdfs",
        "top_k",
        "warmups",
        "repetitions",
        "embedding_model",
        "embedding_dimension",
        "embedding_provider",
        "embedding_transport",
        "embedding_proxy_fingerprint_sha256",
        "dense",
        "sparse",
        "fusion",
        "reranker",
        "query_variants",
        "no_answer_threshold",
        "stage_timing_schema",
    }
    mismatched = dict(manifest, top_k=5)
    assert manifest_identity(mismatched) != identity


def test_load_endpoint_probe_recomputes_rows_and_checks_hash(tmp_path: Path) -> None:
    root = tmp_path / "probe"
    root.mkdir()
    records: list[dict[str, object]] = []
    sequence = 0
    for repetition in range(1, 3):
        forward = ("direct_1", "proxy_1", "direct_3", "proxy_3")
        order = forward if repetition % 2 else tuple(reversed(forward))
        for order_index, condition in enumerate(order, 1):
            sequence += 1
            count = int(condition.rsplit("_", 1)[1])
            records.append(
                {
                    "sequence": sequence,
                    "repetition": repetition,
                    "order_index": order_index,
                    "condition": condition,
                    "path": (
                        "direct OpenAI"
                        if condition.startswith("direct")
                        else "LiteLLM to OpenAI"
                    ),
                    "input_count": count,
                    "elapsed_ms": 100.0 + sequence,
                    "dimension": 1536,
                    "total_tokens": count * 5,
                    "status_code": 200,
                    "error": None,
                }
            )
    raw = "".join(json.dumps(record, sort_keys=True) + "\n" for record in records)
    (root / "per_request.jsonl").write_text(raw)
    summary = summarize_endpoint_probe(records, repetitions=2)
    (root / "summary.json").write_text(json.dumps(summary))
    manifest = {
        "status": "completed",
        "git_dirty": False,
        "scored_repetitions_per_condition": 2,
        "per_request_sha256": hashlib.sha256(raw.encode()).hexdigest(),
    }
    (root / "manifest.json").write_text(json.dumps(manifest))

    loaded = load_endpoint_probe(root)

    assert loaded["conditions"] == summary["conditions"]
    manifest["per_request_sha256"] = "0" * 64
    (root / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="hash"):
        load_endpoint_probe(root)
