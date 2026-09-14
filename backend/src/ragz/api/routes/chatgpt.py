"""Superadmin-managed, installation-wide ChatGPT subscription connection."""

from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ragz.api.deps import get_session
from ragz.core.config import Settings, get_settings
from ragz.core.ratelimit import rate_limit
from ragz.modules.models import chatgpt_oauth as service
from ragz.modules.models.chatgpt_schemas import ChatGPTLogin, ChatGPTPoll, ChatGPTStatus
from ragz.modules.tenancy.context import TenantContext, require_role

router = APIRouter(prefix="/admin/models/chatgpt", tags=["models"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
SuperadminDep = Annotated[TenantContext, Depends(require_role())]


def _transport(request: Request) -> httpx.AsyncBaseTransport | None:
    return getattr(request.app.state, "chatgpt_transport", None)


@router.get("", response_model=ChatGPTStatus)
async def status(session: SessionDep, settings: SettingsDep, ctx: SuperadminDep) -> ChatGPTStatus:
    return await service.connection_status(session, settings=settings)


@router.post(
    "/login",
    response_model=ChatGPTLogin,
    dependencies=[Depends(rate_limit("chatgpt-login", limit=10))],
)
async def login(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    ctx: SuperadminDep,
) -> ChatGPTLogin:
    return await service.start_login(
        session, settings=settings, actor_id=ctx.user_id, transport=_transport(request)
    )


@router.post(
    "/poll",
    response_model=ChatGPTLogin,
    dependencies=[Depends(rate_limit("chatgpt-poll", limit=60))],
)
async def poll(
    body: ChatGPTPoll,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    ctx: SuperadminDep,
) -> ChatGPTLogin:
    return await service.poll_login(
        session,
        settings=settings,
        actor_id=ctx.user_id,
        login_id=body.login_id,
        transport=_transport(request),
    )


@router.delete("/login", response_model=ChatGPTLogin)
async def cancel(session: SessionDep, settings: SettingsDep, ctx: SuperadminDep) -> ChatGPTLogin:
    return await service.cancel_login(session, settings=settings, actor_id=ctx.user_id)


@router.delete("", response_model=ChatGPTStatus)
async def disconnect(
    session: SessionDep, settings: SettingsDep, ctx: SuperadminDep
) -> ChatGPTStatus:
    return await service.disconnect(session, settings=settings, actor_id=ctx.user_id)
