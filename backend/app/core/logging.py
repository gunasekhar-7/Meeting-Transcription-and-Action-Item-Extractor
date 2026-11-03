"""Structured JSON logging with request-scoped correlation IDs."""

from __future__ import annotations

import contextvars
import json
import logging
import sys
import time
import uuid
from typing import Any

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
meeting_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("meeting_id", default="-")
job_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("job_id", default="-")

_REDACTED_KEYS = {"authorization", "password", "token", "api_key", "refresh_token", "secret"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "event": record.getMessage(),
            "logger": record.name,
            "request_id": request_id_var.get(),
        }
        if meeting_id_var.get() != "-":
            payload["meeting_id"] = meeting_id_var.get()
        if job_id_var.get() != "-":
            payload["job_id"] = job_id_var.get()

        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            for key, value in extra.items():
                if key.lower() in _REDACTED_KEYS:
                    payload[key] = "[redacted]"
                else:
                    payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    logging.getLogger("uvicorn.access").handlers = [handler]


def new_request_id() -> str:
    return uuid.uuid4().hex


def log_event(event: str, **fields: Any) -> None:
    logging.getLogger("app").info(event, extra={"extra_fields": fields})
