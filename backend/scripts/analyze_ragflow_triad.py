#!/usr/bin/env python3
# ruff: noqa: E501
"""Export a privacy-safe analysis of a completed private RAGFlow QA run.

The input artifacts are deliberately private: retrieval rows contain the
question and retrieved text, while QA rows contain prompts, answers, and
judge explanations.  This module reads those fields only to validate the run
and emits a new artifact tree containing identifiers, numeric observations,
and error codes.  It never copies source text or user-facing language.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

EXPECTED_QUERY_IDS = tuple(f"q{index:03d}" for index in range(1, 71))
EXPECTED_TOTAL = 70
EXPECTED_ANSWERABLE = 60
EXPECTED_OFF_CORPUS = 10
EXPECTED_GENERATION_CALLS = 70
EXPECTED_JUDGE_CALLS = 70
EXPECTED_DOCUMENTS = 22
EXPECTED_CHUNKS = 415
EXPECTED_EMBEDDING_ALIAS = "ragz-openai-text-embedding-3-large-d1024"
EXPECTED_RAGFLOW_COMMIT = "ec9c08d809f63ba2815090182fa225899d2437d5"
EXPECTED_RAGFLOW_IMAGE = "sha256:e9fe71c5ff14762eeb8e251b3b8ed37c02a99ae2bad3d7b11467260ced79578b"
EXPECTED_PROXY_FINGERPRINT = "e5a2913bf2fe061ba9811d8c102b740230c33ee549cc34e507aa03639200eb31"
EXPECTED_DOCUMENTS_SHA256 = "a7e6f35fda062cf04ab1435ffac269486f3920a6abe520f0a384673f64e9d335"
EXPECTED_QUERIES_SHA256 = "e743da70e48aab4392744dec18330c83da232bd883ce2c0ea5a1bff34c169c57"
EXPECTED_QRELS_SHA256 = "1a7234837da6f2578421e9d0130ef21900ac61ca24a47c91e0c6edb3fc8f248d"

GENERATION_MODEL = "gpt-5.6-luna"
JUDGE_MODEL = "gpt-5.4-mini"
LUNA_INPUT_PRICE = Decimal("0.20")
LUNA_CACHED_INPUT_PRICE = Decimal("0.02")
LUNA_OUTPUT_PRICE = Decimal("1.20")
JUDGE_INPUT_PRICE = Decimal("0.75")
JUDGE_CACHED_INPUT_PRICE = Decimal("0.075")
JUDGE_OUTPUT_PRICE = Decimal("4.50")

_BANNED_KEYS = frozenset(
    {
        "query",
        "question",
        "prompt",
        "answer",
        "reference",
        "reference_answer",
        "context",
        "content",
        "text",
        "source_text",
        "response",
        "response_body",
        "explanation",
        "auth",
        "authorization",
        "api_key",
        "secret",
        "dataset_id",
    }
)


class AnalyzerError(ValueError):
    """Raised when a private input does not satisfy the completed-run contract."""


class OutputExistsError(FileExistsError):
    """Raised before any existing output path is modified."""


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AnalyzerError(f"unable to read JSON artifact: {path.name}") from exc


def _jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise AnalyzerError(f"unable to read JSONL artifact: {path.name}") from exc
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AnalyzerError(f"invalid JSONL row {path.name}:{line_number}") from exc
        if not isinstance(value, dict):
            raise AnalyzerError(f"JSONL row {path.name}:{line_number} is not an object")
        rows.append(value)
    return rows


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise AnalyzerError(f"unable to hash artifact: {path.name}") from exc
    return digest.hexdigest()


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AnalyzerError(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise AnalyzerError(f"{label} must be finite")
    return number


def _token_count(value: object, label: str) -> int:
    number = _finite(value, label)
    if number < 0 or not number.is_integer():
        raise AnalyzerError(f"{label} must be a non-negative integer")
    return int(number)


def _numeric_map(value: object, label: str) -> dict[str, float]:
    if not isinstance(value, Mapping):
        raise AnalyzerError(f"{label} must be an object")
    result: dict[str, float] = {}
    for key, raw in value.items():
        if not isinstance(key, str):
            continue
        if raw is None:
            continue
        if isinstance(raw, bool):
            result[key] = 1.0 if raw else 0.0
        elif isinstance(raw, (int, float)):
            result[key] = _finite(raw, f"{label}.{key}")
    return result


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AnalyzerError(f"{label} must be an object")
    return value


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AnalyzerError(f"{label} must be a non-empty string")
    return value.strip()


def _percentile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    low = int(position)
    high = min(len(ordered) - 1, low + 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _series(values: Sequence[float]) -> dict[str, float | int | None]:
    numbers = [float(value) for value in values]
    return {
        "observations": len(numbers),
        "mean": math.fsum(numbers) / len(numbers) if numbers else None,
        "p50": _percentile(numbers, 0.50),
        "p95": _percentile(numbers, 0.95),
        "p99": _percentile(numbers, 0.99),
    }


def _mean_map(
    rows: Sequence[Mapping[str, float]], *, keys: Sequence[str] | None = None
) -> dict[str, dict[str, float | int | None]]:
    names = list(keys) if keys is not None else sorted({name for row in rows for name in row})
    return {name: _series([row[name] for row in rows if name in row]) for name in names}


def _confusion(
    rows: Sequence[Mapping[str, Any]], expected_key: str, predicted_key: str
) -> dict[str, float | int]:
    tp = fp = fn = tn = 0
    for row in rows:
        expected = bool(row.get(expected_key, 0))
        predicted = bool(row.get(predicted_key, 0))
        if expected and predicted:
            tp += 1
        elif not expected and predicted:
            fp += 1
        elif expected:
            fn += 1
        else:
            tn += 1
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    total = tp + fp + fn + tn
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "accuracy": (tp + tn) / total if total else 0.0,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _validate_ids(rows: Sequence[Mapping[str, Any]], label: str) -> dict[str, Mapping[str, Any]]:
    if len(rows) != EXPECTED_TOTAL:
        raise AnalyzerError(f"{label} must contain exactly {EXPECTED_TOTAL} rows")
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        query_id = _required_text(row.get("query_id"), f"{label}.query_id")
        if query_id in result:
            raise AnalyzerError(f"duplicate query_id: {query_id}")
        result[query_id] = row
    if set(result) != set(EXPECTED_QUERY_IDS):
        raise AnalyzerError(f"{label} query IDs must be q001 through q070")
    return dict(sorted(result.items()))


def _load_qrels(path: Path) -> dict[str, set[str]]:
    rows = _jsonl(path)
    qrels: dict[str, set[str]] = {}
    for index, row in enumerate(rows, 1):
        query_id = _required_text(row.get("query_id"), f"qrels[{index}].query_id")
        if query_id not in EXPECTED_QUERY_IDS:
            raise AnalyzerError(f"qrels[{index}] has an unknown query_id")
        doc_id = _required_text(row.get("doc_id", row.get("document_id")), f"qrels[{index}].doc_id")
        relevance = row.get("relevance", 1)
        if isinstance(relevance, bool) or not isinstance(relevance, int):
            raise AnalyzerError(f"qrels[{index}].relevance must be an integer")
        if relevance > 0:
            qrels.setdefault(query_id, set()).add(doc_id)
    if set(qrels) != set(EXPECTED_QUERY_IDS[:EXPECTED_ANSWERABLE]):
        raise AnalyzerError("qrels must have positive relevance for exactly q001-q060")
    if any(not docs for docs in qrels.values()):
        raise AnalyzerError("answerable qrels must contain a positive document")
    return qrels


def _ranking_metrics(required: set[str], ranked: Sequence[str]) -> dict[str, float | bool]:
    top = list(ranked[:5])
    if not required:
        return {"recall_at_5": 0.0, "mrr_at_5": 0.0, "ndcg_at_5": 0.0, "required_doc_hit": False}
    hits = required.intersection(top)
    reciprocal = next(
        (1.0 / index for index, doc_id in enumerate(top, 1) if doc_id in required), 0.0
    )
    dcg = sum(1.0 / math.log2(index + 2) for index, doc_id in enumerate(top) if doc_id in required)
    ideal_count = min(5, len(required))
    ideal = sum(1.0 / math.log2(index + 2) for index in range(ideal_count))
    return {
        "recall_at_5": len(hits) / len(required),
        "mrr_at_5": reciprocal,
        "ndcg_at_5": dcg / ideal if ideal else 0.0,
        "required_doc_hit": bool(hits),
    }


def _errors(row: Mapping[str, Any], label: str) -> list[str]:
    raw = row.get("error_codes", row.get("errors", []))
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise AnalyzerError(f"{label}.errors must be a list")
    result: list[str] = []
    for code in raw:
        candidate = str(code)
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", candidate):
            raise AnalyzerError(f"{label}.errors contains a non-code value")
        result.append(candidate)
    return result


def _cost(ledger: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    totals: dict[str, dict[str, Any]] = {
        "generation": {
            "calls": 0,
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": Decimal("0"),
        },
        "judge": {
            "calls": 0,
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": Decimal("0"),
        },
    }
    for index, entry in enumerate(ledger, 1):
        endpoint = str(entry.get("endpoint", ""))
        if endpoint == "responses-generation":
            bucket, input_rate, cached_rate, output_rate = (
                totals["generation"],
                LUNA_INPUT_PRICE,
                LUNA_CACHED_INPUT_PRICE,
                LUNA_OUTPUT_PRICE,
            )
        elif endpoint == "responses-judge":
            bucket, input_rate, cached_rate, output_rate = (
                totals["judge"],
                JUDGE_INPUT_PRICE,
                JUDGE_CACHED_INPUT_PRICE,
                JUDGE_OUTPUT_PRICE,
            )
        else:
            raise AnalyzerError(f"cost ledger entry {index} has unknown endpoint")
        usage = _mapping(entry.get("usage"), f"cost ledger entry {index}.usage")
        input_tokens = _token_count(usage.get("input_tokens", 0), "input_tokens")
        cached_tokens = _token_count(usage.get("cached_input_tokens", 0), "cached_input_tokens")
        output_tokens = _token_count(usage.get("output_tokens", 0), "output_tokens")
        if cached_tokens > input_tokens:
            raise AnalyzerError(f"cost ledger entry {index} has invalid usage")
        amount = (
            Decimal(input_tokens - cached_tokens) * input_rate
            + Decimal(cached_tokens) * cached_rate
            + Decimal(output_tokens) * output_rate
        ) / Decimal(1_000_000)
        bucket["calls"] += 1
        bucket["input_tokens"] += input_tokens
        bucket["cached_input_tokens"] += cached_tokens
        bucket["output_tokens"] += output_tokens
        bucket["cost_usd"] += amount
    if totals["generation"]["calls"] != EXPECTED_GENERATION_CALLS:
        raise AnalyzerError("cost ledger must contain exactly 70 generation calls")
    if totals["judge"]["calls"] != EXPECTED_JUDGE_CALLS:
        raise AnalyzerError("cost ledger must contain exactly 70 judge calls")
    by_endpoint: dict[str, Any] = {}
    total = Decimal("0")
    for name, bucket in totals.items():
        total += bucket["cost_usd"]
        by_endpoint[name] = {
            key: (str(value.quantize(Decimal("0.00000001"))) if key == "cost_usd" else value)
            for key, value in bucket.items()
        }
    return {
        "usage_derived_total_usd": str(total.quantize(Decimal("0.00000001"))),
        "by_endpoint": by_endpoint,
        "rates_usd_per_million": {
            "gpt-5.6-luna": {
                "input": str(LUNA_INPUT_PRICE),
                "cached_input": str(LUNA_CACHED_INPUT_PRICE),
                "output": str(LUNA_OUTPUT_PRICE),
            },
            "gpt-5.4-mini": {
                "input": str(JUDGE_INPUT_PRICE),
                "cached_input": str(JUDGE_CACHED_INPUT_PRICE),
                "output": str(JUDGE_OUTPUT_PRICE),
            },
        },
        "basis": "usage_only_endpoint_model_specific_pinned_rates",
    }


def _validate_usage_matches_ledger(
    qa_rows: Mapping[str, Mapping[str, Any]], ledger: Sequence[Mapping[str, Any]]
) -> None:
    qa_totals = {
        "responses-generation": {
            "calls": 0,
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
        },
        "responses-judge": {
            "calls": 0,
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
        },
    }
    for query_id, row in qa_rows.items():
        usage = _mapping(row.get("usage"), f"{query_id}.usage")
        for endpoint_name, endpoint in (
            ("generation", "responses-generation"),
            ("judge", "responses-judge"),
        ):
            values = _mapping(usage.get(endpoint_name), f"{query_id}.{endpoint_name}.usage")
            bucket = qa_totals[endpoint]
            bucket["calls"] += 1
            for name in ("input_tokens", "cached_input_tokens", "output_tokens"):
                bucket[name] += _token_count(
                    values.get(name, 0), f"{query_id}.{endpoint_name}.{name}"
                )
    ledger_totals = {
        endpoint: {"calls": 0, "input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
        for endpoint in qa_totals
    }
    for index, entry in enumerate(ledger, 1):
        endpoint = str(entry.get("endpoint"))
        if endpoint not in ledger_totals:
            raise AnalyzerError(f"cost ledger entry {index} has unknown endpoint")
        values = _mapping(entry.get("usage"), f"cost ledger entry {index}.usage")
        bucket = ledger_totals[endpoint]
        bucket["calls"] += 1
        for name in ("input_tokens", "cached_input_tokens", "output_tokens"):
            bucket[name] += _token_count(values.get(name, 0), f"ledger {endpoint}.{name}")
    if qa_totals != ledger_totals:
        raise AnalyzerError("per-query usage totals do not match the provider cost ledger")


def _validate_r3_attestations(
    runtime_stop: Mapping[str, Any],
    runtime_manifest_hash: str,
    public_manifest_hash: str,
    public_summary_hash: str,
    public_rows_hash: str,
    embedding_preflight: Mapping[str, Any],
    embedding_preflight_hash: str,
    vector_attestation: Mapping[str, Any],
    vector_attestation_hash: str,
) -> None:
    source_runtime = _mapping(
        runtime_stop.get("source_runtime_manifest"), "runtime stop.source_runtime_manifest"
    )
    if source_runtime.get("sha256") != runtime_manifest_hash:
        raise AnalyzerError("runtime stop attestation does not bind the runtime manifest")
    scored = _mapping(runtime_stop.get("scored_artifact"), "runtime stop.scored_artifact")
    if (
        scored.get("manifest_sha256") != public_manifest_hash
        or scored.get("summary_sha256") != public_summary_hash
        or scored.get("per_query_sha256") != public_rows_hash
    ):
        raise AnalyzerError("runtime stop attestation does not bind public retrieval artifacts")
    source = _mapping(runtime_stop.get("source"), "runtime stop.source")
    if (
        source.get("ragflow_version") != "v0.27.0"
        or source.get("commit") != EXPECTED_RAGFLOW_COMMIT
        or source.get("app_image_digest") != EXPECTED_RAGFLOW_IMAGE
    ):
        raise AnalyzerError("runtime stop source is not r6-bound")
    window = _mapping(runtime_stop.get("execution_window_utc"), "runtime stop.execution_window_utc")
    window_values: list[object] = [
        window.get(name)
        for name in (
            "dependencies_started_at",
            "app_started_at",
            "scored_artifact_created_at",
            "last_container_stopped_at",
            "verified_stopped_at",
        )
    ]
    if any(not isinstance(value, str) for value in window_values):
        raise AnalyzerError("runtime execution window is missing or out of order")
    window_text = [value for value in window_values if isinstance(value, str)]
    if window_text != sorted(window_text):
        raise AnalyzerError("runtime execution window is missing or out of order")
    containers = runtime_stop.get("containers")
    if not isinstance(containers, list) or len(containers) != 5:
        raise AnalyzerError("runtime stop attestation must contain exactly five containers")
    for index, container in enumerate(containers, 1):
        row = _mapping(container, f"runtime stop.containers[{index}]")
        if (
            row.get("status") != "exited"
            or row.get("oom_killed") is not False
            or row.get("restart_count") != 0
        ):
            raise AnalyzerError(
                "runtime stop container evidence has OOM, restart, or running state"
            )
    post_stop = _mapping(runtime_stop.get("post_stop"), "runtime stop.post_stop")
    if (
        post_stop.get("containers_left_running") != 0
        or post_stop.get("stop_scope") != "compose_project_only"
    ):
        raise AnalyzerError("runtime stop evidence does not prove zero running containers")

    cells = embedding_preflight.get("cells")
    if not isinstance(cells, list):
        raise AnalyzerError("embedding preflight cells are missing")
    matching = [
        cell
        for cell in cells
        if isinstance(cell, Mapping) and cell.get("alias") == EXPECTED_EMBEDDING_ALIAS
    ]
    if len(matching) != 1:
        raise AnalyzerError("embedding preflight lacks the unique large d1024 cell")
    cell = matching[0]
    if (
        cell.get("model") != "text-embedding-3-large"
        or cell.get("dimension") != 1024
        or cell.get("actual_dimension") != 1024
        or cell.get("probe_status") != "passed"
        or cell.get("embedding_proxy_fingerprint_sha256") != EXPECTED_PROXY_FINGERPRINT
    ):
        raise AnalyzerError("embedding preflight cell is not the passed r6 d1024 contract")
    if (
        embedding_preflight.get("status") != "completed"
        or embedding_preflight.get("embedding_proxy_fingerprint_sha256")
        != EXPECTED_PROXY_FINGERPRINT
    ):
        raise AnalyzerError("embedding preflight manifest is incomplete or has the wrong proxy")

    contract = _mapping(
        vector_attestation.get("embedding_contract"), "dataset vector.embedding_contract"
    )
    if (
        contract.get("litellm_alias") != EXPECTED_EMBEDDING_ALIAS
        or contract.get("underlying_model") != "text-embedding-3-large"
        or contract.get("expected_dimension") != 1024
        or contract.get("observed_infinity_vector_size") != 1024
        or contract.get("proxy_fingerprint_sha256") != EXPECTED_PROXY_FINGERPRINT
    ):
        raise AnalyzerError("dataset-vector embedding contract is not r6-bound")
    preflight_ref = _mapping(
        vector_attestation.get("embedding_preflight"), "dataset vector.embedding_preflight"
    )
    if (
        preflight_ref.get("sha256") != embedding_preflight_hash
        or preflight_ref.get("actual_dimension") != 1024
        or preflight_ref.get("requested_dimension") != 1024
        or preflight_ref.get("probe_status") != "passed"
    ):
        raise AnalyzerError("dataset-vector attestation does not bind the embedding preflight")
    logs = _mapping(
        vector_attestation.get("ragflow_log_evidence"), "dataset vector.ragflow_log_evidence"
    )
    if (
        logs.get("embedding_alias_event_count") != 22
        or not isinstance(logs.get("vector_size_1024_event_count"), int)
        or logs.get("vector_size_1024_event_count", 0) <= 0
        or logs.get("content_persisted") is not False
    ):
        raise AnalyzerError("dataset-vector log evidence is incomplete")
    final = _mapping(
        vector_attestation.get("final_dataset_preflight"), "dataset vector.final_dataset_preflight"
    )
    if (
        final.get("documents_expected") != 22
        or final.get("documents_mapped") != 22
        or final.get("documents_done") != 22
        or final.get("chunks") != 415
        or final.get("document_failure_messages") != 0
        or final.get("retrieval_summary_sha256") != public_summary_hash
    ):
        raise AnalyzerError("dataset-vector final preflight is not the completed 22/415 contract")
    if not vector_attestation_hash:
        raise AnalyzerError("dataset-vector attestation hash is missing")


def _validate_measurement_protocol(
    attestation: Mapping[str, Any],
    retrieval_jsonl_hash: str,
    qa_manifest: Mapping[str, Any],
    r1_manifest_hash: str,
    r1_summary_hash: str,
    r1_rows_hash: str,
    r2_manifest_hash: str,
    r2_summary_hash: str,
    r2_rows_hash: str,
    r3_manifest_hash: str,
    r3_summary_hash: str,
    r3_rows_hash: str,
) -> None:
    if (
        attestation.get("effective_prior_passes_per_query_before_scored_r3") != 3
        or attestation.get("cache_reset_between_passes") is not False
    ):
        raise AnalyzerError(
            "measurement protocol must record three prior passes and no cache reset"
        )
    sequence = attestation.get("sequence")
    if not isinstance(sequence, list) or [
        item.get("order") for item in sequence if isinstance(item, Mapping)
    ] != [1, 2, 3, 4]:
        raise AnalyzerError("measurement protocol sequence must contain orders 1 through 4")
    first = _mapping(sequence[0], "measurement sequence[0]")
    if (
        first.get("role") != "private_qa_context_capture_and_warmup"
        or first.get("private_retrieval_sha256") != retrieval_jsonl_hash
        or first.get("qa_retrieval_input_sha256") != qa_manifest.get("retrieval_sha256")
    ):
        raise AnalyzerError(
            "measurement protocol private context-capture hashes do not match inputs"
        )
    expected = [
        (sequence[1], r1_manifest_hash, r1_summary_hash, r1_rows_hash),
        (sequence[2], r2_manifest_hash, r2_summary_hash, r2_rows_hash),
        (sequence[3], r3_manifest_hash, r3_summary_hash, r3_rows_hash),
    ]
    for item, manifest_hash, summary_hash, rows_hash in expected:
        row = _mapping(item, "measurement public sequence")
        if row.get("role") == "public_scored_retrieval":
            if (
                row.get("manifest_sha256") != manifest_hash
                or row.get("summary_sha256") != summary_hash
                or row.get("per_query_sha256") != rows_hash
            ):
                raise AnalyzerError("measurement protocol scored artifact hashes do not match")
        elif row.get("role") == "public_warmup_only":
            if (
                row.get("summary_sha256") != summary_hash
                or row.get("per_query_sha256") != rows_hash
            ):
                raise AnalyzerError("measurement protocol warmup artifact hashes do not match")
        else:
            raise AnalyzerError("measurement protocol public sequence role is invalid")


def _provenance(
    value: Mapping[str, Any] | None,
    public_manifest: Mapping[str, Any],
    public_manifest_sha256: str,
    runtime_manifest: Mapping[str, Any],
    runtime_manifest_sha256: str,
) -> dict[str, Any]:
    supplied = dict(value or {})
    required = (
        "generation_model",
        "judge_model",
        "embedding_alias",
        "ragflow_version",
        "ragflow_commit",
        "ragflow_image",
        "proxy_fingerprint_sha256",
        "runtime_manifest_sha256",
        "retrieval_manifest_sha256",
        "documents",
        "chunks",
    )
    missing = [key for key in required if supplied.get(key) in (None, "")]
    if missing:
        raise AnalyzerError(f"provenance is missing required fields: {', '.join(missing)}")
    public_provenance = _mapping(public_manifest.get("provenance"), "public manifest.provenance")
    result: dict[str, Any] = {
        "generation_model": supplied["generation_model"],
        "judge_model": supplied["judge_model"],
        "embedding_alias": supplied["embedding_alias"],
        "ragflow_version": supplied["ragflow_version"],
        "documents": int(supplied["documents"]),
        "chunks": int(supplied["chunks"]),
        "ingestion_concurrency_race": supplied.get("ingestion_concurrency_race", "observed"),
        "intentional_app_recovery": bool(supplied.get("intentional_app_recovery", True)),
        "ragflow_commit": supplied["ragflow_commit"],
        "ragflow_image": supplied["ragflow_image"],
        "proxy_fingerprint_sha256": supplied["proxy_fingerprint_sha256"],
        "runtime_manifest_sha256": supplied["runtime_manifest_sha256"],
        "retrieval_manifest_sha256": supplied["retrieval_manifest_sha256"],
    }
    if result["generation_model"] != GENERATION_MODEL or result["judge_model"] != JUDGE_MODEL:
        raise AnalyzerError("provenance model identities do not match the completed run")
    if (
        result["embedding_alias"] != EXPECTED_EMBEDDING_ALIAS
        or result["ragflow_version"] != "v0.27.0"
    ):
        raise AnalyzerError("provenance embedding alias or RAGFlow version is not r6-bound")
    if (
        result["ragflow_commit"] != EXPECTED_RAGFLOW_COMMIT
        or result["ragflow_image"] != EXPECTED_RAGFLOW_IMAGE
        or result["proxy_fingerprint_sha256"] != EXPECTED_PROXY_FINGERPRINT
    ):
        raise AnalyzerError("provenance commit, image, or proxy is not r6-bound")
    if result["runtime_manifest_sha256"] != runtime_manifest_sha256:
        raise AnalyzerError("runtime manifest SHA-256 does not match runtime manifest input")
    if result["retrieval_manifest_sha256"] != public_manifest_sha256:
        raise AnalyzerError("retrieval manifest SHA-256 does not match public retrieval manifest")
    for key, expected in (
        ("expected_image_digest", EXPECTED_RAGFLOW_IMAGE),
        ("image_digest", EXPECTED_RAGFLOW_IMAGE),
        ("proxy_fingerprint_sha256", EXPECTED_PROXY_FINGERPRINT),
    ):
        if public_provenance.get(key) != expected:
            raise AnalyzerError(f"public manifest provenance.{key} is not r6-bound")
    if (
        runtime_manifest.get("version") != "v0.27.0"
        or runtime_manifest.get("commit") != EXPECTED_RAGFLOW_COMMIT
    ):
        raise AnalyzerError("runtime manifest version or commit is not r6-bound")
    if runtime_manifest.get("memory_limit_bytes") != 5_000_000_000:
        raise AnalyzerError("runtime manifest does not record the 5GB budget")
    if runtime_manifest.get("stack_left_running") is not False:
        raise AnalyzerError("runtime manifest stack_left_running must be false")
    image_provenance = runtime_manifest.get("image_provenance")
    if not isinstance(image_provenance, list) or not any(
        isinstance(item, Mapping)
        and item.get("role") == "app"
        and item.get("digest") == EXPECTED_RAGFLOW_IMAGE
        for item in image_provenance
    ):
        raise AnalyzerError("runtime manifest app image digest is not r6-bound")
    post_stop = _mapping(
        runtime_manifest.get("post_smoke_stop"), "runtime manifest.post_smoke_stop"
    )
    if (
        post_stop.get("containers_left_running") != 0
        or post_stop.get("stop_scope") != "compose_project_only"
    ):
        raise AnalyzerError("runtime manifest did not record a clean project-scoped stop")
    if result["documents"] != EXPECTED_DOCUMENTS or result["chunks"] != EXPECTED_CHUNKS:
        raise AnalyzerError("provenance corpus denominator must be 22 documents and 415 chunks")
    dataset_hashes = _mapping(
        public_manifest.get("dataset_sha256"), "public manifest.dataset_sha256"
    )
    if (
        dataset_hashes.get("documents") != EXPECTED_DOCUMENTS_SHA256
        or dataset_hashes.get("queries") != EXPECTED_QUERIES_SHA256
        or not isinstance(dataset_hashes.get("qrels"), str)
    ):
        raise AnalyzerError("public manifest dataset hashes are not r6-bound")
    return result


def analyze(
    retrieval_jsonl: Path,
    qa_dir: Path,
    output_dir: Path,
    *,
    public_retrieval_dir: Path,
    qrels_path: Path,
    runtime_manifest_path: Path,
    runtime_stop_attestation_path: Path,
    embedding_preflight_manifest_path: Path,
    dataset_vector_attestation_path: Path,
    measurement_protocol_attestation_path: Path,
    public_retrieval_r1_dir: Path,
    public_retrieval_r2_dir: Path,
    provenance: Mapping[str, Any],
) -> Path:
    """Validate, analyze, and export one completed run without overwriting output."""

    if output_dir.exists():
        raise OutputExistsError(f"refusing to overwrite output: {output_dir}")
    retrieval = _validate_ids(_jsonl(retrieval_jsonl), "retrieval")
    public_manifest_path = public_retrieval_dir / "manifest.json"
    public_summary_path = public_retrieval_dir / "summary.json"
    public_rows_path = public_retrieval_dir / "per_query.jsonl"
    public_manifest = _mapping(_json(public_manifest_path), "public retrieval manifest")
    public_summary = _mapping(_json(public_summary_path), "public retrieval summary")
    runtime_manifest = _mapping(_json(runtime_manifest_path), "runtime manifest")
    runtime_stop = _mapping(_json(runtime_stop_attestation_path), "runtime stop attestation")
    embedding_preflight = _mapping(
        _json(embedding_preflight_manifest_path), "embedding preflight manifest"
    )
    vector_attestation = _mapping(
        _json(dataset_vector_attestation_path), "dataset-vector attestation"
    )
    public = _validate_ids(_jsonl(public_rows_path), "public retrieval")
    qrels = _load_qrels(qrels_path)
    qrels_hash = _sha256(qrels_path)
    if public_manifest.get("status") != "completed" or public_summary.get("status") != "completed":
        raise AnalyzerError("authoritative public retrieval artifact is not completed")
    public_manifest_hash = _sha256(public_manifest_path)
    runtime_manifest_hash = _sha256(runtime_manifest_path)
    runtime_stop_hash = _sha256(runtime_stop_attestation_path)
    embedding_preflight_hash = _sha256(embedding_preflight_manifest_path)
    vector_attestation_hash = _sha256(dataset_vector_attestation_path)
    measurement_protocol = _mapping(
        _json(measurement_protocol_attestation_path), "measurement protocol attestation"
    )
    measurement_protocol_hash = _sha256(measurement_protocol_attestation_path)
    _validate_r3_attestations(
        runtime_stop,
        runtime_manifest_hash,
        public_manifest_hash,
        _sha256(public_summary_path),
        _sha256(public_rows_path),
        embedding_preflight,
        embedding_preflight_hash,
        vector_attestation,
        vector_attestation_hash,
    )
    provenance_out = _provenance(
        provenance,
        public_manifest,
        public_manifest_hash,
        runtime_manifest,
        runtime_manifest_hash,
    )
    provenance_out["attestation_sha256"] = {
        "runtime_stop": runtime_stop_hash,
        "embedding_preflight": embedding_preflight_hash,
        "dataset_vector": vector_attestation_hash,
        "measurement_protocol": measurement_protocol_hash,
    }
    public_denominator = _mapping(public_manifest.get("denominator"), "public manifest.denominator")
    if dict(public_denominator) != {"total": 70, "answerable": 60, "off_corpus": 10, "errors": 0}:
        raise AnalyzerError("public retrieval denominator is not exactly 60/10 with zero errors")
    public_dataset_hashes = _mapping(
        public_manifest.get("dataset_sha256"), "public manifest.dataset_sha256"
    )
    if public_dataset_hashes.get("qrels") != qrels_hash:
        raise AnalyzerError("qrels SHA-256 does not match authoritative public retrieval manifest")
    qa_rows = _validate_ids(_jsonl(qa_dir / "per_query.jsonl"), "QA")
    qa_summary = _mapping(_json(qa_dir / "summary.json"), "QA summary")
    qa_manifest = _mapping(_json(qa_dir / "manifest.json"), "QA manifest")
    qa_models = _mapping(qa_manifest.get("models"), "QA manifest.models")
    if qa_models != {
        "embedding": EXPECTED_EMBEDDING_ALIAS,
        "generation": GENERATION_MODEL,
        "judge": JUDGE_MODEL,
    }:
        raise AnalyzerError("QA manifest model identities are not r6-bound")
    if qa_summary.get("status") not in (None, "completed") or qa_manifest.get("status") not in (
        None,
        "completed",
    ):
        raise AnalyzerError("upstream QA run is not completed")
    r1_hashes = [
        _sha256(public_retrieval_r1_dir / name)
        for name in ("manifest.json", "summary.json", "per_query.jsonl")
    ]
    r2_hashes = [
        _sha256(public_retrieval_r2_dir / name)
        for name in ("manifest.json", "summary.json", "per_query.jsonl")
    ]
    _validate_measurement_protocol(
        measurement_protocol,
        _sha256(retrieval_jsonl),
        qa_manifest,
        r1_hashes[0],
        r1_hashes[1],
        r1_hashes[2],
        r2_hashes[0],
        r2_hashes[1],
        r2_hashes[2],
        public_manifest_hash,
        _sha256(public_summary_path),
        _sha256(public_rows_path),
    )
    ledger = _jsonl(qa_dir / "cost_ledger.jsonl")
    if len(ledger) != EXPECTED_GENERATION_CALLS + EXPECTED_JUDGE_CALLS:
        raise AnalyzerError("cost ledger must contain exactly 140 provider calls")
    _validate_usage_matches_ledger(qa_rows, ledger)

    rows: list[dict[str, Any]] = []
    retrieval_errors = 0
    qa_errors = 0
    answerable_ids: list[str] = []
    for query_id in EXPECTED_QUERY_IDS:
        retrieval_row = retrieval[query_id]
        public_row = public[query_id]
        qa_row = qa_rows[query_id]
        answerable = query_id in qrels
        private_answerable = retrieval_row.get("answerable")
        if private_answerable is not None and private_answerable != answerable:
            raise AnalyzerError(f"{query_id} private retrieval answerable flag differs from qrels")
        metadata = _mapping(qa_row.get("metadata"), f"{query_id}.metadata")
        qa_answerable = metadata.get("answerable")
        if qa_answerable is not None and qa_answerable != answerable:
            raise AnalyzerError(f"{query_id} answerable flags differ")
        if answerable:
            answerable_ids.append(query_id)
        doc_ids_raw = public_row.get("ranked_doc_ids")
        scores_raw = public_row.get("ranked_scores")
        if not isinstance(doc_ids_raw, list) or not isinstance(scores_raw, list):
            raise AnalyzerError(f"{query_id} public ranking is malformed")
        if len(doc_ids_raw) != len(scores_raw):
            raise AnalyzerError(f"{query_id} public ranking IDs and scores differ in length")
        doc_ids = [_required_text(item, f"{query_id}.ranked_doc_ids") for item in doc_ids_raw]
        scores = [_finite(item, f"{query_id}.ranked_scores") for item in scores_raw]
        retrieval_metrics = _ranking_metrics(qrels[query_id], doc_ids) if answerable else {}
        retrieval_errors_for_row = _errors(retrieval_row, f"{query_id} retrieval")
        qa_errors_for_row = _errors(qa_row, f"{query_id} QA")
        retrieval_errors += bool(retrieval_errors_for_row)
        qa_errors += bool(qa_errors_for_row)
        judge_metrics = _numeric_map(qa_row.get("judge", {}), f"{query_id}.judge")
        deterministic_metrics = _numeric_map(
            qa_row.get("deterministic_metrics", {}), f"{query_id}.deterministic_metrics"
        )
        timings = _mapping(metadata.get("timings_ms"), f"{query_id}.timings_ms")
        generation = _finite(timings.get("generation_provider"), f"{query_id}.generation_provider")
        judge = _finite(timings.get("judge_provider"), f"{query_id}.judge_provider")
        postprocess = _finite(timings.get("postprocess", 0.0), f"{query_id}.postprocess")
        retrieval_latency = _finite(public_row.get("latency_ms"), f"{query_id}.latency_ms")
        timing_metrics = {
            "retrieval": retrieval_latency,
            "ragflow_retrieval": retrieval_latency,
            "generation_provider": generation,
            "judge_provider": judge,
            "postprocess": postprocess,
            "estimated_noncoincident_combined_total": retrieval_latency
            + generation
            + judge
            + postprocess,
            "estimated_noncoincident_user_facing_retrieval_plus_generation": retrieval_latency
            + generation,
        }
        usage = _mapping(qa_row.get("usage"), f"{query_id}.usage")
        usage_out: dict[str, dict[str, int]] = {}
        for endpoint in ("generation", "judge"):
            endpoint_usage = _mapping(usage.get(endpoint), f"{query_id}.{endpoint} usage")
            usage_out[endpoint] = {
                name: _token_count(endpoint_usage.get(name, 0), f"{query_id}.{endpoint}.{name}")
                for name in ("input_tokens", "cached_input_tokens", "output_tokens")
            }
        rows.append(
            {
                "query_id": query_id,
                "answerable": answerable,
                "ranked_doc_ids": doc_ids,
                "ranked_scores": scores,
                "retrieval_metrics": retrieval_metrics,
                "judge_metrics": judge_metrics,
                "deterministic_metrics": deterministic_metrics,
                "timings_ms": timing_metrics,
                "usage": usage_out,
                "error_codes": retrieval_errors_for_row + qa_errors_for_row,
            }
        )
    if len(answerable_ids) != EXPECTED_ANSWERABLE:
        raise AnalyzerError("completed run must contain exactly 60 answerable rows")
    if retrieval_errors or qa_errors:
        raise AnalyzerError("completed run must contain zero errors")

    answerable_rows = [row for row in rows if row["answerable"]]
    triad = _mean_map(
        [row["judge_metrics"] for row in answerable_rows],
        keys=("context_relevance", "groundedness", "answer_relevance"),
    )
    all_deterministic = [row["deterministic_metrics"] for row in rows]
    answer_abstention = _confusion(all_deterministic, "abstention_expected", "abstention_predicted")
    retrieval_abstention_rows = [
        {
            "expected": not row["answerable"],
            "predicted": not row["ranked_scores"] or max(row["ranked_scores"]) < 0.0,
        }
        for row in rows
    ]
    retrieval_abstention = _confusion(retrieval_abstention_rows, "expected", "predicted")
    citation_values = [
        row["deterministic_metrics"]["citation_validity"]
        for row in answerable_rows
        if "citation_validity" in row["deterministic_metrics"]
    ]
    retrieval_metric_rows = [row["retrieval_metrics"] for row in answerable_rows]
    latency_rows = [row["timings_ms"] for row in rows]
    latency = _mean_map(
        latency_rows,
        keys=(
            "retrieval",
            "ragflow_retrieval",
            "generation_provider",
            "judge_provider",
            "postprocess",
            "estimated_noncoincident_combined_total",
            "estimated_noncoincident_user_facing_retrieval_plus_generation",
        ),
    )
    input_hashes = {
        "retrieval_jsonl": _sha256(retrieval_jsonl),
        "public_retrieval_manifest": public_manifest_hash,
        "public_retrieval_summary": _sha256(public_summary_path),
        "public_retrieval_per_query": _sha256(public_rows_path),
        "public_r1_manifest": r1_hashes[0],
        "public_r1_summary": r1_hashes[1],
        "public_r1_per_query": r1_hashes[2],
        "public_r2_manifest": r2_hashes[0],
        "public_r2_summary": r2_hashes[1],
        "public_r2_per_query": r2_hashes[2],
        "qrels": qrels_hash,
        "runtime_manifest": runtime_manifest_hash,
        "runtime_stop_attestation": runtime_stop_hash,
        "embedding_preflight_manifest": embedding_preflight_hash,
        "dataset_vector_attestation": vector_attestation_hash,
        "analyzer": _sha256(Path(__file__).resolve()),
        "qa_per_query_jsonl": _sha256(qa_dir / "per_query.jsonl"),
        "qa_summary_json": _sha256(qa_dir / "summary.json"),
        "qa_manifest_json": _sha256(qa_dir / "manifest.json"),
        "qa_cost_ledger_jsonl": _sha256(qa_dir / "cost_ledger.jsonl"),
        "measurement_protocol_attestation": measurement_protocol_hash,
    }
    costs = _cost(ledger)
    reported_cost = _mapping(qa_summary.get("cost", {}), "QA summary.cost").get(
        "actual_settled_usd"
    )
    costs.update(
        {
            "upstream_reported_actual_usd": str(reported_cost)
            if reported_cost is not None
            else None,
            "upstream_cost_status": "invalid_mispriced",
            "upstream_cost_note": "Upstream settled total is retained only as a flagged value; this export recomputes answer-generation and judge usage cost.",
            "scope": "answer_generation_plus_judge_only",
            "excluded": "embedding_index_and_query_provider_usage_unavailable",
        }
    )
    summary: dict[str, Any] = {
        "schema_version": 1,
        "status": "completed",
        "denominator": {"total": 70, "answerable": 60, "off_corpus": 10, "errors": 0},
        "calls": {"generation": 70, "judge": 70},
        "rag_triad": triad,
        "answer_abstention": answer_abstention,
        "retrieval_threshold_abstention": retrieval_abstention,
        "citation_validity": _series(citation_values),
        "retrieval_metrics": _mean_map(retrieval_metric_rows),
        "latency_ms": latency,
        "latency_note": "estimated_noncoincident values are arithmetic composition of stage timings, not measured wall time",
        "retrieval_latency_source": "public_scored_r3_standalone",
        "qa_context_latency_source": "private_pass_1_context_capture_disclosed_separately",
        "cost": costs,
        "provenance": provenance_out,
        "sha256": input_hashes,
        "privacy": {
            "queries_context_answers_references_explanations_source_text_auth_and_dataset_ids": "excluded"
        },
    }
    try:
        output_dir.mkdir(parents=True)
        per_query_path = output_dir / "per_query.jsonl"
        summary_path = output_dir / "summary.json"
        manifest_path = output_dir / "manifest.json"
        _write_exclusive(per_query_path, rows, jsonl=True)
        summary["output_integrity"] = {
            "per_query_sha256": _sha256(per_query_path),
        }
        _write_exclusive(summary_path, summary)
        output_integrity = {
            "per_query_sha256": _sha256(per_query_path),
            "summary_sha256": _sha256(summary_path),
        }
        manifest = {
            "schema_version": 1,
            "status": "completed",
            "artifact": "private-ragflow-triad-sanitized-export",
            "provenance": provenance_out,
            "sha256": {**input_hashes, **output_integrity},
            "output_integrity": output_integrity,
            "privacy": summary["privacy"],
            "denominator": summary["denominator"],
        }
        _write_exclusive(manifest_path, manifest)
    except FileExistsError as exc:
        raise OutputExistsError(f"refusing to overwrite output: {output_dir}") from exc
    except OSError as exc:
        raise AnalyzerError("unable to write analyzer output") from exc
    return output_dir


def _write_exclusive(path: Path, value: object, *, jsonl: bool = False) -> None:
    with path.open("x", encoding="utf-8") as handle:
        if jsonl:
            assert isinstance(value, list)
            for row in value:
                json.dump(row, handle, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
        else:
            json.dump(value, handle, sort_keys=True, indent=2)
            handle.write("\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retrieval-jsonl", "--retrieval", required=True, type=Path)
    parser.add_argument("--public-retrieval-dir", required=True, type=Path)
    parser.add_argument("--qrels", required=True, type=Path)
    parser.add_argument("--runtime-manifest", required=True, type=Path)
    parser.add_argument("--runtime-stop-attestation", required=True, type=Path)
    parser.add_argument("--embedding-preflight-manifest", required=True, type=Path)
    parser.add_argument("--dataset-vector-attestation", required=True, type=Path)
    parser.add_argument("--measurement-protocol-attestation", required=True, type=Path)
    parser.add_argument("--public-retrieval-r1-dir", required=True, type=Path)
    parser.add_argument("--public-retrieval-r2-dir", required=True, type=Path)
    parser.add_argument("--qa-dir", "--upstream-qa-dir", required=True, type=Path)
    parser.add_argument("--output-dir", "--output", required=True, type=Path)
    parser.add_argument("--generation-model", default=GENERATION_MODEL)
    parser.add_argument("--judge-model", default=JUDGE_MODEL)
    parser.add_argument("--embedding-alias", required=True)
    parser.add_argument("--ragflow-version", required=True)
    parser.add_argument("--ragflow-commit", "--commit", required=True)
    parser.add_argument("--ragflow-image", "--image", required=True)
    parser.add_argument("--proxy-fingerprint-sha256", "--proxy", required=True)
    parser.add_argument("--runtime-manifest-sha256", required=True)
    parser.add_argument("--retrieval-manifest-sha256", required=True)
    parser.add_argument("--documents", type=int, required=True)
    parser.add_argument("--chunks", type=int, required=True)
    parser.add_argument("--ingestion-concurrency-race", default="observed")
    parser.add_argument(
        "--intentional-app-recovery", action=argparse.BooleanOptionalAction, default=True
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        output = analyze(
            args.retrieval_jsonl,
            args.qa_dir,
            args.output_dir,
            public_retrieval_dir=args.public_retrieval_dir,
            qrels_path=args.qrels,
            runtime_manifest_path=args.runtime_manifest,
            runtime_stop_attestation_path=args.runtime_stop_attestation,
            embedding_preflight_manifest_path=args.embedding_preflight_manifest,
            dataset_vector_attestation_path=args.dataset_vector_attestation,
            measurement_protocol_attestation_path=args.measurement_protocol_attestation,
            public_retrieval_r1_dir=args.public_retrieval_r1_dir,
            public_retrieval_r2_dir=args.public_retrieval_r2_dir,
            provenance={
                "generation_model": args.generation_model,
                "judge_model": args.judge_model,
                "embedding_alias": args.embedding_alias,
                "ragflow_version": args.ragflow_version,
                "ragflow_commit": args.ragflow_commit,
                "ragflow_image": args.ragflow_image,
                "proxy_fingerprint_sha256": args.proxy_fingerprint_sha256,
                "runtime_manifest_sha256": args.runtime_manifest_sha256,
                "retrieval_manifest_sha256": args.retrieval_manifest_sha256,
                "documents": args.documents,
                "chunks": args.chunks,
                "ingestion_concurrency_race": args.ingestion_concurrency_race,
                "intentional_app_recovery": args.intentional_app_recovery,
            },
        )
    except (AnalyzerError, OutputExistsError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps({"output": str(output)}))


if __name__ == "__main__":
    main()
