#!/usr/bin/env python3
"""Run privacy-safe RAG-Triad evaluation over the frozen RAGZ retrieval matrix.

The runner restores the exact Postgres/Qdrant state captured during the
retrieval screen.  It never persists questions, document text, answers,
references, prompts, or provider response bodies.  Public rows contain only
query/condition IDs, hashes, numeric metrics, timings, usage, and typed errors.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from contextlib import ExitStack
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]
from testcontainers.qdrant import QdrantContainer  # type: ignore[import-untyped]

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from run_multi_query_benchmark import (  # noqa: E402
    StaticQueryExpander,
    _install_benchmark_reranker,
    _install_settings,
)
from run_open_manuals_matrix_cell import (  # noqa: E402
    GENERATION_MODEL,
    JUDGE_MODEL,
    LiteLLMClient,
    _load_module,
    _provider_cost,
)

DEFAULT_PROVIDER_RUNNER = Path(
    "/home/parshu/projects/ragz/no_rel/ragz-benchmark-lab/scripts/run_openai_qa.py"
)
COLLECTION = "chunks_bge_m3"
EMBEDDING_ALIAS = "ragz-openai-text-embedding-3-large-d1024"
EMBEDDING_MODEL = "text-embedding-3-large"
EMBEDDING_DIMENSION = 1024
RERANK_MODEL = "rerank-v4.0-fast"
ANSWER_METRICS = (
    "context_relevance",
    "groundedness",
    "answer_relevance",
    "correctness",
    "citation_entailment",
    "citation_precision",
    "citation_completeness",
)
ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "answer": {"type": "string"},
        "abstained": {"type": "boolean"},
        "claims": {"type": "array", "items": {"type": "string"}},
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "marker": {"type": "integer"},
                    "chunk_id": {"type": "string"},
                },
                "required": ["marker", "chunk_id"],
            },
        },
    },
    "required": ["answer", "abstained", "claims", "citations"],
}
JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        **{name: {"type": "number"} for name in ANSWER_METRICS},
        "explanation": {"type": "string"},
    },
    "required": [*ANSWER_METRICS, "explanation"],
}


class TriadContractError(RuntimeError):
    """Safe failure that does not include private/provider content."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def condition_id(query_count: int, rerank_pool: int | None) -> str:
    if query_count not in (1, 3, 5):
        raise ValueError("query_count must be 1, 3, or 5")
    if rerank_pool not in (None, 10, 20, 50):
        raise ValueError("rerank_pool must be off, 10, 20, or 50")
    return f"q{query_count}_rerank-{rerank_pool or 'off'}_cache-off"


def ranking_conditions() -> tuple[tuple[int, int | None], ...]:
    return tuple(
        (query_count, pool)
        for query_count in (1, 3, 5)
        for pool in (None, 10, 20, 50)
    )


def load_private_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise TriadContractError("private query set must be a non-empty JSON array")
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in payload:
        if not isinstance(value, Mapping):
            raise TriadContractError("private query record is not an object")
        query_id = str(value.get("query_id", "")).strip()
        query = str(value.get("query", "")).strip()
        alternatives = value.get("alternatives")
        answerable = value.get("answerable")
        if not query_id or query_id in seen or not query:
            raise TriadContractError("private query ID/query contract failed")
        if (
            not isinstance(alternatives, list)
            or len(alternatives) != 4
            or any(not isinstance(item, str) or not item.strip() for item in alternatives)
        ):
            raise TriadContractError(f"{query_id}: four alternatives are required")
        if not isinstance(answerable, bool):
            raise TriadContractError(f"{query_id}: answerable must be boolean")
        expected_answer = value.get("expected_answer")
        if answerable and not isinstance(expected_answer, str):
            raise TriadContractError(f"{query_id}: expected answer is required")
        relevant = value.get("relevant")
        if not isinstance(relevant, list):
            raise TriadContractError(f"{query_id}: relevant evidence is malformed")
        seen.add(query_id)
        cases.append(dict(value))
    return cases


