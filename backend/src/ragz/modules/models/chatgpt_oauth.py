"""Installation-wide ChatGPT device OAuth, custodied only in encrypted Postgres.

The SDK supplies constants only. Its Authenticator is never constructed, so it
cannot read, create or refresh a plaintext token file. One transaction advisory
lock serializes every credential transition across API and worker processes.
"""

import asyncio
import base64
import json
import math
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ragz.core.config import Settings
from ragz.core.errors import ConflictError, NotFoundError, UpstreamError
from ragz.modules.models.chatgpt_schemas import ChatGPTCredentials, ChatGPTLogin, ChatGPTStatus
from ragz.modules.models.sdk import load_sdk
from ragz.modules.secrets import service as secrets_service

_CREDENTIAL = "oauth:chatgpt"
_LOGIN = "oauth:chatgpt:login"
_LOCK = 0x5241475A43475054
_HTTP_TIMEOUT = 15.0


@dataclass(frozen=True)
class _Endpoints:
    client_id: str
    device_code: str
    device_token: str
    oauth_token: str
    verify: str
    auth_base: str
    timeout: int
    interval: int


@lru_cache(maxsize=1)
def _endpoints() -> _Endpoints:
    # Importing LiteLLM initializes its catalog; always called via to_thread.
    load_sdk()
    from litellm.llms.chatgpt.authenticator import (
        DEVICE_CODE_POLL_SLEEP_SECONDS,
        DEVICE_CODE_TIMEOUT_SECONDS,
    )
    from litellm.llms.chatgpt.common_utils import (
        CHATGPT_AUTH_BASE,
        CHATGPT_CLIENT_ID,
        CHATGPT_DEVICE_CODE_URL,
        CHATGPT_DEVICE_TOKEN_URL,
        CHATGPT_DEVICE_VERIFY_URL,
        CHATGPT_OAUTH_TOKEN_URL,
    )

    return _Endpoints(
        CHATGPT_CLIENT_ID,
        CHATGPT_DEVICE_CODE_URL,
        CHATGPT_DEVICE_TOKEN_URL,
        CHATGPT_OAUTH_TOKEN_URL,
        CHATGPT_DEVICE_VERIFY_URL,
        CHATGPT_AUTH_BASE,
        int(DEVICE_CODE_TIMEOUT_SECONDS),
        int(DEVICE_CODE_POLL_SLEEP_SECONDS),
    )


async def _get_endpoints() -> _Endpoints:
    try:
        return await asyncio.to_thread(_endpoints)
    except (ImportError, AttributeError):
        raise UpstreamError(
            "ChatGPT authentication is unavailable in this LiteLLM install"
        ) from None


@asynccontextmanager
async def _locked(session: AsyncSession) -> AsyncIterator[None]:
    try:
        async with asyncio.timeout(20):
            await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _LOCK})
        yield
        await session.commit()
    except BaseException:
        await session.rollback()
        raise


async def _read(session: AsyncSession, settings: Settings, name: str) -> dict[str, Any]:
    try:
        raw = await secrets_service._get_secret_decrypted(  # noqa: SLF001
            session,
            name=name,
            settings=settings,
            commit=False,
        )
    except NotFoundError:
        return {}
    try:
        record = json.loads(raw)
        if isinstance(record, dict):
            return record
    except ValueError:
        pass
    raise UpstreamError("Stored ChatGPT connection is invalid; disconnect and reconnect")


async def _write(
    session: AsyncSession,
    settings: Settings,
    name: str,
    record: dict[str, Any],
    actor_id: UUID | None,
) -> None:
    await secrets_service.set_secret(
        session,
        name=name,
        value=json.dumps(record),
        settings=settings,
        actor_id=actor_id,
        commit=False,
    )


async def _delete(session: AsyncSession, name: str, actor_id: UUID | None) -> None:
    try:
        await secrets_service.delete_secret(session, name=name, actor_id=actor_id, commit=False)
    except NotFoundError:
        pass


def _public(record: dict[str, Any], now: float) -> ChatGPTLogin:
    result = ChatGPTLogin.model_validate(record)
    if result.state == "pending" and (result.expires_at or 0) <= now:
        result.state = "expired"
    if result.state != "pending":
        result.user_code = None
        result.verification_url = None
    return result


async def connection_status(
    session: AsyncSession,
    *,
    settings: Settings,
    now: float | None = None,
) -> ChatGPTStatus:
    now = time.time() if now is None else now
    try:
        await _get_endpoints()
        available = True
    except UpstreamError:
        available = False
    async with _locked(session):
        credential = await _read(session, settings, _CREDENTIAL)
        login = _public(await _read(session, settings, _LOGIN), now)
        return ChatGPTStatus(
            available=available,
            connected=bool(
                credential.get("refresh_token")
                or (credential.get("access_token") and credential.get("expires_at", 0) > now)
            ),
            account_id=credential.get("account_id"),
            email=credential.get("email"),
            plan_type=credential.get("plan_type"),
            expires_at=credential.get("expires_at"),
            login=login,
        )


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        value = response.json()
        if isinstance(value, dict):
            return value
    except ValueError:
        pass
    raise UpstreamError("ChatGPT returned an invalid authentication response")


