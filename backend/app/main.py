"""Application factory."""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import action_items, auth, meetings, system
from app.core.config import Settings, get_settings
from app.core.errors import AppError, RateLimited
from app.core.logging import (
    configure_logging,
    log_event,
    new_request_id,
    request_id_var,
)
from app.core.rate_limiter import (
    MemorySlidingWindowLimiter,
    build_rate_limiter,
)
from app.db.session import make_engine, make_session_factory

logger = logging.getLogger(__name__)

# Retained as backwards-compatible alias for unit tests
SlidingWindowLimiter = MemorySlidingWindowLimiter


def _problem(
    request: Request,
    *,
    status: int,
    code: str,
    title: str,
    detail: str,
    errors: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content={
            "type": f"https://meeting-intelligence.dev/errors/{code}",
            "title": title,
            "status": status,
            "code": code,
            "detail": detail,
            "instance": request.url.path,
            "request_id": request_id_var.get(),
            "errors": errors or [],
        },
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    engine = make_engine(settings)
    session_factory = make_session_factory(engine)
    limiter = build_rate_limiter(
        backend=settings.rate_limit_backend,
        redis_url=settings.redis_url,
    )

    app = FastAPI(
        title="Meeting Intelligence API",
        version="0.1.0",
        description="Transcription, speaker attribution, and evidence-grounded meeting intelligence.",
        docs_url="/docs" if settings.api_docs_enabled else None,
        openapi_url="/openapi.json" if settings.api_docs_enabled else None,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.rate_limiter = limiter

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("X-Request-ID") or new_request_id()
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            if settings.rate_limit_enabled and not request.url.path.startswith(
                ("/health", "/docs", "/openapi")
            ):
                path = request.url.path
                if path.endswith("/auth/login") or path.endswith("/auth/register"):
                    limit, window = 10, 60.0
                elif path.endswith("/audio"):
                    limit, window = 20, 3600.0
                else:
                    limit, window = 120, 60.0
                client = request.client.host if request.client else "unknown"
                allowed, retry_after = limiter.check((client, path.rsplit("/", 1)[-1]), limit, window)
                if not allowed:
                    error = RateLimited("Rate limit exceeded")
                    response = _problem(
                        request,
                        status=error.status_code,
                        code=error.code,
                        title=error.title,
                        detail=error.detail,
                    )
                    response.headers["Retry-After"] = str(retry_after)
                    return response

            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            log_event(
                "http_request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            return response
        finally:
            request_id_var.reset(token)

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return _problem(
            request,
            status=exc.status_code,
            code=exc.code,
            title=exc.title,
            detail=exc.detail,
            errors=exc.errors,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = []
        for error in exc.errors():
            location = ".".join(str(part) for part in error.get("loc", []) if part != "body")
            errors.append({"field": location or "body", "message": error.get("msg", "Invalid value")})
        return _problem(
            request,
            status=422,
            code="validation_error",
            title="Request validation failed",
            detail="One or more fields failed validation.",
            errors=errors,
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception", extra={"extra_fields": {"path": request.url.path}})
        return _problem(
            request,
            status=500,
            code="internal_error",
            title="Internal server error",
            detail="An unexpected error occurred. Use the request_id when reporting it.",
        )

    app.include_router(system.health_router)
    for router in (auth.router, meetings.router, action_items.router, system.system_router):
        app.include_router(router, prefix=settings.api_prefix)

    log_event(
        "app_started",
        environment=settings.env,
        asr_provider=settings.asr_provider,
        llm_provider=settings.llm_provider,
        jobs_mode=settings.jobs_mode,
    )
    return app


app = create_app()
