from __future__ import annotations

from fastapi.testclient import TestClient


def _create_meeting(client: TestClient, headers: dict[str, str], title: str = "Weekly sync") -> str:
    response = client.post("/api/v1/meetings", json={"title": title}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _upload(client: TestClient, headers: dict[str, str], meeting_id: str, wav: bytes):  # type: ignore[no-untyped-def]
    response = client.post(
        f"/api/v1/meetings/{meeting_id}/audio",
        files={"file": ("sync.wav", wav, "audio/wav")},
        headers=headers,
    )
    assert response.status_code == 202, response.text
    return response.json()


def test_upload_transcribe_and_extract(
    client: TestClient, auth_headers: dict[str, str], wav_bytes: bytes
) -> None:
    meeting_id = _create_meeting(client, auth_headers)
    _upload(client, auth_headers, meeting_id, wav_bytes)

    status = client.get(f"/api/v1/meetings/{meeting_id}/status", headers=auth_headers)
    assert status.status_code == 200
    assert status.json()["status"] == "ready", status.text
    assert status.json()["intelligence_status"] == "ready"

    transcript = client.get(
        f"/api/v1/meetings/{meeting_id}/transcript", headers=auth_headers
    ).json()
    assert len(transcript["segments"]) == 3
    assert {segment["speaker_label"] for segment in transcript["segments"]} == {
        "SPEAKER_00",
        "SPEAKER_01",
    }
    assert transcript["segments"][0]["start_ms"] < transcript["segments"][1]["start_ms"]

    intelligence = client.get(
        f"/api/v1/meetings/{meeting_id}/intelligence", headers=auth_headers
    ).json()
    assert intelligence["summary_short"]
    assert intelligence["decisions"], intelligence
    assert intelligence["action_items"], intelligence

    segments = {segment["id"]: segment for segment in transcript["segments"]}
    for item in intelligence["action_items"] + intelligence["decisions"]:
        assert item["evidence"], item
        for link in item["evidence"]:
            segment = segments[link["segment_id"]]
            assert segment["text"][link["char_start"] : link["char_end"]] == link["quote"]

    ada = next(
        item for item in intelligence["action_items"] if item["owner_text"] == "Ada"
    )
    assert ada["owner_resolution"] == "unresolved_mention"
    assert ada["owner_speaker_id"] is None
    assert ada["due_date"] is None
    assert ada["due_date_precision"] == "unknown"


def test_edit_action_item_marks_user_edited(
    client: TestClient, auth_headers: dict[str, str], wav_bytes: bytes
) -> None:
    meeting_id = _create_meeting(client, auth_headers)
    _upload(client, auth_headers, meeting_id, wav_bytes)
    intelligence = client.get(
        f"/api/v1/meetings/{meeting_id}/intelligence", headers=auth_headers
    ).json()
    item = intelligence["action_items"][0]

    response = client.patch(
        f"/api/v1/action-items/{item['id']}",
        json={"status": "done", "title": "Updated title", "due_date": "2026-11-20"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["status"] == "done"
    assert updated["title"] == "Updated title"
    assert updated["is_user_edited"] is True
    assert updated["due_date"] == "2026-11-20"
    assert updated["due_date_precision"] == "day"


def test_export_contains_schema_and_evidence(
    client: TestClient, auth_headers: dict[str, str], wav_bytes: bytes
) -> None:
    meeting_id = _create_meeting(client, auth_headers)
    _upload(client, auth_headers, meeting_id, wav_bytes)

    response = client.get(
        f"/api/v1/meetings/{meeting_id}/export?format=json", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["schema_version"]
    assert payload["meeting"]["title"] == "Weekly sync"
    assert payload["intelligence"]["action_items"]
    assert payload["intelligence"]["action_items"][0]["evidence"]

    markdown = client.get(
        f"/api/v1/meetings/{meeting_id}/export?format=md", headers=auth_headers
    )
    assert markdown.status_code == 200
    assert "# Weekly sync" in markdown.text
    assert "Evidence:" in markdown.text


def test_invalid_upload_is_rejected(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    meeting_id = _create_meeting(client, auth_headers)
    response = client.post(
        f"/api/v1/meetings/{meeting_id}/audio",
        files={"file": ("notes.txt", b"this is not audio", "text/plain")},
        headers=auth_headers,
    )
    assert response.status_code == 415
    assert response.json()["code"] == "unsupported_media_type"


def test_ungrounded_items_are_dropped(
    client: TestClient,
    auth_headers: dict[str, str],
    wav_bytes: bytes,
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    import app.services.pipeline as pipeline
    from app.providers.llm import RuleBasedLLM

    class TamperedLLM(RuleBasedLLM):
        def generate(self, kind, segments):  # type: ignore[no-untyped-def]
            result = super().generate(kind, segments)
            if kind in {"actions", "decisions"}:
                for item in result.payload["items"]:
                    item["evidence"] = [
                        {"segment_id": segments[0].id, "quote": "quantum zebra protocol"}
                    ]
            return result

    monkeypatch.setattr(pipeline, "build_llm", lambda settings: TamperedLLM())

    meeting_id = _create_meeting(client, auth_headers, "Tampered")
    _upload(client, auth_headers, meeting_id, wav_bytes)

    intelligence = client.get(
        f"/api/v1/meetings/{meeting_id}/intelligence", headers=auth_headers
    ).json()
    assert intelligence["action_items"] == []
    assert intelligence["decisions"] == []
    assert intelligence["quality"]["dropped_actions"] >= 1
    assert intelligence["quality"]["dropped_decisions"] >= 1
    assert intelligence["quality"]["grounding_failures"] >= 2
