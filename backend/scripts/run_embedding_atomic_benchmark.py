#!/usr/bin/env python3
"""Run a privacy-safe, atomic OpenAI embedding latency matrix.

The runner intentionally lives beside ``embedding_benchmark_matrix.py`` and
uses that module's immutable model/width aliases.  It does not persist input
text, request bodies, response bodies, API keys, or exception messages.  A
run consists of ten cells, four fixed input counts, two HTTP-client lifecycle
conditions, counterbalanced repetitions, and stage timings that close exactly
to the reported total.

The public functions are deliberately transport-injectable so that validation
and accounting can be tested with ``httpx.MockTransport`` without contacting a
provider.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import statistics
import time
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from embedding_benchmark_matrix import (
    EmbeddingCell,
    InvalidEmbeddingCellError,
    cells,
)

SCHEMA_VERSION = 1
RUNNER_VERSION = "1.0"
DEFAULT_BASE_URL = "http://127.0.0.1:54000"
INPUT_COUNTS = (1, 3, 8, 32)
CLIENT_MODES: tuple[Literal["persistent", "new"], ...] = ("persistent", "new")
STAGE_NAMES = (
    "request_build_ms",
    "http_wall_ms",
    "response_decode_ms",
    "vector_validation_ms",
)
EXPECTED_STATUS = 200
# The numbered synthetic inputs are empirically attested at seven provider
# tokens each.  Larger counts retain the same fixed per-input budget, which is
# also the declared request/cost-ceiling basis.
EXPECTED_TOTAL_TOKENS = {1: 7, 3: 21, 8: 56, 32: 224}
DEFAULT_WARMUPS = 2
DEFAULT_REPETITIONS = 25
DEFAULT_BOOTSTRAP_SAMPLES = 2_000
DEFAULT_BOOTSTRAP_SEED = 42
DEFAULT_MAX_REQUESTS = 5_000
DEFAULT_MAX_INPUT_TOKENS = 1_000_000
DEFAULT_MAX_COST_USD = 5.0
MODEL_COST_PER_INPUT_TOKEN = {
    "text-embedding-3-small": 0.02 / 1_000_000,
    "text-embedding-3-large": 0.13 / 1_000_000,
}
SYNTHETIC_INPUTS = tuple(
    f"synthetic networking latency probe {index:02d}" for index in range(1, 33)
)


class AtomicBenchmarkError(RuntimeError):
    """Base class for typed benchmark failures."""


class BenchmarkBudgetError(AtomicBenchmarkError, ValueError):
    """The configured request, token, or cost ceiling would be exceeded."""


class BenchmarkValidationError(AtomicBenchmarkError, ValueError):
    """A scored response or persisted row violates the benchmark contract."""


class BenchmarkCredentialError(AtomicBenchmarkError):
    """No in-memory provider/proxy API key was supplied."""


@dataclass(frozen=True, slots=True)
class Condition:
    """One cell/input-count/client-lifecycle combination."""

    cell: EmbeddingCell
    input_count: int
    client_mode: Literal["persistent", "new"]

    def __post_init__(self) -> None:
        if self.input_count not in INPUT_COUNTS:
            raise ValueError(f"unsupported input count: {self.input_count}")
        if self.client_mode not in CLIENT_MODES:
            raise ValueError(f"unsupported client mode: {self.client_mode}")

    @property
    def condition_id(self) -> str:
        return f"{self.cell.cell_id}|n{self.input_count}|{self.client_mode}"


@dataclass(frozen=True, slots=True)
class BenchmarkConfig:
    """Immutable run configuration; no credential is held in this object."""

    output: Path
    warmups: int = DEFAULT_WARMUPS
    repetitions: int = DEFAULT_REPETITIONS
    seed: int = DEFAULT_BOOTSTRAP_SEED
    concurrency: int = 1
    max_retries: int = 0
    max_requests: int = DEFAULT_MAX_REQUESTS
    max_input_tokens: int = DEFAULT_MAX_INPUT_TOKENS
    max_cost_usd: float = DEFAULT_MAX_COST_USD
    bootstrap_samples: int = DEFAULT_BOOTSTRAP_SAMPLES
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED
    base_url: str = DEFAULT_BASE_URL
    selected_cells: tuple[EmbeddingCell, ...] = field(default_factory=cells)
    expected_tokens_by_count: Mapping[int, int] = field(
        default_factory=lambda: dict(EXPECTED_TOTAL_TOKENS)
    )

    def __post_init__(self) -> None:
        if self.warmups < 0 or self.repetitions < 25:
            raise ValueError("warmups must be nonnegative and repetitions must be at least 25")
        if self.concurrency < 1:
            raise ValueError("concurrency must be positive")
        if self.max_retries < 0:
            raise ValueError("max_retries must be nonnegative")
        if self.max_requests < 1 or self.max_input_tokens < 1 or self.max_cost_usd <= 0:
            raise ValueError("request, token, and cost ceilings must be positive")
        if self.bootstrap_samples < 100:
            raise ValueError("bootstrap_samples must be at least 100")
        if not self.selected_cells:
            raise ValueError("at least one embedding cell is required")
        if len({cell.cell_id for cell in self.selected_cells}) != len(self.selected_cells):
            raise ValueError("selected embedding cells must be unique")
        if tuple(self.expected_tokens_by_count) != tuple(INPUT_COUNTS):
            raise ValueError("expected token accounting must cover input counts in order")
        if any(
            int(self.expected_tokens_by_count[count]) <= 0 for count in INPUT_COUNTS
        ):
            raise ValueError("expected token counts must be positive")
        _validate_base_url(self.base_url)

    @property
    def conditions_per_cell(self) -> int:
        return len(INPUT_COUNTS) * len(CLIENT_MODES)

    @property
    def expected_scored_observations(self) -> int:
        return len(self.selected_cells) * self.conditions_per_cell * self.repetitions

    @property
    def expected_total_attempt_budget(self) -> int:
        requests = len(self.selected_cells) * self.conditions_per_cell
        return requests * (self.warmups + self.repetitions) * (self.max_retries + 1)

    @property
    def expected_input_token_budget(self) -> int:
        per_cell = sum(
            self.expected_tokens_by_count[count] * len(CLIENT_MODES)
            for count in INPUT_COUNTS
        )
        return (
            len(self.selected_cells)
            * (self.warmups + self.repetitions)
            * per_cell
            * (self.max_retries + 1)
        )

    @property
    def expected_cost_usd(self) -> float:
        return sum(
            self.expected_input_token_budget
            * MODEL_COST_PER_INPUT_TOKEN[cell.model]
            / len(self.selected_cells)
            for cell in self.selected_cells
        )


@dataclass(frozen=True, slots=True)
class AttemptResult:
    stage_ms: Mapping[str, float]
    status_code: int | None
    response_bytes: int
    error_type: str | None
    error_stage: str | None
    dimension: int | None
    vector_count: int | None
    total_tokens: int | None


def _validate_base_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("embedding base URL must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("embedding base URL must not contain credentials, query, or fragment")
    return value.rstrip("/")


def _api_key(env: Mapping[str, str] | None, supplied: str | None) -> str:
    if supplied:
        return supplied
    source = os.environ if env is None else env
    key = source.get("RAGZ_LITELLM_MASTER_KEY") or source.get("LITELLM_MASTER_KEY")
    if key:
        return key
    raise BenchmarkCredentialError("LiteLLM API key is unavailable")


def _client(
    config: BenchmarkConfig, key: str, transport: httpx.BaseTransport | None
) -> httpx.Client:
    return httpx.Client(
        base_url=_validate_base_url(config.base_url),
        headers={"Authorization": f"Bearer {key}"},
        timeout=httpx.Timeout(60.0, connect=10.0),
        transport=transport,
    )


def fixed_inputs(input_count: int) -> tuple[str, ...]:
    """Return a new immutable slice of the fixed synthetic input set."""

    if input_count not in INPUT_COUNTS:
        raise ValueError(f"unsupported input count: {input_count}")
    return tuple(SYNTHETIC_INPUTS[:input_count])


def build_schedule(
    cell: EmbeddingCell, *, seed: int = DEFAULT_BOOTSTRAP_SEED, repetition: int = 1
) -> tuple[Condition, ...]:
    """Build a deterministic randomized/counterbalanced condition order."""

    if repetition < 1:
        raise ValueError("repetition must be positive")
    conditions = [
        Condition(cell=cell, input_count=count, client_mode=mode)
        for count in INPUT_COUNTS
        for mode in CLIENT_MODES
    ]
    random.Random(seed).shuffle(conditions)  # noqa: S311 - deterministic ordering, not secrets
    if repetition % 2 == 0:
        conditions.reverse()
    return tuple(conditions)


def _percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise BenchmarkValidationError("cannot compute a percentile for no observations")
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def bootstrap_ci(
    values: Sequence[float], *, seed: int, samples: int
) -> tuple[float, float]:
    """Return a deterministic percentile bootstrap CI for the arithmetic mean."""

    if not values:
        raise BenchmarkValidationError("cannot bootstrap no observations")
    generator = random.Random(seed)  # noqa: S311 - deterministic statistical resampling
    means = [
        statistics.fmean(generator.choices(tuple(values), k=len(values)))
        for _ in range(samples)
    ]
    return (_percentile(means, 0.025), _percentile(means, 0.975))


def _error_row(
    *,
    condition: Condition,
    sequence: int,
    repetition: int,
    order_index: int,
    phase: Literal["warmup", "scored"],
    attempt: AttemptResult,
    retries: int,
    total_stage_ms: Mapping[str, float],
    response_bytes: int,
) -> dict[str, Any]:
    return {
        "sequence": sequence,
        "phase": phase,
        "scored": phase == "scored",
        "repetition": repetition,
        "order_index": order_index,
        "cell_id": condition.cell.cell_id,
        "alias": condition.cell.alias,
        "model": condition.cell.model,
        "dimension_expected": condition.cell.dimension,
        "input_count": condition.input_count,
        "client_mode": condition.client_mode,
        "status_code": attempt.status_code,
        "dimension_actual": attempt.dimension,
        "vector_count": attempt.vector_count,
        "total_tokens": attempt.total_tokens,
        "response_bytes": response_bytes,
        "retries": retries,
        "error": attempt.error_type,
        "error_stage": attempt.error_stage,
        "stage_timings_ms": {
            name: round(float(total_stage_ms[name]), 6) for name in STAGE_NAMES
        },
        "total_ms": round(sum(float(total_stage_ms[name]) for name in STAGE_NAMES), 6),
    }


def _attempt(
    client: httpx.Client,
    condition: Condition,
    expected_tokens: int,
) -> AttemptResult:
    stages = {name: 0.0 for name in STAGE_NAMES}
    status_code: int | None = None
    response_bytes = 0
    dimension: int | None = None
    vector_count: int | None = None
    total_tokens: int | None = None
    started = time.perf_counter()
    try:
        build_started = time.perf_counter()
        payload = {
            "model": condition.cell.alias,
            "input": list(fixed_inputs(condition.input_count)),
        }
        request = client.build_request("POST", "/v1/embeddings", json=payload)
        stages["request_build_ms"] = (time.perf_counter() - build_started) * 1000
    except Exception as exc:  # noqa: BLE001 - only type is persisted
        stages["total_ms"] = (time.perf_counter() - started) * 1000
        return AttemptResult(
            stage_ms=stages,
            status_code=None,
            response_bytes=0,
            error_type=type(exc).__name__,
            error_stage="request_build",
            dimension=None,
            vector_count=None,
            total_tokens=None,
        )
    http_started = time.perf_counter()
    try:
        response = client.send(request)
        stages["http_wall_ms"] = (time.perf_counter() - http_started) * 1000
        status_code = response.status_code
        response_bytes = len(response.content)
    except Exception as exc:  # noqa: BLE001 - only type is persisted
        stages["http_wall_ms"] = (time.perf_counter() - http_started) * 1000
        return AttemptResult(
            stage_ms=stages,
            status_code=None,
            response_bytes=0,
            error_type=type(exc).__name__,
            error_stage="http",
            dimension=None,
            vector_count=None,
            total_tokens=None,
        )
    if status_code != EXPECTED_STATUS:
        return AttemptResult(
            stage_ms=stages,
            status_code=status_code,
            response_bytes=response_bytes,
            error_type="UnexpectedStatusError",
            error_stage="status",
            dimension=None,
            vector_count=None,
            total_tokens=None,
        )
    decode_started = time.perf_counter()
    try:
        body = response.json()
        stages["response_decode_ms"] = (time.perf_counter() - decode_started) * 1000
    except Exception as exc:  # noqa: BLE001 - only type is persisted
        stages["response_decode_ms"] = (time.perf_counter() - decode_started) * 1000
        return AttemptResult(
            stage_ms=stages,
            status_code=status_code,
            response_bytes=response_bytes,
            error_type=type(exc).__name__,
            error_stage="response_decode",
            dimension=None,
            vector_count=None,
            total_tokens=None,
        )
    validate_started = time.perf_counter()
    try:
        if not isinstance(body, Mapping):
            raise BenchmarkValidationError("response body is not an object")
        raw_data: object = body.get("data")
        if not isinstance(raw_data, list):
            raise BenchmarkValidationError("response data is not a list")
        vector_count = len(raw_data)
        if vector_count != condition.input_count:
            raise BenchmarkValidationError("response vector count is not exact")
        for item in raw_data:
            if not isinstance(item, Mapping) or not isinstance(item.get("embedding"), list):
                raise BenchmarkValidationError("response vector is invalid")
            vector = item["embedding"]
            if len(vector) != condition.cell.dimension:
                raise BenchmarkValidationError("response vector width is not exact")
            if any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                for value in vector
            ):
                raise BenchmarkValidationError("response vector contains invalid values")
        usage = body.get("usage")
        if (
            not isinstance(usage, Mapping)
            or not isinstance(usage.get("total_tokens"), int)
            or isinstance(usage.get("total_tokens"), bool)
        ):
            raise BenchmarkValidationError("response token usage is missing")
        total_tokens = int(usage["total_tokens"])
        if total_tokens != expected_tokens:
            raise BenchmarkValidationError("response token usage is not exact")
    except Exception as exc:  # noqa: BLE001 - only type is persisted
        stages["vector_validation_ms"] = (time.perf_counter() - validate_started) * 1000
        first_embedding: list[object] | None = None
        if isinstance(raw_data, list) and raw_data and isinstance(raw_data[0], Mapping):
            candidate = raw_data[0].get("embedding")
            if isinstance(candidate, list):
                first_embedding = candidate
        return AttemptResult(
            stage_ms=stages,
            status_code=status_code,
            response_bytes=response_bytes,
            error_type=type(exc).__name__,
            error_stage="vector_validation",
            dimension=len(first_embedding) if first_embedding is not None else None,
            vector_count=vector_count,
            total_tokens=total_tokens,
        )
    stages["vector_validation_ms"] = (time.perf_counter() - validate_started) * 1000
    dimension = condition.cell.dimension
    return AttemptResult(
        stage_ms=stages,
        status_code=status_code,
        response_bytes=response_bytes,
        error_type=None,
        error_stage=None,
        dimension=dimension,
        vector_count=vector_count,
        total_tokens=total_tokens,
    )


def _should_retry(attempt: AttemptResult) -> bool:
    return attempt.error_type in {
        "ConnectError",
        "ReadTimeout",
        "WriteTimeout",
        "PoolTimeout",
    } or (
        attempt.status_code is not None
        and attempt.status_code in {408, 425, 429, 500, 502, 503, 504}
    )


def _run_condition(
    config: BenchmarkConfig,
    condition: Condition,
    *,
    client: httpx.Client | None,
    transport: httpx.BaseTransport | None,
    key: str,
    phase: Literal["warmup", "scored"],
    repetition: int,
    order_index: int,
    sequence: int,
) -> dict[str, Any]:
    own_client = client is None
    active_client = client or _client(config, key, transport)
    attempts: list[AttemptResult] = []
    try:
        for _attempt_index in range(config.max_retries + 1):
            result = _attempt(
                active_client,
                condition,
                int(config.expected_tokens_by_count[condition.input_count]),
            )
            attempts.append(result)
            if result.error_type is None or not _should_retry(result):
                break
        stage_totals = {
            name: sum(float(attempt.stage_ms[name]) for attempt in attempts)
            for name in STAGE_NAMES
        }
        final = attempts[-1]
        return _error_row(
            condition=condition,
            sequence=sequence,
            repetition=repetition,
            order_index=order_index,
            phase=phase,
            attempt=final,
            retries=len(attempts) - 1,
            total_stage_ms=stage_totals,
            response_bytes=sum(attempt.response_bytes for attempt in attempts),
        )
    finally:
        if own_client:
            active_client.close()


def _validate_run_budget(config: BenchmarkConfig) -> None:
    if config.expected_total_attempt_budget > config.max_requests:
        raise BenchmarkBudgetError(
            f"planned attempts {config.expected_total_attempt_budget} exceed max_requests "
            f"{config.max_requests}"
        )
    if config.expected_input_token_budget > config.max_input_tokens:
        raise BenchmarkBudgetError(
            f"planned input tokens {config.expected_input_token_budget} exceed max_input_tokens "
            f"{config.max_input_tokens}"
        )
    per_cell_cost = {
        cell.cell_id: config.expected_input_token_budget
        / len(config.selected_cells)
        * MODEL_COST_PER_INPUT_TOKEN[cell.model]
        for cell in config.selected_cells
    }
    if sum(per_cell_cost.values()) > config.max_cost_usd:
        raise BenchmarkBudgetError(
            f"planned cost ${sum(per_cell_cost.values()):.6f} exceeds max_cost_usd "
            f"${config.max_cost_usd:.6f}"
        )


def _required_int(row: Mapping[str, Any], field_name: str) -> int:
    value = row.get(field_name)
    if isinstance(value, bool) or value is None:
        raise BenchmarkValidationError(f"row field {field_name} is missing or invalid")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise BenchmarkValidationError(f"row field {field_name} is invalid") from exc


def _required_float(row: Mapping[str, Any], field_name: str) -> float:
    value = row.get(field_name)
    if isinstance(value, bool) or value is None:
        raise BenchmarkValidationError(f"row field {field_name} is missing or invalid")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise BenchmarkValidationError(f"row field {field_name} is invalid") from exc


def _validate_row_timing(row: Mapping[str, Any]) -> None:
    stages = row.get("stage_timings_ms")
    if not isinstance(stages, Mapping) or set(stages) != set(STAGE_NAMES):
        raise BenchmarkValidationError("row stage timing schema is invalid")
    values = [float(stages[name]) for name in STAGE_NAMES]
    total = _required_float(row, "total_ms")
    if any(value < 0 or not math.isfinite(value) for value in values) or total < 0:
        raise BenchmarkValidationError("row timing contains an invalid value")
    if abs(sum(values) - total) > 0.00001:
        raise BenchmarkValidationError("row timing stages do not close to total")


def _expected_order_rows(
    rows: Sequence[Mapping[str, Any]], config: BenchmarkConfig
) -> None:
    by_cell_rep: dict[tuple[str, int], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        by_cell_rep[(str(row["cell_id"]), _required_int(row, "repetition"))].append(row)
    for cell in config.selected_cells:
        for repetition in range(1, config.repetitions + 1):
            actual = by_cell_rep.get((cell.cell_id, repetition), [])
            if len(actual) != config.conditions_per_cell:
                raise BenchmarkValidationError("condition denominator is incomplete")
            expected = build_schedule(cell, seed=config.seed, repetition=repetition)
            actual_ids = [
                str(row["cell_id"])
                + f"|n{_required_int(row, 'input_count')}|{row['client_mode']}"
                for row in sorted(actual, key=lambda row: _required_int(row, "order_index"))
            ]
            if actual_ids != [condition.condition_id for condition in expected]:
                raise BenchmarkValidationError(
                    "condition order is not deterministic/counterbalanced"
                )


def validate_scored_records(records: Sequence[Mapping[str, Any]], config: BenchmarkConfig) -> None:
    """Validate every scored row and the complete cell/count/mode denominator."""

    scored = [row for row in records if bool(row.get("scored"))]
    if len(scored) != config.expected_scored_observations:
        raise BenchmarkValidationError("scored observation denominator is incomplete")
    expected_sequences = list(range(1, len(records) + 1))
    if [_required_int(row, "sequence") for row in records] != expected_sequences:
        raise BenchmarkValidationError("row sequence is not contiguous")
    keys: list[tuple[str, int, str, int]] = []
    valid_cells = {cell.cell_id: cell for cell in config.selected_cells}
    for row in scored:
        cell = valid_cells.get(str(row.get("cell_id")))
        if cell is None:
            raise BenchmarkValidationError("row references an unknown cell")
        input_count = _required_int(row, "input_count")
        mode = str(row.get("client_mode"))
        if input_count not in INPUT_COUNTS or mode not in CLIENT_MODES:
            raise BenchmarkValidationError("row references an unknown condition")
        if (
            _required_int(row, "dimension_expected") != cell.dimension
            or _required_int(row, "dimension_actual") != cell.dimension
        ):
            raise BenchmarkValidationError("row vector width is not exact")
        if _required_int(row, "vector_count") != input_count:
            raise BenchmarkValidationError("row vector count is not exact")
        if _required_int(row, "total_tokens") != int(config.expected_tokens_by_count[input_count]):
            raise BenchmarkValidationError("row token count is not exact")
        if _required_int(row, "status_code") != EXPECTED_STATUS or row.get("error") is not None:
            raise BenchmarkValidationError("row status or error is invalid")
        _validate_row_timing(row)
        keys.append((cell.cell_id, input_count, mode, _required_int(row, "repetition")))
    expected_keys = {
        (cell.cell_id, count, mode, repetition)
        for cell in config.selected_cells
        for count in INPUT_COUNTS
        for mode in CLIENT_MODES
        for repetition in range(1, config.repetitions + 1)
    }
    if set(keys) != expected_keys or len(keys) != len(set(keys)):
        raise BenchmarkValidationError(
            "condition/repetition denominator is incomplete or duplicated"
        )
    _expected_order_rows(scored, config)


def _metric_summary(values: Sequence[float], *, seed: int, samples: int) -> dict[str, Any]:
    return {
        "observations": len(values),
        "mean_ms": statistics.fmean(values),
        "p50_ms": _percentile(values, 0.50),
        "p95_ms": _percentile(values, 0.95),
        "p99_ms": _percentile(values, 0.99),
        "bootstrap_ci95_ms": list(bootstrap_ci(values, seed=seed, samples=samples)),
    }


def summarize_records(
    records: Sequence[Mapping[str, Any]], config: BenchmarkConfig
) -> dict[str, Any]:
    """Recompute all aggregate metrics from JSONL-compatible rows."""

    validate_scored_records(records, config)
    scored = [row for row in records if bool(row.get("scored"))]
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in scored:
        key = f"{row['cell_id']}|n{int(row['input_count'])}|{row['client_mode']}"
        grouped[key].append(row)
    output_groups: dict[str, Any] = {}
    for key in sorted(grouped):
        rows = grouped[key]
        metrics: dict[str, Any] = {}
        for index, metric in enumerate((*STAGE_NAMES, "total_ms")):
            values = [
                float(row["total_ms"] if metric == "total_ms" else row["stage_timings_ms"][metric])
                for row in rows
            ]
            metrics[metric] = _metric_summary(
                values,
                seed=config.bootstrap_seed + index,
                samples=config.bootstrap_samples,
            )
        output_groups[key] = {
            "cell_id": rows[0]["cell_id"],
            "alias": rows[0]["alias"],
            "model": rows[0]["model"],
            "dimension": int(rows[0]["dimension_expected"]),
            "input_count": int(rows[0]["input_count"]),
            "client_mode": rows[0]["client_mode"],
            "observations": len(rows),
            "metrics": metrics,
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "runner_version": RUNNER_VERSION,
        "observations": len(scored),
        "expected_observations": config.expected_scored_observations,
        "groups": output_groups,
        "bootstrap_samples": config.bootstrap_samples,
        "bootstrap_seed": config.bootstrap_seed,
    }


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def recompute_summary(
    per_request: Path,
    config: BenchmarkConfig | None = None,
    manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Recompute a summary from persisted rows and optionally verify manifest identity."""

    records = _load_jsonl(per_request)
    if config is None:
        raw_manifest = manifest
        if raw_manifest is None:
            manifest_path = per_request.parent / "manifest.json"
            raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        selected_ids = set(raw_manifest["selected_cell_ids"])
        selected = tuple(cell for cell in cells() if cell.cell_id in selected_ids)
        config = BenchmarkConfig(
            output=per_request.parent,
            warmups=int(raw_manifest["warmups"]),
            repetitions=int(raw_manifest["repetitions"]),
            seed=int(raw_manifest["seed"]),
            max_requests=int(raw_manifest["max_requests"]),
            max_input_tokens=int(raw_manifest["max_input_tokens"]),
            max_cost_usd=float(raw_manifest["max_cost_usd"]),
            bootstrap_samples=int(raw_manifest["bootstrap_samples"]),
            bootstrap_seed=int(raw_manifest["bootstrap_seed"]),
            base_url=str(raw_manifest["base_url"]),
            selected_cells=selected,
            expected_tokens_by_count={
                int(key): int(value)
                for key, value in raw_manifest["expected_tokens_by_count"].items()
            },
        )
    return summarize_records(records, config)


