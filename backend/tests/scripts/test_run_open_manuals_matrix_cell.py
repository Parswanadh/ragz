import json
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_open_manuals_matrix_cell import (  # noqa: E402
    JUDGE_MODEL,
    LUNA_CACHED_INPUT_PRICE,
    LUNA_INPUT_PRICE,
    LUNA_OUTPUT_PRICE,
    ContractError,
    LiteLLMClient,
    _embedding_price,
    _parser,
    _provider_cost,
    _sanitize_row,
    _summary_cache,
    _validate_query_denominator,
)


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "output_tokens": self.output_tokens,
        }


@dataclass(frozen=True)
class ProviderResponse:
    payload: object
    usage: Usage


class FakeRunner:
    Usage = Usage

    @staticmethod
    def parse_usage(value: object) -> Usage:
        if not isinstance(value, dict):
            return Usage()
        return Usage(
            input_tokens=int(value.get("input_tokens", value.get("prompt_tokens", 0))),
            cached_input_tokens=0,
            output_tokens=int(value.get("output_tokens", value.get("completion_tokens", 0))),
        )

    @staticmethod
    def extract_embeddings(payload: dict[str, object]) -> list[list[float]]:
        return [list(map(float, row["embedding"])) for row in payload["data"]]  # type: ignore[index]

    ProviderResponse = ProviderResponse


def _client(
    handler: object,
    *,
    dimension: int = 3,
    max_retries: int = 0,
) -> LiteLLMClient:
    return LiteLLMClient(
        FakeRunner,
        base_url="http://litellm.test",
        api_key="test-key",
        embedding_alias="ragz-openai-text-embedding-3-small-d3",
        embedding_model="text-embedding-3-small",
        embedding_dimension=dimension,
        max_retries=max_retries,
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
        sleep=lambda _: None,
    )


def test_embedding_call_uses_fixed_alias_and_records_width_usage_and_latency() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = json.loads(request.content)
        assert request.url.path == "/v1/embeddings"
        assert body == {
            "model": "ragz-openai-text-embedding-3-small-d3",
            "input": ["one", "two"],
            "encoding_format": "float",
        }
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 0, "embedding": [1, 0, 0]},
                    {"index": 1, "embedding": [0, 1, 0]},
                ],
                "usage": {"prompt_tokens": 8, "total_tokens": 8},
            },
        )

    client = _client(handler)
    client.embeddings("ragz-openai-text-embedding-3-small-d3", ["one", "two"])

    assert len(requests) == 1
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call.endpoint_type == "embedding"
    assert call.input_count == 2
    assert call.actual_vector_dimension == 3
    assert call.usage["input_tokens"] == 8
    assert call.retries == 0
    assert call.latency_ms >= 0


def test_embedding_width_mismatch_is_rejected_and_mapped() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"data": [{"embedding": [1, 2]}], "usage": {"input_tokens": 1}}
        )

    client = _client(handler, dimension=3)
    with pytest.raises(ContractError, match="width"):
        client.embeddings("ragz-openai-text-embedding-3-small-d3", ["one"])
    assert client.calls[0].error_code == "embedding_width_contract"
    assert client.calls[0].actual_vector_dimension == 2


def test_retry_count_is_recorded_without_persisting_response_body() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, content=b"secret provider body")
        return httpx.Response(
            200, json={"data": [{"embedding": [1, 2, 3]}], "usage": {"input_tokens": 1}}
        )

    client = _client(handler, max_retries=1)
    client.embeddings("ragz-openai-text-embedding-3-small-d3", ["one"])
    assert attempts == 2
    assert client.calls[0].retries == 1
    assert "secret provider body" not in json.dumps(client.calls[0].as_dict())


