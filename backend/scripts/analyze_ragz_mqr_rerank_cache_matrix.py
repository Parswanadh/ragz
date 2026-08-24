#!/usr/bin/env python3
"""Fail-closed analysis for the frozen 15-condition RAGZ retrieval matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from run_multi_query_benchmark import retrieval_matrix_conditions


class MatrixAnalysisError(RuntimeError):
    pass


def _json(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MatrixAnalysisError(f"unable to read {path.name}") from exc
    if not isinstance(value, Mapping):
        raise MatrixAnalysisError(f"{path.name} must contain an object")
    return value


def _jsonl(path: Path) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise MatrixAnalysisError(f"unable to read {path.name}") from exc
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise MatrixAnalysisError(
                f"invalid JSONL at {path.name}:{line_number}"
            ) from exc
        if not isinstance(row, Mapping):
            raise MatrixAnalysisError(f"non-object row at {path.name}:{line_number}")
        rows.append(row)
    return rows


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MatrixAnalysisError(f"{field} must be numeric")
    return float(value)


def _validate_condition(
    root: Path,
    *,
    condition_id: str,
    query_count: int,
    rerank_pool: int | None,
    cache_mode: str,
) -> dict[str, Any]:
    directory = root / condition_id
    summary = _json(directory / "summary.json")
    rows = _jsonl(directory / "per_query.jsonl")
    warmups = _jsonl(directory / "warmups.jsonl")
    repetitions = summary.get("repetitions")
    source_queries = summary.get("query_count")
    if not isinstance(repetitions, int) or repetitions < 1:
        raise MatrixAnalysisError(f"{condition_id} repetitions are invalid")
    if not isinstance(source_queries, int) or source_queries < 1:
        raise MatrixAnalysisError(f"{condition_id} query count is invalid")
    expected_rows = source_queries * repetitions
    if len(rows) != expected_rows:
        raise MatrixAnalysisError(f"{condition_id} row denominator is incomplete")
    expected_grid = {
        (f"{row['query_id']}", repetition)
        for row in rows[:source_queries]
        for repetition in range(1, repetitions + 1)
    }
    actual_grid = {
        (str(row.get("query_id")), int(row.get("repetition", 0))) for row in rows
    }
    if len(actual_grid) != expected_rows or actual_grid != expected_grid:
        raise MatrixAnalysisError(f"{condition_id} query/repetition grid is invalid")
    if any(row.get("error") is not None for row in rows):
        raise MatrixAnalysisError(f"{condition_id} contains retrieval errors")
    if any(row.get("expansion_count") != query_count for row in rows):
        raise MatrixAnalysisError(f"{condition_id} expansion count differs")
    if any(row.get("rerank_candidate_pool") != rerank_pool for row in rows):
        raise MatrixAnalysisError(f"{condition_id} rerank pool differs")
    condition = summary.get("condition")
    if condition != {
        "query_count": query_count,
        "rerank_candidate_pool": rerank_pool,
        "cache_mode": cache_mode,
    }:
        raise MatrixAnalysisError(f"{condition_id} summary condition differs")
    for row in rows:
        hits = row.get("embedding_cache_hits")
        misses = row.get("embedding_cache_misses")
        if not isinstance(hits, int) or not isinstance(misses, int):
            raise MatrixAnalysisError(f"{condition_id} cache counters are invalid")
        expected_hits = query_count if cache_mode == "warm" else 0
        expected_misses = 0 if cache_mode == "warm" else query_count
        if (hits, misses) != (expected_hits, expected_misses):
            raise MatrixAnalysisError(f"{condition_id} scored cache state differs")
    first_warmup = [row for row in warmups if row.get("warmup") == 1]
    if cache_mode == "warm" and len(first_warmup) != source_queries:
        raise MatrixAnalysisError(f"{condition_id} first warmup denominator differs")
    cold_latency = (
        sum(
            _number(row.get("elapsed_ms"), f"{condition_id}.warmup.elapsed_ms")
            for row in first_warmup
        )
        / len(first_warmup)
        if first_warmup
        else None
    )
    latency = summary.get("latency_ms")
    if not isinstance(latency, Mapping):
        raise MatrixAnalysisError(f"{condition_id} latency summary is missing")
    quality: dict[str, object] = {
        "recall_at_5": summary.get("mean_recall_at_k"),
        "mrr_at_5": summary.get("mean_reciprocal_rank"),
        "ndcg_at_5": summary.get("mean_ndcg_at_k"),
        "abstention_f1": (
            summary.get("abstention", {}).get("f1")
            if isinstance(summary.get("abstention"), Mapping)
            else None
        ),
    }
    output: dict[str, Any] = {
        "condition_id": condition_id,
        "condition": dict(condition),
        "observations": len(rows),
        "quality_observations": summary.get("quality_observations"),
        "errors": 0,
        "quality": quality,
        "latency_ms": dict(latency),
        "cold_first_warmup_mean_ms": cold_latency,
        "embedding_cache": summary.get("embedding_cache"),
        "rerank_usage_units_including_warmups": summary.get(
            "rerank_usage_units_including_warmups"
        ),
        "atomic_latency_ms": summary.get("atomic_latency_ms"),
        "warmup_atomic_latency_ms": summary.get("warmup_atomic_latency_ms"),
        "sha256": {
            "summary": _sha256(directory / "summary.json"),
            "per_query": _sha256(directory / "per_query.jsonl"),
            "warmups": _sha256(directory / "warmups.jsonl"),
        },
    }
    for metric in ("recall_at_5", "mrr_at_5", "ndcg_at_5"):
        value = quality[metric]
        if value is None or not 0 <= _number(value, metric) <= 1:
            raise MatrixAnalysisError(f"{condition_id} {metric} is invalid")
    return output


def _dominates(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    left_quality = left["quality"]
    right_quality = right["quality"]
    left_latency = left["latency_ms"]
    right_latency = right["latency_ms"]
    assert isinstance(left_quality, Mapping) and isinstance(right_quality, Mapping)
    assert isinstance(left_latency, Mapping) and isinstance(right_latency, Mapping)
    dimensions = (
        (
            _number(left_quality["recall_at_5"], "recall"),
            _number(right_quality["recall_at_5"], "recall"),
            True,
        ),
        (
            _number(left_quality["ndcg_at_5"], "ndcg"),
            _number(right_quality["ndcg_at_5"], "ndcg"),
            True,
        ),
        (
            _number(left_latency["p95"], "p95"),
            _number(right_latency["p95"], "p95"),
            False,
        ),
    )
    no_worse = all(a >= b if higher else a <= b for a, b, higher in dimensions)
    strictly_better = any(a > b if higher else a < b for a, b, higher in dimensions)
    return no_worse and strictly_better


def analyze(root: Path) -> dict[str, Any]:
    root = root.resolve()
    manifest = _json(root / "manifest.json")
    if manifest.get("status") != "completed" or manifest.get("condition_matrix") is not True:
        raise MatrixAnalysisError("input is not a completed matrix run")
    conditions: list[dict[str, Any]] = []
    for spec in retrieval_matrix_conditions():
        conditions.append(
            _validate_condition(
                root,
                condition_id=spec.condition_id,
                query_count=spec.query_count,
                rerank_pool=spec.rerank_candidate_pool,
                cache_mode=spec.cache_mode,
            )
        )
    if len(conditions) != 15:
        raise MatrixAnalysisError("matrix must contain exactly 15 conditions")
    pareto = [
        item["condition_id"]
        for item in conditions
        if not any(
            _dominates(other, item)
            for other in conditions
            if other["condition_id"] != item["condition_id"]
        )
    ]
    blended: dict[str, dict[str, float]] = {}
    by_id = {str(item["condition_id"]): item for item in conditions}
    for query_count in (1, 3, 5):
        off = by_id[f"q{query_count}_rerank-off_cache-off"]
        warm = by_id[f"q{query_count}_rerank-off_cache-warm"]
        miss = _number(off["latency_ms"]["mean"], "off mean")
        hit = _number(warm["latency_ms"]["mean"], "warm mean")
        blended[f"q{query_count}"] = {
            str(rate): (1 - rate) * miss + rate * hit
            for rate in (0.0, 0.10, 0.25, 0.50)
        }
    return {
        "schema_version": 1,
        "status": "completed",
        "analysis_kind": "ragz-mqr-rerank-cache-matrix",
        "source_manifest_sha256": _sha256(root / "manifest.json"),
        "conditions": conditions,
        "pareto_condition_ids": pareto,
        "cache_blended_mean_latency_ms": blended,
        "limitations": [
            f"rerank screen provider is {manifest.get('reranker_provider')}",
            "live Luna expansion latency is not part of fixed-alternative retrieval timing",
            "LLM top_p is provider default and is not a reranking parameter",
        ],
    }


def markdown(result: Mapping[str, Any]) -> str:
    lines = [
        "# RAGZ MQR/rerank/cache matrix analysis",
        "",
        "| Condition | Recall@5 | MRR@5 | nDCG@5 | Mean ms | p95 ms | Cache hits/misses |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for item in result["conditions"]:
        quality = item["quality"]
        latency = item["latency_ms"]
        cache = item["embedding_cache"]
        lines.append(
            f"| {item['condition_id']} | {quality['recall_at_5']:.4f} | "
            f"{quality['mrr_at_5']:.4f} | {quality['ndcg_at_5']:.4f} | "
            f"{latency['mean']:.2f} | {latency['p95']:.2f} | "
            f"{cache['hits']}/{cache['misses']} |"
        )
    lines.extend(
        [
            "",
            "Pareto conditions: "
            + ", ".join(f"`{value}`" for value in result["pareto_condition_ids"]),
            "",
            "Rerank P is the pre-rerank candidate pool. LLM top_p is held at provider default.",
        ]
    )
    return "\n".join(lines) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-markdown", required=True, type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.output_json.exists() or args.output_markdown.exists():
        raise FileExistsError("refusing to overwrite matrix analysis")
    result = analyze(args.input)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    args.output_markdown.write_text(markdown(result), encoding="utf-8")
    print(json.dumps({"status": "completed", "output": str(args.output_json)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
