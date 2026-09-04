#!/usr/bin/env python3
"""Sanitized scheduling and aggregation entrypoint for the CAG experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from statistics import fmean
from typing import Any

from jsonschema import Draft202012Validator

DEFAULT_TRIAL_SCHEMA = (
    Path(__file__).parents[2] / "no_rel" / "benchmarks" / "cag" / "schemas" / "trial.schema.json"
)
QUALITY_METRICS = (
    "context_relevance",
    "groundedness",
    "answer_relevance",
    "citation_precision",
    "citation_coverage",
    "citation_provenance_valid",
    "abstention_correct",
    "exact_match",
    "f1",
)


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value


def _opaque_id(*parts: object) -> str:
    material = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:24]


def build_schedule(
    question_manifest: dict[str, Any],
    *,
    variants: tuple[str, ...],
    repetitions: int,
    seed: int,
) -> dict[str, Any]:
    fixture_sha256 = str(question_manifest["fixture_sha256"])
    raw_questions = question_manifest.get("questions")
    if not isinstance(raw_questions, list) or not raw_questions:
        raise ValueError("questions must be a non-empty list")
    if not variants or len(set(variants)) != len(variants):
        raise ValueError("variants must be non-empty and unique")
    if repetitions < 1:
        raise ValueError("repetitions must be positive")

    assignments: list[dict[str, object]] = []
    for question in raw_questions:
        if not isinstance(question, dict):
            raise ValueError("each question manifest row must be an object")
        if set(question) != {"question_id", "stratum"}:
            raise ValueError(
                "public question manifest rows may contain only question_id and stratum"
            )
        question_id = str(question["question_id"])
        stratum = str(question["stratum"])
        for repetition in range(1, repetitions + 1):
            pair_id = _opaque_id("pair", fixture_sha256, question_id, repetition)
            order = list(variants)
            block_seed = int(
                hashlib.sha256(
                    f"{seed}:{fixture_sha256}:{question_id}:{repetition}".encode()
                ).hexdigest(),
                16,
            )
            random.Random(block_seed).shuffle(order)  # noqa: S311 - reproducible schedule
            assignments.extend(
                {
                    "trial_id": _opaque_id("trial", pair_id, variant),
                    "pair_id": pair_id,
                    "question_id": question_id,
                    "stratum": stratum,
                    "repetition": repetition,
                    "order_index": order_index,
                    "variant": variant,
                }
                for order_index, variant in enumerate(order, start=1)
            )
    return {
        "schema_version": 1,
        "fixture_sha256": fixture_sha256,
        "seed": seed,
        "repetitions": repetitions,
        "variants": list(variants),
        "assignments": assignments,
    }


def _schedule(args: argparse.Namespace) -> None:
    manifest = _load_object(args.questions)
    variants = tuple(value.strip() for value in args.variants.split(",") if value.strip())
    schedule = build_schedule(
        manifest,
        variants=variants,
        repetitions=args.repetitions,
        seed=args.seed,
    )
    args.output.write_text(
        json.dumps(schedule, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_records(path: Path) -> list[object]:
    if path.suffix == ".jsonl":
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, list) else [value]


def _safe_validation_error(
    *,
    input_path: Path,
    record_number: int,
    error: Any,
    schema: dict[str, Any],
) -> str:
    instance_path = "/".join(str(part) for part in error.absolute_path) or "<root>"
    detail = ""
    if error.validator == "additionalProperties" and isinstance(error.instance, dict):
        allowed = set((error.schema or schema).get("properties", {}))
        unexpected = sorted(set(error.instance) - allowed)
        detail = f" unexpected_keys={','.join(unexpected)}"
    return (
        f"{input_path}:record={record_number}:path={instance_path}:"
        f"validator={error.validator}{detail}"
    )


def _validate(args: argparse.Namespace) -> None:
    schema = _load_object(args.schema)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    records = _load_records(args.input)
    failures: list[str] = []
    for record_number, record in enumerate(records, start=1):
        errors = sorted(validator.iter_errors(record), key=lambda error: list(error.absolute_path))
        failures.extend(
            _safe_validation_error(
                input_path=args.input,
                record_number=record_number,
                error=error,
                schema=schema,
            )
            for error in errors
        )
    if failures:
        raise SystemExit("\n".join(failures))
    print(json.dumps({"status": "valid", "records": len(records)}, sort_keys=True))


def _percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 10)


def _failure_inclusive_metric(record: dict[str, Any], metric: str) -> float:
    value = record.get("metrics", {}).get(metric)
    return float(value) if isinstance(value, (int, float)) else 0.0


def _bootstrap_delta(
    deltas: list[float], *, samples: int, seed: int
) -> tuple[float, list[float]]:
    estimate = fmean(deltas)
    rng = random.Random(seed)  # noqa: S311 - reproducible bootstrap, not security
    bootstrapped = [
        fmean(deltas[rng.randrange(len(deltas))] for _ in deltas)
        for _ in range(samples)
    ]
    lower = _percentile(bootstrapped, 0.025)
    upper = _percentile(bootstrapped, 0.975)
    assert lower is not None and upper is not None
    return estimate, [lower, upper]


def aggregate_trials(
    records: list[dict[str, Any]],
    *,
    baseline_variant: str,
    bootstrap_samples: int,
    seed: int,
) -> dict[str, Any]:
    if bootstrap_samples < 1:
        raise ValueError("bootstrap_samples must be positive")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record["variant"])].append(record)
    if baseline_variant not in grouped:
        raise ValueError("baseline variant is absent")

    output: dict[str, Any] = {
        "schema_version": 1,
        "baseline_variant": baseline_variant,
        "bootstrap_samples": bootstrap_samples,
        "seed": seed,
        "assigned_n": len(records),
        "variants": {},
    }
    variants_output: dict[str, Any] = output["variants"]
    baseline_records = grouped[baseline_variant]
    for variant in sorted(grouped):
        rows = grouped[variant]
        completed = [row for row in rows if row["status"] == "completed"]
        failure_counts = Counter(
            str(row.get("failure_type") or row["status"])
            for row in rows
            if row["status"] != "completed"
        )
        latency_values = [
            float(value)
            for row in rows
            if isinstance((value := row.get("latency_ms", {}).get("end_to_end")), (int, float))
        ]
        metric_names = [
            metric
            for metric in QUALITY_METRICS
            if any(metric in row.get("metrics", {}) for row in rows)
        ]
        metric_output: dict[str, Any] = {}
        for metric in metric_names:
            observed = [
                float(value)
                for row in rows
                if isinstance((value := row.get("metrics", {}).get(metric)), (int, float))
            ]
            metric_output[metric] = {
                "assigned_n": len(rows),
                "observed_n": len(observed),
                "failure_inclusive_mean": _rounded(
                    fmean(_failure_inclusive_metric(row, metric) for row in rows)
                ),
                "completed_observed_mean": _rounded(fmean(observed) if observed else None),
            }
        usage_output: dict[str, Any] = {}
        for field in (
            "prompt_tokens",
            "completion_tokens",
            "cached_tokens",
            "cache_write_tokens",
            "reasoning_tokens",
        ):
            known = [
                int(value)
                for row in rows
                if isinstance((value := row.get("usage", {}).get(field)), int)
                and not isinstance(value, bool)
            ]
            usage_output[field] = {
                "known_n": len(known),
                "unknown_n": len(rows) - len(known),
                "total": sum(known),
                "mean_known": _rounded(fmean(known) if known else None),
            }
        usage_output["cache_outcomes"] = dict(
            sorted(Counter(str(row["usage"]["cache_outcome"]) for row in rows).items())
        )
        known_costs = [
            float(value)
            for row in rows
            if isinstance((value := row.get("known_cost_usd")), (int, float))
            and not isinstance(value, bool)
        ]
        variant_output: dict[str, Any] = {
            "assigned_n": len(rows),
            "completed_n": len(completed),
            "completion_rate": _rounded(len(completed) / len(rows)),
            "status_counts": dict(sorted(Counter(str(row["status"]) for row in rows).items())),
            "failure_counts": dict(sorted(failure_counts.items())),
            "latency_ms": {
                "observed_n": len(latency_values),
                "mean": _rounded(fmean(latency_values) if latency_values else None),
                "p50": _rounded(_percentile(latency_values, 0.50)),
                "p95": _rounded(_percentile(latency_values, 0.95)),
                "p99": _rounded(_percentile(latency_values, 0.99)),
            },
            "metrics": metric_output,
            "usage": usage_output,
            "known_cost_usd": {
                "complete": len(known_costs) == len(rows),
                "known_n": len(known_costs),
                "unknown_n": len(rows) - len(known_costs),
                "total_known": _rounded(sum(known_costs)),
                "mean_known": _rounded(fmean(known_costs) if known_costs else None),
            },
            "paired_deltas": {},
        }
        if variant != baseline_variant:
            paired_output: dict[str, Any] = variant_output["paired_deltas"]
            for metric in metric_names:
                candidate_by_question: dict[str, list[float]] = defaultdict(list)
                baseline_by_question: dict[str, list[float]] = defaultdict(list)
                for row in rows:
                    candidate_by_question[str(row["question_id"])].append(
                        _failure_inclusive_metric(row, metric)
                    )
                for row in baseline_records:
                    baseline_by_question[str(row["question_id"])].append(
                        _failure_inclusive_metric(row, metric)
                    )
                question_ids = sorted(set(candidate_by_question) & set(baseline_by_question))
                if not question_ids:
                    continue
                deltas = [
                    fmean(candidate_by_question[question_id])
                    - fmean(baseline_by_question[question_id])
                    for question_id in question_ids
                ]
                metric_seed = int(
                    hashlib.sha256(f"{seed}:{variant}:{metric}".encode()).hexdigest(),
                    16,
                )
                estimate, ci95 = _bootstrap_delta(
                    deltas,
                    samples=bootstrap_samples,
                    seed=metric_seed,
                )
                paired_output[metric] = {
                    "query_n": len(question_ids),
                    "estimate": _rounded(estimate),
                    "ci95": [_rounded(ci95[0]), _rounded(ci95[1])],
                }
        variants_output[variant] = variant_output
    return output


def _aggregate(args: argparse.Namespace) -> None:
    schema = _load_object(args.trial_schema)
    validator = Draft202012Validator(schema)
    raw_records = _load_records(args.trials)
    records: list[dict[str, Any]] = []
    for index, record in enumerate(raw_records, start=1):
        errors = list(validator.iter_errors(record))
        if errors:
            safe = _safe_validation_error(
                input_path=args.trials,
                record_number=index,
                error=errors[0],
                schema=schema,
            )
            raise SystemExit(safe)
        assert isinstance(record, dict)
        records.append(record)
    aggregate = aggregate_trials(
        records,
        baseline_variant=args.baseline_variant,
        bootstrap_samples=args.bootstrap_samples,
        seed=args.seed,
    )
    args.output.write_text(
        json.dumps(aggregate, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    schedule = commands.add_parser("schedule", help="build a deterministic paired run order")
    schedule.add_argument("--questions", required=True, type=Path)
    schedule.add_argument("--variants", required=True)
    schedule.add_argument("--repetitions", required=True, type=int)
    schedule.add_argument("--seed", required=True, type=int)
    schedule.add_argument("--output", required=True, type=Path)
    schedule.set_defaults(handler=_schedule)

    validate = commands.add_parser("validate", help="validate JSON or JSONL without echoing data")
    validate.add_argument("--schema", required=True, type=Path)
    validate.add_argument("--input", required=True, type=Path)
    validate.set_defaults(handler=_validate)

    aggregate = commands.add_parser(
        "aggregate", help="aggregate failure-inclusive paired trial records"
    )
    aggregate.add_argument("--trials", required=True, type=Path)
    aggregate.add_argument("--trial-schema", type=Path, default=DEFAULT_TRIAL_SCHEMA)
    aggregate.add_argument("--baseline-variant", required=True)
    aggregate.add_argument("--bootstrap-samples", type=int, default=10_000)
    aggregate.add_argument("--seed", required=True, type=int)
    aggregate.add_argument("--output", required=True, type=Path)
    aggregate.set_defaults(handler=_aggregate)
    return parser


def main() -> None:
    args = _parser().parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