async def _post(
    url: str,
    *,
    transport: httpx.AsyncBaseTransport | None,
    data: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
) -> httpx.Response:
    try:
        async with asyncio.timeout(_HTTP_TIMEOUT):
            async with httpx.AsyncClient(transport=transport, timeout=_HTTP_TIMEOUT) as client:
                return await client.post(url, data=data, json=payload)
    except (httpx.HTTPError, TimeoutError):
        raise UpstreamError("ChatGPT authentication service is unreachable") from None


async def start_login(
    session: AsyncSession,
    *,
    settings: Settings,
    actor_id: UUID | None,
    transport: httpx.AsyncBaseTransport | None = None,
    now: float | None = None,
) -> ChatGPTLogin:
    endpoints = await _get_endpoints()
    now = time.time() if now is None else now
    async with _locked(session):
        previous = _public(await _read(session, settings, _LOGIN), now)
        if previous.state == "pending":
            return previous
        response = await _post(
            endpoints.device_code, transport=transport, payload={"client_id": endpoints.client_id}
        )
        if response.status_code != 200:
            raise UpstreamError("ChatGPT refused the sign-in request")
        body = _json(response)
        device = body.get("device_auth_id")
        code = body.get("user_code") or body.get("usercode")
        if not isinstance(device, str) or not device or not isinstance(code, str) or not code:
            raise UpstreamError("ChatGPT returned an incomplete device code")
        requested_interval = body.get("interval", endpoints.interval)
        try:
            interval = max(endpoints.interval, int(requested_interval))
        except (ValueError, TypeError, OverflowError):
            raise UpstreamError("ChatGPT returned an invalid polling interval") from None
        login = ChatGPTLogin(
            login_id=str(uuid4()),
            state="pending",
            verification_url=endpoints.verify,
            user_code=code,
            expires_at=now + endpoints.timeout,
            interval=interval,
        )
        await _write(
            session,
            settings,
            _LOGIN,
            {
                **login.model_dump(),
                "device_auth_id": device,
                "next_poll_at": now + interval,
            },
            actor_id,
        )
        return login


def _claims(raw: object) -> dict[str, Any]:
    # Claims describe the account to the operator; never used to authenticate
    # Ragz users. Tokens arrive exclusively from the fixed HTTPS OAuth endpoint.
    if not isinstance(raw, str):
        return {}
    try:
        part = raw.split(".")[1]
        value = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        return value if isinstance(value, dict) else {}
    except (ValueError, IndexError):
        return {}


