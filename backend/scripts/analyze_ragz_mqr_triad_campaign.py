#!/usr/bin/env python3
"""Validate and aggregate the RAGZ MQR/rerank/cache plus RAG-Triad campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from run_ragz_matrix_triad import (  # noqa: E402
    ANSWER_METRICS,
    condition_id,
    ranking_conditions,
)


class CampaignAnalysisError(RuntimeError):
    pass


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CampaignAnalysisError(f"{path.name} is not an object")
    return value


def _jsonl(path: Path) -> list[dict[str, Any]]:
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if any(not isinstance(row, dict) for row in rows):
        raise CampaignAnalysisError(f"{path.name} contains a non-object row")
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


def _mean(rows: Sequence[Mapping[str, Any]], path: tuple[str, ...]) -> float | None:
    values: list[float] = []
    for row in rows:
        value: object = row
        for key in path:
            if not isinstance(value, Mapping) or key not in value:
                value = None
                break
            value = value[key]
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            values.append(float(value))
    return statistics.fmean(values) if values else None


def _abstention(rows: Sequence[Mapping[str, Any]]) -> dict[str, float | int | None]:
    tp = sum(not row["answerable"] and row["abstained"] for row in rows)
    fp = sum(row["answerable"] and row["abstained"] for row in rows)
    fn = sum(not row["answerable"] and not row["abstained"] for row in rows)
    tn = sum(row["answerable"] and not row["abstained"] for row in rows)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    return {
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "true_negative": tn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _condition(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    selected = [row for row in rows if row.get("condition_id") == key]
    if len(selected) != 24 or len({row.get("query_id") for row in selected}) != 24:
        raise CampaignAnalysisError(f"{key}: denominator is not 24 unique queries")
    if any(row.get("error_codes") for row in selected):
        raise CampaignAnalysisError(f"{key}: query errors are present")
    answerable = [row for row in selected if row.get("answerable") is True]
    if len(answerable) != 20:
        raise CampaignAnalysisError(f"{key}: answerable denominator is not 20")
    stages = sorted(
        {str(stage) for row in selected for stage in row.get("timings_ms", {})}
    )
    atomic = {
        stage: distribution(
            [
                float(row["timings_ms"][stage])
                for row in selected
                if stage in row.get("timings_ms", {})
            ]
        )
        for stage in stages
    }
    retrieval_total = [float(row["timings_ms"]["retrieval_total"]) for row in selected]
    quota_wait = [
        float(row["timings_ms"].get("retrieval.rerank.rate_limit_wait", 0.0))
        for row in selected
    ]
    intrinsic = [
        max(0.0, total - wait)
        for total, wait in zip(retrieval_total, quota_wait, strict=True)
    ]
    return {
        "condition_id": key,
        "observations": 24,
        "answerable_observations": 20,
        "retrieval": {
            "recall_at_5": _mean(answerable, ("retrieval_metrics", "recall_at_k")),
            "mrr_at_5": _mean(answerable, ("retrieval_metrics", "reciprocal_rank")),
            "ndcg_at_5": _mean(answerable, ("retrieval_metrics", "ndcg_at_k")),
        },
        "rag_triad": {
            name: _mean(answerable, ("judge", name)) for name in ANSWER_METRICS
        },
        "citation": {
            name: _mean(answerable, ("citation", name))
            for name in (
                "citation_validity",
                "citation_evidence_precision",
                "citation_evidence_recall",
            )
        },
        "answer_abstention": _abstention(selected),
        "latency_ms": {
            "retrieval_observed": distribution(retrieval_total),
            "reranker_account_wait": distribution(quota_wait),
            "retrieval_without_benchmark_rate_wait": distribution(intrinsic),
            "generation": distribution(
                [float(row["timings_ms"].get("generation_provider", 0.0)) for row in selected]
            ),
            "judge": distribution(
                [float(row["timings_ms"].get("judge_provider", 0.0)) for row in selected]
            ),
            "total_with_judge": distribution(
                [float(row["timings_ms"]["total"]) for row in selected]
            ),
        },
        "atomic_latency_ms": atomic,
        "ranking_stability": dict(Counter(str(row["ranking_match_kind"]) for row in selected)),
        "structured_output_retries": sum(
            int(row["structured_output_retries"]["generation"])
            + int(row["structured_output_retries"]["judge"])
            for row in selected
        ),
    }


def _cache_analysis(screen: Path) -> dict[str, Any]:
    validation = _json(screen / "post_run_validation.json")
    if validation.get("status") != "invalid_as_complete_matrix":
        raise CampaignAnalysisError("screen validation status is missing")
    output: dict[str, Any] = {
        "screen_status": validation["status"],
        "complete_conditions": validation["complete_condition_count"],
        "invalid_condition": validation["invalid_condition"]["condition_id"],
        "query_lanes": {},
    }
    for query_count in (1, 3, 5):
        off = _json(screen / f"q{query_count}_rerank-off_cache-off" / "summary.json")
        warm = _json(screen / f"q{query_count}_rerank-off_cache-warm" / "summary.json")
        off_mean = float(off["latency_ms"]["mean"])
        warm_mean = float(warm["latency_ms"]["mean"])
        warmups = _jsonl(
            screen / f"q{query_count}_rerank-off_cache-warm" / "warmups.jsonl"
        )
        cold = statistics.fmean(float(row["elapsed_ms"]) for row in warmups)
        output["query_lanes"][f"q{query_count}"] = {
            "cache_off_mean_ms": off_mean,
            "cold_population_mean_ms": cold,
            "warm_hit_mean_ms": warm_mean,
            "warm_hit_p95_ms": warm["latency_ms"]["p95"],
            "mean_saved_ms": off_mean - warm_mean,
            "mean_speedup": off_mean / warm_mean,
            "scored_hits": warm["embedding_cache"]["hits"],
            "scored_misses": warm["embedding_cache"]["misses"],
            "quality_delta_is_tie_order_diagnostic": {
                "recall": warm["mean_recall_at_k"] - off["mean_recall_at_k"],
                "mrr": warm["mean_reciprocal_rank"] - off["mean_reciprocal_rank"],
                "ndcg": warm["mean_ndcg_at_k"] - off["mean_ndcg_at_k"],
            },
        }
    return output


def dominates(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    left_metrics = (
        float(left["retrieval"]["recall_at_5"]),
        float(left["retrieval"]["mrr_at_5"]),
        float(left["retrieval"]["ndcg_at_5"]),
        -float(left["latency_ms"]["retrieval_without_benchmark_rate_wait"]["p95"]),
    )
    right_metrics = (
        float(right["retrieval"]["recall_at_5"]),
        float(right["retrieval"]["mrr_at_5"]),
        float(right["retrieval"]["ndcg_at_5"]),
        -float(right["latency_ms"]["retrieval_without_benchmark_rate_wait"]["p95"]),
    )
    return all(
        a >= b for a, b in zip(left_metrics, right_metrics, strict=True)
    ) and any(
        a > b for a, b in zip(left_metrics, right_metrics, strict=True)
    )


def analyze(triad: Path, screen: Path) -> dict[str, Any]:
    manifest = _json(triad / "manifest.json")
    if manifest.get("status") != "completed":
        raise CampaignAnalysisError("Triad run is not completed")
    rows = _jsonl(triad / "per_query.jsonl")
    if len(rows) != 288:
        raise CampaignAnalysisError("Triad run does not contain 12 x 24 rows")
    conditions = [_condition(rows, condition_id(*value)) for value in ranking_conditions()]
    pareto = [
        condition["condition_id"]
        for condition in conditions
        if not any(
            dominates(other, condition)
            for other in conditions
            if other["condition_id"] != condition["condition_id"]
        )
    ]
    return {
        "schema_version": 1,
        "status": "completed",
        "analysis_kind": "ragz-large-books-mqr-rerank-cache-triad",
        "source_sha256": {
            "triad_manifest": _sha256(triad / "manifest.json"),
            "triad_rows": _sha256(triad / "per_query.jsonl"),
            "screen_manifest": _sha256(screen / "manifest.json"),
            "screen_validation": _sha256(screen / "post_run_validation.json"),
        },
        "conditions": conditions,
        "pareto_condition_ids": pareto,
        "embedding_cache": _cache_analysis(screen),
        "cost": manifest["cost"],
        "limitations": [
            "One scored retrieval/Triad observation per query and condition; "
            "no significance claim.",
            "RAG-Triad is an automated separate-model same-provider evaluation, "
            "not human ground truth.",
            "Cohere account throttling is reported separately from provider/local rerank latency.",
            "Cache quality differences diagnose equal-score RRF ordering; cache "
            "does not change vectors.",
        ],
    }


def markdown(result: Mapping[str, Any]) -> str:
    lines = [
        "# RAGZ large-books MQR/rerank/cache/RAG-Triad analysis",
        "",
        "| Condition | Recall@5 | MRR@5 | nDCG@5 | Context rel. | Grounded | "
        "Answer rel. | Retrieval p95* |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in result["conditions"]:
        retrieval = item["retrieval"]
        triad = item["rag_triad"]
        latency = item["latency_ms"]["retrieval_without_benchmark_rate_wait"]
        lines.append(
            f"| {item['condition_id']} | {retrieval['recall_at_5']:.4f} | "
            f"{retrieval['mrr_at_5']:.4f} | {retrieval['ndcg_at_5']:.4f} | "
            f"{triad['context_relevance']:.4f} | {triad['groundedness']:.4f} | "
            f"{triad['answer_relevance']:.4f} | {latency['p95']:.2f} ms |"
        )
    lines.extend(
        [
            "",
            "\\* Retrieval p95 excludes only the benchmark account-rate wait; it retains "
            "OpenAI embedding, Cohere provider, Qdrant, database and local work.",
            "",
            "Pareto conditions: "
            + ", ".join(f"`{value}`" for value in result["pareto_condition_ids"]),
            "",
            "## Query embedding cache",
            "",
            "| Query lanes | Cache off mean | Cold population mean | Warm-hit mean | Speedup |",
            "|---:|---:|---:|---:|---:|",
        ]
    )
    for key, value in result["embedding_cache"]["query_lanes"].items():
        lines.append(
            f"| {key[1:]} | {value['cache_off_mean_ms']:.2f} ms | "
            f"{value['cold_population_mean_ms']:.2f} ms | "
            f"{value['warm_hit_mean_ms']:.2f} ms | {value['mean_speedup']:.2f}x |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--triad", required=True, type=Path)
    parser.add_argument("--screen", required=True, type=Path)
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-markdown", required=True, type=Path)
    args = parser.parse_args()
    if args.output_json.exists() or args.output_markdown.exists():
        raise FileExistsError("refusing to overwrite analysis output")
    result = analyze(args.triad.resolve(), args.screen.resolve())
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    args.output_markdown.write_text(markdown(result), encoding="utf-8")


if __name__ == "__main__":
    main()
