from sqlalchemy.ext.asyncio import AsyncSession

from ragz.modules.retrieval.query_expansion import ExpandedQueries
from ragz.modules.retrieval.service import retrieve
from tests.modules.retrieval.test_retrieve import seed_workspace, upsert_texts


class _CrossTenantMatchingExpander:
    async def expand(self, query: str, *, model: str) -> ExpandedQueries:
        return ExpandedQueries((query, "rival organization secret phrase"))


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

    result = await retrieve(
        session,
        caller_ctx,
        caller_ws.id,
        "unrelated words",
        query_expander=_CrossTenantMatchingExpander(),
    )

    assert result.no_answer is True
    assert result.chunks == []
