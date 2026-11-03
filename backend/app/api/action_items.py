"""Action item routes."""

from __future__ import annotations

from datetime import date
from math import ceil

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, Db, owned_meeting
from app.api.presenters import action_item_out, action_list_item
from app.core.errors import NotFound, ValidationFailed
from app.db.models import ActionItem, Meeting, Speaker, Transcript
from app.schemas.api import (
    ActionItemCreate,
    ActionItemListItem,
    ActionItemOut,
    ActionItemUpdate,
)
from app.schemas.common import Page
from app.services.exports import action_items_csv

router = APIRouter(prefix="/action-items", tags=["action-items"])


def _base_query(user_id: str):  # type: ignore[no-untyped-def]
    return (
        select(ActionItem)
        .join(Meeting, Meeting.id == ActionItem.meeting_id)
        .where(Meeting.owner_id == user_id)
        .options(
            selectinload(ActionItem.meeting),
            selectinload(ActionItem.owner),
            selectinload(ActionItem.evidence),
        )
    )


def _apply_filters(stmt, *, status_filter, priority, assigned, overdue, due_before, due_after, q):  # type: ignore[no-untyped-def]
    if status_filter:
        stmt = stmt.where(ActionItem.status.in_(status_filter))
    if priority:
        stmt = stmt.where(ActionItem.priority == priority)
    if assigned is True:
        stmt = stmt.where(ActionItem.owner_speaker_id.is_not(None))
    if assigned is False:
        stmt = stmt.where(ActionItem.owner_speaker_id.is_(None))
    if overdue:
        stmt = stmt.where(
            ActionItem.due_date < date.today(),
            ActionItem.status.notin_(["done", "cancelled"]),
        )
    if due_before:
        stmt = stmt.where(ActionItem.due_date <= due_before)
    if due_after:
        stmt = stmt.where(ActionItem.due_date >= due_after)
    if q:
        stmt = stmt.where(ActionItem.title.ilike(f"%{q.strip()}%"))
    return stmt