def test_response_calls_are_typed_generation_and_judge_without_prompt_telemetry() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] in {"gpt-5.6-luna", JUDGE_MODEL}
        return httpx.Response(
            200,
            json={"output_text": "{\"ok\": true}", "usage": {"input_tokens": 4}},
        )

    client = _client(handler)
    client.response(
        model="gpt-5.6-luna",
        system="secret system",
        user="licensed prompt",
        name="rag_answer",
        schema={"type": "object"},
        max_output_tokens=10,
    )
    client.response(
        model=JUDGE_MODEL,
        system="secret judge",
        user="licensed answer",
        name="rag_judge",
        schema={"type": "object"},
        max_output_tokens=10,
    )
    assert [call.endpoint_type for call in client.calls] == ["generation", "judge"]
    assert all(call.input_count == 1 for call in client.calls)
    assert "licensed" not in json.dumps([call.as_dict() for call in client.calls])


@pytest.mark.parametrize(
    "usage", [None, {"input_tokens": 0}, {"input_tokens": "bad"}, {"input_tokens": -1}]
)
def test_every_provider_endpoint_fails_closed_on_invalid_usage(usage: object) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"embedding": [1, 2, 3]}], "usage": usage},
        )

    client = _client(handler)
    with pytest.raises(ContractError, match="usage"):
        client.embeddings("ragz-openai-text-embedding-3-small-d3", ["one"])
    assert client.calls[0].error_code == "usage_contract"


def test_response_rejects_unknown_endpoint_name_and_wrong_endpoint_model_pair() -> None:
    client = _client(lambda _: httpx.Response(200, json={"usage": {"input_tokens": 1}}))
    with pytest.raises(ContractError, match="endpoint name"):
        client.response(
            model="gpt-5.6-luna", system="s", user="u", name="unknown",
            schema={"type": "object"}, max_output_tokens=10,
        )
    with pytest.raises(ContractError, match="model contract"):
        client.response(
            model=JUDGE_MODEL, system="s", user="u", name="rag_answer",
            schema={"type": "object"}, max_output_tokens=10,
        )


def test_publication_defaults_to_separate_judge_and_no_cache() -> None:
    args = _parser().parse_args(
        [
            "--model", "text-embedding-3-small",
            "--dimension", "1024",
            "--dataset", "/private/dataset",
            "--queries", "/private/queries.jsonl",
            "--private-work-dir", "/private/work",
            "--output", "/public/output",
            "--cache-dir", "/private/cache",
            "--env", "/private/env",
            "--litellm-base-url", "http://localhost:54000",
            "--proxy-fingerprint", "a" * 64,
        ]
    )
    assert args.cache_mode == "no-cache"
    assert args.judge_model == JUDGE_MODEL


def test_publication_parser_requires_proxy_fingerprint() -> None:
    with pytest.raises(SystemExit):
        _parser().parse_args(
            [
                "--model", "text-embedding-3-small", "--dimension", "1024",
                "--dataset", "/private/dataset", "--queries", "/private/queries.jsonl",
                "--private-work-dir", "/private/work", "--output", "/public/output",
                "--cache-dir", "/private/cache", "--env", "/private/env",
                "--litellm-base-url", "http://localhost:54000",
            ]
        )


def test_query_denominator_requires_exact_70_with_60_answerable_and_10_off_corpus() -> None:
    cases = [
        SimpleNamespace(query_id=f"q{index:03d}", answerable=index <= 60)
        for index in range(1, 71)
    ]
    assert _validate_query_denominator(cases) == {
        "total": 70,
        "answerable": 60,
        "off_corpus": 10,
    }

    with pytest.raises(ContractError, match="complete"):
        _validate_query_denominator(cases[:-1])


@pytest.mark.parametrize(
    ("model", "expected"),
    [("text-embedding-3-small", "0.02"), ("text-embedding-3-large", "0.13")],
)
def test_embedding_price_tracks_small_vs_large(model: str, expected: str) -> None:
    assert str(_embedding_price(model)) == expected


