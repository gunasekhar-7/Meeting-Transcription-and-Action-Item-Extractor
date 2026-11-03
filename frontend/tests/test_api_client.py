from __future__ import annotations

import httpx
import pytest

from streamlit_app.api_client import ApiClient, ApiError


def test_login_stores_tokens() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/auth/login"
        return httpx.Response(
            200,
            json={"access_token": "access-1", "refresh_token": "refresh-1", "expires_in": 900},
        )

    client = ApiClient(base_url="http://test/api/v1", transport=httpx.MockTransport(handler))
    client.login("ada@example.com", "correct-horse-battery-9")
    assert client.access_token == "access-1"
    assert client.refresh_token == "refresh-1"


def test_problem_error_is_mapped_to_code() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409,
            json={
                "code": "duplicate_audio",
                "detail": "This audio was already uploaded.",
                "request_id": "req-123",
            },
        )

    client = ApiClient(base_url="http://test/api/v1", transport=httpx.MockTransport(handler))
    with pytest.raises(ApiError) as raised:
        client.create_meeting("Weekly sync")
    assert raised.value.status_code == 409
    assert raised.value.code == "duplicate_audio"
    assert "req-123" in str(raised.value)


def test_401_refreshes_once_and_retries() -> None:
    calls = {"me": 0, "refresh": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/refresh"):
            calls["refresh"] += 1
            return httpx.Response(
                200, json={"access_token": "new", "refresh_token": "new-refresh", "expires_in": 900}
            )
        calls["me"] += 1
        if calls["me"] == 1:
            return httpx.Response(401, json={"code": "unauthenticated", "detail": "expired"})
        return httpx.Response(200, json={"id": "u1", "display_name": "Ada", "email": "a@b.c"})

    client = ApiClient(base_url="http://test/api/v1", transport=httpx.MockTransport(handler))
    client.set_tokens("old", "old-refresh")
    user = client.me()
    assert user["display_name"] == "Ada"
    assert calls["refresh"] == 1
    assert client.access_token == "new"
