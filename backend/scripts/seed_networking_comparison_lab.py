#!/usr/bin/env python3
"""Seed a persistent, isolated networking comparison workspace.

The caller supplies explicit PDF paths and an admin password via
RAGZ_LAB_ADMIN_PASSWORD. The script never reads dotenv files and never prints
the password or provider credentials. It expects an already-migrated database
and uses the configured storage/Qdrant services.
"""

from __future__ import annotations

import argparse
import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from ragz.core.config import get_settings
from ragz.core.db import build_engine, build_session_factory
from ragz.core.storage import build_storage
from ragz.modules.auth.models import User
from ragz.modules.auth.passwords import hash_password
from ragz.modules.documents.models import Document
from ragz.modules.documents.parsers import LiteParseParser
from ragz.modules.documents.pipeline import chunk_document, embed_batch, upsert_points
from ragz.modules.models.models import LOCAL_EMBEDDING_MODEL_ID, Model
from ragz.modules.retrieval.embeddings import get_dense_embedder
from ragz.modules.retrieval.service import ensure_collection
from ragz.modules.tenancy.models import Organization, Workspace, WorkspaceMember

WORKSPACE_NAME = "Networking Multi-Query Lab"
ORG_NAME = "RAGZ Comparison Lab"


def parse_pdf(value: str) -> tuple[str, Path]:
    book_id, separator, raw_path = value.partition("=")
    path = Path(raw_path).expanduser().resolve()
    if not separator or not book_id or not path.is_file():
        raise argparse.ArgumentTypeError("PDF must be BOOK_ID=/absolute/existing/path.pdf")
    return book_id, path


async def seed(args: argparse.Namespace) -> None:
    password = os.environ.get("RAGZ_LAB_ADMIN_PASSWORD")
    if not password or len(password) < 12:
        raise RuntimeError("RAGZ_LAB_ADMIN_PASSWORD must contain at least 12 characters")
    settings = get_settings()
    if settings.embedding_backend != "hash":
        raise RuntimeError("comparison lab seeding requires RAGZ_EMBEDDING_BACKEND=hash")
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    storage = build_storage(settings)
    await storage.ensure_bucket()
    try:
        async with factory() as session:
            existing = (
                await session.execute(
                    select(Workspace).where(Workspace.name == WORKSPACE_NAME)
                )
            ).scalar_one_or_none()
            if existing is not None:
                documents = list(
                    (
                        await session.execute(
                            select(Document).where(Document.workspace_id == existing.id)
                        )
                    ).scalars()
                )
                print(
                    f"workspace_id={existing.id} documents={len(documents)} "
                    "status=already_seeded"
                )
                return

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

            embedding_model = await session.get(Model, LOCAL_EMBEDDING_MODEL_ID)
            if embedding_model is None:
                raise RuntimeError("seeded local embedding model is missing; run migrations first")
            embedding_model.display_name = "Hash embeddings — comparison lab"
            embedding_model.provider_kind = "tei"
            embedding_model.modality = "embedding"
            embedding_model.dimension = settings.embedding_dim
            embedding_model.collection_name = f"chunks_networking_lab_{uuid4().hex}"
            embedding_model.enabled = True
            embedding_model.sync_status = "synced"

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
            await session.commit()

        collection_name = embedding_model.collection_name
        assert collection_name is not None
        await ensure_collection(collection_name, settings.embedding_dim)
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
                        status="processing",
                        storage_key=storage_key,
                        page_count=max((block.page for block in blocks), default=0),
                        created_by=admin.id,
                        lineage_id=document_id,
                        is_current=True,
                        approved=True,
                        vectors_present=False,
                        index_state="building",
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
                document = await session.get(Document, document_id)
                assert document is not None
                document.status = "indexed"
                document.vectors_present = True
                document.index_state = "active"
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
    parser.add_argument("--chat-model", default="gpt-5.4-mini")
    args = parser.parse_args()
    if len(args.pdf) != 3 or len({book_id for book_id, _ in args.pdf}) != 3:
        raise ValueError("exactly three uniquely named PDFs are required")
    import asyncio

    asyncio.run(seed(args))


if __name__ == "__main__":
    main()
