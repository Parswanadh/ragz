import hashlib
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from compare_networking_rag_systems import (  # noqa: E402
    aggregate,
    common_ragz_configuration,
    evidence_to_segment,
    segment_id,
    validate_complete_records,
    validate_embedding_parity,
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


def test_common_ragz_configuration_requires_embedding_parity() -> None:
    manifest = {
        "dense": "openai-text-embedding-3-small-1536",
        "embedding_model": "text-embedding-3-small",
        "embedding_dimension": 1536,
        "embedding_provider": "openai",
        "embedding_transport": "litellm",
        "embedding_proxy_fingerprint_sha256": "a" * 64,
        "sparse": "fastembed-bm25",
        "fusion": "qdrant-rrf",
        "reranker": "disabled",
        "top_k": 20,
    }

    assert common_ragz_configuration([manifest, dict(manifest)]) == manifest
    mismatched = dict(manifest, embedding_dimension=1024)
    with pytest.raises(ValueError):
        common_ragz_configuration([manifest, mismatched])


def test_embedding_parity_requires_matching_runs_and_proxy(tmp_path: Path) -> None:
    ragz_runs = [tmp_path / "ragz-a", tmp_path / "ragz-b"]
    anything = tmp_path / "anything"
    expected = {
        "model": "text-embedding-3-small",
        "dimension": 1536,
        "provider": "openai",
        "transport": "litellm",
    }
    attestation = tmp_path / "parity.json"
    anything.mkdir()
    anything_manifest_path = anything / "manifest.json"
    anything_manifest = {
        "track": "common-20-page-segments-openai-lancedb",
        **{f"embedding_{key}": value for key, value in expected.items()},
        "embedding_proxy_fingerprint_sha256": "a" * 64,
    }
    anything_manifest_path.write_text(json.dumps(anything_manifest), encoding="utf-8")
    attestation.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_runs": {
                    "anythingllm": "anything",
                    "ragz": ["ragz-a", "ragz-b"],
                },
                "embedding": {"anythingllm": expected, "ragz": expected},
                "shared_proxy": {
                    "used_by": ["anythingllm", "ragz"],
                    "instance_fingerprint_sha256": "a" * 64,
                },
                "source_artifacts": {
                    "anythingllm_manifest_sha256": hashlib.sha256(
                        anything_manifest_path.read_bytes()
                    ).hexdigest()
                },
            }
        ),
        encoding="utf-8",
    )
    ragz_config = {
        **{f"embedding_{key}": value for key, value in expected.items()},
        "embedding_proxy_fingerprint_sha256": "a" * 64,
    }

    result = validate_embedding_parity(
        path=attestation,
        ragz_config=ragz_config,
        ragz_runs=ragz_runs,
        anything_manifest=anything_manifest,
        anything_manifest_path=anything_manifest_path,
        anything_run=anything,
    )

    assert result["validated"] is True
    bad = dict(ragz_config, embedding_dimension=1024)
    with pytest.raises(ValueError):
        validate_embedding_parity(
            path=attestation,
            ragz_config=bad,
            ragz_runs=ragz_runs,
            anything_manifest=anything_manifest,
            anything_manifest_path=anything_manifest_path,
            anything_run=anything,
        )


def test_complete_records_reject_errors_and_uneven_repetitions() -> None:
    records = [
        {
            "query_id": query_id,
            "answerable": query_id == "answerable",
            "metrics": {"recall_at_k": 1.0} if query_id == "answerable" else None,
            "error": None,
        }
        for query_id in ("answerable", "off")
        for _ in range(3)
    ]

    result = validate_complete_records(
        label="test",
        records=records,
        expected_query_ids={"answerable", "off"},
        answerable_query_ids={"answerable"},
        repetitions_per_query=3,
    )

    assert result == {
        "query_count": 2,
        "answerable_query_count": 1,
        "off_corpus_query_count": 1,
        "repetitions_per_query": 3,
        "observations": 6,
        "errors": 0,
    }
    with pytest.raises(ValueError):
        validate_complete_records(
            label="test",
            records=records[:-1],
            expected_query_ids={"answerable", "off"},
            answerable_query_ids={"answerable"},
            repetitions_per_query=3,
        )
    failed = [dict(record) for record in records]
    failed[0]["error"] = "UpstreamError"
    with pytest.raises(ValueError):
        validate_complete_records(
            label="test",
            records=failed,
            expected_query_ids={"answerable", "off"},
            answerable_query_ids={"answerable"},
            repetitions_per_query=3,
        )
