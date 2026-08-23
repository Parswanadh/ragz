import hashlib
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from analyze_open_manuals_matrix import (  # noqa: E402
    EXPECTED_CELL_IDS,
    EXPECTED_DOCUMENT_SHA256,
    EXPECTED_QUERY_SHA256,
    MatrixAnalysisError,
    OutputExistsError,
    analyze,
    bootstrap_ci,
    holm_correction,
    markdown_report,
    sign_flip_pvalue,
    write_outputs,
)


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _cell_dirs(tmp_path: Path) -> list[Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    directories: list[Path] = []
    for index, cell_id in enumerate(sorted(EXPECTED_CELL_IDS)):
        model = "text-embedding-3-large" if "large" in cell_id else "text-embedding-3-small"
        dimension = int(cell_id.rsplit("d", 1)[1])
        directory = tmp_path / cell_id
        directory.mkdir()
        rows = []
        for query_index in range(1, 71):
            rows.append(
                {
                    "answerable": query_index <= 60,
                    "error_codes": [],
                    "judge": {
                        "answer_relevance": 0.8 + index / 100,
                        "context_relevance": 0.7 + index / 100,
                        "groundedness": 0.9,
                    },
                    "metrics": {
                        "retrieval_evidence_coverage": 1.0 if query_index <= 60 else None,
                    },
                    "query_id": f"q{query_index:03d}",
                    "retrieved_ids": ["manual-a:chunk-0001"],
                    "timings_ms": {
                        "context_select_or_dense_retrieval": 10.0 + index,
                        "generation_total": 20.0,
                        "judge_total": 30.0,
                        "total_with_judge": 60.0 + index,
                    },
                    "usage": {
                        "generation": {
                            "cached_input_tokens": 0,
                            "input_tokens": 10,
                            "output_tokens": 1,
                        },
                        "judge": {
                            "cached_input_tokens": 0,
                            "input_tokens": 10,
                            "output_tokens": 1,
                        },
                    },
                }
            )
        per_query = directory / "per_query.jsonl"
        per_query.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        provider_calls = directory / "provider_calls.jsonl"
        provider_calls.write_text(
            json.dumps(
                {
                    "actual_vector_dimension": dimension,
                    "endpoint": "/v1/embeddings",
                    "endpoint_type": "embedding",
                    "error_code": None,
                    "input_count": 1,
                    "latency_ms": 5.0,
                    "model": f"ragz-{cell_id}",
                    "retries": 0,
                    "sequence": 1,
                    "usage": {
                        "cached_input_tokens": 0,
                        "input_tokens": 100,
                        "output_tokens": 0,
                    },
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        summary = {
            "benchmark": "open-manuals-v2",
            "cell": {
                "alias": f"ragz-{cell_id}",
                "cell_id": cell_id,
                "dimension": dimension,
                "model": model,
            },
            "dataset_sha256": {
                "documents": EXPECTED_DOCUMENT_SHA256,
                "queries": EXPECTED_QUERY_SHA256,
            },
            "denominator": {"answerable": 60, "off_corpus": 10, "total": 70},
            "observed_embedding_dimensions": [dimension],
            "privacy": {"prompts_persisted": False},
            "provider_call_errors": {},
            "provider_calls": 1,
            "schema_version": 1,
            "status": "completed",
        }
        _write_json(directory / "summary.json", summary)
        _write_json(
            directory / "attestation.json",
            {
                "alias_contract": {
                    "alias": f"ragz-{cell_id}",
                    "client_sends_dimensions": False,
                    "expected_dimension": dimension,
                    "observed_dimensions": [dimension],
                    "underlying_model": model,
                },
                "artifacts_sha256": {
                    "per_query": _hash(per_query),
                    "provider_calls": _hash(provider_calls),
                },
                "cell": summary["cell"],
                "denominator": summary["denominator"],
                "error_count": 0,
                "provider_calls": 1,
                "schema_version": 1,
                "status": "completed",
            },
        )
        directories.append(directory)
    return directories


def test_seeded_statistics_are_reproducible_and_holm_is_monotone() -> None:
    assert bootstrap_ci([1.0, 2.0, 3.0], seed=7, samples=1_000) == bootstrap_ci(
        [1.0, 2.0, 3.0], seed=7, samples=1_000
    )
    assert sign_flip_pvalue([1.0] * 10, seed=7, samples=1_000) < 0.01
    corrected = holm_correction({"a": 0.01, "b": 0.02, "c": 0.9})
    assert corrected["a"]["holm_p"] <= corrected["b"]["holm_p"]
    assert corrected["c"]["holm_p"] == 0.9


def test_analyze_validates_ten_cells_and_refuses_section_evidence(tmp_path: Path) -> None:
    result = analyze(_cell_dirs(tmp_path), bootstrap_samples=100, seed=11)
    assert len(result["cells"]) == 10
    cell = result["cells"]["openai-text-embedding-3-small-d1024"]
    assert cell["retrieval_quality"]["section_evidence"]["available"] is False
    assert cell["cache_denominators"]["query_rows"] == {
        "total": 70,
        "cached": 0,
        "uncached": 70,
    }
    assert cell["cost"]["basis"] == "provider_calls_usage_only"
    assert len(result["paired_comparisons"]) == 9
    assert result["analysis"]["bootstrap_samples"] == 100


def test_legacy_unlabelled_short_provider_run_is_cache_contaminated(tmp_path: Path) -> None:
    result = analyze(_cell_dirs(tmp_path), bootstrap_samples=100)
    assert result["analysis"]["cache_contaminated_matrix"] is True
    assert len(result["analysis"]["cache_contaminated_cells"]) == 10
    assert all(
        "provider_calls_below_expected" in reason
        for cell_id in result["analysis"]["cache_contaminated_cells"]
        for reason in result["cells"][cell_id]["cache_denominators"]["contamination_reasons"]
        if reason.startswith("provider_calls_below_expected")
    )
    assert all(
        metric["metric"] != "total_with_judge"
        for comparison in result["paired_comparisons"].values()
        for metric in comparison["metrics"]
    )


def test_analyze_rejects_hash_tampering(tmp_path: Path) -> None:
    directories = _cell_dirs(tmp_path)
    path = directories[0] / "per_query.jsonl"
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(MatrixAnalysisError, match="hash"):
        analyze(directories, bootstrap_samples=100)


def test_cache_contamination_excludes_total_latency_and_spend_from_pareto(
    tmp_path: Path,
) -> None:
    directories = _cell_dirs(tmp_path)
    summary_path = directories[0] / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["cache_mode"] = "shared-cache-exploratory"
    _write_json(summary_path, summary)

    result = analyze(directories, bootstrap_samples=100)
    assert result["analysis"]["cache_contaminated_matrix"] is True
    assert len(result["analysis"]["cache_contaminated_cells"]) == 10
    assert sorted(EXPECTED_CELL_IDS)[0] in result["analysis"]["cache_contaminated_cells"]
    assert all(
        metric["metric"] != "total_with_judge"
        for comparison in result["paired_comparisons"].values()
        for metric in comparison["metrics"]
    )
    assert result["pareto_frontier"]["provider_spend_included"] is False
    assert all(
        "actual_provider_cost_usd" not in point for point in result["pareto_frontier"]["cells"]
    )
    report = markdown_report(result)
    assert "Observed provider spend is descriptive only" in report
    assert "total/generation/judge latency hypotheses are excluded" in report
    assert "| Cost (USD) |" not in report


def test_write_outputs_refuses_overwrite(tmp_path: Path) -> None:
    result = analyze(_cell_dirs(tmp_path / "fixture"), bootstrap_samples=100)
    output_json = tmp_path / "result.json"
    output_markdown = tmp_path / "result.md"
    write_outputs(result, output_json, output_markdown)
    with pytest.raises(OutputExistsError):
        write_outputs(result, output_json, output_markdown)
