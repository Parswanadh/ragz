#!/usr/bin/env python3
"""Aggregate two counterbalanced RAGZ atomic networking latency runs."""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

from run_embedding_endpoint_probe import summarize as summarize_endpoint_probe
from run_multi_query_benchmark import percentile


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def aggregate_mode(run_roots: list[Path], mode: str) -> dict[str, Any]:
    records = [row for root in run_roots for row in _jsonl(root / mode / "per_query.jsonl")]
    if not records or any(record["error"] is not None for record in records):
        raise ValueError(f"{mode} requires nonempty zero-error observations")
    stage_sets = [set(record.get("stage_timings_ms") or {}) for record in records]
    if not stage_sets[0] or any(stages != stage_sets[0] for stages in stage_sets[1:]):
        raise ValueError(f"{mode} atomic stage schema is missing or inconsistent")
    if any(
        abs(
            sum(float(value) for value in record["stage_timings_ms"].values())
            - float(record["elapsed_ms"])
        )
        > 0.05
        for record in records
    ):
        raise ValueError(f"{mode} atomic stages do not close to elapsed_ms")
    totals = [float(record["elapsed_ms"]) for record in records]
    mean_total = statistics.mean(totals)
    stages: dict[str, Any] = {}
    for stage in sorted(stage_sets[0]):
        values = [float(record["stage_timings_ms"][stage]) for record in records]
        mean = statistics.mean(values)
        stages[stage] = {
            "observations": len(values),
            "mean_ms": mean,
            "p50_ms": percentile(values, 0.50),
            "p95_ms": percentile(values, 0.95),
            "mean_total_share": mean / mean_total,
        }
    dense_mean = float(stages["dense_embedding"]["mean_ms"])
    return {
        "observations": len(records),
        "query_count": len({str(record["query_id"]) for record in records}),
        "mean_ms": mean_total,
        "p50_ms": percentile(totals, 0.50),
        "p95_ms": percentile(totals, 0.95),
        "p99_ms": percentile(totals, 0.99),
        "mean_without_dense_embedding_ms": mean_total - dense_mean,
        "stages": stages,
    }


def manifest_identity(manifest: dict[str, Any]) -> dict[str, Any]:
    """Fields that must be identical before two order runs may be pooled."""
    return {
        "dataset_id": manifest["dataset_id"],
        "query_set": manifest["query_set"],
        "pdfs": manifest["pdfs"],
        "top_k": manifest["top_k"],
        "warmups": manifest["warmups"],
        "repetitions": manifest["repetitions"],
        "embedding_model": manifest["embedding_model"],
        "embedding_dimension": manifest["embedding_dimension"],
        "embedding_provider": manifest["embedding_provider"],
        "embedding_transport": manifest["embedding_transport"],
        "embedding_proxy_fingerprint_sha256": manifest[
            "embedding_proxy_fingerprint_sha256"
        ],
        "dense": manifest["dense"],
        "sparse": manifest["sparse"],
        "fusion": manifest["fusion"],
        "reranker": manifest["reranker"],
        "query_variants": manifest["query_variants"],
        "no_answer_threshold": manifest["no_answer_threshold"],
        "stage_timing_schema": manifest["stage_timing_schema"],
    }


def validate_run_records(
    root: Path,
    *,
    mode: str,
    expected_query_count: int,
    repetitions: int,
) -> None:
    records = _jsonl(root / mode / "per_query.jsonl")
    if len(records) != expected_query_count * repetitions:
        raise ValueError(f"{root.name}/{mode} has an incomplete observation denominator")
    keys = [(str(record["query_id"]), int(record["repetition"])) for record in records]
    query_ids = {query_id for query_id, _ in keys}
    if len(query_ids) != expected_query_count or len(set(keys)) != len(keys):
        raise ValueError(f"{root.name}/{mode} has missing or duplicate query repetitions")
    expected_keys = {
        (query_id, repetition)
        for query_id in query_ids
        for repetition in range(1, repetitions + 1)
    }
    if set(keys) != expected_keys:
        raise ValueError(f"{root.name}/{mode} query repetition grid is incomplete")
    expected_query_variants = 3 if mode == "multi" else 1
    if any(int(record["expansion_count"]) != expected_query_variants for record in records):
        raise ValueError(f"{root.name}/{mode} has an unexpected effective query count")
    if any(record["error"] is not None for record in records):
        raise ValueError(f"{root.name}/{mode} contains an error")


