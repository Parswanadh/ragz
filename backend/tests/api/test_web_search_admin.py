import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragz.core.app_settings import get_app_setting
from ragz.modules.secrets.models import Secret


async def test_web_config_and_encrypted_keys_roundtrip(
    client: httpx.AsyncClient,
    superadmin_headers: dict[str, str],
    session: AsyncSession,
) -> None:
    initial = await client.get("/api/v1/admin/web-search", headers=superadmin_headers)
    assert initial.status_code == 200
    assert initial.json()["provider"] == "duckduckgo"
    assert initial.json()["perplexity_model"] == "openai/gpt-5.6-luna"
    key = "pplx-test-secret-not-readable"
    written = await client.put(
        "/api/v1/admin/web-search/keys/perplexity",
        json={"api_key": key},
        headers=superadmin_headers,
    )
    assert written.status_code == 200
    assert key not in written.text
    provider = next(p for p in written.json()["providers"] if p["id"] == "perplexity")
    assert provider["key_set"] and provider["ready"] and provider["key_fingerprint"]
    row = (await session.execute(select(Secret).where(Secret.name == "perplexity"))).scalar_one()
    assert key.encode() not in row.ciphertext
    patched = await client.patch(
        "/api/v1/admin/web-search",
        headers=superadmin_headers,
        json={
            "provider": "perplexity",
            "perplexity_model": "openai/gpt-5.6-sol",
            "max_calls_per_turn": 2,
            "daily_cap": 12,
            "full_content": False,
        },
    )
    assert patched.status_code == 200
    assert patched.json()["max_calls_per_turn"] == 2
    assert patched.json()["daily_cap"] == 12
    assert await get_app_setting(session, "web_search_provider") == "perplexity"
    assert await get_app_setting(session, "web_search_full_content") == "false"
    deleted = await client.delete(
        "/api/v1/admin/web-search/keys/perplexity",
        headers=superadmin_headers,
    )
    assert deleted.status_code == 200
    assert not next(p for p in deleted.json()["providers"] if p["id"] == "perplexity")["key_set"]


@pytest.mark.parametrize(
    "patch",
    [
        {"max_calls_per_turn": 0},
        {"max_calls_per_turn": 51},
        {"max_calls_per_turn": 1.5},
        {"daily_cap": -1},
        {"daily_cap": 10001},
        {"daily_cap": True},
        {"perplexity_model": " "},
        {"perplexity_model": "x" * 121},
        {"provider": "invalid"},
    ],
)
async def test_invalid_web_settings_are_rejected(
    client: httpx.AsyncClient,
    superadmin_headers: dict[str, str],
    patch: dict[str, object],
) -> None:
    response = await client.patch(
        "/api/v1/admin/web-search",
        headers=superadmin_headers,
        json=patch,
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/admin/web-search", None),
        ("PATCH", "/admin/web-search", {}),
        ("PUT", "/admin/web-search/keys/perplexity", {"api_key": "test-key"}),
        ("DELETE", "/admin/web-search/keys/perplexity", None),
        ("POST", "/admin/web-search/test/perplexity", None),
    ],
)
async def test_all_web_configuration_routes_require_superadmin(
    client: httpx.AsyncClient,
    user_headers: dict[str, str],
    method: str,
    path: str,
    body: dict[str, str] | None,
) -> None:
    response = await client.request(method, f"/api/v1{path}", headers=user_headers, json=body)
    assert response.status_code == 403


async def test_missing_provider_key_test_is_safe_and_does_not_call_upstream(
    client: httpx.AsyncClient,
    superadmin_headers: dict[str, str],
) -> None:
    response = await client.post(
        "/api/v1/admin/web-search/test/perplexity",
        headers=superadmin_headers,
    )
    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert response.json()["result_count"] == 0


async def test_invalid_key_never_echoes_plaintext_in_validation_response(
    client: httpx.AsyncClient,
    superadmin_headers: dict[str, str],
) -> None:
    key = "pplx-secret-marker-" + "s" * 8192
    response = await client.put(
        "/api/v1/admin/web-search/keys/perplexity",
        headers=superadmin_headers,
        json={"api_key": key},
    )
    assert response.status_code == 422
    assert "pplx-secret-marker" not in response.text