def load_source_map(path: Path) -> dict[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    documents = payload.get("documents") if isinstance(payload, Mapping) else None
    if not isinstance(documents, list) or not documents:
        raise TriadContractError("source manifest has no documents")
    result: dict[str, str] = {}
    for item in documents:
        if not isinstance(item, Mapping):
            raise TriadContractError("source manifest document is malformed")
        filename = str(item.get("filename", "")).strip()
        doc_id = str(item.get("doc_id", "")).strip()
        if not filename or not doc_id or filename in result:
            raise TriadContractError("source filename/doc ID contract failed")
        result[filename] = doc_id
    return result


def load_screen_rankings(
    screen: Path, expected_query_ids: set[str]
) -> dict[str, dict[str, list[dict[str, object]]]]:
    manifest = json.loads((screen / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "completed" or manifest.get("condition_matrix") is not True:
        raise TriadContractError("retrieval screen is not a completed matrix")
    result: dict[str, dict[str, list[dict[str, object]]]] = {}
    for query_count, pool in ranking_conditions():
        key = condition_id(query_count, pool)
        rows_path = screen / key / "per_query.jsonl"
        rows = [
            json.loads(line)
            for line in rows_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if len(rows) != len(expected_query_ids):
            raise TriadContractError(f"{key}: screen denominator mismatch")
        by_query: dict[str, list[dict[str, object]]] = {}
        for row in rows:
            query_id = str(row.get("query_id", ""))
            if query_id in by_query or row.get("error") is not None:
                raise TriadContractError(f"{key}: duplicate or failed screen row")
            retrieved = row.get("retrieved")
            if not isinstance(retrieved, list):
                raise TriadContractError(f"{key}: malformed ranking")
            by_query[query_id] = [dict(item) for item in retrieved]
        if set(by_query) != expected_query_ids:
            raise TriadContractError(f"{key}: query IDs do not match")
        result[key] = by_query
    return result


def build_context(
    chunks: Sequence[Mapping[str, object]], *, max_chars: int
) -> tuple[str, list[str]]:
    if max_chars < 2_000:
        raise ValueError("max_chars must be at least 2000")
    parts: list[str] = []
    identifiers: list[str] = []
    remaining = max_chars
    for index, chunk in enumerate(chunks, 1):
        chunk_id = str(chunk["chunk_id"])
        text = str(chunk["text"])
        header = f"[{index}] chunk_id={chunk_id}\n"
        allowance = max(0, remaining - len(header))
        if allowance <= 0:
            break
        body = text[:allowance]
        part = header + body
        parts.append(part)
        identifiers.append(chunk_id)
        remaining -= len(part) + 2
        if remaining <= 0:
            break
    if not parts:
        return "(no retrieved context)", []
    return "\n\n".join(parts), identifiers


def safe_score(value: object) -> float:
    try:
        return max(0.0, min(1.0, float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def safe_error(exc: BaseException) -> str:
    return type(exc).__name__


def citation_metrics(
    answer: Mapping[str, object], *, valid_ids: set[str], relevant_pages: set[str]
) -> dict[str, float | int | None]:
    raw = answer.get("citations")
    citations = raw if isinstance(raw, list) else []
    cited_ids = [
        str(item.get("chunk_id", ""))
        for item in citations
        if isinstance(item, Mapping) and str(item.get("chunk_id", ""))
    ]
    valid = [item for item in cited_ids if item in valid_ids]
    cited_pages = {":".join(item.split(":")[:2]) for item in valid}
    evidence_hits = cited_pages & relevant_pages
    return {
        "citation_count": len(cited_ids),
        "valid_citation_count": len(valid),
        "citation_validity": len(valid) / len(cited_ids) if cited_ids else None,
        "citation_evidence_precision": (
            len(evidence_hits) / len(cited_pages) if cited_pages else None
        ),
        "citation_evidence_recall": (
            len(evidence_hits) / len(relevant_pages) if relevant_pages else None
        ),
    }


def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    complete = [row for row in rows if not row.get("error_codes")]
    answerable = [row for row in complete if row.get("answerable") is True]
    triad = {
        name: statistics.fmean(float(row["judge"][name]) for row in answerable)
        if answerable
        else None
        for name in ANSWER_METRICS
    }
    triad["secondary_composite"] = (
        statistics.fmean(
            float(row["judge"][name])
            for row in answerable
            for name in ("context_relevance", "groundedness", "answer_relevance")
        )
        if answerable
        else None
    )
    tp = sum(not row["answerable"] and row["abstained"] for row in complete)
    fp = sum(row["answerable"] and row["abstained"] for row in complete)
    fn = sum(not row["answerable"] and not row["abstained"] for row in complete)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    latency_names = sorted(
        {str(name) for row in complete for name in row.get("timings_ms", {})}
    )
    latency = {
        name: {
            "observations": len(values := [
                float(row["timings_ms"][name])
                for row in complete
                if name in row.get("timings_ms", {})
            ]),
            "mean_ms": statistics.fmean(values),
            "p50_ms": statistics.median(values),
            "max_ms": max(values),
        }
        for name in latency_names
    }
    return {
        "observations": len(rows),
        "complete": len(complete),
        "errors": len(rows) - len(complete),
        "answerable": len(answerable),
        "rag_triad": triad,
        "answer_abstention": {
            "true_positive": tp,
            "false_positive": fp,
            "false_negative": fn,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        },
        "latency_ms": latency,
    }


def restore_postgres(container_id: str, dump: Path) -> None:
    docker = shutil.which("docker")
    if docker is None:
        raise TriadContractError("docker executable not found")
    # This path is inside a new single-purpose benchmark container.
    target = "/tmp/ragz-triad-postgres.dump"  # noqa: S108
    subprocess.run(  # noqa: S603 - fixed docker argv plus resolved container ID
        [docker, "cp", str(dump), f"{container_id}:{target}"],
        check=True,
        capture_output=True,
    )
    completed = subprocess.run(  # noqa: S603 - fixed docker/pg_restore argv
        [
            docker,
            "exec",
            container_id,
            "pg_restore",
            "-U",
            "test",
            "-d",
            "test",
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-privileges",
            target,
        ],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise TriadContractError("Postgres state restoration failed")


def restore_qdrant(base_url: str, snapshot: Path) -> None:
    with snapshot.open("rb") as handle:
        response = httpx.post(
            f"{base_url.rstrip('/')}/collections/{COLLECTION}/snapshots/upload",
            params={"priority": "snapshot"},
            files={"snapshot": (snapshot.name, handle, "application/octet-stream")},
            timeout=300.0,
        )
    if not 200 <= response.status_code < 300:
        raise TriadContractError(f"Qdrant snapshot restoration failed ({response.status_code})")


async def _database_context(database_url: str) -> tuple[Any, Any, Any, UUID, dict[UUID, str]]:
    from ragz.core.db import build_engine, build_session_factory
    from ragz.modules.auth.models import User
    from ragz.modules.documents.models import Document
    from ragz.modules.tenancy.context import TenantContext
    from ragz.modules.tenancy.models import Workspace

    engine = build_engine(database_url)
    factory = build_session_factory(engine)
    async with factory() as session:
        workspaces = (await session.execute(select(Workspace))).scalars().all()
        users = (await session.execute(select(User))).scalars().all()
        documents = (await session.execute(select(Document))).scalars().all()
    if len(workspaces) != 1 or len(users) != 1 or len(documents) != 3:
        await engine.dispose()
        raise TriadContractError("restored benchmark database denominator is invalid")
    workspace, user = workspaces[0], users[0]
    ctx = TenantContext(
        user_id=user.id,
        org_id=user.org_id,
        role="user",
        workspace_ids=frozenset({workspace.id}),
    )
    return engine, factory, ctx, workspace.id, {
        document.id: document.filename for document in documents
    }


async def run(args: argparse.Namespace) -> None:
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    output.mkdir(parents=True)
    private_state = args.private_state.resolve()
    snapshot = private_state / "chunks_bge_m3.snapshot"
    postgres_dump = private_state / "postgres.dump"
    for path in (snapshot, postgres_dump, args.private_queries.resolve()):
        if not path.is_file():
            raise TriadContractError(f"required private input is missing: {path.name}")
    cases = load_private_cases(args.private_queries.resolve())
    expected_query_ids = {str(case["query_id"]) for case in cases}
    screen = args.screen.resolve()
    screen_rankings = load_screen_rankings(screen, expected_query_ids)
    source_map = load_source_map(args.sources.resolve())
    litellm_key = os.environ.get("RAGZ_LITELLM_MASTER_KEY", "")
    cohere_key = os.environ.get("COHERE_API_KEY", "")
    if not litellm_key or not cohere_key:
        raise TriadContractError("LiteLLM and Cohere credentials are required")
    runner = _load_module(args.provider_runner.resolve(), "ragz_triad_provider_runner")
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "status": "running",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "benchmark": "ragz-large-books-mqr-rerank-triad",
        "conditions": [condition_id(*value) for value in ranking_conditions()],
        "denominator": {
            "total": len(cases),
            "answerable": sum(bool(case["answerable"]) for case in cases),
            "unanswerable": sum(not bool(case["answerable"]) for case in cases),
        },
        "models": {
            "embedding_alias": EMBEDDING_ALIAS,
            "embedding_model": EMBEDDING_MODEL,
            "embedding_dimension": EMBEDDING_DIMENSION,
            "generation": GENERATION_MODEL,
            "judge": JUDGE_MODEL,
            "reranker": RERANK_MODEL,
        },
        "judge_independence": "separate_model_same_provider",
        "rag_triad": "exploratory_llm_judge_not_independent_ground_truth",
        "state_sha256": {
            "qdrant_snapshot": sha256_file(snapshot),
            "postgres_dump": sha256_file(postgres_dump),
            "private_queries": sha256_file(args.private_queries.resolve()),
            "retrieval_screen_manifest": sha256_file(screen / "manifest.json"),
        },
        "privacy": {
            "private_inputs_persisted_publicly": False,
            "questions_persisted": False,
            "contexts_persisted": False,
            "answers_persisted": False,
            "provider_bodies_persisted": False,
        },
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    all_rows: list[dict[str, Any]] = []
    client = LiteLLMClient(
        runner,
        base_url=args.litellm_url,
        api_key=litellm_key,
        embedding_alias=EMBEDDING_ALIAS,
        embedding_model=EMBEDDING_MODEL,
        embedding_dimension=EMBEDDING_DIMENSION,
        generation_model=GENERATION_MODEL,
        judge_model=JUDGE_MODEL,
        max_retries=args.provider_retries,
    )
    with ExitStack() as stack:
        postgres = stack.enter_context(PostgresContainer("postgres:16-alpine"))
        qdrant = stack.enter_context(QdrantContainer("qdrant/qdrant:v1.18.0"))
        restore_postgres(postgres.get_wrapped_container().id, postgres_dump)
        database_url = postgres.get_connection_url().replace("psycopg2", "asyncpg")
        qdrant_url = (
            f"http://{qdrant.get_container_host_ip()}:"
            f"{qdrant.get_exposed_port(6333)}"
        )
        restore_qdrant(qdrant_url, snapshot)
        from ragz.core.config import Settings
        from ragz.modules.models.models import Model
        from ragz.modules.retrieval.service import retrieve
        from ragz.modules.tenancy.models import Workspace

        settings = Settings(  # type: ignore[call-arg]
            _env_file=None,
            environment="test",
            database_url=database_url,
            qdrant_url=qdrant_url,
            embedding_backend="litellm",
            embedding_dim=EMBEDDING_DIMENSION,
            rerank_backend="lexical",
            litellm_url=args.litellm_url,
            litellm_master_key=litellm_key,
            model_catalog_url="",
        )
        _install_settings(settings)
        _install_benchmark_reranker(
            provider="cohere",
            api_key=cohere_key,
            model=RERANK_MODEL,
            requests_per_minute=args.reranker_rpm,
        )
        engine, factory, ctx, workspace_id, document_filenames = await _database_context(
            database_url
        )
        try:
            async with factory() as session:
                workspace = await session.get(Workspace, workspace_id)
                assert workspace is not None
                model = await session.get(Model, workspace.embedding_model_id)
                assert model is not None
                if (
                    model.litellm_model_name != EMBEDDING_ALIAS
                    or model.dimension != EMBEDDING_DIMENSION
                ):
                    raise TriadContractError("restored embedding model contract mismatch")
            document_ids: dict[UUID, str] = {}
            for document_id, filename in document_filenames.items():
                if filename not in source_map:
                    raise TriadContractError("restored document has no source mapping")
                document_ids[document_id] = source_map[filename]
            for query_count, rerank_pool in ranking_conditions():
                key = condition_id(query_count, rerank_pool)
                condition_rows: list[dict[str, Any]] = []
                async with factory() as session:
                    workspace = await session.get(Workspace, workspace_id)
                    assert workspace is not None
                    workspace.multi_query_enabled = query_count > 1
                    workspace.rerank_enabled = rerank_pool is not None
                    await session.commit()
                    for case in cases:
                        query_id = str(case["query_id"])
                        errors: list[str] = []
                        timings: dict[str, float] = {}
                        total_started = time.perf_counter()
                        retrieval_stages: dict[str, float] = {}
                        retrieval_started = time.perf_counter()
                        result: Any = None
                        try:
                            result = await retrieve(
                                session,
                                ctx,
                                workspace_id,
                                str(case["query"]),
                                top_k=5,
                                query_expander=(
                                    StaticQueryExpander(
                                        list(case["alternatives"][: query_count - 1])
                                    )
                                    if query_count > 1
                                    else None
                                ),
                                multi_query_count_override=query_count,
                                rerank_candidate_pool_override=rerank_pool,
                                strict_rerank=rerank_pool is not None,
                                stage_timings_ms=retrieval_stages,
                            )
                        except Exception as exc:  # noqa: BLE001
                            errors.append(f"retrieval:{safe_error(exc)}")
                        timings["retrieval_total"] = (
                            time.perf_counter() - retrieval_started
                        ) * 1000
                        chunks: list[dict[str, object]] = []
                        if result is not None:
                            for chunk in result.chunks:
                                book_id = document_ids[chunk.document_id]
                                chunks.append(
                                    {
                                        "chunk_id": f"{book_id}:{chunk.page}:{chunk.chunk_index}",
                                        "screen_id": f"{book_id}:{chunk.page}",
                                        "score": round(float(chunk.score), 8),
                                        "text": chunk.text,
                                    }
                                )
                        actual_screen = [
                            {"evidence_id": item["screen_id"], "rank": rank, "score": item["score"]}
                            for rank, item in enumerate(chunks, 1)
                        ]
                        expected_screen = screen_rankings[key][query_id]
                        ranking_match = actual_screen == expected_screen
                        if not ranking_match:
                            errors.append("retrieval:RankingDrift")
                        context_started = time.perf_counter()
                        context_text, context_ids = build_context(
                            chunks, max_chars=args.max_context_chars
                        )
                        context_hash = canonical_hash(
                            [(item["chunk_id"], item["text"]) for item in chunks]
                        )
                        sent_context_hash = hashlib.sha256(context_text.encode("utf-8")).hexdigest()
                        timings["context_assembly"] = (
                            time.perf_counter() - context_started
                        ) * 1000
                        answer: dict[str, Any] = {
                            "answer": "",
                            "abstained": True,
                            "claims": [],
                            "citations": [],
                        }
                        generation_usage = runner.Usage().as_dict()
                        judge_usage = runner.Usage().as_dict()
                        judge = {name: 0.0 for name in ANSWER_METRICS}
                        if not errors:
                            generation_user = (
                                "Answer the question using only the supplied context. "
                                "Cite every material claim with an exact chunk_id from the "
                                "context. If the context is insufficient, set abstained=true "
                                "and do not guess. "
                                "Return only the requested JSON object.\n"
                                f"Question: {case['query']}\nContext:\n{context_text}"
                            )
                            generation_started = time.perf_counter()
                            try:
                                response: Any = await asyncio.to_thread(
                                    client.response,
                                    model=GENERATION_MODEL,
                                    system="You are a precise, citation-preserving RAG answerer.",
                                    user=generation_user,
                                    name="rag_answer",
                                    schema=ANSWER_SCHEMA,
                                    max_output_tokens=args.max_output_tokens,
                                )
                                answer = dict(runner.structured_response(response.payload))
                                generation_usage = response.usage.as_dict()
                            except Exception as exc:  # noqa: BLE001
                                errors.append(f"generation:{safe_error(exc)}")
                            timings["generation_provider"] = (
                                time.perf_counter() - generation_started
                            ) * 1000
                        if not errors:
                            reference = (
                                str(case.get("expected_answer") or "")
                                if bool(case["answerable"])
                                else (
                                    "(the benchmark labels this query unanswerable from "
                                    "the corpus)"
                                )
                            )
                            judge_user = (
                                "Score this RAG result from 0 to 1 for context relevance, "
                                "groundedness, answer relevance, correctness, citation entailment, "
                                "citation precision, and citation completeness. Apply each "
                                "criterion "
                                "independently and return only the requested JSON object.\n"
                                f"Question: {case['query']}\nReference: {reference}\n"
                                f"Context:\n{context_text}\nAnswer:\n"
                                f"{json.dumps(answer, ensure_ascii=False, sort_keys=True)}"
                            )
                            judge_started = time.perf_counter()
                            try:
                                response = await asyncio.to_thread(
                                    client.response,
                                    model=JUDGE_MODEL,
                                    system="You are a strict, reproducible RAG evaluator.",
                                    user=judge_user,
                                    name="rag_judge",
                                    schema=JUDGE_SCHEMA,
                                    max_output_tokens=args.max_output_tokens,
                                )
                                raw_judge = runner.structured_response(response.payload)
                                judge = {
                                    name: safe_score(raw_judge.get(name))
                                    for name in ANSWER_METRICS
                                }
                                judge_usage = response.usage.as_dict()
                            except Exception as exc:  # noqa: BLE001
                                errors.append(f"judge:{safe_error(exc)}")
                            timings["judge_provider"] = (
                                time.perf_counter() - judge_started
                            ) * 1000
                        relevant_pages = {
                            f"{item['book_id']}:{page}"
                            for item in case["relevant"]
                            for page in item["pages"]
                        }
                        metrics = citation_metrics(
                            answer,
                            valid_ids=set(context_ids),
                            relevant_pages=relevant_pages,
                        )
                        timings["total"] = (time.perf_counter() - total_started) * 1000
                        row = {
                            "schema_version": 1,
                            "condition_id": key,
                            "query_id": query_id,
                            "answerable": bool(case["answerable"]),
                            "retrieved_ids": [item["screen_id"] for item in chunks],
                            "ranking_match_screen": ranking_match,
                            "full_context_sha256": context_hash,
                            "sent_context_sha256": sent_context_hash,
                            "sent_context_chunk_ids": context_ids,
                            "answer_sha256": canonical_hash(answer),
                            "abstained": bool(answer.get("abstained", True)),
                            "judge": judge,
                            "citation": metrics,
                            "usage": {
                                "generation": generation_usage,
                                "judge": judge_usage,
                            },
                            "timings_ms": {
                                **{
                                    f"retrieval.{name}": round(value, 4)
                                    for name, value in retrieval_stages.items()
                                },
                                **{name: round(value, 4) for name, value in timings.items()},
                            },
                            "error_codes": errors,
                        }
                        condition_rows.append(row)
                        all_rows.append(row)
                        with (output / "per_query.jsonl").open("a", encoding="utf-8") as handle:
                            handle.write(json.dumps(row, sort_keys=True) + "\n")
                        provider_calls = [call.as_dict() for call in client.calls]
                        (output / "provider_calls.jsonl").write_text(
                            "".join(
                                json.dumps(call, sort_keys=True) + "\n"
                                for call in provider_calls
                            ),
                            encoding="utf-8",
                        )
                        actual_cost = Decimal(
                            str(_provider_cost(provider_calls)["actual_provider_cost_usd"])
                        )
                        if actual_cost > Decimal(str(args.budget_cap_usd)):
                            raise TriadContractError("provider budget cap exceeded")
                if len(condition_rows) != len(cases):
                    raise TriadContractError(f"{key}: incomplete Triad denominator")
        finally:
            await engine.dispose()
    provider_calls = [call.as_dict() for call in client.calls]
    summaries = {
        condition_id(*value): summarize(
            [row for row in all_rows if row["condition_id"] == condition_id(*value)]
        )
        for value in ranking_conditions()
    }
    if any(value["errors"] for value in summaries.values()):
        manifest["status"] = "failed_query_errors"
    else:
        manifest["status"] = "completed"
    manifest["summaries"] = summaries
    manifest["provider_calls"] = len(provider_calls)
    manifest["cost"] = {
        **_provider_cost(provider_calls),
        "hard_cap_usd": str(args.budget_cap_usd),
    }
    manifest["artifacts_sha256"] = {
        "per_query": sha256_file(output / "per_query.jsonl"),
        "provider_calls": sha256_file(output / "provider_calls.jsonl"),
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if manifest["status"] != "completed":
        raise TriadContractError("Triad run completed with query errors")


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--private-state", required=True, type=Path)
    value.add_argument("--private-queries", required=True, type=Path)
    value.add_argument("--sources", required=True, type=Path)
    value.add_argument("--screen", required=True, type=Path)
    value.add_argument("--output", required=True, type=Path)
    value.add_argument("--provider-runner", type=Path, default=DEFAULT_PROVIDER_RUNNER)
    value.add_argument("--litellm-url", default="http://127.0.0.1:54000")
    value.add_argument("--reranker-rpm", type=int, default=9)
    value.add_argument("--provider-retries", type=int, default=3)
    value.add_argument("--max-context-chars", type=int, default=30_000)
    value.add_argument("--max-output-tokens", type=int, default=800)
    value.add_argument("--budget-cap-usd", type=Decimal, default=Decimal("5.00"))
    return value


def main() -> None:
    args = parser().parse_args()
    if args.reranker_rpm < 1 or args.max_output_tokens < 100 or args.budget_cap_usd <= 0:
        raise SystemExit("invalid rate, output-token, or budget setting")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
