"""The story bank (Phase 4 spec §4). Cookie auth only."""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.schemas.story import StoryCreate, StoryOut, StoryUpdate
from app.services import story_service
from app.services.errors import StoryNotFoundError

router = APIRouter(
    prefix="/api/stories",
    tags=["stories"],
    dependencies=[Depends(get_current_user)],
)

_NOT_FOUND = HTTPException(status_code=404, detail="story not found")


@router.get("", response_model=list[StoryOut])
def list_stories(tag: str | None = None, include_archived: bool = False, db: Session = Depends(get_db)):
    return story_service.list_stories(db, tag=tag, include_archived=include_archived)


@router.post("", response_model=StoryOut, status_code=201)
def create_story(data: StoryCreate, db: Session = Depends(get_db)):
    return story_service.create_story(db, data)


@router.patch("/{story_id}", response_model=StoryOut)
def update_story(story_id: int, data: StoryUpdate, db: Session = Depends(get_db)):
    try:
        return story_service.update_story(db, story_id, data)
    except StoryNotFoundError:
        raise _NOT_FOUND


@router.delete("/{story_id}", status_code=204)
def delete_story(story_id: int, db: Session = Depends(get_db)):
    try:
        story_service.delete_story(db, story_id)
    except StoryNotFoundError:
        raise _NOT_FOUND
    return Response(status_code=204)
