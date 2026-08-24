#!/usr/bin/env python3
"""Bounded AnythingLLM v1.16.0 networking retrieval benchmark.

Consumes the temporary 20-page-segment dataset, uses AnythingLLM's native
MiniLM embedder/chunker and LanceDB, and writes only IDs/metrics/timings. The
temporary storage root is removed on exit because it contains textbook text.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import shutil
import socket
import statistics
import subprocess
import time
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

IMAGE = "mintplexlabs/anythingllm:1.16.0"
IMAGE_DIGEST = "sha256:68bcedecb720e3fadde986bcc4f3aad20059fa64805bc9b306a3023244947515"
IMAGE_REF = f"mintplexlabs/anythingllm@{IMAGE_DIGEST}"
RELEASE_COMMIT = "55b6ebcea132f0d7ac146da99a0cd0db507b9030"
RUNNER_VERSION = "4.0"
ANSWER_MODEL = "gpt-5.6-luna"
ANSWER_TEMPERATURE = 1.0
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_EMBEDDING_DIMENSION = 1536


def batches[T](values: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    if size < 1:
        raise ValueError("batch size must be positive")
    for start in range(0, len(values), size):
        yield values[start : start + size]


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def ranking_metrics(retrieved: list[str], relevant: set[str], k: int) -> dict[str, float]:
    ranked = list(dict.fromkeys(retrieved))[:k]
    hit_ranks = [rank for rank, item in enumerate(ranked, 1) if item in relevant]
    recall = len({item for item in ranked if item in relevant}) / len(relevant)
    mrr = 1.0 / hit_ranks[0] if hit_ranks else 0.0
    dcg = sum(1.0 / math.log2(rank + 1) for rank in hit_ranks)
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(len(relevant), k) + 1))
    return {"recall_at_k": recall, "mrr_at_k": mrr, "ndcg_at_k": dcg / ideal}


def unique_document_ids(results: list[dict[str, Any]], top_k: int) -> list[str]:
    return list(
        dict.fromkeys(
            str(item.get("metadata", {}).get("docSource", ""))
            for item in results
            if item.get("metadata", {}).get("docSource")
        )
    )[:top_k]


def summarize(records: list[dict[str, Any]], *, top_k: int) -> dict[str, Any]:
    quality = [
        row
        for row in records
        if row["answerable"] and row["error"] is None and row["metrics"] is not None
    ]
    abstention = [row for row in records if row["error"] is None]
    tp = sum(not row["answerable"] and row["no_answer"] for row in abstention)
    fp = sum(row["answerable"] and row["no_answer"] for row in abstention)
    fn = sum(not row["answerable"] and not row["no_answer"] for row in abstention)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else 0.0
        if tp + fp + fn
        else None
    )
    latencies = [float(row["latency_ms"]) for row in abstention]

    def mean_metric(name: str) -> float | None:
        return statistics.mean(float(row["metrics"][name]) for row in quality) if quality else None

    return {
        "top_k": top_k,
        "observations": len(records),
        "quality_observations": len(quality),
        "errors": sum(row["error"] is not None for row in records),
        "mean_recall_at_k": mean_metric("recall_at_k"),
        "mean_mrr_at_k": mean_metric("mrr_at_k"),
        "mean_ndcg_at_k": mean_metric("ndcg_at_k"),
        "abstention": {
            "true_positive": tp,
            "false_positive": fp,
            "false_negative": fn,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        },
        "latency_ms": {
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "p99": percentile(latencies, 0.99),
        },
    }


def validate_query_grid(
    records: Sequence[Mapping[str, Any]],
    queries: Sequence[Mapping[str, Any]],
    repetitions: int,
) -> None:
    """Require the complete query-by-repetition population before scoring.

    A partially populated run (or one containing a failed retrieval) is not a
    benchmark result. Counter-based comparison also handles malformed input
    with duplicate query IDs without silently collapsing the denominator.
    """

    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    try:
        expected = Counter(
            (str(query["query_id"]), repetition)
            for query in queries
            for repetition in range(1, repetitions + 1)
        )
        actual = Counter(
            (str(record["query_id"]), int(record["repetition"])) for record in records
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("query/repetition grid contains malformed records") from exc
    if actual != expected:
        raise ValueError("query/repetition grid is incomplete or duplicated")
    if any(record.get("error") is not None for record in records):
        raise ValueError("query/repetition grid contains failed retrievals")


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _command(
    args: list[str],
    *,
    check: bool = True,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        args,
        check=check,
        capture_output=True,
        text=True,
        env=env,
    )


def _required_litellm_api_key(env: Mapping[str, str] | None = None) -> str:
    """Return the LiteLLM key without ever including it in a command argument."""

    source = os.environ if env is None else env
    key = source.get("RAGZ_LITELLM_MASTER_KEY") or source.get("LITELLM_MASTER_KEY")
    if not key:
        raise RuntimeError(
            "RAGZ_LITELLM_MASTER_KEY (or LITELLM_MASTER_KEY) is required for LiteLLM"
        )
    return key


def safe_http_status(exc: BaseException) -> int | None:
    """Extract only a non-sensitive upstream status from HTTP client errors."""
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    return int(status_code) if isinstance(status_code, int) else None


def _port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _wait_ready(client: Any, timeout_seconds: int = 180) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = "not attempted"
    while time.monotonic() < deadline:
        try:
            if (await client.get("/api/ping")).status_code == 200:
                return
            last_error = "non-200 response"
        except Exception as exc:  # noqa: BLE001 - summarized without response body
            last_error = type(exc).__name__
        await asyncio.sleep(1)
    raise TimeoutError(f"AnythingLLM readiness timeout: {last_error}")


async def vector_search_with_retries(
    client: Any,
    path: str,
    payload: Mapping[str, object],
    *,
    max_retries: int,
) -> tuple[Any, int]:
    """Retry only transient native-search failures and expose the retry count."""
    transient_statuses = {429, 500, 502, 503, 504}
    for attempt in range(max_retries + 1):
        response = await client.post(path, json=dict(payload))
        if response.status_code < 400:
            return response, attempt
        if response.status_code not in transient_statuses or attempt == max_retries:
            response.raise_for_status()
        await asyncio.sleep(min(2.0**attempt, 5.0))
    raise AssertionError("unreachable retry loop")


def _memory_bytes(container: str) -> int | None:
    result = _command(
        ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", container],
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    raw = result.stdout.split("/", 1)[0].strip()
    units = {"KiB": 1024, "MiB": 1024**2, "GiB": 1024**3}
    for suffix, multiplier in units.items():
        if raw.endswith(suffix):
            try:
                return int(float(raw.removesuffix(suffix)) * multiplier)
            except ValueError:
                return None
    return None


def _container_state(container: str) -> dict[str, object] | None:
    result = _command(
        ["docker", "inspect", "--format", "{{json .State}}", container],
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        state = json.loads(result.stdout)
    except ValueError:
        return None
    if not isinstance(state, dict):
        return None
    return {
        "status": state.get("Status"),
        "running": state.get("Running"),
        "oom_killed": state.get("OOMKilled"),
        "exit_code": state.get("ExitCode"),
        "error": str(state.get("Error") or "")[:200],
    }


def _dataset_hash(dataset: Path) -> str:
    digest = hashlib.sha256()
    for name in ("documents.jsonl", "queries.jsonl", "qrels.jsonl"):
        digest.update(name.encode())
        digest.update((dataset / name).read_bytes())
    return digest.hexdigest()


def validate_storage_path(storage: Path, allowed_root: Path) -> tuple[Path, Path]:
    storage = storage.resolve()
    allowed_root = allowed_root.resolve()
    if storage == allowed_root or not storage.is_relative_to(allowed_root):
        raise ValueError("storage must be a unique child of the explicit allowed root")
    if storage.is_symlink() or allowed_root.is_symlink():
        raise ValueError("storage paths must not be symlinks")
    return storage, allowed_root


def _embedding_cell(model: str | None, dimension: int | None) -> Any:
    """Resolve an OpenAI matrix cell without duplicating the matrix contract."""

    from embedding_benchmark_matrix import cell_for

    return cell_for(
        model or DEFAULT_EMBEDDING_MODEL,
        dimension if dimension is not None else DEFAULT_EMBEDDING_DIMENSION,
    )


def embedding_configuration(
    engine: str,
    model: str | None = None,
    dimension: int | None = None,
    alias: str | None = None,
    dataset_id: str | None = None,
    base_path: str = "http://host.docker.internal:54000/v1",
) -> tuple[list[str], str, object, object]:
    """Build AnythingLLM environment flags for one embedding track.

    The four-element return value is retained for callers of the original
    runner.  Hosted configuration is now selected by a matrix cell and sends
    only that cell's immutable LiteLLM alias to AnythingLLM.
    """

    if engine == "native":
        if model is not None or dimension is not None or alias is not None:
            raise ValueError("native embedding does not accept hosted model settings")
        return (
            [
                "-e",
                "EMBEDDING_ENGINE=native",
                "-e",
                "EMBEDDING_MODEL_PREF=Xenova/all-MiniLM-L6-v2",
            ],
            "common-20-page-segments-native-minilm-lancedb",
            0,
            0.0,
        )
    if engine == "litellm":
        cell = _embedding_cell(model, dimension)
        if alias is not None and alias != cell.alias:
            raise ValueError(f"LiteLLM alias {alias!r} is not the fixed alias for {cell.cell_id}")
        prefix = dataset_id or "common-20-page-segments"
        return (
            [
                "--add-host",
                "host.docker.internal:host-gateway",
                "-e",
                "EMBEDDING_ENGINE=litellm",
                "-e",
                f"EMBEDDING_MODEL_PREF={cell.alias}",
                "-e",
                f"LITE_LLM_BASE_PATH={base_path}",
                "-e",
                "LITE_LLM_API_KEY",
            ],
            f"{prefix}-openai-lancedb",
            "not_exposed_nonzero",
            None,
        )
    raise ValueError("embedding engine must be native or litellm")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _attestation_records(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    cells = payload.get("cells")
    if isinstance(cells, list):
        return [item for item in cells if isinstance(item, Mapping)]
    # Endpoint probes use one top-level model/dimension record.  Keep this
    # shape supported while requiring the fixed alias supplied by the caller.
    return [payload]


def embedding_attestation(
    artifact: Path,
    *,
    model: str,
    dimension: int,
    alias: str,
    proxy_fingerprint: str,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Validate a CLI-supplied, privacy-safe proof of alias vector width.

    The artifact may contain a single endpoint-probe record or a ``cells``
    array from the embedding matrix runner.  The matching record must bind the
    model, fixed alias, requested width, and measured width.  A proxy
    fingerprint, when present, must match the runner's fingerprint.
    """

    path = artifact.expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"embedding width attestation does not exist: {path}")
    artifact_sha256 = _sha256_file(path)
    if expected_sha256 is not None:
        if len(expected_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in expected_sha256
        ):
            raise ValueError("embedding width attestation hash must be a lowercase SHA-256")
        if expected_sha256 != artifact_sha256:
            raise ValueError("embedding width attestation hash does not match artifact")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("embedding width attestation must be valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("embedding width attestation must contain an object")
    match: Mapping[str, Any] | None = None
    for record in _attestation_records(payload):
        record_alias = record.get("alias") or record.get("embedding_litellm_model_name")
        record_model = record.get("model") or record.get("embedding_model")
        record_dimension = record.get("dimension") or record.get("expected_dimension")
        if record_alias == alias and record_model == model and record_dimension == dimension:
            match = record
            break
    # Single-model endpoint probes do not persist an alias; the alias is still
    # cryptographically bound by this runner's deterministic cell mapping.
    if match is None and "cells" not in payload:
        record_model = payload.get("model") or payload.get("embedding_model")
        record_dimension = payload.get("dimension") or payload.get("expected_dimension")
        if record_model == model and record_dimension == dimension:
            match = payload
    if match is None:
        raise ValueError("embedding alias is not present in the width attestation")
    actual = match.get("actual_dimension")
    if actual is None:
        actual = match.get("actual_width")
    if actual is None:
        actual = match.get("vector_dimension")
    if actual is None:
        raise ValueError(
            "embedding width attestation has no explicit measured actual vector width"
        )
    try:
        actual_dimension = int(actual)
    except (TypeError, ValueError) as exc:
        raise ValueError("embedding width attestation has no actual vector width") from exc
    if actual_dimension != dimension:
        raise ValueError(
            f"embedding alias {alias!r} is attested at width {actual_dimension}, "
            f"expected {dimension}"
        )
    status = str(match.get("probe_status") or match.get("status") or "").lower()
    if status not in {"passed", "completed", "attested", "post_run_attested"}:
        raise ValueError("embedding width attestation is not successful")
    attested_proxy = match.get("embedding_proxy_fingerprint_sha256") or match.get(
        "proxy_fingerprint_sha256"
    )
    if attested_proxy != proxy_fingerprint:
        raise ValueError("embedding width attestation proxy fingerprint does not match")
    return {
        "artifact": str(path),
        "artifact_path": str(path),
        "artifact_sha256": artifact_sha256,
        "sha256": artifact_sha256,
        "actual_dimension": actual_dimension,
        "alias": alias,
        "model": model,
        "requested_dimension": dimension,
    }


def _dataset_identity(
    dataset: Path,
    documents: Sequence[Mapping[str, Any]],
    queries: Sequence[Mapping[str, Any]],
    qrels: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Use a converted dataset manifest when present, with safe count fallback."""

    path = dataset / "manifest.json"
    payload: Mapping[str, Any] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            loaded = None
        if isinstance(loaded, Mapping):
            payload = loaded
    dataset_id = str(payload.get("dataset_id") or payload.get("id") or dataset.name)

    counts = payload.get("counts")
    nested_counts = counts if isinstance(counts, Mapping) else {}

    def count(name: str, fallback: int, *aliases: str) -> int:
        for key in (name, *aliases):
            value = payload.get(key)
            if isinstance(value, int) and value >= 0:
                return value
            nested = nested_counts.get(key)
            if isinstance(nested, int) and nested >= 0:
                return nested
        return fallback

    return {
        "dataset_id": dataset_id,
        "dataset_manifest_sha256": _sha256_file(path) if path.is_file() else None,
        "document_count": count("document_count", len(documents), "documents"),
        "query_count": count("query_count", len(queries), "queries"),
        "qrel_count": count("qrel_count", len(qrels), "qrels"),
    }


def generation_configuration(
    model: str = ANSWER_MODEL,
    base_path: str = "http://host.docker.internal:54000/v1",
) -> list[str]:
    return [
        "--add-host",
        "host.docker.internal:host-gateway",
        "-e",
        "LLM_PROVIDER=litellm",
        "-e",
        f"LITE_LLM_MODEL_PREF={model}",
        "-e",
        "LITE_LLM_MODEL_TOKEN_LIMIT=8192",
        "-e",
        f"LITE_LLM_BASE_PATH={base_path}",
        "-e",
        "LITE_LLM_API_KEY",
    ]


def workspace_configuration(name: str, candidate_depth: int) -> dict[str, Any]:
    """Build a Luna-compatible AnythingLLM workspace configuration."""
    return {
        "name": name,
        "similarityThreshold": 0.0,
        "topN": candidate_depth,
        "openAiTemp": ANSWER_TEMPERATURE,
    }


def validate_indexed_vector_count(vector_count: object, document_count: int) -> int:
    if isinstance(vector_count, bool) or not isinstance(vector_count, int):
        raise RuntimeError("AnythingLLM vector count response is malformed")
    if vector_count < document_count:
        raise RuntimeError(
            f"AnythingLLM vector count {vector_count} is below input document count "
            f"{document_count}"
        )
    return vector_count


async def run(args: argparse.Namespace) -> Path:
    import httpx

    dataset: Path = args.dataset.resolve()
    output: Path = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    output.mkdir(parents=True)
    documents = _jsonl(dataset / "documents.jsonl")
    queries = _jsonl(dataset / "queries.jsonl")
    qrels = _jsonl(dataset / "qrels.jsonl")
    dataset_identity = _dataset_identity(dataset, documents, queries, qrels)
    qrels_by_query: dict[str, set[str]] = {}
    for row in qrels:
        if float(row.get("relevance", 0)) > 0:
            qrels_by_query.setdefault(str(row["query_id"]), set()).add(str(row["doc_id"]))
    storage, _ = validate_storage_path(args.storage, args.allowed_storage_root)
    if storage.exists():
        raise FileExistsError(f"refusing existing storage {storage}")
    embedding_model_arg = getattr(args, "embedding_model", None)
    embedding_dimension_arg = getattr(args, "embedding_dimension", None)
    embedding_alias_arg = getattr(args, "embedding_litellm_model_name", None)
    embedding_args, track, provider_calls, hosted_cost = embedding_configuration(
        args.embedding_engine,
        model=embedding_model_arg,
        dimension=embedding_dimension_arg,
        alias=embedding_alias_arg,
        dataset_id=dataset_identity["dataset_id"],
        base_path=args.litellm_container_base_url,
    )
    embedding_model = (
        DEFAULT_EMBEDDING_MODEL
        if args.embedding_engine == "litellm" and embedding_model_arg is None
        else embedding_model_arg
    )
    embedding_dimension = (
        DEFAULT_EMBEDDING_DIMENSION
        if args.embedding_engine == "litellm" and embedding_dimension_arg is None
        else embedding_dimension_arg
    )
    embedding_alias: str | None = None
    proxy_fingerprint = str(args.embedding_proxy_fingerprint or "")
    if args.embedding_engine == "litellm" and (
        len(proxy_fingerprint) != 64
        or any(character not in "0123456789abcdef" for character in proxy_fingerprint)
    ):
        raise ValueError(
            "litellm embedding runs require a lowercase SHA-256 --embedding-proxy-fingerprint"
        )
    width_attestation: dict[str, Any] | None = None
    if args.embedding_engine == "litellm":
        cell = _embedding_cell(embedding_model, embedding_dimension)
        embedding_model = cell.model
        embedding_dimension = cell.dimension
        embedding_alias = cell.alias
        width_attestation_path = getattr(args, "embedding_width_attestation", None)
        if width_attestation_path is None:
            raise ValueError(
                "litellm embedding runs require a CLI-supplied embedding width attestation"
            )
        width_attestation = embedding_attestation(
            width_attestation_path,
            model=cell.model,
            dimension=cell.dimension,
            alias=cell.alias,
            proxy_fingerprint=proxy_fingerprint,
            expected_sha256=getattr(args, "embedding_width_attestation_sha256", None),
        )
    storage.mkdir(parents=True)
    if args.embedding_engine == "native" and args.model_cache:
        shutil.copytree(args.model_cache.resolve(), storage / "models")
    container = f"ragz-networking-anything-{uuid4().hex[:8]}"
    port = _port()
    stage = "startup"
    memory_samples: list[int] = []
    records: list[dict[str, Any]] = []
    uploads_completed = 0
    index_batches_completed = 0
    locations_indexed = 0
    active_query_id: str | None = None
    indexing_started = time.perf_counter()
    indexing_ms: float | None = None
    vector_count: int | None = None
    docker_env = os.environ.copy()
    if args.embedding_engine == "litellm":
        docker_env["LITE_LLM_API_KEY"] = _required_litellm_api_key(docker_env)
    try:
        _command(
            [
                "docker",
                "run",
                "-d",
                "--name",
                container,
                "--memory",
                args.memory_limit,
                "--cpus",
                str(args.cpus),
                "--cap-add",
                "SYS_ADMIN",
                "-p",
                f"127.0.0.1:{port}:3001",
                "-v",
                f"{storage}:/app/server/storage",
                "-e",
                "STORAGE_DIR=/app/server/storage",
                "-e",
                "DISABLE_TELEMETRY=true",
                *(
                    ["--network", args.docker_network]
                    if args.docker_network
                    else []
                ),
                *generation_configuration(
                    args.answer_model, args.litellm_container_base_url
                ),
                *embedding_args,
                "-e",
                "VECTOR_DB=lancedb",
                IMAGE_REF,
            ],
            env=docker_env,
        )
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}",
            timeout=httpx.Timeout(900.0, connect=30.0),
        ) as client:
            await _wait_ready(client)
            memory = _memory_bytes(container)
            if memory is not None:
                memory_samples.append(memory)
            key_response = await client.post(
                "/api/system/generate-api-key", json={"name": "networking-benchmark"}
            )
            key_response.raise_for_status()
            secret = key_response.json().get("apiKey", {}).get("secret")
            if not secret:
                raise RuntimeError("AnythingLLM API key generation failed")
            client.headers["Authorization"] = f"Bearer {secret}"
            workspace_response = await client.post(
                "/api/v1/workspace/new",
                json=workspace_configuration(f"networking-{uuid4().hex[:8]}", args.candidate_depth),
            )
            workspace_response.raise_for_status()
            slug = str(workspace_response.json()["workspace"]["slug"])
            locations: list[str] = []
            stage = "raw_text_upload"
            for index, document in enumerate(documents, 1):
                response = await client.post(
                    "/api/v1/document/raw-text",
                    json={
                        "textContent": str(document["text"]),
                        "metadata": {
                            "title": f"{document['doc_id']}.txt",
                            "docSource": str(document["doc_id"]),
                            "chunkSource": str(document["doc_id"]),
                        },
                    },
                )
                response.raise_for_status()
                body = response.json()
                if not body.get("success") or not body.get("documents"):
                    raise RuntimeError("AnythingLLM raw-text upload failed")
                locations.append(str(body["documents"][0]["location"]))
                uploads_completed += 1
                if index % 25 == 0:
                    print(f"anythingllm uploaded {index}/{len(documents)}", flush=True)
            stage = "batched_native_indexing"
            for batch_index, location_batch in enumerate(
                batches(locations, args.index_batch_size), 1
            ):
                response = await client.post(
                    f"/api/v1/workspace/{slug}/update-embeddings",
                    json={"adds": list(location_batch), "deletes": []},
                )
                response.raise_for_status()
                index_batches_completed += 1
                locations_indexed += len(location_batch)
                memory = _memory_bytes(container)
                if memory is not None:
                    memory_samples.append(memory)
                print(
                    f"anythingllm indexed batch {batch_index}/"
                    f"{math.ceil(len(locations) / args.index_batch_size)}",
                    flush=True,
                )
            vector_count_response = await client.get("/api/v1/system/vector-count")
            vector_count_response.raise_for_status()
            vector_count = validate_indexed_vector_count(
                vector_count_response.json().get("vectorCount"), len(documents)
            )
            indexing_ms = (time.perf_counter() - indexing_started) * 1000
            stage = "warmup"
            for _ in range(args.warmups):
                for query in queries:
                    active_query_id = str(query["query_id"])
                    response, _ = await vector_search_with_retries(
                        client,
                        f"/api/v1/workspace/{slug}/vector-search",
                        {
                            "query": str(query["query"]),
                            "topN": args.candidate_depth,
                            "scoreThreshold": 0.0,
                        },
                        max_retries=args.retrieval_retries,
                    )
                    response.raise_for_status()
            stage = "scored_retrieval"
            for repetition in range(1, args.repetitions + 1):
                for query in queries:
                    started_at = time.perf_counter()
                    error: str | None = None
                    results: list[dict[str, Any]] = []
                    retries = 0
                    try:
                        active_query_id = str(query["query_id"])
                        response, retries = await vector_search_with_retries(
                            client,
                            f"/api/v1/workspace/{slug}/vector-search",
                            {
                                "query": str(query["query"]),
                                "topN": args.candidate_depth,
                                "scoreThreshold": 0.0,
                            },
                            max_retries=args.retrieval_retries,
                        )
                        response.raise_for_status()
                        results = list(response.json().get("results", []))
                    except Exception as exc:  # noqa: BLE001 - typed in artifact
                        error = type(exc).__name__
                    latency_ms = (time.perf_counter() - started_at) * 1000
                    retrieved = unique_document_ids(results, args.top_k)
                    answerable = bool(query.get("answerable", True))
                    metrics = (
                        ranking_metrics(
                            retrieved,
                            qrels_by_query[str(query["query_id"])],
                            args.top_k,
                        )
                        if answerable and error is None
                        else None
                    )
                    records.append(
                        {
                            "query_id": str(query["query_id"]),
                            "repetition": repetition,
                            "retrieved": retrieved,
                            "metrics": metrics,
                            "answerable": answerable,
                            "no_answer": not retrieved,
                            "latency_ms": round(latency_ms, 4),
                            "error": error,
                            "retries": retries,
                        }
                    )
            memory = _memory_bytes(container)
            if memory is not None:
                memory_samples.append(memory)
        # Do not emit quality metrics for a partial or error-containing
        # population: those observations cannot support a reliable benchmark.
        validate_query_grid(records, queries, args.repetitions)
        summary = summarize(records, top_k=args.top_k)
        summary["indexing_ms"] = indexing_ms
        summary["peak_container_memory_bytes"] = max(memory_samples, default=None)
        summary["ingestion_progress"] = {
            "uploads_completed": uploads_completed,
            "index_batches_completed": index_batches_completed,
            "locations_indexed": locations_indexed,
        }
        status = "completed"
    except Exception as exc:
        status = "failed"
        container_state = _container_state(container)
        summary = {
            "status": status,
            "stage": stage,
            "error_type": type(exc).__name__,
            "upstream_http_status": safe_http_status(exc),
            "query_id": active_query_id,
            "quality_score_emitted": False,
            "indexing_ms": indexing_ms,
            "peak_container_memory_bytes": max(memory_samples, default=None),
            "container_state": container_state,
            "ingestion_progress": {
                "uploads_completed": uploads_completed,
                "index_batches_completed": index_batches_completed,
                "locations_indexed": locations_indexed,
            },
        }
        (output / "failure.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    finally:
        _command(["docker", "rm", "-f", container], check=False)
        shutil.rmtree(storage, ignore_errors=True)

    if records:
        with (output / "per_query.jsonl").open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest = {
        "schema_version": 1,
        "runner_version": RUNNER_VERSION,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "status": status,
        "system_id": "anythingllm-v1.16.0",
        "image": IMAGE,
        "executed_image_ref": IMAGE_REF,
        "image_digest": IMAGE_DIGEST,
        "release_commit": RELEASE_COMMIT,
        "track": track,
        "dataset_id": dataset_identity["dataset_id"],
        "dataset_manifest_sha256": dataset_identity["dataset_manifest_sha256"],
        "embedding_model": (
            embedding_model if args.embedding_engine == "litellm" else "Xenova/all-MiniLM-L6-v2"
        ),
        "embedding_dimension": (embedding_dimension if args.embedding_engine == "litellm" else 384),
        "embedding_underlying_model": (
            embedding_model if args.embedding_engine == "litellm" else "Xenova/all-MiniLM-L6-v2"
        ),
        "embedding_requested_dimension": (
            embedding_dimension if args.embedding_engine == "litellm" else 384
        ),
        "embedding_litellm_model_name": embedding_alias,
        "embedding_alias": embedding_alias,
        "embedding_provider": "openai" if args.embedding_engine == "litellm" else "native",
        "embedding_transport": "litellm" if args.embedding_engine == "litellm" else "local",
        "embedding_proxy_fingerprint_sha256": (
            proxy_fingerprint if args.embedding_engine == "litellm" else None
        ),
        "embedding_width_attestation": width_attestation,
        "embedding_width_attestation_artifact": (
            width_attestation["artifact"] if width_attestation else None
        ),
        "embedding_width_attestation_sha256": (
            width_attestation["artifact_sha256"] if width_attestation else None
        ),
        "embedding_attestation_artifact": (
            width_attestation["artifact"] if width_attestation else None
        ),
        "embedding_attestation_sha256": (
            width_attestation["artifact_sha256"] if width_attestation else None
        ),
        "embedding_actual_dimension": (
            width_attestation["actual_dimension"] if width_attestation else None
        ),
        "answer_model": args.answer_model,
        "answer_provider": "litellm",
        "answer_model_configured": True,
        "answer_temperature_configured": ANSWER_TEMPERATURE,
        "answer_generation_executed": False,
        "answer_provider_calls": 0,
        "dataset_hash_sha256": _dataset_hash(dataset),
        "document_count": dataset_identity["document_count"],
        "query_count": dataset_identity["query_count"],
        "qrel_count": dataset_identity["qrel_count"],
        "top_k": args.top_k,
        "native_candidate_depth": args.candidate_depth,
        "warmups_per_query": args.warmups,
        "repetitions": args.repetitions,
        "retrieval_retries": args.retrieval_retries,
        "index_batch_size": args.index_batch_size,
        "indexed_vector_count": vector_count,
        "docker_network": args.docker_network,
        "litellm_container_base_url": args.litellm_container_base_url,
        "container_limits": {"memory": args.memory_limit, "cpus": args.cpus},
        "provider_calls": provider_calls,
        "hosted_cost_usd": hosted_cost,
        "temporary_storage_removed": not storage.exists(),
        "query_or_document_text_persisted": False,
        "abstention_policy": {
            "similarity_threshold": 0.0,
            "score_threshold": 0.0,
            "no_answer_rule": "zero unique retrieved segments",
            "calibrated": False,
        },
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if status == "completed":
        report = (
            "# AnythingLLM networking retrieval\n\n"
            f"- Status: `{status}`\n"
            f"- Recall@{args.top_k}: `{summary['mean_recall_at_k']:.6f}`\n"
            f"- MRR@{args.top_k}: `{summary['mean_mrr_at_k']:.6f}`\n"
            f"- nDCG@{args.top_k}: `{summary['mean_ndcg_at_k']:.6f}`\n"
            f"- Retrieval p50/p95: `{summary['latency_ms']['p50']:.3f}` / "
            f"`{summary['latency_ms']['p95']:.3f}` ms\n"
        )
    else:
        report = (
            "# AnythingLLM networking retrieval\n\n"
            f"- Status: `failed`\n- Stage: `{stage}`\n"
            f"- Error type: `{summary['error_type']}`\n- Quality score emitted: `false`\n"
        )
    (output / "summary.md").write_text(report, encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--storage", required=True, type=Path)
    parser.add_argument("--allowed-storage-root", required=True, type=Path)
    parser.add_argument("--model-cache", type=Path)
    parser.add_argument("--embedding-engine", choices=("native", "litellm"), default="native")
    parser.add_argument(
        "--embedding-model",
        help="Underlying OpenAI embedding model for the LiteLLM matrix track",
    )
    parser.add_argument(
        "--embedding-dimension",
        type=int,
        help="Requested OpenAI vector width for the LiteLLM matrix track",
    )
    parser.add_argument(
        "--embedding-litellm-model-name",
        "--embedding-alias",
        dest="embedding_litellm_model_name",
        help="Fixed, attested LiteLLM alias for the selected matrix cell",
    )
    parser.add_argument("--answer-model", default=ANSWER_MODEL)
    parser.add_argument(
        "--litellm-container-base-url",
        default="http://host.docker.internal:54000/v1",
    )
    parser.add_argument("--docker-network")
    parser.add_argument(
        "--embedding-proxy-fingerprint",
        help="Non-secret SHA-256 identity of the LiteLLM instance/configuration",
    )
    parser.add_argument(
        "--embedding-width-attestation",
        "--embedding-width-attestation-artifact",
        "--embedding-attestation",
        dest="embedding_width_attestation",
        type=Path,
        help="JSON artifact proving the selected alias returned the requested width",
    )
    parser.add_argument(
        "--embedding-width-attestation-sha256",
        "--embedding-attestation-sha256",
        dest="embedding_width_attestation_sha256",
        help="Optional expected SHA-256 for the width attestation artifact",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--candidate-depth", type=int, default=20)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--retrieval-retries", type=int, default=2)
    parser.add_argument("--index-batch-size", type=int, default=4)
    parser.add_argument("--memory-limit", default="2g")
    parser.add_argument("--cpus", type=float, default=2.0)
    args = parser.parse_args()
    if (
        min(args.top_k, args.repetitions, args.index_batch_size) < 1
        or args.candidate_depth < args.top_k
        or args.warmups < 0
        or args.retrieval_retries < 0
    ):
        parser.error("top-k/repetitions/batch size must be positive; warmups non-negative")
    output = asyncio.run(run(args))
    print(json.dumps({"output": str(output)}, sort_keys=True))


if __name__ == "__main__":
    main()
