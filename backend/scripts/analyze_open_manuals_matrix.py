#!/usr/bin/env python3
# ruff: noqa: E501
"""Analyze the ten privacy-safe Open Manuals matrix cell artifacts.

The analyzer is intentionally a post-processing tool.  It reads only the
public, privacy-safe artifacts emitted by ``run_open_manuals_matrix_cell.py``
and never reads prompts, answers, document text, or provider response bodies.
Every claim is recomputed from per-query/provider-call rows; the producer's
summary cost and latency totals are not used as observations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

SCHEMA_VERSION = 1
EXPECTED_QUERY_IDS = tuple(f"q{index:03d}" for index in range(1, 71))
EXPECTED_CELL_IDS = frozenset(
    {
        *(f"openai-text-embedding-3-small-d{dimension}" for dimension in (1024, 1280, 1536)),
        *(
            f"openai-text-embedding-3-large-d{dimension}"
            for dimension in (1024, 1280, 1536, 1792, 2048, 2096, 3072)
        ),
    }
)
EXPECTED_DENOMINATOR = {"total": 70, "answerable": 60, "off_corpus": 10}
EXPECTED_DOCUMENT_SHA256 = "a7e6f35fda062cf04ab1435ffac269486f3920a6abe520f0a384673f64e9d335"
EXPECTED_QUERY_SHA256 = "e743da70e48aab4392744dec18330c83da232bd883ce2c0ea5a1bff34c169c57"
EXPECTED_PROVIDER_CALLS = 211
EXPECTED_EMBEDDING_CALLS = 71
EXPECTED_GENERATION_CALLS = 70
EXPECTED_JUDGE_CALLS = 70
DEFAULT_BOOTSTRAP_SAMPLES = 10_000
DEFAULT_SEED = 42
ALPHA = 0.05

SMALL_EMBEDDING_PRICE = Decimal("0.02")
LARGE_EMBEDDING_PRICE = Decimal("0.13")
LUNA_INPUT_PRICE = Decimal("0.20")
LUNA_CACHED_INPUT_PRICE = Decimal("0.02")
LUNA_OUTPUT_PRICE = Decimal("1.20")
JUDGE_INPUT_PRICE = Decimal("0.75")
JUDGE_CACHED_INPUT_PRICE = Decimal("0.075")
JUDGE_OUTPUT_PRICE = Decimal("4.50")
LUNA_MODEL = "gpt-5.6-luna"
JUDGE_MODEL = "gpt-5.4-mini"

QUALITY_METRICS = (
    "context_relevance",
    "groundedness",
    "answer_relevance",
    "citation_validity",
    "citation_document_coverage",
    "citation_evidence_coverage",
)
LATENCY_METRICS = (
    "context_select_or_dense_retrieval",
    "total_with_judge",
    "answer_pipeline_without_live_retrieval",
)
RAG_TRIAD_COMPONENTS = ("context_relevance", "groundedness", "answer_relevance")
_BANNED_KEYS = frozenset(
    {
        "query",
        "query_text",
        "prompt",
        "answer",
        "text",
        "response",
        "response_body",
        "headers",
        "authorization",
        "api_key",
        "secret",
    }
)


class MatrixAnalysisError(ValueError):
    """Raised when an input cell violates the reproducibility contract."""


class OutputExistsError(FileExistsError):
    """Raised when either requested output already exists."""


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MatrixAnalysisError(f"unable to read JSON artifact: {path}") from exc


def _jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise MatrixAnalysisError(f"unable to read JSONL artifact: {path}") from exc
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise MatrixAnalysisError(f"invalid JSONL at {path}:{number}") from exc
        if not isinstance(value, dict):
            raise MatrixAnalysisError(f"JSONL row is not an object at {path}:{number}")
        rows.append(value)
    return rows


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise MatrixAnalysisError(f"unable to hash artifact: {path}") from exc
    return digest.hexdigest()


def _walk_keys(value: object) -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            yield str(key).lower()
            yield from _walk_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_keys(nested)


def _assert_privacy_safe(value: object, label: str) -> None:
    leaked = sorted(_BANNED_KEYS & set(_walk_keys(value)))
    if leaked:
        raise MatrixAnalysisError(f"{label} contains forbidden privacy fields: {leaked}")


def _required_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MatrixAnalysisError(f"{label} must be an object")
    return cast(Mapping[str, Any], value)


def _required_int(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise MatrixAnalysisError(f"{label} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not value.is_integer():
            raise MatrixAnalysisError(f"{label} must be an integer")
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError as exc:
            raise MatrixAnalysisError(f"{label} must be an integer") from exc
    raise MatrixAnalysisError(f"{label} must be an integer")


def _required_float(value: object, label: str) -> float:
    if isinstance(value, bool):
        raise MatrixAnalysisError(f"{label} must be numeric")
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise MatrixAnalysisError(f"{label} must be numeric") from exc
    if not math.isfinite(result):
        raise MatrixAnalysisError(f"{label} must be finite")
    return result


def _percentile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def summarize_values(values: Sequence[float]) -> dict[str, float | int | None]:
    numbers = [float(value) for value in values]
    return {
        "observations": len(numbers),
        "mean_ms": statistics.fmean(numbers) if numbers else None,
        "p50_ms": _percentile(numbers, 0.50),
        "p95_ms": _percentile(numbers, 0.95),
        "p99_ms": _percentile(numbers, 0.99),
    }


def _cell_from_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    cell = _required_mapping(summary.get("cell"), "summary.cell")
    cell_id = str(cell.get("cell_id", ""))
    model = str(cell.get("model", ""))
    dimension = _required_int(cell.get("dimension"), "summary.cell.dimension")
    expected_prefix = f"openai-{model.replace('/', '-')}-d{dimension}"
    if cell_id != expected_prefix or cell_id not in EXPECTED_CELL_IDS:
        raise MatrixAnalysisError(f"unexpected matrix cell ID: {cell_id!r}")
    alias = str(cell.get("alias", ""))
    if alias != f"ragz-{cell_id}":
        raise MatrixAnalysisError(f"cell alias does not match cell ID: {cell_id}")
    return {"cell_id": cell_id, "model": model, "dimension": dimension, "alias": alias}


def _validate_denominator(value: object, label: str) -> dict[str, int]:
    raw = _required_mapping(value, label)
    result = {
        name: _required_int(raw.get(name), f"{label}.{name}") for name in EXPECTED_DENOMINATOR
    }
    if result != EXPECTED_DENOMINATOR:
        raise MatrixAnalysisError(f"{label} must equal {EXPECTED_DENOMINATOR}, got {result}")
    return result


def _validate_rows(rows: Sequence[Mapping[str, Any]], label: str) -> dict[str, Mapping[str, Any]]:
    if len(rows) != len(EXPECTED_QUERY_IDS):
        raise MatrixAnalysisError(f"{label} must contain exactly 70 rows")
    result: dict[str, Mapping[str, Any]] = {}
    for index, row in enumerate(rows):
        _assert_privacy_safe(row, f"{label} row {index + 1}")
        query_id = str(row.get("query_id", ""))
        if query_id != EXPECTED_QUERY_IDS[index]:
            raise MatrixAnalysisError(f"{label} query IDs must be ordered q001-q070")
        if query_id in result:
            raise MatrixAnalysisError(f"{label} contains duplicate {query_id}")
        if not isinstance(row.get("answerable"), bool):
            raise MatrixAnalysisError(f"{label} {query_id} lacks boolean answerable flag")
        errors = row.get("error_codes")
        if not isinstance(errors, list):
            raise MatrixAnalysisError(f"{label} {query_id} lacks error_codes list")
        if errors:
            raise MatrixAnalysisError(f"{label} contains query errors for {query_id}")
        result[query_id] = row
    answerable = sum(bool(row["answerable"]) for row in rows)
    if answerable != 60:
        raise MatrixAnalysisError(f"{label} must contain 60 answerable queries")
    return result


def _validate_cell(directory: Path) -> dict[str, Any]:
    if not directory.is_dir():
        raise MatrixAnalysisError(f"input is not a directory: {directory}")
    summary = _required_mapping(_json(directory / "summary.json"), "summary")
    attestation = _required_mapping(_json(directory / "attestation.json"), "attestation")
    _assert_privacy_safe(summary, "summary")
    _assert_privacy_safe(attestation, "attestation")
    if _required_int(summary.get("schema_version"), "summary.schema_version") != SCHEMA_VERSION:
        raise MatrixAnalysisError(f"unsupported summary schema in {directory}")
    if (
        _required_int(attestation.get("schema_version"), "attestation.schema_version")
        != SCHEMA_VERSION
    ):
        raise MatrixAnalysisError(f"unsupported attestation schema in {directory}")
    if summary.get("status") != "completed" or attestation.get("status") != "completed":
        raise MatrixAnalysisError(f"cell is not completed: {directory}")
    cell = _cell_from_summary(summary)
    att_cell = _required_mapping(attestation.get("cell"), "attestation.cell")
    if {
        "cell_id": str(att_cell.get("cell_id")),
        "model": str(att_cell.get("model")),
        "dimension": _required_int(att_cell.get("dimension"), "attestation.cell.dimension"),
        "alias": str(att_cell.get("alias")),
    } != cell:
        raise MatrixAnalysisError(f"summary and attestation cell identity differ: {directory}")
    _validate_denominator(summary.get("denominator"), "summary.denominator")
    _validate_denominator(attestation.get("denominator"), "attestation.denominator")
    rows = _jsonl(directory / "per_query.jsonl")
    row_map = _validate_rows(rows, "per_query.jsonl")
    calls = _jsonl(directory / "provider_calls.jsonl")
    if not calls:
        raise MatrixAnalysisError(f"provider_calls.jsonl is empty: {directory}")
    for index, call in enumerate(calls, 1):
        _assert_privacy_safe(call, f"provider call {index}")
        if call.get("error_code") is not None:
            raise MatrixAnalysisError(f"provider call {index} has an error")
        endpoint_type = str(call.get("endpoint_type", ""))
        if endpoint_type not in {"embedding", "generation", "judge"}:
            raise MatrixAnalysisError(f"provider call {index} has an unknown endpoint type")
        usage = _required_mapping(call.get("usage"), f"provider call {index}.usage")
        for key in ("input_tokens", "cached_input_tokens", "output_tokens"):
            if _required_int(usage.get(key, 0), f"provider call {index}.usage.{key}") < 0:
                raise MatrixAnalysisError(f"provider call {index} has negative usage")
        if endpoint_type == "embedding":
            if str(call.get("model")) != cell["alias"]:
                raise MatrixAnalysisError(
                    f"provider call {index} embedding alias differs from cell"
                )
            observed = _required_int(
                call.get("actual_vector_dimension"),
                f"provider call {index}.actual_vector_dimension",
            )
            if observed != cell["dimension"]:
                raise MatrixAnalysisError(f"provider call {index} has unexpected embedding width")
    if summary.get("provider_calls") != len(calls) or attestation.get("provider_calls") != len(
        calls
    ):
        raise MatrixAnalysisError(f"provider call denominator does not match rows: {directory}")
    observed_dimensions = summary.get("observed_embedding_dimensions")
    if observed_dimensions != [cell["dimension"]]:
        raise MatrixAnalysisError(f"summary embedding widths are not exact for {directory}")
    alias_contract = _required_mapping(
        attestation.get("alias_contract"), "attestation.alias_contract"
    )
    if (
        alias_contract.get("expected_dimension") != cell["dimension"]
        or alias_contract.get("observed_dimensions") != [cell["dimension"]]
        or alias_contract.get("client_sends_dimensions") is not False
    ):
        raise MatrixAnalysisError(f"alias width contract is invalid: {directory}")
    errors = _required_int(attestation.get("error_count"), "attestation.error_count")
    provider_errors = summary.get("provider_call_errors")
    if not isinstance(provider_errors, Mapping):
        provider_errors = {}
    if errors != 0 or any(
        _required_int(value, "provider_call_errors") != 0 for value in provider_errors.values()
    ):
        raise MatrixAnalysisError(f"cell has recorded errors: {directory}")
    artifacts = _required_mapping(
        attestation.get("artifacts_sha256"), "attestation.artifacts_sha256"
    )
    expected_hashes = {
        "per_query": sha256(directory / "per_query.jsonl"),
        "provider_calls": sha256(directory / "provider_calls.jsonl"),
    }
    if {name: str(artifacts.get(name)) for name in expected_hashes} != expected_hashes:
        raise MatrixAnalysisError(f"artifact hashes do not verify: {directory}")
    dataset_hashes = _required_mapping(summary.get("dataset_sha256"), "summary.dataset_sha256")
    if (
        dataset_hashes.get("documents") != EXPECTED_DOCUMENT_SHA256
        or dataset_hashes.get("queries") != EXPECTED_QUERY_SHA256
    ):
        raise MatrixAnalysisError(f"dataset hashes do not match open-manuals-v2: {directory}")
    return {
        "directory": directory,
        "cell": cell,
        "rows": row_map,
        "calls": calls,
        "summary": summary,
        "attestation": attestation,
    }


def validate_matrix(input_dirs: Sequence[Path]) -> dict[str, dict[str, Any]]:
    """Validate all ten cells and return them keyed by immutable cell ID."""

    if len(input_dirs) != len(EXPECTED_CELL_IDS):
        raise MatrixAnalysisError(f"expected exactly 10 input dirs, got {len(input_dirs)}")
    cells_by_id: dict[str, dict[str, Any]] = {}
    for directory in input_dirs:
        cell = _validate_cell(directory)
        cell_id = str(cell["cell"]["cell_id"])
        if cell_id in cells_by_id:
            raise MatrixAnalysisError(f"duplicate matrix cell: {cell_id}")
        cells_by_id[cell_id] = cell
    if set(cells_by_id) != set(EXPECTED_CELL_IDS):
        missing = sorted(EXPECTED_CELL_IDS - set(cells_by_id))
        extra = sorted(set(cells_by_id) - set(EXPECTED_CELL_IDS))
        raise MatrixAnalysisError(f"matrix cells differ; missing={missing}, extra={extra}")
    return dict(sorted(cells_by_id.items()))


def bootstrap_ci(
    values: Sequence[float], *, seed: int, samples: int = DEFAULT_BOOTSTRAP_SAMPLES
) -> tuple[float, float] | None:
    """Return a deterministic percentile CI for the mean of paired deltas."""

    if not values:
        return None
    if samples < 100:
        raise ValueError("bootstrap samples must be at least 100")
    rng = random.Random(seed)  # noqa: S311 - deterministic statistical resampling
    values_list = list(map(float, values))
    means = sorted(
        statistics.fmean(rng.choice(values_list) for _ in values_list) for _ in range(samples)
    )
    return means[int(samples * 0.025)], means[int(samples * 0.975) - 1]


def sign_flip_pvalue(
    values: Sequence[float], *, seed: int, samples: int = DEFAULT_BOOTSTRAP_SAMPLES
) -> float | None:
    """Calculate a reproducible two-sided paired sign-flip p-value."""

    if not values:
        return None
    if samples < 100:
        raise ValueError("sign-flip samples must be at least 100")
    observed = abs(statistics.fmean(values))
    if observed == 0:
        return 1.0
    rng = random.Random(seed)  # noqa: S311 - deterministic statistical resampling
    exceed = 0
    values_list = list(map(float, values))
    for _ in range(samples):
        shuffled = sum(value if rng.getrandbits(1) else -value for value in values_list)
        if abs(shuffled / len(values_list)) >= observed:
            exceed += 1
    return (exceed + 1) / (samples + 1)


def holm_correction(
    p_values: Mapping[str, float | None],
) -> dict[str, dict[str, float | bool | None]]:
    """Apply Holm-Bonferroni correction across the supplied hypotheses."""

    valid = [(key, float(value)) for key, value in p_values.items() if value is not None]
    ordered = sorted(valid, key=lambda item: (item[1], item[0]))
    adjusted: dict[str, float] = {}
    running = 0.0
    count = len(ordered)
    for rank, (key, value) in enumerate(ordered):
        running = max(running, min(1.0, value * (count - rank)))
        adjusted[key] = running
    return {
        key: {
            "raw_p": None if value is None else float(value),
            "holm_p": adjusted.get(key),
            "reject_alpha_0_05": adjusted.get(key, 1.0) <= ALPHA if value is not None else False,
        }
        for key, value in p_values.items()
    }


def _provider_cost(calls: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Compute spend from recorded usage, never producer summary totals."""

    by_endpoint: dict[str, dict[str, Any]] = {}
    total = Decimal("0")
    rates: dict[str, Any] = {
        "text-embedding-3-small": {
            "input": str(SMALL_EMBEDDING_PRICE),
            "cached_input": str(SMALL_EMBEDDING_PRICE),
            "output": "0",
        },
        "text-embedding-3-large": {
            "input": str(LARGE_EMBEDDING_PRICE),
            "cached_input": str(LARGE_EMBEDDING_PRICE),
            "output": "0",
        },
        LUNA_MODEL: {
            "input": str(LUNA_INPUT_PRICE),
            "cached_input": str(LUNA_CACHED_INPUT_PRICE),
            "output": str(LUNA_OUTPUT_PRICE),
        },
        JUDGE_MODEL: {
            "input": str(JUDGE_INPUT_PRICE),
            "cached_input": str(JUDGE_CACHED_INPUT_PRICE),
            "output": str(JUDGE_OUTPUT_PRICE),
        },
    }
    for call in calls:
        endpoint_type = str(call.get("endpoint_type", "unknown"))
        model = str(call.get("model", ""))
        if endpoint_type == "embedding":
            model_key = (
                "text-embedding-3-large"
                if "text-embedding-3-large" in model
                else "text-embedding-3-small"
                if "text-embedding-3-small" in model
                else ""
            )
        else:
            model_key = model
        if model_key not in rates:
            raise MatrixAnalysisError(f"unsupported pricing model in provider calls: {model}")
        usage = _required_mapping(call.get("usage"), "provider_call.usage")
        input_tokens = max(0, _required_int(usage.get("input_tokens", 0), "input_tokens"))
        cached_tokens = min(
            input_tokens,
            max(0, _required_int(usage.get("cached_input_tokens", 0), "cached_input_tokens")),
        )
        output_tokens = max(0, _required_int(usage.get("output_tokens", 0), "output_tokens"))
        rate = rates[model_key]
        amount = (
            Decimal(input_tokens - cached_tokens) * Decimal(rate["input"])
            + Decimal(cached_tokens) * Decimal(rate["cached_input"])
            + Decimal(output_tokens) * Decimal(rate["output"])
        ) / Decimal(1_000_000)
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
        bucket["calls"] += 1
        bucket["input_tokens"] += input_tokens
        bucket["cached_input_tokens"] += cached_tokens
        bucket["output_tokens"] += output_tokens
        bucket["actual_provider_cost_usd"] = str(
            Decimal(bucket["actual_provider_cost_usd"]) + amount
        )
    return {
        "actual_provider_cost_usd": str(total),
        "basis": "provider_calls_usage_only",
        "by_endpoint": by_endpoint,
        "rates_usd_per_million": rates,
    }


