#!/usr/bin/env python3
"""Compare RAGZ and AnythingLLM on common large-books 20-page intervals."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


class FollowupAnalysisError(RuntimeError):
    pass


def interval_id(book_id: str, page: int, pages_per_interval: int = 20) -> str:
    if page < 1 or pages_per_interval < 1:
        raise ValueError("page and interval width must be positive")
    start = ((page - 1) // pages_per_interval) * pages_per_interval + 1
    end = start + pages_per_interval - 1
    return f"{book_id}-pages-{start:04d}-{end:04d}"


def ranking_metrics(
    retrieved: Sequence[str], relevant: set[str], k: int = 5
) -> tuple[float, float, float]:
    ranked = list(dict.fromkeys(retrieved))[:k]
    hit_ranks = [rank for rank, item in enumerate(ranked, 1) if item in relevant]
    recall = len(set(ranked) & relevant) / len(relevant)
    mrr = 1 / hit_ranks[0] if hit_ranks else 0.0
    dcg = sum(1 / math.log2(rank + 1) for rank in hit_ranks)
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(k, len(relevant)) + 1))
    return recall, mrr, dcg / ideal


def _percentile(values: Sequence[float], quantile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise FollowupAnalysisError(f"{path.name} is not an object")
    return value


def _jsonl(path: Path) -> list[dict[str, Any]]:
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if any(not isinstance(row, dict) for row in rows):
        raise FollowupAnalysisError(f"{path.name} contains non-object rows")
    return rows


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _qrels(path: Path) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for row in _jsonl(path):
        if not row.get("answerable"):
            continue
        documents = row.get("expected_doc_ids")
        pages = row.get("evidence_pages")
        if not isinstance(documents, list) or len(documents) != 1 or not isinstance(pages, list):
            raise FollowupAnalysisError("query evidence contract differs")
        result[str(row["query_id"])] = {
            interval_id(str(documents[0]), int(page)) for page in pages
        }
    if len(result) != 20:
        raise FollowupAnalysisError("answerable query denominator is not 20")
    return result


def _ragz_cell(root: Path, qrels: Mapping[str, set[str]], query_count: int) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for order in ("forward", "reverse"):
        rows.extend(
            _jsonl(root / f"{order}_q{query_count}_rerank-off_cache-off" / "per_query.jsonl")
        )
    if len(rows) != 240 or any(row.get("error") is not None for row in rows):
        raise FollowupAnalysisError(f"RAGZ Q{query_count} denominator/errors differ")
    values: list[tuple[float, float, float]] = []
    for row in rows:
        if not row.get("answerable"):
            continue
        retrieved = []
        for item in row["retrieved"]:
            book, page = str(item["evidence_id"]).rsplit(":", 1)
            retrieved.append(interval_id(book, int(page)))
        values.append(ranking_metrics(retrieved, qrels[str(row["query_id"])]))
    latencies = [float(row["elapsed_ms"]) for row in rows]
    return {
        "query_count": query_count,
        "quality_observations": len(values),
        "recall_at_5": statistics.fmean(value[0] for value in values),
        "mrr_at_5": statistics.fmean(value[1] for value in values),
        "ndcg_at_5": statistics.fmean(value[2] for value in values),
        "latency_ms": {
            "mean": statistics.fmean(latencies),
            "p50": _percentile(latencies, 0.5),
            "p95": _percentile(latencies, 0.95),
        },
    }


def analyze(
    *,
    ragz: Path,
    anything: Path,
    queries: Path,
    ragflow: Path,
    onyx: Path,
) -> dict[str, Any]:
    ragz_manifest = _json(ragz / "manifest.json")
    anything_manifest = _json(anything / "manifest.json")
    anything_summary = _json(anything / "summary.json")
    if ragz_manifest.get("status") != "completed" or anything_manifest.get("status") != "completed":
        raise FollowupAnalysisError("a common-interval source run is incomplete")
    if (
        anything_manifest.get("indexed_vector_count", 0) < 222
        or anything_summary.get("errors") != 0
    ):
        raise FollowupAnalysisError("AnythingLLM vector/error gate failed")
    qrels = _qrels(queries)
    ragz_q1 = _ragz_cell(ragz, qrels, 1)
    ragz_q3 = _ragz_cell(ragz, qrels, 3)
    ragflow_summary = _json(ragflow)
    onyx_manifest = _json(onyx)
    return {
        "schema_version": 1,
        "status": "completed_with_boundaries",
        "dataset": {
            "source": "large-books-v1",
            "evaluation_unit": "20-page_interval",
            "queries": 24,
            "answerable": 20,
            "off_corpus": 4,
            "embedding": "text-embedding-3-large/1024",
            "top_k": 5,
        },
        "common_interval": {
            "ragz_q1": ragz_q1,
            "ragz_q3": ragz_q3,
            "anythingllm": {
                "quality_observations": anything_summary["quality_observations"],
                "recall_at_5": anything_summary["mean_recall_at_k"],
                "mrr_at_5": anything_summary["mean_mrr_at_k"],
                "ndcg_at_5": anything_summary["mean_ndcg_at_k"],
                "latency_ms": anything_summary["latency_ms"],
                "indexing_ms": anything_summary["indexing_ms"],
                "indexed_vector_count": anything_manifest["indexed_vector_count"],
                "peak_container_memory_bytes": anything_summary[
                    "peak_container_memory_bytes"
                ],
            },
        },
        "source_bound": {
            "ragflow": {
                "status": ragflow_summary.get("status"),
                "dataset": "open-manuals-v2",
                "recall_at_5": ragflow_summary["metrics"]["recall_at_5"]["mean"],
                "mrr_at_5": ragflow_summary["metrics"]["mrr_at_5"]["mean"],
                "ndcg_at_5": ragflow_summary["metrics"]["ndcg_at_5"]["mean"],
                "not_common_corpus": True,
            },
            "onyx": {
                "status": onyx_manifest.get("status"),
                "quality_score_emitted": onyx_manifest.get("quality_score_emitted"),
            },
        },
        "source_sha256": {
            "ragz_manifest": _sha256(ragz / "manifest.json"),
            "anythingllm_manifest": _sha256(anything / "manifest.json"),
            "anythingllm_rows": _sha256(anything / "per_query.jsonl"),
            "queries": _sha256(queries),
            "ragflow_summary": _sha256(ragflow),
            "onyx_manifest": _sha256(onyx),
        },
        "claim_boundaries": [
            "AnythingLLM indexes common intervals directly; RAGZ maps native "
            "chunks to intervals after retrieval.",
            "RAGFlow is source-bound to Open Manuals and is not in the "
            "common-corpus ranking.",
            "Onyx passed resource preflight but was not executed; no numeric score is emitted.",
        ],
    }


def markdown(result: Mapping[str, Any]) -> str:
    common = result["common_interval"]
    lines = [
        "# Large-books normalized open-source follow-up",
        "",
        "| System | Recall@5 | MRR@5 | nDCG@5 | p50 ms | p95 ms |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for label, key in (("RAGZ Q1", "ragz_q1"), ("RAGZ Q3", "ragz_q3")):
        row = common[key]
        lines.append(
            f"| {label} | {row['recall_at_5']:.4f} | {row['mrr_at_5']:.4f} | "
            f"{row['ndcg_at_5']:.4f} | {row['latency_ms']['p50']:.2f} | "
            f"{row['latency_ms']['p95']:.2f} |"
        )
    anything = common["anythingllm"]
    lines.append(
        f"| AnythingLLM | {anything['recall_at_5']:.4f} | "
        f"{anything['mrr_at_5']:.4f} | {anything['ndcg_at_5']:.4f} | "
        f"{anything['latency_ms']['p50']:.2f} | {anything['latency_ms']['p95']:.2f} |"
    )
    lines.extend(
        [
            "",
            "RAGFlow remains source-bound to Open Manuals; Onyx remains "
            "eligible-not-executed. Neither receives a common-corpus numeric row.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ragz", required=True, type=Path)
    parser.add_argument("--anythingllm", required=True, type=Path)
    parser.add_argument("--queries", required=True, type=Path)
    parser.add_argument("--ragflow-summary", required=True, type=Path)
    parser.add_argument("--onyx-manifest", required=True, type=Path)
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-markdown", required=True, type=Path)
    args = parser.parse_args()
    if args.output_json.exists() or args.output_markdown.exists():
        raise FileExistsError("refusing to overwrite follow-up analysis")
    result = analyze(
        ragz=args.ragz.resolve(),
        anything=args.anythingllm.resolve(),
        queries=args.queries.resolve(),
        ragflow=args.ragflow_summary.resolve(),
        onyx=args.onyx_manifest.resolve(),
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    args.output_markdown.write_text(markdown(result), encoding="utf-8")


if __name__ == "__main__":
    main()
