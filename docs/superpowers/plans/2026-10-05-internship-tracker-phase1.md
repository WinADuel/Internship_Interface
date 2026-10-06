# Internship Tracker Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a working, migration-ready internship/job application tracker: FastAPI + PostgreSQL backend, Svelte/TypeScript frontend, password+TOTP auth, kanban pipeline, a customizable dashboard, read-only Google Docs linking, and a Docker Compose deployment that runs identically on a VPS now and a local server later.

**Architecture:** Three-service Docker Compose stack (FastAPI backend, PostgreSQL, static Svelte frontend) behind a Caddy reverse proxy. Backend is layered (API routers → services → models), never putting business logic in route handlers. Frontend is organized by feature (routes, components, api clients, stores), with a draggable/resizable Gridstack.js dashboard whose layout persists per-device in `localStorage`.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, PostgreSQL 16, pyotp, PyJWT, `cryptography` (Fernet), pytest, httpx. Svelte 5 + TypeScript, Vite, svelte-spa-router, gridstack, Vitest, @testing-library/svelte. Caddy, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-10-05-internship-tracker-design.md`

## Global Constraints

- Backend: Python 3.12, FastAPI, SQLAlchemy 2.0. All schema changes go through Alembic migrations — never hand-edited DDL (spec §3).
- Database: PostgreSQL 16.
- Frontend: Svelte 5 + TypeScript, built via Vite, served as static files (no SSR/Node server at runtime).
- Auth: bcrypt password hashing + TOTP (RFC 6238, Google Authenticator-compatible) second factor; session via `access_token`/`refresh_token` cookies (httpOnly, Secure, SameSite=Lax) (spec §7).
- API error responses: structured JSON with a `detail` field and correct HTTP status codes (spec §10).
- Google OAuth: read-only scope only; refresh tokens encrypted at rest (Fernet, key from `TOKEN_ENCRYPTION_KEY` env var), never exposed to the frontend (spec §5, §8).
- Dashboard layout and per-widget content-amount settings persist in browser `localStorage`, per device — never synced via the backend (spec §6a).
- Code organization: API routers are thin and delegate to services; models/schemas/services live in separate files; no file may accumulate multiple responsibilities — split when it does (spec §4).
- Everything ships as a Docker Compose stack portable unchanged from the VPS to a future local server (spec §2, §11).

## Review Focus

- Any request to a protected endpoint with no/invalid/expired session cookie must return 401 with a structured JSON body, not a crash or silent pass-through — pinned to Task 6.
- A status-change request with an unknown/invalid status value must be rejected (422, Pydantic enum validation) without mutating the application or writing a history row — pinned to Task 5.
- A status-change request whose new status equals the current status must not write a duplicate `status_history` row — pinned to Task 5.
- Archived applications must be excluded from the default application list, kanban board, and dashboard bucket preview unless explicitly requested — pinned to Task 5 (backend default) and Task 15 (frontend widget).
- A Google Doc fetch failure (no token connected, expired/revoked token, deleted/inaccessible doc) must degrade gracefully — a 502 with a structured error from the backend, and a fallback "open in Google Docs" link in the UI, never an unhandled crash — pinned to Task 8 (backend) and Task 12 (frontend).

---

## Task 1: Backend Project Scaffolding & Test Harness

**Files:**
- Create: `backend/app/__init__.py`, `backend/app/main.py`
- Create: `backend/app/core/config.py`
- Create: `backend/app/db/base.py`, `backend/app/db/session.py`
- Create: `backend/requirements.txt`
- Create: `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/versions/.gitkeep`
- Create: `backend/tests/conftest.py`
- Test: `backend/tests/test_health.py`

**Interfaces:**
- Produces: `Settings` class (`app/core/config.py`) read from env (`database_url`, `jwt_secret`, `token_encryption_key`, `google_client_id`, `google_client_secret`, `google_redirect_uri`, `access_token_expire_minutes=30`, `refresh_token_expire_days=14`), instantiated as `settings`. `Base` (SQLAlchemy `DeclarativeBase`) in `app/db/base.py`. `engine`, `SessionLocal`, `get_db() -> Generator[Session, None, None]` in `app/db/session.py`. `app` (FastAPI instance) in `app/main.py` with `GET /api/health -> {"status": "ok"}`.
- Test harness: `conftest.py` provides a `db_session` fixture — session-scoped engine bound to `TEST_DATABASE_URL`, creates all tables once via `Base.metadata.create_all`, and a function-scoped fixture that opens a connection + transaction, binds a `Session` to it, yields it, then rolls back. Also provides a `client` fixture (FastAPI `TestClient`) with the `get_db` dependency overridden to use the test session.

- [ ] **Step 1: Write `requirements.txt`** with: `fastapi`, `uvicorn[standard]`, `sqlalchemy`, `psycopg[binary]`, `alembic`, `pydantic`, `pydantic-settings`, `passlib[bcrypt]`, `pyotp`, `qrcode[pil]`, `pyjwt`, `cryptography`, `httpx`, `pytest`, `pytest-cov`.

- [ ] **Step 2: Write the failing test** `backend/tests/test_health.py`:

```python
def test_health_returns_ok(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 3: Run test to verify it fails** — `pytest backend/tests/test_health.py -v` — expected: collection error (no `app`, no `client` fixture).

- [ ] **Step 4: Implement `config.py`, `db/base.py`, `db/session.py`, `conftest.py`, and `main.py`** per the Interfaces block above. `conftest.py` reads `TEST_DATABASE_URL` from env (document it in a `backend/.env.example`).

- [ ] **Step 5: Run test to verify it passes** — `pytest backend/tests/test_health.py -v` — expected: PASS.

- [ ] **Step 6: Initialize Alembic** (`alembic init alembic` adjusted to the `backend/` layout, `env.py` wired to `Settings().database_url` and `Base.metadata`).

- [ ] **Step 7: Commit.**

```bash
git add backend/
git commit -m "feat: backend scaffolding, config, db session, test harness, health check"
```

---

## Task 2: Auth Data Model & Security Helpers

**Files:**
- Create: `backend/app/models/auth_credential.py`
- Create: `backend/app/core/security.py`
- Create: `backend/alembic/versions/0001_auth_credentials.py` (via `alembic revision`)
- Test: `backend/tests/core/test_security.py`

**Interfaces:**
- Consumes: `Base` (Task 1).
- Produces: `AuthCredential` model (`id`, `username: str unique`, `password_hash: str`, `totp_secret_encrypted: bytes | None`, `totp_confirmed: bool default False`). Security helpers in `app/core/security.py`:
  - `hash_password(password: str) -> str`
  - `verify_password(password: str, password_hash: str) -> bool`
  - `generate_totp_secret() -> str`
  - `totp_provisioning_uri(secret: str, username: str, issuer: str = "InternHelper") -> str`
  - `verify_totp_code(secret: str, code: str) -> bool`
  - `encrypt_value(plaintext: str) -> bytes`
  - `decrypt_value(ciphertext: bytes) -> str`
  - `create_access_token(subject: str) -> str`
  - `create_refresh_token(subject: str) -> str`
  - `decode_token(token: str) -> dict` (raises `jwt.PyJWTError` on invalid/expired)

- [ ] **Step 1: Write the failing tests** `backend/tests/core/test_security.py`:

```python
def test_password_hash_roundtrip():
    hashed = hash_password("correct-horse")
    assert hashed != "correct-horse"
    assert verify_password("correct-horse", hashed)
    assert not verify_password("wrong", hashed)

def test_totp_roundtrip():
    secret = generate_totp_secret()
    code = pyotp.TOTP(secret).now()
    assert verify_totp_code(secret, code)
    assert not verify_totp_code(secret, "000000")

def test_encrypt_decrypt_roundtrip():
    ciphertext = encrypt_value("my-refresh-token")
    assert ciphertext != b"my-refresh-token"
    assert decrypt_value(ciphertext) == "my-refresh-token"

def test_access_token_roundtrip():
    token = create_access_token(subject="1")
    payload = decode_token(token)
    assert payload["sub"] == "1"

def test_decode_token_rejects_garbage():
    with pytest.raises(jwt.PyJWTError):
        decode_token("not-a-real-token")
```

- [ ] **Step 2: Run tests to verify they fail** — `pytest backend/tests/core/test_security.py -v` — expected: FAIL (module not found).

- [ ] **Step 3: Implement `AuthCredential` model and `app/core/security.py`.** Use `passlib.hash.bcrypt` for password hashing, `pyotp` for TOTP, `cryptography.fernet.Fernet(settings.token_encryption_key)` for encrypt/decrypt, `pyjwt` with `settings.jwt_secret` (HS256) for tokens — access tokens expire after `settings.access_token_expire_minutes`, refresh tokens after `settings.refresh_token_expire_days`; encode a `type` claim (`"access"`/`"refresh"`) alongside `sub` so the two can't be swapped.

- [ ] **Step 4: Run tests to verify they pass** — expected: PASS.

- [ ] **Step 5: Generate and apply the Alembic migration** for `auth_credentials` (`alembic revision --autogenerate -m "auth credentials"`, review the generated file, `alembic upgrade head` against the test DB).

- [ ] **Step 6: Commit.**

```bash
git add backend/app/models/auth_credential.py backend/app/core/security.py backend/alembic/versions/ backend/tests/core/test_security.py
git commit -m "feat: auth credential model and security helpers (hashing, TOTP, JWT, encryption)"
```

---

## Task 3: Auth Service, API Routes & `get_current_user` Dependency

**Files:**
- Create: `backend/app/services/errors.py`
- Create: `backend/app/services/auth_service.py`
- Create: `backend/app/api/deps.py`
- Create: `backend/app/api/auth.py`
- Modify: `backend/app/main.py` (register the auth router)
- Test: `backend/tests/services/test_auth_service.py`
- Test: `backend/tests/api/test_auth_routes.py`

**Interfaces:**
- Consumes: `AuthCredential` model, `security.py` helpers (Task 2).
- Produces:
  - `app/services/errors.py`: `InvalidCredentialsError`, `TotpAlreadyConfirmedError`, `InvalidTotpCodeError` (all `Exception` subclasses).
  - `auth_service.py`: `authenticate(db: Session, username: str, password: str, totp_code: str) -> None` (raises `InvalidCredentialsError` on any failure — wrong username, wrong password, or wrong/missing TOTP code when confirmed); `begin_totp_setup(db: Session) -> tuple[str, str]` returns `(secret, provisioning_uri)`, raises `TotpAlreadyConfirmedError` if `totp_confirmed` is already `True`; `confirm_totp_setup(db: Session, code: str) -> None` raises `InvalidTotpCodeError` on mismatch, else sets `totp_confirmed = True`.
  - `app/api/deps.py`: `get_current_user(request: Request, db: Session = Depends(get_db)) -> AuthCredential` — reads the `access_token` cookie, calls `decode_token`, raises `HTTPException(401, detail="not authenticated")` if the cookie is missing or the token is invalid/expired/wrong `type`.
  - `app/api/auth.py` routes, all returning structured JSON:
    - `POST /api/auth/login` body `{username, password, totp_code}` → 200, sets `access_token`/`refresh_token` cookies, body `{"detail": "ok"}`; 401 `{"detail": "invalid credentials"}` on `InvalidCredentialsError`.
    - `POST /api/auth/totp/setup` → 200 `{"provisioning_uri": str}`; 409 `{"detail": "totp already confirmed"}`.
    - `POST /api/auth/totp/confirm` body `{code}` → 200 `{"detail": "confirmed"}`; 400 `{"detail": "invalid code"}`.
    - `POST /api/auth/refresh` → 200, rotates the `access_token` cookie; 401 if the refresh cookie is missing/invalid.
    - `POST /api/auth/logout` → 200, clears both cookies.

- [ ] **Step 1: Write the failing service tests** `backend/tests/services/test_auth_service.py` (seed a single `AuthCredential` row per test via the `db_session` fixture):

```python
def test_authenticate_succeeds_with_correct_credentials(db_session, seeded_credential):
    authenticate(db_session, "dxwu", "correct-horse", seeded_credential.current_totp_code())

def test_authenticate_rejects_wrong_password(db_session, seeded_credential):
    with pytest.raises(InvalidCredentialsError):
        authenticate(db_session, "dxwu", "wrong", seeded_credential.current_totp_code())

def test_authenticate_rejects_wrong_totp(db_session, seeded_credential):
    with pytest.raises(InvalidCredentialsError):
        authenticate(db_session, "dxwu", "correct-horse", "000000")

def test_begin_totp_setup_rejects_when_already_confirmed(db_session, seeded_credential_confirmed):
    with pytest.raises(TotpAlreadyConfirmedError):
        begin_totp_setup(db_session)

def test_confirm_totp_setup_rejects_wrong_code(db_session, seeded_credential_unconfirmed):
    with pytest.raises(InvalidTotpCodeError):
        confirm_totp_setup(db_session, "000000")
```

(Add a small `seeded_credential`/`seeded_credential_confirmed`/`seeded_credential_unconfirmed` fixture in a local `conftest.py` under `tests/services/`, each inserting an `AuthCredential` row with a known password/secret via the Task 2 helpers, exposing a `.current_totp_code()` convenience using `pyotp`.)

- [ ] **Step 2: Run tests to verify they fail** — expected: FAIL (module not found).

- [ ] **Step 3: Implement `errors.py` and `auth_service.py`.**

- [ ] **Step 4: Run tests to verify they pass.**

- [ ] **Step 5: Write the failing API tests** `backend/tests/api/test_auth_routes.py`:

```python
def test_login_sets_cookies_on_success(client, seeded_credential):
    response = client.post("/api/auth/login", json={
        "username": "dxwu", "password": "correct-horse",
        "totp_code": seeded_credential.current_totp_code(),
    })
    assert response.status_code == 200
    assert "access_token" in response.cookies
    assert "refresh_token" in response.cookies

def test_login_rejects_bad_password(client, seeded_credential):
    response = client.post("/api/auth/login", json={
        "username": "dxwu", "password": "wrong", "totp_code": "000000",
    })
    assert response.status_code == 401
    assert response.json() == {"detail": "invalid credentials"}

def test_logout_clears_cookies(client, logged_in_client):
    response = logged_in_client.post("/api/auth/logout")
    assert response.status_code == 200
    assert response.cookies.get("access_token") in (None, "")
```

- [ ] **Step 6: Run tests to verify they fail.**

- [ ] **Step 7: Implement `app/api/deps.py` and `app/api/auth.py`; register the router in `main.py`.**

- [ ] **Step 8: Run tests to verify they pass.**

- [ ] **Step 9: Commit.**

```bash
git add backend/app/services/errors.py backend/app/services/auth_service.py backend/app/api/deps.py backend/app/api/auth.py backend/app/main.py backend/tests/services/test_auth_service.py backend/tests/api/test_auth_routes.py
git commit -m "feat: auth service, login/totp/refresh/logout routes, get_current_user dependency"
```

---

## Task 4: Application, StatusHistory & OAuthToken Models + Migration

**Files:**
- Create: `backend/app/models/application.py`
- Create: `backend/app/models/status_history.py`
- Create: `backend/app/models/oauth_token.py`
- Create: `backend/alembic/versions/0002_applications.py`
- Test: `backend/tests/models/test_application_models.py`

**Interfaces:**
- Consumes: `Base` (Task 1).
- Produces:
  - `application.py`: `ApplicationStatus(str, Enum)` = `WISHLIST="wishlist"`, `APPLIED="applied"`, `PHONE_SCREEN="phone_screen"`, `INTERVIEW="interview"`, `OFFER="offer"`, `REJECTED="rejected"`; `Priority(str, Enum)` = `LOW="low"`, `MEDIUM="medium"`, `HIGH="high"`; `Application` model with exactly the columns listed in spec §3 (`company`, `role_title`, `date_applied`, `status`, `job_link`, `notes`, `resume_version`, `contact_person`, `salary_range`, `location`, `source`, `priority`, `follow_up_date`, `interview_datetime`, `google_doc_link`, `archived` default `False`, `created_at`, `updated_at`).
  - `status_history.py`: `StatusHistory` model (`application_id` FK → `applications.id`, `old_status: ApplicationStatus | None`, `new_status: ApplicationStatus`, `changed_at`).
  - `oauth_token.py`: `OAuthToken` model (`provider: str`, `encrypted_refresh_token: bytes`, `scopes: str`, `created_at`, `updated_at`).

- [ ] **Step 1: Write the failing test** `backend/tests/models/test_application_models.py`:

```python
def test_create_application_defaults(db_session):
    app = Application(company="Stripe", role_title="SWE Intern")
    db_session.add(app)
    db_session.flush()
    assert app.status == ApplicationStatus.WISHLIST
    assert app.priority == Priority.MEDIUM
    assert app.archived is False

def test_status_history_links_to_application(db_session):
    app = Application(company="Stripe", role_title="SWE Intern")
    db_session.add(app)
    db_session.flush()
    history = StatusHistory(application_id=app.id, old_status=None, new_status=ApplicationStatus.WISHLIST)
    db_session.add(history)
    db_session.flush()
    assert history.application_id == app.id
```

- [ ] **Step 2: Run test to verify it fails.**

- [ ] **Step 3: Implement the three model files.**

- [ ] **Step 4: Run test to verify it passes.**

- [ ] **Step 5: Generate and review the Alembic migration** for `applications`, `status_history`, `oauth_tokens`; apply it against the test DB.

- [ ] **Step 6: Commit.**

```bash
git add backend/app/models/application.py backend/app/models/status_history.py backend/app/models/oauth_token.py backend/alembic/versions/ backend/tests/models/test_application_models.py
git commit -m "feat: application, status history, and oauth token models + migration"
```

---

## Task 5: Application Service (CRUD, Status Changes, Archiving, Activity)

**Files:**
- Create: `backend/app/schemas/application.py`
- Create: `backend/app/services/application_service.py`
- Modify: `backend/app/services/errors.py` (add `ApplicationNotFoundError`)
- Test: `backend/tests/services/test_application_service.py`

**Interfaces:**
- Consumes: `Application`, `StatusHistory` models (Task 4).
- Produces:
  - `schemas/application.py`: `ApplicationCreate`, `ApplicationUpdate` (all fields optional), `ApplicationOut` (adds `id`, `archived`, `created_at`, `updated_at`, `model_config = ConfigDict(from_attributes=True)`), `StatusHistoryOut` (`old_status`, `new_status`, `changed_at`), `ActivityEntryOut` (`application_id`, `company`, `role_title`, `old_status`, `new_status`, `changed_at`).
  - `application_service.py`:
    - `create_application(db: Session, data: ApplicationCreate) -> Application`
    - `get_application(db: Session, application_id: int) -> Application` (raises `ApplicationNotFoundError`)
    - `list_applications(db: Session, include_archived: bool = False) -> list[Application]`
    - `update_application(db: Session, application_id: int, data: ApplicationUpdate) -> Application`
    - `change_status(db: Session, application_id: int, new_status: ApplicationStatus) -> Application` — if `new_status == application.status`, return the application unchanged with **no** `StatusHistory` row written; otherwise update `status` and insert a `StatusHistory` row.
    - `archive_application(db: Session, application_id: int) -> Application` — sets `archived = True`.
    - `get_status_history(db: Session, application_id: int) -> list[StatusHistory]`
    - `get_recent_activity(db: Session, limit: int = 10) -> list[dict]` — joins `StatusHistory` + `Application`, ordered by `changed_at` descending, shaped to match `ActivityEntryOut`.

- [ ] **Step 1: Write the failing tests** `backend/tests/services/test_application_service.py`:

```python
def test_create_and_get_application(db_session):
    app = create_application(db_session, ApplicationCreate(company="Stripe", role_title="SWE Intern"))
    fetched = get_application(db_session, app.id)
    assert fetched.company == "Stripe"

def test_get_application_raises_when_missing(db_session):
    with pytest.raises(ApplicationNotFoundError):
        get_application(db_session, 999)

def test_list_applications_excludes_archived_by_default(db_session):
    active = create_application(db_session, ApplicationCreate(company="A", role_title="R"))
    archived = create_application(db_session, ApplicationCreate(company="B", role_title="R"))
    archive_application(db_session, archived.id)
    results = list_applications(db_session)
    assert [a.id for a in results] == [active.id]
    assert len(list_applications(db_session, include_archived=True)) == 2

def test_change_status_writes_history_row(db_session):
    app = create_application(db_session, ApplicationCreate(company="A", role_title="R"))
    change_status(db_session, app.id, ApplicationStatus.APPLIED)
    history = get_status_history(db_session, app.id)
    assert len(history) == 1
    assert history[0].new_status == ApplicationStatus.APPLIED

def test_change_status_to_same_status_is_a_noop(db_session):
    app = create_application(db_session, ApplicationCreate(company="A", role_title="R"))
    change_status(db_session, app.id, ApplicationStatus.WISHLIST)  # already wishlist
    assert get_status_history(db_session, app.id) == []

def test_get_recent_activity_orders_newest_first(db_session):
    app = create_application(db_session, ApplicationCreate(company="A", role_title="R"))
    change_status(db_session, app.id, ApplicationStatus.APPLIED)
    change_status(db_session, app.id, ApplicationStatus.PHONE_SCREEN)
    activity = get_recent_activity(db_session, limit=10)
    assert [a["new_status"] for a in activity[:2]] == [ApplicationStatus.PHONE_SCREEN, ApplicationStatus.APPLIED]
```

- [ ] **Step 2: Run tests to verify they fail.**

- [ ] **Step 3: Implement `schemas/application.py`, `application_service.py`, and add `ApplicationNotFoundError` to `errors.py`.**

- [ ] **Step 4: Run tests to verify they pass.**

- [ ] **Step 5: Commit.**

```bash
git add backend/app/schemas/application.py backend/app/services/application_service.py backend/app/services/errors.py backend/tests/services/test_application_service.py
git commit -m "feat: application service — CRUD, status-change history, archiving, recent activity"
```

---

## Task 6: Applications API Routes

**Files:**
- Create: `backend/app/api/applications.py`
- Modify: `backend/app/main.py` (register the applications router)
- Test: `backend/tests/api/test_application_routes.py`

**Interfaces:**
- Consumes: `application_service.py` (Task 5), `get_current_user` (Task 3).
- Produces, all protected by `Depends(get_current_user)`:
  - `GET /api/applications?include_archived=false` → 200 `list[ApplicationOut]`
  - `POST /api/applications` → 201 `ApplicationOut`
  - `GET /api/applications/{id}` → 200 `ApplicationOut`; 404 `{"detail": "application not found"}`
  - `PATCH /api/applications/{id}` → 200 `ApplicationOut`
  - `POST /api/applications/{id}/status` body `{"new_status": ApplicationStatus}` → 200 `ApplicationOut`; 422 on invalid enum value
  - `POST /api/applications/{id}/archive` → 200 `ApplicationOut`
  - `GET /api/applications/{id}/history` → 200 `list[StatusHistoryOut]`
  - `GET /api/applications/activity?limit=10` → 200 `list[ActivityEntryOut]`

- [ ] **Step 1: Write the failing tests** `backend/tests/api/test_application_routes.py`:

```python
def test_list_applications_requires_auth(client):
    response = client.get("/api/applications")
    assert response.status_code == 401

def test_create_and_list_application(logged_in_client):
    create_resp = logged_in_client.post("/api/applications", json={"company": "Stripe", "role_title": "SWE Intern"})
    assert create_resp.status_code == 201
    list_resp = logged_in_client.get("/api/applications")
    assert any(a["company"] == "Stripe" for a in list_resp.json())

def test_get_missing_application_returns_404(logged_in_client):
    response = logged_in_client.get("/api/applications/999")
    assert response.status_code == 404
    assert response.json() == {"detail": "application not found"}

def test_status_change_rejects_invalid_value(logged_in_client):
    created = logged_in_client.post("/api/applications", json={"company": "A", "role_title": "R"}).json()
    response = logged_in_client.post(f"/api/applications/{created['id']}/status", json={"new_status": "not-a-status"})
    assert response.status_code == 422

def test_archived_application_excluded_from_default_list(logged_in_client):
    created = logged_in_client.post("/api/applications", json={"company": "A", "role_title": "R"}).json()
    logged_in_client.post(f"/api/applications/{created['id']}/archive")
    response = logged_in_client.get("/api/applications")
    assert created["id"] not in [a["id"] for a in response.json()]
```

(Add a `logged_in_client` fixture to `tests/api/conftest.py` that seeds an `AuthCredential`, logs in via `POST /api/auth/login`, and reuses the resulting cookies on an `httpx`/`TestClient` instance.)

- [ ] **Step 2: Run tests to verify they fail.**

- [ ] **Step 3: Implement `app/api/applications.py`; map `ApplicationNotFoundError` to a 404 JSON response (e.g. via an exception handler or explicit `try/except` in each route); register the router in `main.py`.**

- [ ] **Step 4: Run tests to verify they pass.**

- [ ] **Step 5: Commit.**

```bash
git add backend/app/api/applications.py backend/app/main.py backend/tests/api/test_application_routes.py backend/tests/api/conftest.py
git commit -m "feat: applications API routes (CRUD, status change, archive, activity feed)"
```

---

## Task 7: Google OAuth Flow (Service & Routes)

**Files:**
- Create: `backend/app/services/google_docs_service.py` (OAuth portion only)
- Modify: `backend/app/services/errors.py` (add `GoogleAuthError`)
- Create: `backend/app/api/docs.py` (OAuth routes only)
- Modify: `backend/app/main.py` (register the docs router)
- Test: `backend/tests/services/test_google_oauth.py`
- Test: `backend/tests/api/test_docs_oauth_routes.py`

**Interfaces:**
- Consumes: `OAuthToken` model (Task 4), `encrypt_value`/`decrypt_value` (Task 2), `get_current_user` (Task 3), `settings.google_client_id/secret/redirect_uri` (Task 1).
- Produces:
  - `get_authorization_url(state: str) -> str`
  - `exchange_code_for_token(code: str) -> dict` — POSTs to Google's token endpoint via `httpx.post` (patched in tests), returns `{"refresh_token": str, "access_token": str, "expires_in": int}`
  - `store_token(db: Session, token_response: dict, scopes: str) -> None` — encrypts `refresh_token`, upserts the single `OAuthToken(provider="google")` row
  - `get_valid_access_token(db: Session) -> str` — raises `GoogleAuthError` if no row exists or the refresh call fails
  - `GET /api/docs/google/authorize` (protected) → 302 redirect to the URL from `get_authorization_url`
  - `GET /api/docs/google/callback?code=&state=` (protected) → exchanges the code, stores the token, 302 redirect to `/essays?connected=1`

- [ ] **Step 1: Write the failing service tests** `backend/tests/services/test_google_oauth.py`, patching `httpx.post`:

```python
def test_exchange_code_for_token_calls_google_and_returns_tokens(monkeypatch):
    monkeypatch.setattr(httpx, "post", fake_post_returning({"refresh_token": "rt", "access_token": "at", "expires_in": 3600}))
    result = exchange_code_for_token("some-code")
    assert result["refresh_token"] == "rt"

def test_store_token_encrypts_refresh_token(db_session):
    store_token(db_session, {"refresh_token": "rt", "access_token": "at", "expires_in": 3600}, scopes="drive.readonly")
    row = db_session.query(OAuthToken).filter_by(provider="google").one()
    assert row.encrypted_refresh_token != b"rt"
    assert decrypt_value(row.encrypted_refresh_token) == "rt"

def test_get_valid_access_token_raises_when_not_connected(db_session):
    with pytest.raises(GoogleAuthError):
        get_valid_access_token(db_session)
```

- [ ] **Step 2: Run tests to verify they fail.**

- [ ] **Step 3: Implement the OAuth portion of `google_docs_service.py` and add `GoogleAuthError` to `errors.py`.**

- [ ] **Step 4: Run tests to verify they pass.**

- [ ] **Step 5: Write the failing route tests** `backend/tests/api/test_docs_oauth_routes.py`:

```python
def test_authorize_requires_auth(client):
    response = client.get("/api/docs/google/authorize", follow_redirects=False)
    assert response.status_code == 401

def test_authorize_redirects_to_google(logged_in_client):
    response = logged_in_client.get("/api/docs/google/authorize", follow_redirects=False)
    assert response.status_code == 302
    assert "accounts.google.com" in response.headers["location"]

def test_callback_stores_token_and_redirects(logged_in_client, monkeypatch):
    monkeypatch.setattr(httpx, "post", fake_post_returning({"refresh_token": "rt", "access_token": "at", "expires_in": 3600}))
    response = logged_in_client.get("/api/docs/google/callback?code=abc&state=xyz", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/essays?connected=1"
```

- [ ] **Step 6: Run tests to verify they fail.**

- [ ] **Step 7: Implement the OAuth routes in `app/api/docs.py`; register the router in `main.py`.**

- [ ] **Step 8: Run tests to verify they pass.**

- [ ] **Step 9: Commit.**

```bash
git add backend/app/services/google_docs_service.py backend/app/services/errors.py backend/app/api/docs.py backend/app/main.py backend/tests/services/test_google_oauth.py backend/tests/api/test_docs_oauth_routes.py
git commit -m "feat: google oauth authorize/callback flow with encrypted token storage"
```

---

## Task 8: Google Docs Content Fetch (Service & Route)

**Files:**
- Modify: `backend/app/services/google_docs_service.py` (add content-fetch portion)
- Modify: `backend/app/services/errors.py` (add `GoogleDocsFetchError`, `GoogleNotConnectedError`)
- Modify: `backend/app/api/docs.py` (add content route)
- Test: `backend/tests/services/test_google_docs_fetch.py`
- Test: `backend/tests/api/test_docs_content_route.py`

**Interfaces:**
- Consumes: `get_valid_access_token` (Task 7).
- Produces:
  - `extract_doc_id(doc_ref: str) -> str` — accepts either a bare Drive file ID or a full `https://docs.google.com/document/d/<id>/...` URL and returns the bare ID in both cases.
  - `fetch_doc_text(db: Session, doc_ref: str) -> str` — raises `GoogleNotConnectedError` if no token is stored, `GoogleDocsFetchError` on any Docs API failure (non-2xx response, network error).
  - `GET /api/docs/content?doc_ref=<id-or-url>` (protected) → 200 `{"content": str}`; 502 `{"detail": "couldn't load doc"}` on `GoogleDocsFetchError`/`GoogleNotConnectedError`.

- [ ] **Step 1: Write the failing service tests** `backend/tests/services/test_google_docs_fetch.py`:

```python
@pytest.mark.parametrize("doc_ref,expected_id", [
    ("abc123", "abc123"),
    ("https://docs.google.com/document/d/abc123/edit", "abc123"),
])
def test_extract_doc_id_normalizes_both_forms(doc_ref, expected_id):
    assert extract_doc_id(doc_ref) == expected_id

def test_fetch_doc_text_raises_when_not_connected(db_session):
    with pytest.raises(GoogleNotConnectedError):
        fetch_doc_text(db_session, "abc123")

def test_fetch_doc_text_raises_on_api_failure(db_session, connected_token, monkeypatch):
    monkeypatch.setattr(httpx, "get", fake_get_returning_status(404))
    with pytest.raises(GoogleDocsFetchError):
        fetch_doc_text(db_session, "abc123")
```

- [ ] **Step 2: Run tests to verify they fail.**

- [ ] **Step 3: Implement the content-fetch portion of `google_docs_service.py` and the two new error classes.**

- [ ] **Step 4: Run tests to verify they pass.**

- [ ] **Step 5: Write the failing route test** `backend/tests/api/test_docs_content_route.py` (this is the task that owns the Review Focus item on graceful Google Doc failure degradation):

```python
def test_content_route_returns_502_with_detail_when_fetch_fails(logged_in_client, monkeypatch):
    monkeypatch.setattr(httpx, "get", fake_get_returning_status(404))
    response = logged_in_client.get("/api/docs/content", params={"doc_ref": "abc123"})
    assert response.status_code == 502
    assert response.json() == {"detail": "couldn't load doc"}

def test_content_route_returns_content_on_success(logged_in_client, connected_token, monkeypatch):
    monkeypatch.setattr(httpx, "get", fake_get_returning_json({"body": {"content": [...]}}))
    response = logged_in_client.get("/api/docs/content", params={"doc_ref": "abc123"})
    assert response.status_code == 200
    assert "content" in response.json()
```

- [ ] **Step 6: Run test to verify it fails.**

- [ ] **Step 7: Implement the content route in `app/api/docs.py`.**

- [ ] **Step 8: Run test to verify it passes.**

- [ ] **Step 9: Commit.**

```bash
git add backend/app/services/google_docs_service.py backend/app/services/errors.py backend/app/api/docs.py backend/tests/services/test_google_docs_fetch.py backend/tests/api/test_docs_content_route.py
git commit -m "feat: google docs content fetch with doc-ref normalization and graceful failure"
```

---

## Task 9: Frontend Scaffolding, Router, API Client & Login Page

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/index.html`
- Create: `frontend/src/App.svelte`, `frontend/src/main.ts`
- Create: `frontend/src/lib/api/client.ts`
- Create: `frontend/src/lib/stores/session.ts`
- Create: `frontend/src/lib/stores/toast.ts`
- Create: `frontend/src/lib/components/Toast.svelte`
- Create: `frontend/src/lib/components/NavSidebar.svelte`
- Create: `frontend/src/routes/Login.svelte`
- Test: `frontend/src/lib/api/client.test.ts`
- Test: `frontend/src/lib/stores/toast.test.ts`
- Test: `frontend/src/routes/Login.test.ts`

**Interfaces:**
- Produces:
  - `frontend/src/lib/api/client.ts`: `class ApiError extends Error { status: number; detail: unknown }`; `async function apiFetch<T>(path: string, options?: RequestInit): Promise<T>` — always sets `credentials: "include"`; throws `ApiError` on non-2xx responses, parsing the JSON body for `detail`.
  - `frontend/src/lib/stores/toast.ts`: `interface ToastMessage { id: number; text: string; kind: "error" | "info" }`; `export const toasts = writable<ToastMessage[]>([])`; `export function showToast(text: string, kind: ToastMessage["kind"] = "error"): void` (appends a message with an incrementing id, auto-removes it after 5s); `export function dismissToast(id: number): void`. This is the app-wide mechanism for surfacing failures (spec §10) — later tasks call `showToast` on a caught `ApiError` instead of failing silently.
  - `frontend/src/lib/components/Toast.svelte` — renders `$toasts`, each dismissible by clicking it or calling `dismissToast`.
  - `frontend/src/lib/components/NavSidebar.svelte` — links to `/` (Dashboard), `/applications` (Applications), `/essays` (Essays); plus three visibly-present but disabled (non-clickable, muted-style) entries labeled "Job Discovery," "Interview Prep," and "Email Sync," each marked "Coming soon" (spec §6) so the nav doesn't need restructuring when those phases land.
  - `frontend/src/lib/stores/session.ts`: `export const session = writable<{ loggedIn: boolean }>({ loggedIn: false })`; `export async function login(username: string, password: string, totpCode: string): Promise<void>` — POSTs `/api/auth/login` via `apiFetch`, sets `session.set({ loggedIn: true })` on success, lets `ApiError` propagate on failure; `export async function logout(): Promise<void>`.
  - `frontend/src/routes/Login.svelte` — username/password/TOTP-code fields, calls `login()`, navigates to `/` via `svelte-spa-router`'s `push` on success, shows the `ApiError`'s message inline on failure (a login failure is shown inline, right next to the field — the global toast mechanism is for failures during normal app use, after the user is already past this form).
  - `frontend/src/App.svelte` wires up `svelte-spa-router` with routes `/` → `Dashboard` (stub for now), `/login` → `Login`, `/applications` → stub, `/essays` → stub; renders `NavSidebar` and `Toast` alongside the active route.

- [ ] **Step 0: Write the failing test** `frontend/src/lib/stores/toast.test.ts`:

```ts
it("showToast appends a message that dismissToast removes", () => {
  showToast("something failed");
  const [message] = get(toasts);
  expect(message.text).toBe("something failed");
  expect(message.kind).toBe("error");
  dismissToast(message.id);
  expect(get(toasts)).toEqual([]);
});
```

Run it to verify it fails, implement `toast.ts`, run it to verify it passes — fold this in before Step 1 below.

- [ ] **Step 1: Scaffold the Vite+Svelte+TS project** (`npm create vite@latest frontend -- --template svelte-ts`), add `svelte-spa-router`, `gridstack`, `vitest`, `@testing-library/svelte`, `jsdom` as dependencies, configure `vite.config.ts`'s `test` block for `jsdom`.

- [ ] **Step 2: Write the failing test** `frontend/src/lib/api/client.test.ts`:

```ts
import { describe, it, expect, vi } from "vitest";
import { apiFetch, ApiError } from "./client";

describe("apiFetch", () => {
  it("throws ApiError with status and detail on non-2xx", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false, status: 401, json: async () => ({ detail: "invalid credentials" }),
    });
    await expect(apiFetch("/api/auth/login")).rejects.toMatchObject({
      status: 401, detail: "invalid credentials",
    });
  });

  it("returns parsed JSON on success", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true }) });
    const result = await apiFetch("/api/health");
    expect(result).toEqual({ ok: true });
  });
});
```

- [ ] **Step 3: Run test to verify it fails.**

- [ ] **Step 4: Implement `lib/api/client.ts`.**

- [ ] **Step 5: Run test to verify it passes.**

- [ ] **Step 6: Write the failing test** `frontend/src/routes/Login.test.ts` (using `@testing-library/svelte`):

```ts
it("shows an error message when login fails", async () => {
  vi.spyOn(sessionModule, "login").mockRejectedValue(new ApiError(401, "invalid credentials"));
  const { getByLabelText, getByText, findByText } = render(Login);
  await fireEvent.input(getByLabelText("Username"), { target: { value: "dxwu" } });
  await fireEvent.input(getByLabelText("Password"), { target: { value: "wrong" } });
  await fireEvent.input(getByLabelText("Authenticator code"), { target: { value: "000000" } });
  await fireEvent.click(getByText("Log in"));
  expect(await findByText("invalid credentials")).toBeInTheDocument();
});
```

- [ ] **Step 7: Run test to verify it fails.**

- [ ] **Step 8: Implement `routes/Login.svelte`, `lib/stores/session.ts`, `lib/components/NavSidebar.svelte`, `lib/components/Toast.svelte`, and `App.svelte`'s routing/layout** (rendering `NavSidebar` and `Toast` around the active route).

- [ ] **Step 9: Run test to verify it passes.**

- [ ] **Step 10: Commit.**

```bash
git add frontend/
git commit -m "feat: frontend scaffolding, router, api client, nav sidebar, toasts, login page"
```

---

## Task 10: Applications API Client, Types & Store

**Files:**
- Create: `frontend/src/lib/types/application.ts`
- Create: `frontend/src/lib/api/applications.ts`
- Create: `frontend/src/lib/stores/applications.ts`
- Create: `frontend/src/lib/testing/fixtures.ts`
- Test: `frontend/src/lib/api/applications.test.ts`
- Test: `frontend/src/lib/stores/applications.test.ts`

**Interfaces:**
- Consumes: `apiFetch` (Task 9).
- Produces:
  - `types/application.ts`: `ApplicationStatus = "wishlist" | "applied" | "phone_screen" | "interview" | "offer" | "rejected"`; `Priority = "low" | "medium" | "high"`; `Application` interface (camelCase: `id`, `company`, `roleTitle`, `dateApplied`, `status`, `jobLink`, `notes`, `resumeVersion`, `contactPerson`, `salaryRange`, `location`, `source`, `priority`, `followUpDate`, `interviewDatetime`, `googleDocLink`, `archived`, `createdAt`, `updatedAt`); `ApplicationInput` (same minus `id`/`archived`/`createdAt`/`updatedAt`); `StatusHistoryEntry`; `ActivityEntry`.
  - `lib/testing/fixtures.ts`: `export function fakeApplication(overrides?: Partial<Application>): Application` — returns a complete `Application` with sensible defaults (`status: "wishlist"`, `priority: "medium"`, `archived: false`, all nullable fields `null`), merged with `overrides`. **This is the single shared source of test fixture data for the frontend — Tasks 11 and 15 import it from here rather than redefining it.**
  - `api/applications.ts`: `mapApplicationFromApi(raw: Record<string, unknown>): Application` (snake_case → camelCase); `listApplications(includeArchived?: boolean): Promise<Application[]>`; `getApplication(id: number): Promise<Application>`; `createApplication(data: ApplicationInput): Promise<Application>`; `updateApplication(id: number, data: Partial<ApplicationInput>): Promise<Application>`; `changeStatus(id: number, newStatus: ApplicationStatus): Promise<Application>`; `archiveApplication(id: number): Promise<Application>`; `getStatusHistory(id: number): Promise<StatusHistoryEntry[]>`; `getRecentActivity(limit?: number): Promise<ActivityEntry[]>`.
  - `stores/applications.ts`: `export const applications = writable<Application[]>([])`; `export async function loadApplications(): Promise<void>` (calls `listApplications(false)`, excluding archived by default); `export async function moveApplicationStatus(id: number, newStatus: ApplicationStatus): Promise<void>` (optimistic update of the store, then calls `changeStatus`, reverting on failure).

- [ ] **Step 1: Write the failing test** `frontend/src/lib/api/applications.test.ts`:

```ts
it("maps snake_case api fields to camelCase", () => {
  const mapped = mapApplicationFromApi({
    id: 1, company: "Stripe", role_title: "SWE Intern", status: "wishlist",
    date_applied: null, job_link: null, notes: null, resume_version: null,
    contact_person: null, salary_range: null, location: null, source: null,
    priority: "medium", follow_up_date: null, interview_datetime: null,
    google_doc_link: null, archived: false, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
  });
  expect(mapped.roleTitle).toBe("SWE Intern");
  expect(mapped.dateApplied).toBeNull();
});
```

- [ ] **Step 2: Run test to verify it fails.**

- [ ] **Step 3: Implement `types/application.ts` and `api/applications.ts`.**

- [ ] **Step 4: Run test to verify it passes.**

- [ ] **Step 5: Write the failing test** `frontend/src/lib/stores/applications.test.ts`:

```ts
it("loadApplications populates the store excluding archived", async () => {
  vi.spyOn(apiModule, "listApplications").mockResolvedValue([fakeApplication({ id: 1 })]);
  await loadApplications();
  expect(get(applications)).toHaveLength(1);
  expect(apiModule.listApplications).toHaveBeenCalledWith(false);
});