def _cache_denominators(
    rows: Mapping[str, Mapping[str, Any]],
    calls: Sequence[Mapping[str, Any]],
    *,
    cache_mode: str = "unlabelled",
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "query_rows": {"total": len(rows), "cached": 0, "uncached": len(rows)},
        "provider_calls": {},
    }
    for endpoint in ("embedding", "generation", "judge"):
        endpoint_calls = [call for call in calls if str(call.get("endpoint_type")) == endpoint]
        cached = sum(
            _required_int(
                _required_mapping(call.get("usage"), "usage").get("cached_input_tokens", 0),
                "cached_input_tokens",
            )
            > 0
            for call in endpoint_calls
        )
        result["provider_calls"][endpoint] = {
            "total": len(endpoint_calls),
            "cached": cached,
            "uncached": len(endpoint_calls) - cached,
        }
    result["mode"] = cache_mode
    result["comparability"] = "uncached_only; cached and uncached totals are not pooled"
    result["cached_latency_comparable"] = False
    for row in rows.values():
        usage = row.get("usage")
        if isinstance(usage, Mapping) and any(
            _required_int(
                _required_mapping(value, "query usage").get("cached_input_tokens", 0),
                "cached_input_tokens",
            )
            > 0
            for value in usage.values()
            if isinstance(value, Mapping)
        ):
            result["query_rows"]["cached"] += 1
            result["query_rows"]["uncached"] -= 1
    missing_generation_provider = sum(
        (
            "generation_provider" not in _required_mapping(row.get("timings_ms"), "timings_ms")
            or _required_mapping(row.get("timings_ms"), "timings_ms").get("generation_provider")
            is None
        )
        for row in rows.values()
    )
    missing_judge_provider = sum(
        (
            "judge_provider" not in _required_mapping(row.get("timings_ms"), "timings_ms")
            or _required_mapping(row.get("timings_ms"), "timings_ms").get("judge_provider") is None
        )
        for row in rows.values()
    )
    zero_generation_usage = sum(_usage_is_zero(row, "generation") for row in rows.values())
    zero_judge_usage = sum(_usage_is_zero(row, "judge") for row in rows.values())
    inferred_reasons: list[str] = []
    if len(calls) < EXPECTED_PROVIDER_CALLS:
        inferred_reasons.append(
            f"provider_calls_below_expected_{len(calls)}_of_{EXPECTED_PROVIDER_CALLS}"
        )
    for endpoint, expected in (
        ("embedding", EXPECTED_EMBEDDING_CALLS),
        ("generation", EXPECTED_GENERATION_CALLS),
        ("judge", EXPECTED_JUDGE_CALLS),
    ):
        actual = int(result["provider_calls"][endpoint]["total"])
        if actual < expected:
            inferred_reasons.append(f"{endpoint}_calls_below_expected_{actual}_of_{expected}")
    if missing_generation_provider:
        inferred_reasons.append(f"missing_generation_provider_timing_{missing_generation_provider}")
    if missing_judge_provider:
        inferred_reasons.append(f"missing_judge_provider_timing_{missing_judge_provider}")
    if zero_generation_usage:
        inferred_reasons.append(f"zero_generation_usage_{zero_generation_usage}")
    if zero_judge_usage:
        inferred_reasons.append(f"zero_judge_usage_{zero_judge_usage}")
    explicit_contamination = cache_mode in {
        "shared",
        "shared-cache",
        "shared-cache-exploratory",
        "exploratory",
    }
    inferred_contamination = bool(inferred_reasons)
    result["cache_contaminated"] = (
        explicit_contamination
        or any(value["cached"] > 0 for value in result["provider_calls"].values())
        or result["query_rows"]["cached"] > 0
        or inferred_contamination
    )
    result["contamination_reasons"] = inferred_reasons
    result["expected_provider_calls"] = {
        "embedding": EXPECTED_EMBEDDING_CALLS,
        "generation": EXPECTED_GENERATION_CALLS,
        "judge": EXPECTED_JUDGE_CALLS,
        "total": EXPECTED_PROVIDER_CALLS,
    }
    result["uncached_latency_population"] = {
        "observations": result["query_rows"]["uncached"],
        "use": "descriptive_only" if result["cache_contaminated"] else "comparable",
    }
    return result


