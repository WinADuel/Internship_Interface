from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all ORM models. Models import this to register with
    `Base.metadata` for Alembic autogeneration and `create_all` in tests."""
