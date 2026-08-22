#!/usr/bin/env python3
"""Build the common-segment four-way networking RAG comparison."""

from __future__ import annotations

import argparse
import hashlib
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


def common_ragz_configuration(manifests: list[dict[str, Any]]) -> dict[str, Any]:
    if not manifests:
        raise ValueError("at least one RAGZ manifest is required")
    fields = (
        "dense",
        "embedding_model",
        "embedding_dimension",
        "embedding_provider",
        "embedding_transport",
        "embedding_proxy_fingerprint_sha256",
        "sparse",
        "fusion",
        "reranker",
        "top_k",
    )
    first = {field: manifests[0].get(field) for field in fields}
    for manifest in manifests[1:]:
        current = {field: manifest.get(field) for field in fields}
        if current != first:
            raise ValueError("RAGZ source runs do not share one retrieval configuration")
    return first


def validate_complete_records(
    *,
    label: str,
    records: list[dict[str, Any]],
    expected_query_ids: set[str],
    answerable_query_ids: set[str],
    repetitions_per_query: int,
) -> dict[str, int]:
    if repetitions_per_query < 1:
        raise ValueError(f"{label} has no declared repetitions")
    counts: dict[str, int] = defaultdict(int)
    errors = 0
    for record in records:
        query_id = str(record["query_id"])
        counts[query_id] += 1
        errors += record.get("error") is not None
        expected_answerable = query_id in answerable_query_ids
        if bool(record.get("answerable")) != expected_answerable:
            raise ValueError(f"{label} has inconsistent answerable flag for {query_id}")
        if expected_answerable and record.get("metrics") is None:
            raise ValueError(f"{label} is missing quality metrics for {query_id}")
    if set(counts) != expected_query_ids:
        raise ValueError(f"{label} query IDs do not match the 15-query benchmark")
    wrong_counts = {
        query_id: count
        for query_id, count in counts.items()
        if count != repetitions_per_query
    }
    if wrong_counts:
        raise ValueError(f"{label} has incomplete or uneven repetitions: {wrong_counts}")
    if errors:
        raise ValueError(f"{label} has {errors} scored provider/retrieval errors")
    expected_observations = len(expected_query_ids) * repetitions_per_query
    if len(records) != expected_observations:
        raise ValueError(
            f"{label} has {len(records)} observations; expected {expected_observations}"
        )
    return {
        "query_count": len(expected_query_ids),
        "answerable_query_count": len(answerable_query_ids),
        "off_corpus_query_count": len(expected_query_ids - answerable_query_ids),
        "repetitions_per_query": repetitions_per_query,
        "observations": len(records),
        "errors": errors,
    }


def validate_embedding_parity(
    *,
    path: Path | None,
    ragz_config: dict[str, Any],
    ragz_runs: list[Path],
    anything_manifest: dict[str, Any],
    anything_manifest_path: Path,
    anything_run: Path,
) -> dict[str, Any]:
    if ragz_config.get("embedding_model") != "text-embedding-3-small":
        return {"validated": False, "reason": "RAGZ track is not OpenAI model parity"}
    if path is None:
        raise ValueError("OpenAI RAGZ comparison requires --embedding-parity-attestation")
    attestation = json.loads(path.read_text(encoding="utf-8"))
    if attestation.get("schema_version") != 1:
        raise ValueError("unsupported embedding parity attestation schema")
    expected_runs = {
        "anythingllm": anything_run.name,
        "ragz": [run.name for run in ragz_runs],
    }
    if attestation.get("source_runs") != expected_runs:
        raise ValueError("embedding parity attestation does not match source run IDs")
    expected_embedding = {
        "model": "text-embedding-3-small",
        "dimension": 1536,
        "provider": "openai",
        "transport": "litellm",
    }
    embedding = attestation.get("embedding") or {}
    if embedding.get("anythingllm") != expected_embedding:
        raise ValueError("AnythingLLM embedding attestation is not the parity model")
    if embedding.get("ragz") != expected_embedding:
        raise ValueError("RAGZ embedding attestation is not the parity model")
    for field, value in expected_embedding.items():
        if ragz_config.get(f"embedding_{field}") != value:
            raise ValueError(f"RAGZ manifests disagree with attested embedding {field}")
        if anything_manifest.get(f"embedding_{field}") != value:
            raise ValueError(
                f"AnythingLLM manifest disagrees with attested embedding {field}"
            )
    if anything_manifest.get("track") != "common-20-page-segments-openai-lancedb":
        raise ValueError("AnythingLLM source run is not the attested OpenAI track")
    proxy = attestation.get("shared_proxy") or {}
    fingerprint = str(proxy.get("instance_fingerprint_sha256") or "")
    if (
        proxy.get("used_by") != ["anythingllm", "ragz"]
        or len(fingerprint) != 64
        or any(character not in "0123456789abcdef" for character in fingerprint)
    ):
        raise ValueError("shared LiteLLM proxy identity is missing or malformed")
    if ragz_config.get("embedding_proxy_fingerprint_sha256") != fingerprint:
        raise ValueError("RAGZ manifests do not match the shared LiteLLM proxy")
    if anything_manifest.get("embedding_proxy_fingerprint_sha256") != fingerprint:
        raise ValueError("AnythingLLM manifest does not match the shared LiteLLM proxy")
    manifest_sha256 = hashlib.sha256(anything_manifest_path.read_bytes()).hexdigest()
    if (
        (attestation.get("source_artifacts") or {}).get(
            "anythingllm_manifest_sha256"
        )
        != manifest_sha256
    ):
        raise ValueError("attestation is not bound to the AnythingLLM manifest bytes")
    return {
        "validated": True,
        "model": expected_embedding["model"],
        "dimension": expected_embedding["dimension"],
        "provider": expected_embedding["provider"],
        "transport": expected_embedding["transport"],
        "proxy_instance_fingerprint_sha256": fingerprint,
        "attestation": path.name,
    }


