"""Native Responses behavior, including planner tool calls and credential dispatch."""

import json

import httpx
import pytest

from ragz.core.errors import UpstreamError
from ragz.modules.chat.llm import LiteLLMStreamer, LLMDelta, LLMUsage


def sse(*events: dict[str, object]) -> str:
    return "\n\n".join("data: " + json.dumps(event) for event in events) + "\n\n"


async def credentials():
    from ragz.modules.models.chatgpt_schemas import ChatGPTCredentials

    return ChatGPTCredentials("private-access-token", "account-one", 2_000_000_000)


async def test_dispatch_stream_uses_chatgpt_credentials_and_responses_payload() -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            text=sse(
                {"type": "response.output_text.delta", "delta": "Hello"},
                {
                    "type": "response.completed",
                    "response": {
                        "usage": {"input_tokens": 20, "output_tokens": 3},
                        "output": [],
                    },
                },
            ),
        )

    client = LiteLLMStreamer(
        base_url="http://gateway",
        master_key="gateway-secret",
        transport=httpx.MockTransport(handler),
        chatgpt_credentials=credentials,
    )
    events = [
        event
        async for event in client.stream(
            model="chatgpt/gpt-5.5",
            reasoning_effort="high",
            messages=[
                {"role": "system", "content": "Follow the grounding rules"},
                {"role": "user", "content": "Hi"},
            ],
        )
    ]
    assert events == [LLMDelta("Hello"), LLMUsage(20, 3)]
    request = seen[0]
    assert str(request.url) == "https://chatgpt.com/backend-api/codex/responses"
    assert request.headers["Authorization"] == "Bearer private-access-token"
    assert request.headers["chatgpt-account-id"] == "account-one"
    assert "gateway-secret" not in str(request.headers)
    payload = json.loads(request.content)
    assert payload["model"] == "gpt-5.5" and payload["stream"] and not payload["store"]
    assert payload["instructions"] == "Follow the grounding rules"
    assert payload["input"] == [{"role": "user", "content": [{"type": "input_text", "text": "Hi"}]}]
    assert payload["reasoning"] == {"effort": "high"}
    assert "max_tokens" not in payload


async def test_complete_aggregates_streamed_tool_arguments_and_final_usage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["stream"] is True
        assert body["tools"] == [
            {"type": "function", "name": "search", "parameters": {"type": "object"}}
        ]
        return httpx.Response(
            200,
            text=sse(
                {
                    "type": "response.output_item.added",
                    "output_index": 1,
                    "item": {
                        "type": "function_call",
                        "id": "fc_one",
                        "call_id": "call-one",
                        "name": "search",
                        "arguments": "",
                    },
                },
                {
                    "type": "response.function_call_arguments.delta",
                    "output_index": 1,
                    "item_id": "fc_one",
                    "delta": '{"query":',
                },
                {
                    "type": "response.function_call_arguments.delta",
                    "output_index": 1,
                    "item_id": "fc_one",
                    "delta": '"records"}',
                },
                {
                    "type": "response.output_item.done",
                    "output_index": 1,
                    "item": {
                        "type": "function_call",
                        "id": "fc_one",
                        "call_id": "call-one",
                        "name": "search",
                        "arguments": '{"query":"records"}',
                    },
                },
                {
                    "type": "response.completed",
                    "response": {
                        "usage": {"input_tokens": 30, "output_tokens": 7},
                        "output": [],
                    },
                },
            ),
        )

    client = LiteLLMStreamer(
        base_url="http://gateway", master_key="gateway-secret",
        chatgpt_credentials=credentials, transport=httpx.MockTransport(handler),
    )
    result = await client.complete(
        model="chatgpt/gpt-5.5",
        messages=[],
        tools=[
            {"type": "function", "function": {"name": "search", "parameters": {"type": "object"}}},
        ],
    )
    assert result.text == ""
    assert [(tool.name, tool.arguments) for tool in result.tool_calls] == [
        ("search", '{"query":"records"}'),
    ]
    assert result.usage == LLMUsage(30, 7)


@pytest.mark.parametrize(
    "status, body",
    [
        (401, "private-provider-token"),
        (200, 'data: {"type":"error","message":"private-provider-token"}\n\n'),
        (200, 'data: {"type":"response.output_text.delta","delta":"partial"}\n\n'),
        (200, "data: {broken json}\n\n"),
    ],
)
async def test_stream_rejects_errors_and_truncation_without_provider_details(
    status: int,
    body: str,
) -> None:
    from ragz.modules.chat.chatgpt import ChatGPTClient

    client = ChatGPTClient(
        credentials=credentials,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(status, text=body),
        ),
    )
    with pytest.raises(UpstreamError) as error:
        await client.complete(model="chatgpt/gpt-5.5", messages=[])
    assert "private-provider-token" not in str(error.value)


async def test_tool_results_images_and_assistant_history_translate_to_responses() -> None:
    from ragz.modules.chat.chatgpt import ChatGPTClient

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            text=sse(
                {"type": "response.completed", "response": {"output": [], "usage": {}}},
            ),
        )

    client = ChatGPTClient(credentials=credentials, transport=httpx.MockTransport(handler))
    await client.complete(
        model="chatgpt/gpt-5.5",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Explain"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,eA=="}},
                ],
            },
            {
                "role": "assistant",
                "content": "Looking",
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "search", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "Found"},
        ],
        reasoning_effort="off",
    )
    assert seen[0]["input"] == [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "Explain"},
                {"type": "input_image", "image_url": "data:image/png;base64,eA=="},
            ],
        },
        {"role": "assistant", "content": [{"type": "output_text", "text": "Looking"}]},
        {"type": "function_call", "call_id": "c1", "name": "search", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "c1", "output": "Found"},
    ]
    assert "reasoning" not in seen[0]
