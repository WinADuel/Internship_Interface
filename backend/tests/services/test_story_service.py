import pytest
from pydantic import ValidationError

from app.models.application import Application
from app.models.interview import InterviewRound
from app.schemas.story import StoryCreate, StoryUpdate
from app.services.errors import StoryNotFoundError
from app.services.interview_service import set_round_stories
from app.services.story_service import (
    archive_story,
    create_story,
    delete_story,
    get_story,
    list_stories,
    update_story,
)


def test_create_and_get_story(db_session):
    story = create_story(
        db_session,
        StoryCreate(
            title="  Shipped the parser ",
            situation="S",
            task="T",
            action="A",
            result="R",
            tags=[" Leadership", "conflict", "leadership", ""],
        ),
    )
    fetched = get_story(db_session, story.id)
    assert fetched.title == "Shipped the parser"
    assert (fetched.situation, fetched.task, fetched.action, fetched.result) == ("S", "T", "A", "R")
    assert fetched.tags == ["leadership", "conflict"]
    assert fetched.archived is False


def test_get_missing_story_raises(db_session):
    with pytest.raises(StoryNotFoundError):
        get_story(db_session, 999_999)


def test_list_orders_by_title_hides_archived_and_filters_by_tag(db_session):
    b = create_story(db_session, StoryCreate(title="beta", tags=["failure"]))
    a = create_story(db_session, StoryCreate(title="Alpha", tags=["leadership", "failure"]))
    gone = create_story(db_session, StoryCreate(title="Archived", tags=["failure"]))
    archive_story(db_session, gone.id)

    assert [s.id for s in list_stories(db_session)] == [a.id, b.id]
    assert [s.id for s in list_stories(db_session, include_archived=True)] == [a.id, gone.id, b.id]
    assert [s.id for s in list_stories(db_session, tag=" LEADERSHIP ")] == [a.id]
    assert [s.id for s in list_stories(db_session, tag="failure")] == [a.id, b.id]
    assert list_stories(db_session, tag="nope") == []

    archive_story(db_session, gone.id, archived=False)
    assert gone.archived is False


def test_update_sets_given_fields_only(db_session):
    story = create_story(db_session, StoryCreate(title="T", situation="keep", tags=["a"]))
    update_story(db_session, story.id, StoryUpdate(result="Won", tags=["B", "b"]))
    assert story.situation == "keep"
    assert story.result == "Won"
    assert story.tags == ["b"]


def test_update_missing_story_raises(db_session):
    with pytest.raises(StoryNotFoundError):
        update_story(db_session, 999_999, StoryUpdate(title="x"))


def test_delete_story_unlinks_it_from_rounds(db_session):
    application = Application(company="Acme", role_title="Intern")
    db_session.add(application)
    db_session.flush()
    interview_round = InterviewRound(application_id=application.id, checklist=[])
    db_session.add(interview_round)
    db_session.flush()
    story = create_story(db_session, StoryCreate(title="T"))
    set_round_stories(db_session, interview_round.id, [story.id])

    delete_story(db_session, story.id)
    db_session.expire_all()
    assert interview_round.stories == []
    with pytest.raises(StoryNotFoundError):
        delete_story(db_session, story.id)


@pytest.mark.parametrize(
    "fields",
    [
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 201},
        {"situation": "x" * 5_001},
        {"task": "x" * 5_001},
        {"action": "x" * 5_001},
        {"result": "x" * 5_001},
        {"tags": [f"t{i}" for i in range(16)]},
        {"tags": ["x" * 41]},
    ],
)
def test_story_caps(fields):
    with pytest.raises(ValidationError):
        StoryCreate(**{"title": "T", **fields})
    with pytest.raises(ValidationError):
        StoryUpdate(**fields)


def test_story_caps_allow_the_limits():
    StoryCreate(title="x" * 200, situation="x" * 5_000, tags=[f"{i:02d}" + "x" * 38 for i in range(15)])
    # Duplicates collapse before the count is checked.
    assert len(StoryCreate(title="T", tags=["a"] * 20).tags) == 1


@pytest.mark.parametrize("field", ["title", "tags", "archived"])
def test_update_rejects_null_for_non_nullable_fields(field):
    with pytest.raises(ValidationError):
        StoryUpdate(**{field: None})
