#!/usr/bin/env python3
"""Paired single-query versus multi-query RAGZ retrieval benchmark.

The runner parses the supplied PDFs locally with RAGZ LiteParse, indexes the
same chunks once into an isolated Qdrant/Postgres pair, changes only the
workspace multi-query toggle, and writes no query/document/provider text.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import random
import shutil
import statistics
import subprocess
import time
from collections import defaultdict
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from build_networking_benchmark import (
    build_manifest,
    load_query_set,
    parse_pdf_arg,
)
from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]
from testcontainers.qdrant import QdrantContainer  # type: ignore[import-untyped]


@dataclass(frozen=True)
class EmbeddingTrack:
    engine: str
    model: str
    dimension: int
    provider_kind: str
    settings_backend: str
    dense_label: str
    provider_calls: int | str
    provider_cost_usd: float | None


@dataclass
class BenchmarkProgress:
    stage: str = "initializing"
    index_embedding_calls_completed: int = 0
    index_embedding_tokens: int = 0
    query_embedding_attempts: int = 0


def write_progress(output: Path, progress: BenchmarkProgress) -> None:
    (output / "progress.json").write_text(
        json.dumps(
            {
                "stage": progress.stage,
                "index_embedding_calls_completed": (
                    progress.index_embedding_calls_completed
                ),
                "index_embedding_tokens": progress.index_embedding_tokens,
                "query_embedding_attempts": progress.query_embedding_attempts,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def resolve_embedding_track(engine: str) -> EmbeddingTrack:
    if engine == "hash":
        return EmbeddingTrack(
            engine="hash",
            model="deterministic-hash",
            dimension=1024,
            provider_kind="tei",
            settings_backend="hash",
            dense_label="deterministic-hash-1024",
            provider_calls=0,
            provider_cost_usd=0.0,
        )
    if engine == "openai":
        return EmbeddingTrack(
            engine="openai",
            model="text-embedding-3-small",
            dimension=1536,
            provider_kind="openai",
            settings_backend="litellm",
            dense_label="openai-text-embedding-3-small-1536",
            provider_calls="not_exposed_nonzero",
            provider_cost_usd=None,
        )
    raise ValueError("embedding engine must be hash or openai")


def create_output_directory(path: Path) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    path.mkdir(parents=True)


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def format_metric(value: float | None, digits: int = 6) -> str:
    return f"{value:.{digits}f}" if value is not None else "not measured"


def ranking_metrics(
    *, retrieved: list[str], relevant: set[str], k: int
) -> dict[str, float]:
    # Multiple chunks can start on the same PDF page. Page-level qrels must
    # count that evidence page once; otherwise repeated hits inflate DCG above
    # its ideal and can produce impossible nDCG values greater than 1.
    ranked: list[str] = []
    seen: set[str] = set()
    for item in retrieved:
        if item in seen:
            continue
        seen.add(item)
        ranked.append(item)
        if len(ranked) == k:
            break
    hit_ranks = [index + 1 for index, item in enumerate(ranked) if item in relevant]
    recall = len({item for item in ranked if item in relevant}) / len(relevant) if relevant else 0.0
    reciprocal_rank = 1.0 / hit_ranks[0] if hit_ranks else 0.0
    dcg = sum(1.0 / math.log2(rank + 1) for rank in hit_ranks)
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return {
        "recall_at_k": recall,
        "reciprocal_rank": reciprocal_rank,
        "ndcg_at_k": dcg / idcg if idcg else 0.0,
    }


def safe_query_record(
    *,
    query_id: str,
    mode: str,
    retrieved: list[dict[str, object]],
    metrics: dict[str, float] | None,
    elapsed_ms: float,
    expansion_count: int | None,
    error: str | None,
    stage_timings_ms: dict[str, float] | None = None,
    repetition: int = 1,
    answerable: bool = True,
    no_answer: bool | None = False,
) -> dict[str, Any]:
    return {
        "query_id": query_id,
        "mode": mode,
        "repetition": repetition,
        "retrieved": retrieved,
        "metrics": metrics,
        "elapsed_ms": round(elapsed_ms, 4),
        "expansion_count": expansion_count,
        "stage_timings_ms": {
            stage: round(float(duration), 4)
            for stage, duration in sorted((stage_timings_ms or {}).items())
        },
        "answerable": answerable,
        "no_answer": no_answer,
        "error": error,
    }


def summarize_stage_timings(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate privacy-safe successful per-query wall-clock stage timings."""
    successful = [record for record in records if record["error"] is None]
    stages = sorted(
        {
            str(stage)
            for record in successful
            for stage in (record.get("stage_timings_ms") or {})
        }
    )
    total_latencies = [float(record["elapsed_ms"]) for record in successful]
    mean_total = statistics.mean(total_latencies) if total_latencies else None
    output: dict[str, Any] = {}
    for stage in stages:
        values = [
            float(record["stage_timings_ms"][stage])
            for record in successful
            if stage in (record.get("stage_timings_ms") or {})
        ]
        mean = statistics.mean(values)
        output[stage] = {
            "observations": len(values),
            "mean": mean,
            "p50": percentile(values, 0.50),
            "p95": percentile(values, 0.95),
            "p99": percentile(values, 0.99),
            "mean_total_share": mean / mean_total if mean_total else None,
        }
    return {
        "successful_observations": len(successful),
        "clock": "time.perf_counter wall clock",
        "stages": output,
    }


