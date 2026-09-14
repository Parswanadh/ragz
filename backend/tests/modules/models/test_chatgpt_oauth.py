"""ChatGPT credentials use a real isolated database; only provider HTTP is faked."""

import asyncio
import base64
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from ragz.core.config import Settings
from ragz.core.db import build_session_factory
from ragz.core.errors import ConflictError, UpstreamError
from ragz.modules.secrets.crypto import ensure_kek
from ragz.modules.secrets.models import Secret


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    path = tmp_path / "kek"
    ensure_kek(str(path))
    return Settings(_env_file=None, kek_file=str(path))


def token(expires_at: int = 2_000_000_000) -> str:
    claims = {
        "exp": expires_at,
        "email": "operator@example.com",
        "https://api.openai.com/auth": {
            "chatgpt_account_id": "account-one",
            "chatgpt_plan_type": "plus",
        },
    }
    encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{encoded}.signature"


class OAuthProvider:
    def __init__(self) -> None:
        self.paths: list[str] = []
        self.pending = False
        self.now = 1_900_000_000.0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(request.url.path)
        if request.url.path.endswith("usercode"):
            return httpx.Response(
                200,
                json={
                    "device_auth_id": "private-device-id",
                    "user_code": "TEST-CODE",
                    "interval": 5,
                },
            )
        if request.url.path.endswith("deviceauth/token"):
            if self.pending:
                return httpx.Response(403, json={"error": "authorization_pending"})
            return httpx.Response(
                200,
                json={
                    "authorization_code": "private-grant",
                    "code_verifier": "private-verifier",
                    "code_challenge": "challenge",
                },
            )
        return httpx.Response(
            200,
            json={
                "access_token": token(),
                "refresh_token": "private-refresh",
                "id_token": token(),
                "expires_in": 3600,
            },
        )

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


async def connected(session: AsyncSession, settings: Settings, provider: OAuthProvider):
    from ragz.modules.models import chatgpt_oauth as oauth

    login = await oauth.start_login(
        session, settings=settings, actor_id=None, transport=provider.transport, now=provider.now
    )
    for _ in range(2):
        login = await oauth.poll_login(
            session,
            settings=settings,
            actor_id=None,
            login_id=login.login_id,
            transport=provider.transport,
            now=provider.now + 10,
        )
    assert login.state == "authorised"
    return login


async def test_login_is_encrypted_and_each_poll_makes_one_request(
    session: AsyncSession,
    settings: Settings,
) -> None:
    from ragz.modules.models import chatgpt_oauth as oauth

    provider = OAuthProvider()
    login = await connected(session, settings, provider)
    assert len(provider.paths) == 3
    status = await oauth.connection_status(session, settings=settings, now=provider.now)
    assert status.connected and status.account_id == "account-one"
    assert status.email == "operator@example.com" and status.plan_type == "plus"
    encoded = status.model_dump_json()
    for private in ("private-device-id", "private-grant", "private-refresh", token()):
        assert private not in encoded
    rows = (await session.execute(select(Secret))).scalars().all()
    assert rows
    assert all(b"private-refresh" not in row.ciphertext for row in rows)
    assert login.user_code is None


async def test_poll_throttles_expires_and_rejects_replaced_flow(
    session: AsyncSession,
    settings: Settings,
) -> None:
    from ragz.modules.models import chatgpt_oauth as oauth

    provider = OAuthProvider()
    provider.pending = True
    login = await oauth.start_login(
        session, settings=settings, actor_id=None, transport=provider.transport, now=provider.now
    )
    for _ in range(2):
        result = await oauth.poll_login(
            session,
            settings=settings,
            actor_id=None,
            login_id=login.login_id,
            transport=provider.transport,
            now=provider.now + 5,
        )
        assert result.state == "pending"
    assert len(provider.paths) == 2
    expired = await oauth.poll_login(
        session,
        settings=settings,
        actor_id=None,
        login_id=login.login_id,
        transport=provider.transport,
        now=provider.now + 1000,
    )
    assert expired.state == "expired" and expired.user_code is None
    assert len(provider.paths) == 2
    with pytest.raises(ConflictError):
        await oauth.poll_login(
            session,
            settings=settings,
            actor_id=None,
            login_id=str(uuid4()),
            transport=provider.transport,
        )


