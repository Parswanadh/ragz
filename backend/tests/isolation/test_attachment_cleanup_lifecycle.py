from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragz.modules.auth.models import User
from ragz.modules.chat.chats import delete_chat
from ragz.modules.chat.cleanup import legacy_orphan_candidates, process_cleanup_job
from ragz.modules.chat.models import AttachmentCleanupJob, Chat, ChatAttachment
from ragz.modules.tenancy.context import TenantContext
from ragz.modules.tenancy.models import Organization, Workspace


async def _attachment_fixture(
    session: AsyncSession,
) -> tuple[TenantContext, Chat, ChatAttachment]:
    org = Organization(name="Cleanup lifecycle")
    session.add(org)
    await session.flush()
    user = User(
        org_id=org.id,
        email="cleanup-lifecycle@example.com",
        password_hash="x",  # noqa: S106
        role="admin",
    )
    workspace = Workspace(org_id=org.id, name="Cleanup")
    session.add_all([user, workspace])
    await session.flush()
    chat = Chat(org_id=org.id, workspace_id=workspace.id, user_id=user.id)
    session.add(chat)
    await session.flush()
    attachment = ChatAttachment(
        chat_id=chat.id,
        kind="document",
        filename="evidence.txt",
        mime="text/plain",
        storage_key=f"{org.id}/chats/{chat.id}/evidence.txt",
        size_bytes=8,
        status="ready",
        routed_to="retrieval",
    )
    session.add(attachment)
    await session.commit()
    return (
        TenantContext(
            user_id=user.id,
            org_id=org.id,
            role="admin",
            workspace_ids=frozenset(),
        ),
        chat,
        attachment,
    )


async def test_chat_delete_persists_external_identifiers_before_attachment_cascade(
    session: AsyncSession,
) -> None:
    ctx, chat, attachment = await _attachment_fixture(session)
    attachment_id = attachment.id
    storage_key = attachment.storage_key
    chat_id = chat.id

    await delete_chat(session, ctx, chat_id)

    session.expire_all()
    assert await session.get(ChatAttachment, attachment_id) is None
    job = (
        await session.execute(
            select(AttachmentCleanupJob).where(
                AttachmentCleanupJob.attachment_id == attachment_id
            )
        )
    ).scalar_one()
    assert job.chat_id == chat_id
    assert job.storage_key == storage_key
    assert job.completed_at is None
    assert job.attempts == 0


async def test_cleanup_retries_store_failure_and_completes_idempotently(
    session: AsyncSession,
) -> None:
    ctx, chat, attachment = await _attachment_fixture(session)
    await delete_chat(session, ctx, chat.id)
    job = (
        await session.execute(
            select(AttachmentCleanupJob).where(
                AttachmentCleanupJob.attachment_id == attachment.id
            )
        )
    ).scalar_one()
    calls: list[tuple[str, str]] = []

    async def fail_blob(storage_key: str) -> None:
        calls.append(("blob", storage_key))
        raise RuntimeError("synthetic isolated store failure")

    async def delete_vectors(chat_id, attachment_id) -> None:  # type: ignore[no-untyped-def]
        calls.append(("vectors", str(attachment_id)))

    assert not await process_cleanup_job(
        session, job, delete_blob=fail_blob, delete_vectors=delete_vectors
    )
    await session.refresh(job)
    assert job.attempts == 1
    assert job.last_error == "RuntimeError"
    assert job.completed_at is None
    assert [kind for kind, _ in calls] == ["blob"]

    async def delete_blob(storage_key: str) -> None:
        calls.append(("blob", storage_key))

    assert await process_cleanup_job(
        session, job, delete_blob=delete_blob, delete_vectors=delete_vectors
    )
    await session.refresh(job)
    assert job.completed_at is not None
    assert [kind for kind, _ in calls] == ["blob", "blob", "vectors"]

    assert await process_cleanup_job(
        session, job, delete_blob=delete_blob, delete_vectors=delete_vectors
    )
    assert [kind for kind, _ in calls] == ["blob", "blob", "vectors"]


def test_legacy_orphan_discovery_is_read_only_set_reconciliation() -> None:
    referenced = {uuid4()}
    already_queued = {uuid4()}
    orphaned = {uuid4(), uuid4()}

    result = legacy_orphan_candidates(
        database_attachment_ids=referenced,
        cleanup_job_attachment_ids=already_queued,
        object_attachment_ids=referenced | already_queued | orphaned,
        vector_attachment_ids=referenced | orphaned,
    )

    assert result.object_attachment_ids == orphaned
    assert result.vector_attachment_ids == orphaned
