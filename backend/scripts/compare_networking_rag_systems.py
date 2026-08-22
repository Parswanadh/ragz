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
        else 0.0 if tp + fp + fn else None
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
    ragz_manifests = [
        json.loads((run_root / "manifest.json").read_text()) for run_root in args.ragz_run
    ]
    single = aggregate(ragz_records(args.ragz_run, "single", qrels))
    multi = aggregate(ragz_records(args.ragz_run, "multi", qrels))
    anything_manifest = json.loads((args.anythingllm / "manifest.json").read_text())
    anything_summary = json.loads((args.anythingllm / "summary.json").read_text())
    anything_native_manifest = json.loads(
        (args.anythingllm_native_failure / "manifest.json").read_text()
    )
    anything_native_failure = json.loads(
        (args.anythingllm_native_failure / "failure.json").read_text()
    )
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
                "native_candidate_depth": ragz_manifests[0]["top_k"],
                "abstention_policy": ragz_manifests[0]["no_answer_threshold"],
            },
            "ragz_multi": {
                "status": "completed",
                "track": "hash-dense+bm25+qdrant-rrf-fixed-three-query",
                "metrics": multi,
                "native_candidate_depth": ragz_manifests[0]["top_k"],
                "abstention_policy": ragz_manifests[0]["no_answer_threshold"],
            },
            "anythingllm": {
                "status": anything_manifest["status"],
                "track": anything_manifest["track"],
                "metrics": anything,
                "container_limits": anything_manifest["container_limits"],
                "indexing_ms": anything_summary.get("indexing_ms"),
                "peak_container_memory_bytes": anything_summary.get(
                    "peak_container_memory_bytes"
                ),
                "provider_calls": anything_manifest.get("provider_calls"),
                "hosted_cost_usd": anything_manifest.get("hosted_cost_usd"),
                "native_candidate_depth": anything_manifest.get(
                    "native_candidate_depth"
                ),
                "abstention_policy": anything_manifest.get("abstention_policy"),
            },
            "anythingllm_native_minilm": {
                "status": anything_native_manifest["status"],
                "track": anything_native_manifest["track"],
                "metrics": None,
                "container_limits": anything_native_manifest["container_limits"],
                "failure": anything_native_failure,
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
        ("anythingllm", "AnythingLLM OpenAI + LanceDB"),
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
                    _fmt(metrics["latency_ms"]["p50"] if metrics else None, 2),
                    _fmt(metrics["latency_ms"]["p95"] if metrics else None, 2),
                ]
            )
            + " |"
        )
    anything = systems["anythingllm"]
    native_failure = systems["anythingllm_native_minilm"]
    onyx = systems["onyx"]
    ragz_delta = result["ragz_multi_minus_single"]
    return (
        "# Four-way networking RAG retrieval comparison\n\n"
        "Date: 2026-08-22\n\n"
        "Primary evidence unit: unique 20-physical-PDF-page interval. Quality "
        "uses 12 answerable queries; abstention uses all 15 successful queries.\n\n"
        "| System | Status | Recall@5 | MRR@5 | nDCG@5 | Segment hit@5 | "
        "p50 ms | p95 ms |\n"
        "|---|---|---:|---:|---:|---:|---:|---:|\n"
        + "\n".join(rows)
        + "\n\n"
        "## Configuration and eligibility\n\n"
        "| Variant | Retrieval configuration | Resource/result |\n"
        "|---|---|---|\n"
        "| AnythingLLM numeric | Native raw-text collector/chunker → "
        "OpenAI `text-embedding-3-small` → LanceDB | "
        f"2 CPU / 2 GiB; indexing {_fmt(anything['indexing_ms'], 2)} ms; "
        f"peak {_fmt(anything['peak_container_memory_bytes'], 0)} bytes |\n"
        "| AnythingLLM native MiniLM | Native raw-text collector/chunker → "
        "MiniLM → LanceDB | "
        f"`{native_failure['status']}` at `{native_failure['failure']['stage']}`; "
        f"OOM flag `{native_failure['failure']['container_state']['oom_killed']}` |\n"
        "| RAGZ single | Hash dense + BM25 → Qdrant RRF; one query | Completed |\n"
        "| RAGZ multi | Same index; original + two fixed alternatives → Qdrant RRF | "
        "Completed |\n"
        "| Onyx Standard | Native vector/keyword search | "
        f"`{onyx['status']}`: Docker RAM "
        f"{onyx['resource_evidence']['measured']['memory_bytes']} / required "
        f"{onyx['resource_evidence']['required']['memory_bytes']} bytes |\n\n"
        "## Abstention observations—not cross-system comparable\n\n"
        "| Variant | Decision rule | Calibrated here? | Observed F1 |\n"
        "|---|---|---|---:|\n"
        "| AnythingLLM | Empty result only; similarity/score threshold `0.0` | No | "
        f"{_fmt(anything['metrics']['abstention']['f1'])} |\n"
        "| RAGZ single | Maximum dense cosine `< 0.42` | Development sweep, not held out | "
        f"{_fmt(systems['ragz_single']['metrics']['abstention']['f1'])} |\n"
        "| RAGZ multi | Maximum variant dense cosine `< 0.42` | Development sweep, not held out | "
        f"{_fmt(systems['ragz_multi']['metrics']['abstention']['f1'])} |\n"
        "| Onyx | Unavailable—system not started | No | unavailable |\n\n"
        "These values describe each configured product policy and must not be ranked as a "
        "fair abstention leaderboard.\n\n"
        "## RAGZ paired effect\n\n"
        "| Delta | Mean | 95% query-bootstrap CI |\n"
        "|---|---:|---:|\n"
        f"| Recall@5 | {_fmt(ragz_delta['recall_at_k']['mean_delta'])} | "
        f"{_fmt(ragz_delta['recall_at_k']['ci95'][0])} to "
        f"{_fmt(ragz_delta['recall_at_k']['ci95'][1])} |\n"
        f"| MRR@5 | {_fmt(ragz_delta['mrr_at_k']['mean_delta'])} | "
        f"{_fmt(ragz_delta['mrr_at_k']['ci95'][0])} to "
        f"{_fmt(ragz_delta['mrr_at_k']['ci95'][1])} |\n"
        f"| nDCG@5 | {_fmt(ragz_delta['ndcg_at_k']['mean_delta'])} | "
        f"{_fmt(ragz_delta['ndcg_at_k']['ci95'][0])} to "
        f"{_fmt(ragz_delta['ndcg_at_k']['ci95'][1])} |\n\n"
        "## Interpretation limits\n\n"
        "- RAGZ multi-query uses two fixed alternatives, not live expansion.\n"
        "- AnythingLLM and RAGZ use different embedders/chunkers; this is a common-locator "
        "product comparison, not a controlled model ablation.\n"
        "- AnythingLLM provider call/token counts and hosted embedding cost are not exposed "
        "by the pinned public API, so cost is unavailable rather than zero.\n"
        "- Onyx receives no numeric score because its official Standard memory floor is unmet. "
        "Onyx Lite is not substituted because it omits the RAG index/workers.\n"
        "- Exact page quality remains available only for RAGZ. A 20-page interval hit cannot "
        "be presented as an exact-page citation.\n"
        "- Answer-quality comparison is unavailable: the query set has relevance pages but no "
        "reference-answer/atomic-claim rubric.\n"
        "- p99 is descriptive because these cells have fewer than 100 observations per "
        "AnythingLLM condition.\n\n"
        "- The historical AnythingLLM MiniLM OOM attempt used the pinned local v1.16.0 "
        "tag, but that runner did not enforce the digest at `docker run`; the successful "
        "numeric rerun executes the digest-qualified image reference.\n\n"
        "Official Onyx resource guidance: "
        "<https://docs.onyx.app/deployment/getting_started/resourcing>\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ragz-run", action="append", required=True, type=Path)
    parser.add_argument("--anythingllm", required=True, type=Path)
    parser.add_argument("--anythingllm-native-failure", required=True, type=Path)
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
