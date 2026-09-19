import json
from typing import Any

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from ragz.api.app import create_app
from ragz.core.config import Settings, get_settings
from ragz.core.db import build_session_factory
from ragz.modules.chat import web
from ragz.modules.chat.llm import LLMCompletion, LLMUsage
from ragz.modules.quotas.models import UsageRecord
from tests.api.test_chat_agent_stream import _flag_tools_unreliable
from tests.api.test_chat_stream import _disable_generative_ui, auth, make_model_and_chat, parse_sse
from tests.conftest import (
    FakeChunkReader,
    FakeCompleter,
    FakeRetriever,
    FakeStreamer,
    FakeWebSearcher,
    _stub_litellm_handler,
)


async def test_selected_research_stream_uses_configured_caps_and_records_paid_usage(
    engine: AsyncEngine,
    redis_client: Redis,
    test_settings: Settings,
    chat_env: dict[str, Any],
    seeded_user: Any,
    seeded_superadmin: Any,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def provider(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == "openai/gpt-5.6-sol"
        assert "secret-value" not in payload["input"]
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "search_results",
                        "results": [
                            {"id": 1, "title": "Guidance", "url": "https://example.org/guidance"},
                        ],
                    },
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "Regular inspections are recommended [1].",
                            },
                        ],
                    },
                ]
            },
        )

    class _ResearcherWithFakeHTTP(web.PerplexityResearcher):
        def __init__(self, **kwargs: Any) -> None:
            kwargs["transport"] = httpx.MockTransport(provider)
            super().__init__(**kwargs)

    monkeypatch.setattr(web, "PerplexityResearcher", _ResearcherWithFakeHTTP)
    streamer = FakeStreamer(["Perplexity reports regular inspections [1]."])
    link_searcher = FakeWebSearcher()
    completer = FakeCompleter(
        [
            LLMCompletion(
                text='{"action":"web_search","query":"inspections"}',
                tool_calls=[],
                usage=LLMUsage(prompt_tokens=1, completion_tokens=1),
            )
        ]
    )
    app = create_app(
        session_factory=build_session_factory(engine),
        redis_client=redis_client,
        litellm_transport=httpx.MockTransport(_stub_litellm_handler),
        retriever=FakeRetriever(chat_env["document"].id),
        llm_streamer=streamer,
        chunk_reader=FakeChunkReader(),
        llm_completer=completer,
        web_searcher=link_searcher,
    )
    app.dependency_overrides[get_settings] = lambda: test_settings
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        user = await auth(client, seeded_user.email)
        chat_id = await make_model_and_chat(client, chat_env, session, seeded_superadmin, user)
        admin = await auth(client, seeded_superadmin.email)
        await _flag_tools_unreliable(client, admin)
        await _disable_generative_ui(client, admin)
        enabled = await client.patch(
            f"/api/v1/workspaces/{chat_env['workspace'].id}",
            json={"web_search_enabled": True},
            headers=user,
        )
        assert enabled.status_code == 200
        key = await client.put(
            "/api/v1/admin/web-search/keys/perplexity",
            headers=admin,
            json={"api_key": "pplx-test-key"},
        )
        assert key.status_code == 200
        config = await client.patch(
            "/api/v1/admin/web-search",
            headers=admin,
            json={
                "provider": "perplexity",
                "perplexity_model": "openai/gpt-5.6-sol",
                "max_calls_per_turn": 1,
                "daily_cap": 1,
            },
        )
        assert config.status_code == 200
        response = await client.post(
            f"/api/v1/chats/{chat_id}/messages",
            headers=user,
            json={
                "content": "What inspections are recommended? api_key=secret-value",
                "web_search_consented": True,
            },
        )
    frames = parse_sse(response.text)
    first = next(data for name, data in frames if name == "agent_step")
    assert first["tool"] == "web_research"
    tool_result = next(data for name, data in frames if name == "tool_result")
    assert tool_result["tool"] == "web_research"
    assert "third-party synthesis" in tool_result["results"][0]["snippet"]
    assert any(item["url"] == "https://example.org/guidance" for item in tool_result["results"])
    assert link_searcher.queries == []
    rows = (
        (
            await session.execute(
                select(UsageRecord).where(
                    UsageRecord.org_id == seeded_user.org_id,
                    UsageRecord.feature == "web_search",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1 and rows[0].units == 1
