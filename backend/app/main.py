from fastapi import FastAPI

from app.api.applications import router as applications_router
from app.api.auth import router as auth_router

app = FastAPI(title="Internship Tracker API")
app.include_router(auth_router)
app.include_router(applications_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
