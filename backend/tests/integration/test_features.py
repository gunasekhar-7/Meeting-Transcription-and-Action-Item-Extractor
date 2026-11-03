from __future__ import annotations

from fastapi.testclient import TestClient


def test_system_operational_endpoints(client: TestClient, auth_headers: dict[str, str]) -> None:
    reconcile_resp = client.post("/api/v1/system/reconcile", headers=auth_headers)
    assert reconcile_resp.status_code == 200, reconcile_resp.text
    data = reconcile_resp.json()
    assert "checked" in data
    assert "requeued" in data
    assert "failed" in data

    retention_resp = client.post("/api/v1/system/retention", headers=auth_headers)
    assert retention_resp.status_code == 200, retention_resp.text
    ret_data = retention_resp.json()
    assert "retention" in ret_data
    assert "orphans" in ret_data


def test_pipeline_with_diarization(
    client: TestClient,
    auth_headers: dict[str, str],
    wav_bytes: bytes,
    settings,  # type: ignore[no-untyped-def]
) -> None:
    settings.diarization_provider = "fake"

    meeting = client.post("/api/v1/meetings", json={"title": "Diarized sync"}, headers=auth_headers).json()
    meeting_id = meeting["id"]

    upload = client.post(
        f"/api/v1/meetings/{meeting_id}/audio",
        files={"file": ("sync.wav", wav_bytes, "audio/wav")},
        headers=auth_headers,
    )
    assert upload.status_code == 202

    transcript_resp = client.get(f"/api/v1/meetings/{meeting_id}/transcript", headers=auth_headers)
    assert transcript_resp.status_code == 200
    transcript = transcript_resp.json()
    assert len(transcript["segments"]) > 0
    # Speakers from fake diarization should be assigned
    speaker_labels = {seg["speaker_label"] for seg in transcript["segments"]}
    assert "SPEAKER_00" in speaker_labels or "SPEAKER_01" in speaker_labels
