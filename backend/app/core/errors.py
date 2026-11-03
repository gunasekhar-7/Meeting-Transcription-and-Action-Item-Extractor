"""Typed application errors rendered as RFC 9457 problem+json."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    status_code = 500
    code = "internal_error"
    title = "Internal server error"

    def __init__(self, detail: str | None = None, *, errors: list[dict[str, Any]] | None = None) -> None:
        super().__init__(detail or self.title)
        self.detail = detail or self.title
        self.errors = errors or []


class BadRequest(AppError):
    status_code = 400
    code = "bad_request"
    title = "Bad request"


class Unauthenticated(AppError):
    status_code = 401
    code = "unauthenticated"
    title = "Authentication required"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"
    title = "Forbidden"


class NotFound(AppError):
    status_code = 404
    code = "not_found"
    title = "Resource not found"


class Conflict(AppError):
    status_code = 409
    code = "conflict"
    title = "Request conflicts with current state"


class DuplicateAudio(Conflict):
    code = "duplicate_audio"
    title = "Audio already uploaded"

    def __init__(self, existing_meeting_id: str) -> None:
        super().__init__(
            "This audio file was already uploaded. Use the existing meeting instead.",
            errors=[{"field": "file", "message": f"existing_meeting_id={existing_meeting_id}"}],
        )
        self.existing_meeting_id = existing_meeting_id


class AudioTooLarge(AppError):
    status_code = 413
    code = "audio_too_large"
    title = "Audio file too large"


class UnsupportedMedia(AppError):
    status_code = 415
    code = "unsupported_media_type"
    title = "Unsupported audio format"


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_error"
    title = "Request validation failed"


class AudioUnreadable(AppError):
    status_code = 422
    code = "audio_unreadable"
    title = "Audio cannot be read"


class AudioTooLong(AppError):
    status_code = 422
    code = "audio_too_long"
    title = "Audio exceeds the duration limit"


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"
    title = "Too many requests"


class ServiceUnavailable(AppError):
    status_code = 503
    code = "service_unavailable"
    title = "Service temporarily unavailable"


class LLMNotConfigured(ServiceUnavailable):
    code = "llm_not_configured"
    title = "Meeting analysis is not configured"

    def __init__(self) -> None:
        super().__init__("Set LLM_PROVIDER and LLM_API_KEY to enable meeting analysis.")


class StorageUnavailable(ServiceUnavailable):
    code = "storage_unavailable"
    title = "Object storage is unavailable"


class PipelineError(Exception):
    """Raised inside workers; carries a stable, user-visible code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
