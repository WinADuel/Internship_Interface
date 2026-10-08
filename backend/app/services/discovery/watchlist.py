"""The company watchlist (Phase 2 spec §2b; plan Task 8)."""

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.posting import Posting, PostingState
from app.models.watch_company import WatchAts, WatchCompany
from app.schemas.discovery import MAX_WATCH_NAME, WatchCompanyIn
from app.services.discovery.filters import DiscoveryFilters, inbox_clause
from app.services.discovery.parsers import clean_text, company_from_token
from app.services.discovery.urls import (
    BoardRef,
    board_careers_url,
    known_custom_site,
    parse_board_url,
)
from app.services.errors import (
    DuplicateWatchCompanyError,
    UnsupportedCareersSiteError,
    WatchCompanyNotFoundError,
)

_CUSTOM_SITE = (
    "{company} uses its own careers site, so it can't be watched. Its internships come in "
    "through the community lists, and you can paste any of its postings."
)
_NOT_A_BOARD = (
    "That careers page isn't on Greenhouse, Lever, Ashby or Workday, so it can't be watched. "
    "You can still paste individual postings from it."
)


def _default_name(ref: BoardRef) -> str:
    # Workday tokens are "<host>/<tenant>/<site>"; the tenant names the company.
    token = ref.token.split("/")[1] if ref.ats is WatchAts.WORKDAY else ref.token
    return clean_text(company_from_token(token), MAX_WATCH_NAME) or "Watched company"


def _is_watched(db: Session, ref: BoardRef) -> bool:
    # Board tokens differ only in case for the same board ("OpenAI" / "openai").
    return (
        db.scalar(
            select(WatchCompany.id).where(
                WatchCompany.ats == ref.ats,
                func.lower(WatchCompany.board_token) == ref.token.lower(),
            )
        )
        is not None
    )


def add_company(db: Session, data: WatchCompanyIn) -> WatchCompany:
    """Watch a company by its careers URL. Stores the canonical careers URL
    built from the recognized board, never the pasted string."""
    ref = parse_board_url(data.careers_url)
    if ref is None:
        company = known_custom_site(data.careers_url)
        if company is not None:
            raise UnsupportedCareersSiteError(_CUSTOM_SITE.format(company=company))
        raise UnsupportedCareersSiteError(_NOT_A_BOARD)
    if _is_watched(db, ref):
        raise DuplicateWatchCompanyError(ref.token)
    company = WatchCompany(
        name=data.name or _default_name(ref),
        ats=ref.ats,
        board_token=ref.token,
        careers_url=board_careers_url(ref),
    )
    db.add(company)
    try:
        db.commit()
    except IntegrityError:
        # Added by another request between the check and the insert.
        db.rollback()
        raise DuplicateWatchCompanyError(ref.token) from None
    return company


def list_companies(
    db: Session, filters: DiscoveryFilters
) -> list[tuple[WatchCompany, int]]:
    """Every watched company with its open matches: how many of its postings
    the Inbox shows under `filters`."""
    matches = (
        select(Posting.watch_company_id.label("company_id"), func.count().label("n"))
        .where(Posting.watch_company_id.is_not(None), inbox_clause(filters))
        .group_by(Posting.watch_company_id)
        .subquery()
    )
    rows = db.execute(
        select(WatchCompany, func.coalesce(matches.c.n, 0))
        .outerjoin(matches, matches.c.company_id == WatchCompany.id)
        .order_by(func.lower(WatchCompany.name), WatchCompany.id)
    )
    return [(company, int(n)) for company, n in rows]


def remove_company(db: Session, company_id: int) -> None:
    """Stop watching a company. Its `new` postings go with it: no scan lists
    them any more, so nothing would ever close them and they would sit in the
    Inbox forever. Saved and applied postings stay (they are the user's own
    work) and so do dismissed ones, which keep their de-duplication tombstone
    role and age out through housekeeping; their `watch_company_id` is nulled
    by the foreign key."""
    company = db.get(WatchCompany, company_id)
    if company is None:
        raise WatchCompanyNotFoundError(company_id)
    db.execute(
        delete(Posting).where(
            Posting.watch_company_id == company_id, Posting.state == PostingState.NEW
        ),
        # Drop the deleted rows from the session too, so a caller holding one
        # (the API, which just listed them) does not read a vanished row.
        execution_options={"synchronize_session": "fetch"},
    )
    db.delete(company)
    db.commit()
