"""The scheduled Claude job's only way in (spec §13.5). Every route is
behind `get_claude_token`; nothing here accepts a session cookie."""

from fastapi import APIRouter, Depends

from app.api.deps import get_claude_token

router = APIRouter(prefix="/api/claude", tags=["claude"], dependencies=[Depends(get_claude_token)])


@router.get("/ping")
def ping() -> dict[str, bool]:
    return {"ok": True}