async def test_disconnect_cancels_grant_before_exchange(
    session: AsyncSession,
    settings: Settings,
) -> None:
    from ragz.modules.models import chatgpt_oauth as oauth

    provider = OAuthProvider()
    login = await oauth.start_login(
        session, settings=settings, actor_id=None, transport=provider.transport, now=provider.now
    )
    await oauth.poll_login(
        session,
        settings=settings,
        actor_id=None,
        login_id=login.login_id,
        transport=provider.transport,
        now=provider.now + 5,
    )
    status = await oauth.disconnect(session, settings=settings, actor_id=None)
    assert not status.connected and status.login.state == "cancelled"
    result = await oauth.poll_login(
        session,
        settings=settings,
        actor_id=None,
        login_id=login.login_id,
        transport=provider.transport,
    )
    assert result.state == "cancelled" and len(provider.paths) == 2
    with pytest.raises(UpstreamError, match="Connect ChatGPT"):
        await oauth.get_runtime_credentials(
            session, settings=settings, transport=provider.transport
        )


async def test_concurrent_refresh_rotates_once_and_disconnect_wins(
    session: AsyncSession,
    engine: AsyncEngine,
    settings: Settings,
) -> None:
    from ragz.modules.models import chatgpt_oauth as oauth

    provider = OAuthProvider()
    await connected(session, settings, provider)
    refresh_started = asyncio.Event()
    finish_refresh = asyncio.Event()
    refresh_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal refresh_count
        refresh_count += 1
        refresh_started.set()
        await finish_refresh.wait()
        return httpx.Response(
            200,
            json={
                "access_token": token(2_100_000_000),
                "refresh_token": "rotated-refresh",
                "id_token": token(),
                "expires_in": 3600,
            },
        )

    factory = build_session_factory(engine)

    async def refresh():
        async with factory() as other:
            return await oauth.get_runtime_credentials(
                other,
                settings=settings,
                transport=httpx.MockTransport(handler),
                now=2_000_000_001,
            )

    first = asyncio.create_task(refresh())
    await refresh_started.wait()
    second = asyncio.create_task(refresh())
    finish_refresh.set()
    credentials = await asyncio.gather(first, second)
    assert refresh_count == 1
    assert credentials[0].access_token == credentials[1].access_token == token(2_100_000_000)
    assert token(2_100_000_000) not in repr(credentials[0])
    async with factory() as other:
        await oauth.disconnect(other, settings=settings, actor_id=None)
    async with factory() as other:
        with pytest.raises(UpstreamError, match="Connect ChatGPT"):
            await oauth.get_runtime_credentials(other, settings=settings)


async def test_provider_failure_hides_tokens_and_response_body(
    session: AsyncSession,
    settings: Settings,
) -> None:
    from ragz.modules.models import chatgpt_oauth as oauth

    transport = httpx.MockTransport(lambda _: httpx.Response(500, text="private-provider-body"))
    with pytest.raises(UpstreamError) as error:
        await oauth.start_login(session, settings=settings, actor_id=None, transport=transport)
    assert "private-provider-body" not in str(error.value)


@pytest.mark.parametrize("interval", ["private-invalid-interval", {}, -100, 1])
async def test_device_interval_is_validated_without_exposing_provider_data(
    session: AsyncSession,
    settings: Settings,
    interval: object,
) -> None:
    from ragz.modules.models import chatgpt_oauth as oauth

    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={
                "device_auth_id": "device",
                "user_code": "CODE",
                "interval": interval,
            },
        )
    )
    if isinstance(interval, int):
        login = await oauth.start_login(
            session, settings=settings, actor_id=None, transport=transport
        )
        assert login.interval >= 5
    else:
        with pytest.raises(UpstreamError) as error:
            await oauth.start_login(session, settings=settings, actor_id=None, transport=transport)
        assert "private-invalid-interval" not in str(error.value)


