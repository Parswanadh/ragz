#!/usr/bin/env python3
"""Seed a persistent, isolated networking comparison workspace.

The caller supplies explicit PDF paths, an admin password and the answer-model
credential via process environment. The script never reads dotenv files and
never prints either secret. It expects an already-migrated database and uses
the configured storage/Qdrant services.
"""

from __future__ import annotations

import argparse
import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from qdrant_client import models as qdrant_models
from sqlalchemy import select, true
from sqlalchemy.engine import make_url

from ragz.core.config import get_settings
from ragz.core.db import build_engine, build_session_factory
from ragz.core.storage import build_storage
from ragz.modules.auth.models import User
from ragz.modules.auth.passwords import hash_password
from ragz.modules.documents.models import Document
from ragz.modules.documents.parsers import LiteParseParser
from ragz.modules.documents.pipeline import chunk_document, embed_batch, upsert_points
from ragz.modules.models.models import Model
from ragz.modules.retrieval.client import get_qdrant
from ragz.modules.retrieval.embeddings import get_dense_embedder
from ragz.modules.retrieval.service import ensure_collection
from ragz.modules.secrets import service as secrets_service
from ragz.modules.tenancy.models import Organization, Workspace, WorkspaceMember

WORKSPACE_NAME = "Networking Multi-Query Lab"
ORG_NAME = "RAGZ Comparison Lab"
DEFAULT_CHAT_MODEL = "gpt-5.6-luna"


def parse_pdf(value: str) -> tuple[str, Path]:
    book_id, separator, raw_path = value.partition("=")
    path = Path(raw_path).expanduser().resolve()
    if not separator or not book_id or not path.is_file():
        raise argparse.ArgumentTypeError("PDF must be BOOK_ID=/absolute/existing/path.pdf")
    return book_id, path


def validate_lab_target(
    *, database_url: str, environment: str, confirmed_database: str | None
) -> str:
    database_name = make_url(database_url).database
    if environment not in {"dev", "test"}:
        raise RuntimeError("comparison lab seeding is restricted to dev/test")
    if (
        not database_name
        or confirmed_database != database_name
        or not database_name.startswith("ragz_mq_lab")
    ):
        raise RuntimeError(
            "set RAGZ_LAB_DATABASE_NAME to the dedicated ragz_mq_lab* database name"
        )
    return database_name