@router.get("", response_model=Page[ActionItemListItem])
def list_action_items(
    db: Db,
    user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: list[str] | None = Query(default=None, alias="status"),
    priority: str | None = None,
    assigned: bool | None = None,
    overdue: bool = False,
    due_before: date | None = None,
    due_after: date | None = None,
    q: str | None = Query(default=None, max_length=200),
) -> Page[ActionItemListItem]:
    stmt = _apply_filters(
        _base_query(user.id),
        status_filter=status_filter,
        priority=priority,
        assigned=assigned,
        overdue=overdue,
        due_before=due_before,
        due_after=due_after,
        q=q,
    )
    count_stmt = _apply_filters(
        select(ActionItem)
        .join(Meeting, Meeting.id == ActionItem.meeting_id)
        .where(Meeting.owner_id == user.id),
        status_filter=status_filter,
        priority=priority,
        assigned=assigned,
        overdue=overdue,
        due_before=due_before,
        due_after=due_after,
        q=q,
    )
    total = db.scalar(select(func.count()).select_from(count_stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(ActionItem.due_date.asc(), ActionItem.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return Page[ActionItemListItem](
        items=[action_list_item(item) for item in rows],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=ceil(total / page_size) if total else 0,
    )


@router.post("", response_model=ActionItemOut, status_code=status.HTTP_201_CREATED)
def create_action_item(
    payload: ActionItemCreate, db: Db, user: CurrentUser
) -> ActionItemOut:
    meeting = owned_meeting(db, user, payload.meeting_id)
    owner: Speaker | None = None
    if payload.owner_speaker_id:
        owner = db.scalar(
            select(Speaker)
            .join(Transcript, Transcript.id == Speaker.transcript_id)
            .where(
                Speaker.id == payload.owner_speaker_id,
                Transcript.meeting_id == meeting.id,
                Transcript.is_active.is_(True),
            )
        )
        if owner is None:
            raise ValidationFailed("Owner must belong to this meeting's active transcript")

    due_date = payload.due_date
    item = ActionItem(
        meeting_id=meeting.id,
        intelligence_id=None,
        sequence=None,
        title=payload.title.strip(),
        description=(payload.description or "").strip() or None,
        owner_speaker_id=owner.id if owner else None,
        owner_text=(owner.display_name or owner.label) if owner else None,
        owner_resolution="matched_speaker" if owner else "unassigned",
        due_date=due_date,
        due_date_text=due_date.isoformat() if due_date else None,
        due_date_precision="day" if due_date else "unknown",
        priority=payload.priority,
        status="open",
        confidence=None,
        is_user_edited=True,
    )
    db.add(item)
    db.commit()

    transcript = db.scalar(
        select(Transcript).where(Transcript.meeting_id == meeting.id, Transcript.is_active.is_(True))
    )
    segments = {segment.id: segment for segment in transcript.segments} if transcript else {}
    return action_item_out(item, segments)


@router.patch("/{item_id}", response_model=ActionItemOut)
def update_action_item(
    item_id: str, payload: ActionItemUpdate, db: Db, user: CurrentUser
) -> ActionItemOut:
    item = db.scalar(_base_query(user.id).where(ActionItem.id == item_id))
    if item is None:
        raise NotFound("Action item not found")

    fields = payload.model_fields_set
    if "title" in fields:
        if not payload.title or not payload.title.strip():
            raise ValidationFailed("Title cannot be empty")
        item.title = payload.title.strip()
    if "description" in fields:
        item.description = (payload.description or "").strip() or None
    if "priority" in fields and payload.priority:
        item.priority = payload.priority
    if "status" in fields and payload.status:
        item.status = payload.status

    if "owner_speaker_id" in fields:
        if payload.owner_speaker_id is None:
            item.owner_speaker_id = None
            item.owner_text = None
            item.owner_resolution = "unassigned"
        else:
            owner = db.get(Speaker, payload.owner_speaker_id)
            active_transcript = db.scalar(
                select(Transcript).where(
                    Transcript.meeting_id == item.meeting_id,
                    Transcript.is_active.is_(True),
                )
            )
            if (
                owner is None
                or active_transcript is None
                or owner.transcript_id != active_transcript.id
            ):
                raise ValidationFailed("Owner must belong to this meeting's active transcript")
            item.owner_speaker_id = owner.id
            item.owner_text = owner.display_name or owner.label
            item.owner_resolution = "matched_speaker"

    if "due_date" in fields:
        if payload.due_date is None:
            item.due_date = None
            item.due_date_text = None
            item.due_date_precision = "unknown"
        else:
            item.due_date = payload.due_date
            item.due_date_text = payload.due_date.isoformat()
            item.due_date_precision = "day"

    item.is_user_edited = True
    db.commit()

    transcript = db.scalar(
        select(Transcript).where(
            Transcript.meeting_id == item.meeting_id, Transcript.is_active.is_(True)
        )
    )
    segments = {segment.id: segment for segment in transcript.segments} if transcript else {}
    return action_item_out(item, segments)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_action_item(item_id: str, db: Db, user: CurrentUser) -> Response:
    item = db.scalar(_base_query(user.id).where(ActionItem.id == item_id))
    if item is None:
        raise NotFound("Action item not found")
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/export.csv")
def export_csv(
    db: Db,
    user: CurrentUser,
    status_filter: list[str] | None = Query(default=None, alias="status"),
    overdue: bool = False,
) -> Response:
    stmt = _apply_filters(
        _base_query(user.id),
        status_filter=status_filter,
        priority=None,
        assigned=None,
        overdue=overdue,
        due_before=None,
        due_after=None,
        q=None,
    )
    items = db.scalars(stmt.order_by(ActionItem.due_date.asc())).all()
    return Response(
        content=action_items_csv(list(items)),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="action-items.csv"'},
    )
