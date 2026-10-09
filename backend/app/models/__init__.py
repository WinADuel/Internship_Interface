"""Import every model module here so a single `import app.models` registers
all tables on `Base.metadata` — used by Alembic autogeneration and by the
test harness's `Base.metadata.create_all`."""

from app.models.auth_credential import AuthCredential  # noqa: F401
from app.models.application import Application  # noqa: F401
from app.models.oauth_token import OAuthToken  # noqa: F401
from app.models.status_history import StatusHistory  # noqa: F401
from app.models.contact import Contact  # noqa: F401
from app.models.contact_status_history import ContactStatusHistory  # noqa: F401
from app.models.research_queue import ResearchQueueItem  # noqa: F401
from app.models.app_settings import AppSettings  # noqa: F401
from app.models.claude_token import ClaudeToken  # noqa: F401
from app.models.watch_company import WatchCompany  # noqa: F401
from app.models.posting import Posting  # noqa: F401
from app.models.story import Story  # noqa: F401
from app.models.interview import InterviewRound  # noqa: F401
from app.models.prep_brief import PrepBrief  # noqa: F401
