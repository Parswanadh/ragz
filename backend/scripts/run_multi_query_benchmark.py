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
    litellm_model_name: str
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


@dataclass(frozen=True)
class MatrixCondition:
    query_count: int
    rerank_candidate_pool: int | None
    cache_mode: str

    @property
    def condition_id(self) -> str:
        rerank = self.rerank_candidate_pool or "off"
        return f"q{self.query_count}_rerank-{rerank}_cache-{self.cache_mode}"


def retrieval_matrix_conditions() -> tuple[MatrixCondition, ...]:
    return tuple(
        condition
        for query_count in (1, 3, 5)
        for condition in (
            MatrixCondition(query_count, None, "off"),
            MatrixCondition(query_count, None, "warm"),
            MatrixCondition(query_count, 10, "off"),
            MatrixCondition(query_count, 20, "off"),
            MatrixCondition(query_count, 50, "off"),
        )
    )


def campaign_code_provenance() -> dict[str, object]:
    """Hash every campaign implementation file, including files untracked at HEAD."""
    backend = Path(__file__).resolve().parents[1]
    files = (
        Path(__file__).resolve(),
        backend / "scripts" / "build_networking_benchmark.py",
        backend / "scripts" / "embedding_benchmark_matrix.py",
        backend / "src" / "ragz" / "modules" / "documents" / "pipeline.py",
        backend / "src" / "ragz" / "modules" / "retrieval" / "embeddings.py",
        backend / "src" / "ragz" / "modules" / "retrieval" / "query_expansion.py",
        backend / "src" / "ragz" / "modules" / "retrieval" / "service.py",
    )
    hashes = {
        str(path.relative_to(backend)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in files
    }
    aggregate = hashlib.sha256(
        json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {"aggregate_sha256": aggregate, "files_sha256": hashes}


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


def resolve_embedding_track(
    engine: str,
    *,
    model: str | None = None,
    dimension: int | None = None,
    litellm_model_name: str | None = None,
) -> EmbeddingTrack:
    if engine == "hash":
        if model is not None or dimension is not None or litellm_model_name is not None:
            raise ValueError("hash embedding track does not accept hosted model settings")
        return EmbeddingTrack(
            engine="hash",
            model="deterministic-hash",
            litellm_model_name="deterministic-hash",
            dimension=1024,
            provider_kind="tei",
            settings_backend="hash",
            dense_label="deterministic-hash-1024",
            provider_calls=0,
            provider_cost_usd=0.0,
        )
    if engine == "openai":
        from embedding_benchmark_matrix import cell_for

        selected_model = model or "text-embedding-3-small"
        selected_dimension = dimension if dimension is not None else 1536
        cell = cell_for(selected_model, selected_dimension)
        if litellm_model_name is not None and litellm_model_name != cell.alias:
            raise ValueError(
                f"LiteLLM alias {litellm_model_name!r} is not the fixed alias for {cell.cell_id}"
            )
        return EmbeddingTrack(
            engine="openai",
            model=cell.model,
            litellm_model_name=cell.alias,
            dimension=cell.dimension,
            provider_kind="openai",
            settings_backend="litellm",
            dense_label=f"openai-{cell.model}-{cell.dimension}",
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
    embedding_cache_hits: int = 0,
    embedding_cache_misses: int = 0,
    rerank_candidate_pool: int | None = None,
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
        "embedding_cache_hits": embedding_cache_hits,
        "embedding_cache_misses": embedding_cache_misses,
        "rerank_candidate_pool": rerank_candidate_pool,
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


def _install_benchmark_reranker(
    *, provider: str, api_key: str, model: str
) -> None:
    import ragz.modules.retrieval.service as retrieval
    from ragz.modules.retrieval.rerank import CohereReranker, LexicalReranker

    if provider == "cohere":
        if not api_key:
            raise RuntimeError("COHERE_API_KEY is required for the Cohere rerank matrix")
        reranker: Any = CohereReranker(
            base_url="https://api.cohere.com", api_key=api_key, model=model
        )
    elif provider == "lexical":
        reranker = LexicalReranker()
    else:
        raise ValueError("reranker provider must be lexical or cohere")

    async def controlled_reranker(_session: Any, _settings: Any) -> Any:
        return reranker

    retrieval.get_reranker = controlled_reranker  # type: ignore[attr-defined,assignment]


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
    from ragz.modules.documents.pipeline import chunk_document, upsert_points
    from ragz.modules.models.models import LOCAL_EMBEDDING_MODEL_ID, Model
    from ragz.modules.retrieval.client import COLLECTION
    from ragz.modules.retrieval.embeddings import embed_sparse, get_dense_embedder
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
                    litellm_model_name=embedding_track.litellm_model_name,
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
        litellm_model_name=embedding_track.litellm_model_name,
        dimension=embedding_track.dimension,
    )
    document_map: dict[UUID, str] = {}
    corpus_stats: dict[str, Any] = {
        "books": [],
        "chunks": 0,
        "index_atomic_latency_ms": {
            "parse": 0.0,
            "chunk": 0.0,
            "dense_embedding": 0.0,
            "sparse_embedding": 0.0,
            "qdrant_upsert": 0.0,
        },
    }
    embedding_usage: list[int] = []
    for book_id, path in pdfs:
        progress.stage = f"indexing:{book_id}"
        write_progress(output, progress)
        data = path.read_bytes()
        parse_started = time.perf_counter()
        blocks = await LiteParseParser().parse(data, path.name)
        parse_ms = (time.perf_counter() - parse_started) * 1000
        chunk_started = time.perf_counter()
        chunks = chunk_document(blocks, method="heading")
        chunk_ms = (time.perf_counter() - chunk_started) * 1000
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
        book_dense_ms = book_sparse_ms = book_upsert_ms = 0.0
        for start in range(0, len(chunks), index_batch_size):
            batch = chunks[start : start + index_batch_size]
            texts = [chunk.text for chunk in batch]
            dense_started = time.perf_counter()
            dense, billed_tokens = await dense_embedder.embed_with_usage(texts)
            dense_ms = (time.perf_counter() - dense_started) * 1000
            embedding_usage.append(billed_tokens)
            sparse_started = time.perf_counter()
            sparse = await asyncio.to_thread(embed_sparse, texts)
            sparse_ms = (time.perf_counter() - sparse_started) * 1000
            book_dense_ms += dense_ms
            book_sparse_ms += sparse_ms
            if embedding_track.engine == "openai":
                progress.index_embedding_calls_completed += 1
                progress.index_embedding_tokens += billed_tokens
                write_progress(output, progress)
            upsert_started = time.perf_counter()
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
            book_upsert_ms += (time.perf_counter() - upsert_started) * 1000
        index_timings = corpus_stats["index_atomic_latency_ms"]
        assert isinstance(index_timings, dict)
        index_timings["parse"] += parse_ms
        index_timings["chunk"] += chunk_ms
        index_timings["dense_embedding"] += book_dense_ms
        index_timings["sparse_embedding"] += book_sparse_ms
        index_timings["qdrant_upsert"] += book_upsert_ms
        corpus_stats["books"].append(
            {
                "book_id": book_id,
                "pages": max((block.page for block in blocks), default=0),
                "chunks": len(chunks),
                "parse_ms": round(parse_ms, 4),
                "chunk_ms": round(chunk_ms, 4),
                "dense_embedding_ms": round(book_dense_ms, 4),
                "sparse_embedding_ms": round(book_sparse_ms, 4),
                "qdrant_upsert_ms": round(book_upsert_ms, 4),
            }
        )
        corpus_stats["chunks"] = int(corpus_stats["chunks"]) + len(chunks)
    corpus_stats["index_embedding_tokens"] = sum(embedding_usage)
    corpus_stats["index_embedding_calls_completed"] = (
        progress.index_embedding_calls_completed
    )
    corpus_stats["index_atomic_latency_ms"] = {
        stage: round(float(duration), 4)
        for stage, duration in corpus_stats["index_atomic_latency_ms"].items()
    }
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
    query_count: int | None = None,
    rerank_candidate_pool: int | None = None,
    cache_mode: str = "off",
) -> dict[str, Any]:
    from sqlalchemy import select

    from ragz.modules.quotas.models import UsageRecord
    from ragz.modules.retrieval.embeddings import InMemoryQueryEmbeddingCache
    from ragz.modules.retrieval.service import retrieve
    from ragz.modules.tenancy.models import Workspace

    create_output_directory(output)
    records: list[dict[str, Any]] = []
    warmup_records: list[dict[str, Any]] = []
    rerank_usage_units = 0
    condition_query_count = query_count or (3 if mode == "multi" else 1)
    if condition_query_count not in (1, 3, 5):
        raise ValueError("query_count must be 1, 3, or 5")
    if cache_mode not in {"off", "warm"}:
        raise ValueError("cache_mode must be off or warm")
    embedding_cache = (
        InMemoryQueryEmbeddingCache() if cache_mode == "warm" else None
    )
    async with factory() as session:
        workspace = await session.get(Workspace, workspace_id)
        assert workspace is not None
        workspace.multi_query_enabled = condition_query_count > 1
        workspace.rerank_enabled = rerank_candidate_pool is not None
        await session.commit()
        progress.stage = f"retrieval:{mode}:warmup"
        write_progress(progress_output, progress)
        for warmup_index in range(1, warmups + 1):
            for record in queries:
                if provider_backed_embeddings:
                    progress.query_embedding_attempts += 1
                    write_progress(progress_output, progress)
                warmup_timings_ms: dict[str, float] = {}
                warmup_started = time.perf_counter()
                warmup_result = await retrieve(
                    session,
                    ctx,
                    workspace_id,
                    record["query"],
                    top_k=top_k,
                    query_expander=(
                        StaticQueryExpander(
                            record["alternatives"][: condition_query_count - 1]
                        )
                        if condition_query_count > 1
                        else None
                    ),
                    multi_query_count_override=condition_query_count,
                    rerank_candidate_pool_override=rerank_candidate_pool,
                    query_embedding_cache=embedding_cache,
                    stage_timings_ms=warmup_timings_ms,
                )
                warmup_elapsed_ms = (time.perf_counter() - warmup_started) * 1000
                warmup_timings_ms["unattributed_runner"] = round(
                    max(0.0, warmup_elapsed_ms - sum(warmup_timings_ms.values())),
                    4,
                )
                warmup_records.append(
                    {
                        "query_id": record["query_id"],
                        "warmup": warmup_index,
                        "elapsed_ms": round(warmup_elapsed_ms, 4),
                        "embedding_cache_hits": warmup_result.embedding_cache_hits,
                        "embedding_cache_misses": warmup_result.embedding_cache_misses,
                        "stage_timings_ms": warmup_timings_ms,
                        "error": None,
                    }
                )
        progress.stage = f"retrieval:{mode}:scored"
        write_progress(progress_output, progress)
        for repetition in range(1, repetitions + 1):
            for record in queries:
                expander = (
                    StaticQueryExpander(
                        record["alternatives"][: condition_query_count - 1]
                    )
                    if condition_query_count > 1
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
                        multi_query_count_override=condition_query_count,
                        rerank_candidate_pool_override=rerank_candidate_pool,
                        query_embedding_cache=embedding_cache,
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
                        embedding_cache_hits=(
                            int(result.embedding_cache_hits)
                            if result is not None
                            else 0
                        ),
                        embedding_cache_misses=(
                            int(result.embedding_cache_misses)
                            if result is not None
                            else 0
                        ),
                        rerank_candidate_pool=rerank_candidate_pool,
                    )
                )
        if rerank_candidate_pool is not None:
            usage_rows = (
                await session.execute(
                    select(UsageRecord).where(UsageRecord.feature == "rerank")
                )
            ).scalars().all()
            rerank_usage_units = sum(int(row.units) for row in usage_rows)
    with (output / "per_query.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    with (output / "warmups.jsonl").open("w", encoding="utf-8") as handle:
        for record in warmup_records:
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
        "condition": {
            "query_count": condition_query_count,
            "rerank_candidate_pool": rerank_candidate_pool,
            "cache_mode": cache_mode,
        },
        "query_count": len(queries),
        "observations": len(records),
        "quality_observations": len(quality_records),
        "abstention_observations": len(abstention_records),
        "answerable_queries": sum(bool(item["answerable"]) for item in queries),
        "unanswerable_queries": sum(not bool(item["answerable"]) for item in queries),
        "warmups": warmups,
        "repetitions": repetitions,
        "errors": sum(item["error"] is not None for item in records),
        "embedding_cache": {
            "hits": sum(int(item["embedding_cache_hits"]) for item in records),
            "misses": sum(int(item["embedding_cache_misses"]) for item in records),
        },
        "rerank_usage_units_including_warmups": rerank_usage_units,
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
            "mean": statistics.mean(latencies) if latencies else None,
            "p50": percentile(latencies, 0.5),
            "p95": percentile(latencies, 0.95),
            "p99": percentile(latencies, 0.99),
        },
        "atomic_latency_ms": summarize_stage_timings(records),
        "warmup_atomic_latency_ms": summarize_stage_timings(warmup_records),
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
    embedding_track = resolve_embedding_track(
        args.embedding_engine,
        model=args.embedding_model,
        dimension=args.embedding_dimension,
        litellm_model_name=args.embedding_litellm_model_name,
    )
    litellm_master_key = os.environ.get("RAGZ_LITELLM_MASTER_KEY", "")
    cohere_api_key = os.environ.get("COHERE_API_KEY", "")
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
            "campaign_code_provenance": campaign_code_provenance(),
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
            "embedding_litellm_model_name": embedding_track.litellm_model_name,
            "embedding_alias": embedding_track.litellm_model_name,
            "embedding_dimension": embedding_track.dimension,
            "embedding_requested_dimension": embedding_track.dimension,
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
            "reranker_provider": args.reranker_provider,
            "reranker_model": (
                args.cohere_rerank_model
                if args.reranker_provider == "cohere"
                else "lexical-overlap"
            ),
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
            _install_benchmark_reranker(
                provider=args.reranker_provider,
                api_key=cohere_api_key,
                model=args.cohere_rerank_model,
            )
            summaries: dict[str, dict[str, Any]] = {}
            if args.matrix:
                if any(len(record["alternatives"]) != 4 for record in queries):
                    raise ValueError("matrix runs require four alternatives per query")
                conditions = list(retrieval_matrix_conditions())
                if args.matrix_order == "reverse":
                    conditions.reverse()
                for condition in conditions:
                    summaries[condition.condition_id] = await _run_mode(
                        mode=condition.condition_id,
                        queries=queries,
                        factory=factory,
                        ctx=ctx,
                        workspace_id=workspace_id,
                        document_map=document_map,
                        output=output / condition.condition_id,
                        top_k=args.top_k,
                        warmups=args.warmups,
                        repetitions=args.repetitions,
                        provider_backed_embeddings=embedding_track.engine == "openai",
                        progress=progress,
                        progress_output=output,
                        query_count=condition.query_count,
                        rerank_candidate_pool=condition.rerank_candidate_pool,
                        cache_mode=condition.cache_mode,
                    )
            else:
                modes = (
                    ("single", "multi")
                    if args.order == "single-first"
                    else ("multi", "single")
                )
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
    manifest["condition_order"] = (
        args.matrix_order if args.matrix else args.order
    )
    manifest["warmups"] = args.warmups
    manifest["repetitions"] = args.repetitions
    manifest["no_answer_threshold"] = {
        "value": args.min_score,
        "score_space": "maximum_dense_cosine",
        "calibration": args.threshold_calibration,
    }
    manifest["conditions"] = summaries
    manifest["condition_matrix"] = args.matrix
    if args.matrix:
        manifest["reranker"] = f"{args.reranker_provider}-screen"
        manifest["query_variants"] = "fixed-four-perspective-alternatives"
        manifest["matrix_protocol"] = {
            "query_counts": [1, 3, 5],
            "rerank_candidate_pools": [None, 10, 20, 50],
            "cache_modes": ["off", "warm"],
            "conditions": list(summaries),
            "llm_top_p": "provider-default-not-a-reranker-control",
        }
    manifest["provider_progress"] = {
        "index_embedding_calls_completed": progress.index_embedding_calls_completed,
        "index_embedding_tokens": progress.index_embedding_tokens,
        "query_embedding_attempts": progress.query_embedding_attempts,
    }
    manifest["status"] = "completed"
    if args.matrix:
        reranker_model_label = (
            args.cohere_rerank_model
            if args.reranker_provider == "cohere"
            else "lexical-overlap"
        )
        (output / "matrix-summary.json").write_text(
            json.dumps(summaries, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (output / "summary.md").write_text(
            "# RAGZ MQR/rerank/cache retrieval matrix\n\n"
            f"- Commit: `{git_commit}`\n"
            f"- Conditions: `{len(summaries)}`\n"
            f"- Condition order: `{args.matrix_order}`\n"
            f"- Warmups/repetitions: `{args.warmups}` / `{args.repetitions}`\n"
            "- Reranker: `benchmark-controlled provider seam`\n"
            f"- Reranker provider/model: `{args.reranker_provider}` / "
            f"`{reranker_model_label}`\n"
            "- LLM top_p: `provider default; not varied`\n",
            encoding="utf-8",
        )
    else:
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
        "--matrix",
        action="store_true",
        help="run the frozen 15-condition MQR/rerank/cache retrieval screen",
    )
    parser.add_argument(
        "--matrix-order",
        choices=("forward", "reverse"),
        default="forward",
        help="counterbalance the frozen matrix without changing condition definitions",
    )
    parser.add_argument(
        "--reranker-provider",
        choices=("lexical", "cohere"),
        default="lexical",
    )
    parser.add_argument(
        "--cohere-rerank-model",
        choices=("rerank-v4.0-fast", "rerank-v4.0-pro"),
        default="rerank-v4.0-fast",
    )
    parser.add_argument(
        "--embedding-engine",
        choices=("hash", "openai"),
        default="hash",
        help="Dense embedding track; OpenAI model and width are explicit matrix inputs",
    )
    parser.add_argument(
        "--embedding-model",
        choices=("text-embedding-3-small", "text-embedding-3-large"),
        help="Underlying OpenAI embedding model; valid only with --embedding-engine openai",
    )
    parser.add_argument(
        "--embedding-dimension",
        type=int,
        help="Requested OpenAI vector width; valid only with --embedding-engine openai",
    )
    parser.add_argument(
        "--embedding-litellm-model-name",
        help="Attested LiteLLM alias for the selected model/dimension cell",
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
                failed_track = resolve_embedding_track(
                    args.embedding_engine,
                    model=args.embedding_model,
                    dimension=args.embedding_dimension,
                    litellm_model_name=args.embedding_litellm_model_name,
                )
                failed_manifest = {
                    "schema_version": 1,
                    "runner_version": "3.0",
                    "dataset_id": "networking-pdfs-v1",
                    "source_pdf_count": len(args.pdf),
                    "query_set_filename": args.queries.name,
                    "embedding_engine": failed_track.engine,
                    "embedding_model": failed_track.model,
                    "embedding_litellm_model_name": failed_track.litellm_model_name,
                    "embedding_alias": failed_track.litellm_model_name,
                    "embedding_dimension": failed_track.dimension,
                    "embedding_requested_dimension": failed_track.dimension,
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
