"""The scheduled Claude job's only way in (spec §13.5). Every route is
behind `get_claude_token`; nothing here accepts a session cookie."""

from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_claude_token, get_sheet_sync_scheduler
from app.db.session import get_db
from app.schemas.claude import ContactsBatchIn, FollowupsBatchIn, IngestResultOut, QueueResultIn, WorkOut
from app.schemas.research_queue import QueueItemOut
from app.services import claude_ingest_service
from app.services.errors import QueueItemNotFoundError, QueueItemNotPendingError
from app.services.sheet_sync_service import CONTACT_TABS, SheetSyncScheduler

router = APIRouter(prefix="/api/claude", tags=["claude"], dependencies=[Depends(get_claude_token)])


@router.get("/work", response_model=WorkOut)
def work(db: Session = Depends(get_db)):
    return claude_ingest_service.get_work(db, today=date.today())


@router.post("/contacts", response_model=IngestResultOut)
def upsert_contacts(
    batch: ContactsBatchIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    sync: SheetSyncScheduler = Depends(get_sheet_sync_scheduler),
):
    result = claude_ingest_service.upsert_contacts(db, batch)
    sync.schedule(background_tasks, CONTACT_TABS)
    return result


@router.post("/followups", response_model=IngestResultOut)
def apply_followups(
    batch: FollowupsBatchIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    sync: SheetSyncScheduler = Depends(get_sheet_sync_scheduler),
):
    result = claude_ingest_service.apply_followups(db, batch)
    sync.schedule(background_tasks, CONTACT_TABS)
    return result


def _finish(finisher, item_id: int, body: QueueResultIn, db: Session):
    try:
        return finisher(db, item_id, body.result_note)
    except QueueItemNotFoundError:
        raise HTTPException(status_code=404, detail="queue item not found")
    except QueueItemNotPendingError:
        raise HTTPException(status_code=409, detail="queue item not pending")


@router.post("/queue/{item_id}/complete", response_model=QueueItemOut)
def complete(item_id: int, body: QueueResultIn, db: Session = Depends(get_db)):
    return _finish(claude_ingest_service.complete_queue_item, item_id, body, db)


@router.post("/queue/{item_id}/failed", response_model=QueueItemOut)
def failed(item_id: int, body: QueueResultIn, db: Session = Depends(get_db)):
    return _finish(claude_ingest_service.fail_queue_item, item_id, body, db)
