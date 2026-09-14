import httpx
import pytest


@pytest.mark.parametrize(
    "method, path, body",
    [
        ("GET", "/admin/models/chatgpt", None),
        ("POST", "/admin/models/chatgpt/login", None),
        ("POST", "/admin/models/chatgpt/poll", {"login_id": "test-login"}),
        ("DELETE", "/admin/models/chatgpt/login", None),
        ("DELETE", "/admin/models/chatgpt", None),
    ],
)
async def test_all_chatgpt_routes_require_superadmin(
    client: httpx.AsyncClient,
    user_headers: dict[str, str],
    method: str,
    path: str,
    body: dict[str, str] | None,
) -> None:
    anonymous = await client.request(method, f"/api/v1{path}", json=body)
    assert anonymous.status_code == 401
    admin = await client.request(method, f"/api/v1{path}", headers=user_headers, json=body)
    assert admin.status_code == 403


async def test_superadmin_reads_disconnected_status(
    client: httpx.AsyncClient,
    superadmin_headers: dict[str, str],
) -> None:
    response = await client.get("/api/v1/admin/models/chatgpt", headers=superadmin_headers)
    assert response.status_code == 200
    assert response.json() == {
        "available": True,
        "connected": False,
        "account_id": None,
        "email": None,
        "plan_type": None,
        "expires_at": None,
        "login": {
            "login_id": None,
            "state": "idle",
            "verification_url": None,
            "user_code": None,
            "expires_at": None,
            "interval": 5,
            "error": None,
        },
    }
