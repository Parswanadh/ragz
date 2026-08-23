import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import analyze_open_manuals_clean_pair as clean_pair  # noqa: E402
from analyze_open_manuals_clean_pair import (  # noqa: E402
    LATENCY_METRICS,
    QUALITY_METRICS,
    analyze_clean_pair,
)
from analyze_open_manuals_matrix import EXPECTED_QUERY_IDS, MatrixAnalysisError  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "docs/benchmarks/artifacts/raw/2026-08-23"
LARGE = RAW / "open-manuals-publication-large-1024-nocache-gpt54judge-20260823-r1"
SMALL = RAW / "open-manuals-publication-small-1024-nocache-gpt54judge-20260823-r1"


def test_clean_pair_has_fixed_orientation_18_metrics_and_cost_premium() -> None:
    # The checked-in pre-hardening artifacts intentionally lack the required
    # proxy/provenance attestation and contain a judge endpoint/model mismatch.
    with pytest.raises(MatrixAnalysisError, match="not completed|model|proxy|provenance"):
        analyze_clean_pair([LARGE, SMALL], bootstrap_samples=100, sign_flip_samples=100, seed=7)


def test_clean_pair_rejects_exploratory_short_cell() -> None:
    exploratory = RAW / "open-manuals-matrix-large-1024-20260823-r1"
    with pytest.raises(
        MatrixAnalysisError,
        match="judge model|cache mode|cache-contaminated|211",
    ):
        analyze_clean_pair([exploratory, SMALL], bootstrap_samples=100, sign_flip_samples=100)


def test_clean_pair_rejects_mutually_consistent_self_judge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        clean_pair,
        "_validate_cell",
        lambda _directory: {
            "cell": {"cell_id": clean_pair.LARGE_CELL_ID},
            "summary": {
                "models": {
                    "generation": clean_pair.PUBLICATION_GENERATION_MODEL,
                    "judge": clean_pair.PUBLICATION_GENERATION_MODEL,
                }
            },
        },
    )

    with pytest.raises(MatrixAnalysisError, match="judge model"):
        clean_pair._validate_clean_cell(Path("synthetic-self-judge"))


def _synthetic_clean_pair() -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for index, query_id in enumerate(EXPECTED_QUERY_IDS):
        answerable = index < 60
        judge = {
            name: 1.0 if answerable else 9.0
            for section, name, _direction in QUALITY_METRICS
            if section == "judge"
        }
        metrics = {
            name: (
                (1.0 if answerable else 0.0)
                if name == "abstention_correct"
                else (1.0 if answerable else 9.0)
            )
            for section, name, _direction in QUALITY_METRICS
            if section == "metrics"
        }
        timings = {
            name: 1.0
            for name in (
                *LATENCY_METRICS,
                "context_select_or_dense_retrieval",
                "generation_provider",
                "generation_total",
                "judge_provider",
                "judge_total",
                "postprocess",
            )
        }
        rows[query_id] = {
            "answerable": answerable,
            "judge": judge,
            "metrics": metrics,
            "timings_ms": timings,
            "usage": {
                "generation": {"input_tokens": 1},
                "judge": {"input_tokens": 1},
            },
        }

    def cell(cell_id: str) -> dict[str, Any]:
        return {
            "cell": {"cell_id": cell_id},
            "calls": [],
            "rows": rows,
            "summary": {
                "models": {"generation": "generation-model", "judge": "judge-model"}
            },
        }

    return {
        "large": cell("openai-text-embedding-3-large-d1024"),
        "small": cell("openai-text-embedding-3-small-d1024"),
    }


def test_clean_pair_quality_summaries_use_the_declared_populations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pair = _synthetic_clean_pair()
    monkeypatch.setattr(clean_pair, "_validate_pair", lambda _input_dirs: pair)
    monkeypatch.setattr(
        clean_pair,
        "_provider_cost",
        lambda _calls: {"actual_provider_cost_usd": "1.00"},
    )

    result = analyze_clean_pair([], bootstrap_samples=100, sign_flip_samples=100)

    for label in ("large", "small"):
        quality = result["conditions"][label]["quality"]
        for section, name, _direction in QUALITY_METRICS:
            summary = quality[f"{section}.{name}"]
            if section == "metrics" and name == "abstention_correct":
                assert summary["observations"] == 70
                assert summary["mean"] == pytest.approx(60 / 70)
            else:
                assert summary["observations"] == 60
                assert summary["mean"] == pytest.approx(1.0)