def bootstrap_ci(
    values: list[float], *, seed: int, samples: int = 10_000
) -> tuple[float, float] | None:
    if not values:
        return None
    # This RNG drives a reproducible statistical resample, never a secret.
    rng = random.Random(seed)  # noqa: S311
    means = sorted(
        statistics.mean(rng.choice(values) for _ in values)
        for _ in range(samples)
    )
    return means[int(samples * 0.025)], means[int(samples * 0.975) - 1]


def paired_summary(output: Path, *, seed: int) -> dict[str, Any]:
    by_mode: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for mode in ("single", "multi"):
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for line in (output / mode / "per_query.jsonl").read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            grouped[str(row["query_id"])].append(row)
        by_mode[mode] = grouped
    metrics: dict[str, Any] = {}
    for metric in ("recall_at_k", "reciprocal_rank", "ndcg_at_k"):
        deltas: list[float] = []
        for query_id in sorted(by_mode["single"].keys() & by_mode["multi"].keys()):
            single_rows = [
                row
                for row in by_mode["single"][query_id]
                if row["answerable"]
                and row["error"] is None
                and row["metrics"] is not None
            ]
            multi_rows = [
                row
                for row in by_mode["multi"][query_id]
                if row["answerable"]
                and row["error"] is None
                and row["metrics"] is not None
            ]
            if not single_rows or not multi_rows:
                continue
            single = statistics.mean(
                float(row["metrics"][metric])
                for row in single_rows
            )
            multi = statistics.mean(
                float(row["metrics"][metric])
                for row in multi_rows
            )
            deltas.append(multi - single)
        metrics[metric] = {
            "paired_query_count": len(deltas),
            "mean_delta": statistics.mean(deltas) if deltas else None,
            "bootstrap_ci95": bootstrap_ci(deltas, seed=seed),
            "improved": sum(delta > 1e-12 for delta in deltas),
            "regressed": sum(delta < -1e-12 for delta in deltas),
            "tied": sum(abs(delta) <= 1e-12 for delta in deltas),
        }
    return {"seed": seed, "bootstrap_samples": 10_000, "metrics": metrics}


class StaticQueryExpander:
    """Deterministic variants isolate retrieval fusion from LLM variance."""

    def __init__(self, alternatives: list[str]) -> None:
        self._alternatives = alternatives

    async def expand(self, query: str, *, model: str) -> Any:
        from ragz.modules.retrieval.query_expansion import ExpandedQueries

        return ExpandedQueries((query, *self._alternatives))


def _install_settings(settings: Any) -> None:
    import ragz.core.config as config
    import ragz.modules.documents.pipeline as pipeline
    import ragz.modules.retrieval.client as client
    import ragz.modules.retrieval.embeddings as embeddings
    import ragz.modules.retrieval.service as retrieval

    def controlled_settings() -> Any:
        return settings

    config.get_settings = controlled_settings  # type: ignore[assignment]
    client.get_settings = controlled_settings  # type: ignore[attr-defined,assignment]
    embeddings.get_settings = controlled_settings  # type: ignore[attr-defined,assignment]
    retrieval.get_settings = controlled_settings  # type: ignore[attr-defined,assignment]
    embeddings.get_dense_embedder.cache_clear()
    client.get_qdrant.cache_clear()
    pipeline.get_qdrant = client.get_qdrant  # type: ignore[attr-defined]


