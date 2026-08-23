#!/usr/bin/env python3
# ruff: noqa: E501
"""Analyze the counterbalanced RAGZ large/1024 product benchmark.

The input contract is deliberately stricter than the producer's summaries.  The
analyzer validates both manifests, recomputes latency and retrieval quality from
the privacy-safe per-query rows, and emits only aggregate statistics.  It never
copies retrieved evidence, document names, query text, or provider payloads to
the output.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

SCHEMA_VERSION = 1
QUERY_IDS = tuple(f"q{number:02d}" for number in range(1, 16))
ANSWERABLE_COUNT = 12
REPETITIONS = 7
EXPECTED_QUERY_HASH = "dc44eabf6842f80bd0c3800e5f40e7e07f6e3a6c7ce0ab68051b42ee15de1906"
EXPECTED_MODEL = "text-embedding-3-large"
EXPECTED_DIMENSION = 1024
EXPECTED_ALIAS = "ragz-openai-text-embedding-3-large-d1024"
EXPECTED_PROXY = "e5a2913bf2fe061ba9811d8c102b740230c33ee549cc34e507aa03639200eb31"
STAGE_NAMES = frozenset(
    {
        "authorization_prefilter",
        "authorization_recheck",
        "candidate_decode",
        "candidate_dedupe",
        "collection_ready",
        "database_release",
        "dense_embedding",
        "embedder_resolution",
        "embedding_usage_record",
        "no_answer_probe",
        "query_expansion",
        "sparse_embedding",
        "unattributed_runner",
        "vector_search",
        "workspace_model_resolution",
    }
)
QUALITY_METRICS = ("recall_at_k", "reciprocal_rank", "ndcg_at_k")
LATENCY_METRICS = ("elapsed_ms",) + tuple(sorted(STAGE_NAMES))
INDEX_STAGE_NAMES = frozenset({"chunk", "dense_embedding", "parse", "qdrant_upsert", "sparse_embedding"})
BOOTSTRAP_SAMPLES = 10_000
BOOTSTRAP_SEED = 42
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


class AnalysisError(ValueError):
    """Raised when a benchmark artifact violates the analysis contract."""


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AnalysisError(f"unable to read JSON artifact: {path}") from exc


def _jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise AnalysisError(f"unable to read JSONL artifact: {path}") from exc
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AnalysisError(f"invalid JSONL at {path}:{number}") from exc
        if not isinstance(value, dict):
            raise AnalysisError(f"JSONL row is not an object at {path}:{number}")
        rows.append(value)
    return rows


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AnalysisError(f"{label} must be an object")
    return cast(Mapping[str, Any], value)


def _number(value: object, label: str) -> float:
    if isinstance(value, bool):
        raise AnalysisError(f"{label} must be numeric")
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise AnalysisError(f"{label} must be numeric") from exc
    if not math.isfinite(result):
        raise AnalysisError(f"{label} must be finite")
    return result


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise AnalysisError(f"{label} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError as exc:
            raise AnalysisError(f"{label} must be an integer") from exc
    raise AnalysisError(f"{label} must be an integer")


def _percentile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * quantile
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def summary(values: Sequence[float]) -> dict[str, float | int | None]:
    numbers = [float(value) for value in values]
    return {
        "observations": len(numbers),
        "mean_ms": statistics.fmean(numbers) if numbers else None,
        "p50_ms": _percentile(numbers, 0.50),
        "p95_ms": _percentile(numbers, 0.95),
        "p99_ms": _percentile(numbers, 0.99),
    }


def _walk_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, Mapping):
        for key, nested in value.items():
            keys.add(str(key).lower())
            keys.update(_walk_keys(nested))
    elif isinstance(value, list):
        for nested in value:
            keys.update(_walk_keys(nested))
    return keys


def _assert_privacy_safe(value: object, label: str) -> None:
    leaked = sorted(_BANNED_KEYS & _walk_keys(value))
    if leaked:
        raise AnalysisError(f"{label} contains forbidden privacy fields: {leaked}")


def _valid_hash(value: object, label: str) -> str:
    result = str(value or "")
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise AnalysisError(f"{label} must be a lowercase SHA-256 fingerprint")
    return result


def _manifest_identity(manifest: Mapping[str, Any], *, large: bool) -> dict[str, Any]:
    model = str(manifest.get("embedding_model", ""))
    dimension = _integer(manifest.get("embedding_dimension"), "embedding_dimension")
    query_set = _mapping(manifest.get("query_set"), "query_set")
    if str(manifest.get("dataset_id")) != "networking-pdfs-v1":
        raise AnalysisError("unexpected dataset_id")
    if _integer(query_set.get("count"), "query_set.count") != len(QUERY_IDS):
        raise AnalysisError("query set must contain exactly 15 queries")
    query_hash = str(query_set.get("sha256", ""))
    if query_hash != EXPECTED_QUERY_HASH:
        raise AnalysisError("query-set SHA-256 does not match the locked benchmark")
    if large:
        expected: tuple[str, int, str | None] = (EXPECTED_MODEL, EXPECTED_DIMENSION, EXPECTED_ALIAS)
    else:
        expected = ("text-embedding-3-small", 1536, None)
    if (model, dimension) != expected[:2]:
        raise AnalysisError("embedding model/dimension does not match the requested track")
    if large:
        if manifest.get("embedding_alias") != EXPECTED_ALIAS:
            raise AnalysisError("large/1024 embedding alias is invalid")
        if manifest.get("embedding_litellm_model_name") != EXPECTED_ALIAS:
            raise AnalysisError("large/1024 LiteLLM model alias is invalid")
        if manifest.get("embedding_requested_dimension") != EXPECTED_DIMENSION:
            raise AnalysisError("large/1024 requested dimension is invalid")
    if manifest.get("embedding_provider") != "openai" or manifest.get("embedding_transport") != "litellm":
        raise AnalysisError("embedding provider/transport is not OpenAI through LiteLLM")
    proxy = _valid_hash(manifest.get("embedding_proxy_fingerprint_sha256"), "embedding proxy")
    dense = str(manifest.get("dense", ""))
    expected_dense = f"openai-{model}-{dimension}"
    if dense != expected_dense:
        raise AnalysisError(f"dense alias must be {expected_dense}")
    schema = _mapping(manifest.get("stage_timing_schema"), "stage_timing_schema")
    if schema.get("version") != "retrieval-atomic-v1":
        raise AnalysisError("unsupported retrieval stage-timing schema")
    if schema.get("elapsed_ms_authoritative_total") is not True or schema.get("unit") != "milliseconds":
        raise AnalysisError("stage-timing schema is not authoritative milliseconds")
    repetitions = _integer(manifest.get("repetitions"), "repetitions")
    if large and repetitions != REPETITIONS:
        raise AnalysisError("large/1024 product runs require seven scored repetitions")
    if _integer(manifest.get("warmups"), "warmups") != 5 and large:
        raise AnalysisError("large/1024 product runs require five warmups")
    return {
        "dataset_id": manifest["dataset_id"],
        "query_set": {"count": len(QUERY_IDS), "sha256": query_hash},
        "embedding_model": model,
        "embedding_dimension": dimension,
        "embedding_alias": manifest.get("embedding_alias"),
        "embedding_provider": manifest["embedding_provider"],
        "embedding_transport": manifest["embedding_transport"],
        "embedding_proxy_fingerprint_sha256": proxy,
        "dense": dense,
        "sparse": manifest.get("sparse"),
        "fusion": manifest.get("fusion"),
        "reranker": manifest.get("reranker"),
        "top_k": manifest.get("top_k"),
        "query_variants": manifest.get("query_variants"),
        "no_answer_threshold": manifest.get("no_answer_threshold"),
        "stage_timing_schema": dict(schema),
        "repetitions": repetitions,
        "warmups": _integer(manifest["warmups"], "warmups"),
        "pdfs": manifest.get("pdfs"),
    }


def validate_manifest(manifest: Mapping[str, Any], *, large: bool = True) -> dict[str, Any]:
    """Validate one manifest and return the non-sensitive fairness identity."""
    if manifest.get("status") != "completed":
        raise AnalysisError("run is not completed")
    if not isinstance(manifest.get("git_dirty"), bool):
        raise AnalysisError("git_dirty must be boolean")
    commit = str(manifest.get("git_commit", ""))
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise AnalysisError("git_commit must be a full lowercase commit hash")
    diff = _valid_hash(manifest.get("tracked_diff_sha256"), "tracked diff")
    identity = _manifest_identity(manifest, large=large)
    identity.update(
        {
            "git_commit": commit,
            "git_dirty": bool(manifest["git_dirty"]),
            "tracked_diff_sha256": diff,
            "condition_order": str(manifest.get("condition_order", "")),
        }
    )
    if identity["condition_order"] not in {"single-first", "multi-first"}:
        raise AnalysisError("condition_order must be single-first or multi-first")
    if large and manifest.get("benchmark_status") != "production_embedding_fixed_fusion":
        raise AnalysisError("large/1024 run has an unexpected benchmark status")
    return identity


def validate_records(root: Path, mode: str, *, repetitions: int = REPETITIONS) -> list[dict[str, Any]]:
    """Validate an exact query-by-repetition grid and atomic stage closure."""
    if mode not in {"single", "multi"}:
        raise AnalysisError(f"unknown mode: {mode}")
    rows = _jsonl(root / mode / "per_query.jsonl")
    expected_count = len(QUERY_IDS) * repetitions
    if len(rows) != expected_count:
        raise AnalysisError(f"{root.name}/{mode} must contain exactly {expected_count} rows")
    expected_expansion = 1 if mode == "single" else 3
    keys: list[tuple[str, int]] = []
    stage_schema: set[str] | None = None
    for index, row in enumerate(rows, 1):
        _assert_privacy_safe(row, f"{root.name}/{mode} row {index}")
        query_id = str(row.get("query_id", ""))
        repetition = _integer(row.get("repetition"), f"{mode} repetition")
        key = (query_id, repetition)
        keys.append(key)
        if str(row.get("mode")) != mode:
            raise AnalysisError(f"{root.name}/{mode} row has wrong mode")
        if query_id not in QUERY_IDS or not 1 <= repetition <= repetitions:
            raise AnalysisError(f"{root.name}/{mode} contains an invalid query grid key")
        if _integer(row.get("expansion_count"), f"{mode} expansion_count") != expected_expansion:
            raise AnalysisError(f"{root.name}/{mode} has an invalid expansion count")
        if row.get("error") is not None:
            raise AnalysisError(f"{root.name}/{mode} contains a scored error")
        if not isinstance(row.get("answerable"), bool):
            raise AnalysisError(f"{root.name}/{mode} answerable flag is not boolean")
        elapsed = _number(row.get("elapsed_ms"), f"{mode} elapsed_ms")
        if elapsed < 0:
            raise AnalysisError(f"{root.name}/{mode} elapsed_ms is negative")
        stages = _mapping(row.get("stage_timings_ms"), f"{mode} stage_timings_ms")
        stage_keys = set(str(key) for key in stages)
        if stage_schema is None:
            stage_schema = stage_keys
        if stage_keys != stage_schema or stage_keys != STAGE_NAMES:
            raise AnalysisError(f"{root.name}/{mode} stage schema is missing or inconsistent")
        stage_total = 0.0
        for stage in STAGE_NAMES:
            value = _number(stages[stage], f"{mode}.{stage}")
            if value < 0:
                raise AnalysisError(f"{mode}.{stage} is negative")
            stage_total += value
        if abs(stage_total - elapsed) > 0.05:
            raise AnalysisError(f"{root.name}/{mode} stage timings do not close to elapsed_ms")
        metrics = row.get("metrics")
        if row["answerable"]:
            metric_map = _mapping(metrics, f"{mode} metrics")
            for metric in QUALITY_METRICS:
                _number(metric_map.get(metric), f"{mode}.{metric}")
        elif metrics is not None:
            raise AnalysisError(f"{root.name}/{mode} off-corpus row contains quality metrics")
    expected_keys = {(query_id, repetition) for query_id in QUERY_IDS for repetition in range(1, repetitions + 1)}
    if set(keys) != expected_keys or len(set(keys)) != len(keys):
        raise AnalysisError(f"{root.name}/{mode} query/repetition grid is incomplete or duplicated")
    answerable_ids = {str(row["query_id"]) for row in rows if row["answerable"]}
    if len(answerable_ids) != ANSWERABLE_COUNT:
        raise AnalysisError(f"{root.name}/{mode} must contain 12 answerable query IDs")
    if any(bool(row["answerable"]) != (str(row["query_id"]) in answerable_ids) for row in rows):
        raise AnalysisError(f"{root.name}/{mode} answerable flags vary within a query")
    return rows


def _aggregate_mode(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    totals = [_number(row["elapsed_ms"], "elapsed_ms") for row in rows]
    mean_total = statistics.fmean(totals)
    stages: dict[str, Any] = {}
    for stage in sorted(STAGE_NAMES):
        values = [_number(_mapping(row["stage_timings_ms"], "stage_timings_ms")[stage], stage) for row in rows]
        stage_summary = summary(values)
        stage_mean = stage_summary["mean_ms"]
        stage_summary["mean_total_share"] = (
            float(stage_mean) / mean_total
            if isinstance(stage_mean, (int, float)) and mean_total
            else None
        )
        stages[stage] = stage_summary
    quality: dict[str, Any] = {}
    quality_rows = [row for row in rows if bool(row["answerable"])]
    for metric in QUALITY_METRICS:
        values = [_number(_mapping(row["metrics"], "metrics")[metric], metric) for row in quality_rows]
        quality[metric] = {"observations": len(values), "mean": statistics.fmean(values) if values else None}
    return {
        "observations": len(rows),
        "query_count": len({str(row["query_id"]) for row in rows}),
        "orders": 2,
        "repetitions_per_query_per_order": REPETITIONS,
        "answerable_observations": len(quality_rows),
        "off_corpus_observations": len(rows) - len(quality_rows),
        "errors": 0,
        "latency_ms": summary(totals),
        "quality": quality,
        "stages": stages,
        "stage_closure_max_abs_ms": max(
            abs(sum(_number(value, "stage") for value in _mapping(row["stage_timings_ms"], "stage_timings_ms").values()) - _number(row["elapsed_ms"], "elapsed_ms"))
            for row in rows
        ),
    }


def paired_bootstrap(
    single_rows: Sequence[Mapping[str, Any]],
    multi_rows: Sequence[Mapping[str, Any]],
    *,
    samples: int = BOOTSTRAP_SAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Bootstrap multi-minus-single deltas over query-level paired means."""
    def grouped(rows: Sequence[Mapping[str, Any]], metric: str, quality: bool) -> dict[str, float]:
        grouped_values: dict[str, list[float]] = defaultdict(list)
        for row in rows:
            if quality and not bool(row["answerable"]):
                continue
            source: Mapping[str, Any] = row if metric == "elapsed_ms" else _mapping(row["metrics"], "metrics")
            grouped_values[str(row["query_id"])].append(_number(source[metric], metric))
        return {query_id: statistics.fmean(values) for query_id, values in grouped_values.items()}

    rng = random.Random(seed)  # noqa: S311 - deterministic statistical resampling
    result: dict[str, Any] = {"bootstrap_samples": samples, "seed": seed, "unit": "query"}
    for metric, quality in (("elapsed_ms", False), *[(name, True) for name in QUALITY_METRICS]):
        first, second = grouped(single_rows, metric, quality), grouped(multi_rows, metric, quality)
        common = sorted(set(first) & set(second))
        deltas = [second[query_id] - first[query_id] for query_id in common]
        if not deltas:
            raise AnalysisError(f"no paired observations for {metric}")
        sampled_means = sorted(statistics.fmean(rng.choice(deltas) for _ in deltas) for _ in range(samples))
        result[metric] = {
            "paired_query_count": len(common),
            "mean_delta": statistics.fmean(deltas),
            "bootstrap_ci95": [sampled_means[int(samples * 0.025)], sampled_means[int(samples * 0.975) - 1]],
            "improved": sum(delta < 0 for delta in deltas) if metric == "elapsed_ms" else sum(delta > 0 for delta in deltas),
            "regressed": sum(delta > 0 for delta in deltas) if metric == "elapsed_ms" else sum(delta < 0 for delta in deltas),
            "tied": sum(delta == 0 for delta in deltas),
        }
    return result