it("moveApplicationStatus reverts the optimistic update on failure", async () => {
  applications.set([fakeApplication({ id: 1, status: "wishlist" })]);
  vi.spyOn(apiModule, "changeStatus").mockRejectedValue(new Error("boom"));
  await expect(moveApplicationStatus(1, "applied")).rejects.toThrow();
  expect(get(applications)[0].status).toBe("wishlist");
});
```

- [ ] **Step 6: Run test to verify it fails.**

- [ ] **Step 7: Implement `stores/applications.ts`.**

- [ ] **Step 8: Run test to verify it passes.**

- [ ] **Step 9: Commit.**

```bash
git add frontend/src/lib/types/application.ts frontend/src/lib/api/applications.ts frontend/src/lib/stores/applications.ts frontend/src/lib/api/applications.test.ts frontend/src/lib/stores/applications.test.ts
git commit -m "feat: applications api client, types, and store"
```

---

## Task 11: Kanban Board & Application Card

**Files:**
- Create: `frontend/src/lib/components/KanbanBoard.svelte`
- Create: `frontend/src/lib/components/ApplicationCard.svelte`
- Create: `frontend/src/lib/components/StatusBadge.svelte`
- Create: `frontend/src/lib/kanban/grouping.ts`
- Test: `frontend/src/lib/kanban/grouping.test.ts`

**Interfaces:**
- Consumes: `applications` store, `moveApplicationStatus` (Task 10), `Application`/`ApplicationStatus` types, `showToast` (Task 9), `fakeApplication` from `lib/testing/fixtures.ts` (Task 10 — import it in `grouping.test.ts` rather than redefining it).
- Produces:
  - `kanban/grouping.ts`: `const KANBAN_COLUMNS: ApplicationStatus[]` in spec order (`wishlist`, `applied`, `phone_screen`, `interview`, `offer`, `rejected`); `groupByStatus(apps: Application[]): Record<ApplicationStatus, Application[]>` — ignores archived applications even if present in the input array.
  - `KanbanBoard.svelte` — renders one column per `KANBAN_COLUMNS` entry using `groupByStatus($applications)`; each column is an HTML5 drop target; on drop, calls `moveApplicationStatus(draggedId, columnStatus)`, catching any `ApiError` and calling `showToast("Couldn't move application — try again.")` (Task 9's toast store) rather than failing silently.
  - `ApplicationCard.svelte` — shows company, role, priority, a `StatusBadge`; `draggable="true"`, sets the application id as drag data on `dragstart`.

- [ ] **Step 1: Write the failing test** `frontend/src/lib/kanban/grouping.test.ts`:

```ts
it("groups applications by status and excludes archived", () => {
  const apps = [
    fakeApplication({ id: 1, status: "wishlist", archived: false }),
    fakeApplication({ id: 2, status: "applied", archived: false }),
    fakeApplication({ id: 3, status: "wishlist", archived: true }),
  ];
  const grouped = groupByStatus(apps);
  expect(grouped.wishlist.map(a => a.id)).toEqual([1]);
  expect(grouped.applied.map(a => a.id)).toEqual([2]);
});

