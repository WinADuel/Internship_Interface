"""The story bank (Phase 4 spec §3): STAR stories reused across interview
rounds. Archiving hides a story from the bank but keeps its round links."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.story import Story
from app.schemas.story import StoryCreate, StoryUpdate
from app.services.errors import StoryNotFoundError


def create_story(db: Session, data: StoryCreate) -> Story:
    story = Story(**data.model_dump())
    db.add(story)
    db.commit()
    return story


def get_story(db: Session, story_id: int) -> Story:
    story = db.get(Story, story_id)
    if story is None:
        raise StoryNotFoundError(story_id)
    return story


def list_stories(db: Session, tag: str | None = None, include_archived: bool = False) -> list[Story]:
    """By title (case-insensitive). `tag` matches a stored tag exactly after
    the same trim-and-lowercase that tags get when saved."""
    query = select(Story).order_by(func.lower(Story.title), Story.id)
    if not include_archived:
        query = query.where(Story.archived.is_(False))
    if tag is not None and tag.strip():
        query = query.where(Story.tags.contains([tag.strip().lower()]))
    return list(db.scalars(query))


def update_story(db: Session, story_id: int, data: StoryUpdate) -> Story:
    story = get_story(db, story_id)
    for name, value in data.model_dump(exclude_unset=True).items():
        setattr(story, name, value)
    db.commit()
    return story


def archive_story(db: Session, story_id: int, archived: bool = True) -> Story:
    return update_story(db, story_id, StoryUpdate(archived=archived))


def delete_story(db: Session, story_id: int) -> None:
    """Deletes the story and, by cascade, its links to rounds."""
    db.delete(get_story(db, story_id))
    db.commit()
