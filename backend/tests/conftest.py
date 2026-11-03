from __future__ import annotations

import io
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.base import Base
from app.main import create_app

PASSWORD = "correct-horse-battery-9"
EMAIL = "ada@example.com"


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(
        env="test",
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        local_storage_path=str(tmp_path / "audio"),
        jwt_secret="test-secret-" + "a" * 40,
        asr_provider="fake",
        llm_provider="rule_based",
        jobs_mode="inline",
        rate_limit_enabled=False,
        api_docs_enabled=True,
        llm_model="test-model",
        llm_api_key=None,
        log_level="WARNING",
    )


@pytest.fixture()
def app(settings: Settings):  # type: ignore[no-untyped-def]
    application = create_app(settings)
    Base.metadata.create_all(application.state.engine)
    return application


@pytest.fixture()
def client(app):  # type: ignore[no-untyped-def]
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def auth_headers(client: TestClient) -> dict[str, str]:
    register = client.post(
        "/api/v1/auth/register",
        json={"email": EMAIL, "password": PASSWORD, "display_name": "Ada"},
    )
    assert register.status_code == 201, register.text
    login = client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture()
def wav_bytes() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 8000)
    return buffer.getvalue()
