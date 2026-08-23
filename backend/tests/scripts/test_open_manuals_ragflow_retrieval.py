from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

R6_COMMIT = "ec9c08d809f63ba2815090182fa225899d2437d5"
R6_IMAGE_DIGEST = "sha256:e9fe71c5ff14762eeb8e251b3b8ed37c02a99ae2bad3d7b11467260ced79578b"

from run_open_manuals_ragflow_retrieval import (  # noqa: E402
    ContractError,
    RetrievalConfig,
    dedupe_ranked_documents,
    load_dataset,
    mrr_at_5,
    ndcg_at_5,
    recall_at_5,
    run_benchmark,
    sha256_file,
)


class FakeResponse:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self) -> object:
        return self.payload


class FakeClient:
    def __init__(self, docs: Sequence[Mapping[str, object]]) -> None:
        self.docs = list(docs)
        self.posts: list[tuple[str, Mapping[str, object], Mapping[str, object]]] = []

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, object],
        headers: Mapping[str, str] | None = None,
    ) -> FakeResponse:
        assert url.endswith("/api/v1/datasets/dataset-1/documents")
        assert params == {"page": 1, "page_size": 100}
        assert headers is not None and headers["Authorization"] == "Bearer private-token"
        return FakeResponse({"code": 0, "data": {"docs": self.docs}})

    def post(
        self, url: str, *, headers: Mapping[str, str], json: Mapping[str, object]
    ) -> FakeResponse:
        self.posts.append((url, headers, json))
        assert url.endswith("/api/v1/retrieval")
        assert headers["Authorization"] == "Bearer private-token"
        assert json["page_size"] == 5
        assert json["top_k"] == 50
        assert json["vector_similarity_weight"] == 1.0
        assert json["similarity_threshold"] == 0.0
        assert json["keyword"] is False
        return FakeResponse(
            {
                "code": 0,
                "data": {
                    "chunks": [
                        {
                            "document_id": "remote-01",
                            "similarity": 0.9,
                            "content": "must not be persisted",
                        },
                        {"document_id": "remote-01", "similarity": 0.8},
                        {"document_keyword": "manual-02.pdf", "similarity": 0.7},
                    ]
                },
            }
        )


def _dataset(tmp_path: Path) -> Path:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    with (dataset / "documents.jsonl").open("w", encoding="utf-8") as handle:
        for index in range(1, 23):
            json.dump({"doc_id": f"doc-{index:02d}", "filename": f"manual-{index:02d}.pdf"}, handle)
            handle.write("\n")
    with (dataset / "queries.jsonl").open("w", encoding="utf-8") as handle:
        for index in range(1, 71):
            row: dict[str, object] = {
                "query_id": f"q{index:03d}",
                "question": f"question {index}",
                "answerable": index <= 60,
            }
            if index <= 60:
                row["required_document_ids"] = ["doc-01"]
            json.dump(row, handle)
            handle.write("\n")
    (dataset / "qrels.jsonl").write_text("", encoding="utf-8")
    return dataset


def _config(tmp_path: Path, dataset: Path) -> RetrievalConfig:
    token = tmp_path / "token"
    token.write_text("private-token\n", encoding="utf-8")
    token.chmod(0o600)
    dataset_id = tmp_path / "dataset-id"
    dataset_id.write_text("dataset-1\n", encoding="utf-8")
    dataset_id.chmod(0o600)
    runtime_manifest = tmp_path / "ragflow-native-daemon-swap-smoke-20260823-r6" / "manifest.json"
    runtime_manifest.parent.mkdir()
    runtime_manifest.write_text(
        json.dumps(
            {
                "status": "smoke_passed",
                "memory_limit_bytes": 5_000_000_000,
                "stack_left_running": False,
                "post_smoke_stop": {
                    "containers_left_running": 0,
                    "stop_scope": "compose_project_only",
                },
                "commit": R6_COMMIT,
                "app_service": "ragflow-cpu",
                "image_provenance": [
                    {"role": "app", "service": "ragflow-cpu", "digest": R6_IMAGE_DIGEST}
                ],
            }
        ),
        encoding="utf-8",
    )
    return RetrievalConfig(
        base_url="http://ragflow.test",
        auth_token_file=token,
        dataset_id_file=dataset_id,
        dataset_dir=dataset,
        private_output_dir=tmp_path / "private",
        public_output_dir=tmp_path / "public",
        expected_model_alias="text-embedding-3-small",
        expected_dimension=1536,
        expected_proxy_fingerprint="a" * 64,
        expected_source_commit=R6_COMMIT,
        expected_image_digest=R6_IMAGE_DIGEST,
        runtime_manifest=runtime_manifest,
    )


def test_document_metrics_dedupe_chunk_ranking_before_scoring() -> None:
    ranked, scores = dedupe_ranked_documents(
        [("doc-a", 0.9), ("doc-a", 0.8), ("doc-b", 0.7), ("doc-c", 0.6)]
    )
    assert ranked == ["doc-a", "doc-b", "doc-c"]
    assert scores == [0.9, 0.7, 0.6]
    required = {"doc-a", "doc-b"}
    assert recall_at_5(required, ranked) == 1.0
    assert mrr_at_5(required, ranked) == 1.0
    assert ndcg_at_5(required, ranked) == pytest.approx(1.0)


def test_dataset_loader_enforces_locked_denominator(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path)
    loaded = load_dataset(dataset)
    assert len(loaded.documents) == 22
    assert len(loaded.queries) == 70
    assert sum(query.answerable for query in loaded.queries) == 60


