"""Async ChatGPT Responses transport using installation credentials in memory.

Both consumer protocols use SSE. Planner completions collect that stream so
function-call arguments remain intact even if the terminal event omits output.
"""

import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any, Protocol
from uuid import uuid4

import httpx

from ragz.core.config import get_settings
from ragz.core.errors import UpstreamError
from ragz.modules.chat.llm import LLMCompletion, LLMDelta, LLMToolCall, LLMUsage

_RESPONSES_URL = "https://chatgpt.com/backend-api/codex/responses"


class Credentials(Protocol):
    @property
    def access_token(self) -> str: ...

    @property
    def account_id(self) -> str: ...


CredentialLoader = Callable[[], Awaitable[Credentials]]


async def _load_credentials() -> Credentials:
    from ragz.modules.models.service import get_chatgpt_credentials

    return await get_chatgpt_credentials(settings=get_settings())


def _content(raw: object, *, assistant: bool = False) -> list[dict[str, Any]]:
    if isinstance(raw, str):
        return [{"type": "output_text" if assistant else "input_text", "text": raw}]
    parts: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for part in raw:
            if not isinstance(part, dict):
                continue
            if part.get("type") in ("text", "input_text", "output_text"):
                parts.append(
                    {
                        "type": "output_text" if assistant else "input_text",
                        "text": str(part.get("text", "")),
                    }
                )
            elif part.get("type") == "image_url":
                value = part.get("image_url")
                url = value.get("url") if isinstance(value, dict) else value
                if isinstance(url, str):
                    image: dict[str, Any] = {"type": "input_image", "image_url": url}
                    if isinstance(value, dict) and value.get("detail"):
                        image["detail"] = value["detail"]
                    parts.append(image)
    return parts


def _payload(
    model: str,
    messages: list[dict[str, object]],
    tools: list[dict[str, object]] | None,
    reasoning_effort: str | None,
) -> dict[str, Any]:
    instructions: list[str] = []
    items: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role", "user")
        raw = message.get("content")
        if role in ("system", "developer"):
            instructions.extend(str(part["text"]) for part in _content(raw) if "text" in part)
        elif role == "tool":
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": message.get("tool_call_id"),
                    "output": raw if isinstance(raw, str) else json.dumps(raw),
                }
            )
        else:
            content = _content(raw, assistant=role == "assistant")
            if content:
                items.append({"role": role, "content": content})
            calls = message.get("tool_calls")
            if isinstance(calls, list):
                for call in calls:
                    if isinstance(call, dict) and isinstance(call.get("function"), dict):
                        function = call["function"]
                        items.append(
                            {
                                "type": "function_call",
                                "call_id": call.get("id"),
                                "name": function.get("name"),
                                "arguments": function.get("arguments", "{}"),
                            }
                        )
    payload: dict[str, Any] = {
        "model": model.removeprefix("chatgpt/"),
        "input": items,
        "instructions": "\n\n".join(instructions),
        "stream": True,
        "store": False,
    }
    if tools:
        payload["tools"] = [
            {"type": "function", **function}
            for tool in tools
            if isinstance(function := tool.get("function"), dict)
        ]
    if reasoning_effort and reasoning_effort != "off":
        payload["reasoning"] = {"effort": reasoning_effort}
    return payload


async def _sse(response: httpx.Response) -> AsyncGenerator[dict[str, Any], None]:
    lines: list[str] = []
    async for line in response.aiter_lines():
        if line.startswith("data:"):
            lines.append(line[5:].lstrip())
        elif not line and lines:
            data = "\n".join(lines)
            lines.clear()
            if data == "[DONE]":
                return
            try:
                event = json.loads(data)
                if not isinstance(event, dict):
                    raise ValueError
            except ValueError:
                raise UpstreamError("ChatGPT returned an invalid stream event") from None
            yield event
    if lines:
        raise UpstreamError("ChatGPT response ended before an event completed")


