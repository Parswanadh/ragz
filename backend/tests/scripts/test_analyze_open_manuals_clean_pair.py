import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from analyze_open_manuals_clean_pair import (  # noqa: E402
    LARGE_CELL_ID,
    SMALL_CELL_ID,
    MatrixAnalysisError,
    analyze_clean_pair,
)

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "docs/benchmarks/artifacts/raw/2026-08-23"
LARGE = RAW / "open-manuals-publication-large-1024-nocache-gpt54judge-20260823-r1"
SMALL = RAW / "open-manuals-publication-small-1024-nocache-gpt54judge-20260823-r1"


def test_clean_pair_has_fixed_orientation_18_metrics_and_cost_premium() -> None:
    result = analyze_clean_pair(
        [LARGE, SMALL], bootstrap_samples=100, sign_flip_samples=100, seed=7
    )
    assert result["orientation"] == {
        "large_cell_id": LARGE_CELL_ID,
        "small_cell_id": SMALL_CELL_ID,
        "delta": "large_minus_small",
    }
    assert len(result["paired_comparisons"]) == 18
    assert len(result["holm_correction"]) == 18
    assert all(
        metric["population"] == "answerable_only" for metric in result["paired_comparisons"][:7]
    )
    assert result["paired_comparisons"][7]["metric"] == "metrics.abstention_correct"
    assert result["paired_comparisons"][7]["population"] == "all_70_queries"
    assert result["paired_comparisons"][7]["paired_query_count"] == 70
    assert all(
        metric["population"] == "answerable_only" for metric in result["paired_comparisons"][8:14]
    )
    assert {metric["population"] for metric in result["paired_comparisons"][14:]} == {
        "all_70_queries"
    }
    assert result["conditions"]["large"]["provider_calls"] == 211
    assert result["conditions"]["small"]["provider_calls"] == 211
    assert result["actual_cost_premium"]["basis"] == "provider_calls_usage_only"


def test_clean_pair_rejects_exploratory_short_cell() -> None:
    exploratory = RAW / "open-manuals-matrix-large-1024-20260823-r1"
    with pytest.raises(MatrixAnalysisError, match="cache-contaminated|211"):
        analyze_clean_pair([exploratory, SMALL], bootstrap_samples=100, sign_flip_samples=100)