it("returns an empty array for columns with no applications", () => {
  const grouped = groupByStatus([]);
  expect(grouped.offer).toEqual([]);
});
```

- [ ] **Step 2: Run test to verify it fails.**

- [ ] **Step 3: Implement `kanban/grouping.ts`.**

- [ ] **Step 4: Run test to verify it passes.**

- [ ] **Step 5: Implement `StatusBadge.svelte`, `ApplicationCard.svelte`, and `KanbanBoard.svelte`** using native HTML5 drag-and-drop events (`dragstart`/`dragover`/`drop`), delegating the actual status change to `moveApplicationStatus`.

- [ ] **Step 6: Commit.**

```bash
git add frontend/src/lib/components/KanbanBoard.svelte frontend/src/lib/components/ApplicationCard.svelte frontend/src/lib/components/StatusBadge.svelte frontend/src/lib/kanban/
git commit -m "feat: kanban board, application card, status grouping"
```

---

## Task 12: Application Detail Panel & Google Doc Viewer

**Files:**
- Create: `frontend/src/lib/components/GoogleDocViewer.svelte`
- Create: `frontend/src/lib/components/ApplicationDetailPanel.svelte`
- Modify: `frontend/src/lib/api/applications.ts` (none expected — reuse existing) / Create: `frontend/src/lib/api/docs.ts`
- Test: `frontend/src/lib/api/docs.test.ts`
- Test: `frontend/src/lib/components/GoogleDocViewer.test.ts`

**Interfaces:**
- Consumes: `apiFetch` (Task 9), `getStatusHistory` (Task 10).
- Produces:
  - `lib/api/docs.ts`: `async function getDocContent(docRef: string): Promise<string>` — calls `GET /api/docs/content?doc_ref=...` via `apiFetch`, returns the `content` field; lets `ApiError` propagate.
  - `GoogleDocViewer.svelte` (props: `docRef: string | null`) — if `docRef` is null, renders nothing; otherwise calls `getDocContent` on mount, shows the content on success, and on failure (any `ApiError`) shows: `"Couldn't load doc."` plus a link `"Open in Google Docs"` pointing at `https://docs.google.com/document/d/${docRef}/edit` — this is the frontend half of the Review Focus item on graceful Google Doc failure.
  - `ApplicationDetailPanel.svelte` (prop: `application: Application`) — displays every field, a status-history timeline (via `getStatusHistory`), and `<GoogleDocViewer docRef={application.googleDocLink} />`.