def load_endpoint_probe(root: Path) -> dict[str, Any]:
    manifest = json.loads((root / "manifest.json").read_text())
    records = _jsonl(root / "per_request.jsonl")
    persisted = json.loads((root / "summary.json").read_text())
    if manifest["status"] != "completed" or manifest["git_dirty"]:
        raise ValueError("endpoint probe must be completed from a clean worktree")
    recomputed = summarize_endpoint_probe(
        records, repetitions=int(manifest["scored_repetitions_per_condition"])
    )
    if recomputed != persisted:
        raise ValueError("endpoint probe summary does not recompute from raw rows")
    import hashlib

    if manifest["per_request_sha256"] != hashlib.sha256(
        (root / "per_request.jsonl").read_bytes()
    ).hexdigest():
        raise ValueError("endpoint probe per-request hash does not match")
    return {"manifest": manifest, **recomputed}


def aggregate_historical_mode(run_roots: list[Path], mode: str) -> dict[str, Any]:
    records = [row for root in run_roots for row in _jsonl(root / mode / "per_query.jsonl")]
    if not records or any(record["error"] is not None for record in records):
        raise ValueError(f"historical {mode} requires nonempty zero-error observations")
    values = [float(record["elapsed_ms"]) for record in records]
    return {
        "observations": len(values),
        "mean_ms": statistics.mean(values),
        "p50_ms": percentile(values, 0.50),
        "p95_ms": percentile(values, 0.95),
    }


def build(
    *,
    run_roots: list[Path],
    historical_run_roots: list[Path],
    endpoint_probe: dict[str, Any],
) -> dict[str, Any]:
    if len(run_roots) != 2:
        raise ValueError("exactly two counterbalanced RAGZ runs are required")
    manifests = [json.loads((root / "manifest.json").read_text()) for root in run_roots]
    orders = {str(manifest["condition_order"]) for manifest in manifests}
    commits = {str(manifest["git_commit"]) for manifest in manifests}
    identities = [manifest_identity(manifest) for manifest in manifests]
    if orders != {"single-first", "multi-first"}:
        raise ValueError("atomic runs are not counterbalanced")
    if len(commits) != 1 or identities[1] != identities[0]:
        raise ValueError("atomic runs do not share one clean implementation/configuration")
    if any(manifest["status"] != "completed" or manifest["git_dirty"] for manifest in manifests):
        raise ValueError("atomic runs must be completed from a clean worktree")

    identity = identities[0]
    query_count = int(identity["query_set"]["count"])
    repetitions = int(identity["repetitions"])
    for root in run_roots:
        for mode in ("single", "multi"):
            validate_run_records(
                root,
                mode=mode,
                expected_query_count=query_count,
                repetitions=repetitions,
            )
    single = aggregate_mode(run_roots, "single")
    multi = aggregate_mode(run_roots, "multi")
    stage_deltas = {
        stage: float(multi["stages"][stage]["mean_ms"])
        - float(single["stages"][stage]["mean_ms"])
        for stage in single["stages"]
    }
    total_delta = float(multi["mean_ms"]) - float(single["mean_ms"])
    dense_delta = stage_deltas["dense_embedding"]
    if len(historical_run_roots) != 2:
        raise ValueError("exactly two historical hash runs are required")
    historical_manifests = [
        json.loads((root / "manifest.json").read_text()) for root in historical_run_roots
    ]
    historical_fields = (
        "dataset_id",
        "query_set",
        "pdfs",
        "top_k",
        "warmups",
        "repetitions",
        "dense",
        "sparse",
        "fusion",
        "reranker",
        "query_variants",
        "no_answer_threshold",
    )
    historical_identity = {
        field: historical_manifests[0][field] for field in historical_fields
    }
    if any(
        {field: manifest[field] for field in historical_fields} != historical_identity
        for manifest in historical_manifests[1:]
    ):
        raise ValueError("historical hash runs do not share one configuration")
    historical_query_count = int(historical_identity["query_set"]["count"])
    historical_repetitions = int(historical_identity["repetitions"])
    for root in historical_run_roots:
        for mode in ("single", "multi"):
            validate_run_records(
                root,
                mode=mode,
                expected_query_count=historical_query_count,
                repetitions=historical_repetitions,
            )
    historical_single = aggregate_historical_mode(historical_run_roots, "single")
    historical_multi = aggregate_historical_mode(historical_run_roots, "multi")
    endpoint_manifest = endpoint_probe["manifest"]
    if (
        endpoint_manifest["model"] != identity["embedding_model"]
        or int(endpoint_manifest["dimension"]) != int(identity["embedding_dimension"])
        or endpoint_manifest["embedding_proxy_fingerprint_sha256"]
        != identity["embedding_proxy_fingerprint_sha256"]
    ):
        raise ValueError("endpoint probe does not match the RAGZ embedding identity")
    return {
        "schema_version": 1,
        "dataset_id": identity["dataset_id"],
        "corpus_identity": {
            "query_set": identity["query_set"],
            "pdfs": identity["pdfs"],
        },
        "source_runs": [root.name for root in run_roots],
        "configuration": {
            "git_commit": next(iter(commits)),
            "embedding_model": identity["embedding_model"],
            "embedding_dimension": identity["embedding_dimension"],
            "embedding_provider": identity["embedding_provider"],
            "embedding_transport": identity["embedding_transport"],
            "embedding_proxy_fingerprint_sha256": identity[
                "embedding_proxy_fingerprint_sha256"
            ],
            "dense": identity["dense"],
            "sparse": identity["sparse"],
            "fusion": identity["fusion"],
            "reranker": identity["reranker"],
            "top_k": identity["top_k"],
            "no_answer_threshold": identity["no_answer_threshold"],
            "timing_schema": identity["stage_timing_schema"]["version"],
            "query_variants": identity["query_variants"],
            "warmups_per_query_per_order": identity["warmups"],
            "warmups_per_mode_per_order": int(identity["warmups"]) * query_count,
            "scored_repetitions_per_query_per_order": repetitions,
        },
        "modes": {"single": single, "multi": multi},
        "multi_minus_single": {
            "mean_total_ms": total_delta,
            "stage_mean_ms": stage_deltas,
            "dense_embedding_share_of_total_delta": dense_delta / total_delta,
        },
        "historical_hash_baseline": {
            "source_runs": [root.name for root in historical_run_roots],
            "single": historical_single,
            "multi": historical_multi,
            "dense_embedding": historical_identity["dense"],
            "residual_vs_hash_mean": {
                "single_relative_increase": (
                    float(single["mean_without_dense_embedding_ms"])
                    / float(historical_single["mean_ms"])
                    - 1
                ),
                "multi_relative_increase": (
                    float(multi["mean_without_dense_embedding_ms"])
                    / float(historical_multi["mean_ms"])
                    - 1
                ),
            },
        },
        "embedding_endpoint_probe": endpoint_probe,
        "agno_boundary": {
            "participates_in_ragz_measurement": False,
            "repository": "Parswanadh/Rag_agno",
            "reason": "separate application, database, Qdrant, model and benchmark runner",
            "evidence_scope": "architecture boundary only; no AGNO latency row",
        },
    }


