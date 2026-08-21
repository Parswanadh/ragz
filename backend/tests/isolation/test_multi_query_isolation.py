from sqlalchemy.ext.asyncio import AsyncSession

from ragz.modules.documents.service import set_document_acl
from ragz.modules.retrieval.query_expansion import ExpandedQueries
from ragz.modules.retrieval.service import retrieve
from tests.isolation.conftest import (
    ingest_text,
    seed_acl_workspace,
    seed_same_org_two_workspaces,
)
from tests.modules.retrieval.test_retrieve import seed_workspace, upsert_texts


class _CrossTenantMatchingExpander:
    def __init__(self, alternative: str = "rival organization secret phrase") -> None:
        self.alternative = alternative
        self.calls = 0

    async def expand(self, query: str, *, model: str) -> ExpandedQueries:
        self.calls += 1
        return ExpandedQueries((query, self.alternative))


async def test_multi_query_variants_cannot_cross_tenant_filter(
    session: AsyncSession,
    qdrant_collection: None,
    utility_model: object,
) -> None:
    caller_ctx, caller_ws = await seed_workspace(
        session, "mq-caller", multi_query_enabled=True
    )
    rival_ctx, rival_ws = await seed_workspace(session, "mq-rival")
    await upsert_texts(
        rival_ctx,
        rival_ws,
        ["rival organization secret phrase"],
    )

    expander = _CrossTenantMatchingExpander()
    result = await retrieve(
        session,
        caller_ctx,
        caller_ws.id,
        "unrelated words",
        query_expander=expander,
    )

    assert expander.calls == 1
    assert result.no_answer is True
    assert result.chunks == []


async def test_multi_query_variants_cannot_cross_sibling_workspace_filter(
    session: AsyncSession,
    qdrant_collection: None,
    utility_model: object,
) -> None:
    caller_ctx, caller_ws, sibling_ctx, sibling_ws = await seed_same_org_two_workspaces(
        session
    )
    caller_ws.multi_query_enabled = True
    await session.commit()
    await upsert_texts(
        sibling_ctx,
        sibling_ws,
        ["sibling workspace secret phrase"],
    )
    expander = _CrossTenantMatchingExpander("sibling workspace secret phrase")

    result = await retrieve(
        session,
        caller_ctx,
        caller_ws.id,
        "unrelated words",
        query_expander=expander,
    )

    assert expander.calls == 1
    assert result.no_answer is True
    assert result.chunks == []


async def test_multi_query_variants_preserve_group_acl_filter(
    session: AsyncSession,
    qdrant_collection: None,
    utility_model: object,
) -> None:
    restricted_text = "finance multi-query secret: merger price is 8123"
    open_text = "public multi-query notice: cafeteria opens at seven"
    ctx_in, ctx_out, ctx_admin, ws, finance = await seed_acl_workspace(session)
    ws.multi_query_enabled = True
    await session.commit()
    restricted = await ingest_text(
        session, ctx_admin, ws, "multi-query-restricted.txt", restricted_text
    )
    await set_document_acl(session, ctx_admin, restricted.id, [finance.id])
    open_doc = await ingest_text(
        session, ctx_admin, ws, "multi-query-open.txt", open_text
    )

    outsider_expander = _CrossTenantMatchingExpander(restricted_text)
    outsider = await retrieve(
        session,
        ctx_out,
        ws.id,
        open_text,
        top_k=10,
        query_expander=outsider_expander,
    )
    returned = {chunk.document_id for chunk in outsider.chunks}
    assert outsider_expander.calls == 1
    assert restricted.id not in returned
    assert open_doc.id in returned
    assert all("8123" not in chunk.text for chunk in outsider.chunks)

    insider = await retrieve(
        session,
        ctx_in,
        ws.id,
        "unrelated words",
        top_k=10,
        query_expander=_CrossTenantMatchingExpander(restricted_text),
    )
    assert restricted.id in {chunk.document_id for chunk in insider.chunks}
