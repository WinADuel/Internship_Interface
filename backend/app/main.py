from fastapi import FastAPI

from app.api.applications import router as applications_router
from app.api.auth import router as auth_router
from app.api.backups import router as backups_router
from app.api.claude import router as claude_router
from app.api.contacts import router as contacts_router
from app.api.discovery import router as discovery_router
from app.api.docs import router as docs_router
from app.api.interviews import router as interviews_router
from app.api.research_queue import router as research_queue_router
from app.api.settings import router as settings_router
from app.api.stories import router as stories_router

app = FastAPI(title="Internship Tracker API")
app.include_router(auth_router)
app.include_router(applications_router)
app.include_router(docs_router)
app.include_router(contacts_router)
app.include_router(research_queue_router)
app.include_router(settings_router)
app.include_router(discovery_router)
app.include_router(claude_router)
app.include_router(backups_router)
app.include_router(interviews_router)
app.include_router(stories_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
