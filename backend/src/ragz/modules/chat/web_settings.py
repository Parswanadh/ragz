"""Installation-wide web configuration, encrypted keys, and explicit provider tests."""

import time
from typing import Annotated, Literal, cast
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from ragz.core.app_settings import get_app_setting, set_app_setting
from ragz.core.config import Settings
from ragz.core.errors import BadRequestError, NotFoundError, UpstreamError
from ragz.modules.audit.service import record_audit
from ragz.modules.chat.web import (
    DEFAULT_PERPLEXITY_MODEL,
    DuckDuckGoSearcher,
    PerplexityResearcher,
    TavilySearcher,
)
from ragz.modules.secrets import service as secrets_service

WebProviderId = Literal["duckduckgo", "tavily", "perplexity"]
KeyedWebProviderId = Literal["tavily", "perplexity"]
_ModelName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
_TurnCap = Annotated[int, Field(strict=True, ge=1, le=50)]
_DailyCap = Annotated[int, Field(strict=True, ge=1, le=10000)]


class WebProvider(BaseModel):
    id: WebProviderId
    name: str
    result_kind: Literal["links", "answer"]
    needs_key: bool
    key_set: bool
    key_fingerprint: str | None
    ready: bool


class WebConfig(BaseModel):
    provider: WebProviderId
    perplexity_model: str
    max_calls_per_turn: int
    daily_cap: int
    full_content: bool
    providers: list[WebProvider]


class WebConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: WebProviderId | None = None
    perplexity_model: _ModelName | None = None
    max_calls_per_turn: _TurnCap | None = None
    daily_cap: _DailyCap | None = None
    full_content: bool | None = None


class WebKeyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: SecretStr = Field(min_length=1, max_length=8192)


class WebProviderTest(BaseModel):
    ok: bool
    detail: str
    latency_ms: int
    result_count: int


async def get_web_limits(session: AsyncSession, settings: Settings) -> tuple[int, int]:
    turn = await get_app_setting(session, "web_search_max_calls_per_turn")
    daily = await get_app_setting(session, "web_search_daily_cap")
    return int(turn) if turn is not None else 3, (
        int(daily) if daily is not None else settings.web_search_daily_limit_per_user
    )


async def get_web_config(session: AsyncSession, settings: Settings) -> WebConfig:
    stored_provider = await get_app_setting(session, "web_search_provider")
    provider: WebProviderId = (
        cast(WebProviderId, stored_provider)
        if stored_provider in ("duckduckgo", "tavily", "perplexity")
        else "duckduckgo"
    )
    model = await get_app_setting(session, "web_search_perplexity_model")
    full_content = await get_app_setting(session, "web_search_full_content")
    turn, daily = await get_web_limits(session, settings)
    fingerprints = {
        row.name: row.fingerprint
        for row in await secrets_service.list_secrets(session)
        if row.name in ("tavily", "perplexity")
    }
    providers = [
        WebProvider(
            id="duckduckgo",
            name="DuckDuckGo",
            result_kind="links",
            needs_key=False,
            key_set=False,
            key_fingerprint=None,
            ready=True,
        )
    ]
    keyed_providers: tuple[tuple[KeyedWebProviderId, str, Literal["links", "answer"]], ...] = (
        ("tavily", "Tavily", "links"),
        ("perplexity", "Perplexity", "answer"),
    )
    for key, name, kind in keyed_providers:
        providers.append(
            WebProvider(
                id=key,
                name=name,
                result_kind=kind,
                needs_key=True,
                key_set=key in fingerprints,
                key_fingerprint=fingerprints.get(key),
                ready=key in fingerprints,
            )
        )
    return WebConfig(
        provider=provider,
        perplexity_model=model or DEFAULT_PERPLEXITY_MODEL,
        max_calls_per_turn=turn,
        daily_cap=daily,
        full_content=full_content is None
        or full_content.strip().lower() not in ("false", "0", "off"),
        providers=providers,
    )


async def update_web_config(
    session: AsyncSession,
    settings: Settings,
    *,
    actor_id: UUID,
    patch: WebConfigUpdate,
) -> WebConfig:
    mapping = {
        "provider": "web_search_provider",
        "perplexity_model": "web_search_perplexity_model",
        "max_calls_per_turn": "web_search_max_calls_per_turn",
        "daily_cap": "web_search_daily_cap",
        "full_content": "web_search_full_content",
    }
    for field, value in patch.model_dump(exclude_none=True).items():
        rendered = str(value).lower() if isinstance(value, bool) else str(value)
        await set_app_setting(session, mapping[field], rendered, commit=False)
    await record_audit(
        session,
        org_id=None,
        actor_id=actor_id,
        action="web_search.config.updated",
        target_type="app_settings",
        target_id="web_search",
    )
    await session.commit()
    return await get_web_config(session, settings)


async def set_web_key(
    session: AsyncSession,
    settings: Settings,
    *,
    actor_id: UUID,
    provider: KeyedWebProviderId,
    api_key: SecretStr,
) -> WebConfig:
    value = api_key.get_secret_value().strip()
    if not value:
        raise BadRequestError("API key must not be blank")
    await secrets_service.set_secret(
        session,
        actor_id=actor_id,
        name=provider,
        value=value,
        settings=settings,
    )
    return await get_web_config(session, settings)


async def delete_web_key(
    session: AsyncSession,
    settings: Settings,
    *,
    actor_id: UUID,
    provider: KeyedWebProviderId,
) -> WebConfig:
    try:
        await secrets_service.delete_secret(session, actor_id=actor_id, name=provider)
    except NotFoundError:
        pass
    return await get_web_config(session, settings)


async def test_web_provider(
    session: AsyncSession,
    settings: Settings,
    *,
    provider: WebProviderId,
    transport: httpx.AsyncBaseTransport | None = None,
) -> WebProviderTest:
    """Operator initiated, fixed public query; no chat text is sent by a test."""
    started = time.monotonic()
    config = await get_web_config(session, settings)
    entry = next(p for p in config.providers if p.id == provider)
    if not entry.ready:
        return WebProviderTest(
            ok=False,
            detail="Store a provider API key before testing.",
            latency_ms=0,
            result_count=0,
        )
    query = "What is the official Python programming language website?"
    count = 0
    try:
        if provider == "perplexity":
            research = await PerplexityResearcher(
                settings=settings,
                model=config.perplexity_model,
                transport=transport,
            )(session, query)
            count = len(research.citations)
            ok = bool(research.answer)
        elif provider == "tavily":
            results = await TavilySearcher(settings=settings, transport=transport)(session, query)
            count, ok = len(results), bool(results)
        else:
            results = await DuckDuckGoSearcher(full_content=False, transport=transport)(
                session, query
            )
            count, ok = len(results), bool(results)
        detail = "Provider returned a response." if ok else "Provider returned no results."
    except (UpstreamError, NotFoundError) as exc:
        ok, detail = False, str(exc)
    return WebProviderTest(
        ok=ok,
        detail=detail,
        latency_ms=int((time.monotonic() - started) * 1000),
        result_count=count,
    )
