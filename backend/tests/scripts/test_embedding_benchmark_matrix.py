import json
import sys
from pathlib import Path

import httpx
import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from embedding_benchmark_matrix import (  # noqa: E402
    AliasConflictError,
    CredentialUnavailableError,
    InvalidEmbeddingCellError,
    LiteLLMAPIError,
    VectorWidthProbeError,
    build_manifest,
    cell_for,
    cells,
    preflight_aliases,
    probe_vector_width,
    write_manifest,
)


def test_matrix_contains_only_the_supported_small_and_large_cells() -> None:
    matrix = cells()

    assert [(cell.model, cell.dimension) for cell in matrix] == [
        ("text-embedding-3-small", 1024),
        ("text-embedding-3-small", 1280),
        ("text-embedding-3-small", 1536),
        ("text-embedding-3-large", 1024),
        ("text-embedding-3-large", 1280),
        ("text-embedding-3-large", 1536),
        ("text-embedding-3-large", 1792),
        ("text-embedding-3-large", 2048),
        ("text-embedding-3-large", 2096),
        ("text-embedding-3-large", 3072),
    ]
    assert all("medium" not in cell.model for cell in matrix)
    assert len({cell.cell_id for cell in matrix}) == len(matrix)
    assert len({cell.alias for cell in matrix}) == len(matrix)


def test_cell_ids_and_aliases_are_stable() -> None:
    first = cells()
    second = cells()

    assert [(cell.cell_id, cell.alias) for cell in first] == [
        (cell.cell_id, cell.alias) for cell in second
    ]
    assert first[0].cell_id == "openai-text-embedding-3-small-d1024"
    assert first[0].alias == "ragz-openai-text-embedding-3-small-d1024"


@pytest.mark.parametrize(
    ("model", "dimension"),
    [
        ("text-embedding-3-medium", 1024),
        ("text-embedding-3-small", 1792),
        ("text-embedding-3-large", 1537),
        ("text-embedding-3-large", 0),
    ],
)
def test_invalid_model_dimension_pairs_are_typed(
    model: str, dimension: int
) -> None:
    with pytest.raises(InvalidEmbeddingCellError):
        cell_for(model, dimension)


def test_missing_master_key_is_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAGZ_LITELLM_MASTER_KEY", raising=False)
    monkeypatch.delenv("LITELLM_MASTER_KEY", raising=False)

    with pytest.raises(CredentialUnavailableError):
        preflight_aliases(cells()[:1], base_url="http://litellm.test")


def test_missing_provider_key_is_typed_without_echoing_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAGZ_LITELLM_MASTER_KEY", "test-master-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_EMBEDDING_API_KEY", raising=False)

    with pytest.raises(CredentialUnavailableError, match="OPENAI_API_KEY") as error:
        preflight_aliases(cells()[:1], base_url="http://litellm.test")

    assert "test-master-key" not in str(error.value)


def test_dry_run_never_constructs_or_calls_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAGZ_LITELLM_MASTER_KEY", "test-master-key")

    def fail(_: httpx.Request) -> httpx.Response:
        raise AssertionError("dry run must not call LiteLLM")

    result = preflight_aliases(
        cells()[:2],
        base_url="http://litellm.test",
        dry_run=True,
        transport=httpx.MockTransport(fail),
    )

    assert [item.status for item in result] == ["would_create", "would_create"]
    assert all(item.proxy_calls == 0 for item in result)


def test_existing_matching_alias_is_idempotent_without_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAGZ_LITELLM_MASTER_KEY", "test-master-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-provider-key")
    cell = cells()[0]
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        assert request.url.path == "/model/info"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "model_name": cell.alias,
                        "litellm_params": {
                            "model": f"openai/{cell.model}",
                            "dimensions": cell.dimension,
                        },
                    }
                ]
            },
        )

    result = preflight_aliases(
        [cell],
        base_url="http://litellm.test/",
        transport=httpx.MockTransport(handler),
    )

    assert result[0].status == "present"
    assert result[0].proxy_calls == 1
    assert calls == ["GET"]


def test_conflicting_alias_is_rejected_without_overwrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAGZ_LITELLM_MASTER_KEY", "test-master-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-provider-key")
    cell = cells()[0]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "model_name": cell.alias,
                            "litellm_params": {
                                "model": "openai/text-embedding-3-large",
                                "dimensions": 3072,
                            },
                        }
                    ]
                },
            )
        raise AssertionError("conflicts must not be overwritten")

    with pytest.raises(AliasConflictError):
        preflight_aliases(
            [cell],
            base_url="http://litellm.test",
            transport=httpx.MockTransport(handler),
        )