def _fmt(value: Any, digits: int = 2) -> str:
    return f"{float(value):.{digits}f}"


def markdown(result: dict[str, Any]) -> str:
    single = result["modes"]["single"]
    multi = result["modes"]["multi"]
    deltas = result["multi_minus_single"]
    stages = sorted(
        single["stages"],
        key=lambda stage: float(single["stages"][stage]["mean_ms"])
        + float(multi["stages"][stage]["mean_ms"]),
        reverse=True,
    )
    stage_rows = "\n".join(
        f"| `{stage}` | {_fmt(single['stages'][stage]['mean_ms'])} | "
        f"{_fmt(multi['stages'][stage]['mean_ms'])} | "
        f"{_fmt(deltas['stage_mean_ms'][stage])} | "
        f"{_fmt(float(multi['stages'][stage]['mean_total_share']) * 100, 1)}% |"
        for stage in stages
    )
    probe = result["embedding_endpoint_probe"]["conditions"]
    probe_rows = "\n".join(
        f"| {label} | {_fmt(values['mean_ms'])} | {_fmt(values['p50_ms'])} | "
        f"{_fmt(values['p95_ms'])} |"
        for label, values in (
            ("Direct OpenAI · 1 input", probe["direct_1"]),
            ("LiteLLM → OpenAI · 1 input", probe["proxy_1"]),
            ("Direct OpenAI · 3 inputs", probe["direct_3"]),
            ("LiteLLM → OpenAI · 3 inputs", probe["proxy_3"]),
        )
    )
    old = result["historical_hash_baseline"]
    return (
        "# RAGZ atomic retrieval latency analysis\n\n"
        "Date: 2026-08-23\n\n"
        "## Verdict\n\n"
        f"- Single-query mean/p50/p95: `{_fmt(single['mean_ms'])}` / "
        f"`{_fmt(single['p50_ms'])}` / `{_fmt(single['p95_ms'])}` ms.\n"
        f"- Multi-query mean/p50/p95: `{_fmt(multi['mean_ms'])}` / "
        f"`{_fmt(multi['p50_ms'])}` / `{_fmt(multi['p95_ms'])}` ms.\n"
        f"- Dense OpenAI embedding accounts for "
        f"`{_fmt(float(single['stages']['dense_embedding']['mean_total_share']) * 100, 1)}%` "
        "of single and "
        f"`{_fmt(float(multi['stages']['dense_embedding']['mean_total_share']) * 100, 1)}%` "
        "of multi mean latency.\n"
        "- Removing dense-provider time leaves "
        f"`{_fmt(single['mean_without_dense_embedding_ms'])}` "
        f"ms single and `{_fmt(multi['mean_without_dense_embedding_ms'])}` ms multi—the "
        "same tens-of-milliseconds range as the hash track, but about 25% higher.\n"
        f"- Multi adds `{_fmt(deltas['mean_total_ms'])}` ms mean latency; dense embedding "
        f"explains `{_fmt(float(deltas['dense_embedding_share_of_total_delta']) * 100, 1)}%` "
        "of that delta.\n\n"
        "## Atomic stage means\n\n"
        "| Stage | Single ms | Multi ms | Delta ms | Multi share |\n"
        "|---|---:|---:|---:|---:|\n"
        + stage_rows
        + "\n\n"
        "## Embedding endpoint probe\n\n"
        "Synthetic content, two warmups and ten scored repetitions per condition; "
        "a new HTTP client was created per request to match the RAGZ embedder lifecycle.\n\n"
        "| Path | Mean ms | p50 ms | p95 ms |\n"
        "|---|---:|---:|---:|\n"
        + probe_rows
        + "\n\n"
        "The LiteLLM and direct paths differed by "
        f"`{_fmt(abs(float(probe['proxy_1']['mean_ms']) - float(probe['direct_1']['mean_ms'])))}` "
        "ms for one input and "
        f"`{_fmt(abs(float(probe['proxy_3']['mean_ms']) - float(probe['direct_3']['mean_ms'])))}` "
        "ms for three inputs in this small diagnostic. Both paths remained hundreds "
        "of milliseconds; the provider/network path dominates, and these unpaired samples "
        "do not prove a fixed proxy speedup or penalty.\n\n"
        "## Why the earlier report showed about 50 ms\n\n"
        f"The historical baseline used `{old['dense_embedding']}` with no provider call: "
        f"single mean/p50/p95 `{_fmt(old['single']['mean_ms'])}` / "
        f"`{_fmt(old['single']['p50_ms'])}` / `{_fmt(old['single']['p95_ms'])}` ms; "
        f"multi `{_fmt(old['multi']['mean_ms'])}` / `{_fmt(old['multi']['p50_ms'])}` / "
        f"`{_fmt(old['multi']['p95_ms'])}` ms. The OpenAI residuals are in the same "
        f"tens-of-milliseconds range but are "
        f"`{_fmt(float(old['residual_vs_hash_mean']['single_relative_increase']) * 100, 1)}%` "
        f"and `{_fmt(float(old['residual_vs_hash_mean']['multi_relative_increase']) * 100, 1)}%` "
        "higher than the hash means. They retain a different vector width/provider-backed "
        "index and are not a controlled hash counterfactual.\n\n"
        "## AGNO boundary\n\n"
        "AGNO does not participate in these measurements. `rag_agno` is a separate "
        "application with separate PostgreSQL/Qdrant instances and a separate benchmark. "
        "Its architecture has its own atomic timing contract, but no AGNO timing row is "
        "included here. A separately source-bound model/corpus/prompt lock is required before "
        "a cross-system latency score is valid.\n\n"
        "## Limits\n\n"
        "- Timings are wall clock, so they include async scheduling and network wait.\n"
        "- Fixed alternatives make query-expansion time effectively zero; live LLM expansion "
        "would add a separate generation call.\n"
        "- The endpoint probe has ten observations per condition and is diagnostic, not a "
        "provider SLA.\n"
        "- Repeated-query embedding caches were intentionally disabled.\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="append", required=True, type=Path)
    parser.add_argument("--historical-run", action="append", required=True, type=Path)
    parser.add_argument("--endpoint-probe", required=True, type=Path)
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-md", required=True, type=Path)
    args = parser.parse_args()
    for output in (args.output_json, args.output_md):
        if output.exists():
            raise FileExistsError(f"refusing to overwrite {output}")
    result = build(
        run_roots=args.run,
        historical_run_roots=args.historical_run,
        endpoint_probe=load_endpoint_probe(args.endpoint_probe),
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(markdown(result))


if __name__ == "__main__":
    main()
