from __future__ import annotations

# ruff: noqa: E501
import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from analyze_ragflow_triad import AnalyzerError, analyze


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _inputs(
    tmp_path: Path, *, answerable_count: int = 60
) -> tuple[Path, Path, Path, Path, Path, Path, Path, Path, Path, Path, Path]:
    retrieval = tmp_path / "retrieval.jsonl"
    qa = tmp_path / "qa"
    qa.mkdir()
    public = tmp_path / "public-retrieval"
    public.mkdir()
    qrels = tmp_path / "qrels.jsonl"
    retrieval_rows: list[dict[str, object]] = []
    qa_rows: list[dict[str, object]] = []
    ledger: list[dict[str, object]] = []
    for index in range(1, 71):
        query_id = f"q{index:03d}"
        answerable = index <= answerable_count
        retrieval_rows.append(
            {
                "query_id": query_id,
                "answerable": answerable,
                "latency_ms": float(index),
                "ranked": [
                    {"doc_id": "doc-a", "score": 0.9, "content": "PRIVATE"},
                    {"doc_id": "doc-b", "score": 0.8, "content": "PRIVATE"},
                ],
                "metrics": {"mrr_at_5": 1.0, "recall_at_5": 1.0},
                "query": "PRIVATE",
            }
        )
        qa_rows.append(
            {
                "query_id": query_id,
                "metadata": {
                    "answerable": answerable,
                    "timings_ms": {
                        "generation_provider": 10.0,
                        "judge_provider": 20.0,
                        "postprocess": 1.0,
                    },
                    "query": "PRIVATE",
                },
                "judge": {
                    "context_relevance": 0.5 + (index / 1000),
                    "groundedness": 0.7,
                    "answer_relevance": 0.9,
                    "explanation": "PRIVATE",
                },
                "deterministic_metrics": {
                    "abstention_correct": True,
                    "citation_validity": 1.0 if answerable else None,
                    "citation_count": 1 if answerable else 0,
                },
                "usage": {
                    "generation": {"input_tokens": 100, "output_tokens": 10},
                    "judge": {"input_tokens": 200, "output_tokens": 20},
                },
                "answer": "PRIVATE",
                "errors": [],
            }
        )
        ledger.extend(
            [
                {
                    "endpoint": "responses-generation",
                    "usage": {"input_tokens": 100, "output_tokens": 10, "cached_input_tokens": 0},
                },
                {
                    "endpoint": "responses-judge",
                    "usage": {"input_tokens": 200, "output_tokens": 20, "cached_input_tokens": 0},
                },
            ]
        )
    _write_jsonl(retrieval, retrieval_rows)
    public_rows = [
        {
            "query_id": row["query_id"],
            "ranked_doc_ids": [item["doc_id"] for item in row["ranked"]],
            "ranked_scores": [item["score"] for item in row["ranked"]],
            "latency_ms": row["latency_ms"],
            "error_codes": [],
        }
        for row in retrieval_rows
    ]
    _write_jsonl(public / "per_query.jsonl", public_rows)
    qrel_rows = [
        {"query_id": f"q{index:03d}", "doc_id": "doc-a", "relevance": 1}
        for index in range(1, answerable_count + 1)
    ]
    # q001 has two relevant documents, proving nDCG is recomputed from qrels.
    qrel_rows.append({"query_id": "q001", "doc_id": "doc-b", "relevance": 1})
    _write_jsonl(qrels, qrel_rows)
    public_manifest = {
        "status": "completed",
        "denominator": {"total": 70, "answerable": 60, "off_corpus": 10, "errors": 0},
        "dataset_sha256": {
            "documents": "a7e6f35fda062cf04ab1435ffac269486f3920a6abe520f0a384673f64e9d335",
            "queries": "e743da70e48aab4392744dec18330c83da232bd883ce2c0ea5a1bff34c169c57",
            "qrels": hashlib.sha256(qrels.read_bytes()).hexdigest(),
        },
        "provenance": {
            "expected_source_commit": "ec9c08d809f63ba2815090182fa225899d2437d5",
            "source_commit": "ec9c08d809f63ba2815090182fa225899d2437d5",
            "expected_image_digest": "sha256:e9fe71c5ff14762eeb8e251b3b8ed37c02a99ae2bad3d7b11467260ced79578b",
            "image_digest": "sha256:e9fe71c5ff14762eeb8e251b3b8ed37c02a99ae2bad3d7b11467260ced79578b",
            "proxy_fingerprint_sha256": "e5a2913bf2fe061ba9811d8c102b740230c33ee549cc34e507aa03639200eb31",
        },
    }
    (public / "manifest.json").write_text(json.dumps(public_manifest), encoding="utf-8")
    (public / "summary.json").write_text(json.dumps({"status": "completed"}), encoding="utf-8")
    runtime = tmp_path / "runtime-manifest.json"
    runtime.write_text(
        json.dumps(
            {
                "version": "v0.27.0",
                "commit": "ec9c08d809f63ba2815090182fa225899d2437d5",
                "memory_limit_bytes": 5_000_000_000,
                "stack_left_running": False,
                "image_provenance": [
                    {
                        "role": "app",
                        "digest": "sha256:e9fe71c5ff14762eeb8e251b3b8ed37c02a99ae2bad3d7b11467260ced79578b",
                    }
                ],
                "post_smoke_stop": {
                    "containers_left_running": 0,
                    "stop_scope": "compose_project_only",
                },
            }
        ),
        encoding="utf-8",
    )
    preflight = tmp_path / "preflight.json"
    preflight.write_text(
        json.dumps(
            {
                "status": "completed",
                "embedding_proxy_fingerprint_sha256": "e5a2913bf2fe061ba9811d8c102b740230c33ee549cc34e507aa03639200eb31",
                "cells": [
                    {
                        "alias": "ragz-openai-text-embedding-3-large-d1024",
                        "model": "text-embedding-3-large",
                        "dimension": 1024,
                        "actual_dimension": 1024,
                        "probe_status": "passed",
                        "embedding_proxy_fingerprint_sha256": "e5a2913bf2fe061ba9811d8c102b740230c33ee549cc34e507aa03639200eb31",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    public_manifest_hash = hashlib.sha256((public / "manifest.json").read_bytes()).hexdigest()
    public_summary_hash = hashlib.sha256((public / "summary.json").read_bytes()).hexdigest()
    public_rows_hash = hashlib.sha256((public / "per_query.jsonl").read_bytes()).hexdigest()
    runtime_hash = hashlib.sha256(runtime.read_bytes()).hexdigest()
    preflight_hash = hashlib.sha256(preflight.read_bytes()).hexdigest()
    vector = tmp_path / "dataset-vector.json"
    vector.write_text(
        json.dumps(
            {
                "embedding_contract": {
                    "litellm_alias": "ragz-openai-text-embedding-3-large-d1024",
                    "underlying_model": "text-embedding-3-large",
                    "expected_dimension": 1024,
                    "observed_infinity_vector_size": 1024,
                    "proxy_fingerprint_sha256": "e5a2913bf2fe061ba9811d8c102b740230c33ee549cc34e507aa03639200eb31",
                },
                "embedding_preflight": {
                    "sha256": preflight_hash,
                    "actual_dimension": 1024,
                    "requested_dimension": 1024,
                    "probe_status": "passed",
                },
                "ragflow_log_evidence": {
                    "embedding_alias_event_count": 22,
                    "vector_size_1024_event_count": 1,
                    "content_persisted": False,
                },
                "final_dataset_preflight": {
                    "documents_expected": 22,
                    "documents_mapped": 22,
                    "documents_done": 22,
                    "chunks": 415,
                    "document_failure_messages": 0,
                    "retrieval_summary_sha256": public_summary_hash,
                },
            }
        ),
        encoding="utf-8",
    )
    stop = tmp_path / "runtime-stop.json"
    stop.write_text(
        json.dumps(
            {
                "source_runtime_manifest": {"sha256": runtime_hash},
                "scored_artifact": {
                    "manifest_sha256": public_manifest_hash,
                    "summary_sha256": public_summary_hash,
                    "per_query_sha256": public_rows_hash,
                },
                "source": {
                    "ragflow_version": "v0.27.0",
                    "commit": "ec9c08d809f63ba2815090182fa225899d2437d5",
                    "app_image_digest": "sha256:e9fe71c5ff14762eeb8e251b3b8ed37c02a99ae2bad3d7b11467260ced79578b",
                },
                "execution_window_utc": {
                    "dependencies_started_at": "2026-01-01T00:00:00Z",
                    "app_started_at": "2026-01-01T00:00:01Z",
                    "scored_artifact_created_at": "2026-01-01T00:00:02Z",
                    "last_container_stopped_at": "2026-01-01T00:00:03Z",
                    "verified_stopped_at": "2026-01-01T00:00:04Z",
                },
                "containers": [
                    {"status": "exited", "oom_killed": False, "restart_count": 0} for _ in range(5)
                ],
                "post_stop": {"containers_left_running": 0, "stop_scope": "compose_project_only"},
            }
        ),
        encoding="utf-8",
    )
    r1 = tmp_path / "r1"
    r2 = tmp_path / "r2"
    r1.mkdir()
    r2.mkdir()
    for directory in (r1, r2):
        for name in ("manifest.json", "summary.json", "per_query.jsonl"):
            shutil.copyfile(public / name, directory / name)
    r1_hashes = [
        hashlib.sha256((r1 / name).read_bytes()).hexdigest()
        for name in ("manifest.json", "summary.json", "per_query.jsonl")
    ]
    r2_hashes = [
        hashlib.sha256((r2 / name).read_bytes()).hexdigest()
        for name in ("manifest.json", "summary.json", "per_query.jsonl")
    ]
    measurement = tmp_path / "measurement.json"
    retrieval_hash = hashlib.sha256(retrieval.read_bytes()).hexdigest()
    measurement.write_text(
        json.dumps(
            {
                "effective_prior_passes_per_query_before_scored_r3": 3,
                "cache_reset_between_passes": False,
                "sequence": [
                    {
                        "order": 1,
                        "role": "private_qa_context_capture_and_warmup",
                        "private_retrieval_sha256": retrieval_hash,
                        "qa_retrieval_input_sha256": retrieval_hash,
                    },
                    {
                        "order": 2,
                        "role": "public_warmup_only",
                        "per_query_sha256": r1_hashes[2],
                        "summary_sha256": r1_hashes[1],
                    },
                    {
                        "order": 3,
                        "role": "public_warmup_only",
                        "per_query_sha256": r2_hashes[2],
                        "summary_sha256": r2_hashes[1],
                    },
                    {
                        "order": 4,
                        "role": "public_scored_retrieval",
                        "manifest_sha256": public_manifest_hash,
                        "per_query_sha256": public_rows_hash,
                        "summary_sha256": public_summary_hash,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    _write_jsonl(qa / "per_query.jsonl", qa_rows)
    _write_jsonl(qa / "cost_ledger.jsonl", ledger)
    (qa / "summary.json").write_text(
        json.dumps({"status": "completed", "query_count": 70}), encoding="utf-8"
    )
    (qa / "manifest.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "models": {
                    "embedding": "ragz-openai-text-embedding-3-large-d1024",
                    "generation": "gpt-5.6-luna",
                    "judge": "gpt-5.4-mini",
                },
                "retrieval_sha256": retrieval_hash,
            }
        ),
        encoding="utf-8",
    )
    return retrieval, qa, public, qrels, runtime, stop, preflight, vector, measurement, r1, r2


def test_analyzer_exports_private_safe_rows_and_recomputes_metrics(tmp_path: Path) -> None:
    retrieval, qa, public, qrels, runtime, stop, preflight, vector, measurement, r1, r2 = _inputs(
        tmp_path
    )
    output = tmp_path / "out"
    runtime_hash = hashlib.sha256(runtime.read_bytes()).hexdigest()
    retrieval_hash = hashlib.sha256((public / "manifest.json").read_bytes()).hexdigest()
    result = analyze(
        retrieval,
        qa,
        output,
        public_retrieval_dir=public,
        qrels_path=qrels,
        runtime_manifest_path=runtime,
        runtime_stop_attestation_path=stop,
        embedding_preflight_manifest_path=preflight,
        dataset_vector_attestation_path=vector,
        measurement_protocol_attestation_path=measurement,
        public_retrieval_r1_dir=r1,
        public_retrieval_r2_dir=r2,
        provenance={
            "generation_model": "gpt-5.6-luna",
            "judge_model": "gpt-5.4-mini",
            "embedding_alias": "ragz-openai-text-embedding-3-large-d1024",
            "ragflow_version": "v0.27.0",
            "ragflow_commit": "ec9c08d809f63ba2815090182fa225899d2437d5",
            "ragflow_image": "sha256:e9fe71c5ff14762eeb8e251b3b8ed37c02a99ae2bad3d7b11467260ced79578b",
            "proxy_fingerprint_sha256": "e5a2913bf2fe061ba9811d8c102b740230c33ee549cc34e507aa03639200eb31",
            "runtime_manifest_sha256": runtime_hash,
            "retrieval_manifest_sha256": retrieval_hash,
            "documents": 22,
            "chunks": 415,
            "ingestion_concurrency_race": "observed_and_recovered",
            "intentional_app_recovery": True,
        },
    )
    assert result == output
    rows = [json.loads(line) for line in (output / "per_query.jsonl").read_text().splitlines()]
    assert len(rows) == 70
    assert set(rows[0]) == {
        "query_id",
        "answerable",
        "ranked_doc_ids",
        "ranked_scores",
        "retrieval_metrics",
        "judge_metrics",
        "deterministic_metrics",
        "timings_ms",
        "usage",
        "error_codes",
    }
    encoded = (output / "per_query.jsonl").read_text()
    for banned in ("PRIVATE", '"query"', '"answer"', '"content"', '"explanation"'):
        assert banned not in encoded
    summary = json.loads((output / "summary.json").read_text())
    assert summary["denominator"] == {"total": 70, "answerable": 60, "off_corpus": 10, "errors": 0}
    assert summary["calls"] == {"generation": 70, "judge": 70}
    assert summary["latency_ms"]["estimated_noncoincident_combined_total"]["mean"] == pytest.approx(
        66.5
    )
    assert summary["latency_ms"]["estimated_noncoincident_user_facing_retrieval_plus_generation"][
        "mean"
    ] == pytest.approx(45.5)
    assert summary["cost"]["usage_derived_total_usd"] == "0.01904000"
    assert summary["cost"]["upstream_cost_status"] == "invalid_mispriced"
    assert summary["rag_triad"]["context_relevance"]["observations"] == 60
    assert summary["citation_validity"]["observations"] == 60
    assert summary["retrieval_metrics"]["ndcg_at_5"]["observations"] == 60
    assert summary["retrieval_metrics"]["ndcg_at_5"]["mean"] <= 1.0
    assert rows[-1]["retrieval_metrics"] == {}
    assert json.loads((output / "manifest.json").read_text())["provenance"]["chunks"] == 415


def test_analyzer_refuses_overwrite_and_rejects_wrong_denominator(tmp_path: Path) -> None:
    retrieval, qa, public, qrels, runtime, stop, preflight, vector, measurement, r1, r2 = _inputs(
        tmp_path
    )
    output = tmp_path / "out"
    provenance = {
        "generation_model": "gpt-5.6-luna",
        "judge_model": "gpt-5.4-mini",
        "embedding_alias": "ragz-openai-text-embedding-3-large-d1024",
        "ragflow_version": "v0.27.0",
        "ragflow_commit": "ec9c08d809f63ba2815090182fa225899d2437d5",
        "ragflow_image": "sha256:e9fe71c5ff14762eeb8e251b3b8ed37c02a99ae2bad3d7b11467260ced79578b",
        "proxy_fingerprint_sha256": "e5a2913bf2fe061ba9811d8c102b740230c33ee549cc34e507aa03639200eb31",
        "runtime_manifest_sha256": hashlib.sha256(runtime.read_bytes()).hexdigest(),
        "retrieval_manifest_sha256": hashlib.sha256(
            (public / "manifest.json").read_bytes()
        ).hexdigest(),
        "documents": 22,
        "chunks": 415,
    }
    analyze(
        retrieval,
        qa,
        output,
        public_retrieval_dir=public,
        qrels_path=qrels,
        runtime_manifest_path=runtime,
        runtime_stop_attestation_path=stop,
        embedding_preflight_manifest_path=preflight,
        dataset_vector_attestation_path=vector,
        measurement_protocol_attestation_path=measurement,
        public_retrieval_r1_dir=r1,
        public_retrieval_r2_dir=r2,
        provenance=provenance,
    )
    with pytest.raises(FileExistsError):
        analyze(
            retrieval,
            qa,
            output,
            public_retrieval_dir=public,
            qrels_path=qrels,
            runtime_manifest_path=runtime,
            runtime_stop_attestation_path=stop,
            embedding_preflight_manifest_path=preflight,
            dataset_vector_attestation_path=vector,
            measurement_protocol_attestation_path=measurement,
            public_retrieval_r1_dir=r1,
            public_retrieval_r2_dir=r2,
            provenance=provenance,
        )

    bad = tmp_path / "bad.jsonl"
    lines = retrieval.read_text().splitlines()
    bad.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    with pytest.raises(AnalyzerError, match="70"):
        analyze(
            bad,
            qa,
            tmp_path / "bad-out",
            public_retrieval_dir=public,
            qrels_path=qrels,
            runtime_manifest_path=runtime,
            runtime_stop_attestation_path=stop,
            embedding_preflight_manifest_path=preflight,
            dataset_vector_attestation_path=vector,
            measurement_protocol_attestation_path=measurement,
            public_retrieval_r1_dir=r1,
            public_retrieval_r2_dir=r2,
            provenance=provenance,
        )