def _usage_is_zero(row: Mapping[str, Any], endpoint: str) -> bool:
    usage = row.get("usage")
    if not isinstance(usage, Mapping):
        return True
    values = usage.get(endpoint)
    if not isinstance(values, Mapping):
        return True
    return not any(
        _required_int(values.get(name, 0), f"{endpoint}.{name}") > 0
        for name in ("input_tokens", "cached_input_tokens", "output_tokens")
    )


def _cache_mode(summary: Mapping[str, Any], attestation: Mapping[str, Any] | None = None) -> str:
    """Read an optional producer cache label without inventing one."""

    for artifact in (summary, attestation or {}):
        direct = artifact.get("cache_mode")
        if isinstance(direct, str) and direct.strip():
            return direct.strip().lower()
        cache = artifact.get("cache")
        if isinstance(cache, Mapping):
            mode = cache.get("mode")
            if isinstance(mode, str) and mode.strip():
                return mode.strip().lower()
    return "unlabelled"


def _row_is_cached(row: Mapping[str, Any]) -> bool:
    usage = row.get("usage")
    return isinstance(usage, Mapping) and any(
        _required_int(
            _required_mapping(value, "query usage").get("cached_input_tokens", 0),
            "cached_input_tokens",
        )
        > 0
        for value in usage.values()
        if isinstance(value, Mapping)
    )