- [ ] **Step 1: Write the failing test** `frontend/src/lib/api/docs.test.ts`:

```ts
it("returns doc content on success", async () => {
  globalThis.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ content: "hello" }) });
  expect(await getDocContent("abc123")).toBe("hello");
});
```

- [ ] **Step 2: Run test to verify it fails.**

- [ ] **Step 3: Implement `lib/api/docs.ts`.**

- [ ] **Step 4: Run test to verify it passes.**

- [ ] **Step 5: Write the failing test** `frontend/src/lib/components/GoogleDocViewer.test.ts`:

```ts
it("shows a fallback link when the doc fails to load", async () => {
  vi.spyOn(docsApi, "getDocContent").mockRejectedValue(new ApiError(502, "couldn't load doc"));
  const { findByText } = render(GoogleDocViewer, { props: { docRef: "abc123" } });
  expect(await findByText("Couldn't load doc.")).toBeInTheDocument();
  expect(await findByText("Open in Google Docs")).toHaveAttribute(
    "href", "https://docs.google.com/document/d/abc123/edit"
  );
});

it("renders content on success", async () => {
  vi.spyOn(docsApi, "getDocContent").mockResolvedValue("my essay draft");
  const { findByText } = render(GoogleDocViewer, { props: { docRef: "abc123" } });
  expect(await findByText("my essay draft")).toBeInTheDocument();
});
```