def build(args: argparse.Namespace) -> dict[str, Any]:
    qrels = qrels_map(args.qrels)
    ragz_manifests = [
        json.loads((run_root / "manifest.json").read_text()) for run_root in args.ragz_run
    ]
    ragz_config = common_ragz_configuration(ragz_manifests)
    single_records = ragz_records(args.ragz_run, "single", qrels)
    multi_records = ragz_records(args.ragz_run, "multi", qrels)
    anything_manifest = json.loads((args.anythingllm / "manifest.json").read_text())
    embedding_parity = validate_embedding_parity(
        path=getattr(args, "embedding_parity_attestation", None),
        ragz_config=ragz_config,
        ragz_runs=args.ragz_run,
        anything_manifest=anything_manifest,
        anything_manifest_path=args.anythingllm / "manifest.json",
        anything_run=args.anythingllm,
    )
    anything_summary = json.loads((args.anythingllm / "summary.json").read_text())
    anything_native_manifest = json.loads(
        (args.anythingllm_native_failure / "manifest.json").read_text()
    )
    anything_native_failure = json.loads(
        (args.anythingllm_native_failure / "failure.json").read_text()
    )
    anything_records = (
        _jsonl(args.anythingllm / "per_query.jsonl")
        if anything_manifest["status"] == "completed"
        else []
    )
    expected_query_ids = {str(row["query_id"]) for row in anything_records}
    answerable_query_ids = set(qrels)
    if len(expected_query_ids) != 15 or len(answerable_query_ids) != 12:
        raise ValueError("comparison requires exactly 15 queries and 12 answerable qrels")
    ragz_repetitions = sum(int(manifest["repetitions"]) for manifest in ragz_manifests)
    anything_repetitions = int(anything_manifest["repetitions"])
    denominators = {
        "ragz_single": validate_complete_records(
            label="RAGZ single",
            records=single_records,
            expected_query_ids=expected_query_ids,
            answerable_query_ids=answerable_query_ids,
            repetitions_per_query=ragz_repetitions,
        ),
        "ragz_multi": validate_complete_records(
            label="RAGZ multi",
            records=multi_records,
            expected_query_ids=expected_query_ids,
            answerable_query_ids=answerable_query_ids,
            repetitions_per_query=ragz_repetitions,
        ),
        "anythingllm": validate_complete_records(
            label="AnythingLLM",
            records=anything_records,
            expected_query_ids=expected_query_ids,
            answerable_query_ids=answerable_query_ids,
            repetitions_per_query=anything_repetitions,
        ),
    }
    single = aggregate(single_records)
    multi = aggregate(multi_records)
    anything = aggregate(anything_records)
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
                "track": f"{ragz_config['dense']}+bm25+qdrant-rrf-single-query",
                "embedding": ragz_config,
                "metrics": single,
                "native_candidate_depth": ragz_manifests[0]["top_k"],
                "abstention_policy": ragz_manifests[0]["no_answer_threshold"],
            },
            "ragz_multi": {
                "status": "completed",
                "track": f"{ragz_config['dense']}+bm25+qdrant-rrf-fixed-three-query",
                "embedding": ragz_config,
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
        "embedding_parity": embedding_parity,
        "validated_denominators": denominators,
        "source_runs": {
            "ragz": [path.name for path in args.ragz_run],
            "anythingllm": args.anythingllm.name,
            "anythingllm_native_failure": args.anythingllm_native_failure.name,
            "onyx": args.onyx.name,
            "aggregate_artifact": args.output_json.name,
        },
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
    sources = result["source_runs"]
    ragz_embedding = systems["ragz_single"]["embedding"]
    ragz_embedding_label = (
        f"{ragz_embedding['embedding_model']} ({ragz_embedding['embedding_dimension']}d)"
        if ragz_embedding.get("embedding_model")
        else str(ragz_embedding["dense"])
    )
    same_embedding = bool(result["embedding_parity"]["validated"])
    embedding_limit = (
        "- AnythingLLM and RAGZ use the same embedder model, but retain their native "
        "chunkers and retrieval engines; this is a model-parity product comparison, "
        "not an embedding-only ablation.\n"
        if same_embedding
        else "- AnythingLLM and RAGZ use different embedders/chunkers; this is a "
        "common-locator product comparison, not a controlled model ablation.\n"
    )
    embedding_verdict = (
        "- AnythingLLM and RAGZ use the same OpenAI `text-embedding-3-small` model "
        "at 1,536 dimensions in this report.\n"
        if same_embedding
        else "- AnythingLLM uses OpenAI `text-embedding-3-small`; this RAGZ track uses "
        f"`{ragz_embedding['dense']}`.\n"
    )
    labels = {
        "anythingllm": "AnythingLLM",
        "ragz_single": "RAGZ single",
        "ragz_multi": "RAGZ multi",
    }
    leaders: list[str] = []
    for metric, name in (
        ("recall_at_5", "Recall@5"),
        ("mrr_at_5", "MRR@5"),
        ("ndcg_at_5", "nDCG@5"),
    ):
        eligible = [
            (key, systems[key]["metrics"][metric])
            for key in labels
            if systems[key]["metrics"] is not None
        ]
        winner, value = max(eligible, key=lambda item: item[1])
        leaders.append(f"{name}: {labels[winner]} ({_fmt(value)})")
    speed_eligible = [
        (key, systems[key]["metrics"]["latency_ms"]["p50"])
        for key in labels
        if systems[key]["metrics"] is not None
    ]
    speed_winner, speed_value = min(speed_eligible, key=lambda item: item[1])
    ragz_policy = systems["ragz_single"]["abstention_policy"]
    return (
        "# Four-way networking RAG retrieval comparison\n\n"
        "Date: 2026-08-22\n\n"
        "Primary evidence unit: unique 20-physical-PDF-page interval. Quality "
        "uses 12 answerable queries; abstention uses all 15 successful queries.\n\n"
        "## Executive verdict\n\n"
        f"{embedding_verdict}"
        f"- Quality leaders — {'; '.join(leaders)}.\n"
        f"- Median-latency leader: {labels[speed_winner]} ({_fmt(speed_value, 2)} ms).\n"
        "- The paired RAGZ multi-minus-single effect and query-bootstrap intervals are "
        "reported below without assuming the direction in advance.\n"
        "- AnythingLLM native MiniLM was OOM-killed during serialized indexing.\n"
        "- Onyx Standard was resource-gated before startup and receives no score.\n\n"
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
        f"| RAGZ single | {ragz_embedding_label} + BM25 → Qdrant RRF; one query | "
        "Completed |\n"
        "| RAGZ multi | Same embedding/index; original + two fixed alternatives → "
        "Qdrant RRF | "
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
        f"| RAGZ single | Maximum dense cosine `< {ragz_policy['value']}` | "
        f"{ragz_policy['calibration']} | "
        f"{_fmt(systems['ragz_single']['metrics']['abstention']['f1'])} |\n"
        f"| RAGZ multi | Maximum variant dense cosine `< {ragz_policy['value']}` | "
        f"{ragz_policy['calibration']} | "
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
        f"{embedding_limit}"
        "- AnythingLLM provider call/token counts and hosted embedding cost are not exposed "
        "by the pinned public API, so cost is unavailable rather than zero.\n"
        "- Onyx receives no numeric score because its official Standard memory floor is unmet. "
        "Onyx Lite is not substituted because it omits the RAG index/workers.\n"
        "- Exact page quality remains available only for RAGZ. A 20-page interval hit cannot "
        "be presented as an exact-page citation.\n"
        "- Answer-quality comparison is unavailable: the query set has relevance pages but no "
        "reference-answer/atomic-claim rubric.\n"
        "- p99 is descriptive because these cells have fewer than 100 observations per "
        "AnythingLLM condition.\n"
        "- The historical AnythingLLM MiniLM OOM attempt used the pinned local v1.16.0 "
        "tag, but that runner did not enforce the digest at `docker run`; the successful "
        "numeric rerun executes the digest-qualified image reference.\n\n"
        "Official Onyx resource guidance: "
        "<https://docs.onyx.app/deployment/getting_started/resourcing>\n\n"
        "## Evidence\n\n"
        f"- RAGZ source runs: `{sources['ragz'][0]}`, `{sources['ragz'][1]}`.\n"
        f"- AnythingLLM numeric run: `{sources['anythingllm']}`.\n"
        f"- AnythingLLM MiniLM failure: `{sources['anythingllm_native_failure']}`.\n"
        f"- Onyx preflight: `{sources['onyx']}`.\n"
        "- Privacy-safe raw copies: `docs/benchmarks/artifacts/raw/2026-08-22/`.\n"
        "- Machine-readable aggregate: "
        f"`docs/benchmarks/artifacts/{sources['aggregate_artifact']}`.\n\n"
        "Temporary extracted textbook text is local-only and must be deleted after "
        "the comparison is built; committed raw copies contain no textbook text.\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ragz-run", action="append", required=True, type=Path)
    parser.add_argument("--anythingllm", required=True, type=Path)
    parser.add_argument("--anythingllm-native-failure", required=True, type=Path)
    parser.add_argument("--onyx", required=True, type=Path)
    parser.add_argument("--qrels", required=True, type=Path)
    parser.add_argument("--embedding-parity-attestation", type=Path)
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
