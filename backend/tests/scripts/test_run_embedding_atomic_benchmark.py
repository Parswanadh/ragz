import json
import sys
from pathlib import Path

import httpx
import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from embedding_benchmark_matrix import cells  # noqa: E402
from run_embedding_atomic_benchmark import (  # noqa: E402
    INPUT_COUNTS,
    BenchmarkConfig,
    BenchmarkValidationError,
    build_schedule,
    fixed_inputs,
    recompute_summary,
    run_benchmark,
    summarize_records,
)


def _config(output: Path, *, warmups: int = 1) -> BenchmarkConfig:
    return BenchmarkConfig(
        output=output,
        warmups=warmups,
        repetitions=25,
        max_requests=1_000,
        max_input_tokens=100_000,
        max_cost_usd=5.0,
        bootstrap_samples=100,
        selected_cells=(cells()[0],),
    )


def _transport(cell_dimension: int, expected_tokens: dict[int, int]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.url.path == "/v1/embeddings"
        assert "dimensions" not in body
        count = len(body["input"])
        return httpx.Response(
            200,
            json={
                "data": [{"embedding": [0.0] * cell_dimension} for _ in range(count)],
                "usage": {"total_tokens": expected_tokens[count]},
            },
        )

    return httpx.MockTransport(handler)


def test_matrix_schedule_is_seeded_and_counterbalanced() -> None:
    cell = cells()[0]
    first = build_schedule(cell, seed=7, repetition=1)
    second = build_schedule(cell, seed=7, repetition=1)
    reverse = build_schedule(cell, seed=7, repetition=2)

    assert first == second
    assert reverse == tuple(reversed(first))
    assert {(condition.input_count, condition.client_mode) for condition in first} == {
        (count, mode) for count in INPUT_COUNTS for mode in ("persistent", "new")
    }


def test_fixed_inputs_are_immutable_and_not_mutated() -> None:
    original = fixed_inputs(3)
    assert isinstance(original, tuple)
    with pytest.raises(TypeError):
        original[0] = "mutation"  # type: ignore[index]
    assert fixed_inputs(3) == original


def test_mock_matrix_persists_privacy_safe_rows_and_recomputes_summary(tmp_path: Path) -> None:
    output = tmp_path / "atomic"
    config = _config(output)
    secret = "test-key-never-persist"  # noqa: S105
    result = run_benchmark(
        config,
        api_key=secret,
        transport=_transport(
            config.selected_cells[0].dimension,
            dict(config.expected_tokens_by_count),
        ),
    )

    assert result == output.resolve()
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    rows = [
        json.loads(line)
        for line in (output / "per_request.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "completed"
    assert len(rows) == 8 * (25 + 1)
    assert sum(bool(row["scored"]) for row in rows) == 8 * 25
    assert summary["observations"] == 8 * 25
    assert recompute_summary(output / "per_request.jsonl", config) == summary
    assert all(set(row["stage_timings_ms"]) == {
        "request_build_ms",
        "http_wall_ms",
        "response_decode_ms",
        "vector_validation_ms",
    } for row in rows)
    assert all(
        abs(sum(row["stage_timings_ms"].values()) - row["total_ms"]) <= 0.00001
        for row in rows
    )
    serialized = "\n".join(
        [
            (output / "manifest.json").read_text(encoding="utf-8"),
            (output / "per_request.jsonl").read_text(encoding="utf-8"),
            (output / "summary.json").read_text(encoding="utf-8"),
        ]
    )
    assert secret not in serialized
    assert all("synthetic networking" not in json.dumps(row) for row in rows)
    assert manifest["input_text_persisted"] is False


def test_summary_rejects_mutated_width_and_incomplete_denominator(tmp_path: Path) -> None:
    config = _config(tmp_path / "unused")
    transport = _transport(
        config.selected_cells[0].dimension,
        dict(config.expected_tokens_by_count),
    )
    output = run_benchmark(config, api_key="secret", transport=transport)
    rows = [
        json.loads(line)
        for line in (output / "per_request.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    scored_index = next(index for index, row in enumerate(rows) if row["scored"])
    mutated = [dict(row) for row in rows]
    mutated[scored_index]["dimension_actual"] = config.selected_cells[0].dimension - 1
    with pytest.raises(BenchmarkValidationError, match="width"):
        summarize_records(mutated, config)
    token_mutation = [dict(row) for row in rows]
    token_mutation[scored_index]["total_tokens"] += 1
    with pytest.raises(BenchmarkValidationError, match="token"):
        summarize_records(token_mutation, config)
    with pytest.raises(BenchmarkValidationError, match="denominator"):
        summarize_records(rows[:-1], config)


def test_output_path_is_never_overwritten(tmp_path: Path) -> None:
    output = tmp_path / "existing"
    output.mkdir()
    (output / "sentinel").write_text("keep", encoding="utf-8")
    config = _config(output)
    with pytest.raises(FileExistsError):
        run_benchmark(
            config,
            api_key="secret",  # noqa: S105
            transport=httpx.MockTransport(lambda _: httpx.Response(500)),
        )
    assert (output / "sentinel").read_text(encoding="utf-8") == "keep"
