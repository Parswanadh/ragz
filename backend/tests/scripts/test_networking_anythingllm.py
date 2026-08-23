import hashlib
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_networking_anythingllm import (  # noqa: E402
    _command,
    _dataset_identity,
    _required_litellm_api_key,
    batches,
    embedding_attestation,
    embedding_configuration,
    generation_configuration,
    ranking_metrics,
    safe_http_status,
    summarize,
    unique_document_ids,
    validate_storage_path,
    vector_search_with_retries,
    workspace_configuration,
)


def test_safe_http_status_extracts_status_without_response_body() -> None:
    import httpx

    request = httpx.Request("POST", "http://anything.test/vector-search")
    response = httpx.Response(500, request=request, text="sensitive provider detail")
    error = httpx.HTTPStatusError("failed", request=request, response=response)

    assert safe_http_status(error) == 500
    assert safe_http_status(RuntimeError("not HTTP")) is None


@pytest.mark.asyncio
async def test_vector_search_retries_transient_status_and_reports_count() -> None:
    import httpx

    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        status = 500 if attempts == 1 else 200
        return httpx.Response(status, request=request, json={"results": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response, retries = await vector_search_with_retries(
            client,
            "http://anything.test/vector-search",
            {"query": "safe synthetic query"},
            max_retries=2,
        )

    assert response.status_code == 200
    assert retries == 1
    assert attempts == 2


def test_batches_cover_values_once_and_reject_zero() -> None:
    assert list(batches(list(range(10)), 4)) == [
        [0, 1, 2, 3],
        [4, 5, 6, 7],
        [8, 9],
    ]
    with pytest.raises(ValueError):
        list(batches([1], 0))


def test_ranking_metrics_deduplicate_repeated_segments() -> None:
    metrics = ranking_metrics(["a", "a", "x", "b"], {"a", "b"}, 3)
    assert metrics["recall_at_k"] == 1.0
    assert metrics["mrr_at_k"] == 1.0
    assert 0 < metrics["ndcg_at_k"] <= 1.0


def test_summary_excludes_off_corpus_and_errors_from_quality() -> None:
    records = [
        {
            "answerable": True,
            "error": None,
            "metrics": {"recall_at_k": 1.0, "mrr_at_k": 0.5, "ndcg_at_k": 0.75},
            "no_answer": False,
            "latency_ms": 10.0,
        },
        {
            "answerable": False,
            "error": None,
            "metrics": None,
            "no_answer": True,
            "latency_ms": 20.0,
        },
        {
            "answerable": True,
            "error": "RemoteProtocolError",
            "metrics": None,
            "no_answer": False,
            "latency_ms": 30.0,
        },
    ]

    result = summarize(records, top_k=5)

    assert result["quality_observations"] == 1
    assert result["mean_recall_at_k"] == 1.0
    assert result["abstention"]["f1"] == 1.0
    assert result["errors"] == 1


def test_storage_must_be_unique_child_of_explicit_root(tmp_path: Path) -> None:
    child = tmp_path / "run-1"
    assert validate_storage_path(child, tmp_path) == (child, tmp_path)
    with pytest.raises(ValueError):
        validate_storage_path(tmp_path, tmp_path)
    with pytest.raises(ValueError):
        validate_storage_path(tmp_path.parent / "outside", tmp_path)


def test_embedding_configuration_labels_hosted_and_native_tracks() -> None:
    native = embedding_configuration("native")
    hosted = embedding_configuration("litellm")
    assert "native-minilm" in native[1]
    assert native[2:] == (0, 0.0)
    assert "openai" in hosted[1]
    assert hosted[2:] == ("not_exposed_nonzero", None)
    with pytest.raises(ValueError):
        embedding_configuration("unknown")


def test_litellm_configuration_uses_fixed_matrix_alias_and_requested_cell() -> None:
    configuration = embedding_configuration(
        "litellm", model="text-embedding-3-large", dimension=2096
    )

    assert "EMBEDDING_ENGINE=litellm" in configuration[0]
    assert "EMBEDDING_MODEL_PREF=ragz-openai-text-embedding-3-large-d2096" in configuration[0]
    assert "LITE_LLM_API_KEY" in configuration[0]
    assert not any(value.startswith("LITE_LLM_API_KEY=") for value in configuration[0])
    assert configuration[1] == "common-20-page-segments-openai-lancedb"


def test_litellm_configuration_rejects_invalid_matrix_cell() -> None:
    with pytest.raises(ValueError, match="unsupported embedding cell"):
        embedding_configuration("litellm", model="text-embedding-3-medium", dimension=1536)


def test_width_attestation_binds_alias_model_dimension_and_proxy(tmp_path: Path) -> None:
    path = tmp_path / "width.json"
    path.write_text(
        json.dumps(
            {
                "alias": "ragz-openai-text-embedding-3-small-d1024",
                "model": "text-embedding-3-small",
                "dimension": 1024,
                "actual_dimension": 1024,
                "probe_status": "passed",
                "embedding_proxy_fingerprint_sha256": "a" * 64,
            }
        ),
        encoding="utf-8",
    )

    result = embedding_attestation(
        path,
        model="text-embedding-3-small",
        dimension=1024,
        alias="ragz-openai-text-embedding-3-small-d1024",
        proxy_fingerprint="a" * 64,
    )

    assert result["actual_dimension"] == 1024
    assert result["artifact_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_width_attestation_rejects_unattested_alias(tmp_path: Path) -> None:
    path = tmp_path / "width.json"
    path.write_text(
        json.dumps(
            {
                "alias": "ragz-openai-text-embedding-3-small-d1024",
                "model": "text-embedding-3-small",
                "dimension": 1024,
                "actual_dimension": 1024,
                "probe_status": "passed",
                "embedding_proxy_fingerprint_sha256": "b" * 64,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="proxy fingerprint"):
        embedding_attestation(
            path,
            model="text-embedding-3-small",
            dimension=1024,
            alias="ragz-openai-text-embedding-3-small-d1024",
            proxy_fingerprint="a" * 64,
        )


def test_width_attestation_rejects_missing_successful_probe(tmp_path: Path) -> None:
    path = tmp_path / "width.json"
    path.write_text(
        json.dumps(
            {
                "alias": "ragz-openai-text-embedding-3-small-d1024",
                "model": "text-embedding-3-small",
                "dimension": 1024,
                "actual_dimension": 1024,
                "embedding_proxy_fingerprint_sha256": "a" * 64,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not successful"):
        embedding_attestation(
            path,
            model="text-embedding-3-small",
            dimension=1024,
            alias="ragz-openai-text-embedding-3-small-d1024",
            proxy_fingerprint="a" * 64,
        )


def test_matrix_probe_manifest_can_attest_fixed_alias(tmp_path: Path) -> None:
    path = tmp_path / "matrix.json"
    path.write_text(
        json.dumps(
            {
                "cells": [
                    {
                        "alias": "ragz-openai-text-embedding-3-large-d2096",
                        "model": "text-embedding-3-large",
                        "dimension": 2096,
                        "actual_dimension": 2096,
                        "probe_status": "passed",
                        "embedding_proxy_fingerprint_sha256": "a" * 64,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = embedding_attestation(
        path,
        model="text-embedding-3-large",
        dimension=2096,
        alias="ragz-openai-text-embedding-3-large-d2096",
        proxy_fingerprint="a" * 64,
    )

    assert result["actual_dimension"] == 2096


def test_width_attestation_rejects_missing_proxy_fingerprint(tmp_path: Path) -> None:
    path = tmp_path / "width.json"
    path.write_text(
        json.dumps(
            {
                "alias": "ragz-openai-text-embedding-3-small-d1024",
                "model": "text-embedding-3-small",
                "dimension": 1024,
                "actual_dimension": 1024,
                "probe_status": "passed",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="proxy fingerprint"):
        embedding_attestation(
            path,
            model="text-embedding-3-small",
            dimension=1024,
            alias="ragz-openai-text-embedding-3-small-d1024",
            proxy_fingerprint="a" * 64,
        )


def test_dataset_identity_prefers_converted_manifest_metadata(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "dataset_id": "open-manuals-v2",
                "counts": {"documents": 77, "queries": 42, "qrels": 99},
            }
        ),
        encoding="utf-8",
    )

    identity = _dataset_identity(
        tmp_path,
        [{"doc_id": "actual"}],
        [{"query_id": "actual"}],
        [{"query_id": "actual", "doc_id": "actual"}],
    )

    assert identity["dataset_id"] == "open-manuals-v2"
    assert identity["document_count"] == 77
    assert identity["query_count"] == 42
    assert identity["qrel_count"] == 99


def test_generation_configuration_pins_shared_litellm_answer_model() -> None:
    configuration = generation_configuration()

    assert "LLM_PROVIDER=litellm" in configuration
    assert "LITE_LLM_MODEL_PREF=gpt-5.6-luna" in configuration
    assert "LITE_LLM_MODEL_TOKEN_LIMIT=8192" in configuration
    assert "host.docker.internal:host-gateway" in configuration
    assert "LITE_LLM_API_KEY" in configuration
    assert not any(value.startswith("LITE_LLM_API_KEY=") for value in configuration)


def test_litellm_key_is_required_and_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAGZ_LITELLM_MASTER_KEY", "env-only-value")
    assert _required_litellm_api_key() == "env-only-value"

    monkeypatch.delenv("RAGZ_LITELLM_MASTER_KEY")
    monkeypatch.delenv("LITELLM_MASTER_KEY", raising=False)
    with pytest.raises(RuntimeError, match="required for LiteLLM"):
        _required_litellm_api_key()


def test_command_passes_credentials_only_through_subprocess_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(*args: object, **kwargs: object) -> object:
        captured["args"] = args
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("subprocess.run", fake_run)
    _command(
        ["docker", "run", "-e", "LITE_LLM_API_KEY"],
        env={"LITE_LLM_API_KEY": "env-only-value"},
    )

    assert captured["env"] == {"LITE_LLM_API_KEY": "env-only-value"}
    assert captured["args"] == (["docker", "run", "-e", "LITE_LLM_API_KEY"],)


def test_workspace_configuration_pins_luna_supported_temperature() -> None:
    configuration = workspace_configuration("networking-test", 50)

    assert configuration == {
        "name": "networking-test",
        "similarityThreshold": 0.0,
        "topN": 50,
        "openAiTemp": 1.0,
    }


def test_abstention_f1_is_zero_when_every_off_corpus_probe_is_missed() -> None:
    result = summarize(
        [
            {
                "answerable": False,
                "error": None,
                "metrics": None,
                "no_answer": False,
                "latency_ms": 1.0,
            }
        ],
        top_k=5,
    )
    assert result["abstention"]["f1"] == 0.0


def test_unique_intervals_are_filled_from_deeper_native_candidates() -> None:
    results = [
        {"metadata": {"docSource": value}}
        for value in ("a", "a", "a", "b", "b", "c", "d", "e", "f")
    ]
    assert unique_document_ids(results, 5) == ["a", "b", "c", "d", "e"]