def _call_is_cached(call: Mapping[str, Any]) -> bool:
    usage = _required_mapping(call.get("usage"), "provider call usage")
    return _required_int(usage.get("cached_input_tokens", 0), "cached_input_tokens") > 0


def _stage_summaries(
    rows: Mapping[str, Mapping[str, Any]], calls: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    query_populations: dict[str, dict[str, list[float]]] = {
        "uncached": defaultdict(list),
        "cached": defaultdict(list),
    }
    for row in rows.values():
        population = "cached" if _row_is_cached(row) else "uncached"
        timings = _required_mapping(row.get("timings_ms"), "timings_ms")
        for name, value in timings.items():
            query_populations[population][str(name)].append(
                _required_float(value, f"timings_ms.{name}")
            )
    provider_populations: dict[str, dict[str, list[float]]] = {
        "uncached": defaultdict(list),
        "cached": defaultdict(list),
    }
    for call in calls:
        population = "cached" if _call_is_cached(call) else "uncached"
        provider_populations[population][f"{call.get('endpoint_type', 'unknown')}_provider"].append(
            _required_float(call.get("latency_ms"), "provider latency_ms")
        )
    query_summaries = {
        population: {name: summarize_values(values) for name, values in sorted(stages.items())}
        for population, stages in query_populations.items()
    }
    provider_summaries = {
        population: {name: summarize_values(values) for name, values in sorted(stages.items())}
        for population, stages in provider_populations.items()
    }
    # ``total_with_judge`` and ``answer_pipeline_without_live_retrieval`` are
    # aggregate clocks, not atomic layers.  They stay in the summaries but are
    # excluded from dominant-layer attribution.
    uncached_stages = query_populations["uncached"]
    totals = [float(value) for value in uncached_stages.get("total_with_judge", [])]
    dominant = None
    if totals:
        candidates = [
            (name, cast(float, summary["mean_ms"]))
            for name, summary in query_summaries["uncached"].items()
            if name not in {"total_with_judge", "answer_pipeline_without_live_retrieval"}
            and not name.endswith("_provider")
            if summary["mean_ms"] is not None
        ]
        if candidates:
            name, mean = max(candidates, key=lambda item: item[1])
            dominant = {
                "stage": name,
                "mean_ms": mean,
                "share_of_total_mean": mean / statistics.fmean(totals)
                if statistics.fmean(totals)
                else None,
            }
    return {
        # Backward-compatible names are explicitly the uncached population.
        "query_stages": query_summaries["uncached"],
        "provider_stages": provider_summaries["uncached"],
        "cached_query_stages": query_summaries["cached"],
        "cached_provider_stages": provider_summaries["cached"],
        "dominant_query_stage": dominant,
        "population": "uncached",
    }


def _mean_metric(
    rows: Mapping[str, Mapping[str, Any]],
    metric: str,
    section: str,
    *,
    answerable_only: bool = False,
) -> dict[str, Any]:
    values: list[float] = []
    for row in rows.values():
        if answerable_only and row.get("answerable") is not True:
            continue
        source = _required_mapping(row.get(section), section)
        if source.get(metric) is not None:
            values.append(_required_float(source[metric], f"{section}.{metric}"))
    return {
        "observations": len(values),
        "mean": statistics.fmean(values) if values else None,
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
    }


def _triad(rows: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    components: dict[str, Any] = {}
    for metric in RAG_TRIAD_COMPONENTS:
        components[metric] = _mean_metric(rows, metric, "judge")
        components[metric]["answerable_only"] = _mean_metric(
            rows, metric, "judge", answerable_only=True
        )
    per_query: dict[str, float] = {}
    for query_id, row in rows.items():
        if row.get("answerable") is not True:
            continue
        values = [
            _required_float(_required_mapping(row.get("judge"), "judge")[metric], f"judge.{metric}")
            for metric in RAG_TRIAD_COMPONENTS
            if _required_mapping(row.get("judge"), "judge").get(metric) is not None
        ]
        if len(values) == len(RAG_TRIAD_COMPONENTS):
            per_query[query_id] = statistics.fmean(values)
    composite = {
        "observations": len(per_query),
        "mean": statistics.fmean(per_query.values()) if per_query else None,
        "population": "answerable_only",
        "definition": "secondary arithmetic mean of context_relevance, groundedness, and answer_relevance; not a canonical RAG Triad metric",
    }
    return {
        "components": components,
        "secondary_composite": composite,
        "_composite_by_query": per_query,
    }


def _paired_metric(
    baseline: Mapping[str, Mapping[str, Any]],
    condition: Mapping[str, Mapping[str, Any]],
    metric: str,
    section: str,
    *,
    seed: int,
    higher_is_better: bool,
    samples: int,
    answerable_only: bool,
) -> dict[str, Any]:
    deltas: list[float] = []
    for query_id in EXPECTED_QUERY_IDS:
        if answerable_only and (
            baseline[query_id].get("answerable") is not True
            or condition[query_id].get("answerable") is not True
        ):
            continue
        left = _required_mapping(baseline[query_id].get(section), section).get(metric)
        right = _required_mapping(condition[query_id].get(section), section).get(metric)
        if left is None or right is None:
            continue
        deltas.append(
            _required_float(right, f"{section}.{metric}")
            - _required_float(left, f"{section}.{metric}")
        )
    wins = sum(delta > 1e-12 if higher_is_better else delta < -1e-12 for delta in deltas)
    losses = sum(delta < -1e-12 if higher_is_better else delta > 1e-12 for delta in deltas)
    ties = len(deltas) - wins - losses
    p_value = sign_flip_pvalue(deltas, seed=seed + 1, samples=samples)
    return {
        "metric": metric,
        "section": section,
        "direction": "higher" if higher_is_better else "lower",
        "population": "answerable_only" if answerable_only else "all_queries",
        "paired_query_count": len(deltas),
        "mean_delta": statistics.fmean(deltas) if deltas else None,
        "bootstrap_ci95": bootstrap_ci(deltas, seed=seed, samples=samples),
        "sign_flip_p": p_value,
        "sign_flip_p_value": p_value,
        "wins": wins,
        "ties": ties,
        "losses": losses,
        "w_t_l": [wins, ties, losses],
    }


def _pareto(cells: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for cell_id, value in cells.items():
        triad = value["rag_triad"]["secondary_composite"].get("mean")
        retrieval = value["retrieval_latency"]
        latency = retrieval.get("p95_ms")
        if triad is None or latency is None:
            continue
        points.append(
            {
                "cell_id": cell_id,
                "quality_secondary_composite_mean": float(triad),
                "retrieval_p95_ms": float(latency),
                "retrieval_observations": retrieval.get("observations"),
            }
        )
    frontier: list[dict[str, Any]] = []
    for candidate in points:
        dominated = False
        for other in points:
            if other is candidate:
                continue
            no_worse = (
                other["quality_secondary_composite_mean"]
                >= candidate["quality_secondary_composite_mean"]
                and other["retrieval_p95_ms"] <= candidate["retrieval_p95_ms"]
            )
            strictly = (
                other["quality_secondary_composite_mean"]
                > candidate["quality_secondary_composite_mean"]
                or other["retrieval_p95_ms"] < candidate["retrieval_p95_ms"]
            )
            if no_worse and strictly:
                dominated = True
                break
        if not dominated:
            frontier.append(candidate)
    return sorted(frontier, key=lambda point: point["cell_id"])


def analyze(
    input_dirs: Sequence[Path],
    *,
    seed: int = DEFAULT_SEED,
    bootstrap_samples: int = DEFAULT_BOOTSTRAP_SAMPLES,
) -> dict[str, Any]:
    """Validate and aggregate the complete ten-cell matrix."""

    validated = validate_matrix(input_dirs)
    baseline_id = "openai-text-embedding-3-small-d1024"
    cells: dict[str, Any] = {}
    hypotheses: dict[str, float | None] = {}
    for cell_id, data in validated.items():
        rows = data["rows"]
        calls = data["calls"]
        timings = _stage_summaries(rows, calls)
        retrieval_summary = timings["query_stages"].get("context_select_or_dense_retrieval", {})
        triad = _triad(rows)
        cost = _provider_cost(calls)
        cache_mode = _cache_mode(data["summary"], data["attestation"])
        cache_denominators = _cache_denominators(rows, calls, cache_mode=cache_mode)
        cost["cross_cell_comparable"] = False
        cost["cross_cell_comparability_reason"] = (
            "observed spend is descriptive only; cache state and provider call mix differ across cells"
        )
        source_retrieval = {
            "document_hit_or_evidence_coverage": _mean_metric(
                rows, "retrieval_evidence_coverage", "metrics"
            ),
            "section_evidence": {
                "available": False,
                "value": None,
                "reason": "chunk/document hits are not section-level qrels and are never promoted to section evidence",
            },
        }
        cells[cell_id] = {
            "cell": data["cell"],
            "denominator": EXPECTED_DENOMINATOR,
            "cache_denominators": cache_denominators,
            "cost": cost,
            "rag_triad": {key: value for key, value in triad.items() if not key.startswith("_")},
            "retrieval_quality": source_retrieval,
            "retrieval_latency": retrieval_summary,
            "atomic_latency": timings,
            "provider_call_count": len(calls),
            "errors": {"query_errors": 0, "provider_call_errors": 0},
        }
    baseline = validated[baseline_id]["rows"]
    matrix_cache_contaminated = any(
        bool(cell["cache_denominators"]["cache_contaminated"]) for cell in cells.values()
    )
    comparisons: dict[str, Any] = {}
    for index, (cell_id, data) in enumerate(validated.items()):
        if cell_id == baseline_id:
            continue
        metrics: list[dict[str, Any]] = []
        for metric_index, metric in enumerate(RAG_TRIAD_COMPONENTS):
            result = _paired_metric(
                baseline,
                data["rows"],
                metric,
                "judge",
                seed=seed + index * 100 + metric_index * 10,
                higher_is_better=True,
                samples=bootstrap_samples,
                answerable_only=True,
            )
            key = f"{cell_id}:{metric}"
            hypotheses[key] = result["sign_flip_p"]
            metrics.append(result)
        latency_metrics = ["context_select_or_dense_retrieval"]
        if not matrix_cache_contaminated:
            latency_metrics.append("total_with_judge")
        for metric_index, metric in enumerate(latency_metrics):
            result = _paired_metric(
                baseline,
                data["rows"],
                metric,
                "timings_ms",
                seed=seed + index * 100 + 50 + metric_index * 10,
                higher_is_better=False,
                samples=bootstrap_samples,
                answerable_only=False,
            )
            key = f"{cell_id}:{metric}"
            hypotheses[key] = result["sign_flip_p"]
            metrics.append(result)
        comparisons[cell_id] = {"baseline_cell_id": baseline_id, "metrics": metrics}
    corrected = holm_correction(hypotheses)
    for cell_id, comparison in comparisons.items():
        for metric in comparison["metrics"]:
            holm = corrected[f"{cell_id}:{metric['metric']}"]
            metric.update({"holm": holm, "holm_adjusted_p": holm["holm_p"]})
    frontier = _pareto(cells)
    return {
        "schema_version": SCHEMA_VERSION,
        "benchmark": "open-manuals-v2",
        "analysis": {
            "seed": seed,
            "bootstrap_samples": bootstrap_samples,
            "alpha": ALPHA,
            "baseline_cell_id": baseline_id,
            "cache_contaminated_matrix": matrix_cache_contaminated,
            "cache_contaminated_cells": sorted(
                cell_id
                for cell_id, cell in cells.items()
                if cell["cache_denominators"]["cache_contaminated"]
            ),
            "privacy": {
                "prompts_persisted": False,
                "answers_persisted": False,
                "document_text_persisted": False,
                "provider_response_bodies_persisted": False,
            },
            "evidence_policy": "document hit is not section evidence; section-level qrels are unavailable",
            "cache_policy": "cached and uncached denominators are reported separately and never pooled for comparable latency",
            "provider_spend_policy": "observed provider spend is descriptive only and excluded from cross-cell Pareto ranking",
        },
        "cells": cells,
        "paired_comparisons": comparisons,
        "holm_correction": corrected,
        "pareto_frontier": {
            "definition": "secondary self-judge RAG Triad arithmetic composite maximize, fresh uncached retrieval p95 minimize; provider spend and total answer latency excluded because cache state is not cross-cell comparable",
            "quality_metric": "secondary_rag_triad_self_judge_answerable_mean",
            "latency_metric": "uncached_context_select_or_dense_retrieval_p95_ms",
            "provider_spend_included": False,
            "cells": frontier,
        },
    }


def markdown_report(result: Mapping[str, Any]) -> str:
    cells = _required_mapping(result.get("cells"), "result.cells")
    analysis = _required_mapping(result.get("analysis"), "result.analysis")
    cache_contaminated = bool(analysis.get("cache_contaminated_matrix"))
    lines = [
        "# Open Manuals embedding matrix analysis",
        "",
        "Privacy-safe post-processing of ten completed 70-query cells.",
        "",
        "- Section evidence: unavailable; document/chunk hit is not treated as section evidence.",
        "- Cached and uncached totals are reported separately and never pooled for comparable latency.",
        "- Observed provider spend is descriptive only and is not used to compare cells or rank the Pareto frontier.",
        "- RAG Triad components are primary; the arithmetic composite is explicitly secondary.",
        "",
        "## Cell summary",
        "",
        "| Cell | Dimension | Triad context | Groundedness | Answer relevance | Fresh retrieval p95 (ms) | N | Observed cost (USD; descriptive) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for cell_id, cell in sorted(cells.items()):
        triad = _required_mapping(cell.get("rag_triad"), f"cells.{cell_id}.rag_triad")
        components = _required_mapping(triad.get("components"), "triad.components")
        values = [
            _required_mapping(components.get(name), name).get("mean")
            for name in RAG_TRIAD_COMPONENTS
        ]
        dimension = _required_mapping(cell.get("cell"), "cell").get("dimension")
        retrieval = _required_mapping(cell.get("retrieval_latency"), "retrieval_latency")
        cost = _required_mapping(cell.get("cost"), "cost").get("actual_provider_cost_usd")

        def fmt(value: object) -> str:
            return "n/a" if value is None else f"{_required_float(value, 'markdown metric'):.4f}"

        lines.append(
            f"| `{cell_id}` | {dimension} | {fmt(values[0])} | {fmt(values[1])} | {fmt(values[2])} | {fmt(retrieval.get('p95_ms'))} | {retrieval.get('observations', 'n/a')} | {cost} |"
        )
    frontier = _required_mapping(result.get("pareto_frontier"), "pareto_frontier")
    lines.extend(
        [
            "",
            "## Pareto frontier",
            "",
            "The frontier maximizes the clearly labeled secondary self-judge Triad composite while minimizing fresh uncached retrieval p95. Provider spend and total answer latency are excluded because cache state is not cross-cell comparable.",
            "",
            "| Cell | Secondary self-judge Triad composite | Fresh retrieval p95 (ms) | N |",
            "|---|---:|---:|---:|",
        ]
    )
    for point in frontier.get("cells", []):
        lines.append(
            f"| `{point['cell_id']}` | {_required_float(point['quality_secondary_composite_mean'], 'frontier quality'):.4f} | {_required_float(point['retrieval_p95_ms'], 'frontier latency'):.4f} | {point.get('retrieval_observations', 'n/a')} |"
        )
    lines.extend(
        [
            "",
            "## Paired inference",
            "",
            (
                "Each non-baseline cell is paired query-by-query with `openai-text-embedding-3-small-d1024`; intervals are 10,000-resample query bootstraps, p-values are seeded sign-flip tests, and Holm correction spans all listed hypotheses. Because this matrix contains cache-contaminated cells, total/generation/judge latency hypotheses are excluded; uncached stage summaries are descriptive with their N."
                if cache_contaminated
                else "Each non-baseline cell is paired query-by-query with `openai-text-embedding-3-small-d1024`; intervals are 10,000-resample query bootstraps, p-values are seeded sign-flip tests, and Holm correction spans all listed hypotheses."
            ),
            "",
            "| Cell | Metric | N | Mean delta | 95% CI | W/T/L | Sign-flip p | Holm p |",
            "|---|---|---:|---:|---|---:|---:|---:|",
        ]
    )
    for cell_id, comparison in sorted(
        _required_mapping(result.get("paired_comparisons"), "paired_comparisons").items()
    ):
        for metric in _required_mapping(comparison, "comparison").get("metrics", []):
            ci = metric.get("bootstrap_ci95")
            ci_text = "n/a" if ci is None else f"[{float(ci[0]):.4f}, {float(ci[1]):.4f}]"
            holm = _required_mapping(metric.get("holm"), "holm")
            lines.append(
                f"| `{cell_id}` | {metric['metric']} | {metric['paired_query_count']} | {metric['mean_delta'] if metric['mean_delta'] is not None else 'n/a'} | {ci_text} | {metric['wins']}/{metric['ties']}/{metric['losses']} | {metric['sign_flip_p']:.6f} | {float(holm['holm_p']):.6f} |"
            )
    return "\n".join(lines) + "\n"


def write_outputs(result: Mapping[str, Any], output_json: Path, output_markdown: Path) -> None:
    """Write both outputs atomically with an explicit refuse-overwrite policy."""

    if output_json == output_markdown or output_json.exists() or output_markdown.exists():
        raise OutputExistsError("refusing to overwrite an existing analyzer output")
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_markdown.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output_markdown.write_text(markdown_report(result), encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir",
        action="append",
        required=True,
        type=Path,
        help="one completed cell artifact directory; repeat exactly ten times",
    )
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-markdown", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--bootstrap-samples", type=int, default=DEFAULT_BOOTSTRAP_SAMPLES)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = analyze(args.input_dir, seed=args.seed, bootstrap_samples=args.bootstrap_samples)
    write_outputs(result, args.output_json, args.output_markdown)
    print(
        json.dumps(
            {
                "status": "completed",
                "output_json": str(args.output_json.resolve()),
                "output_markdown": str(args.output_markdown.resolve()),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (MatrixAnalysisError, OutputExistsError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