- [ ] **Step 6: Run test to verify it fails.**

- [ ] **Step 7: Implement `GoogleDocViewer.svelte`.**

- [ ] **Step 8: Run test to verify it passes.**

- [ ] **Step 9: Implement `ApplicationDetailPanel.svelte`** (no new test required beyond the two above — it composes already-tested pieces: field display, a list rendered from `getStatusHistory`, and `GoogleDocViewer`).

- [ ] **Step 10: Commit.**

```bash
git add frontend/src/lib/api/docs.ts frontend/src/lib/components/GoogleDocViewer.svelte frontend/src/lib/components/ApplicationDetailPanel.svelte frontend/src/lib/api/docs.test.ts frontend/src/lib/components/GoogleDocViewer.test.ts
git commit -m "feat: application detail panel and google doc viewer with graceful fallback"
```

---

## Task 13: Applications Route Page

**Files:**
- Create: `frontend/src/routes/Applications.svelte`
- Modify: `frontend/src/App.svelte` (wire the real route in place of the stub)

**Interfaces:**
- Consumes: `KanbanBoard`, `ApplicationDetailPanel` (Tasks 11–12), `applications` store + `loadApplications` (Task 10).

- [ ] **Step 1: Implement `Applications.svelte`** — calls `loadApplications()` on mount, renders `KanbanBoard`, and on card click opens `ApplicationDetailPanel` for the selected application (local `selectedId` state, `null` = closed).

