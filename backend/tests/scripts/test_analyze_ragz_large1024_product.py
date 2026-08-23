import json
import shutil
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from analyze_ragz_large1024_product import (  # noqa: E402
    AnalysisError,
    build,
    paired_bootstrap,
    validate_manifest,
    validate_records,
)

ARTIFACTS = Path(__file__).resolve().parents[2] / "../docs/benchmarks/artifacts/raw/2026-08-23"
LARGE_RUNS = [
    ARTIFACTS / "ragz-networking-large1024-product-atomic-20260823-r1",
    ARTIFACTS / "ragz-networking-large1024-product-atomic-20260823-r2",
]
SMALL_RUNS = [
    ARTIFACTS / "ragz-networking-openai-atomic-depth20-20260823-235f77c-r1",
    ARTIFACTS / "ragz-networking-openai-atomic-depth20-20260823-235f77c-r2",
]


@pytest.mark.skipif(not LARGE_RUNS[0].exists(), reason="benchmark artifacts are not checked out")
def test_build_recomputes_the_210_observation_product_denominators() -> None:
    result = build(run_roots=LARGE_RUNS, historical_run_roots=SMALL_RUNS)

    assert result["denominators"]["single"] == {
        "observations": 210,
        "query_count": 15,
        "orders": 2,
        "repetitions_per_query_per_order": 7,
        "answerable_observations": 168,
        "off_corpus_observations": 42,
        "errors": 0,
    }
    assert result["denominators"]["multi"] == result["denominators"]["single"]
    assert result["paired_multi_minus_single"]["elapsed_ms"]["paired_query_count"] == 15
    assert result["paired_multi_minus_single"]["recall_at_k"]["paired_query_count"] == 12
    assert result["index_stages"]["observations"] == 2
    assert result["index_stages"]["stages"]["dense_embedding"]["combined_total_share"] > 0.9
    assert result["historical_small1536"]["denominators"]["single"]["observations"] == 90


@pytest.mark.skipif(not LARGE_RUNS[0].exists(), reason="benchmark artifacts are not checked out")
def test_validation_binds_alias_and_grid_and_stage_closure(tmp_path: Path) -> None:
    manifest = json.loads((LARGE_RUNS[0] / "manifest.json").read_text())
    manifest["embedding_alias"] = "wrong-alias"
    with pytest.raises(AnalysisError, match="alias"):
        validate_manifest(manifest)

    copied = tmp_path / "run"
    shutil.copytree(LARGE_RUNS[0], copied)
    path = copied / "single" / "per_query.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    rows.pop()
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(AnalysisError, match="exactly 105"):
        validate_records(copied, "single")

    shutil.copytree(LARGE_RUNS[0], tmp_path / "bad-closure")
    bad_path = tmp_path / "bad-closure" / "single" / "per_query.jsonl"
    bad_rows = [json.loads(line) for line in bad_path.read_text().splitlines() if line.strip()]
    bad_rows[0]["stage_timings_ms"]["dense_embedding"] += 1
    bad_path.write_text("".join(json.dumps(row) + "\n" for row in bad_rows))
    with pytest.raises(AnalysisError, match="close"):
        validate_records(tmp_path / "bad-closure", "single")


def test_paired_bootstrap_is_query_level_and_deterministic() -> None:
    def rows(mode: str, offset: float) -> list[dict[str, object]]:
        return [
            {
                "query_id": f"q{query:02d}",
                "answerable": True,
                "elapsed_ms": 10 + query + offset,
                "metrics": {
                    "recall_at_k": 0.1 * query + offset,
                    "reciprocal_rank": 0.2 * query + offset,
                    "ndcg_at_k": 0.3 * query + offset,
                },
            }
            for query in range(1, 4)
        ]

    first = rows("single", 0)
    second = rows("multi", 2)
    result = paired_bootstrap(first, second, samples=500, seed=7)

    assert result == paired_bootstrap(first, second, samples=500, seed=7)
    assert result["elapsed_ms"]["paired_query_count"] == 3
    assert result["elapsed_ms"]["mean_delta"] == pytest.approx(2)
    assert result["recall_at_k"]["mean_delta"] == pytest.approx(2)
