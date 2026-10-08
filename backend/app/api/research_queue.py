from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.research_queue import QueueState
from app.schemas.research_queue import QueueItemCreate, QueueItemOut
from app.services import application_service, research_queue_service
from app.services.errors import AlreadyQueuedError, ApplicationNotFoundError

router = APIRouter(
    prefix="/api/research-queue",
    tags=["research-queue"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=list[QueueItemOut])
def list_queue(state: QueueState | None = None, db: Session = Depends(get_db)):
    return research_queue_service.list_queue(db, state=state)


@router.post("", response_model=QueueItemOut, status_code=201)
def add_item(data: QueueItemCreate, db: Session = Depends(get_db)):
    return research_queue_service.enqueue_professor(db, data)


@router.post("/find-contacts/{application_id}", response_model=QueueItemOut, status_code=201)
def find_contacts(application_id: int, db: Session = Depends(get_db)):
    try:
        application = application_service.get_application(db, application_id)
        return research_queue_service.enqueue_company_contacts(db, application)
    except ApplicationNotFoundError:
        raise HTTPException(status_code=404, detail="application not found")
    except AlreadyQueuedError:
        raise HTTPException(status_code=409, detail="already queued")
