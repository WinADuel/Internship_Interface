"""Import every model module here so a single `import app.models` registers
all tables on `Base.metadata` — used by Alembic autogeneration and by the
test harness's `Base.metadata.create_all`."""

from app.models.auth_credential import AuthCredential  # noqa: F401
