import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_embedding_endpoint_probe import summarize, validate_proxy_fingerprint  # noqa: E402


def _records() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    sequence = 0
    for repetition in range(1, 3):
        forward = ("direct_1", "proxy_1", "direct_3", "proxy_3")
        order = forward if repetition % 2 else tuple(reversed(forward))
        for order_index, condition in enumerate(order, 1):
            sequence += 1
            count = int(condition.rsplit("_", 1)[1])
            records.append(
                {
                    "sequence": sequence,
                    "repetition": repetition,
                    "order_index": order_index,
                    "condition": condition,
                    "path": (
                        "direct OpenAI"
                        if condition.startswith("direct")
                        else "LiteLLM to OpenAI"
                    ),
                    "input_count": count,
                    "elapsed_ms": 100.0 + sequence,
                    "dimension": 1536,
                    "total_tokens": count * 5,
                    "status_code": 200,
                    "error": None,
                }
            )
    return records


def test_summary_recomputes_complete_zero_error_conditions() -> None:
    result = summarize(_records(), repetitions=2)

    assert result["conditions"]["direct_1"]["observations"] == 2
    assert result["conditions"]["proxy_3"]["input_count"] == 3
    assert result["proxy_minus_direct_mean_ms"]["one_input"] == 0.0


def test_summary_rejects_errors_and_incomplete_denominators() -> None:
    rows = _records()
    rows[0]["error"] = "UpstreamError"
    with pytest.raises(ValueError, match="failed"):
        summarize(rows, repetitions=2)
    with pytest.raises(ValueError, match="incomplete"):
        summarize(_records()[:-1], repetitions=2)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("order_index", 4, "order"),
        ("status_code", 500, "metadata"),
        ("input_count", 3, "metadata"),
        ("total_tokens", 15, "metadata"),
        ("path", "wrong path", "metadata"),
        ("dimension", 1024, "dimension"),
    ],
)
def test_summary_rejects_tampered_row_evidence(
    field: str, value: object, message: str
) -> None:
    rows = _records()
    rows[0][field] = value

    with pytest.raises(ValueError, match=message):
        summarize(rows, repetitions=2)


def test_proxy_fingerprint_is_strict_sha256() -> None:
    assert validate_proxy_fingerprint("a" * 64) == "a" * 64
    with pytest.raises(ValueError):
        validate_proxy_fingerprint("not-a-fingerprint")
