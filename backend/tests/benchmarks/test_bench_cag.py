import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[2] / "scripts" / "bench_cag.py"
SCHEMA_DIR = Path(__file__).parents[3] / "no_rel" / "benchmarks" / "cag" / "schemas"


def test_schedule_is_deterministic_and_contains_only_opaque_question_identity(
    tmp_path: Path,
) -> None:
    questions = tmp_path / "questions.json"
    first_output = tmp_path / "schedule-one.json"
    second_output = tmp_path / "schedule-two.json"
    questions.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "fixture_sha256": "a" * 64,
                "questions": [
                    {
                        "question_id": "q-001",
                        "stratum": "single_document_fact",
                    }
                ],
            }
        )
    )
    command = [
        sys.executable,
        str(SCRIPT),
        "schedule",
        "--questions",
        str(questions),
        "--variants",
        "ragz_rag_q1,ragz_full_snapshot_cag_warm",
        "--repetitions",
        "2",
        "--seed",
        "17",
    ]

    subprocess.run(  # noqa: S603 - fixed interpreter and repository script
        [*command, "--output", str(first_output)], check=True
    )
    subprocess.run(  # noqa: S603 - fixed interpreter and repository script
        [*command, "--output", str(second_output)], check=True
    )

    first = json.loads(first_output.read_text())
    second = json.loads(second_output.read_text())
    assert first == second
    assert len(first["assignments"]) == 4
    assert {row["variant"] for row in first["assignments"]} == {
        "ragz_rag_q1",
        "ragz_full_snapshot_cag_warm",
    }
    assert all(row["question_id"] == "q-001" for row in first["assignments"])
    assert all(
        {"question", "answer", "reference_answer"}.isdisjoint(row)
        for row in first["assignments"]
    )


def test_trial_schema_accepts_sanitized_row_and_rejects_raw_question(
    tmp_path: Path,
) -> None:
    sanitized = {
        "schema_version": 1,
        "trial_id": "trial-001",
        "pair_id": "pair-001",
        "question_id": "q-001",
        "stratum": "single_document_fact",
        "variant": "ragz_full_snapshot_cag_warm",
        "repetition": 1,
        "order_index": 1,
        "cache_state": "warm_hit",
        "status": "completed",
        "failure_type": None,
        "answerable": True,
        "answered": True,
        "metrics": {
            "groundedness": 1.0,
            "answer_relevance": 1.0,
            "citation_precision": 1.0,
            "citation_coverage": 1.0,
            "abstention_correct": 1.0,
        },
        "usage": {
            "prompt_tokens": 2000,
            "completion_tokens": 20,
            "cached_tokens": 1900,
            "cache_write_tokens": 0,
            "reasoning_tokens": 0,
            "cache_outcome": "hit",
        },
        "latency_ms": {"end_to_end": 100.0, "ttft": 40.0},
        "known_cost_usd": 0.0001,
    }
    valid = tmp_path / "valid.jsonl"
    invalid = tmp_path / "invalid.jsonl"
    valid.write_text(json.dumps(sanitized) + "\n")
    invalid.write_text(json.dumps({**sanitized, "question": "private text"}) + "\n")
    command = [
        sys.executable,
        str(SCRIPT),
        "validate",
        "--schema",
        str(SCHEMA_DIR / "trial.schema.json"),
        "--input",
    ]

    subprocess.run(  # noqa: S603 - fixed interpreter and repository script
        [*command, str(valid)], check=True
    )
    rejected = subprocess.run(  # noqa: S603 - fixed interpreter and repository script
        [*command, str(invalid)], capture_output=True, text=True
    )

    assert rejected.returncode != 0
    assert "question" in rejected.stderr
    assert "private text" not in rejected.stderr


def test_aggregate_keeps_failures_in_quality_and_pair_denominators(tmp_path: Path) -> None:
    def row(
        trial_id: str,
        pair_id: str,
        question_id: str,
        variant: str,
        *,
        status: str,
        groundedness: float | None,
        latency_ms: float,
    ) -> dict[str, object]:
        return {
            "schema_version": 1,
            "trial_id": trial_id,
            "pair_id": pair_id,
            "question_id": question_id,
            "stratum": "single_document_fact",
            "variant": variant,
            "repetition": 1,
            "order_index": 1,
            "cache_state": "not_requested",
            "status": status,
            "failure_type": None if status == "completed" else "timeout",
            "answerable": True,
            "answered": status == "completed",
            "metrics": {"groundedness": groundedness},
            "usage": {
                "prompt_tokens": 100 if status == "completed" else None,
                "completion_tokens": 10 if status == "completed" else None,
                "cached_tokens": 0 if status == "completed" else None,
                "cache_write_tokens": 0 if status == "completed" else None,
                "reasoning_tokens": 0 if status == "completed" else None,
                "cache_outcome": "not_requested",
            },
            "latency_ms": {"end_to_end": latency_ms, "ttft": None},
            "known_cost_usd": 0.001 if status == "completed" else None,
        }

    baseline = "ragz_rag_q1"
    candidate = "ragz_full_snapshot_cag_warm"
    trials = [
        row("b1", "p1", "q1", baseline, status="completed", groundedness=1.0, latency_ms=100),
        row("c1", "p1", "q1", candidate, status="completed", groundedness=1.0, latency_ms=50),
        row("b2", "p2", "q2", baseline, status="completed", groundedness=1.0, latency_ms=120),
        row("c2", "p2", "q2", candidate, status="failed", groundedness=None, latency_ms=200),
    ]
    trial_path = tmp_path / "trials.jsonl"
    output_path = tmp_path / "aggregate.json"
    trial_path.write_text("".join(json.dumps(trial) + "\n" for trial in trials))

    subprocess.run(  # noqa: S603 - fixed interpreter and repository script
        [
            sys.executable,
            str(SCRIPT),
            "aggregate",
            "--trials",
            str(trial_path),
            "--baseline-variant",
            baseline,
            "--bootstrap-samples",
            "1000",
            "--seed",
            "23",
            "--output",
            str(output_path),
        ],
        check=True,
    )

    aggregate = json.loads(output_path.read_text())
    subprocess.run(  # noqa: S603 - fixed interpreter and repository script
        [
            sys.executable,
            str(SCRIPT),
            "validate",
            "--schema",
            str(SCHEMA_DIR / "aggregate.schema.json"),
            "--input",
            str(output_path),
        ],
        check=True,
    )
    candidate_result = aggregate["variants"][candidate]
    assert candidate_result["assigned_n"] == 2
    assert candidate_result["completed_n"] == 1
    assert candidate_result["completion_rate"] == 0.5
    assert candidate_result["failure_counts"] == {"timeout": 1}
    assert candidate_result["metrics"]["groundedness"]["failure_inclusive_mean"] == 0.5
    assert candidate_result["usage"]["prompt_tokens"] == {
        "known_n": 1,
        "mean_known": 100.0,
        "total": 100,
        "unknown_n": 1,
    }
    assert candidate_result["usage"]["cache_outcomes"] == {"not_requested": 2}
    assert candidate_result["known_cost_usd"] == {
        "complete": False,
        "known_n": 1,
        "mean_known": 0.001,
        "total_known": 0.001,
        "unknown_n": 1,
    }
    delta = candidate_result["paired_deltas"]["groundedness"]
    assert delta["query_n"] == 2
    assert delta["estimate"] == -0.5
    assert delta["ci95"] == [-1.0, 0.0]
