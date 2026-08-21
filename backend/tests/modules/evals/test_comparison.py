from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragz.core.config import get_settings
from ragz.modules.auth.models import User
from ragz.modules.chat.llm import LLMCompletion, LLMUsage
from ragz.modules.evals.comparison import compare_answers
from ragz.modules.quotas.models import UsageRecord
from ragz.modules.retrieval.service import RetrievalResult, RetrievedChunk
from ragz.modules.tenancy.context import TenantContext
from ragz.modules.tenancy.models import Workspace
from ragz.modules.tenancy.views import WorkspaceView


class _ComparisonRetriever:
    def __init__(self, document_id: UUID) -> None:
        self.document_id = document_id
        self.overrides: list[bool | None] = []

    async def __call__(  # type: ignore[no-untyped-def]
        self,
        session,
        ctx,
        workspace_id,
        query,
        top_k=None,
        metadata_clauses=None,
        *,
        multi_query_enabled_override=None,
    ):
        self.overrides.append(multi_query_enabled_override)
        mode = "multi" if multi_query_enabled_override else "single"
        return RetrievalResult(
            chunks=[
                RetrievedChunk(
                    document_id=self.document_id,
                    page=7,
                    chunk_index=2,
                    text=f"{mode} evidence says the receive window must cover the path.",
                    score=0.9,
                )
            ],
            no_answer=False,
            query_count=3 if multi_query_enabled_override else 1,
        )


class _ComparisonCompleter:
    def __init__(self) -> None:
        self.calls: list[list[dict[str, object]]] = []

    async def complete(  # type: ignore[no-untyped-def]
        self, *, model, messages, tools=None, reasoning_effort=None
    ):
        self.calls.append(messages)
        number = len(self.calls)
        return LLMCompletion(
            text=f"Answer {number} is grounded [1].",
            tool_calls=[],
            usage=LLMUsage(prompt_tokens=10 * number, completion_tokens=number),
        )


async def test_compare_answers_is_ordered_transient_and_accounted(
    session: AsyncSession,
    seeded_user: User,
    chat_env: dict[str, object],
) -> None:
    workspace = chat_env["workspace"]
    document = chat_env["document"]
    assert isinstance(workspace, Workspace)
    document_id = document.id  # type: ignore[union-attr]
    ctx = TenantContext(
        user_id=seeded_user.id,
        org_id=seeded_user.org_id,
        role="admin",
        workspace_ids=frozenset({workspace.id}),
    )
    retriever = _ComparisonRetriever(document_id)
    completer = _ComparisonCompleter()
    original_toggle = workspace.multi_query_enabled

    variants = await compare_answers(
        session,
        ctx,
        WorkspaceView.of(workspace),
        question="Why does a long-delay path need a larger TCP window?",
        model_id=UUID("00000000-0000-4000-8000-000000000001"),
        model_name="comparison-model",
        completer=completer,
        retriever=retriever,
        token_budget=get_settings().chat_context_token_budget,
    )

    await session.refresh(workspace)
    assert workspace.multi_query_enabled is original_toggle
    assert retriever.overrides == [False, True]
    assert [variant.mode for variant in variants] == ["single", "multi"]
    assert [variant.query_count for variant in variants] == [1, 3]
    assert [variant.answer for variant in variants] == [
        "Answer 1 is grounded [1].",
        "Answer 2 is grounded [1].",
    ]
    assert all(variant.citation_markers == [1] for variant in variants)
    assert all(variant.sources[0].filename == "report.pdf" for variant in variants)
    assert all(variant.total_ms >= variant.retrieval_ms for variant in variants)
    assert len(completer.calls) == 2
    usage = list(
        (
            await session.execute(
                select(UsageRecord).where(
                    UsageRecord.org_id == seeded_user.org_id,
                    UsageRecord.feature == "chat",
                )
            )
        ).scalars()
    )
    assert [(row.prompt_tokens, row.completion_tokens) for row in usage] == [
        (10, 1),
        (20, 2),
    ]


async def test_compare_answers_declines_without_calling_generator(
    session: AsyncSession,
    seeded_user: User,
    chat_env: dict[str, object],
) -> None:
    workspace = chat_env["workspace"]
    document = chat_env["document"]
    assert isinstance(workspace, Workspace)
    ctx = TenantContext(
        user_id=seeded_user.id,
        org_id=seeded_user.org_id,
        role="admin",
        workspace_ids=frozenset({workspace.id}),
    )
    completer = _ComparisonCompleter()

    class _NoAnswerRetriever(_ComparisonRetriever):
        async def __call__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            result = await super().__call__(*args, **kwargs)
            return RetrievalResult(
                chunks=result.chunks,
                no_answer=True,
                query_count=result.query_count,
            )

    variants = await compare_answers(
        session,
        ctx,
        WorkspaceView.of(workspace),
        question="Off-corpus question",
        model_id=UUID("00000000-0000-4000-8000-000000000001"),
        model_name="comparison-model",
        completer=completer,
        retriever=_NoAnswerRetriever(document.id),  # type: ignore[union-attr]
        token_budget=get_settings().chat_context_token_budget,
    )

    assert completer.calls == []
    assert all(variant.no_answer for variant in variants)
    assert all("did not provide enough evidence" in variant.answer for variant in variants)
    assert all(variant.generation_ms == 0 for variant in variants)