def _credentials(
    body: dict[str, Any],
    now: float,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    previous = previous or {}
    access = body.get("access_token")
    refresh = body.get("refresh_token") or previous.get("refresh_token")
    identity = body.get("id_token") or previous.get("id_token")
    access_claims, id_claims = _claims(access), _claims(identity)
    account_claims = access_claims.get("https://api.openai.com/auth") or {}
    id_account = id_claims.get("https://api.openai.com/auth") or {}
    if not isinstance(account_claims, dict) or not isinstance(id_account, dict):
        raise UpstreamError("ChatGPT returned invalid account credentials")
    account = account_claims.get("chatgpt_account_id") or id_account.get("chatgpt_account_id")
    if (
        not isinstance(access, str)
        or not access
        or not isinstance(refresh, str)
        or not isinstance(account, str)
        or not account
    ):
        raise UpstreamError("ChatGPT returned incomplete account credentials")
    try:
        expires_at = float(access_claims.get("exp") or (now + float(body.get("expires_in", 3600))))
    except (TypeError, ValueError):
        raise UpstreamError("ChatGPT returned invalid token expiry") from None
    if not math.isfinite(expires_at) or expires_at <= now:
        raise UpstreamError("ChatGPT returned an expired token")
    return {
        "access_token": access,
        "refresh_token": refresh,
        "id_token": identity,
        "expires_at": expires_at,
        "account_id": str(account),
        "email": id_claims.get("email") or access_claims.get("email") or previous.get("email"),
        "plan_type": account_claims.get("chatgpt_plan_type")
        or id_account.get("chatgpt_plan_type")
        or previous.get("plan_type"),
    }


async def poll_login(
    session: AsyncSession,
    *,
    settings: Settings,
    actor_id: UUID | None,
    login_id: str,
    transport: httpx.AsyncBaseTransport | None = None,
    now: float | None = None,
) -> ChatGPTLogin:
    endpoints = await _get_endpoints()
    clock_now = time.time() if now is None else now
    async with _locked(session):
        record = await _read(session, settings, _LOGIN)
        if record.get("login_id") != login_id:
            raise ConflictError("This ChatGPT sign-in has been replaced; reload its status")
        login = _public(record, clock_now)
        if login.state != "pending":
            await _write(session, settings, _LOGIN, login.model_dump(), actor_id)
            return login
        if record.get("next_poll_at", 0) > clock_now:
            return login
        try:
            grant = record.get("grant")
            if grant:
                response = await _post(
                    endpoints.oauth_token,
                    transport=transport,
                    data={
                        "grant_type": "authorization_code",
                        "code": grant["authorization_code"],
                        "redirect_uri": f"{endpoints.auth_base}/deviceauth/callback",
                        "client_id": endpoints.client_id,
                        "code_verifier": grant["code_verifier"],
                    },
                )
            else:
                response = await _post(
                    endpoints.device_token,
                    transport=transport,
                    payload={
                        "device_auth_id": record["device_auth_id"],
                        "user_code": record["user_code"],
                    },
                )
            finished_at = time.time() if now is None else now
            if finished_at >= (login.expires_at or 0):
                login.state = "expired"
            elif not grant and response.status_code in (403, 404, 429):
                if response.status_code == 429:
                    login.interval += 5
                record["next_poll_at"] = finished_at + login.interval
            elif response.status_code != 200:
                raise UpstreamError("ChatGPT sign-in failed; start a new sign-in")
            elif grant:
                credential = _credentials(_json(response), finished_at)
                credential["login_id"] = login_id
                await _write(session, settings, _CREDENTIAL, credential, actor_id)
                login.state = "authorised"
            else:
                body = _json(response)
                if not all(
                    isinstance(body.get(k), str) and body[k]
                    for k in ("authorization_code", "code_verifier")
                ):
                    raise UpstreamError("ChatGPT returned an incomplete authorization code")
                record["grant"] = {k: body[k] for k in ("authorization_code", "code_verifier")}
                record["next_poll_at"] = finished_at
        except UpstreamError as exc:
            login.state = "failed"
            login.error = exc.detail
        if login.state != "pending":
            login.user_code = None
            login.verification_url = None
            record = {}
        await _write(session, settings, _LOGIN, {**record, **login.model_dump()}, actor_id)
        return login


async def cancel_login(
    session: AsyncSession,
    *,
    settings: Settings,
    actor_id: UUID | None,
) -> ChatGPTLogin:
    async with _locked(session):
        record = await _read(session, settings, _LOGIN)
        login = _public(record, time.time())
        credential = await _read(session, settings, _CREDENTIAL)
        # A cancellation queued behind the final exchange must also cancel the
        # credentials just published by that same flow, without erasing an older login.
        if login.login_id and credential.get("login_id") == login.login_id:
            await _delete(session, _CREDENTIAL, actor_id)
        login.state = "cancelled"
        login.user_code = login.verification_url = login.error = None
        await _write(session, settings, _LOGIN, login.model_dump(), actor_id)
        return login


async def disconnect(
    session: AsyncSession,
    *,
    settings: Settings,
    actor_id: UUID | None,
) -> ChatGPTStatus:
    async with _locked(session):
        login = _public(await _read(session, settings, _LOGIN), time.time())
        login.state = "cancelled"
        login.user_code = login.verification_url = login.error = None
        await _delete(session, _CREDENTIAL, actor_id)
        await _write(session, settings, _LOGIN, login.model_dump(), actor_id)
        return ChatGPTStatus(login=login)


async def get_runtime_credentials(
    session: AsyncSession,
    *,
    settings: Settings,
    transport: httpx.AsyncBaseTransport | None = None,
    now: float | None = None,
) -> ChatGPTCredentials:
    endpoints = await _get_endpoints()
    now = time.time() if now is None else now
    async with _locked(session):
        record = await _read(session, settings, _CREDENTIAL)
        if not record.get("access_token"):
            raise UpstreamError("Connect ChatGPT in model settings before using this model")
        if record.get("expires_at", 0) <= now + 60:
            response = await _post(
                endpoints.oauth_token,
                transport=transport,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": record["refresh_token"],
                    "client_id": endpoints.client_id,
                },
            )
            if response.status_code != 200:
                raise UpstreamError("ChatGPT token refresh failed; reconnect in model settings")
            refreshed = _credentials(_json(response), now, record)
            record = {**record, **refreshed}
            await _write(session, settings, _CREDENTIAL, record, None)
        return ChatGPTCredentials(
            access_token=record["access_token"],
            account_id=record["account_id"],
            expires_at=record["expires_at"],
        )