def test_runner_preflights_maps_documents_and_writes_privacy_safe_artifacts(
    tmp_path: Path,
) -> None:
    dataset = _dataset(tmp_path)
    docs = [
        {"id": f"remote-{index:02d}", "name": f"manual-{index:02d}.pdf", "run": "DONE"}
        for index in range(1, 23)
    ]
    client = FakeClient(docs)
    output = run_benchmark(_config(tmp_path, dataset), client=client)

    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "completed"
    assert summary["denominator"] == {
        "total": 70,
        "answerable": 60,
        "off_corpus": 10,
        "errors": 0,
    }
    assert summary["preflight"] == {
        "documents_expected": 22,
        "documents_mapped": 22,
        "all_done": True,
    }
    assert summary["latency_ms"]["observations"] == 70
    assert summary["latency_ms"]["mean"] >= 0
    rows = [json.loads(line) for line in (output / "per_query.jsonl").read_text().splitlines()]
    assert len(rows) == 70
    assert rows[0]["ranked_doc_ids"] == ["doc-01", "doc-02"]
    assert rows[0]["ranked_scores"] == [0.9, 0.7]
    serialized = (output / "per_query.jsonl").read_text(encoding="utf-8")
    assert "question 1" not in serialized
    assert "must not be persisted" not in serialized
    assert "private-token" not in serialized
    assert len(client.posts) == 70


def test_runner_refuses_non_done_preflight(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path)
    docs = [
        {"id": f"remote-{index:02d}", "name": f"manual-{index:02d}.pdf", "run": "DONE"}
        for index in range(1, 22)
    ] + [{"id": "remote-22", "name": "manual-22.pdf", "run": "UNSTARTED"}]
    with pytest.raises(ContractError, match="DONE"):
        run_benchmark(_config(tmp_path, dataset), client=FakeClient(docs))


def test_runner_rejects_runtime_manifest_provenance_mismatch(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path)
    config = _config(tmp_path, dataset)
    config.runtime_manifest.write_text(
        json.dumps(
            {
                "status": "smoke_passed",
                "memory_limit_bytes": 5_000_000_000,
                "stack_left_running": False,
                "post_smoke_stop": {
                    "containers_left_running": 0,
                    "stop_scope": "compose_project_only",
                },
                "commit": "d" * 40,
                "app_service": "ragflow-cpu",
                "image_provenance": [
                    {
                        "role": "app",
                        "service": "ragflow-cpu",
                        "digest": config.expected_image_digest,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ContractError, match="source commit"):
        run_benchmark(config, client=FakeClient([]))


def _warmup_artifact(
    root: Path, *, name: str = "warmup-1", queries: int = 70, status: str = "completed"
) -> Path:
    artifact = root / name
    artifact.mkdir()
    rows = [
        {"query_id": f"q{index:03d}", "ranked_doc_ids": [], "ranked_scores": [], "error_codes": []}
        for index in range(1, queries + 1)
    ]
    (artifact / "per_query.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8"
    )
    metadata = {
        "status": status,
        "denominator": {"total": 70, "answerable": 60, "off_corpus": 10, "errors": 0},
    }
    (artifact / "manifest.json").write_text(json.dumps(metadata), encoding="utf-8")
    (artifact / "summary.json").write_text(json.dumps(metadata), encoding="utf-8")
    return artifact


def test_runner_validates_and_records_repeated_warmup_artifacts_and_hashes(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path)
    config = _config(tmp_path, dataset)
    warmup = _warmup_artifact(tmp_path)
    warmup_two = _warmup_artifact(tmp_path, name="warmup-2")
    config = replace(config, warmup_artifacts=(warmup, warmup_two))
    docs = [
        {"id": f"remote-{index:02d}", "name": f"manual-{index:02d}.pdf", "run": "DONE"}
        for index in range(1, 23)
    ]
    output = run_benchmark(config, client=FakeClient(docs))
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert manifest["warmups_per_query"] == 2
    assert [item["name"] for item in manifest["warmup_artifacts"]] == ["warmup-1", "warmup-2"]
    assert manifest["provenance"]["source_commit"] == R6_COMMIT
    assert manifest["provenance"]["image_digest"] == R6_IMAGE_DIGEST
    assert manifest["warmup_protocol"]["cache_reset"] is False
    assert manifest["provenance"]["runtime_manifest_sha256"] == sha256_file(config.runtime_manifest)
    assert manifest["provenance"]["qrels_sha256"] == sha256_file(dataset / "qrels.jsonl")
    assert manifest["artifact_integrity"]["per_query_sha256"] == sha256_file(
        output / "per_query.jsonl"
    )
    assert manifest["artifact_integrity"]["summary_sha256"] == sha256_file(output / "summary.json")
    assert (
        "artifact_integrity" not in summary or "summary_sha256" not in summary["artifact_integrity"]
    )
    assert (
        summary["artifact_integrity"]["per_query_sha256"]
        == manifest["artifact_integrity"]["per_query_sha256"]
    )


def test_runner_rejects_incomplete_warmup_artifact(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path)
    config = _config(tmp_path, dataset)
    warmup = _warmup_artifact(tmp_path, queries=69)
    with pytest.raises(ContractError, match="70"):
        run_benchmark(replace(config, warmup_artifacts=(warmup,)), client=FakeClient([]))
