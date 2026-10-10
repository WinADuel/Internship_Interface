from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

# Errors never quote SQL parameters: a failed write can carry email text,
# contacts' details or tokens, and the message ends up in logs.
engine = create_engine(settings.database_url, hide_parameters=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a request-scoped DB session, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