async def _seed_corpus(
    *,
    pdfs: list[tuple[str, Path]],
    database_url: str,
    qdrant_url: str,
    min_score: float,
    embedding_track: EmbeddingTrack,
    litellm_url: str,
    litellm_master_key: str,
    output: Path,
    progress: BenchmarkProgress,
    resources: dict[str, Any],
) -> tuple[Any, Any, Any, Any, dict[UUID, str], dict[str, object]]:
    from ragz.core.config import Settings
    from ragz.core.db import Base, build_engine, build_session_factory
    from ragz.modules.auth.models import User
    from ragz.modules.documents.models import Document
    from ragz.modules.documents.parsers import LiteParseParser
    from ragz.modules.documents.pipeline import chunk_document, embed_batch, upsert_points
    from ragz.modules.models.models import LOCAL_EMBEDDING_MODEL_ID, Model
    from ragz.modules.retrieval.client import COLLECTION
    from ragz.modules.retrieval.embeddings import get_dense_embedder
    from ragz.modules.retrieval.service import ensure_collection
    from ragz.modules.tenancy.context import TenantContext
    from ragz.modules.tenancy.models import Organization, Workspace, WorkspaceMember

    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        environment="test",
        database_url=database_url,
        qdrant_url=qdrant_url,
        embedding_backend=embedding_track.settings_backend,
        embedding_dim=embedding_track.dimension,
        rerank_backend="lexical",
        litellm_url=litellm_url,
        litellm_master_key=litellm_master_key,
        model_catalog_url="",
    )
    _install_settings(settings)
    engine = build_engine(database_url)
    resources["engine"] = engine
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = build_session_factory(engine)
    org_id, workspace_id, user_id = uuid4(), uuid4(), uuid4()
    embedding_model_id = (
        LOCAL_EMBEDDING_MODEL_ID if embedding_track.engine == "hash" else uuid4()
    )
    async with factory() as session:
        session.add(Organization(id=org_id, name=f"networking-bench-{org_id.hex[:8]}"))
        session.add_all(
            [
                Model(
                    id=embedding_model_id,
                    litellm_model_name=embedding_track.model,
                    display_name=f"{embedding_track.model} benchmark embeddings",
                    provider_kind=embedding_track.provider_kind,
                    modality="embedding",
                    dimension=embedding_track.dimension,
                    collection_name=COLLECTION,
                    enabled=True,
                    sync_status="synced",
                ),
                Model(
                    litellm_model_name="static-query-expander",
                    display_name="Static benchmark query expander",
                    provider_kind="ollama",
                    modality="chat",
                    enabled=True,
                    is_utility=True,
                ),
            ]
        )
        # These rows are referenced only by their scalar UUIDs below (there are
        # no ORM relationship attributes for SQLAlchemy to order through), so
        # make the FK targets visible before inserting Workspace/User.
        await session.flush()
        session.add(
            Workspace(
                id=workspace_id,
                org_id=org_id,
                name="Networking benchmark",
                embedding_model_id=embedding_model_id,
                top_k=5,
                min_score=min_score,
                rerank_enabled=False,
                multi_query_enabled=False,
                chunk_method="heading",
            )
        )
        session.add(
            User(
                id=user_id,
                org_id=org_id,
                email=f"benchmark-{user_id.hex[:8]}@example.com",
                password_hash="benchmark-only",  # noqa: S106 - inert benchmark row
                role="user",
            )
        )
        await session.flush()
        session.add(WorkspaceMember(workspace_id=workspace_id, user_id=user_id))
        await session.commit()
    await ensure_collection(COLLECTION, embedding_track.dimension)
    dense_embedder = get_dense_embedder(
        embedding_model_id,
        provider_kind=embedding_track.provider_kind,
        litellm_model_name=embedding_track.model,
    )
    document_map: dict[UUID, str] = {}
    corpus_stats: dict[str, Any] = {"books": [], "chunks": 0}
    embedding_usage: list[int] = []
    for book_id, path in pdfs:
        progress.stage = f"indexing:{book_id}"
        write_progress(output, progress)
        data = path.read_bytes()
        parse_started = time.perf_counter()
        blocks = await LiteParseParser().parse(data, path.name)
        parse_ms = (time.perf_counter() - parse_started) * 1000
        chunks = chunk_document(blocks, method="heading")
        document_id = uuid4()
        document_map[document_id] = book_id
        async with factory() as session:
            session.add(
                Document(
                    id=document_id,
                    org_id=org_id,
                    workspace_id=workspace_id,
                    filename=path.name,
                    mime="application/pdf",
                    size_bytes=len(data),
                    content_hash=__import__("hashlib").sha256(data).hexdigest(),
                    status="indexed",
                    storage_key=f"benchmark/{document_id}",
                    page_count=max((block.page for block in blocks), default=0),
                    created_by=user_id,
                    lineage_id=document_id,
                    is_current=True,
                    approved=True,
                    vectors_present=True,
                    index_state="active",
                    security_revision=0,
                    projected_security_revision=0,
                )
            )
            await session.commit()
        index_batch_size = 32 if embedding_track.engine == "openai" else 64
        for start in range(0, len(chunks), index_batch_size):
            batch = chunks[start : start + index_batch_size]
            usage_count_before = len(embedding_usage)
            dense, sparse = await embed_batch(
                [chunk.text for chunk in batch],
                dense_embedder,
                usage_sink=embedding_usage,
            )
            if embedding_track.engine == "openai":
                progress.index_embedding_calls_completed += 1
                progress.index_embedding_tokens += sum(
                    embedding_usage[usage_count_before:]
                )
                write_progress(output, progress)
            await upsert_points(
                org_id=org_id,
                workspace_id=workspace_id,
                document_id=document_id,
                mime="application/pdf",
                created_at=datetime.now(UTC).replace(tzinfo=None),
                acl_group_ids=[],
                chunks=batch,
                dense=dense,
                sparse=sparse,
                version=1,
                meta={"book_id": book_id},
                collection_name=COLLECTION,
                is_current=True,
            )
        corpus_stats["books"].append(
            {
                "book_id": book_id,
                "pages": max((block.page for block in blocks), default=0),
                "chunks": len(chunks),
                "parse_ms": round(parse_ms, 4),
            }
        )
        corpus_stats["chunks"] = int(corpus_stats["chunks"]) + len(chunks)
    corpus_stats["index_embedding_tokens"] = sum(embedding_usage)
    corpus_stats["index_embedding_calls_completed"] = (
        progress.index_embedding_calls_completed
    )
    ctx = TenantContext(
        user_id=user_id,
        org_id=org_id,
        role="user",
        workspace_ids=frozenset({workspace_id}),
    )
    return engine, factory, ctx, workspace_id, document_map, corpus_stats


