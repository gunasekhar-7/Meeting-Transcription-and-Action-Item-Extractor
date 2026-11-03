from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import PASSWORD


def test_register_login_and_me(client: TestClient) -> None:
    register = client.post(
        "/api/v1/auth/register",
        json={"email": "new@example.com", "password": PASSWORD, "display_name": "New"},
    )
    assert register.status_code == 201
    login = client.post(
        "/api/v1/auth/login", json={"email": "new@example.com", "password": PASSWORD}
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "new@example.com"


def test_duplicate_email_is_conflict(client: TestClient) -> None:
    payload = {"email": "dupe@example.com", "password": PASSWORD, "display_name": "Dupe"}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 201
    assert client.post("/api/v1/auth/register", json=payload).status_code == 409


def test_wrong_password_is_unauthenticated(client: TestClient) -> None:
    client.post(
        "/api/v1/auth/register",
        json={"email": "bad@example.com", "password": PASSWORD, "display_name": "Bad"},
    )
    response = client.post(
        "/api/v1/auth/login", json={"email": "bad@example.com", "password": "wrong-password-123"}
    )
    assert response.status_code == 401


def test_refresh_rotation_and_reuse_detection(client: TestClient) -> None:
    client.post(
        "/api/v1/auth/register",
        json={"email": "rotate@example.com", "password": PASSWORD, "display_name": "Rotate"},
    )
    login = client.post(
        "/api/v1/auth/login", json={"email": "rotate@example.com", "password": PASSWORD}
    ).json()
    first = login["refresh_token"]

    rotated = client.post("/api/v1/auth/refresh", json={"refresh_token": first})
    assert rotated.status_code == 200
    second = rotated.json()["refresh_token"]
    assert second != first

    reused = client.post("/api/v1/auth/refresh", json={"refresh_token": first})
    assert reused.status_code == 401

    # Reuse revokes the whole family, including the valid descendant.
    family_dead = client.post("/api/v1/auth/refresh", json={"refresh_token": second})
    assert family_dead.status_code == 401


def test_resources_are_scoped_to_the_owner(client: TestClient) -> None:
    client.post(
        "/api/v1/auth/register",
        json={"email": "owner@example.com", "password": PASSWORD, "display_name": "Owner"},
    )
    owner_token = client.post(
        "/api/v1/auth/login", json={"email": "owner@example.com", "password": PASSWORD}
    ).json()["access_token"]
    owner_headers = {"Authorization": f"Bearer {owner_token}"}

    meeting = client.post(
        "/api/v1/meetings", json={"title": "Private meeting"}, headers=owner_headers
    )
    assert meeting.status_code == 201
    meeting_id = meeting.json()["id"]

    client.post(
        "/api/v1/auth/register",
        json={"email": "other@example.com", "password": PASSWORD, "display_name": "Other"},
    )
    other_token = client.post(
        "/api/v1/auth/login", json={"email": "other@example.com", "password": PASSWORD}
    ).json()["access_token"]
    other_headers = {"Authorization": f"Bearer {other_token}"}

    assert client.get(f"/api/v1/meetings/{meeting_id}", headers=other_headers).status_code == 404
    assert client.get("/api/v1/meetings", headers=owner_headers).json()["total"] == 1


def test_missing_token_is_unauthenticated(client: TestClient) -> None:
    assert client.get("/api/v1/meetings").status_code == 401