async def seed(args: argparse.Namespace) -> None:
    password = os.environ.get("RAGZ_LAB_ADMIN_PASSWORD")
    if not password or len(password) < 12:
        raise RuntimeError("RAGZ_LAB_ADMIN_PASSWORD must contain at least 12 characters")
    chat_api_key = os.environ.get("RAGZ_LAB_CHAT_API_KEY")
    if not chat_api_key:
        raise RuntimeError("RAGZ_LAB_CHAT_API_KEY must be non-empty")
    settings = get_settings()
    validate_lab_target(
        database_url=settings.database_url,
        environment=settings.environment,
        confirmed_database=os.environ.get("RAGZ_LAB_DATABASE_NAME"),
    )
    if settings.embedding_backend != "hash":
        raise RuntimeError("comparison lab seeding requires RAGZ_EMBEDDING_BACKEND=hash")
    requested_hashes = {
        book_id: hashlib.sha256(path.read_bytes()).hexdigest()
        for book_id, path in args.pdf
    }
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    storage = build_storage(settings)
    await storage.ensure_bucket()
    try:
        async with factory() as session:
            other_workspace = (
                await session.execute(
                    select(Workspace.id)
                    .where(Workspace.name != WORKSPACE_NAME)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if other_workspace is not None:
                raise RuntimeError("confirmed lab database contains a non-lab workspace")
            existing = (
                await session.execute(
                    select(Workspace).where(Workspace.name == WORKSPACE_NAME)
                )
            ).scalar_one_or_none()
            already_seeded = False
            documents: list[Document] = []
            if existing is not None:
                documents = list(
                    (
                        await session.execute(
                            select(Document).where(Document.workspace_id == existing.id)
                        )
                    ).scalars()
                )
                already_seeded = len(documents) == 3 and all(
                    document.status == "indexed"
                    and document.vectors_present
                    and document.index_state == "active"
                    and document.projected_security_revision == document.security_revision
                    for document in documents
                )
                existing_hashes = {document.content_hash for document in documents}
                if existing_hashes - set(requested_hashes.values()):
                    raise RuntimeError(
                        "comparison workspace contains a document outside the requested corpus"
                    )
                if already_seeded and existing_hashes != set(requested_hashes.values()):
                    raise RuntimeError("indexed comparison corpus hashes do not match the request")
                if documents and not already_seeded:
                    raise RuntimeError(
                        "comparison workspace is partially seeded; preserve it for inspection "
                        "and create a fresh dedicated ragz_mq_lab* database to retry"
                    )
                workspace = existing
                organization = await session.get(Organization, workspace.org_id)
                admin = (
                    await session.execute(
                        select(User).where(
                            User.org_id == workspace.org_id,
                            User.email == args.admin_email,
                        )
                    )
                ).scalar_one_or_none()
                embedding_model = await session.get(Model, workspace.embedding_model_id)
                chat_model = (
                    await session.get(Model, workspace.default_model_id)
                    if workspace.default_model_id is not None
                    else None
                )
                if any(item is None for item in (organization, admin, embedding_model, chat_model)):
                    raise RuntimeError("comparison workspace bootstrap rows are incomplete")
            else:
                organization = Organization(name=ORG_NAME)
                session.add(organization)
                await session.flush()
                admin = User(
                    org_id=organization.id,
                    email=args.admin_email,
                    password_hash=hash_password(password),
                    role="superadmin",
                )
                session.add(admin)
                await session.flush()

                embedding_model_id = uuid4()
                embedding_model = Model(
                    id=embedding_model_id,
                    litellm_model_name=f"networking-lab-hash-{embedding_model_id.hex}",
                    display_name="Hash embeddings — comparison lab",
                    provider_kind="tei",
                    modality="embedding",
                    dimension=settings.embedding_dim,
                    collection_name=f"chunks_networking_lab_{embedding_model_id.hex}",
                    enabled=True,
                    sync_status="synced",
                )
                session.add(embedding_model)
                await session.flush()
                chat_model = (
                    await session.execute(
                        select(Model).where(Model.litellm_model_name == args.chat_model)
                    )
                ).scalar_one_or_none()
                if chat_model is None:
                    chat_model = Model(
                        litellm_model_name=args.chat_model,
                        display_name=args.chat_model,
                        provider_kind="openai",
                        modality="chat",
                        enabled=True,
                        is_utility=True,
                        sync_status="synced",
                    )
                    session.add(chat_model)
                    await session.flush()
                other_utility = (
                    await session.execute(
                        select(Model.id).where(
                            Model.is_utility == true(), Model.id != chat_model.id
                        )
                    )
                ).scalar_one_or_none()
                if other_utility is not None:
                    raise RuntimeError(
                        "lab database already has a different utility model; "
                        "select it explicitly with --chat-model"
                    )
                chat_model.is_utility = True
                workspace = Workspace(
                    org_id=organization.id,
                    name=WORKSPACE_NAME,
                    embedding_model_id=embedding_model.id,
                    default_model_id=chat_model.id,
                    top_k=5,
                    min_score=0.0,
                    rerank_enabled=False,
                    multi_query_enabled=False,
                    chunk_method="heading",
                )
                session.add(workspace)
                await session.flush()
                session.add(WorkspaceMember(workspace_id=workspace.id, user_id=admin.id))
                await session.flush()

            assert organization is not None
            assert admin is not None
            assert embedding_model is not None
            assert chat_model is not None
            if (
                not chat_model.enabled
                or chat_model.modality != "chat"
                or chat_model.litellm_model_name != args.chat_model
            ):
                raise RuntimeError("answer model must be the requested enabled chat model")
            utility_ids = set(
                (
                    await session.execute(select(Model.id).where(Model.is_utility == true()))
                ).scalars()
            )
            if utility_ids != {chat_model.id}:
                raise RuntimeError("answer model must be the lab's sole utility model")
            if (
                not embedding_model.enabled
                or embedding_model.modality != "embedding"
                or embedding_model.dimension != settings.embedding_dim
                or not embedding_model.collection_name
                or not embedding_model.collection_name.startswith("chunks_networking_lab_")
            ):
                raise RuntimeError(
                    "embedding model must be the enabled hash-dimension lab collection model"
                )
            await secrets_service.set_secret(
                session,
                actor_id=admin.id,
                name=f"model:{chat_model.id}",
                value=chat_api_key,
                settings=settings,
                commit=False,
            )
            await session.commit()

        collection_name = embedding_model.collection_name
        assert collection_name is not None
        await ensure_collection(collection_name, settings.embedding_dim)
        if already_seeded:
            client = get_qdrant()
            for document in documents:
                stored = await storage.get(document.storage_key)
                if hashlib.sha256(stored).hexdigest() != document.content_hash:
                    raise RuntimeError(
                        f"stored object hash mismatch for document {document.id}; "
                        "create a fresh dedicated lab database"
                    )
                source_path = next(
                    path
                    for book_id, path in args.pdf
                    if requested_hashes[book_id] == document.content_hash
                )
                source_data = source_path.read_bytes()
                blocks = await LiteParseParser().parse(source_data, source_path.name)
                expected_chunks = len(chunk_document(blocks, method="heading"))
                if document.page_count != max((block.page for block in blocks), default=0):
                    raise RuntimeError(
                        f"page count mismatch for document {document.id}; "
                        "create a fresh dedicated lab database"
                    )
                point_count = await client.count(
                    collection_name,
                    count_filter=qdrant_models.Filter(
                        must=[
                            qdrant_models.FieldCondition(
                                key="tenant_id",
                                match=qdrant_models.MatchValue(value=str(document.org_id)),
                            ),
                            qdrant_models.FieldCondition(
                                key="workspace_id",
                                match=qdrant_models.MatchValue(value=str(document.workspace_id)),
                            ),
                            qdrant_models.FieldCondition(
                                key="document_id",
                                match=qdrant_models.MatchValue(value=str(document.id)),
                            ),
                        ]
                    ),
                    exact=True,
                )
                if point_count.count != expected_chunks:
                    raise RuntimeError(
                        f"vector count mismatch for document {document.id}: "
                        f"expected {expected_chunks}, found {point_count.count}; "
                        "create a fresh dedicated lab database"
                    )
            print(
                f"workspace_id={workspace.id} documents=3 "
                "credential_refreshed=true storage_vectors_verified=true "
                "status=already_seeded"
            )
            return
        dense_embedder = get_dense_embedder(
            embedding_model.id,
            provider_kind=embedding_model.provider_kind,
            litellm_model_name=embedding_model.litellm_model_name,
        )
        total_chunks = 0
        for book_id, path in args.pdf:
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            document_id = uuid4()
            storage_key = f"comparison/{workspace.id}/{document_id}/{path.name}"
            await storage.put(storage_key, data, "application/pdf")
            blocks = await LiteParseParser().parse(data, path.name)
            chunks = chunk_document(blocks, method="heading")
            created_at = datetime.now(UTC).replace(tzinfo=None)
            async with factory() as session:
                session.add(
                    Document(
                        id=document_id,
                        org_id=organization.id,
                        workspace_id=workspace.id,
                        filename=path.name,
                        mime="application/pdf",
                        size_bytes=len(data),
                        content_hash=digest,
                        meta={
                            "book_id": book_id,
                            "expected_chunk_count": str(len(chunks)),
                        },
                        status="processing",
                        storage_key=storage_key,
                        page_count=max((block.page for block in blocks), default=0),
                        created_by=admin.id,
                        lineage_id=document_id,
                        is_current=True,
                        approved=True,
                        vectors_present=False,
                        index_state="pending",
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
                    org_id=organization.id,
                    workspace_id=workspace.id,
                    document_id=document_id,
                    mime="application/pdf",
                    created_at=created_at,
                    acl_group_ids=[],
                    chunks=batch,
                    dense=dense,
                    sparse=sparse,
                    version=1,
                    meta={"book_id": book_id},
                    collection_name=collection_name,
                    is_current=True,
                )
            async with factory() as session:
                indexed_document = await session.get(Document, document_id)
                assert indexed_document is not None
                indexed_document.status = "indexed"
                indexed_document.vectors_present = True
                indexed_document.index_state = "active"
                await session.commit()
            total_chunks += len(chunks)
            print(
                f"book_id={book_id} pages={max((block.page for block in blocks), default=0)} "
                f"chunks={len(chunks)} status=indexed"
            )
        print(
            f"workspace_id={workspace.id} documents={len(args.pdf)} "
            f"chunks={total_chunks} admin_email={args.admin_email} status=ready"
        )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", action="append", required=True, type=parse_pdf)
    parser.add_argument("--admin-email", default="compare@ragz.example")
    parser.add_argument("--chat-model", default=DEFAULT_CHAT_MODEL)
    args = parser.parse_args()
    if len(args.pdf) != 3 or len({book_id for book_id, _ in args.pdf}) != 3:
        raise ValueError("exactly three uniquely named PDFs are required")
    import asyncio

    asyncio.run(seed(args))


if __name__ == "__main__":
    main()
