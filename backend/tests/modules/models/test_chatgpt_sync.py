import json

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ragz.core.config import Settings
from ragz.modules.models.models import Model
from ragz.modules.models.sync import sync_models_to_litellm


async def test_chatgpt_is_removed_from_gateway_and_never_redeployed(
    session: AsyncSession,
    test_settings: Settings,
) -> None:
    model = Model(
        litellm_model_name="chatgpt/gpt-5.5", display_name="ChatGPT", provider_kind="litellm"
    )
    session.add(model)
    await session.commit()
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/model/info":
            return httpx.Response(200, json={"data": [{"model_info": {"id": "old-chatgpt"}}]})
        return httpx.Response(200, json={})

    assert (
        await sync_models_to_litellm(
            session,
            test_settings,
            transport=httpx.MockTransport(handler),
        )
        == 0
    )
    assert [(r.method, r.url.path) for r in requests] == [
        ("GET", "/v1/model/info"),
        ("POST", "/model/delete"),
    ]
    assert json.loads(requests[1].content) == {"id": "old-chatgpt"}
    await session.refresh(model)
    assert model.sync_status == "synced"
