"""Import every model module here so a single `import app.models` registers
all tables on `Base.metadata` — used by Alembic autogeneration and by the
test harness's `Base.metadata.create_all`."""

from app.models.auth_credential import AuthCredential  # noqa: F401
from app.models.application import Application  # noqa: F401
from app.models.oauth_token import OAuthToken  # noqa: F401
from app.models.status_history import StatusHistory  # noqa: F401
