#!/usr/bin/env python3
"""Paired single-query versus multi-query RAGZ retrieval benchmark.

The runner parses the supplied PDFs locally with RAGZ LiteParse, indexes the
same chunks once into an isolated Qdrant/Postgres pair, changes only the
workspace multi-query toggle, and writes no query/document/provider text.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import shutil
import subprocess
import time
from contextlib import ExitStack
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


def ranking_metrics(
    *, retrieved: list[str], relevant: set[str], k: int
) -> dict[str, float]:
    ranked = retrieved[:k]
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
    metrics: dict[str, float],
    elapsed_ms: float,
    expansion_count: int,
    error: str | None,
) -> dict[str, Any]:
    return {
        "query_id": query_id,
        "mode": mode,
        "retrieved": retrieved,
        "metrics": metrics,
        "elapsed_ms": round(elapsed_ms, 4),
        "expansion_count": expansion_count,
        "error": error,
    }


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
        embedding_backend="hash",
        embedding_dim=1024,
        rerank_backend="lexical",
        litellm_url="http://127.0.0.1:1",
        model_catalog_url="",
    )
    _install_settings(settings)
    engine = build_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = build_session_factory(engine)
    org_id, workspace_id, user_id = uuid4(), uuid4(), uuid4()
    async with factory() as session:
        session.add(Organization(id=org_id, name=f"networking-bench-{org_id.hex[:8]}"))
        session.add_all(
            [
                Model(
                    id=LOCAL_EMBEDDING_MODEL_ID,
                    litellm_model_name="local-embeddings",
                    display_name="Hash benchmark embeddings",
                    provider_kind="tei",
                    modality="embedding",
                    dimension=1024,
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
                embedding_model_id=LOCAL_EMBEDDING_MODEL_ID,
                top_k=5,
                min_score=0.0,
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
    await ensure_collection(COLLECTION, 1024)
    dense_embedder = get_dense_embedder(
        LOCAL_EMBEDDING_MODEL_ID,
        provider_kind="tei",
        litellm_model_name="local-embeddings",
    )
    document_map: dict[UUID, str] = {}
    corpus_stats: dict[str, Any] = {"books": [], "chunks": 0}
    for book_id, path in pdfs:
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
        for start in range(0, len(chunks), 64):
            batch = chunks[start : start + 64]
            dense, sparse = await embed_batch(
                [chunk.text for chunk in batch], dense_embedder
            )
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
        for record in queries:
            expander = (
                StaticQueryExpander(record["alternatives"])
                if mode == "multi"
                else None
            )
            started = time.perf_counter()
            error: str | None = None
            result: Any = None
            try:
                result = await retrieve(
                    session,
                    ctx,
                    workspace_id,
                    record["query"],
                    top_k=top_k,
                    query_expander=expander,
                )
            except Exception as exc:  # noqa: BLE001 - benchmark records typed failure only
                error = type(exc).__name__
            elapsed_ms = (time.perf_counter() - started) * 1000
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
            metrics = ranking_metrics(
                retrieved=evidence_ids,
                relevant=_relevant_keys(record),
                k=top_k,
            )
            records.append(
                safe_query_record(
                    query_id=record["query_id"],
                    mode=mode,
                    retrieved=retrieved,
                    metrics=metrics,
                    elapsed_ms=elapsed_ms,
                    expansion_count=3 if mode == "multi" else 1,
                    error=error,
                )
            )
    with (output / "per_query.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    latencies = [float(item["elapsed_ms"]) for item in records if item["error"] is None]
    summary: dict[str, Any] = {
        "mode": mode,
        "query_count": len(records),
        "errors": sum(item["error"] is not None for item in records),
        "mean_recall_at_k": sum(float(item["metrics"]["recall_at_k"]) for item in records)
        / len(records),
        "mean_reciprocal_rank": sum(
            float(item["metrics"]["reciprocal_rank"]) for item in records
        )
        / len(records),
        "mean_ndcg_at_k": sum(float(item["metrics"]["ndcg_at_k"]) for item in records)
        / len(records),
        "latency_ms": {
            "p50": percentile(latencies, 0.5),
            "p95": percentile(latencies, 0.95),
        },
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


async def run(args: argparse.Namespace) -> None:
    output = args.output.resolve()
    create_output_directory(output)
    queries = load_query_set(args.queries.resolve())
    manifest = build_manifest(args.pdf, args.queries.resolve())
    git_executable = shutil.which("git")
    if git_executable is None:
        raise RuntimeError("git executable not found")
    manifest.update(
        {
            "runner_version": "1.0",
            "git_commit": subprocess.check_output(  # noqa: S603 - fixed git argv
                [git_executable, "rev-parse", "HEAD"], text=True
            ).strip(),
            "top_k": args.top_k,
            "dense": "deterministic-hash-1024",
            "sparse": "fastembed-bm25",
            "fusion": "qdrant-rrf",
            "reranker": "disabled",
            "query_variants": "fixed-two-alternatives",
        }
    )
    with ExitStack() as stack:
        postgres = stack.enter_context(PostgresContainer("postgres:16-alpine"))
        qdrant = stack.enter_context(QdrantContainer("qdrant/qdrant:v1.18.0"))
        database_url = postgres.get_connection_url().replace("psycopg2", "asyncpg")
        qdrant_url = (
            f"http://{qdrant.get_container_host_ip()}:"
            f"{qdrant.get_exposed_port(6333)}"
        )
        engine, factory, ctx, workspace_id, document_map, corpus_stats = await _seed_corpus(
            pdfs=args.pdf,
            database_url=database_url,
            qdrant_url=qdrant_url,
        )
        try:
            single = await _run_mode(
                mode="single",
                queries=queries,
                factory=factory,
                ctx=ctx,
                workspace_id=workspace_id,
                document_map=document_map,
                output=output / "single",
                top_k=args.top_k,
            )
            multi = await _run_mode(
                mode="multi",
                queries=queries,
                factory=factory,
                ctx=ctx,
                workspace_id=workspace_id,
                document_map=document_map,
                output=output / "multi",
                top_k=args.top_k,
            )
        finally:
            await engine.dispose()
    manifest["corpus_stats"] = corpus_stats
    manifest["conditions"] = {"single": single, "multi": multi}
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", action="append", required=True, type=parse_pdf_arg)
    parser.add_argument("--queries", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    if len(args.pdf) != 3 or len({book_id for book_id, _ in args.pdf}) != 3:
        raise ValueError("exactly three uniquely named PDFs are required")
    if not 1 <= args.top_k <= 50:
        raise ValueError("top-k must be between 1 and 50")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
