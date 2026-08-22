#!/usr/bin/env python3
"""Build the common-segment four-way networking RAG comparison."""

from __future__ import annotations

import argparse
import json
import random
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from run_networking_anythingllm import percentile, ranking_metrics


def segment_id(book_id: str, page: int, pages_per_segment: int = 20) -> str:
    start = ((page - 1) // pages_per_segment) * pages_per_segment + 1
    return f"{book_id}-pages-{start:04d}-{start + pages_per_segment - 1:04d}"


def evidence_to_segment(evidence_id: str) -> str:
    book_id, raw_page = evidence_id.rsplit(":", 1)
    return segment_id(book_id, int(raw_page))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def qrels_map(path: Path) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for row in _jsonl(path):
        if float(row.get("relevance", 0)) > 0:
            result[str(row["query_id"])].add(str(row["doc_id"]))
    return dict(result)


def ragz_records(
    run_roots: list[Path], mode: str, qrels: dict[str, set[str]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for root in run_roots:
        order = json.loads((root / "manifest.json").read_text())["condition_order"]
        for raw in _jsonl(root / mode / "per_query.jsonl"):
            retrieved = list(
                dict.fromkeys(
                    evidence_to_segment(str(item["evidence_id"]))
                    for item in raw["retrieved"]
                )
            )[:5]
            answerable = bool(raw["answerable"])
            error = raw["error"]
            rows.append(
                {
                    "query_id": str(raw["query_id"]),
                    "answerable": answerable,
                    "no_answer": bool(raw["no_answer"]),
                    "retrieved": retrieved,
                    "metrics": (
                        ranking_metrics(retrieved, qrels[str(raw["query_id"])], 5)
                        if answerable and error is None
                        else None
                    ),
                    "latency_ms": float(raw["elapsed_ms"]),
                    "error": error,
                    "condition_order": order,
                }
            )
    return rows


def aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_query: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        by_query[str(row["query_id"])].append(row)
    per_query: dict[str, dict[str, float]] = {}
    for query_id, rows in by_query.items():
        quality = [
            row
            for row in rows
            if row["answerable"] and row["error"] is None and row["metrics"] is not None
        ]
        if quality:
            per_query[query_id] = {
                metric: statistics.mean(float(row["metrics"][metric]) for row in quality)
                for metric in ("recall_at_k", "mrr_at_k", "ndcg_at_k")
            }
            per_query[query_id]["hit_at_k"] = statistics.mean(
                float(bool(row["metrics"]["recall_at_k"])) for row in quality
            )
    successful = [row for row in records if row["error"] is None]
    tp = sum(not row["answerable"] and row["no_answer"] for row in successful)
    fp = sum(row["answerable"] and row["no_answer"] for row in successful)
    fn = sum(not row["answerable"] and not row["no_answer"] for row in successful)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    latencies = [float(row["latency_ms"]) for row in successful]
    return {
        "query_count": len(by_query),
        "observations": len(records),
        "answerable_query_count": len(per_query),
        "errors": sum(row["error"] is not None for row in records),
        "recall_at_5": statistics.mean(row["recall_at_k"] for row in per_query.values())
        if per_query
        else None,
        "mrr_at_5": statistics.mean(row["mrr_at_k"] for row in per_query.values())
        if per_query
        else None,
        "ndcg_at_5": statistics.mean(row["ndcg_at_k"] for row in per_query.values())
        if per_query
        else None,
        "segment_hit_at_5": statistics.mean(row["hit_at_k"] for row in per_query.values())
        if per_query
        else None,
        "abstention": {"precision": precision, "recall": recall, "f1": f1},
        "latency_ms": {
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "p99": percentile(latencies, 0.99),
        },
        "per_query": per_query,
    }


def paired_bootstrap(
    single: dict[str, Any], multi: dict[str, Any], *, seed: int = 42, samples: int = 10_000
) -> dict[str, Any]:
    common = sorted(set(single["per_query"]) & set(multi["per_query"]))
    rng = random.Random(seed)  # noqa: S311 - deterministic statistical resampling
    output: dict[str, Any] = {"query_count": len(common), "samples": samples, "seed": seed}
    for metric in ("recall_at_k", "mrr_at_k", "ndcg_at_k"):
        deltas = [
            float(multi["per_query"][query_id][metric])
            - float(single["per_query"][query_id][metric])
            for query_id in common
        ]
        means = sorted(
            statistics.mean(rng.choice(deltas) for _ in deltas) for _ in range(samples)
        )
        output[metric] = {
            "mean_delta": statistics.mean(deltas),
            "ci95": [means[int(samples * 0.025)], means[int(samples * 0.975) - 1]],
        }
    return output


def _fmt(value: object, digits: int = 4) -> str:
    return f"{float(value):.{digits}f}" if isinstance(value, (int, float)) else "unavailable"


def build(args: argparse.Namespace) -> dict[str, Any]:
    qrels = qrels_map(args.qrels)
    single = aggregate(ragz_records(args.ragz_run, "single", qrels))
    multi = aggregate(ragz_records(args.ragz_run, "multi", qrels))
    anything_manifest = json.loads((args.anythingllm / "manifest.json").read_text())
    anything = (
        aggregate(_jsonl(args.anythingllm / "per_query.jsonl"))
        if anything_manifest["status"] == "completed"
        else None
    )
    onyx_manifest = json.loads((args.onyx / "manifest.json").read_text())
    return {
        "schema_version": 1,
        "dataset": {
            "id": "networking-pdfs-v1",
            "pages": 2582,
            "segments": 131,
            "queries": 15,
            "answerable": 12,
            "off_corpus": 3,
            "evidence_unit": "20-physical-PDF-page interval",
        },
        "systems": {
            "ragz_single": {
                "status": "completed",
                "track": "hash-dense+bm25+qdrant-rrf-single-query",
                "metrics": single,
            },
            "ragz_multi": {
                "status": "completed",
                "track": "hash-dense+bm25+qdrant-rrf-fixed-three-query",
                "metrics": multi,
            },
            "anythingllm": {
                "status": anything_manifest["status"],
                "track": anything_manifest["track"],
                "metrics": anything,
                "container_limits": anything_manifest["container_limits"],
            },
            "onyx": {
                "status": onyx_manifest["status"],
                "track": onyx_manifest["track"],
                "metrics": None,
                "resource_evidence": onyx_manifest["resource_evidence"],
            },
        },
        "ragz_multi_minus_single": paired_bootstrap(single, multi),
    }


def markdown(result: dict[str, Any]) -> str:
    systems = result["systems"]
    rows = []
    for key, label in (
        ("anythingllm", "AnythingLLM v1.16.0"),
        ("ragz_single", "RAGZ single-query"),
        ("ragz_multi", "RAGZ multi-query"),
        ("onyx", "Onyx v4.6.0 Standard"),
    ):
        system = systems[key]
        metrics = system["metrics"]
        rows.append(
            "| "
            + " | ".join(
                [
                    label,
                    str(system["status"]),
                    _fmt(metrics["recall_at_5"] if metrics else None),
                    _fmt(metrics["mrr_at_5"] if metrics else None),
                    _fmt(metrics["ndcg_at_5"] if metrics else None),
                    _fmt(metrics["segment_hit_at_5"] if metrics else None),
                    _fmt(metrics["abstention"]["f1"] if metrics else None),
                    _fmt(metrics["latency_ms"]["p50"] if metrics else None, 2),
                    _fmt(metrics["latency_ms"]["p95"] if metrics else None, 2),
                ]
            )
            + " |"
        )
    return (
        "# Four-way networking RAG retrieval comparison\n\n"
        "Primary evidence unit: unique 20-physical-PDF-page interval. Quality "
        "uses 12 answerable queries; abstention uses all 15 successful queries.\n\n"
        "| System | Status | Recall@5 | MRR@5 | nDCG@5 | Segment hit@5 | "
        "Abstention F1 | p50 ms | p95 ms |\n"
        "|---|---|---:|---:|---:|---:|---:|---:|---:|\n"
        + "\n".join(rows)
        + "\n\n"
        "RAGZ multi-query uses two fixed alternatives, not live expansion. "
        "AnythingLLM uses native MiniLM/LanceDB over the common text segments. "
        "Onyx receives no numeric score when its official Standard resource floor is unmet.\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ragz-run", action="append", required=True, type=Path)
    parser.add_argument("--anythingllm", required=True, type=Path)
    parser.add_argument("--onyx", required=True, type=Path)
    parser.add_argument("--qrels", required=True, type=Path)
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-md", required=True, type=Path)
    args = parser.parse_args()
    for output in (args.output_json, args.output_md):
        if output.exists():
            raise FileExistsError(f"refusing to overwrite {output}")
    result = build(args)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(markdown(result), encoding="utf-8")


if __name__ == "__main__":
    main()