- [ ] **Step 2: Wire the route into `App.svelte`.**

- [ ] **Step 3: Manually verify** — `npm run dev`, log in, create an application via the UI (or `curl`), confirm it appears on the board and the detail panel opens on click.

- [ ] **Step 4: Commit.**

```bash
git add frontend/src/routes/Applications.svelte frontend/src/App.svelte
git commit -m "feat: applications page wiring kanban board and detail panel"
```

---

## Task 14: Dashboard Grid (Gridstack Wrapper & Layout Persistence)

**Files:**
- Create: `frontend/src/lib/dashboard/layout.ts`
- Create: `frontend/src/lib/components/DashboardGrid.svelte`
- Test: `frontend/src/lib/dashboard/layout.test.ts`

**Interfaces:**
- Produces:
  - `dashboard/layout.ts`: `interface WidgetLayoutEntry { id: string; x: number; y: number; w: number; h: number; settings: Record<string, unknown> }`; `const LAYOUT_STORAGE_KEY = "dashboard-layout-v1"`; `loadLayout(defaults: WidgetLayoutEntry[]): WidgetLayoutEntry[]` — reads `localStorage[LAYOUT_STORAGE_KEY]`, parses JSON, returns it if it's a valid array, otherwise returns `defaults` (also on a `JSON.parse` failure); `saveLayout(layout: WidgetLayoutEntry[]): void` — writes the JSON-stringified layout to the same key.
  - `DashboardGrid.svelte` (props: `defaultLayout: WidgetLayoutEntry[]`, slot per widget keyed by `id`) — initializes a Gridstack instance from `loadLayout(defaultLayout)`, calls `saveLayout` on Gridstack's `change` event.

