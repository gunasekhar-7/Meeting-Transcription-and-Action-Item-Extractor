"""Operational and dashboard routes."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Response, status
from sqlalchemy import func, select, text
from sqlalchemy.orm import selectinload

from app.api.deps import AppSettings, CurrentUser, Db
from app.core.config import Settings
from app.db.models import ActionItem, Meeting, Transcript
from app.schemas.api import DashboardCounts, MetaOut
from app.services.storage import build_storage

health_router = APIRouter(tags=["health"])
system_router = APIRouter(tags=["system"])


def _ready(db, settings: Settings) -> dict[str, object]:
    components: dict[str, object] = {}
    try:
        db.execute(text("SELECT 1"))
        components["database"] = "ok"
    except Exception:
        components["database"] = "error"
    try:
        components["storage"] = "ok" if build_storage(settings).healthcheck() else "error"
    except Exception:
        components["storage"] = "error"
    return components


@health_router.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@health_router.get("/health/ready")
def ready(db: Db, settings: AppSettings, response: Response) -> dict[str, object]:
    components = _ready(db, settings)
    healthy = all(value == "ok" for value in components.values())
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if healthy else "degraded", "components": components}


@system_router.get("/meta", response_model=MetaOut)
def meta(settings: AppSettings) -> MetaOut:
    return MetaOut(
        api_version="0.1.0",
        environment=settings.env,
        schema_version=settings.schema_version,
        prompt_version=settings.prompt_version,
        asr={
            "provider": settings.asr_provider,
            "default_model": settings.asr_model,
            "diarization_enabled": settings.diarization_provider != "none",
        },
        llm={"provider": settings.llm_provider, "default_model": settings.llm_model},
    )


@system_router.get("/dashboard/summary", response_model=DashboardCounts)
def dashboard(db: Db, user: CurrentUser) -> DashboardCounts:
    meeting_rows = db.execute(
        select(Meeting.status, func.count())
        .where(Meeting.owner_id == user.id)
        .group_by(Meeting.status)
    ).all()
    meeting_counts = {"total": 0, "ready": 0, "processing": 0, "failed": 0, "created": 0}
    for name, count in meeting_rows:
        meeting_counts[name] = count
        meeting_counts["total"] += count

    item_rows = db.execute(
        select(ActionItem.status, func.count())
        .join(Meeting, Meeting.id == ActionItem.meeting_id)
        .where(Meeting.owner_id == user.id)
        .group_by(ActionItem.status)
    ).all()
    item_counts = {"open": 0, "in_progress": 0, "blocked": 0, "done": 0, "cancelled": 0, "overdue": 0}
    for name, count in item_rows:
        item_counts[name] = count

    overdue = db.scalar(
        select(func.count())
        .select_from(ActionItem)
        .join(Meeting, Meeting.id == ActionItem.meeting_id)
        .where(
            Meeting.owner_id == user.id,
            ActionItem.due_date < date.today(),
            ActionItem.status.notin_(["done", "cancelled"]),
        )
    )
    item_counts["overdue"] = overdue or 0

    recent = db.scalars(
        select(Meeting)
        .options(selectinload(Meeting.transcripts).selectinload(Transcript.speakers))
        .where(Meeting.owner_id == user.id)
        .order_by(Meeting.created_at.desc())
        .limit(5)
    ).all()

    upcoming = db.execute(
        select(ActionItem, Meeting.title)
        .join(Meeting, Meeting.id == ActionItem.meeting_id)
        .where(
            Meeting.owner_id == user.id,
            ActionItem.due_date.is_not(None),
            ActionItem.status.notin_(["done", "cancelled"]),
        )
        .order_by(ActionItem.due_date.asc())
        .limit(5)
    ).all()

    return DashboardCounts(
        meetings=meeting_counts,
        action_items=item_counts,
        recent_meetings=[
            {
                "id": item.id,
                "title": item.title,
                "status": item.status,
                "created_at": item.created_at.isoformat(),
            }
            for item in recent
        ],
        upcoming_due=[
            {
                "id": item.id,
                "title": item.title,
                "due_date": item.due_date.isoformat() if item.due_date else None,
                "meeting_title": meeting_title,
            }
            for item, meeting_title in upcoming
        ],
    )


@system_router.post("/system/reconcile")
def run_reconcile(db: Db, settings: AppSettings, user: CurrentUser) -> dict[str, int]:
    from app.db.session import session_factory_for
    from app.services.reconciliation import reconcile_stranded_jobs

    return reconcile_stranded_jobs(session_factory_for(settings), settings)


@system_router.post("/system/retention")
def run_retention(db: Db, settings: AppSettings, user: CurrentUser) -> dict[str, object]:
    from app.services.retention import enforce_audio_retention, sweep_orphan_audio

    storage = build_storage(settings)
    purged = enforce_audio_retention(db, storage, settings)
    orphans = sweep_orphan_audio(db, storage)
    return {"retention": purged, "orphans": orphans}
