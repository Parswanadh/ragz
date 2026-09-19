from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ragz.api.deps import get_session
from ragz.api.secret_route import SecretSafeRoute
from ragz.core.config import Settings, get_settings
from ragz.modules.chat import web_settings
from ragz.modules.chat.web_settings import (
    KeyedWebProviderId,
    WebConfig,
    WebConfigUpdate,
    WebKeyUpdate,
    WebProviderId,
    WebProviderTest,
)
from ragz.modules.tenancy.context import TenantContext, require_role

router = APIRouter(prefix="/admin/web-search", tags=["web-search"], route_class=SecretSafeRoute)
SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
SuperadminDep = Annotated[TenantContext, Depends(require_role())]


@router.get("", response_model=WebConfig)
async def get_config(session: SessionDep, settings: SettingsDep, ctx: SuperadminDep) -> WebConfig:
    return await web_settings.get_web_config(session, settings)


@router.patch("", response_model=WebConfig)
async def patch_config(
    body: WebConfigUpdate,
    session: SessionDep,
    settings: SettingsDep,
    ctx: SuperadminDep,
) -> WebConfig:
    return await web_settings.update_web_config(session, settings, actor_id=ctx.user_id, patch=body)


@router.put("/keys/{provider}", response_model=WebConfig)
async def put_key(
    provider: KeyedWebProviderId,
    body: WebKeyUpdate,
    session: SessionDep,
    settings: SettingsDep,
    ctx: SuperadminDep,
) -> WebConfig:
    return await web_settings.set_web_key(
        session,
        settings,
        actor_id=ctx.user_id,
        provider=provider,
        api_key=body.api_key,
    )


@router.delete("/keys/{provider}", response_model=WebConfig)
async def delete_key(
    provider: KeyedWebProviderId,
    session: SessionDep,
    settings: SettingsDep,
    ctx: SuperadminDep,
) -> WebConfig:
    return await web_settings.delete_web_key(
        session, settings, actor_id=ctx.user_id, provider=provider
    )


@router.post("/test/{provider}", response_model=WebProviderTest)
async def test_provider(
    provider: WebProviderId,
    session: SessionDep,
    settings: SettingsDep,
    ctx: SuperadminDep,
) -> WebProviderTest:
    return await web_settings.test_web_provider(session, settings, provider=provider)