- [ ] **Step 1: Write the failing test** `frontend/src/lib/dashboard/layout.test.ts`:

```ts
beforeEach(() => localStorage.clear());

it("returns defaults when nothing is stored", () => {
  const defaults = [{ id: "activity", x: 0, y: 0, w: 4, h: 2, settings: {} }];
  expect(loadLayout(defaults)).toEqual(defaults);
});

it("returns the stored layout when present", () => {
  const stored = [{ id: "activity", x: 1, y: 1, w: 6, h: 3, settings: { limit: 5 } }];
  saveLayout(stored);
  expect(loadLayout([])).toEqual(stored);
});

it("falls back to defaults on corrupted storage", () => {
  localStorage.setItem("dashboard-layout-v1", "not-json");
  const defaults = [{ id: "activity", x: 0, y: 0, w: 4, h: 2, settings: {} }];
  expect(loadLayout(defaults)).toEqual(defaults);
});
```

- [ ] **Step 2: Run tests to verify they fail.**

- [ ] **Step 3: Implement `dashboard/layout.ts`.**

- [ ] **Step 4: Run tests to verify they pass.**

- [ ] **Step 5: Implement `DashboardGrid.svelte`** wrapping `gridstack`'s `GridStack.init`, feeding it the result of `loadLayout`, and persisting via `saveLayout` on every layout change (drag/resize).

- [ ] **Step 6: Commit.**

```bash
git add frontend/src/lib/dashboard/layout.ts frontend/src/lib/components/DashboardGrid.svelte frontend/src/lib/dashboard/layout.test.ts
git commit -m "feat: dashboard grid with per-device localStorage layout persistence"
```

---

## Task 15: Dashboard Widgets

**Files:**
- Create: `frontend/src/lib/dashboard/widgets.ts`
- Create: `frontend/src/lib/components/widgets/RecentActivityFeed.svelte`
- Create: `frontend/src/lib/components/widgets/RemindersList.svelte`
- Create: `frontend/src/lib/components/widgets/BucketPreview.svelte`
- Create: `frontend/src/lib/components/widgets/KanbanSnapshot.svelte`
- Test: `frontend/src/lib/dashboard/widgets.test.ts`

**Interfaces:**
- Consumes: `applications` store (Task 10), `getRecentActivity` (Task 10), `ApplicationStatus` (Task 10), `fakeApplication` from `lib/testing/fixtures.ts` (Task 10 — import it in `widgets.test.ts` rather than redefining it).
- Produces, all in `dashboard/widgets.ts` (pure functions, each excluding archived applications):
  - `upcomingReminders(apps: Application[], withinDays: number, now: Date): Application[]` — includes applications where `followUpDate` or `interviewDatetime` falls within `[now, now + withinDays]`, sorted ascending by whichever date qualified.
  - `type Bucket = "undone" | "workingOn" | "completed"`; `bucketApplications(apps: Application[]): Record<Bucket, Application[]>` — `undone` = `wishlist`; `workingOn` = `applied`/`phone_screen`/`interview`; `completed` = `offer`/`rejected`.
  - `countByStatus(apps: Application[]): Record<ApplicationStatus, number>`.

- [ ] **Step 1: Write the failing tests** `frontend/src/lib/dashboard/widgets.test.ts`:

