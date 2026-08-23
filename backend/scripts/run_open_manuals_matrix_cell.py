#!/usr/bin/env python3
"""Run one privacy-safe Open Manuals embedding matrix cell.

The benchmark implementation remains the read-only OpenAI QA runner in the
separate benchmark-lab checkout.  This adapter supplies a LiteLLM client,
pins one immutable embedding alias, and exports only aggregate and ID/metric
records.  The runner's raw checkpoint files and content-addressed cache must
live below the explicitly supplied private work directory.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import statistics
import sys
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any, Literal, cast

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_RUNNER = Path(
    "/home/parshu/projects/ragz/no_rel/ragz-benchmark-lab/scripts/run_openai_qa.py"
)
DEFAULT_DATASET = Path(
    "/home/parshu/projects/ragz/no_rel/ragz-benchmark-lab/datasets/open-manuals-v2"
)
DEFAULT_QUERIES = DEFAULT_DATASET / "queries.jsonl"
GENERATION_MODEL = "gpt-5.6-luna"
JUDGE_MODEL = "gpt-5.4-mini"
SMALL_EMBEDDING_PRICE = Decimal("0.02")
LARGE_EMBEDDING_PRICE = Decimal("0.13")
LUNA_INPUT_PRICE = Decimal("0.20")
LUNA_CACHED_INPUT_PRICE = Decimal("0.02")
LUNA_OUTPUT_PRICE = Decimal("1.20")
JUDGE_INPUT_PRICE = Decimal("0.75")
JUDGE_CACHED_INPUT_PRICE = Decimal("0.075")
JUDGE_OUTPUT_PRICE = Decimal("4.50")
CacheMode = Literal["no-cache", "shared-cache-exploratory"]
EXPECTED_QUERY_IDS = tuple(f"q{index:03d}" for index in range(1, 71))
RETRY_STATUSES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


class CellRunError(RuntimeError):
    """A safe, non-provider-body benchmark failure."""


class ContractError(CellRunError):
    """The matrix, dataset, provider, or output contract was violated."""


@dataclass
class ProviderCall:
    """Privacy-safe telemetry for one logical provider operation."""

    sequence: int
    endpoint_type: str
    endpoint: str
    model: str
    input_count: int
    actual_vector_dimension: int | None
    latency_ms: float
    usage: dict[str, int]
    retries: int
    error_code: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "endpoint_type": self.endpoint_type,
            "endpoint": self.endpoint,
            "model": self.model,
            "input_count": self.input_count,
            "actual_vector_dimension": self.actual_vector_dimension,
            "latency_ms": round(self.latency_ms, 4),
            "usage": dict(self.usage),
            "retries": self.retries,
            "error_code": self.error_code,
        }


def _load_module(path: Path, name: str) -> ModuleType:
    path = path.resolve()
    if not path.is_file():
        raise CellRunError(f"benchmark runner does not exist: {path}")
    scripts = str(path.parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise CellRunError("unable to load benchmark runner")
    module = importlib.util.module_from_spec(spec)
    # Dataclasses and postponed annotations resolve their module through
    # sys.modules while the dynamically loaded module is executing.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise CellRunError(f"unable to hash input: {path}") from exc
    return digest.hexdigest()


def _percentile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _safe_error_code(value: object) -> str:
    """Map runner/provider errors without copying diagnostic text."""

    text = str(value or "").lower()
    if "budget" in text or "spend" in text:
        return "budget_exceeded"
    if "embedding" in text and "width" in text:
        return "embedding_width_contract"
    if "http" in text or "network" in text or "provider" in text:
        return "provider_request_failed"
    if "structured" in text or "json" in text:
        return "invalid_provider_payload"
    return "runner_error"


def _usage_dict(usage: object) -> dict[str, int]:
    if hasattr(usage, "as_dict"):
        raw = usage.as_dict()
        if isinstance(raw, Mapping):
            return {
                key: max(0, int(raw.get(key, 0) or 0))
                for key in ("input_tokens", "cached_input_tokens", "output_tokens")
            }
    if isinstance(usage, Mapping):
        return {
            "input_tokens": max(0, int(usage.get("input_tokens", 0) or 0)),
            "cached_input_tokens": max(0, int(usage.get("cached_input_tokens", 0) or 0)),
            "output_tokens": max(0, int(usage.get("output_tokens", 0) or 0)),
        }
    return {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}


def _parse_litellm_usage(runner: ModuleType, payload: Mapping[str, Any]) -> object:
    raw = payload.get("usage")
    if not isinstance(raw, Mapping):
        return runner.Usage()
    # OpenAI Responses uses input_tokens/output_tokens.  LiteLLM's embedding
    # adapter may expose prompt_tokens/total_tokens instead.
    normalized = dict(raw)
    if "input_tokens" not in normalized:
        normalized["input_tokens"] = normalized.get(
            "prompt_tokens", normalized.get("total_tokens", 0)
        )
    if "output_tokens" not in normalized:
        normalized["output_tokens"] = normalized.get("completion_tokens", 0)
    return runner.parse_usage(normalized)


class LiteLLMClient:
    """Small synchronous LiteLLM OpenAI-compatible client with telemetry."""

    def __init__(
        self,
        runner: ModuleType,
        *,
        base_url: str,
        api_key: str,
        embedding_alias: str,
        embedding_model: str,
        embedding_dimension: int,
        generation_model: str = GENERATION_MODEL,
        judge_model: str = JUDGE_MODEL,
        max_retries: int = 3,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key:
            raise CellRunError("LiteLLM API key is required")
        if not base_url.startswith(("http://", "https://")):
            raise CellRunError("LiteLLM base URL must be absolute HTTP(S)")
        self.runner = runner
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.embedding_alias = embedding_alias
        self.embedding_model = embedding_model
        self.embedding_dimension = embedding_dimension
        self.generation_model = generation_model
        self.judge_model = judge_model
        self.max_retries = max(0, max_retries)
        self.sleep = sleep
        self.calls: list[ProviderCall] = []
        self._transport = transport

    def _path(self, endpoint: str) -> str:
        if self.base_url.endswith("/v1"):
            return f"/{endpoint.lstrip('/').removeprefix('v1/') }"
        return f"/v1/{endpoint.lstrip('/').removeprefix('v1/') }"

    def _request(
        self,
        *,
        endpoint_type: str,
        endpoint: str,
        model: str,
        input_count: int,
        payload: Mapping[str, object],
    ) -> tuple[Mapping[str, Any], int]:
        path = self._path(endpoint)
        started = time.perf_counter()
        retries = 0
        error_code: str | None = None
        status_code: int | None = None
        body: Mapping[str, Any] | None = None
        request_id: str | None = None
        try:
            with httpx.Client(
                base_url=self.base_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=httpx.Timeout(60.0, connect=10.0),
                transport=self._transport,
            ) as client:
                for attempt in range(self.max_retries + 1):
                    try:
                        response = client.post(path, json=dict(payload))
                        status_code = response.status_code
                        request_id = response.headers.get("x-request-id")
                        if 200 <= response.status_code < 300:
                            decoded = response.json()
                            if not isinstance(decoded, Mapping):
                                raise ValueError("provider payload is not an object")
                            body = decoded
                            break
                        if (
                            response.status_code not in RETRY_STATUSES
                            or attempt >= self.max_retries
                        ):
                            error_code = f"http_{response.status_code}"
                            break
                        retries += 1
                        self.sleep(min(30.0, 2.0**attempt))
                    except (httpx.HTTPError, ValueError):
                        if attempt >= self.max_retries:
                            error_code = "provider_transport_or_payload"
                            break
                        retries += 1
                        self.sleep(min(30.0, 2.0**attempt))
        except httpx.HTTPError:
            error_code = "provider_transport"
        elapsed = (time.perf_counter() - started) * 1000
        usage = _usage_dict(_parse_litellm_usage(self.runner, body or {}))
        call = ProviderCall(
            sequence=len(self.calls) + 1,
            endpoint_type=endpoint_type,
            endpoint=path,
            model=model,
            input_count=input_count,
            actual_vector_dimension=None,
            latency_ms=elapsed,
            usage=usage,
            retries=retries,
            error_code=error_code,
        )
        self.calls.append(call)
        if body is None:
            raise CellRunError(error_code or "provider_request_failed")
        # request_id is deliberately not emitted; retaining it in memory only
        # is useful when debugging an active process and cannot leak it.
        _ = request_id, status_code
        return body, len(self.calls) - 1

    def embeddings(self, model: str, inputs: Sequence[str]) -> object:
        if model != self.embedding_alias:
            raise ContractError("embedding alias/model contract mismatch")
        payload = {"model": self.embedding_alias, "input": list(inputs), "encoding_format": "float"}
        body, call_index = self._request(
            endpoint_type="embedding",
            endpoint="embeddings",
            model=self.embedding_alias,
            input_count=len(inputs),
            payload=payload,
        )
        try:
            vectors = self.runner.extract_embeddings(body)
        except Exception as exc:  # noqa: BLE001 - map payload shape, never body
            self.calls[call_index].error_code = "invalid_provider_payload"
            raise ContractError("embedding response payload was invalid") from exc
        if len(vectors) != len(inputs):
            self.calls[call_index].error_code = "embedding_count_contract"
            raise ContractError("embedding response count did not match request count")
        widths = {len(vector) for vector in vectors}
        actual = len(vectors[0]) if vectors else None
        self.calls[call_index].actual_vector_dimension = actual
        if widths != {self.embedding_dimension}:
            self.calls[call_index].error_code = "embedding_width_contract"
            raise ContractError("embedding response width did not match matrix cell")
        usage = self.runner.parse_usage(body.get("usage"))
        return self.runner.ProviderResponse(body, usage)

    def response(
        self,
        *,
        model: str,
        system: str,
        user: str,
        name: str,
        schema: Mapping[str, Any],
        max_output_tokens: int,
    ) -> object:
        expected_model = self.judge_model if name == "rag_judge" else self.generation_model
        if model != expected_model:
            raise ContractError("generation/judge model contract mismatch")
        endpoint_type = (
            "judge" if name == "rag_judge"
            else "generation" if name == "rag_answer" else "response"
        )
        payload = {
            "model": expected_model,
            "store": False,
            "max_output_tokens": max_output_tokens,
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": system}]},
                {"role": "user", "content": [{"type": "input_text", "text": user}]},
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": name,
                    "strict": True,
                    "schema": dict(schema),
                }
            },
        }
        body, _ = self._request(
            endpoint_type=endpoint_type,
            endpoint="responses",
            model=self.generation_model,
            input_count=1,
            payload=payload,
        )
        return self.runner.ProviderResponse(body, self.runner.parse_usage(body.get("usage")))


def _validate_query_denominator(cases: Sequence[object]) -> dict[str, int]:
    ids: list[str] = []
    answerable = 0
    off_corpus = 0
    for case in cases:
        query_id = str(getattr(case, "query_id", "")).strip()
        ids.append(query_id)
        value = getattr(case, "answerable", None)
        if value is True:
            answerable += 1
        elif value is False:
            off_corpus += 1
        else:
            raise ContractError(f"query {query_id or '<unknown>'} lacks answerable label")
    if tuple(ids) != EXPECTED_QUERY_IDS:
        raise ContractError("query denominator is not the complete ordered q001-q070 set")
    if answerable != 60 or off_corpus != 10:
        raise ContractError(
            "query denominator must contain 60 answerable and 10 off-corpus queries"
        )
    return {"total": len(ids), "answerable": answerable, "off_corpus": off_corpus}


def _validate_cache_mode(value: str) -> CacheMode:
    if value not in {"no-cache", "shared-cache-exploratory"}:
        raise ContractError(
            "cache mode must be 'no-cache' or explicitly labeled "
            "'shared-cache-exploratory'"
        )
    return cast(CacheMode, value)


def _document_id(value: object) -> str:
    text = str(value).strip()
    return text.split(":", 1)[0] if ":" in text else text


def _required_document_metrics(row: Mapping[str, Any]) -> dict[str, object]:
    required = row.get("required_evidence_ids")
    retrieved = row.get("retrieved")
    if not isinstance(required, list) or not isinstance(retrieved, list):
        return {}
    required_documents = {_document_id(value) for value in required if str(value).strip()}
    retrieved_documents = {
        _document_id(item.get("chunk_id"))
        for item in retrieved
        if isinstance(item, Mapping) and str(item.get("chunk_id", "")).strip()
    }
    hit_count = len(required_documents & retrieved_documents)
    total = len(required_documents)
    return {
        "retrieval_required_document_hit_count": hit_count,
        "retrieval_required_document_count": total,
        "retrieval_required_document_coverage": hit_count / total if total else None,
    }


def _sanitize_row(row: Mapping[str, Any]) -> dict[str, object]:
    deterministic = row.get("deterministic_metrics")
    deterministic = deterministic if isinstance(deterministic, Mapping) else {}
    judge = row.get("judge")
    judge = judge if isinstance(judge, Mapping) else {}
    metadata = row.get("metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    timings = metadata.get("timings_ms")
    timings = timings if isinstance(timings, Mapping) else {}
    retrieved = row.get("retrieved")
    retrieved_ids = [
        str(item.get("chunk_id"))
        for item in retrieved
        if isinstance(item, Mapping) and item.get("chunk_id")
    ] if isinstance(retrieved, list) else []
    raw_errors = row.get("errors")
    error_codes = [
        _safe_error_code(item) for item in raw_errors
        if item
    ] if isinstance(raw_errors, list) else []
    metric_names = (
        "abstention_expected", "abstention_predicted",
        "abstention_correct", "citation_validity", "citation_document_coverage",
        "citation_evidence_coverage", "invalid_citation_rate", "citation_count",
        "valid_citation_count",
    )
    judge_names = (
        "context_relevance", "groundedness", "answer_relevance", "correctness",
        "citation_entailment", "citation_precision", "citation_completeness",
    )
    return {
        "query_id": str(row.get("query_id", "")),
        "answerable": bool(metadata.get("answerable")),
        "retrieved_ids": retrieved_ids,
        "metrics": _required_document_metrics(row) | {
            name: deterministic.get(name)
            for name in metric_names
            if name in deterministic
        },
        "judge": {name: judge.get(name) for name in judge_names if name in judge},
        "timings_ms": {
            str(name): round(float(value), 4)
            for name, value in timings.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        },
        "usage": row.get("usage") if isinstance(row.get("usage"), Mapping) else {},
        "error_codes": error_codes,
    }


def _stage_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, object]:
    names = sorted({name for row in rows for name in (row.get("timings_ms") or {})})
    stages: dict[str, object] = {}
    for name in names:
        values = [
            float(row["timings_ms"][name])
            for row in rows
            if name in row.get("timings_ms", {})
        ]
        stages[name] = {
            "observations": len(values),
            "mean_ms": statistics.mean(values) if values else None,
            "p50_ms": _percentile(values, 0.5),
            "p95_ms": _percentile(values, 0.95),
            "p99_ms": _percentile(values, 0.99),
        }
    return {"stages": stages, "successful_observations": len(rows)}


def _provider_cost(calls: Sequence[Mapping[str, Any]]) -> dict[str, object]:
    """Calculate actual provider spend from persisted call usage only."""

    million = Decimal(1_000_000)
    by_endpoint: dict[str, dict[str, object]] = {}
    total = Decimal("0")
    for call in calls:
        endpoint_type = str(call.get("endpoint_type", "unknown"))
        model = str(call.get("model", ""))
        usage = call.get("usage")
        usage = usage if isinstance(usage, Mapping) else {}
        input_tokens = max(0, int(usage.get("input_tokens", 0) or 0))
        cached_tokens = min(input_tokens, max(0, int(usage.get("cached_input_tokens", 0) or 0)))
        output_tokens = max(0, int(usage.get("output_tokens", 0) or 0))
        if endpoint_type == "embedding":
            if "text-embedding-3-small" in model:
                input_price = SMALL_EMBEDDING_PRICE
            elif "text-embedding-3-large" in model:
                input_price = LARGE_EMBEDDING_PRICE
            else:
                raise ContractError("provider cost has an unsupported embedding model")
            cached_price = input_price
            output_price = Decimal("0")
        elif model == GENERATION_MODEL:
            input_price = LUNA_INPUT_PRICE
            cached_price = LUNA_CACHED_INPUT_PRICE
            output_price = LUNA_OUTPUT_PRICE
        elif model == JUDGE_MODEL:
            input_price = JUDGE_INPUT_PRICE
            cached_price = JUDGE_CACHED_INPUT_PRICE
            output_price = JUDGE_OUTPUT_PRICE
        else:
            raise ContractError("provider cost has an unsupported response model")
        uncached_tokens = input_tokens - cached_tokens
        amount = (
            Decimal(uncached_tokens) * input_price
            + Decimal(cached_tokens) * cached_price
            + Decimal(output_tokens) * output_price
        ) / million
        total += amount
        bucket = by_endpoint.setdefault(
            endpoint_type,
            {
                "calls": 0,
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "actual_provider_cost_usd": "0",
            },
        )
        bucket["calls"] = _nonnegative_int(bucket["calls"]) + 1
        bucket["input_tokens"] = _nonnegative_int(bucket["input_tokens"]) + input_tokens
        bucket["cached_input_tokens"] = (
            _nonnegative_int(bucket["cached_input_tokens"]) + cached_tokens
        )
        bucket["output_tokens"] = _nonnegative_int(bucket["output_tokens"]) + output_tokens
        bucket["actual_provider_cost_usd"] = str(
            Decimal(str(bucket["actual_provider_cost_usd"])) + amount
        )
    return {
        "actual_provider_cost_usd": str(total),
        "basis": "provider_calls_usage_only",
        "by_endpoint": by_endpoint,
        "rates_usd_per_million": {
            "text-embedding-3-small": str(SMALL_EMBEDDING_PRICE),
            "text-embedding-3-large": str(LARGE_EMBEDDING_PRICE),
            GENERATION_MODEL: {
                "input": str(LUNA_INPUT_PRICE),
                "cached_input": str(LUNA_CACHED_INPUT_PRICE),
                "output": str(LUNA_OUTPUT_PRICE),
            },
            JUDGE_MODEL: {
                "input": str(JUDGE_INPUT_PRICE),
                "cached_input": str(JUDGE_CACHED_INPUT_PRICE),
                "output": str(JUDGE_OUTPUT_PRICE),
            },
        },
    }


def _summary_cache(
    hit_counts: Mapping[str, object],
    *,
    total_chunks: int,
    total_queries: int,
    mode: str,
) -> dict[str, object]:
    cache_mode = _validate_cache_mode(mode)
    counts = {
        name: _nonnegative_int(hit_counts.get(name, 0))
        for name in ("chunk_embeddings", "query_embeddings", "generation", "judge")
    }
    totals = {
        "chunk_embeddings": total_chunks,
        "query_embeddings": total_queries,
        "generation": total_queries,
        "judge": total_queries,
    }
    denominators = {
        name: {
            "total": total,
            "cached": min(total, counts[name]),
            "uncached": max(0, total - min(total, counts[name])),
        }
        for name, total in totals.items()
    }
    return {
        "mode": cache_mode,
        "publication_eligible": cache_mode == "no-cache",
        "hit_counts": counts,
        "denominators": denominators,
        "latency_comparability": (
            "all_query_timings_comparable"
            if cache_mode == "no-cache"
            else "cached_query_timings_excluded_from_comparable_latency"
        ),
    }


def _provider_latency_summary(calls: Sequence[Mapping[str, Any]]) -> dict[str, object]:
    rows = [
        {"timings_ms": {f"{call.get('endpoint_type', 'unknown')}_provider": call.get("latency_ms")}}
        for call in calls
        if isinstance(call.get("latency_ms"), (int, float))
        and not isinstance(call.get("latency_ms"), bool)
    ]
    return {
        "population": "uncached_provider_calls",
        "comparable": True,
        **_stage_summary(rows),
    }


def _write_new(path: Path, value: object) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl_new(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _embedding_price(model: str) -> Decimal:
    if model == "text-embedding-3-small":
        return SMALL_EMBEDDING_PRICE
    if model == "text-embedding-3-large":
        return LARGE_EMBEDDING_PRICE
    raise ContractError("unsupported embedding model")


def _nonnegative_int(value: object) -> int:
    try:
        return max(0, int(str(value)))
    except (TypeError, ValueError):
        return 0


def run_cell(
    *,
    model: str,
    dimension: int,
    dataset_dir: Path,
    queries_path: Path,
    private_work_dir: Path,
    output_dir: Path,
    cache_dir: Path,
    env_values: Mapping[str, str],
    litellm_base_url: str,
    litellm_api_key: str | None = None,
    judge_model: str = JUDGE_MODEL,
    cache_mode: str = "no-cache",
    runner: ModuleType | None = None,
    client: object | None = None,
    transport: httpx.BaseTransport | None = None,
    max_retries: int = 3,
    top_k: int = 5,
    chunk_size: int = 2000,
    overlap: int = 300,
) -> dict[str, object]:
    """Execute one matrix cell and emit only privacy-safe public artifacts."""

    matrix = _load_module(
        SCRIPT_DIR / "embedding_benchmark_matrix.py", "ragz_embedding_matrix_cell"
    )
    cell = matrix.cell_for(model, dimension)
    cache_mode = _validate_cache_mode(cache_mode)
    if not judge_model.strip():
        raise ContractError("judge model must not be empty")
    dataset_dir = dataset_dir.resolve()
    queries_path = queries_path.resolve()
    private_work_dir = private_work_dir.resolve()
    output_dir = output_dir.resolve()
    cache_dir = cache_dir.resolve()
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite output directory: {output_dir}")
    raw_dir = private_work_dir / f"cell-{cell.cell_id}"
    if raw_dir.exists():
        raise FileExistsError(f"refusing to overwrite private raw directory: {raw_dir}")
    if output_dir.is_relative_to(private_work_dir):
        raise ContractError("public output must be outside the private work directory")
    if not cache_dir.is_relative_to(private_work_dir):
        raise ContractError("shared cache must be below the explicit private work directory")
    if litellm_api_key is None:
        litellm_api_key = str(
            env_values.get("RAGZ_LITELLM_API_KEY")
            or env_values.get("RAGZ_LITELLM_MASTER_KEY")
            or env_values.get("LITELLM_MASTER_KEY")
            or ""
        )
    if not litellm_api_key:
        raise CellRunError("LiteLLM API key is required")
    if runner is None:
        runner = _load_module(DEFAULT_RUNNER, "ragz_openai_qa_matrix_runner")
    documents = runner.read_jsonl(dataset_dir / "documents.jsonl")
    cases = runner.load_queries(queries_path, documents)
    denominator = _validate_query_denominator(cases)
    values = runner.merge_non_secret_defaults(dict(env_values))
    values.update({
        "OPENAI_API_KEY": "proxy-key-configured",
        "OPENAI_BASE_URL": litellm_base_url,
        "OPENAI_EMBEDDING_MODEL": cell.alias,
        "OPENAI_GENERATION_MODEL": GENERATION_MODEL,
        "OPENAI_JUDGE_MODEL": judge_model,
    })
    if cache_mode == "shared-cache-exploratory":
        values["RAGZ_BENCHMARK_CACHE_DIR"] = str(cache_dir)
    budget_cap = Decimal(str(values.get("RAGZ_BENCHMARK_MAX_BUDGET_USD", "3.00")))
    if budget_cap <= 0:
        raise ContractError("benchmark budget cap must be positive")
    original_price = getattr(runner, "EMBEDDING_USD_PER_MILLION", None)
    runner.__dict__["EMBEDDING_USD_PER_MILLION"] = _embedding_price(model)
    cache_class = getattr(runner, "ContentCache", None)
    if cache_class is None or not callable(cache_class):
        raise CellRunError("target runner has no content cache")

    class WidthCheckingCache(cache_class):  # type: ignore[misc,valid-type]
        def get(self, key: str) -> Mapping[str, Any] | None:
            value = cast(Mapping[str, Any] | None, super().get(key))
            if isinstance(value, Mapping) and isinstance(value.get("embedding"), list):
                if any(not isinstance(item, (int, float)) for item in value["embedding"]):
                    raise ContractError("cached embedding contains a non-numeric value")
                if len(value["embedding"]) != cell.dimension:
                    raise ContractError("cached embedding width did not match matrix cell")
            return value

    runner.__dict__["ContentCache"] = WidthCheckingCache
    try:
        raw_dir.mkdir(parents=True)
        if client is None:
            client = LiteLLMClient(
                runner,
                base_url=litellm_base_url,
                api_key=litellm_api_key,
                embedding_alias=cell.alias,
                embedding_model=model,
                embedding_dimension=cell.dimension,
                max_retries=max_retries,
                judge_model=judge_model,
                transport=transport,
            )
        source_summary = runner.run(
            values=values,
            dataset_dir=dataset_dir,
            output_dir=raw_dir,
            queries_path=queries_path,
            limit=None,
            top_k=top_k,
            chunk_size=chunk_size,
            overlap=overlap,
            use_cache=cache_mode == "shared-cache-exploratory",
            dataset_approved=True,
            client=client,
        )
    finally:
        if original_price is None:
            try:
                delattr(runner, "EMBEDDING_USD_PER_MILLION")
            except AttributeError:
                pass
        else:
            runner.__dict__["EMBEDDING_USD_PER_MILLION"] = original_price
        runner.__dict__["ContentCache"] = cache_class

    if not isinstance(source_summary, Mapping):
        raise CellRunError("target runner returned an invalid summary")
    raw_rows = runner.read_jsonl(raw_dir / "per_query.jsonl")
    if (
        len(raw_rows) != denominator["total"]
        or {str(row.get("query_id")) for row in raw_rows} != set(EXPECTED_QUERY_IDS)
    ):
        raise ContractError("per-query output does not cover the complete 70-query denominator")
    errors = [
        code
        for row in raw_rows
        for code in (_safe_error_code(item) for item in row.get("errors", []) if item)
    ]
    if errors:
        raise ContractError("benchmark produced non-zero mapped query errors")
    source_manifest = source_summary.get("manifest")
    if isinstance(source_manifest, Mapping):
        models = source_manifest.get("models")
        if isinstance(models, Mapping) and (
            models.get("embedding") != cell.alias
            or models.get("generation") != GENERATION_MODEL
            or models.get("judge") != judge_model
        ):
            raise ContractError("target runner model contract does not match matrix cell")
    sanitized = [_sanitize_row(row) for row in raw_rows]
    client_calls = getattr(client, "calls", [])
    public_calls = [
        call.as_dict() if hasattr(call, "as_dict") else dict(call)
        for call in client_calls
    ]
    observed_dimensions = sorted(
        {
            int(call["actual_vector_dimension"])
            for call in public_calls
            if call.get("actual_vector_dimension") is not None
        }
    )
    if observed_dimensions and observed_dimensions != [cell.dimension]:
        raise ContractError("provider telemetry observed an unexpected embedding width")
    source_accounting = source_summary.get("accounting")
    source_accounting = source_accounting if isinstance(source_accounting, Mapping) else {}
    source_cache_hits = source_accounting.get("cache_hits")
    source_cache_hits = source_cache_hits if isinstance(source_cache_hits, Mapping) else {}
    source_chunks = source_manifest.get("chunks") if isinstance(source_manifest, Mapping) else None
    total_chunks = int(source_chunks) if isinstance(source_chunks, (int, float)) else 0
    cache_summary = _summary_cache(
        source_cache_hits,
        total_chunks=total_chunks,
        total_queries=denominator["total"],
        mode=cache_mode,
    )
    actual_cost = _provider_cost(public_calls)
    cost_value = source_summary.get("cost")
    cost = cast(Mapping[str, Any], cost_value) if isinstance(cost_value, Mapping) else {}
    committed = Decimal(str(cost.get("committed_estimated_plus_actual_usd", "0")))
    if committed > budget_cap:
        raise ContractError("committed provider estimate and actual cost exceed hard budget cap")
    actual_provider_cost = Decimal(str(actual_cost["actual_provider_cost_usd"]))
    if actual_provider_cost > budget_cap:
        raise ContractError("actual provider cost exceeds hard budget cap")
    query_latency = _stage_summary(sanitized)
    document_hit_rows: list[Mapping[str, object]] = []
    for row in sanitized:
        metrics = row.get("metrics")
        if (
            row["answerable"]
            and isinstance(metrics, Mapping)
            and metrics.get("retrieval_required_document_count", 0)
        ):
            document_hit_rows.append(metrics)
    document_hit_rate = (
        sum(bool(row.get("retrieval_required_document_hit_count")) for row in document_hit_rows)
        / len(document_hit_rows)
        if document_hit_rows
        else None
    )
    output_dir.mkdir(parents=True)
    _write_jsonl_new(output_dir / "per_query.jsonl", sanitized)
    _write_jsonl_new(output_dir / "provider_calls.jsonl", public_calls)
    query_hash = _sha256(queries_path)
    corpus_hash = _sha256(dataset_dir / "documents.jsonl")
    summary = {
        "schema_version": 1,
        "status": "completed",
        "benchmark": "open-manuals-v2",
        "cell": {
            "cell_id": cell.cell_id,
            "alias": cell.alias,
            "model": model,
            "dimension": dimension,
        },
        "models": {
            "embedding_alias": cell.alias,
            "generation": GENERATION_MODEL,
            "judge": judge_model,
        },
        "judge_independence": (
            "self_evaluation_same_model" if judge_model == GENERATION_MODEL
            else "separate_model_same_provider"
        ),
        "rag_triad": "exploratory_not_independent",
        "denominator": denominator,
        "provider_calls": len(public_calls),
        "provider_call_errors": dict(
            Counter(call.get("error_code") for call in public_calls if call.get("error_code"))
        ),
        "observed_embedding_dimensions": observed_dimensions or [cell.dimension],
        "cost": {
            **actual_cost,
            "hard_budget_usd": str(budget_cap),
        },
        "budget_accounting": {
            "committed_estimated_plus_actual_usd": str(committed),
            "basis": "upstream_budget_accounting_not_provider_cost",
            "hard_budget_usd": str(budget_cap),
        },
        "cache": cache_summary,
        "latency": {
            "query_timings": {
                "population": "all_query_rows",
                "comparable": cache_mode == "no-cache",
                "exclusion_reason": (
                    None if cache_mode == "no-cache"
                    else "cached totals are not mixed with uncached publication latency"
                ),
                **query_latency,
            },
            "provider_calls": _provider_latency_summary(public_calls),
        },
        "source_summary_metrics": {
            "retrieval_required_document_hit_rate": document_hit_rate,
            **{
                key: source_summary.get(key)
                for key in ("abstention", "citation", "reliability", "mean_judge_scores")
                if key in source_summary
            },
        },
        "dataset_sha256": {"documents": corpus_hash, "queries": query_hash},
        "privacy": {
            "raw_artifacts_private_only": True,
            "prompts_persisted": False,
            "response_bodies_persisted": False,
            "credentials_persisted": False,
            "public_per_query_fields": [
                "query_id", "retrieved_ids", "metrics", "judge", "timings_ms",
                "usage", "error_codes",
            ],
        },
    }
    _write_new(output_dir / "summary.json", summary)
    calls_hash = _sha256(output_dir / "provider_calls.jsonl")
    rows_hash = _sha256(output_dir / "per_query.jsonl")
    attestation = {
        "schema_version": 1,
        "attestation": "open-manuals-v2-matrix-cell",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "status": "completed",
        "cell": summary["cell"],
        "alias_contract": {
            "alias": cell.alias,
            "underlying_model": model,
            "expected_dimension": dimension,
            "observed_dimensions": observed_dimensions or [dimension],
            "client_sends_dimensions": False,
        },
        "denominator": denominator,
        "judge_independence": summary["judge_independence"],
        "rag_triad": summary["rag_triad"],
        "cache": summary["cache"],
        "provider_calls": len(public_calls),
        "error_count": 0,
        "artifacts_sha256": {"per_query": rows_hash, "provider_calls": calls_hash},
        "privacy": summary["privacy"],
    }
    _write_new(output_dir / "attestation.json", attestation)
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        required=True,
        choices=("text-embedding-3-small", "text-embedding-3-large"),
    )
    parser.add_argument("--dimension", required=True, type=int)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--queries", required=True, type=Path)
    parser.add_argument("--private-work-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument(
        "--cache-mode",
        choices=("no-cache", "shared-cache-exploratory"),
        default="no-cache",
        help="publication defaults to no-cache; shared cache is exploratory only",
    )
    parser.add_argument(
        "--judge-model",
        default=JUDGE_MODEL,
        help="judge model; defaults to a separate gpt-5.4-mini publication judge",
    )
    parser.add_argument(
        "--env",
        required=True,
        type=Path,
        help="explicit dotenv file for run settings and the LiteLLM key",
    )
    parser.add_argument("--litellm-base-url", required=True)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--chunk-size", type=int, default=2000)
    parser.add_argument("--overlap", type=int, default=300)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    runner = _load_module(DEFAULT_RUNNER, "ragz_openai_qa_matrix_cli")
    values = runner.load_env_file(args.env)
    run_cell(
        model=args.model,
        dimension=args.dimension,
        dataset_dir=args.dataset,
        queries_path=args.queries,
        private_work_dir=args.private_work_dir,
        output_dir=args.output,
        cache_dir=args.cache_dir,
        env_values=values,
        litellm_base_url=args.litellm_base_url,
        judge_model=args.judge_model,
        cache_mode=args.cache_mode,
        max_retries=args.max_retries,
        top_k=args.top_k,
        chunk_size=args.chunk_size,
        overlap=args.overlap,
        runner=runner,
    )
    print(json.dumps({"output": str(args.output.resolve()), "status": "completed"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
