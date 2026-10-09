"""Interview rounds and their prep pages (Phase 4 spec §4). Cookie auth only;
the Claude token is rejected like on every other non-/api/claude route."""

from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_sheet_sync_scheduler
from app.db.session import get_db
from app.models.interview import InterviewRound
from app.schemas.interview import (
    InterviewRoundCreate,
    InterviewRoundDetailOut,
    InterviewRoundOut,
    InterviewRoundSummaryOut,
    InterviewRoundUpdate,
    RoundContactOut,
    RoundContactsIn,
    RoundStoriesIn,
    RoundStoryOut,
)
from app.services import interview_service
from app.services.errors import (
    ApplicationNotFoundError,
    ContactNotFoundError,
    ContactNotOnApplicationError,
    InterviewRoundNotFoundError,
    RoundNotScheduledError,
    StoryArchivedError,
    StoryNotFoundError,
)
from app.services.interview_service import ROUND_SYNC_TABS, RoundScope
from app.services.sheet_sync_service import CONTACT_TABS, SheetSyncScheduler

router = APIRouter(
    prefix="/api/interviews",
    tags=["interviews"],
    dependencies=[Depends(get_current_user)],
)

_NOT_FOUND = HTTPException(status_code=404, detail="interview round not found")


def _summary_fields(interview_round: InterviewRound, now: datetime) -> dict:
    done, total = interview_service.checklist_progress(interview_round)
    return {
        **InterviewRoundOut.model_validate(interview_round).model_dump(),
        "company": interview_round.application.company,
        "role_title": interview_round.application.role_title,
        "checklist_done": done,
        "checklist_total": total,
        "thank_you_due": interview_service.thank_you_due(interview_round, now),
    }


def _detail(interview_round: InterviewRound) -> InterviewRoundDetailOut:
    return InterviewRoundDetailOut(
        **_summary_fields(interview_round, datetime.now(timezone.utc)),
        contacts=[RoundContactOut.model_validate(c) for c in interview_round.contacts],
        stories=[RoundStoryOut.model_validate(s) for s in interview_round.stories],
    )


def _get(db: Session, round_id: int) -> InterviewRound:
    try:
        return interview_service.get_round(db, round_id)
    except InterviewRoundNotFoundError:
        raise _NOT_FOUND


@router.get("", response_model=list[InterviewRoundSummaryOut])
def list_rounds(
    scope: RoundScope = "all",
    application_id: int | None = None,
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    rounds = interview_service.list_rounds(db, scope, application_id=application_id, now=now)
    return [InterviewRoundSummaryOut(**_summary_fields(r, now)) for r in rounds]


@router.post("", response_model=InterviewRoundDetailOut, status_code=201)
def create_round(
    data: InterviewRoundCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    sync: SheetSyncScheduler = Depends(get_sheet_sync_scheduler),
):
    try:
        interview_round = interview_service.create_round(db, data)
    except ApplicationNotFoundError:
        raise HTTPException(status_code=422, detail="application not found")
    sync.schedule(background_tasks, ROUND_SYNC_TABS)
    return _detail(interview_round)


@router.get("/{round_id}", response_model=InterviewRoundDetailOut)
def get_round(round_id: int, db: Session = Depends(get_db)):
    return _detail(_get(db, round_id))


@router.patch("/{round_id}", response_model=InterviewRoundDetailOut)
def update_round(
    round_id: int,
    data: InterviewRoundUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    sync: SheetSyncScheduler = Depends(get_sheet_sync_scheduler),
):
    try:
        interview_round = interview_service.update_round(db, round_id, data)
    except InterviewRoundNotFoundError:
        raise _NOT_FOUND
    sync.schedule(background_tasks, ROUND_SYNC_TABS)
    return _detail(interview_round)


@router.delete("/{round_id}", status_code=204)
def delete_round(
    round_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    sync: SheetSyncScheduler = Depends(get_sheet_sync_scheduler),
):
    try:
        interview_service.delete_round(db, round_id)
    except InterviewRoundNotFoundError:
        raise _NOT_FOUND
    sync.schedule(background_tasks, ROUND_SYNC_TABS)
    return Response(status_code=204)


@router.put("/{round_id}/contacts", response_model=InterviewRoundDetailOut)
def set_contacts(
    round_id: int,
    body: RoundContactsIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    sync: SheetSyncScheduler = Depends(get_sheet_sync_scheduler),
):
    try:
        interview_round = interview_service.set_round_contacts(db, round_id, body.contact_ids)
    except InterviewRoundNotFoundError:
        raise _NOT_FOUND
    except ContactNotFoundError as e:
        raise HTTPException(status_code=422, detail=f"contact {e.args[0]} not found")
    except ContactNotOnApplicationError as e:
        raise HTTPException(status_code=422, detail=e.message)
    # Linking can attach a contact to the application.
    sync.schedule(background_tasks, CONTACT_TABS)
    return _detail(interview_round)


@router.put("/{round_id}/stories", response_model=InterviewRoundDetailOut)
def set_stories(round_id: int, body: RoundStoriesIn, db: Session = Depends(get_db)):
    try:
        interview_round = interview_service.set_round_stories(db, round_id, body.story_ids)
    except InterviewRoundNotFoundError:
        raise _NOT_FOUND
    except StoryNotFoundError as e:
        raise HTTPException(status_code=422, detail=f"story {e.args[0]} not found")
    except StoryArchivedError as e:
        raise HTTPException(status_code=422, detail=e.message)
    return _detail(interview_round)


@router.get("/{round_id}/calendar.ics")
def calendar(round_id: int, db: Session = Depends(get_db)):
    interview_round = _get(db, round_id)
    try:
        body = interview_service.round_calendar(interview_round)
    except RoundNotScheduledError:
        raise HTTPException(status_code=409, detail="interview round has no scheduled time")
    return Response(
        content=body,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="interview-{round_id}.ics"'},
    )