def _manifest(config: BenchmarkConfig, *, status: str, api_key_present: bool) -> dict[str, Any]:
    input_fingerprint = hashlib.sha256("|".join(SYNTHETIC_INPUTS).encode()).hexdigest()
    return {
        "schema_version": SCHEMA_VERSION,
        "runner_version": RUNNER_VERSION,
        "benchmark_kind": "openai-embedding-atomic-latency-matrix",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "status": status,
        "selected_cell_ids": [cell.cell_id for cell in config.selected_cells],
        "selected_aliases": [cell.alias for cell in config.selected_cells],
        "input_counts": list(INPUT_COUNTS),
        "client_modes": list(CLIENT_MODES),
        "warmups": config.warmups,
        "repetitions": config.repetitions,
        "seed": config.seed,
        "condition_order": "seeded shuffle, forward/reverse counterbalanced per repetition",
        "concurrency": config.concurrency,
        "max_retries": config.max_retries,
        "max_requests": config.max_requests,
        "max_input_tokens": config.max_input_tokens,
        "max_cost_usd": config.max_cost_usd,
        "expected_tokens_by_count": {
            str(key): value for key, value in config.expected_tokens_by_count.items()
        },
        "bootstrap_samples": config.bootstrap_samples,
        "bootstrap_seed": config.bootstrap_seed,
        "base_url": _validate_base_url(config.base_url),
        "input_set_sha256": input_fingerprint,
        "synthetic_input": True,
        "input_text_persisted": False,
        "request_bodies_persisted": False,
        "response_bodies_persisted": False,
        "credentials_persisted": False,
        "api_key_supplied": api_key_present,
        "stage_timing_schema": list(STAGE_NAMES),
    }


