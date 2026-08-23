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
import shutil
import socket
import statistics
import subprocess
import time
from collections.abc import Iterator, Sequence
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
    ideal = sum(
        1.0 / math.log2(rank + 1)
        for rank in range(1, min(len(relevant), k) + 1)
    )
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
        else 0.0 if tp + fp + fn else None
    )
    latencies = [float(row["latency_ms"]) for row in abstention]

    def mean_metric(name: str) -> float | None:
        return (
            statistics.mean(float(row["metrics"][name]) for row in quality)
            if quality
            else None
        )

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


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _command(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, capture_output=True, text=True)  # noqa: S603


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


def embedding_configuration(engine: str) -> tuple[list[str], str, object, object]:
    if engine == "native":
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
        return (
            [
                "-e",
                "EMBEDDING_ENGINE=litellm",
                "-e",
                "EMBEDDING_MODEL_PREF=text-embedding-3-small",
            ],
            "common-20-page-segments-openai-lancedb",
            "not_exposed_nonzero",
            None,
        )
    raise ValueError("embedding engine must be native or litellm")


def generation_configuration(model: str = ANSWER_MODEL) -> list[str]:
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
        "LITE_LLM_BASE_PATH=http://host.docker.internal:54000/v1",
        "-e",
        "LITE_LLM_API_KEY=sk-ragz-dev-master",
    ]


def workspace_configuration(name: str, candidate_depth: int) -> dict[str, Any]:
    """Build a Luna-compatible AnythingLLM workspace configuration."""
    return {
        "name": name,
        "similarityThreshold": 0.0,
        "topN": candidate_depth,
        "openAiTemp": ANSWER_TEMPERATURE,
    }


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
    qrels_by_query: dict[str, set[str]] = {}
    for row in qrels:
        if float(row.get("relevance", 0)) > 0:
            qrels_by_query.setdefault(str(row["query_id"]), set()).add(str(row["doc_id"]))
    storage, _ = validate_storage_path(args.storage, args.allowed_storage_root)
    if storage.exists():
        raise FileExistsError(f"refusing existing storage {storage}")
    storage.mkdir(parents=True)
    embedding_args, track, provider_calls, hosted_cost = embedding_configuration(
        args.embedding_engine
    )
    proxy_fingerprint = str(args.embedding_proxy_fingerprint or "")
    if args.embedding_engine == "litellm" and (
        len(proxy_fingerprint) != 64
        or any(character not in "0123456789abcdef" for character in proxy_fingerprint)
    ):
        raise ValueError(
            "litellm embedding runs require a lowercase SHA-256 "
            "--embedding-proxy-fingerprint"
        )
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
    indexing_started = time.perf_counter()
    indexing_ms: float | None = None
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
                *generation_configuration(args.answer_model),
                *embedding_args,
                "-e",
                "VECTOR_DB=lancedb",
                IMAGE_REF,
            ]
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
                json=workspace_configuration(
                    f"networking-{uuid4().hex[:8]}", args.candidate_depth
                ),
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
            indexing_ms = (time.perf_counter() - indexing_started) * 1000
            stage = "warmup"
            for _ in range(args.warmups):
                for query in queries:
                    response = await client.post(
                        f"/api/v1/workspace/{slug}/vector-search",
                        json={
                            "query": str(query["query"]),
                            "topN": args.candidate_depth,
                            "scoreThreshold": 0.0,
                        },
                    )
                    response.raise_for_status()
            stage = "scored_retrieval"
            for repetition in range(1, args.repetitions + 1):
                for query in queries:
                    started_at = time.perf_counter()
                    error: str | None = None
                    results: list[dict[str, Any]] = []
                    try:
                        response = await client.post(
                            f"/api/v1/workspace/{slug}/vector-search",
                            json={
                                "query": str(query["query"]),
                                "topN": args.candidate_depth,
                                "scoreThreshold": 0.0,
                            },
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
                        }
                    )
            memory = _memory_bytes(container)
            if memory is not None:
                memory_samples.append(memory)
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
        "embedding_model": (
            "text-embedding-3-small"
            if args.embedding_engine == "litellm"
            else "Xenova/all-MiniLM-L6-v2"
        ),
        "embedding_dimension": 1536 if args.embedding_engine == "litellm" else 384,
        "embedding_provider": "openai" if args.embedding_engine == "litellm" else "native",
        "embedding_transport": "litellm" if args.embedding_engine == "litellm" else "local",
        "embedding_proxy_fingerprint_sha256": (
            proxy_fingerprint if args.embedding_engine == "litellm" else None
        ),
        "answer_model": args.answer_model,
        "answer_provider": "litellm",
        "answer_model_configured": True,
        "answer_temperature_configured": ANSWER_TEMPERATURE,
        "answer_generation_executed": False,
        "answer_provider_calls": 0,
        "dataset_hash_sha256": _dataset_hash(dataset),
        "document_count": len(documents),
        "query_count": len(queries),
        "top_k": args.top_k,
        "native_candidate_depth": args.candidate_depth,
        "warmups_per_query": args.warmups,
        "repetitions": args.repetitions,
        "index_batch_size": args.index_batch_size,
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
    parser.add_argument("--answer-model", default=ANSWER_MODEL)
    parser.add_argument(
        "--embedding-proxy-fingerprint",
        help="Non-secret SHA-256 identity of the LiteLLM instance/configuration",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--candidate-depth", type=int, default=20)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--index-batch-size", type=int, default=4)
    parser.add_argument("--memory-limit", default="2g")
    parser.add_argument("--cpus", type=float, default=2.0)
    args = parser.parse_args()
    if (
        min(args.top_k, args.repetitions, args.index_batch_size) < 1
        or args.candidate_depth < args.top_k
        or args.warmups < 0
    ):
        parser.error("top-k/repetitions/batch size must be positive; warmups non-negative")
    output = asyncio.run(run(args))
    print(json.dumps({"output": str(output)}, sort_keys=True))


if __name__ == "__main__":
    main()
