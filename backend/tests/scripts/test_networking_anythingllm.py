import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_networking_anythingllm import (  # noqa: E402
    batches,
    embedding_configuration,
    generation_configuration,
    ranking_metrics,
    summarize,
    unique_document_ids,
    validate_storage_path,
    workspace_configuration,
)


def test_batches_cover_values_once_and_reject_zero() -> None:
    assert list(batches(list(range(10)), 4)) == [
        [0, 1, 2, 3],
        [4, 5, 6, 7],
        [8, 9],
    ]
    with pytest.raises(ValueError):
        list(batches([1], 0))


def test_ranking_metrics_deduplicate_repeated_segments() -> None:
    metrics = ranking_metrics(["a", "a", "x", "b"], {"a", "b"}, 3)
    assert metrics["recall_at_k"] == 1.0
    assert metrics["mrr_at_k"] == 1.0
    assert 0 < metrics["ndcg_at_k"] <= 1.0


def test_summary_excludes_off_corpus_and_errors_from_quality() -> None:
    records = [
        {
            "answerable": True,
            "error": None,
            "metrics": {"recall_at_k": 1.0, "mrr_at_k": 0.5, "ndcg_at_k": 0.75},
            "no_answer": False,
            "latency_ms": 10.0,
        },
        {
            "answerable": False,
            "error": None,
            "metrics": None,
            "no_answer": True,
            "latency_ms": 20.0,
        },
        {
            "answerable": True,
            "error": "RemoteProtocolError",
            "metrics": None,
            "no_answer": False,
            "latency_ms": 30.0,
        },
    ]

    result = summarize(records, top_k=5)

    assert result["quality_observations"] == 1
    assert result["mean_recall_at_k"] == 1.0
    assert result["abstention"]["f1"] == 1.0
    assert result["errors"] == 1


def test_storage_must_be_unique_child_of_explicit_root(tmp_path: Path) -> None:
    child = tmp_path / "run-1"
    assert validate_storage_path(child, tmp_path) == (child, tmp_path)
    with pytest.raises(ValueError):
        validate_storage_path(tmp_path, tmp_path)
    with pytest.raises(ValueError):
        validate_storage_path(tmp_path.parent / "outside", tmp_path)


def test_embedding_configuration_labels_hosted_and_native_tracks() -> None:
    native = embedding_configuration("native")
    hosted = embedding_configuration("litellm")
    assert "native-minilm" in native[1]
    assert native[2:] == (0, 0.0)
    assert "openai" in hosted[1]
    assert hosted[2:] == ("not_exposed_nonzero", None)
    with pytest.raises(ValueError):
        embedding_configuration("unknown")


def test_generation_configuration_pins_shared_litellm_answer_model() -> None:
    configuration = generation_configuration()

    assert "LLM_PROVIDER=litellm" in configuration
    assert "LITE_LLM_MODEL_PREF=gpt-5.6-luna" in configuration
    assert "LITE_LLM_MODEL_TOKEN_LIMIT=8192" in configuration
    assert "host.docker.internal:host-gateway" in configuration


def test_workspace_configuration_pins_luna_supported_temperature() -> None:
    configuration = workspace_configuration("networking-test", 50)

    assert configuration == {
        "name": "networking-test",
        "similarityThreshold": 0.0,
        "topN": 50,
        "openAiTemp": 1.0,
    }


def test_abstention_f1_is_zero_when_every_off_corpus_probe_is_missed() -> None:
    result = summarize(
        [
            {
                "answerable": False,
                "error": None,
                "metrics": None,
                "no_answer": False,
                "latency_ms": 1.0,
            }
        ],
        top_k=5,
    )
    assert result["abstention"]["f1"] == 0.0


def test_unique_intervals_are_filled_from_deeper_native_candidates() -> None:
    results = [
        {"metadata": {"docSource": value}}
        for value in ("a", "a", "a", "b", "b", "c", "d", "e", "f")
    ]
    assert unique_document_ids(results, 5) == ["a", "b", "c", "d", "e"]
