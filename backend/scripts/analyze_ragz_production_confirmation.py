#!/usr/bin/env python3
"""Fail-closed aggregation for the counterbalanced Q1/Q3 cache confirmation."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from run_multi_query_benchmark import (  # noqa: E402
    bootstrap_ci,
    production_confirmation_conditions,
)


class ConfirmationAnalysisError(RuntimeError):
    pass


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ConfirmationAnalysisError(f"{path.name} is not an object")
    return value


def _jsonl(path: Path) -> list[dict[str, Any]]:
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if any(not isinstance(row, dict) for row in rows):
        raise ConfirmationAnalysisError(f"{path.name} contains a non-object row")
    return rows


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def percentile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def distribution(values: Sequence[float]) -> dict[str, float | int | None]:
    return {
        "observations": len(values),
        "mean": statistics.fmean(values) if values else None,
        "p50": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
    }


def _mean_metric(rows: Sequence[Mapping[str, Any]], name: str) -> float:
    values = [
        float(row["metrics"][name])
        for row in rows
        if row.get("answerable") and isinstance(row.get("metrics"), Mapping)
    ]
    if not values:
        raise ConfirmationAnalysisError(f"no answerable values for {name}")
    return statistics.fmean(values)


def _aggregate(rows: list[dict[str, Any]], *, query_count: int, cache: str) -> dict[str, Any]:
    if len(rows) != 240:
        raise ConfirmationAnalysisError(
            f"Q{query_count}/{cache} must contain 240 scored rows"
        )
    if any(row.get("error") is not None for row in rows):
        raise ConfirmationAnalysisError(f"Q{query_count}/{cache} contains errors")
    expected_hits = query_count if cache == "warm" else 0
    expected_misses = 0 if cache == "warm" else query_count
    if any(
        (row.get("embedding_cache_hits"), row.get("embedding_cache_misses"))
        != (expected_hits, expected_misses)
        for row in rows
    ):
        raise ConfirmationAnalysisError(f"Q{query_count}/{cache} cache state differs")
    latency = [float(row["elapsed_ms"]) for row in rows]
    stages = sorted(
        {str(stage) for row in rows for stage in row.get("stage_timings_ms", {})}
    )
    atomic = {
        stage: distribution(
            [
                float(row["stage_timings_ms"][stage])
                for row in rows
                if stage in row.get("stage_timings_ms", {})
            ]
        )
        for stage in stages
    }
    parallel_vector_probe = [
        max(
            float(row["stage_timings_ms"].get("vector_search", 0.0)),
            float(row["stage_timings_ms"].get("no_answer_probe", 0.0)),
        )
        for row in rows
    ]
    signatures: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in rows:
        signature = json.dumps(row["retrieved"], sort_keys=True, separators=(",", ":"))
        signatures[(str(row["mode"]).split("_", 1)[0], str(row["query_id"]))].add(
            signature
        )
    stable = sum(len(values) == 1 for values in signatures.values())
    return {
        "query_count": query_count,
        "cache_mode": cache,
        "observations": len(rows),
        "answerable_observations": sum(bool(row["answerable"]) for row in rows),
        "quality": {
            "recall_at_5": _mean_metric(rows, "recall_at_k"),
            "mrr_at_5": _mean_metric(rows, "reciprocal_rank"),
            "ndcg_at_5": _mean_metric(rows, "ndcg_at_k"),
        },
        "latency_ms": distribution(latency),
        "atomic_latency_ms": atomic,
        "parallel_vector_search_no_answer_critical_ms": distribution(
            parallel_vector_probe
        ),
        "ranking_stability": {
            "order_query_groups": len(signatures),
            "stable_groups": stable,
            "unstable_groups": len(signatures) - stable,
        },
    }


def _paired(rows: Sequence[Mapping[str, Any]], *, cache: str, seed: int) -> dict[str, Any]:
    indexed = {
        (
            str(row["mode"]).split("_", 1)[0],
            int(row["expansion_count"]),
            int(row["repetition"]),
            str(row["query_id"]),
        ): row
        for row in rows
        if str(row["mode"]).endswith(f"cache-{cache}")
    }
    output: dict[str, Any] = {}
    for metric in ("recall_at_k", "reciprocal_rank", "ndcg_at_k", "elapsed_ms"):
        deltas: list[float] = []
        for order in ("forward", "reverse"):
            for repetition in range(1, 6):
                query_ids = {
                    key[3]
                    for key in indexed
                    if key[:3] == (order, 1, repetition)
                }
                for query_id in query_ids:
                    one = indexed[(order, 1, repetition, query_id)]
                    three = indexed[(order, 3, repetition, query_id)]
                    if metric == "elapsed_ms":
                        left, right = float(one[metric]), float(three[metric])
                    elif one.get("answerable"):
                        left = float(one["metrics"][metric])
                        right = float(three["metrics"][metric])
                    else:
                        continue
                    deltas.append(right - left)
        output[metric] = {
            "paired_observations": len(deltas),
            "mean_q3_minus_q1": statistics.fmean(deltas),
            "bootstrap_ci95": bootstrap_ci(deltas, seed=seed),
            "improved": sum(delta > 1e-12 for delta in deltas),
            "regressed": sum(delta < -1e-12 for delta in deltas),
            "tied": sum(abs(delta) <= 1e-12 for delta in deltas),
        }
    return output


def analyze(root: Path) -> dict[str, Any]:
    root = root.resolve()
    manifest = _json(root / "manifest.json")
    if manifest.get("status") != "completed" or manifest.get(
        "production_confirmation"
    ) is not True:
        raise ConfirmationAnalysisError("input is not a completed confirmation")
    all_rows: list[dict[str, Any]] = []
    grouped: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for output_id, condition in production_confirmation_conditions():
        directory = root / output_id
        summary = _json(directory / "summary.json")
        rows = _jsonl(directory / "per_query.jsonl")
        warmups = _jsonl(directory / "warmups.jsonl")
        if summary.get("errors") != 0 or len(rows) != 120 or len(warmups) != 48:
            raise ConfirmationAnalysisError(f"{output_id} denominator/status differs")
        grouped[(condition.query_count, condition.cache_mode)].extend(rows)
        all_rows.extend(rows)
    cells = [
        _aggregate(grouped[(query_count, cache)], query_count=query_count, cache=cache)
        for query_count in (1, 3)
        for cache in ("off", "warm")
    ]
    return {
        "schema_version": 1,
        "status": "completed",
        "analysis_kind": "ragz-production-mqr-cache-confirmation",
        "source_manifest_sha256": _sha256(root / "manifest.json"),
        "cells": cells,
        "paired": {
            cache: _paired(all_rows, cache=cache, seed=int(manifest["seed"]))
            for cache in ("off", "warm")
        },
        "parallel_stage_contract": {
            "overlap": ["vector_search", "no_answer_probe"],
            "elapsed_ms_authoritative": True,
            "critical_group_uses_max_not_sum": True,
        },
        "limitations": [
            "Fixed private alternatives isolate retrieval; live expansion quality is separate.",
            "Hosted embedding calls can vary across repetitions despite identical inputs.",
            "Two orders and five repetitions support paired estimation, not a universal ranking.",
        ],
    }


def markdown(result: Mapping[str, Any]) -> str:
    lines = [
        "# RAGZ production MQR/cache confirmation",
        "",
        "| Cell | Recall@5 | MRR@5 | nDCG@5 | Mean ms | p50 ms | p95 ms | Stable groups |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for cell in result["cells"]:
        quality = cell["quality"]
        latency = cell["latency_ms"]
        stability = cell["ranking_stability"]
        lines.append(
            f"| Q{cell['query_count']} cache-{cell['cache_mode']} | "
            f"{quality['recall_at_5']:.4f} | {quality['mrr_at_5']:.4f} | "
            f"{quality['ndcg_at_5']:.4f} | {latency['mean']:.2f} | "
            f"{latency['p50']:.2f} | {latency['p95']:.2f} | "
            f"{stability['stable_groups']}/{stability['order_query_groups']} |"
        )
    lines.extend(
        [
            "",
            "Vector search and the dense no-answer probe overlap; request elapsed time is "
            "authoritative and the parallel group's critical duration is their maximum, not sum.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-markdown", required=True, type=Path)
    args = parser.parse_args()
    if args.output_json.exists() or args.output_markdown.exists():
        raise FileExistsError("refusing to overwrite confirmation analysis")
    result = analyze(args.input)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    args.output_markdown.write_text(markdown(result), encoding="utf-8")


if __name__ == "__main__":
    main()