@pytest.mark.parametrize("operation", ["cancel_login", "disconnect"])
async def test_cancel_waiting_for_final_exchange_cannot_resurrect_connection(
    session: AsyncSession,
    engine: AsyncEngine,
    settings: Settings,
    operation: str,
) -> None:
    from ragz.modules.models import chatgpt_oauth as oauth

    provider = OAuthProvider()
    login = await oauth.start_login(
        session, settings=settings, actor_id=None, transport=provider.transport, now=provider.now
    )
    await oauth.poll_login(
        session,
        settings=settings,
        actor_id=None,
        login_id=login.login_id,
        transport=provider.transport,
        now=provider.now + 5,
    )
    started, release = asyncio.Event(), asyncio.Event()

    async def exchange(request: httpx.Request) -> httpx.Response:
        started.set()
        await release.wait()
        return provider.handler(request)

    factory = build_session_factory(engine)

    async def poll():
        async with factory() as other:
            return await oauth.poll_login(
                other,
                settings=settings,
                actor_id=None,
                login_id=login.login_id,
                now=provider.now + 5,
                transport=httpx.MockTransport(exchange),
            )

    async def cancel():
        async with factory() as other:
            return await getattr(oauth, operation)(other, settings=settings, actor_id=None)

    polling = asyncio.create_task(poll())
    await asyncio.wait_for(started.wait(), timeout=5)
    cancellation = asyncio.create_task(cancel())
    release.set()
    await asyncio.wait_for(asyncio.gather(polling, cancellation), timeout=5)
    async with factory() as other:
        status = await oauth.connection_status(other, settings=settings)
    assert not status.connected and status.login.state == "cancelled"


async def test_device_expiry_during_upstream_poll_drops_authorization_grant(
    session: AsyncSession,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ragz.modules.models import chatgpt_oauth as oauth

    provider = OAuthProvider()
    monkeypatch.setattr(oauth.time, "time", lambda: provider.now)
    login = await oauth.start_login(
        session, settings=settings, actor_id=None, transport=provider.transport
    )
    provider.now += 5

    def delayed(request: httpx.Request) -> httpx.Response:
        provider.now += 1000
        return provider.handler(request)

    result = await oauth.poll_login(
        session,
        settings=settings,
        actor_id=None,
        login_id=login.login_id,
        transport=httpx.MockTransport(delayed),
    )
    assert result.state == "expired" and result.user_code is None
    status = await oauth.connection_status(session, settings=settings)
    assert not status.connected


async def test_malformed_account_claims_fail_without_exposing_token(
    session: AsyncSession,
    settings: Settings,
) -> None:
    from ragz.modules.models import chatgpt_oauth as oauth

    provider = OAuthProvider()
    login = await oauth.start_login(
        session, settings=settings, actor_id=None, transport=provider.transport, now=provider.now
    )
    await oauth.poll_login(
        session,
        settings=settings,
        actor_id=None,
        login_id=login.login_id,
        transport=provider.transport,
        now=provider.now + 5,
    )
    claims = {"exp": 2_000_000_000, "https://api.openai.com/auth": ["private-claim"]}
    encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    malformed = f"header.{encoded}.signature"
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={
                "access_token": malformed,
                "refresh_token": "private-refresh",
                "id_token": token(),
            },
        )
    )
    result = await oauth.poll_login(
        session,
        settings=settings,
        actor_id=None,
        login_id=login.login_id,
        transport=transport,
        now=provider.now + 5,
    )
    assert result.state == "failed"
    assert malformed not in result.model_dump_json()
    assert not (await oauth.connection_status(session, settings=settings)).connected