```ts
it("upcomingReminders includes only dates within the window and excludes archived", () => {
  const now = new Date("2026-10-05T00:00:00Z");
  const apps = [
    fakeApplication({ id: 1, followUpDate: "2026-10-10", archived: false }),
    fakeApplication({ id: 2, followUpDate: "2026-11-10", archived: false }),
    fakeApplication({ id: 3, followUpDate: "2026-10-06", archived: true }),
  ];
  expect(upcomingReminders(apps, 14, now).map(a => a.id)).toEqual([1]);
});

it("bucketApplications maps statuses to the three buckets and excludes archived", () => {
  const apps = [
    fakeApplication({ id: 1, status: "wishlist", archived: false }),
    fakeApplication({ id: 2, status: "interview", archived: false }),
    fakeApplication({ id: 3, status: "offer", archived: false }),
    fakeApplication({ id: 4, status: "offer", archived: true }),
  ];
  const buckets = bucketApplications(apps);
  expect(buckets.undone.map(a => a.id)).toEqual([1]);
  expect(buckets.workingOn.map(a => a.id)).toEqual([2]);
  expect(buckets.completed.map(a => a.id)).toEqual([3]);
});

it("countByStatus tallies non-archived applications per status", () => {
  const apps = [
    fakeApplication({ id: 1, status: "applied", archived: false }),
    fakeApplication({ id: 2, status: "applied", archived: false }),
    fakeApplication({ id: 3, status: "applied", archived: true }),
  ];
  expect(countByStatus(apps).applied).toBe(2);
});
```

- [ ] **Step 2: Run tests to verify they fail.**

- [ ] **Step 3: Implement `dashboard/widgets.ts`.**

- [ ] **Step 4: Run tests to verify they pass.**

- [ ] **Step 5: Implement the four widget components**, each reading `$applications` (or, for `RecentActivityFeed`, calling `getRecentActivity`) and a `limit`/content-amount setting passed in as a prop (sourced from the widget's `settings` in the Gridstack layout — e.g. `RecentActivityFeed` takes a `limit: number = 5` prop with a small `<select>` to change it).

- [ ] **Step 6: Commit.**

```bash
git add frontend/src/lib/dashboard/widgets.ts frontend/src/lib/components/widgets/ frontend/src/lib/dashboard/widgets.test.ts
git commit -m "feat: dashboard widgets — recent activity, reminders, bucket preview, kanban snapshot"
```

---

## Task 16: Dashboard Route Page

**Files:**
- Create: `frontend/src/routes/Dashboard.svelte`
- Modify: `frontend/src/App.svelte` (wire the real route in place of the stub)

**Interfaces:**
- Consumes: `DashboardGrid` (Task 14), the four widgets (Task 15), `loadApplications` (Task 10).

- [ ] **Step 1: Implement `Dashboard.svelte`** — calls `loadApplications()` on mount, defines a sensible `defaultLayout: WidgetLayoutEntry[]` (one entry per widget, reasonable default `x`/`y`/`w`/`h`), renders `DashboardGrid` with the four widgets as its slotted content.

- [ ] **Step 2: Wire the route into `App.svelte`.**

- [ ] **Step 3: Manually verify** — `npm run dev`, confirm all four widgets render with seeded data, dragging/resizing a widget persists across a page reload.

- [ ] **Step 4: Commit.**

```bash
git add frontend/src/routes/Dashboard.svelte frontend/src/App.svelte
git commit -m "feat: dashboard page with default widget layout"
```

---

## Task 17: Essays Page

**Files:**
- Create: `frontend/src/lib/data/promptTemplates.ts`
- Create: `frontend/src/routes/Essays.svelte`
- Modify: `frontend/src/App.svelte` (wire the real route in place of the stub)
- Test: `frontend/src/lib/data/promptTemplates.test.ts`

**Interfaces:**
- Consumes: `GoogleDocViewer` (Task 12), `applications` store (Task 10).
- Produces:
  - `promptTemplates.ts`: `interface PromptTemplate { id: string; title: string; prompt: string }`; `export const promptTemplates: PromptTemplate[]` with at least: drafting an essay from a prompt + the user's background, and "review this essay for succinct, authentic writing."

- [ ] **Step 1: Write the failing test** `frontend/src/lib/data/promptTemplates.test.ts`:

```ts
it("includes a draft prompt and a succinct/authentic review prompt", () => {
  const titles = promptTemplates.map(t => t.title.toLowerCase());
  expect(titles.some(t => t.includes("draft"))).toBe(true);
  expect(titles.some(t => t.includes("review"))).toBe(true);
  for (const template of promptTemplates) {
    expect(template.prompt.length).toBeGreaterThan(0);
  }
});
```

- [ ] **Step 2: Run test to verify it fails.**

- [ ] **Step 3: Implement `promptTemplates.ts`.**

- [ ] **Step 4: Run test to verify it passes.**

- [ ] **Step 5: Implement `Essays.svelte`** — a prompt-template list with a "Copy" button per entry (`navigator.clipboard.writeText(template.prompt)`) and a link to `https://claude.ai`; below it, a list of applications from `$applications` each showing `<GoogleDocViewer docRef={app.googleDocLink} />` and a field to set/update `googleDocLink` (calling `updateApplication`).

- [ ] **Step 6: Wire the route into `App.svelte`.**

- [ ] **Step 7: Manually verify** — `npm run dev`, confirm copy buttons populate the clipboard and the claude.ai link opens in a new tab.

- [ ] **Step 8: Commit.**

```bash
git add frontend/src/lib/data/promptTemplates.ts frontend/src/routes/Essays.svelte frontend/src/App.svelte frontend/src/lib/data/promptTemplates.test.ts
git commit -m "feat: essays page with prompt library and linked google doc viewer"
```

---

## Task 18: Deployment (Docker Compose, Caddy, Env)

**Files:**
- Create: `backend/Dockerfile`
- Create: `frontend/Dockerfile`
- Create: `docker-compose.yml`
- Create: `Caddyfile`
- Create: `.env.example`

**Interfaces:**
- Consumes: every prior task's running application.
- Produces: a `docker compose up --build` that serves the full app over Caddy, reverse-proxying `/api/*` to the backend and everything else to the built frontend static files.

- [ ] **Step 1: Write `backend/Dockerfile`** — `python:3.12-slim` base, copy `requirements.txt`, `pip install`, copy `app/` and `alembic/`, `CMD` runs `alembic upgrade head` then `uvicorn app.main:app --host 0.0.0.0 --port 8000`.

- [ ] **Step 2: Write `frontend/Dockerfile`** — multi-stage: `node:20` stage runs `npm ci && npm run build`; final stage copies the built `dist/` output to a location Caddy can serve (e.g. a shared named volume, or directly into the Caddy image's file-server root via a `COPY --from=`).

- [ ] **Step 3: Write `docker-compose.yml`** with three services: `db` (`postgres:16`, named volume for data, env from `.env`), `backend` (built from `backend/Dockerfile`, depends on `db`, env from `.env`), `caddy` (built from a stage including the frontend's `dist/`, depends on `backend`, mounts `Caddyfile`, exposes 80/443, named volume for Let's Encrypt state).

- [ ] **Step 4: Write `Caddyfile`** — `{$DOMAIN}` block: `reverse_proxy /api/* backend:8000`, `file_server` for everything else, Caddy's automatic HTTPS handles the TLS certificate.

- [ ] **Step 5: Write `.env.example`** listing every required variable: `DATABASE_URL`, `JWT_SECRET`, `TOKEN_ENCRYPTION_KEY`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, `DOMAIN`.

- [ ] **Step 6: Manually verify locally** — copy `.env.example` to `.env` with local values (`DOMAIN=localhost`), run `docker compose up --build`, then:
  - `curl http://localhost/api/health` → expect `{"status":"ok"}`
  - load `http://localhost/` in a browser → expect the Login page to render

- [ ] **Step 7: Commit.**

```bash
git add backend/Dockerfile frontend/Dockerfile docker-compose.yml Caddyfile .env.example
git commit -m "feat: docker compose deployment with caddy reverse proxy and automatic https"
```