def _relevant_keys(record: dict[str, Any]) -> set[str]:
    return {
        f"{item['book_id']}:{page}"
        for item in record["relevant"]
        for page in item["pages"]
    }


async def _run_mode(
    *,
    mode: str,
    queries: list[dict[str, Any]],
    factory: Any,
    ctx: Any,
    workspace_id: UUID,
    document_map: dict[UUID, str],
    output: Path,
    top_k: int,
    warmups: int,
    repetitions: int,
    provider_backed_embeddings: bool,
    progress: BenchmarkProgress,
    progress_output: Path,
) -> dict[str, Any]:
    from ragz.modules.retrieval.service import retrieve
    from ragz.modules.tenancy.models import Workspace

    create_output_directory(output)
    records: list[dict[str, Any]] = []
    async with factory() as session:
        workspace = await session.get(Workspace, workspace_id)
        assert workspace is not None
        workspace.multi_query_enabled = mode == "multi"
        await session.commit()
        progress.stage = f"retrieval:{mode}:warmup"
        write_progress(progress_output, progress)
        for _ in range(warmups):
            for record in queries:
                if provider_backed_embeddings:
                    progress.query_embedding_attempts += 1
                    write_progress(progress_output, progress)
                await retrieve(
                    session,
                    ctx,
                    workspace_id,
                    record["query"],
                    top_k=top_k,
                    query_expander=(
                        StaticQueryExpander(record["alternatives"])
                        if mode == "multi"
                        else None
                    ),
                )
        progress.stage = f"retrieval:{mode}:scored"
        write_progress(progress_output, progress)
        for repetition in range(1, repetitions + 1):
            for record in queries:
                expander = (
                    StaticQueryExpander(record["alternatives"])
                    if mode == "multi"
                    else None
                )
                error: str | None = None
                result: Any = None
                stage_timings_ms: dict[str, float] = {}
                if provider_backed_embeddings:
                    progress.query_embedding_attempts += 1
                    write_progress(progress_output, progress)
                # Provider progress is durability bookkeeping, not retrieval.
                # Keep its file I/O outside the user-visible latency clock.
                started = time.perf_counter()
                try:
                    result = await retrieve(
                        session,
                        ctx,
                        workspace_id,
                        record["query"],
                        top_k=top_k,
                        query_expander=expander,
                        stage_timings_ms=stage_timings_ms,
                    )
                except Exception as exc:  # noqa: BLE001 - typed failure only
                    error = type(exc).__name__
                elapsed_ms = (time.perf_counter() - started) * 1000
                attributed_ms = sum(stage_timings_ms.values())
                stage_timings_ms["unattributed_runner"] = round(
                    max(0.0, elapsed_ms - attributed_ms), 4
                )
                retrieved: list[dict[str, object]] = []
                evidence_ids: list[str] = []
                if result is not None:
                    for rank, chunk in enumerate(result.chunks, 1):
                        evidence_id = f"{document_map[chunk.document_id]}:{chunk.page}"
                        evidence_ids.append(evidence_id)
                        retrieved.append(
                            {
                                "evidence_id": evidence_id,
                                "rank": rank,
                                "score": round(float(chunk.score), 8),
                            }
                        )
                answerable = bool(record["answerable"])
                metrics = (
                    ranking_metrics(
                        retrieved=evidence_ids,
                        relevant=_relevant_keys(record),
                        k=top_k,
                    )
                    if answerable and error is None
                    else None
                )
                records.append(
                    safe_query_record(
                        query_id=record["query_id"],
                        mode=mode,
                        retrieved=retrieved,
                        metrics=metrics,
                        elapsed_ms=elapsed_ms,
                        expansion_count=(
                            int(result.query_count) if result is not None else None
                        ),
                        error=error,
                        stage_timings_ms=stage_timings_ms,
                        repetition=repetition,
                        answerable=answerable,
                        no_answer=(
                            bool(result.no_answer) if result is not None else None
                        ),
                    )
                )
    with (output / "per_query.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    latencies = [float(item["elapsed_ms"]) for item in records if item["error"] is None]
    abstention_records = [item for item in records if item["error"] is None]
    quality_records = [
        item
        for item in records
        if item["answerable"]
        and item["error"] is None
        and item["metrics"] is not None
    ]
    abstention_tp = sum(
        not item["answerable"] and item["no_answer"] is True
        for item in abstention_records
    )
    abstention_fp = sum(
        item["answerable"] and item["no_answer"] is True
        for item in abstention_records
    )
    abstention_fn = sum(
        not item["answerable"] and item["no_answer"] is False
        for item in abstention_records
    )
    abstention_precision = (
        abstention_tp / (abstention_tp + abstention_fp)
        if abstention_tp + abstention_fp
        else None
    )
    abstention_recall = (
        abstention_tp / (abstention_tp + abstention_fn)
        if abstention_tp + abstention_fn
        else None
    )
    abstention_f1 = (
        2 * abstention_precision * abstention_recall
        / (abstention_precision + abstention_recall)
        if abstention_precision is not None
        and abstention_recall is not None
        and abstention_precision + abstention_recall
        else None
    )
    summary: dict[str, Any] = {
        "mode": mode,
        "query_count": len(queries),
        "observations": len(records),
        "quality_observations": len(quality_records),
        "abstention_observations": len(abstention_records),
        "answerable_queries": sum(bool(item["answerable"]) for item in queries),
        "unanswerable_queries": sum(not bool(item["answerable"]) for item in queries),
        "warmups": warmups,
        "repetitions": repetitions,
        "errors": sum(item["error"] is not None for item in records),
        "mean_recall_at_k": (
            statistics.mean(
                float(item["metrics"]["recall_at_k"])
                for item in quality_records
            )
            if quality_records
            else None
        ),
        "mean_reciprocal_rank": (
            statistics.mean(
                float(item["metrics"]["reciprocal_rank"])
                for item in quality_records
            )
            if quality_records
            else None
        ),
        "mean_ndcg_at_k": (
            statistics.mean(
                float(item["metrics"]["ndcg_at_k"])
                for item in quality_records
            )
            if quality_records
            else None
        ),
        "abstention": {
            "true_positive": abstention_tp,
            "false_positive": abstention_fp,
            "false_negative": abstention_fn,
            "precision": abstention_precision,
            "recall": abstention_recall,
            "f1": abstention_f1,
        },
        "latency_ms": {
            "p50": percentile(latencies, 0.5),
            "p95": percentile(latencies, 0.95),
            "p99": percentile(latencies, 0.99),
        },
        "atomic_latency_ms": summarize_stage_timings(records),
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    atomic_lines = [
        "| Stage | Mean ms | p50 ms | p95 ms | Mean share |",
        "|---|---:|---:|---:|---:|",
        *(
            f"| {stage} | {values['mean']:.3f} | {values['p50']:.3f} | "
            f"{values['p95']:.3f} | {values['mean_total_share'] * 100:.1f}% |"
            for stage, values in sorted(
                summary["atomic_latency_ms"]["stages"].items(),
                key=lambda item: float(item[1]["mean"]),
                reverse=True,
            )
        ),
    ]
    (output / "summary.md").write_text(
        "# RAGZ networking retrieval summary\n\n"
        f"- Mode: `{mode}`\n"
        f"- Queries: `{len(queries)}` × `{repetitions}` repetitions\n"
        f"- Recall@{top_k}: `{format_metric(summary['mean_recall_at_k'])}`\n"
        f"- MRR@{top_k}: `{format_metric(summary['mean_reciprocal_rank'])}`\n"
        f"- nDCG@{top_k}: `{format_metric(summary['mean_ndcg_at_k'])}`\n"
        "- Abstention precision/recall/F1: "
        f"`{format_metric(summary['abstention']['precision'], 3)}` / "
        f"`{format_metric(summary['abstention']['recall'], 3)}` / "
        f"`{format_metric(summary['abstention']['f1'], 3)}`\n"
        f"- p50/p95/p99: `{summary['latency_ms']['p50']:.3f}` / "
        f"`{summary['latency_ms']['p95']:.3f}` / "
        f"`{summary['latency_ms']['p99']:.3f}` ms\n"
        f"- Errors: `{summary['errors']}`\n"
        + "\n## Atomic retrieval latency\n\n"
        + "\n".join(atomic_lines)
        + "\n",
        encoding="utf-8",
    )
    return summary


async def run(args: argparse.Namespace) -> None:
    output = args.output.resolve()
    embedding_track = resolve_embedding_track(args.embedding_engine)
    litellm_master_key = os.environ.get("RAGZ_LITELLM_MASTER_KEY", "")
    if embedding_track.engine == "openai" and not litellm_master_key:
        raise RuntimeError(
            "RAGZ_LITELLM_MASTER_KEY is required for the OpenAI embedding track"
        )
    proxy_fingerprint = str(args.embedding_proxy_fingerprint or "")
    if embedding_track.engine == "openai" and (
        len(proxy_fingerprint) != 64
        or any(character not in "0123456789abcdef" for character in proxy_fingerprint)
    ):
        raise ValueError(
            "OpenAI embedding runs require a lowercase SHA-256 "
            "--embedding-proxy-fingerprint"
        )
    create_output_directory(output)
    progress = BenchmarkProgress()
    write_progress(output, progress)
    queries = load_query_set(args.queries.resolve())
    manifest = build_manifest(args.pdf, args.queries.resolve())
    git_executable = shutil.which("git")
    if git_executable is None:
        raise RuntimeError("git executable not found")
    git_commit = subprocess.check_output(  # noqa: S603 - fixed git argv
        [git_executable, "rev-parse", "HEAD"], text=True
    ).strip()
    git_status = subprocess.check_output(  # noqa: S603 - fixed git argv
        [git_executable, "status", "--porcelain"], text=True
    )
    tracked_diff = subprocess.check_output(  # noqa: S603 - fixed git argv
        [git_executable, "diff", "--binary", "HEAD"]
    )
    manifest.update(
        {
            "runner_version": "3.0",
            "git_commit": git_commit,
            "git_dirty": bool(git_status),
            "tracked_diff_sha256": hashlib.sha256(tracked_diff).hexdigest(),
            "python_version": platform.python_version(),
            "tool_versions": {
                "liteparse": importlib.metadata.version("liteparse"),
                "qdrant_client": importlib.metadata.version("qdrant-client"),
                "fastembed": importlib.metadata.version("fastembed"),
            },
            "top_k": args.top_k,
            "seed": args.seed,
            "embedding_engine": embedding_track.engine,
            "embedding_model": embedding_track.model,
            "embedding_dimension": embedding_track.dimension,
            "embedding_provider": embedding_track.provider_kind,
            "embedding_transport": (
                "litellm" if embedding_track.engine == "openai" else "local"
            ),
            "embedding_proxy_fingerprint_sha256": (
                proxy_fingerprint if embedding_track.engine == "openai" else None
            ),
            "dense": embedding_track.dense_label,
            "sparse": "fastembed-bm25",
            "fusion": "qdrant-rrf",
            "reranker": "disabled",
            "query_variants": "fixed-two-alternatives",
            "expansion_provider_calls": 0,
            "embedding_provider_calls": embedding_track.provider_calls,
            "provider_cost_usd": embedding_track.provider_cost_usd,
            "benchmark_status": (
                "production_embedding_fixed_fusion"
                if embedding_track.engine == "openai"
                else "synthetic_fusion_pilot"
            ),
            "status": "running",
            "stage_timing_schema": {
                "version": "retrieval-atomic-v1",
                "clock": "time.perf_counter wall clock",
                "unit": "milliseconds",
                "warmups_persisted": False,
                "elapsed_ms_authoritative_total": True,
            },
        }
    )
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with ExitStack() as stack:
        postgres = stack.enter_context(PostgresContainer("postgres:16-alpine"))
        qdrant = stack.enter_context(QdrantContainer("qdrant/qdrant:v1.18.0"))
        database_url = postgres.get_connection_url().replace("psycopg2", "asyncpg")
        qdrant_url = (
            f"http://{qdrant.get_container_host_ip()}:"
            f"{qdrant.get_exposed_port(6333)}"
        )
        seed_resources: dict[str, Any] = {}
        try:
            engine, factory, ctx, workspace_id, document_map, corpus_stats = (
                await _seed_corpus(
                    pdfs=args.pdf,
                    database_url=database_url,
                    qdrant_url=qdrant_url,
                    min_score=args.min_score,
                    embedding_track=embedding_track,
                    litellm_url=args.litellm_url,
                    litellm_master_key=litellm_master_key,
                    output=output,
                    progress=progress,
                    resources=seed_resources,
                )
            )
        except Exception:
            leaked_engine = seed_resources.get("engine")
            if leaked_engine is not None:
                await leaked_engine.dispose()
            raise
        try:
            summaries: dict[str, dict[str, Any]] = {}
            modes = ("single", "multi") if args.order == "single-first" else ("multi", "single")
            for mode in modes:
                summaries[mode] = await _run_mode(
                    mode=mode,
                    queries=queries,
                    factory=factory,
                    ctx=ctx,
                    workspace_id=workspace_id,
                    document_map=document_map,
                    output=output / mode,
                    top_k=args.top_k,
                    warmups=args.warmups,
                    repetitions=args.repetitions,
                    provider_backed_embeddings=embedding_track.engine == "openai",
                    progress=progress,
                    progress_output=output,
                )
        finally:
            await engine.dispose()
            seed_resources.clear()
    manifest["corpus_stats"] = corpus_stats
    manifest["condition_order"] = args.order
    manifest["warmups"] = args.warmups
    manifest["repetitions"] = args.repetitions
    manifest["no_answer_threshold"] = {
        "value": args.min_score,
        "score_space": "maximum_dense_cosine",
        "calibration": args.threshold_calibration,
    }
    manifest["conditions"] = summaries
    manifest["provider_progress"] = {
        "index_embedding_calls_completed": progress.index_embedding_calls_completed,
        "index_embedding_tokens": progress.index_embedding_tokens,
        "query_embedding_attempts": progress.query_embedding_attempts,
    }
    manifest["status"] = "completed"
    paired = paired_summary(output, seed=args.seed)
    (output / "paired-summary.json").write_text(
        json.dumps(paired, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output / "summary.md").write_text(
        "# RAGZ single-query vs multi-query retrieval benchmark\n\n"
        f"- Commit: `{git_commit}`\n"
        f"- Dense embedding: `{embedding_track.dense_label}`\n"
        f"- Condition order: `{args.order}`\n"
        f"- Seed: `{args.seed}`\n"
        f"- No-answer threshold: `{args.min_score}` (maximum dense cosine)\n"
        f"- Single Recall@{args.top_k}: "
        f"`{format_metric(summaries['single']['mean_recall_at_k'])}`\n"
        f"- Multi Recall@{args.top_k}: "
        f"`{format_metric(summaries['multi']['mean_recall_at_k'])}`\n"
        "- Live expansion/provider latency: `not measured`\n",
        encoding="utf-8",
    )
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    progress.stage = "completed"
    write_progress(output, progress)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", action="append", required=True, type=parse_pdf_arg)
    parser.add_argument("--queries", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--embedding-engine",
        choices=("hash", "openai"),
        default="hash",
        help="Dense embedding track; openai is pinned to text-embedding-3-small/1536",
    )
    parser.add_argument(
        "--litellm-url",
        default="http://127.0.0.1:54000",
        help="RAGZ LiteLLM gateway used only by the OpenAI embedding track",
    )
    parser.add_argument(
        "--embedding-proxy-fingerprint",
        help="Non-secret SHA-256 identity of the LiteLLM instance/configuration",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        required=True,
        help="Explicit maximum-dense-cosine threshold for no-answer evaluation",
    )
    parser.add_argument(
        "--threshold-calibration",
        required=True,
        help="Non-secret provenance for selecting --min-score",
    )
    parser.add_argument(
        "--order",
        choices=("single-first", "multi-first"),
        default="single-first",
    )
    args = parser.parse_args()
    if len(args.pdf) != 3 or len({book_id for book_id, _ in args.pdf}) != 3:
        raise ValueError("exactly three uniquely named PDFs are required")
    if not 1 <= args.top_k <= 50:
        raise ValueError("top-k must be between 1 and 50")
    if args.warmups < 0 or args.repetitions < 1:
        raise ValueError("warmups must be non-negative and repetitions positive")
    if not 0.0 <= args.min_score <= 1.0:
        raise ValueError("min-score must be between 0 and 1")
    output_preexisted = args.output.resolve().exists()
    try:
        asyncio.run(run(args))
    except Exception as exc:
        output = args.output.resolve()
        if output.is_dir() and not output_preexisted:
            progress_path = output / "progress.json"
            progress_data = (
                json.loads(progress_path.read_text(encoding="utf-8"))
                if progress_path.is_file()
                else {"stage": "before_progress_checkpoint"}
            )
            failure = {
                "status": "failed",
                "stage": progress_data.get("stage", "unknown"),
                "error_type": type(exc).__name__,
                "provider_progress": progress_data,
                "error_message_persisted": False,
                "credentials_persisted": False,
            }
            (output / "failure.json").write_text(
                json.dumps(failure, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            manifest_path = output / "manifest.json"
            if manifest_path.is_file():
                failed_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            else:
                failed_track = resolve_embedding_track(args.embedding_engine)
                failed_manifest = {
                    "schema_version": 1,
                    "runner_version": "3.0",
                    "dataset_id": "networking-pdfs-v1",
                    "source_pdf_count": len(args.pdf),
                    "query_set_filename": args.queries.name,
                    "embedding_engine": failed_track.engine,
                    "embedding_model": failed_track.model,
                    "embedding_dimension": failed_track.dimension,
                    "embedding_provider": failed_track.provider_kind,
                    "embedding_transport": (
                        "litellm" if failed_track.engine == "openai" else "local"
                    ),
                    "embedding_proxy_fingerprint_sha256": (
                        args.embedding_proxy_fingerprint
                        if failed_track.engine == "openai"
                        else None
                    ),
                    "top_k": args.top_k,
                }
            failed_manifest["status"] = "failed"
            failed_manifest["failure"] = failure
            manifest_path.write_text(
                json.dumps(failed_manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        raise


if __name__ == "__main__":
    main()
