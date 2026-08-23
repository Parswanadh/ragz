#!/usr/bin/env python3
# ruff: noqa: E501
"""Analyze the source-bound clean large-1024 versus small-1024 pair.

This publication track is intentionally separate from the exploratory matrix:
it accepts exactly two complete, no-cache cells, validates their shared
generation/judge/cache contract, and reports only paired query statistics.
No provider is contacted by this module.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from analyze_open_manuals_matrix import (  # noqa: E402
    EXPECTED_DENOMINATOR,
    EXPECTED_EMBEDDING_CALLS,
    EXPECTED_GENERATION_CALLS,
    EXPECTED_JUDGE_CALLS,
    EXPECTED_PROVIDER_CALLS,
    EXPECTED_QUERY_IDS,
    MatrixAnalysisError,
    OutputExistsError,
    _cache_denominators,
    _cache_mode,
    _provider_cost,
    _required_float,
    _required_mapping,
    _validate_cell,
    bootstrap_ci,
    holm_correction,
    sign_flip_pvalue,
)

SCHEMA_VERSION = 1
LARGE_CELL_ID = "openai-text-embedding-3-large-d1024"
SMALL_CELL_ID = "openai-text-embedding-3-small-d1024"
BOOTSTRAP_SAMPLES = 10_000
SIGN_FLIP_SAMPLES = 100_000
PUBLICATION_GENERATION_MODEL = "gpt-5.6-luna"
PUBLICATION_JUDGE_MODEL = "gpt-5.4-mini"

# Seven judge dimensions plus seven normalized/citation/retrieval dimensions.
# Counts are retained only where the producer already defines a per-query
# count; they are not mistaken for section-level evidence.
QUALITY_METRICS: tuple[tuple[str, str, str], ...] = (
    ("judge", "context_relevance", "higher"),
    ("judge", "groundedness", "higher"),
    ("judge", "answer_relevance", "higher"),
    ("judge", "correctness", "higher"),
    ("judge", "citation_entailment", "higher"),
    ("judge", "citation_precision", "higher"),
    ("judge", "citation_completeness", "higher"),
    ("metrics", "abstention_correct", "higher"),
    ("metrics", "citation_document_coverage", "higher"),
    ("metrics", "citation_evidence_coverage", "higher"),
    ("metrics", "citation_validity", "higher"),
    ("metrics", "invalid_citation_rate", "lower"),
    ("metrics", "retrieval_required_document_coverage", "higher"),
    ("metrics", "valid_citation_count", "higher"),
)
LATENCY_METRICS: tuple[str, ...] = (
    "context_select_or_dense_retrieval",
    "generation_provider",
    "judge_provider",
    "total_with_judge",
)


def _metric_value(row: Mapping[str, Any], section: str, name: str) -> float | None:
    source = _required_mapping(row.get(section), section)
    value = source.get(name)
    if value is None:
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    return _required_float(value, f"{section}.{name}")


def _summary(values: Sequence[float]) -> dict[str, Any]:
    ordered = sorted(values)
    if not ordered:
        return {"observations": 0, "mean": None, "p50": None, "p95": None, "p99": None}

    def percentile(q: float) -> float:
        position = (len(ordered) - 1) * q
        low, high = int(position), int(position + 0.999999999)
        if low == high:
            return ordered[low]
        return ordered[low] + (ordered[high] - ordered[low]) * (position - low)

    return {
        "observations": len(ordered),
        "mean": sum(ordered) / len(ordered),
        "p50": percentile(0.50),
        "p95": percentile(0.95),
        "p99": percentile(0.99),
    }


def _sha256_value(value: object, field: str) -> str:
    digest = str(value or "")
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise MatrixAnalysisError(f"{field} must be a lowercase SHA-256")
    return digest


def _validate_clean_cell(directory: Path) -> dict[str, Any]:
    data = _validate_cell(directory)
    cell_id = str(data["cell"]["cell_id"])
    if cell_id not in {LARGE_CELL_ID, SMALL_CELL_ID}:
        raise MatrixAnalysisError(f"clean pair only accepts large/small d1024 cells: {cell_id}")
    models = _required_mapping(data["summary"].get("models"), "summary.models")
    if models.get("generation") != PUBLICATION_GENERATION_MODEL:
        raise MatrixAnalysisError(
            f"clean pair generation model must be {PUBLICATION_GENERATION_MODEL}"
        )
    if models.get("judge") != PUBLICATION_JUDGE_MODEL:
        raise MatrixAnalysisError(f"clean pair judge model must be {PUBLICATION_JUDGE_MODEL}")
    if models.get("generation") == models.get("judge"):
        raise MatrixAnalysisError("clean pair requires an independent judge model")
    summary_proxy = _sha256_value(
        data["summary"].get("proxy_fingerprint_sha256"),
        "summary.proxy_fingerprint_sha256",
    )
    attestation_proxy = _sha256_value(
        data["attestation"].get("proxy_fingerprint_sha256"),
        "attestation.proxy_fingerprint_sha256",
    )
    if summary_proxy != attestation_proxy:
        raise MatrixAnalysisError("clean cell proxy fingerprints differ")
    summary_provenance = _required_mapping(
        data["summary"].get("runner_provenance"), "summary.runner_provenance"
    )
    attestation_provenance = _required_mapping(
        data["attestation"].get("runner_provenance"), "attestation.runner_provenance"
    )
    if summary_provenance != attestation_provenance:
        raise MatrixAnalysisError("clean cell runner provenance differs")
    _sha256_value(summary_provenance.get("wrapper_sha256"), "runner wrapper_sha256")
    _sha256_value(
        summary_provenance.get("upstream_runner_sha256"), "runner upstream_runner_sha256"
    )
    _sha256_value(summary_provenance.get("matrix_sha256"), "runner matrix_sha256")
    _sha256_value(summary_provenance.get("dataset_sha256"), "runner dataset_sha256")
    _sha256_value(summary_provenance.get("queries_sha256"), "runner queries_sha256")
    cache = _cache_denominators(
        data["rows"], data["calls"], cache_mode=_cache_mode(data["summary"], data["attestation"])
    )
    if cache["cache_contaminated"] or cache["query_rows"] != {
        "total": 70,
        "cached": 0,
        "uncached": 70,
    }:
        raise MatrixAnalysisError(f"clean pair cell is cache-contaminated: {directory}")
    if len(data["calls"]) != EXPECTED_PROVIDER_CALLS:
        raise MatrixAnalysisError(
            f"clean pair cell must have exactly {EXPECTED_PROVIDER_CALLS} provider calls"
        )
    endpoint_counts = cache["provider_calls"]
    expected_counts = {
        "embedding": EXPECTED_EMBEDDING_CALLS,
        "generation": EXPECTED_GENERATION_CALLS,
        "judge": EXPECTED_JUDGE_CALLS,
    }
    for endpoint, expected in expected_counts.items():
        if endpoint_counts[endpoint]["total"] != expected:
            raise MatrixAnalysisError(f"clean pair {endpoint} call count is not {expected}")
    for query_id, row in data["rows"].items():
        if set(row["timings_ms"]) < set(LATENCY_METRICS):
            raise MatrixAnalysisError(f"clean pair {query_id} lacks a required latency metric")
        for endpoint in ("generation", "judge"):
            usage = _required_mapping(row["usage"].get(endpoint), f"{query_id}.{endpoint} usage")
            if (
                sum(
                    int(usage.get(name, 0) or 0)
                    for name in ("input_tokens", "cached_input_tokens", "output_tokens")
                )
                <= 0
            ):
                raise MatrixAnalysisError(f"clean pair {query_id} has zero {endpoint} usage")
    return {
        **data,
        "cache": cache,
        "proxy_fingerprint_sha256": summary_proxy,
        "provenance": dict(summary_provenance),
    }


def _validate_pair(input_dirs: Sequence[Path]) -> dict[str, dict[str, Any]]:
    if len(input_dirs) != 2:
        raise MatrixAnalysisError("clean publication pair requires exactly two input dirs")
    validated = [_validate_clean_cell(directory) for directory in input_dirs]
    by_id = {str(data["cell"]["cell_id"]): data for data in validated}
    if set(by_id) != {LARGE_CELL_ID, SMALL_CELL_ID}:
        raise MatrixAnalysisError("clean publication pair must contain large-1024 and small-1024")
    large = by_id[LARGE_CELL_ID]
    small = by_id[SMALL_CELL_ID]
    for field in ("generation", "judge"):
        large_model = _required_mapping(large["summary"].get("models"), "large.models").get(field)
        small_model = _required_mapping(small["summary"].get("models"), "small.models").get(field)
        if large_model != small_model:
            raise MatrixAnalysisError(f"clean pair {field} model identity differs")
    large_mode = _cache_mode(large["summary"], large["attestation"])
    small_mode = _cache_mode(small["summary"], small["attestation"])
    if large_mode not in {"no-cache", "no_cache"} or small_mode not in {
        "no-cache",
        "no_cache",
    }:
        raise MatrixAnalysisError("clean pair cache mode must be no-cache")
    if large["proxy_fingerprint_sha256"] != small["proxy_fingerprint_sha256"]:
        raise MatrixAnalysisError("clean pair proxy fingerprint differs")
    if large["provenance"] != small["provenance"]:
        raise MatrixAnalysisError("clean pair runner provenance differs")
    if (
        set(large["rows"]) != set(small["rows"])
        or tuple(large["rows"]) != EXPECTED_QUERY_IDS
        or tuple(small["rows"]) != EXPECTED_QUERY_IDS
    ):
        raise MatrixAnalysisError("clean pair query IDs are not identical and complete")
    if any(
        large["rows"][query_id]["answerable"] != small["rows"][query_id]["answerable"]
        for query_id in EXPECTED_QUERY_IDS
    ):
        raise MatrixAnalysisError("clean pair answerable labels differ")
    for label, data in (("large", large), ("small", small)):
        for section, name, _direction in QUALITY_METRICS:
            answerable_only = not (section == "metrics" and name == "abstention_correct")
            if section == "metrics" and name == "citation_validity":
                expected = sum(
                    int(
                        _required_float(
                            _required_mapping(row["metrics"], "metrics").get("citation_count"),
                            "metrics.citation_count",
                        )
                        > 0
                    )
                    for row in data["rows"].values()
                    if row["answerable"] is True
                )
            else:
                expected = 60 if answerable_only else 70
            observations = sum(
                _metric_value(row, section, name) is not None
                for row in data["rows"].values()
                if not answerable_only or row["answerable"] is True
            )
            if observations != expected:
                raise MatrixAnalysisError(
                    f"{label} {section}.{name} must have {expected} observations, got {observations}"
                )
    return {"large": large, "small": small}


def _stage_shares(rows: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    stage_names = (
        "context_select_or_dense_retrieval",
        "generation_provider",
        "generation_total",
        "judge_provider",
        "judge_total",
        "postprocess",
    )
    summaries: dict[str, Any] = {}
    for name in stage_names:
        values = [
            _required_float(_required_mapping(row["timings_ms"], "timings_ms")[name], name)
            for row in rows.values()
        ]
        summaries[name] = _summary(values)
    total_mean = _summary(
        [
            _required_float(row["timings_ms"]["total_with_judge"], "total_with_judge")
            for row in rows.values()
        ]
    )["mean"]
    additive_stages = {
        "context_select_or_dense_retrieval",
        "generation_provider",
        "judge_provider",
        "postprocess",
    }
    for name, value in summaries.items():
        value["share_of_total_mean"] = (
            value["mean"] / total_mean if name in additive_stages and total_mean else None
        )
    return {
        "total_with_judge": _summary(
            [
                _required_float(row["timings_ms"]["total_with_judge"], "total_with_judge")
                for row in rows.values()
            ]
        ),
        "stages": summaries,
        "population": "all_70_uncached_queries",
        "share_basis": "disjoint retrieval/provider/judge-provider/postprocess stages; generation_total and judge_total are aggregate clocks and not additive",
    }


def _paired(
    large: Mapping[str, Mapping[str, Any]],
    small: Mapping[str, Mapping[str, Any]],
    section: str,
    name: str,
    direction: str,
    *,
    answerable_only: bool,
    bootstrap_samples: int,
    sign_flip_samples: int,
    seed: int,
) -> dict[str, Any]:
    deltas: list[float] = []
    for query_id in EXPECTED_QUERY_IDS:
        if answerable_only and large[query_id]["answerable"] is not True:
            continue
        left = _metric_value(large[query_id], section, name)
        right = _metric_value(small[query_id], section, name)
        if left is None or right is None:
            continue
        deltas.append(left - right)
    higher = direction == "higher"
    wins = sum(delta > 1e-12 if higher else delta < -1e-12 for delta in deltas)
    losses = sum(delta < -1e-12 if higher else delta > 1e-12 for delta in deltas)
    ties = len(deltas) - wins - losses
    return {
        "metric": f"{section}.{name}",
        "orientation": "large_minus_small",
        "direction": direction,
        "population": (
            "answerable_queries_with_citations_in_both_conditions"
            if section == "metrics" and name == "citation_validity"
            else "answerable_only" if answerable_only else "all_70_queries"
        ),
        "paired_query_count": len(deltas),
        "mean_delta": sum(deltas) / len(deltas) if deltas else None,
        "bootstrap_samples": bootstrap_samples,
        "bootstrap_ci95": bootstrap_ci(deltas, seed=seed, samples=bootstrap_samples),
        "sign_flip_samples": sign_flip_samples,
        "sign_flip_p": sign_flip_pvalue(deltas, seed=seed + 1, samples=sign_flip_samples),
        "wins": wins,
        "ties": ties,
        "losses": losses,
        "w_t_l": [wins, ties, losses],
    }


def analyze_clean_pair(
    input_dirs: Sequence[Path],
    *,
    seed: int = 42,
    bootstrap_samples: int = BOOTSTRAP_SAMPLES,
    sign_flip_samples: int = SIGN_FLIP_SAMPLES,
) -> dict[str, Any]:
    pair = _validate_pair(input_dirs)
    large, small = pair["large"], pair["small"]
    large_rows, small_rows = large["rows"], small["rows"]
    metrics: list[dict[str, Any]] = []
    hypotheses: dict[str, float | None] = {}
    for index, (section, name, direction) in enumerate(QUALITY_METRICS):
        answerable_only = not (section == "metrics" and name == "abstention_correct")
        metric = _paired(
            large_rows,
            small_rows,
            section,
            name,
            direction,
            answerable_only=answerable_only,
            bootstrap_samples=bootstrap_samples,
            sign_flip_samples=sign_flip_samples,
            seed=seed + index * 10,
        )
        metrics.append(metric)
        hypotheses[metric["metric"]] = metric["sign_flip_p"]
    for index, name in enumerate(LATENCY_METRICS):
        metric = _paired(
            large_rows,
            small_rows,
            "timings_ms",
            name,
            "lower",
            answerable_only=False,
            bootstrap_samples=bootstrap_samples,
            sign_flip_samples=sign_flip_samples,
            seed=seed + 200 + index * 10,
        )
        metrics.append(metric)
        hypotheses[metric["metric"]] = metric["sign_flip_p"]
    holm = holm_correction(hypotheses)
    for metric in metrics:
        metric["holm"] = holm[metric["metric"]]
        metric["holm_adjusted_p"] = holm[metric["metric"]]["holm_p"]
    costs = {label: _provider_cost(data["calls"]) for label, data in pair.items()}
    large_cost = Decimal(costs["large"]["actual_provider_cost_usd"])
    small_cost = Decimal(costs["small"]["actual_provider_cost_usd"])
    premium = large_cost - small_cost
    quality_summary: dict[str, Any] = {}
    for label, data in pair.items():
        quality_summary[label] = {
            f"{section}.{name}": _summary(
                [
                    value
                    for query_id, row in data["rows"].items()
                    if (
                        (
                            name == "abstention_correct"
                            and section == "metrics"
                        )
                        or row["answerable"] is True
                    )
                    and (value := _metric_value(row, section, name)) is not None
                ]
            )
            for section, name, _direction in QUALITY_METRICS
        }
    latency_summary = {
        label: {
            name: _summary(
                [_required_float(row["timings_ms"][name], name) for row in data["rows"].values()]
            )
            for name in LATENCY_METRICS
        }
        for label, data in pair.items()
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "benchmark": "open-manuals-v2",
        "analysis_kind": "clean-publication-pair",
        "orientation": {
            "large_cell_id": LARGE_CELL_ID,
            "small_cell_id": SMALL_CELL_ID,
            "delta": "large_minus_small",
        },
        "validation": {
            "cache_identity": "explicit no-cache with complete 211-call/no-zero-usage rows",
            "generation_model_identity": _required_mapping(
                large["summary"]["models"], "large.models"
            )["generation"],
            "judge_model_identity": _required_mapping(large["summary"]["models"], "large.models")[
                "judge"
            ],
            "denominator": EXPECTED_DENOMINATOR,
            "quality_population": "60 answerable queries; abstention_correct uses all 70; citation_validity excludes answers with no citations",
            "latency_population": "70 queries",
        },
        "conditions": {
            "large": {
                "cell": large["cell"],
                "provider_calls": len(large["calls"]),
                "cost": costs["large"],
                "quality": quality_summary["large"],
                "latency": latency_summary["large"],
                "atomic_stage_shares": _stage_shares(large_rows),
            },
            "small": {
                "cell": small["cell"],
                "provider_calls": len(small["calls"]),
                "cost": costs["small"],
                "quality": quality_summary["small"],
                "latency": latency_summary["small"],
                "atomic_stage_shares": _stage_shares(small_rows),
            },
        },
        "paired_comparisons": metrics,
        "holm_correction": holm,
        "actual_cost_premium": {
            "large_minus_small_usd": str(premium),
            "large_cost_usd": str(large_cost),
            "small_cost_usd": str(small_cost),
            "relative_premium": str(premium / small_cost) if small_cost else None,
            "basis": "provider_calls_usage_only",
        },
        "privacy": {
            "prompts_persisted": False,
            "answers_persisted": False,
            "document_text_persisted": False,
            "provider_response_bodies_persisted": False,
        },
    }


def markdown_report(result: Mapping[str, Any]) -> str:
    validation = _required_mapping(result["validation"], "validation")
    lines = [
        "# Open Manuals clean embedding pair analysis",
        "",
        "Large 1024 minus small 1024; no-cache publication pair.",
        "",
        f"- Quality population: {validation['quality_population']}; latency population: {validation['latency_population']}.",
        "- Triad/citation/retrieval quality metrics are answerable-only; abstention_correct and latency metrics use all 70 clean queries.",
        "- Section-level qrels are unavailable; document/chunk hits are not promoted to section evidence.",
        "",
        "## Actual provider cost",
        "",
        f"Large-minus-small premium: `{result['actual_cost_premium']['large_minus_small_usd']}` USD (`{float(result['actual_cost_premium']['relative_premium']) * 100:.2f}%`).",
        "",
        "## Stage shares",
        "",
        "| Condition | Stage | Mean ms | Share of total mean | N |",
        "|---|---|---:|---:|---:|",
    ]
    for label in ("large", "small"):
        stage_data = result["conditions"][label]["atomic_stage_shares"]
        for name, summary in stage_data["stages"].items():
            share = summary["share_of_total_mean"]
            share_text = "n/a" if share is None else f"{share:.4f}"
            lines.append(
                f"| {label} | {name} | {summary['mean']:.4f} | {share_text} | {summary['observations']} |"
            )
    lines.extend(
        [
            "",
            "## Paired quality and latency inference",
            "",
            "| Metric | Population | N | Large-small mean delta | 95% bootstrap CI | W/T/L | Sign-flip p | Holm p |",
            "|---|---|---:|---:|---|---:|---:|---:|",
        ]
    )
    for metric in result["paired_comparisons"]:
        ci = metric["bootstrap_ci95"]
        ci_text = "n/a" if ci is None else f"[{ci[0]:.5f}, {ci[1]:.5f}]"
        mean_text = "n/a" if metric["mean_delta"] is None else f"{metric['mean_delta']:.6f}"
        p_text = "n/a" if metric["sign_flip_p"] is None else f"{metric['sign_flip_p']:.6f}"
        holm_text = (
            "n/a" if metric["holm_adjusted_p"] is None else f"{metric['holm_adjusted_p']:.6f}"
        )
        lines.append(
            f"| {metric['metric']} | {metric['population']} | {metric['paired_query_count']} | {mean_text} | {ci_text} | {metric['wins']}/{metric['ties']}/{metric['losses']} | {p_text} | {holm_text} |"
        )
    return "\n".join(lines) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir",
        action="append",
        required=True,
        type=Path,
        help="exactly two clean publication cell dirs",
    )
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-markdown", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--bootstrap-samples", type=int, default=BOOTSTRAP_SAMPLES)
    parser.add_argument("--sign-flip-samples", type=int, default=SIGN_FLIP_SAMPLES)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = analyze_clean_pair(
        args.input_dir,
        seed=args.seed,
        bootstrap_samples=args.bootstrap_samples,
        sign_flip_samples=args.sign_flip_samples,
    )
    output_json = args.output_json
    output_markdown = args.output_markdown
    if output_json.exists() or output_markdown.exists() or output_json == output_markdown:
        raise OutputExistsError("refusing to overwrite clean pair output")
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        __import__("json").dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    output_markdown.write_text(markdown_report(result), encoding="utf-8")
    print(
        f'{{"status":"completed","output_json":"{output_json.resolve()}","output_markdown":"{output_markdown.resolve()}"}}'
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (MatrixAnalysisError, OutputExistsError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