class ChatGPTClient:
    def __init__(
        self,
        *,
        credentials: CredentialLoader | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        limits: httpx.Limits | None = None,
    ) -> None:
        self._credentials = credentials or _load_credentials
        self._transport = transport
        self._limits = limits or httpx.Limits()

    async def _events(
        self,
        *,
        model: str,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None = None,
        reasoning_effort: str | None = None,
    ) -> AsyncGenerator[LLMDelta | LLMUsage | LLMToolCall, None]:
        credential = await self._credentials()
        headers = {
            "Authorization": f"Bearer {credential.access_token}",
            "chatgpt-account-id": credential.account_id,
            "Accept": "text/event-stream",
            "originator": "codex_cli_rs",
            "User-Agent": "ragz/0.1.0",
            "session_id": str(uuid4()),
        }
        payload = _payload(model, messages, tools, reasoning_effort)
        calls: dict[int, dict[str, Any]] = {}
        texts: dict[tuple[int, int], str] = {}

        def recover_text(index: int, content_index: int, full: str) -> str:
            key = (index, content_index)
            previous = texts.get(key, "")
            texts[key] = full
            return full[len(previous) :] if full.startswith(previous) else ""

        def recover_item(index: int, item: dict[str, Any]) -> list[LLMDelta]:
            deltas = []
            if item.get("type") == "function_call":
                calls[index] = {**calls.get(index, {}), **item}
            elif item.get("type") == "message":
                for content_index, content in enumerate(item.get("content") or []):
                    if content.get("type") == "output_text":
                        delta = recover_text(index, content_index, str(content.get("text", "")))
                        if delta:
                            deltas.append(LLMDelta(delta))
            return deltas

        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=httpx.Timeout(120.0, connect=10.0),
                limits=self._limits,
            ) as client:
                async with client.stream(
                    "POST", _RESPONSES_URL, json=payload, headers=headers
                ) as response:
                    if response.status_code != 200:
                        raise UpstreamError(
                            f"ChatGPT request failed (HTTP {response.status_code}); "
                            "check connection and model availability"
                        )
                    async for event in _sse(response):
                        kind = event.get("type")
                        index = int(event.get("output_index", 0))
                        content_index = int(event.get("content_index", 0))
                        if kind == "response.output_text.delta":
                            delta = str(event.get("delta", ""))
                            key = (index, content_index)
                            texts[key] = texts.get(key, "") + delta
                            if delta:
                                yield LLMDelta(delta)
                        elif kind == "response.output_text.done":
                            delta = recover_text(index, content_index, str(event.get("text", "")))
                            if delta:
                                yield LLMDelta(delta)
                        elif kind == "response.output_item.added":
                            item = event.get("item") or {}
                            if item.get("type") == "function_call":
                                calls[index] = item
                        elif kind == "response.function_call_arguments.delta":
                            call = calls.setdefault(index, {})
                            call["arguments"] = call.get("arguments", "") + str(
                                event.get("delta", "")
                            )
                        elif kind == "response.function_call_arguments.done":
                            calls.setdefault(index, {})["arguments"] = event.get("arguments", "{}")
                        elif kind == "response.output_item.done":
                            for delta_event in recover_item(index, event.get("item") or {}):
                                yield delta_event
                        elif kind == "response.completed":
                            completed = event.get("response") or {}
                            for output_index, item in enumerate(completed.get("output") or []):
                                for delta_event in recover_item(output_index, item):
                                    yield delta_event
                            for call in (calls[i] for i in sorted(calls)):
                                if not call.get("name"):
                                    raise UpstreamError("ChatGPT returned an incomplete tool call")
                                yield LLMToolCall(
                                    name=str(call["name"]),
                                    arguments=str(call.get("arguments") or "{}"),
                                )
                            usage = completed.get("usage") or {}
                            yield LLMUsage(
                                prompt_tokens=int(usage.get("input_tokens", 0)),
                                completion_tokens=int(usage.get("output_tokens", 0)),
                            )
                            return
                        elif kind in ("error", "response.failed", "response.incomplete"):
                            raise UpstreamError("ChatGPT could not complete the response")
        except httpx.HTTPError:
            raise UpstreamError("ChatGPT service is unreachable") from None
        except (ValueError, TypeError, AttributeError, KeyError):
            raise UpstreamError("ChatGPT returned an invalid stream event") from None
        raise UpstreamError("ChatGPT response ended before completion")

    async def stream(
        self,
        *,
        model: str,
        messages: list[dict[str, object]],
        reasoning_effort: str | None = None,
    ) -> AsyncGenerator[LLMDelta | LLMUsage, None]:
        events = self._events(model=model, messages=messages, reasoning_effort=reasoning_effort)
        try:
            async for event in events:
                if isinstance(event, (LLMDelta, LLMUsage)):
                    yield event
        finally:
            await events.aclose()

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None = None,
        reasoning_effort: str | None = None,
    ) -> LLMCompletion:
        parts, calls = [], []
        usage = LLMUsage(0, 0)
        async for event in self._events(
            model=model, messages=messages, tools=tools, reasoning_effort=reasoning_effort
        ):
            if isinstance(event, LLMDelta):
                parts.append(event.text)
            elif isinstance(event, LLMToolCall):
                calls.append(event)
            else:
                usage = event
        return LLMCompletion(text="".join(parts), tool_calls=calls, usage=usage)