def test_sanitized_query_record_contains_ids_metrics_timings_only() -> None:
    safe = _sanitize_row(
        {
            "query_id": "q001",
            "required_evidence_ids": ["doc:required"],
            "retrieved": [{"chunk_id": "doc:chunk-1", "text": "licensed source"}],
            "answer": {"answer": "licensed answer"},
            "deterministic_metrics": {"citation_validity": 1.0},
            "judge": {"groundedness": 1.0, "explanation": "licensed reasoning"},
            "metadata": {
                "answerable": True,
                "timings_ms": {"total": 8.1},
                "evidence": ["licensed"],
            },
            "usage": {"generation": {"input_tokens": 4}},
            "errors": [],
        }
    )
    encoded = json.dumps(safe)
    assert "licensed" not in encoded
    assert safe["metrics"]["retrieval_required_document_hit_count"] == 1
    assert safe["metrics"]["retrieval_required_document_count"] == 1
    assert safe["metrics"]["retrieval_required_document_coverage"] == 1.0
    assert set(safe) == {
        "query_id", "answerable", "retrieved_ids", "metrics", "judge",
        "timings_ms", "usage", "error_codes",
    }


def test_required_evidence_is_reported_as_document_level() -> None:
    safe = _sanitize_row(
        {
            "query_id": "q001",
            "required_evidence_ids": ["manual-a:chunk-0001", "manual-a:chunk-0002"],
            "retrieved": [
                {"chunk_id": "manual-a:chunk-0007", "text": "licensed source"},
                {"chunk_id": "manual-b:chunk-0001", "text": "licensed source"},
            ],
            "deterministic_metrics": {},
            "metadata": {"answerable": True},
        }
    )
    assert safe["metrics"] == {
        "retrieval_required_document_hit_count": 1,
        "retrieval_required_document_count": 1,
        "retrieval_required_document_coverage": 1.0,
    }


def test_provider_cost_uses_model_rate_and_luna_cached_input_rate() -> None:
    calls = [
        {
            "endpoint_type": "embedding",
            "model": "ragz-openai-text-embedding-3-small-d1024",
            "usage": {"input_tokens": 1_000_000, "cached_input_tokens": 0, "output_tokens": 0},
        },
        {
            "endpoint_type": "embedding",
            "model": "ragz-openai-text-embedding-3-large-d1024",
            "usage": {"input_tokens": 1_000_000, "cached_input_tokens": 0, "output_tokens": 0},
        },
        {
            "endpoint_type": "generation",
            "model": "gpt-5.6-luna",
            "usage": {
                "input_tokens": 1_000_000,
                "cached_input_tokens": 250_000,
                "output_tokens": 1_000_000,
            },
        },
        {
            "endpoint_type": "judge",
            "model": JUDGE_MODEL,
            "usage": {
                "input_tokens": 1_000_000,
                "cached_input_tokens": 200_000,
                "output_tokens": 1_000_000,
            },
        },
    ]
    result = _provider_cost(calls)
    expected_luna = (
        750_000 * LUNA_INPUT_PRICE / 1_000_000
        + 250_000 * LUNA_CACHED_INPUT_PRICE / 1_000_000
        + 1_000_000 * LUNA_OUTPUT_PRICE / 1_000_000
    )
    expected_judge = (
        800_000 * Decimal("0.75") / 1_000_000
        + 200_000 * Decimal("0.075") / 1_000_000
        + 1_000_000 * Decimal("4.50") / 1_000_000
    )
    assert result["actual_provider_cost_usd"] == str(
        _embedding_price("text-embedding-3-small")
        + _embedding_price("text-embedding-3-large")
        + expected_luna
        + expected_judge
    )
    assert result["basis"] == "provider_calls_usage_only"


def test_cache_summary_has_separate_cached_and_uncached_denominators() -> None:
    summary = _summary_cache(
        {"chunk_embeddings": 2, "query_embeddings": 3, "generation": 4, "judge": 5},
        total_chunks=10,
        total_queries=20,
        mode="shared-cache-exploratory",
    )
    assert summary["mode"] == "shared-cache-exploratory"
    assert summary["publication_eligible"] is False
    assert summary["denominators"]["generation"] == {
        "total": 20,
        "cached": 4,
        "uncached": 16,
    }


def test_cache_mode_rejects_unlabelled_shared_cache() -> None:
    from run_open_manuals_matrix_cell import _validate_cache_mode

    assert _validate_cache_mode("no-cache") == "no-cache"
    with pytest.raises(ContractError, match="shared-cache-exploratory"):
        _validate_cache_mode("shared-cache")