def test_missing_alias_is_created_with_fixed_width_and_no_client_dimension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAGZ_LITELLM_MASTER_KEY", "test-master-key")
    provider_key = "test-provider-key"
    monkeypatch.setenv("OPENAI_API_KEY", provider_key)
    cell = cells()[5]
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"data": []})
        body = json.loads(request.content)
        assert request.url.path == "/model/new"
        assert body["model_name"] == cell.alias
        assert body["litellm_params"] == {
            "model": f"openai/{cell.model}",
            "api_key": provider_key,
            "dimensions": cell.dimension,
        }
        assert body["model_info"]["ragz_cell_id"] == cell.cell_id
        assert body["model_info"]["id"] == cell.cell_id
        return httpx.Response(200, json={"status": "success"})

    result = preflight_aliases(
        [cell],
        base_url="http://litellm.test",
        transport=httpx.MockTransport(handler),
    )

    assert result[0].status == "created"
    assert result[0].proxy_calls == 2
    assert [request.method for request in requests] == ["GET", "POST"]
    assert provider_key not in json.dumps(build_manifest([cell]))


def test_preflight_falls_back_to_v2_model_info_after_legacy_server_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAGZ_LITELLM_MASTER_KEY", "test-master-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-provider-key")
    cell = cells()[0]
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/model/info":
            return httpx.Response(500)
        if request.url.path == "/v2/model/info":
            return httpx.Response(200, json={"data": []})
        return httpx.Response(200, json={"status": "success"})

    [result] = preflight_aliases(
        [cell],
        base_url="http://litellm.test",
        transport=httpx.MockTransport(handler),
    )

    assert result.status == "created"
    assert paths == ["/model/info", "/v2/model/info", "/model/new"]


def test_alias_create_failure_body_is_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAGZ_LITELLM_MASTER_KEY", "test-master-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-provider-key")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"data": []})
        return httpx.Response(200, json={"status": "failure"})

    with pytest.raises(LiteLLMAPIError, match="reported failure"):
        preflight_aliases(
            [cells()[0]],
            base_url="http://litellm.test",
            transport=httpx.MockTransport(handler),
        )


def test_probe_posts_alias_only_and_validates_one_vector_width(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAGZ_LITELLM_MASTER_KEY", "test-master-key")
    cell = cells()[2]

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.url.path == "/v1/embeddings"
        assert body == {"model": cell.alias, "input": ["ragz synthetic width probe"]}
        return httpx.Response(200, json={"data": [{"embedding": [0.0] * cell.dimension}]})

    result = probe_vector_width(
        cell,
        base_url="http://litellm.test",
        transport=httpx.MockTransport(handler),
    )

    assert result.expected_dimension == cell.dimension
    assert result.actual_dimension == cell.dimension
    assert result.vector_count == 1
    assert result.provider_calls == 1


def test_probe_width_mismatch_is_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAGZ_LITELLM_MASTER_KEY", "test-master-key")
    cell = cells()[0]

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"embedding": [0.0]}]})

    with pytest.raises(VectorWidthProbeError, match="expected"):
        probe_vector_width(
            cell,
            base_url="http://litellm.test",
            transport=httpx.MockTransport(handler),
        )


def test_manifest_and_writer_never_persist_credentials(tmp_path: Path) -> None:
    provider_key = "sk-provider-secret"
    manifest = build_manifest(
        cells()[:1],
        status="dry_run",
        provider_calls=0,
        proxy_calls=0,
        proxy_fingerprint="a" * 64,
    )
    destination = write_manifest(tmp_path, manifest)
    serialized = destination.read_text(encoding="utf-8")

    assert manifest["schema_version"] == 1
    assert manifest["credentials_persisted"] is False
    assert manifest["embedding_proxy_fingerprint_sha256"] == "a" * 64
    assert manifest["cells"][0]["embedding_proxy_fingerprint_sha256"] == "a" * 64
    assert "test-master-key" not in serialized
    assert provider_key not in serialized
    assert json.loads(serialized)["cells"][0]["alias"] == cells()[0].alias


def test_manifest_rejects_malformed_proxy_fingerprint() -> None:
    with pytest.raises(ValueError, match="proxy fingerprint"):
        build_manifest(cells()[:1], proxy_fingerprint="not-a-sha")