def _index_summary(manifests: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    totals: dict[str, list[float]] = defaultdict(list)
    for manifest in manifests:
        corpus = _mapping(manifest.get("corpus_stats"), "corpus_stats")
        index = _mapping(corpus.get("index_atomic_latency_ms"), "corpus_stats.index_atomic_latency_ms")
        if set(index) != INDEX_STAGE_NAMES:
            raise AnalysisError("index-stage schema is missing or inconsistent")
        for stage in INDEX_STAGE_NAMES:
            totals[stage].append(_number(index[stage], f"index.{stage}"))
    combined = {stage: sum(values) for stage, values in totals.items()}
    total_ms = sum(combined.values())
    return {
        "observations": len(manifests),
        "combined_total_ms": total_ms,
        "stages": {
            stage: {
                "run_values_ms": values,
                "combined_total_ms": combined[stage],
                "mean_ms": statistics.fmean(values),
                "combined_total_share": combined[stage] / total_ms if total_ms else None,
            }
            for stage, values in sorted(totals.items())
        },
    }


def _historical(root_paths: Sequence[Path]) -> dict[str, Any]:
    if len(root_paths) != 2:
        raise AnalysisError("exactly two historical small/1536 runs are required")
    manifests = [_json(path / "manifest.json") for path in root_paths]
    identities = [validate_manifest(_mapping(manifest, "historical manifest"), large=False) for manifest in manifests]
    if {identity["condition_order"] for identity in identities} != {"single-first", "multi-first"}:
        raise AnalysisError("historical small/1536 runs are not counterbalanced")
    if len({identity["git_commit"] for identity in identities}) != 1 or len({identity["tracked_diff_sha256"] for identity in identities}) != 1:
        raise AnalysisError("historical runs do not share commit/diff identity")
    rows: dict[str, list[dict[str, Any]]] = {}
    for mode in ("single", "multi"):
        collected: list[dict[str, Any]] = []
        for root in root_paths:
            current = validate_records(root, mode, repetitions=3)
            collected.extend(current)
        rows[mode] = collected
    return {
        "description_only": True,
        "source_runs": [path.name for path in root_paths],
        "configuration": {
            "embedding_model": identities[0]["embedding_model"],
            "embedding_dimension": identities[0]["embedding_dimension"],
            "query_set": identities[0]["query_set"],
        },
        "denominators": {
            mode: {
                "observations": len(values),
                "query_count": 15,
                "repetitions_per_query_per_order": 3,
                "orders": 2,
                "answerable_observations": ANSWERABLE_COUNT * 3 * 2,
                "off_corpus_observations": (15 - ANSWERABLE_COUNT) * 3 * 2,
                "errors": 0,
            }
            for mode, values in rows.items()
        },
        "modes": {mode: _aggregate_mode(values) for mode, values in rows.items()},
    }


def build(*, run_roots: Sequence[Path], historical_run_roots: Sequence[Path]) -> dict[str, Any]:
    if len(run_roots) != 2:
        raise AnalysisError("exactly two large/1024 product runs are required")
    manifests = [_json(path / "manifest.json") for path in run_roots]
    identities = [validate_manifest(_mapping(manifest, "manifest")) for manifest in manifests]
    if {identity["condition_order"] for identity in identities} != {"single-first", "multi-first"}:
        raise AnalysisError("large/1024 runs are not counterbalanced")
    identity_keys = (
        "dataset_id", "query_set", "embedding_model", "embedding_dimension", "embedding_alias",
        "embedding_provider", "embedding_transport", "embedding_proxy_fingerprint_sha256", "dense",
        "sparse", "fusion", "reranker", "top_k", "query_variants", "no_answer_threshold",
        "stage_timing_schema", "repetitions", "warmups", "pdfs",
    )
    for key in identity_keys:
        if identities[0].get(key) != identities[1].get(key):
            raise AnalysisError(f"large/1024 runs disagree on {key}")
    if len({identity["git_commit"] for identity in identities}) != 1:
        raise AnalysisError("large/1024 runs disagree on git commit")
    if len({identity["tracked_diff_sha256"] for identity in identities}) != 1:
        raise AnalysisError("large/1024 runs disagree on tracked diff")
    rows: dict[str, list[dict[str, Any]]] = {}
    for mode in ("single", "multi"):
        rows[mode] = []
        for root in run_roots:
            rows[mode].extend(validate_records(root, mode))
    modes = {mode: _aggregate_mode(values) for mode, values in rows.items()}
    return {
        "schema_version": SCHEMA_VERSION,
        "copyright_safe": True,
        "track": "RAGZ networking exact-page product benchmark",
        "source_runs": [path.name for path in run_roots],
        "configuration": {
            key: identities[0][key]
            for key in (
                "dataset_id", "query_set", "embedding_model", "embedding_dimension", "embedding_alias",
                "embedding_provider", "embedding_transport", "embedding_proxy_fingerprint_sha256", "dense",
                "sparse", "fusion", "reranker", "top_k", "query_variants", "no_answer_threshold",
                "stage_timing_schema", "repetitions", "warmups",
            )
        },
        "run_integrity": [
            {
                "source_run": path.name,
                "condition_order": identity["condition_order"],
                "git_commit": identity["git_commit"],
                "git_dirty": identity["git_dirty"],
                "tracked_diff_sha256": identity["tracked_diff_sha256"],
            }
            for path, identity in zip(run_roots, identities, strict=True)
        ],
        "denominators": {
            mode: {
                "observations": values["observations"],
                "query_count": values["query_count"],
                "orders": values["orders"],
                "repetitions_per_query_per_order": values["repetitions_per_query_per_order"],
                "answerable_observations": values["answerable_observations"],
                "off_corpus_observations": values["off_corpus_observations"],
                "errors": values["errors"],
            }
            for mode, values in modes.items()
        },
        "modes": modes,
        "paired_multi_minus_single": paired_bootstrap(rows["single"], rows["multi"]),
        "index_stages": _index_summary(manifests),
        "historical_small1536": _historical(historical_run_roots),
    }


def _fmt(value: object, digits: int = 2) -> str:
    return "n/a" if not isinstance(value, (int, float)) else f"{float(value):.{digits}f}"


def markdown(result: Mapping[str, Any]) -> str:
    single = _mapping(_mapping(result["modes"], "modes")["single"], "single")
    multi = _mapping(_mapping(result["modes"], "modes")["multi"], "multi")
    single_latency = _mapping(single["latency_ms"], "single latency")
    multi_latency = _mapping(multi["latency_ms"], "multi latency")
    lines = [
        "# RAGZ large/1024 product benchmark analysis",
        "",
        "This report is aggregate-only: it contains no prompts, answers, query text, or retrieved evidence.",
        "",
        "## Run integrity",
        "",
        "| Run | Order | Commit | Tracked diff | Dirty flag |",
        "|---|---|---|---|---:|",
    ]
    for run in result["run_integrity"]:
        lines.append(
            f"| `{run['source_run']}` | `{run['condition_order']}` | `{run['git_commit']}` | "
            f"`{run['tracked_diff_sha256']}` | `{str(run['git_dirty']).lower()}` |"
        )
    lines.extend(
        [
            "",
            "## Combined retrieval latency",
            "",
            "| Mode | N | Mean ms | p50 ms | p95 ms | p99 ms |",
            "|---|---:|---:|---:|---:|---:|",
            f"| Single | {single_latency['observations']} | {_fmt(single_latency['mean_ms'])} | {_fmt(single_latency['p50_ms'])} | {_fmt(single_latency['p95_ms'])} | {_fmt(single_latency['p99_ms'])} |",
            f"| Multi | {multi_latency['observations']} | {_fmt(multi_latency['mean_ms'])} | {_fmt(multi_latency['p50_ms'])} | {_fmt(multi_latency['p95_ms'])} | {_fmt(multi_latency['p99_ms'])} |",
            "",
            "## Atomic retrieval stages",
            "",
            "| Stage | Single mean ms | Multi mean ms | Single share | Multi share |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    single_stages = _mapping(single["stages"], "single stages")
    multi_stages = _mapping(multi["stages"], "multi stages")
    for stage in sorted(STAGE_NAMES, key=lambda name: float(_mapping(single_stages[name], name)["mean_ms"]), reverse=True):
        one, many = _mapping(single_stages[stage], stage), _mapping(multi_stages[stage], stage)
        lines.append(
            f"| `{stage}` | {_fmt(one['mean_ms'])} | {_fmt(many['mean_ms'])} | "
            f"{_fmt(float(one['mean_total_share']) * 100, 1)}% | {_fmt(float(many['mean_total_share']) * 100, 1)}% |"
        )
    lines.extend(
        [
            "",
            "## Paired multi-minus-single bootstrap",
            "",
            "Bootstrap resampling is over the 15 query-level paired means (12 for retrieval quality), with 10,000 samples and seed 42.",
            "",
            "| Metric | Paired queries | Mean delta | 95% CI |",
            "|---|---:|---:|---:|",
        ]
    )
    paired = _mapping(result["paired_multi_minus_single"], "paired bootstrap")
    labels = {"elapsed_ms": "Latency ms", "recall_at_k": "Recall@5", "reciprocal_rank": "MRR@5", "ndcg_at_k": "nDCG@5"}
    for metric in ("elapsed_ms", *QUALITY_METRICS):
        values = _mapping(paired[metric], metric)
        interval = values["bootstrap_ci95"]
        lines.append(f"| {labels[metric]} | {values['paired_query_count']} | {_fmt(values['mean_delta'], 4)} | [{_fmt(interval[0], 4)}, {_fmt(interval[1], 4)}] |")
    lines.extend(["", "## Combined index-stage totals", "", "| Stage | Combined ms | Share |", "|---|---:|---:|"])
    index = _mapping(result["index_stages"], "index stages")
    for stage, values in _mapping(index["stages"], "index stage values").items():
        values_map = _mapping(values, stage)
        lines.append(f"| `{stage}` | {_fmt(values_map['combined_total_ms'])} | {_fmt(float(values_map['combined_total_share']) * 100, 1)}% |")
    historical = _mapping(result["historical_small1536"], "historical")
    lines.extend(["", "## Prior small/1536 track (descriptive only)", "", "The prior pair is shown only as context; its denominator is 15 queries × 3 repetitions × 2 orderings = 90 observations per mode.", "", "| Mode | N | Answerable N | Mean ms | p50 ms | p95 ms | p99 ms |", "|---|---:|---:|---:|---:|---:|---:|"])
    for mode, values in _mapping(historical["modes"], "historical modes").items():
        metrics = _mapping(values, mode)
        latency = _mapping(metrics["latency_ms"], f"historical {mode} latency")
        denom = _mapping(_mapping(historical["denominators"], "historical denominators")[mode], mode)
        lines.append(f"| {mode.title()} | {denom['observations']} | {denom['answerable_observations']} | {_fmt(latency['mean_ms'])} | {_fmt(latency['p50_ms'])} | {_fmt(latency['p95_ms'])} | {_fmt(latency['p99_ms'])} |")
    lines.extend(["", "## Interpretation", "", "The dominant retrieval stage is the one with the largest mean share above; stage closure is validated per row. Fixed local alternatives make query expansion near-zero and are not a live Luna expansion measurement. The historical small/1536 comparison is not a controlled ranking because it has a different model, dimension, repetition count, and commit.", ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="append", required=True, type=Path)
    parser.add_argument("--historical-run", action="append", required=True, type=Path)
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-md", required=True, type=Path)
    args = parser.parse_args()
    for output in (args.output_json, args.output_md):
        if output.exists():
            raise FileExistsError(f"refusing to overwrite {output}")
    result = build(run_roots=args.run, historical_run_roots=args.historical_run)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(markdown(result), encoding="utf-8")


if __name__ == "__main__":
    main()
