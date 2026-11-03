"""HTTP client for the meeting intelligence API.

The UI never touches the database or an AI provider directly; this module is the
only seam between Streamlit and the backend.
"""

from __future__ import annotations

import os
from typing import Any

import httpx


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.request_id = request_id

    def __str__(self) -> str:
        suffix = f" (request {self.request_id})" if self.request_id else ""
        return f"{self.message}{suffix}"


class ApiClient:
    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 120.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = (
            base_url or os.getenv("API_BASE_URL", "http://localhost:8000/api/v1")
        ).rstrip("/")
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def set_tokens(self, access_token: str, refresh_token: str) -> None:
        self.access_token = access_token
        self.refresh_token = refresh_token

    def clear(self) -> None:
        self.access_token = None
        self.refresh_token = None

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"} if self.access_token else {}

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        retry: bool = True,
    ) -> Any:
        response = self._client.request(
            method,
            f"{self.base_url}{path}",
            headers=self._headers(),
            json=json,
            files=files,
            params=params,
        )
        if response.status_code == 401 and retry and self.refresh_token:
            self.refresh()
            return self._request(method, path, json=json, files=files, params=params, retry=False)
        if response.status_code >= 400:
            try:
                body = response.json()
            except ValueError:
                body = {}
            raise ApiError(
                status_code=response.status_code,
                code=body.get("code", "http_error"),
                message=body.get("detail") or f"Request failed with status {response.status_code}",
                request_id=body.get("request_id"),
            )
        if response.status_code == 204:
            return None
        return response.json()

    # --- auth ---------------------------------------------------------
    def register(self, email: str, password: str, display_name: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/auth/register",
            json={"email": email, "password": password, "display_name": display_name},
        )

    def login(self, email: str, password: str) -> dict[str, Any]:
        data = self._request("POST", "/auth/login", json={"email": email, "password": password})
        self.set_tokens(data["access_token"], data["refresh_token"])
        return data

    def refresh(self) -> None:
        if not self.refresh_token:
            raise ApiError(401, "unauthenticated", "Session expired; sign in again")
        data = self._request(
            "POST",
            "/auth/refresh",
            json={"refresh_token": self.refresh_token},
            retry=False,
        )
        self.set_tokens(data["access_token"], data["refresh_token"])

    def logout(self) -> None:
        if self.refresh_token:
            try:
                self._request(
                    "POST",
                    "/auth/logout",
                    json={"refresh_token": self.refresh_token},
                    retry=False,
                )
            except ApiError:
                pass
        self.clear()

    def me(self) -> dict[str, Any]:
        return self._request("GET", "/auth/me")

    # --- meetings -----------------------------------------------------
    def dashboard(self) -> dict[str, Any]:
        return self._request("GET", "/dashboard/summary")

    def list_meetings(self, q: str | None = None, status: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"page_size": 100}
        if q:
            params["q"] = q
        if status:
            params["status"] = status
        return self._request("GET", "/meetings", params=params)

    def create_meeting(
        self,
        title: str,
        description: str | None = None,
        meeting_date: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/meetings",
            json={"title": title, "description": description, "meeting_date": meeting_date},
        )

    def upload(self, meeting_id: str, filename: str, content: bytes, content_type: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/meetings/{meeting_id}/audio",
            files={"file": (filename, content, content_type or "application/octet-stream")},
        )

    def status(self, meeting_id: str) -> dict[str, Any]:
        return self._request("GET", f"/meetings/{meeting_id}/status")

    def transcript(self, meeting_id: str, offset: int = 0, limit: int = 2000) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/meetings/{meeting_id}/transcript",
            params={"offset": offset, "limit": limit},
        )

    def search_transcript(self, meeting_id: str, query: str) -> dict[str, Any]:
        return self._request(
            "GET", f"/meetings/{meeting_id}/transcript/search", params={"q": query}
        )

    def intelligence(self, meeting_id: str) -> dict[str, Any]:
        return self._request("GET", f"/meetings/{meeting_id}/intelligence")

    def analyze(self, meeting_id: str) -> dict[str, Any]:
        return self._request("POST", f"/meetings/{meeting_id}/analyze")

    def rename_speaker(self, meeting_id: str, speaker_id: str, name: str | None) -> dict[str, Any]:
        return self._request(
            "PATCH", f"/meetings/{meeting_id}/speakers/{speaker_id}", json={"display_name": name}
        )

    # --- action items -------------------------------------------------
    def list_action_items(
        self, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        query: dict[str, Any] = {"page_size": 100}
        if params:
            query.update(params)
        return self._request("GET", "/action-items", params=query)

    def update_action_item(self, item_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("PATCH", f"/action-items/{item_id}", json=payload)

    # --- downloads ----------------------------------------------------
    def download(self, meeting_id: str, fmt: str) -> tuple[bytes, str]:
        response = self._client.get(
            f"{self.base_url}/meetings/{meeting_id}/export",
            headers=self._headers(),
            params={"format": fmt},
        )
        if response.status_code >= 400:
            raise ApiError(
                response.status_code, "export_failed", "Could not export this meeting"
            )
        return response.content, response.headers.get("content-type", "application/octet-stream")