def run_benchmark(
    config: BenchmarkConfig,
    *,
    transport: httpx.BaseTransport | None = None,
    api_key: str | None = None,
    env: Mapping[str, str] | None = None,
) -> Path:
    """Execute the matrix and write manifest, JSONL rows, and recomputed summary."""

    output = config.output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output}")
    _validate_run_budget(config)
    key = _api_key(env, api_key)
    output.mkdir(parents=True, exist_ok=False)
    manifest_path = output / "manifest.json"
    rows_path = output / "per_request.jsonl"
    summary_path = output / "summary.json"
    manifest_path.write_text(
        json.dumps(
            _manifest(config, status="running", api_key_present=bool(key)),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    rows: list[dict[str, Any]] = []
    sequence = 0
    persistent_clients: dict[str, httpx.Client] = {}
    try:
        for cell in config.selected_cells:
            for warmup_index in range(1, config.warmups + 1):
                for order_index, condition in enumerate(
                    build_schedule(cell, seed=config.seed, repetition=warmup_index), 1
                ):
                    sequence += 1
                    client = None
                    if condition.client_mode == "persistent":
                        client = persistent_clients.get(condition.condition_id)
                        if client is None:
                            client = _client(config, key, transport)
                            persistent_clients[condition.condition_id] = client
                    row = _run_condition(
                        config,
                        condition,
                        client=client,
                        transport=transport,
                        key=key,
                        phase="warmup",
                        repetition=warmup_index,
                        order_index=order_index,
                        sequence=sequence,
                    )
                    rows.append(row)
                    if row["error"] is not None:
                        raise BenchmarkValidationError("warmup response failed validation")
            for repetition in range(1, config.repetitions + 1):
                for order_index, condition in enumerate(
                    build_schedule(cell, seed=config.seed, repetition=repetition), 1
                ):
                    sequence += 1
                    client = None
                    if condition.client_mode == "persistent":
                        client = persistent_clients.get(condition.condition_id)
                        if client is None:
                            client = _client(config, key, transport)
                            persistent_clients[condition.condition_id] = client
                    row = _run_condition(
                        config,
                        condition,
                        client=client,
                        transport=transport,
                        key=key,
                        phase="scored",
                        repetition=repetition,
                        order_index=order_index,
                        sequence=sequence,
                    )
                    rows.append(row)
                    if row["error"] is not None:
                        raise BenchmarkValidationError("scored response failed validation")
        with rows_path.open("x", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        summary = summarize_records(rows, config)
        summary_path.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        completed = _manifest(config, status="completed", api_key_present=bool(key))
        completed["observations"] = len([row for row in rows if row["scored"]])
        completed["attempts"] = sum(1 + int(row["retries"]) for row in rows)
        completed["input_tokens_accounted"] = sum(
            int(row["total_tokens"] or 0) for row in rows
        )
        completed["summary_sha256"] = hashlib.sha256(summary_path.read_bytes()).hexdigest()
        manifest_path.write_text(
            json.dumps(completed, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except Exception:
        # Preserve a privacy-safe failed manifest; no exception message is persisted.
        if rows and not rows_path.exists():
            with rows_path.open("x", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, sort_keys=True) + "\n")
        failed = _manifest(config, status="failed", api_key_present=bool(key))
        failed["rows_written"] = len(rows)
        failed["failure_type"] = "BenchmarkExecutionError"
        manifest_path.write_text(
            json.dumps(failed, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        raise
    finally:
        for client in persistent_clients.values():
            client.close()
    return output


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--base-url", default=os.environ.get("RAGZ_LITELLM_BASE_URL", DEFAULT_BASE_URL)
    )
    parser.add_argument("--warmups", type=int, default=DEFAULT_WARMUPS)
    parser.add_argument("--repetitions", type=int, default=DEFAULT_REPETITIONS)
    parser.add_argument("--seed", type=int, default=DEFAULT_BOOTSTRAP_SEED)
    parser.add_argument("--max-retries", type=int, default=0)
    parser.add_argument("--max-requests", type=int, default=DEFAULT_MAX_REQUESTS)
    parser.add_argument("--max-input-tokens", type=int, default=DEFAULT_MAX_INPUT_TOKENS)
    parser.add_argument("--max-cost-usd", type=float, default=DEFAULT_MAX_COST_USD)
    parser.add_argument("--bootstrap-samples", type=int, default=DEFAULT_BOOTSTRAP_SAMPLES)
    parser.add_argument("--bootstrap-seed", type=int, default=DEFAULT_BOOTSTRAP_SEED)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument(
        "--cells", nargs="*", help="optional canonical cell IDs; defaults to all ten"
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    available = {cell.cell_id: cell for cell in cells()}
    selected = (
        tuple(available[cell_id] for cell_id in args.cells)
        if args.cells
        else tuple(available.values())
    )
    if args.cells and len(selected) != len(set(args.cells)):
        raise InvalidEmbeddingCellError("duplicate --cells entry")
    config = BenchmarkConfig(
        output=args.output,
        warmups=args.warmups,
        repetitions=args.repetitions,
        seed=args.seed,
        concurrency=args.concurrency,
        max_retries=args.max_retries,
        max_requests=args.max_requests,
        max_input_tokens=args.max_input_tokens,
        max_cost_usd=args.max_cost_usd,
        bootstrap_samples=args.bootstrap_samples,
        bootstrap_seed=args.bootstrap_seed,
        base_url=args.base_url,
        selected_cells=selected,
    )
    result = run_benchmark(config)
    print(json.dumps({"output": str(result), "status": "completed"}, sort_keys=True))


if __name__ == "__main__":
    main()
