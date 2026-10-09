"""The daily Claude routine's Inbox ranking step (Phase 5 spec §5).

`ranking_work` hands the routine the profile, the ranking preferences, a few
example titles and the Inbox postings worth its review; `save_scores`
stores what it sends back. Claude may write only `claude_score`,
`claude_note` and `claude_scored_at`, and only on postings still `new` or
`saved`. Notes are untrusted text: the schema cleans and caps them."""

from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.posting import Posting, PostingState
from app.schemas.claude import PostingScoresIn, ScoresResultOut
from app.services.discovery.filters import filters_from_settings, inbox_clause
from app.services.discovery.ranking import lock_scores, prefs_from_settings
from app.services.settings_service import get_settings

# Example titles of each kind sent with every run (spec §2). Applied
# postings count as positive examples together with saves.
EXAMPLES = 20
SCORABLE_STATES = (PostingState.NEW, PostingState.SAVED)
POSITIVE_STATES = (PostingState.SAVED, PostingState.APPLIED)
# How far before the first preferences change a score made with no
# preferences at all is dated, so that it reads stale.
STALE_BY = timedelta(microseconds=1)


def _examples(db: Session, *states: PostingState) -> list[str]:
    rows = db.execute(
        select(Posting.company, Posting.title)
        .where(Posting.state.in_(states))
        .order_by(Posting.state_changed_at.desc(), Posting.id.desc())
        .limit(EXAMPLES)
    )
    return [f"{company} — {title}" for company, title in rows]


def _needs_review(ranking_updated_at: datetime | None):
    """Never scored by Claude, or scored before the preferences last changed."""
    unscored = or_(Posting.claude_score.is_(None), Posting.claude_scored_at.is_(None))
    if ranking_updated_at is None:
        return unscored
    return or_(unscored, Posting.claude_scored_at < ranking_updated_at)


def ranking_work(db: Session) -> dict:
    """What the routine's ranking step reads. `postings` holds up to the
    daily limit of Inbox postings (the saved Inbox filters apply) that need
    a review, highest local score first, then newest; a limit of 0 turns
    Claude ranking off."""
    settings = get_settings(db)
    limit = settings.ranking_claude_daily_limit
    postings: list[Posting] = []
    if limit > 0:
        postings = list(
            db.scalars(
                select(Posting)
                .where(
                    inbox_clause(filters_from_settings(settings)),
                    _needs_review(settings.ranking_updated_at),
                )
                .order_by(
                    Posting.local_score.desc().nulls_last(),
                    func.coalesce(Posting.date_posted, Posting.first_seen_at).desc(),
                    Posting.id.desc(),
                )
                .limit(limit)
            )
        )
    return {
        "profile": settings.outreach_profile,
        "preferences": {k: list(v) for k, v in asdict(prefs_from_settings(settings)).items()},
        "preferences_as_of": settings.ranking_updated_at,
        "examples": {
            "saved": _examples(db, *POSITIVE_STATES),
            "dismissed": _examples(db, PostingState.DISMISSED),
        },
        "postings": postings,
    }


def _scored_at(batch: PostingScoresIn, current: datetime | None, now: datetime) -> datetime:
    """When the scores count as made. Scores the routine made from an older
    `preferences_as_of` than the current one (the user changed the
    preferences meanwhile) keep that older time, so they read stale and the
    postings are offered again. Made before any preferences existed (null),
    they count as made just before the first change."""
    if "preferences_as_of" not in batch.model_fields_set or current is None:
        return now
    as_of = batch.preferences_as_of
    if as_of is None:
        return current - STALE_BY
    return as_of if as_of < current else now


def save_scores(db: Session, batch: PostingScoresIn, now: datetime | None = None) -> ScoresResultOut:
    """Store Claude's scores. A posting that is missing, dismissed or
    applied is skipped and counted; a posting listed twice takes the last."""
    now = now or datetime.now(UTC)
    # Serialised with re-scoring (see `lock_scores`); the preferences are
    # read after the lock, so a change committed meanwhile is seen.
    lock_scores(db)
    settings = get_settings(db)
    db.refresh(settings, ["ranking_updated_at"])
    scored_at = _scored_at(batch, settings.ranking_updated_at, now)
    ids = {item.posting_id for item in batch.scores}
    rows = {p.id: p for p in db.scalars(select(Posting).where(Posting.id.in_(ids)))} if ids else {}
    updated = skipped = 0
    for item in batch.scores:
        posting = rows.get(item.posting_id)
        if posting is None or posting.state not in SCORABLE_STATES:
            skipped += 1
            continue
        posting.claude_score = item.score
        posting.claude_note = item.note or None
        posting.claude_scored_at = scored_at
        updated += 1
    db.commit()
    return ScoresResultOut(updated=updated, skipped=skipped)
