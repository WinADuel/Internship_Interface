# Outreach & Contacts (Phase 1b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add outreach tracking for professors and company contacts to the internship tracker. Claude (a scheduled Claude Code job, no API billing) researches each contact and drafts their emails; the app has one-tap status buttons, staleness nudges, and a one-way Google Sheet backup.

**Architecture:** Same layering as Phase 1 (thin routers → services → models). Contacts are a separate entity from applications, linked by an optional FK. A separate `/api/claude/*` router authenticated by a revocable bearer token is the only way in for the scheduled job. Sheet sync rewrites whole tabs through a small Sheets client behind an overridable dependency, triggered after writes and nightly by a scheduler container.

**Tech Stack:** Unchanged from Phase 1 (FastAPI, SQLAlchemy 2.0, Alembic, PostgreSQL 16, httpx, pytest; Svelte 5 + TS, Vitest). Google Sheets REST API v4 via httpx — no new Python dependencies.

**Spec:** `docs/superpowers/specs/2026-10-05-internship-tracker-design.md` §13 (plus §7, §12 amendments).

**Prerequisite:** Phase 1 plan (`docs/superpowers/plans/2026-10-05-internship-tracker-phase1.md`) Tasks 1–18 complete. Interfaces referenced below as "P1 Task N" come from that plan.

## Global Constraints

- All Phase 1 Global Constraints apply unchanged (Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic-only schema changes, PostgreSQL 16, Svelte 5 + TS, structured `{"detail": ...}` errors, thin routers, one responsibility per file).
- No Claude API usage anywhere in the app. The scheduled Claude Code routine is the only producer of research and drafts (spec §13).
- The app never sends email and holds no Gmail permission. Sending is via a Gmail compose URL opened by the user (§13.6).
- Google scopes: the existing read-only scopes plus exactly `https://www.googleapis.com/auth/drive.file`. No other write scope (§7, §13.7).
- `/api/claude/*` accepts only `Authorization: Bearer <token>` matching a non-revoked `claude_tokens` row. It never accepts session cookies, and a Claude token never authenticates any other route (§13.5).
- Claude-delivered content is untrusted: every field length-capped, batch sizes capped, non-`http`/`https` URLs dropped. The frontend renders contact content as plain text and never uses `{@html}` for it (§13.5).
- Claude never changes a contact's `status`, date fields, `priority`, `notes`, or `archived`, and never overwrites a draft whose `*_edited` flag is true (§13.2).
- Sheet sync is one-way (app → sheet). A sync failure never fails or rolls back the user's write (§13.7).
- Workflow (spec §11b):
  - Build on a Phase 1b feature branch.
  - After each task passes review, push its commits to that branch on GitHub before the next task starts. Run a secret check first, and never rewrite history.
  - When the final review is clean, merge into `main`, push `main`, and write `docs/phases/phase-1b-report.md`.
- Nudge defaults: `nudge_unsent_days=5`, `nudge_followup_days=10`, `nudge_gone_quiet_days=10`, `nudge_replied_stale_days=14`. Snoozes: "Not yet" 3 days, "Wait longer" and "Still talking" 7 days. Undo window: 60 seconds. `claude_job_max_items=8`. Company contacts `target_count=3` (§13.2–13.4).

## Review Focus

- Hostile content from a web page arrives via Claude (a `javascript:` URL, HTML/script in `research_summary`). Expected: URLs dropped server-side and text rendered inert client-side. Pinned to Task 7 (server) and Task 12 (client).
- Claude re-delivers a contact the user has already edited, moved, or annotated. Expected: user-owned fields and edited drafts are untouched; only research fields refresh. Pinned to Task 7.
- A Claude token is presented to a cookie route, a session cookie to `/api/claude/*`, or a revoked token anywhere. Expected: 401 every time, nothing leaks. Pinned to Task 6.
- Google isn't connected, or the Sheets API errors, during a sync. Expected: the user's write still returns 2xx and the error is recorded for Settings. Pinned to Task 8.
- An application goes `applied → interview → applied`, or Find contacts is clicked after auto-enqueue. Expected: exactly one `company_contacts` queue item per application. Pinned to Task 4.

---

## Task 1: Outreach Data Models & Migration

**Files:**
- Create: `backend/app/models/contact.py`, `backend/app/models/contact_status_history.py`, `backend/app/models/research_queue.py`, `backend/app/models/app_settings.py`, `backend/app/models/claude_token.py`
- Modify: `backend/app/models/__init__.py` (import the new models so Alembic sees them)
- Create: `backend/alembic/versions/0003_outreach_contacts.py` (via `alembic revision --autogenerate`, then reviewed)
- Test: `backend/tests/models/test_outreach_models.py`

**Interfaces:**
- Consumes: `Base` (P1 Task 1), `Application`, `Priority` (P1 Task 4).
- Produces:
  - `contact.py`: `ContactKind(str, Enum)` = `PROFESSOR="professor"`, `COMPANY="company"`; `EmailConfidence(str, Enum)` = `FOUND="found"`, `PATTERN_GUESS="pattern_guess"`, `NOT_FOUND="not_found"`; `ContactStatus(str, Enum)` = `TO_CONTACT="to_contact"`, `SENT="sent"`, `FOLLOWED_UP="followed_up"`, `REPLIED="replied"`, `MEETING="meeting"`, `ACCEPTED="accepted"`, `DECLINED="declined"`; `ContactOrigin(str, Enum)` = `CLAUDE="claude"`, `MANUAL="manual"`. A `Contact` model with exactly the spec §13.2 `contacts` columns. Defaults: `email_confidence=NOT_FOUND`, `status=TO_CONTACT`, `priority=Priority.MEDIUM`, `origin=MANUAL`, `draft_edited=False`, `followup_edited=False`, `archived=False`, `sources=[]` (JSONB). `application_id` FK has `ondelete="SET NULL"`.
  - `contact_status_history.py`: `ContactStatusHistory` (`id`, `contact_id` FK → `contacts.id` `ondelete="CASCADE"`, `old_status: ContactStatus | None`, `new_status: ContactStatus`, `changed_at` default now).
  - `research_queue.py`: `QueueKind(str, Enum)` = `PROFESSOR_PERSON="professor_person"`, `PROFESSOR_SEARCH="professor_search"`, `COMPANY_CONTACTS="company_contacts"`; `QueueState(str, Enum)` = `PENDING="pending"`, `DONE="done"`, `FAILED="failed"`. A `ResearchQueueItem` model (table `research_queue`) with the spec columns, default `state=PENDING`, default `target_count=1`.
  - `app_settings.py`: `AppSettings` (single row, `id` always 1). Columns and defaults are exactly as in the Global Constraints values: `outreach_profile` text default `""`, the four `nudge_*_days` ints, `claude_job_max_items=8`, `backup_sheet_id` nullable, `last_sheet_sync_at` nullable, `last_sheet_sync_error` nullable.
  - `claude_token.py`: `ClaudeToken` (`id`, `token_hash` unique, `token_prefix`, `created_at`, `last_used_at` nullable, `revoked_at` nullable).

- [ ] **Step 1: Write the failing tests** `backend/tests/models/test_outreach_models.py`:

```python
def test_contact_defaults(db_session):
    c = Contact(kind=ContactKind.PROFESSOR, name="Jane Lee", organization="Stanford")
    db_session.add(c); db_session.flush()
    assert c.status == ContactStatus.TO_CONTACT
    assert c.email_confidence == EmailConfidence.NOT_FOUND
    assert c.origin == ContactOrigin.MANUAL
    assert c.draft_edited is False and c.followup_edited is False and c.archived is False
    assert c.sources == []

def test_contact_application_link_nulls_on_application_delete(db_session):
    app = Application(company="Stripe", role_title="SWE Intern"); db_session.add(app); db_session.flush()
    c = Contact(kind=ContactKind.COMPANY, name="Sam", organization="Stripe", application_id=app.id)
    db_session.add(c); db_session.flush()
    db_session.delete(app); db_session.flush(); db_session.refresh(c)
    assert c.application_id is None

def test_queue_item_and_settings_defaults(db_session):
    item = ResearchQueueItem(kind=QueueKind.PROFESSOR_PERSON, request_text="Jane Lee, Stanford")
    s = AppSettings(id=1)
    db_session.add_all([item, s]); db_session.flush()
    assert item.state == QueueState.PENDING and item.target_count == 1
    assert (s.nudge_unsent_days, s.nudge_followup_days, s.nudge_gone_quiet_days, s.nudge_replied_stale_days) == (5, 10, 10, 14)
    assert s.claude_job_max_items == 8 and s.outreach_profile == ""
```

- [ ] **Step 2: Run** `pytest backend/tests/models/test_outreach_models.py -v` — expected FAIL (import error).
- [ ] **Step 3: Implement the five model files** and register them in `models/__init__.py`.
- [ ] **Step 4: Run the tests** — expected PASS.
- [ ] **Step 5: Generate migration `0003_outreach_contacts`**, review it (enum types created and dropped, FKs with the `ondelete` rules, `token_hash` unique index, JSONB `sources` with server default `'[]'`), and apply it to the test and dev DBs: `alembic upgrade head`, then `alembic downgrade -1 && alembic upgrade head`. Expected: both succeed.
- [ ] **Step 6: Run the full backend suite** — expected all PASS.
- [ ] **Step 7: Commit** — `feat: outreach data models (contacts, history, research queue, settings, claude tokens) + migration`.

---

## Task 2: Contact Service — CRUD, Status Actions, Undo, Snooze

**Files:**
- Create: `backend/app/schemas/contact.py`, `backend/app/services/contact_service.py`, `backend/app/services/contact_transitions.py`
- Modify: `backend/app/services/errors.py` (add `ContactNotFoundError`, `InvalidTransitionError`, `UndoExpiredError`)
- Test: `backend/tests/services/test_contact_service.py`, `backend/tests/services/test_contact_transitions.py`

**Interfaces:**
- Consumes: Task 1 models.
- Produces:
  - `contact_transitions.py`: `ContactAction(str, Enum)` = `SENT="sent"`, `FOLLOWED_UP="followed_up"`, `REPLIED="replied"`, `MEETING_SET="meeting_set"`, `ACCEPTED="accepted"`, `DECLINED="declined"`, `NO_RESPONSE="no_response"`. `ACTIONS_BY_STATUS: dict[ContactStatus, tuple[ContactAction, ...]]` copied exactly from the spec §13.3 table (`accepted`/`declined` map to `()`). `ACTION_RESULT: dict[ContactAction, ContactStatus]` (`NO_RESPONSE → DECLINED`, `MEETING_SET → MEETING`, the others to their same-named status). `ACTION_DATE_FIELD: dict[ContactAction, str]` = `SENT→"sent_at"`, `FOLLOWED_UP→"followed_up_at"`, `REPLIED→"replied_at"`, `MEETING_SET→"meeting_at"`. `UNDO_WINDOW = timedelta(seconds=60)`.
  - `schemas/contact.py`: `ContactCreate` (`kind`, `name`, `organization`, optional identity fields, `priority`, `notes`, `application_id`), `ContactUpdate` (every user-editable field optional, including `draft_subject`, `draft_body`, `followup_subject`, `followup_body`, `priority`, `notes`), `ContactOut` (all columns plus `nudge: NudgeKind | None = None`, `from_attributes`), `ContactActionIn` (`action: ContactAction`, `on: datetime | None = None`, `meeting_at: datetime | None = None`), `ContactStatusIn` (`new_status: ContactStatus`), `SnoozeIn` (`days: int`, constrained `1 <= days <= 30`), `ContactHistoryOut`, `ContactActivityOut` (`contact_id`, `name`, `organization`, `kind`, `old_status`, `new_status`, `changed_at`).
  - `contact_service.py`:
    - `create_contact(db, data: ContactCreate) -> Contact` (`origin=MANUAL`)
    - `get_contact(db, contact_id: int) -> Contact` (raises `ContactNotFoundError`)
    - `list_contacts(db, kind: ContactKind | None = None, include_archived: bool = False, application_id: int | None = None) -> list[Contact]`, newest `updated_at` first
    - `update_contact(db, contact_id, data: ContactUpdate) -> Contact`. Setting `draft_subject` or `draft_body` sets `draft_edited=True`; setting `followup_*` sets `followup_edited=True`.
    - `apply_action(db, contact_id, action: ContactAction, on: datetime | None = None, meeting_at: datetime | None = None, now: datetime | None = None) -> Contact`. Raises `InvalidTransitionError` if `action not in ACTIONS_BY_STATUS[contact.status]`, or if `action == MEETING_SET` and `meeting_at is None`. On success it sets the status to `ACTION_RESULT[action]` and the date field to `on or now` (`meeting_at` for `MEETING_SET`). `NO_RESPONSE` also sets `closed_reason="no_response"`. It clears `nudge_snoozed_until` and writes one `ContactStatusHistory` row with `changed_at=now`.
    - `move_status(db, contact_id, new_status: ContactStatus, now=None) -> Contact` (drag-and-drop). Finds the first action in `ACTIONS_BY_STATUS[current]` whose result is `new_status` and delegates to `apply_action`; raises `InvalidTransitionError` if none exists or if it is `MEETING_SET` (a meeting needs a time, so it must use the button).
    - `undo_last_action(db, contact_id, now: datetime | None = None) -> Contact`. Takes the newest history row; raises `UndoExpiredError` if none exists or `now - changed_at > UNDO_WINDOW`. Otherwise restores `old_status`, sets the date field of the undone status back to `None` (`sent→sent_at`, `followed_up→followed_up_at`, `replied→replied_at`, `meeting→meeting_at`), clears `closed_reason` if it was `"no_response"`, and deletes that history row.
    - `snooze_contact(db, contact_id, days: int, today: date) -> Contact` (sets `nudge_snoozed_until = today + days`)
    - `archive_contact(db, contact_id) -> Contact`
    - `get_contact_history(db, contact_id) -> list[ContactStatusHistory]` (oldest first)
    - `get_recent_contact_activity(db, limit: int = 10) -> list[dict]` (newest first, shaped as `ContactActivityOut`)
  - `errors.py`: `ContactNotFoundError`, `InvalidTransitionError(message: str)`, `UndoExpiredError`.

- [ ] **Step 1: Write the failing transition-table test** `test_contact_transitions.py` — assert `ACTIONS_BY_STATUS` equals the spec table literally:

```python
def test_actions_by_status_matches_spec_table():
    assert ACTIONS_BY_STATUS == {
        ContactStatus.TO_CONTACT: (ContactAction.SENT,),
        ContactStatus.SENT: (ContactAction.FOLLOWED_UP, ContactAction.REPLIED, ContactAction.DECLINED),
        ContactStatus.FOLLOWED_UP: (ContactAction.REPLIED, ContactAction.DECLINED, ContactAction.NO_RESPONSE),
        ContactStatus.REPLIED: (ContactAction.MEETING_SET, ContactAction.ACCEPTED, ContactAction.DECLINED),
        ContactStatus.MEETING: (ContactAction.ACCEPTED, ContactAction.DECLINED),
        ContactStatus.ACCEPTED: (),
        ContactStatus.DECLINED: (),
    }
```

- [ ] **Step 2: Write the failing service tests** `test_contact_service.py` (use a fixed `NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)`):

```python
def test_sent_action_stamps_date_and_writes_history(db_session):
    c = create_contact(db_session, ContactCreate(kind="professor", name="Jane", organization="Stanford"))
    apply_action(db_session, c.id, ContactAction.SENT, now=NOW)
    assert c.status == ContactStatus.SENT and c.sent_at == NOW
    [h] = get_contact_history(db_session, c.id)
    assert (h.old_status, h.new_status) == (ContactStatus.TO_CONTACT, ContactStatus.SENT)

def test_backdated_action_uses_on(db_session):
    c = create_contact(db_session, ContactCreate(kind="professor", name="Jane", organization="Stanford"))
    apply_action(db_session, c.id, ContactAction.SENT, on=NOW - timedelta(days=3), now=NOW)
    assert c.sent_at == NOW - timedelta(days=3)

def test_invalid_action_raises_and_writes_nothing(db_session):
    c = create_contact(db_session, ContactCreate(kind="professor", name="Jane", organization="Stanford"))
    with pytest.raises(InvalidTransitionError):
        apply_action(db_session, c.id, ContactAction.ACCEPTED, now=NOW)
    assert c.status == ContactStatus.TO_CONTACT and get_contact_history(db_session, c.id) == []

def test_meeting_set_requires_meeting_at(db_session): ...  # REPLIED contact; MEETING_SET without meeting_at → InvalidTransitionError

def test_no_response_closes_as_declined_with_reason(db_session): ...  # FOLLOWED_UP → NO_RESPONSE → status DECLINED, closed_reason "no_response"

def test_move_status_rejects_skipping_stages(db_session): ...  # TO_CONTACT → REPLIED via move_status → InvalidTransitionError

def test_undo_within_window_restores_previous_state(db_session):
    c = create_contact(db_session, ContactCreate(kind="professor", name="Jane", organization="Stanford"))
    apply_action(db_session, c.id, ContactAction.SENT, now=NOW)
    undo_last_action(db_session, c.id, now=NOW + timedelta(seconds=59))
    assert c.status == ContactStatus.TO_CONTACT and c.sent_at is None
    assert get_contact_history(db_session, c.id) == []

def test_undo_after_window_raises(db_session): ...  # now = NOW + 61s → UndoExpiredError, status still SENT

def test_editing_draft_marks_it_edited(db_session):
    c = create_contact(db_session, ContactCreate(kind="professor", name="Jane", organization="Stanford"))
    update_contact(db_session, c.id, ContactUpdate(draft_body="my words"))
    assert c.draft_edited is True and c.followup_edited is False

def test_action_clears_snooze(db_session): ...  # snooze 3 days, then SENT → nudge_snoozed_until is None
```

- [ ] **Step 3: Run** both test files — expected FAIL.
- [ ] **Step 4: Implement** `contact_transitions.py`, `schemas/contact.py`, `contact_service.py`, and the new errors. In this task, declare `ContactOut.nudge: str | None = None`; Task 3 narrows it to `NudgeKind | None`.
- [ ] **Step 5: Run the tests** — expected PASS. Run the full suite.
- [ ] **Step 6: Commit** — `feat: contact service with status actions, undo window, snooze`.

---

## Task 3: Nudges & App Settings Service

**Files:**
- Create: `backend/app/services/nudges.py`, `backend/app/services/settings_service.py`, `backend/app/schemas/settings.py`
- Modify: `backend/app/services/contact_service.py` (add `list_needs_attention`), `backend/app/schemas/contact.py` (type `ContactOut.nudge` as `NudgeKind | None`)
- Test: `backend/tests/services/test_nudges.py`, `backend/tests/services/test_settings_service.py`

**Interfaces:**
- Consumes: Task 1–2.
- Produces:
  - `nudges.py`: `NudgeKind(str, Enum)` = `UNSENT="unsent"`, `FOLLOWUP_DUE="followup_due"`, `GONE_QUIET="gone_quiet"`, `REPLIED_STALE="replied_stale"`, `MEETING_OUTCOME="meeting_outcome"`. `@dataclass(frozen=True) class NudgeSettings: unsent_days: int; followup_days: int; gone_quiet_days: int; replied_stale_days: int`. `compute_nudge(contact: Contact, last_status_change: datetime | None, settings: NudgeSettings, today: date) -> NudgeKind | None` — a pure function implementing spec §13.4. "Older than N days" means `(today - field.date()).days >= N`. It returns `None` if the contact is archived or `today < nudge_snoozed_until`. `MEETING_OUTCOME` fires when `meeting_at.date() < today`. `REPLIED_STALE` uses `last_status_change` (or `replied_at` when that is None). `needs_followup_draft(contact, settings, today) -> bool`: `status == SENT`, `followup_body is None`, not archived, and `(today - sent_at.date()).days >= settings.followup_days - 1`, so the draft lands the day before the nudge appears.
  - `settings_service.py`: `get_settings(db) -> AppSettings` (creates the `id=1` row with defaults if missing), `update_settings(db, data: SettingsUpdate) -> AppSettings`, `nudge_settings(s: AppSettings) -> NudgeSettings`.
  - `schemas/settings.py`: `SettingsOut` (every `AppSettings` column except `id`), `SettingsUpdate` (`outreach_profile: str | None` capped at 5000 chars; each `nudge_*_days: int | None` constrained `1..90`; `claude_job_max_items: int | None` constrained `1..25`).
  - `contact_service.list_needs_attention(db, today: date) -> list[tuple[Contact, NudgeKind]]` — every non-archived contact whose `compute_nudge` is not None. It gets `last_status_change` from one grouped query over `contact_status_history` (no per-contact query).

- [ ] **Step 1: Write the failing pure-function tests** `test_nudges.py`. Use a fixed `TODAY = date(2026, 10, 20)` and `S = NudgeSettings(5, 10, 10, 14)`, building unsaved `Contact` objects in memory. Cover:

```python
@pytest.mark.parametrize("status,field,days_ago,expected", [
    ("to_contact", "draft_ready_at", 5, NudgeKind.UNSENT),
    ("to_contact", "draft_ready_at", 4, None),
    ("sent", "sent_at", 10, NudgeKind.FOLLOWUP_DUE),
    ("sent", "sent_at", 9, None),
    ("followed_up", "followed_up_at", 10, NudgeKind.GONE_QUIET),
    ("followed_up", "followed_up_at", 9, None),
])
def test_date_threshold_nudges(status, field, days_ago, expected): ...

def test_replied_stale_uses_last_status_change(): ...   # replied, last change 14 days ago → REPLIED_STALE; 13 → None
def test_meeting_outcome_after_meeting_day(): ...        # meeting_at yesterday → MEETING_OUTCOME; meeting_at today → None
def test_snooze_hides_nudge_until_date(): ...            # sent 12 days ago, snoozed_until TODAY+1 → None; snoozed_until TODAY → FOLLOWUP_DUE
def test_archived_contact_has_no_nudge(): ...
def test_to_contact_without_draft_has_no_nudge(): ...
def test_needs_followup_draft_one_day_early(): ...       # sent 9 days ago, no followup_body → True; with followup_body → False; 8 days → False
```

- [ ] **Step 2: Write the failing settings tests**: `get_settings` creates the defaults once and returns the same row on a second call; `update_settings` changes only the supplied fields.
- [ ] **Step 3: Run** — expected FAIL.
- [ ] **Step 4: Implement**, then add `list_needs_attention` with a DB test (two contacts, one due and one not → only the due one is returned with `FOLLOWUP_DUE`).
- [ ] **Step 5: Run** — expected PASS. Run the full suite.
- [ ] **Step 6: Commit** — `feat: nudge computation and app settings service`.

---

## Task 4: Research Queue Service & Auto-Enqueue on Applied

**Files:**
- Create: `backend/app/services/research_queue_service.py`, `backend/app/schemas/research_queue.py`
- Modify: `backend/app/services/application_service.py` (`change_status` hook), `backend/app/services/errors.py` (add `QueueItemNotFoundError`, `QueueItemNotPendingError`, `AlreadyQueuedError`)
- Test: `backend/tests/services/test_research_queue_service.py`

**Interfaces:**
- Consumes: Task 1, `application_service.change_status`/`get_application` (P1 Task 5).
- Produces:
  - `schemas/research_queue.py`: `QueueItemCreate` (`kind: Literal["professor_person", "professor_search"]`, `request_text: str` 1..1000 chars, `target_count: int = 1` constrained `1..10`), `QueueItemOut` (all columns, `from_attributes`).
  - `research_queue_service.py`:
    - `enqueue_professor(db, data: QueueItemCreate) -> ResearchQueueItem` (`target_count` is forced to 1 for `professor_person`)
    - `enqueue_company_contacts(db, application: Application) -> ResearchQueueItem` — raises `AlreadyQueuedError` if any queue item (any state) already exists for `application.id`. Sets `request_text = f"{application.company} — {application.role_title}" + (f" — {application.job_link}" if application.job_link else "")`, `target_count=3`, `kind=COMPANY_CONTACTS`.
    - `list_queue(db, state: QueueState | None = None) -> list[ResearchQueueItem]` (newest first)
    - `pending_items(db, limit: int) -> list[ResearchQueueItem]` (oldest first, so leftovers roll forward fairly)
    - `complete_item(db, item_id, note: str, now=None)` / `fail_item(db, item_id, note: str, now=None)` — raise `QueueItemNotFoundError` / `QueueItemNotPendingError`; set `state`, `result_note`, `completed_at`.
  - `application_service.change_status`: after it writes a history row with `new_status == APPLIED`, call `enqueue_company_contacts` and swallow only `AlreadyQueuedError`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_marking_applied_enqueues_company_contacts_once(db_session):
    app = create_application(db_session, ApplicationCreate(company="Stripe", role_title="SWE Intern", job_link="https://stripe.com/jobs/1"))
    change_status(db_session, app.id, ApplicationStatus.APPLIED)
    change_status(db_session, app.id, ApplicationStatus.INTERVIEW)
    change_status(db_session, app.id, ApplicationStatus.APPLIED)
    [item] = list_queue(db_session)
    assert item.kind == QueueKind.COMPANY_CONTACTS and item.application_id == app.id and item.target_count == 3
    assert item.request_text == "Stripe — SWE Intern — https://stripe.com/jobs/1"

def test_manual_find_contacts_after_auto_enqueue_raises(db_session): ...  # AlreadyQueuedError
def test_non_applied_status_does_not_enqueue(db_session): ...           # wishlist → interview: queue empty
def test_professor_person_target_count_forced_to_one(db_session): ...
def test_pending_items_oldest_first_and_limited(db_session): ...
def test_complete_non_pending_item_raises(db_session): ...
```

- [ ] **Step 2: Run** — expected FAIL. **Step 3: Implement.** **Step 4: Run** — expected PASS. Run the full suite, which confirms P1 application tests still pass.
- [ ] **Step 5: Commit** — `feat: research queue service with auto-enqueue on applied`.

---

## Task 5: Contacts, Research Queue & Settings API Routes (cookie-protected)

**Files:**
- Create: `backend/app/api/contacts.py`, `backend/app/api/research_queue.py`, `backend/app/api/settings.py`
- Modify: `backend/app/main.py` (register the three routers)
- Test: `backend/tests/api/test_contact_routes.py`, `backend/tests/api/test_research_queue_routes.py`, `backend/tests/api/test_settings_routes.py`

**Interfaces:**
- Consumes: Tasks 2–4, `get_current_user` (P1 Task 3), `logged_in_client` fixture (`backend/tests/api/conftest.py`).
- Produces, every route protected by `Depends(get_current_user)`. `ContactOut.nudge` is filled with `compute_nudge(..., today=date.today())`. Declare static paths before `/{contact_id}`.
  - `GET /api/contacts?kind=&include_archived=false&application_id=` → `list[ContactOut]`
  - `POST /api/contacts` → 201 `ContactOut`
  - `GET /api/contacts/activity?limit=10` → `list[ContactActivityOut]`
  - `GET /api/contacts/needs-attention` → `list[ContactOut]` (every item has a non-null `nudge`)
  - `GET /api/contacts/{id}` → `ContactOut`; 404 `{"detail": "contact not found"}`
  - `PATCH /api/contacts/{id}` → `ContactOut`
  - `POST /api/contacts/{id}/actions` body `ContactActionIn` → `ContactOut`; 422 `{"detail": <InvalidTransitionError message>}`
  - `POST /api/contacts/{id}/status` body `ContactStatusIn` → `ContactOut`; 422 on an invalid transition
  - `POST /api/contacts/{id}/undo` → `ContactOut`; 409 `{"detail": "undo window expired"}`
  - `POST /api/contacts/{id}/snooze` body `SnoozeIn` → `ContactOut`
  - `POST /api/contacts/{id}/archive` → `ContactOut`
  - `GET /api/contacts/{id}/history` → `list[ContactHistoryOut]`
  - `GET /api/research-queue?state=` → `list[QueueItemOut]`; `POST /api/research-queue` body `QueueItemCreate` → 201
  - `POST /api/research-queue/find-contacts/{application_id}` → 201 `QueueItemOut`; 404 for an unknown application; 409 `{"detail": "already queued"}`
  - `GET /api/settings` → `SettingsOut`; `PATCH /api/settings` body `SettingsUpdate` → `SettingsOut`

- [ ] **Step 1: Write the failing route tests:**
  - every route returns 401 `{"detail": "not authenticated"}` without a cookie (one parametrized test over method+path);
  - create → actions(sent) → history round-trip;
  - invalid action → 422 and a follow-up `GET` shows the status unchanged;
  - an unknown `action` value → 422 (Pydantic);
  - undo after the window → 409 (patch `contact_service`'s clock or call the service to backdate the history row);
  - `needs-attention` returns only the due contact;
  - `find-contacts` twice → 201 then 409;
  - `PATCH /api/settings` with `nudge_followup_days=0` → 422.
- [ ] **Step 2: Run** — expected FAIL. **Step 3: Implement** thin routers mapping service errors to the status codes above. **Step 4: Run** — expected PASS. Run the full suite.
- [ ] **Step 5: Commit** — `feat: contacts, research queue, and settings API routes`.

---

## Task 6: Claude Tokens — Service, Dependency, Management Routes

**Files:**
- Create: `backend/app/services/claude_token_service.py`, `backend/app/schemas/claude_token.py`
- Modify: `backend/app/api/deps.py` (add `get_claude_token`), `backend/app/api/settings.py` (token management routes)
- Create: `backend/app/api/claude.py` (router skeleton with only `GET /api/claude/ping`, so the boundary can be tested before Task 7 fills it in)
- Modify: `backend/app/main.py` (register the claude router)
- Test: `backend/tests/services/test_claude_token_service.py`, `backend/tests/api/test_claude_auth_boundary.py`

**Interfaces:**
- Consumes: `ClaudeToken` (Task 1), `get_current_user` (P1 Task 3).
- Produces:
  - `claude_token_service.py`: `TOKEN_PREFIX = "ct_"`; `create_token(db) -> tuple[ClaudeToken, str]` returns `TOKEN_PREFIX + secrets.token_urlsafe(32)` as the plaintext and stores only `hashlib.sha256(plaintext).hexdigest()` plus the first 8 chars as `token_prefix`; `authenticate(db, raw: str, now=None) -> ClaudeToken | None` (looks up by hash, rejects revoked tokens, updates `last_used_at`); `list_tokens(db) -> list[ClaudeToken]`; `revoke_token(db, token_id, now=None) -> ClaudeToken`.
  - `deps.get_claude_token(request: Request, db = Depends(get_db)) -> ClaudeToken` reads **only** the `Authorization: Bearer` header (never cookies). Missing, malformed, unknown or revoked → `HTTPException(401, detail="invalid claude token")`.
  - `schemas/claude_token.py`: `ClaudeTokenOut` (`id`, `token_prefix`, `created_at`, `last_used_at`, `revoked_at`), `ClaudeTokenCreatedOut` (`ClaudeTokenOut` fields + `token: str`).
  - Cookie-protected: `GET /api/settings/claude-tokens` → `list[ClaudeTokenOut]`; `POST /api/settings/claude-tokens` → 201 `ClaudeTokenCreatedOut` (the only response that ever contains the plaintext); `POST /api/settings/claude-tokens/{id}/revoke` → `ClaudeTokenOut`.
  - `api/claude.py`: `router = APIRouter(prefix="/api/claude", dependencies=[Depends(get_claude_token)])`; `GET /api/claude/ping` → `{"ok": true}`.

- [ ] **Step 1: Write the failing tests.** Service: the plaintext is never stored (no column equals it); `authenticate` accepts the plaintext, rejects a wrong value, and rejects it after `revoke_token`. Boundary, in `test_claude_auth_boundary.py`:

```python
def test_claude_route_accepts_valid_bearer(client, db_session):
    _, raw = create_token(db_session)
    assert client.get("/api/claude/ping", headers={"Authorization": f"Bearer {raw}"}).status_code == 200

def test_claude_route_rejects_session_cookie(logged_in_client):
    r = logged_in_client.get("/api/claude/ping")
    assert r.status_code == 401 and r.json() == {"detail": "invalid claude token"}

def test_claude_token_rejected_on_cookie_routes(client, db_session):
    _, raw = create_token(db_session)
    for path in ["/api/applications", "/api/contacts", "/api/settings", "/api/settings/claude-tokens"]:
        assert client.get(path, headers={"Authorization": f"Bearer {raw}"}).status_code == 401

def test_revoked_token_rejected(client, db_session): ...
def test_malformed_authorization_header_rejected(client): ...   # "Bearer", "Basic xyz", "" → 401
def test_token_list_never_contains_plaintext(logged_in_client): ...  # create, then list: no "token" key in any item
```

- [ ] **Step 2: Run** — expected FAIL. **Step 3: Implement.** **Step 4: Run** — expected PASS. Run the full suite.
- [ ] **Step 5: Commit** — `feat: claude bearer tokens with strict auth boundary`.

---

## Task 7: Claude Job API — Work List, Contact Upsert, Follow-ups, Queue Completion

**Files:**
- Create: `backend/app/schemas/claude.py`, `backend/app/services/claude_ingest_service.py`
- Modify: `backend/app/api/claude.py` (replace `ping` with the real routes)
- Test: `backend/tests/services/test_claude_ingest_service.py`, `backend/tests/api/test_claude_routes.py`

**Interfaces:**
- Consumes: Tasks 1–4, 6.
- Produces:
  - `schemas/claude.py` (all `str` fields stripped; caps given as max lengths):
    - `SourceIn(label: str ≤200, url: str ≤2000)`
    - `ContactIn(queue_item_id: int, name ≤200 required, organization ≤200 required, department ≤200?, title ≤200?, lab_name ≤200?, email ≤320?, email_confidence: EmailConfidence, website_url ≤2000?, profile_url ≤2000?, relevance_note ≤1000?, research_summary ≤5000?, recent_work ≤5000?, sources: list[SourceIn] ≤20 items, draft_subject ≤300?, draft_body ≤10000?)`
    - `ContactsBatchIn(contacts: list[ContactIn] ≤25 items)`
    - `FollowupIn(contact_id: int, followup_subject ≤300, followup_body ≤10000)`; `FollowupsBatchIn(followups: list[FollowupIn] ≤25)`
    - `QueueResultIn(result_note: str ≤1000)`; `IngestResultOut(created: int, updated: int, skipped: int)`
    - `WorkOut(queue: list[{id, kind, request_text, target_count}], outreach_profile: str, known_contacts: list[{name, organization, email}], followups_needed: list[{contact_id, name, organization, draft_subject, draft_body, sent_at}])`
  - `claude_ingest_service.py`:
    - `is_safe_url(url: str | None) -> bool` — true only for an `http`/`https` scheme with a non-empty host.
    - `get_work(db, today: date) -> dict` — at most `claude_job_max_items` pending items (oldest first); `known_contacts` covers all non-archived contacts; `followups_needed` uses `needs_followup_draft`.
    - `upsert_contacts(db, batch: ContactsBatchIn, now=None) -> IngestResultOut`. Per item: skip it (`skipped += 1`) if `queue_item_id` is missing or not pending. Drop unsafe `website_url`/`profile_url`/source entries. If `email_confidence == FOUND` and no safe sources remain, downgrade to `PATTERN_GUESS`. Derive `kind`/`application_id` from the queue item (`COMPANY_CONTACTS` → `COMPANY` + its `application_id`, else `PROFESSOR`); the payload never sets them. Match an existing contact by case-insensitive `email`, else case-insensitive (`name`, `organization`).
      - **On a match:** update only the research fields listed in spec §13.2; update `draft_subject`/`draft_body` only if `draft_edited` is false; set `draft_ready_at = now` if it was None and the draft is now non-empty; never touch status, dates, priority, notes, archived, origin.
      - **New:** `origin=CLAUDE`, `status=TO_CONTACT`, `draft_ready_at=now` if there's a draft.
    - `apply_followups(db, batch: FollowupsBatchIn) -> IngestResultOut` — skips unknown contacts and those with `followup_edited=True`.
    - `complete_queue_item` / `fail_queue_item` — delegate to Task 4.
  - Routes on the Task 6 claude router: `GET /api/claude/work` → `WorkOut`; `POST /api/claude/contacts` body `ContactsBatchIn` → `IngestResultOut`; `POST /api/claude/followups` body `FollowupsBatchIn` → `IngestResultOut`; `POST /api/claude/queue/{id}/complete` and `/failed` body `QueueResultIn` → `QueueItemOut` (404 unknown, 409 `{"detail": "queue item not pending"}`). An oversized or malformed body → 422 with nothing written (a single transaction per request).

- [ ] **Step 1: Write the failing service tests** (`test_claude_ingest_service.py`):

```python
def test_new_company_contact_takes_kind_and_application_from_queue_item(db_session): ...
def test_reingest_preserves_user_owned_fields_and_edited_draft(db_session):
    # Claude creates a contact with a draft; the user edits the draft, sends, and adds notes; Claude re-delivers with a new draft and a new research_summary
    # → draft_body still the user's text, status SENT, notes unchanged, research_summary updated, updated == 1
def test_unedited_draft_is_refreshed(db_session): ...
def test_dedup_by_email_case_insensitive_then_name_org(db_session): ...
def test_unsafe_urls_dropped(db_session):
    # website_url="javascript:alert(1)", sources=[{"label":"x","url":"data:text/html,..."}, {"label":"ok","url":"https://cs.stanford.edu/~jlee"}]
    # → website_url is None, sources == [{"label": "ok", "url": "https://cs.stanford.edu/~jlee"}]
def test_found_email_without_safe_source_downgraded(db_session): ...
def test_item_for_unknown_or_done_queue_item_skipped(db_session): ...
def test_followup_not_applied_when_edited(db_session): ...
def test_get_work_respects_max_items_and_lists_followups(db_session): ...
```

- [ ] **Step 2: Write the failing route tests** (`test_claude_routes.py`, authenticated with a token from `create_token`). Cover:
  - a `contacts` payload with 26 items → 422 and no contacts exist;
  - a `research_summary` of 5001 chars → 422;
  - the complete → 200, complete again → 409 sequence;
  - `/api/claude/work` shape contains `queue`, `outreach_profile`, `known_contacts`, `followups_needed`.
- [ ] **Step 3: Run** — expected FAIL. **Step 4: Implement.** **Step 5: Run** — expected PASS. Run the full suite.
- [ ] **Step 6: Commit** — `feat: claude job API — work list, contact upsert with dedup and protections, follow-ups, queue completion`.

---

## Task 8: Backup Google Sheet Sync

**Files:**
- Create: `backend/app/services/sheets_client.py`, `backend/app/services/sheet_sync_service.py`, `backend/app/jobs/__init__.py`, `backend/app/jobs/nightly_sheet_sync.py`
- Modify: `backend/app/services/google_docs_service.py` (add the `drive.file` scope to the authorization URL)
- Modify: `backend/app/api/deps.py` (add `get_sheet_sync_scheduler`)
- Modify: `backend/app/api/applications.py`, `backend/app/api/contacts.py`, `backend/app/api/claude.py` (schedule a sync after every successful write)
- Modify: `backend/app/api/settings.py` (`POST /api/settings/sheet-sync`)
- Modify: `docker-compose.yml` (add the `sheet-sync` service)
- Test: `backend/tests/services/test_sheet_sync_service.py`, `backend/tests/api/test_sheet_sync_hooks.py`, `backend/tests/jobs/test_nightly_sheet_sync.py`, plus one assertion added to the Google OAuth tests

**Interfaces:**
- Consumes: `get_valid_access_token` (P1 Task 7, raises `GoogleAuthError` when Google isn't connected or refresh fails), Tasks 1–3, 7.
- Produces:
  - `sheets_client.py`: `class SheetsClient(Protocol)` with `create_spreadsheet(title: str, tab_titles: list[str]) -> str` and `replace_tab(spreadsheet_id: str, tab: str, rows: list[list[str]]) -> None`. `class GoogleSheetsClient(SheetsClient)` built from an access token: `POST https://sheets.googleapis.com/v4/spreadsheets`, then `values:clear` + `values` `PUT` with `valueInputOption=RAW` on `'<tab>'!A1`. Any non-2xx response or `httpx.HTTPError` → `SheetSyncError` (add it to `errors.py`).
  - `sheet_sync_service.py`:
    - `SHEET_TITLE = "Internship Tracker Backup"`; `TAB_APPLICATIONS = "Applications"`, `TAB_PROFESSORS = "Professors"`, `TAB_COMPANY = "Company Contacts"`; `HEADER_NOTE = "One-way backup mirror of Internship Tracker — edits made here are overwritten."`
    - `application_rows(apps) -> list[list[str]]` and `contact_rows(contacts_with_nudges) -> list[list[str]]`. Row 1 is `[HEADER_NOTE]`, row 2 the column headers, then one row per record keyed by id in column A. Every value is rendered as a string (`""` for None, ISO dates). Contact rows include `status`, `email`, `email_confidence`, `sent_at`, `followed_up_at`, `replied_at`, `draft_subject`, `draft_body`, and `Needs Attention` (the nudge value or `""`). Archived records are included, flagged in an `archived` column.
    - `sync_tabs(db, client: SheetsClient, tabs: Iterable[str], now=None) -> None` — creates the spreadsheet on first use (storing `backup_sheet_id`), then rewrites each named tab from the current DB state. Whole-tab rewrite is deliberate: at personal scale it is simpler and self-healing compared with row patching, and it satisfies §13.7's "row re-synced".
    - `safe_sync(db, client_factory: Callable[[Session], SheetsClient], tabs, now=None) -> bool` — catches **every** exception, records `last_sheet_sync_error` and returns False. The message is exactly `"google not connected"` for `GoogleAuthError`; otherwise it is `"sheet sync failed: <exception message, truncated to 300 chars>"`; on success sets `last_sheet_sync_at=now`, clears the error, and returns True.
    - `ALL_TABS = (TAB_APPLICATIONS, TAB_PROFESSORS, TAB_COMPANY)`.
  - `deps.get_sheet_sync_scheduler() -> SheetSyncScheduler` with `schedule(background_tasks: BackgroundTasks, tabs: Iterable[str]) -> None`. The real implementation adds a background task that opens its **own** `SessionLocal()` session (the request session is closed by then), builds a `GoogleSheetsClient` from `get_valid_access_token`, calls `safe_sync`, commits, and closes. Tests override the dependency with a recorder.
  - Hooks:
    - application create/patch/status/archive → `[TAB_APPLICATIONS]`;
    - contact mutations → `[TAB_PROFESSORS, TAB_COMPANY]`;
    - `/api/claude/contacts` and `/api/claude/followups` → `[TAB_PROFESSORS, TAB_COMPANY]`;
    - Task 4's auto-enqueue doesn't change sheet data, so no extra hook.
  - `POST /api/settings/sheet-sync` (cookie) runs `safe_sync` synchronously over `ALL_TABS` → `{"ok": bool, "last_sheet_sync_at", "last_sheet_sync_error", "sheet_url"}`, where `sheet_url = f"https://docs.google.com/spreadsheets/d/{id}"` or `null`.
  - `get_authorization_url` additionally requests `https://www.googleapis.com/auth/drive.file`.
  - `jobs/nightly_sheet_sync.py`: `seconds_until_next_run(now: datetime, hour: int = 3) -> float` (pure); `main()` loops forever, sleeping `seconds_until_next_run(datetime.now())` and then running `safe_sync` over `ALL_TABS` in a fresh session. `if __name__ == "__main__": main()`.
  - `docker-compose.yml`: a `sheet-sync` service with the same build/env as `backend`, `command: python -m app.jobs.nightly_sheet_sync`, `depends_on: [db]`, `restart: unless-stopped`, and `TZ` taken from `.env` (add `TZ=America/Chicago` to `.env.example` as an example value).

- [ ] **Step 1: Write the failing service tests** with an in-memory `FakeSheetsClient` (records `created` titles/tabs and `replaced[tab] = rows`; an optional `fail=True` raises `SheetSyncError`):

```python
def test_first_sync_creates_sheet_and_stores_id(db_session): ...      # backup_sheet_id set; created == [("Internship Tracker Backup", [...ALL_TABS])]
def test_second_sync_reuses_sheet(db_session): ...
def test_contact_tabs_split_by_kind_with_header_note(db_session):
    # one professor + one company contact → replaced["Professors"][0] == [HEADER_NOTE], 3 rows total; same for "Company Contacts"
def test_needs_attention_column_filled(db_session): ...
def test_safe_sync_records_error_and_returns_false(db_session): ...   # fail=True → False, last_sheet_sync_error set, no exception
def test_safe_sync_handles_google_not_connected(db_session): ...      # client_factory raises GoogleAuthError → False, last_sheet_sync_error == "google not connected"
```

- [ ] **Step 2: Write the failing hook tests** (`test_sheet_sync_hooks.py`) overriding `get_sheet_sync_scheduler` with a recorder:
  - creating an application schedules `["Applications"]`;
  - a contact action schedules both contact tabs;
  - a `/api/claude/contacts` upsert schedules both contact tabs;
  - with the real scheduler and Google not connected, `POST /api/applications` still returns 201. Patch `SessionLocal` in the scheduler module to yield the test session so nothing touches the dev DB.
- [ ] **Step 3: Write the failing scope and job tests**: the authorization URL contains `drive.file` (URL-encoded); `seconds_until_next_run(datetime(2026,10,6,2,0)) == 3600` and `seconds_until_next_run(datetime(2026,10,6,3,0)) == 86400`.
- [ ] **Step 4: Run** — expected FAIL. **Step 5: Implement.** **Step 6: Run** — expected PASS. Run the full suite.
- [ ] **Step 7: Verify compose** — `docker compose config` parses and lists `sheet-sync`.
- [ ] **Step 8: Commit** — `feat: one-way Google Sheet backup with on-change and nightly sync`.

---

## Task 9: Frontend Contact Types, API Clients, Store & Helpers

**Files:**
- Create: `frontend/src/lib/types/contact.ts`, `frontend/src/lib/api/contacts.ts`, `frontend/src/lib/api/researchQueue.ts`, `frontend/src/lib/api/settings.ts`, `frontend/src/lib/stores/contacts.ts`, `frontend/src/lib/contacts/actions.ts`, `frontend/src/lib/contacts/gmail.ts`
- Modify: `frontend/src/lib/testing/fixtures.ts` (add `fakeContact`)
- Test: `frontend/src/lib/api/contacts.test.ts`, `frontend/src/lib/contacts/actions.test.ts`, `frontend/src/lib/contacts/gmail.test.ts`

**Interfaces:**
- Consumes: `apiFetch`, `showToast` (P1 Task 9), fixture conventions (P1 Task 10).
- Produces:
  - `types/contact.ts`:
    - String unions mirroring the backend enums exactly: `ContactKind`, `ContactStatus`, `EmailConfidence`, `ContactOrigin`, `ContactAction`, `NudgeKind`, `QueueKind`, `QueueState`.
    - `interface Contact`, camelCase of every `ContactOut` field: `id, kind, name, organization, department, title, labName, email, emailConfidence, websiteUrl, profileUrl, applicationId, relevanceNote, researchSummary, recentWork, sources: {label: string; url: string}[], draftSubject, draftBody, draftEdited, followupSubject, followupBody, followupEdited, draftReadyAt, status, closedReason, priority, sentAt, followedUpAt, repliedAt, meetingAt, nudgeSnoozedUntil, notes, origin, archived, createdAt, updatedAt, nudge`.
    - `ContactInput`, `ContactHistoryEntry`, `ContactActivityEntry`, `QueueItem`, `AppSettings`, `ClaudeTokenInfo`, `ClaudeTokenCreated`, `SheetSyncResult`.
  - `api/contacts.ts`: `mapContactFromApi(raw): Contact`; `listContacts(opts?: {kind?: ContactKind; applicationId?: number; includeArchived?: boolean})`; `getContact`; `createContact`; `updateContact(id, data: Partial<ContactInput & {draftSubject; draftBody; followupSubject; followupBody}>)`; `applyContactAction(id, action, opts?: {on?: string; meetingAt?: string})`; `moveContactStatus(id, status)`; `undoContactAction(id)`; `snoozeContact(id, days)`; `archiveContact(id)`; `getContactHistory(id)`; `getContactActivity(limit?)`; `getNeedsAttention()`.
  - `api/researchQueue.ts`: `listQueue(state?)`, `addQueueItem({kind, requestText, targetCount})`, `findContacts(applicationId)`.
  - `api/settings.ts`: `getSettings`, `updateSettings`, `listClaudeTokens`, `createClaudeToken`, `revokeClaudeToken`, `syncSheetNow`.
  - `stores/contacts.ts`: `contacts = writable<Contact[]>([])`; `loadContacts(kind?: ContactKind)`; `replaceContact(updated: Contact)`; `runContactAction(id, action, opts?) => Promise<Contact | null>` (calls the API, replaces the store entry, and on `ApiError` calls `showToast` with the API `detail` and returns null).
  - `contacts/actions.ts`: `ACTIONS_BY_STATUS: Record<ContactStatus, ContactAction[]>` (same table as backend Task 2); `ACTION_LABELS: Record<ContactAction, string>` = Sent, Followed up, Replied, Meeting set, Accepted, Declined, No response; `statusLabel(status: ContactStatus, kind: ContactKind): string` (`accepted` + `company` → `"Positive (referral/interview)"`); `NUDGE_LABELS: Record<NudgeKind, string>` = "Did you send this?", "Follow-up due", "Gone quiet — close it out?", "Any update?", "How did it go?".
  - `contacts/gmail.ts`: `MAX_GMAIL_URL_LENGTH = 2000`; `gmailComposeUrl(to: string, subject: string, body: string): string` → `https://mail.google.com/mail/?view=cm&fs=1&to=…&su=…&body=…`, each param `encodeURIComponent`-encoded; `fitsInGmailUrl(url: string): boolean`.
  - `fixtures.ts`: `fakeContact(overrides?: Partial<Contact>): Contact` — defaults `kind: "professor"`, `status: "to_contact"`, `emailConfidence: "not_found"`, `priority: "medium"`, `origin: "manual"`, `sources: []`, booleans false, `nudge: null`, nullable fields `null`.

- [ ] **Step 1: Write the failing tests:**
  - `mapContactFromApi` maps `email_confidence`, `draft_ready_at`, and `sources` correctly;
  - `ACTIONS_BY_STATUS` deep-equals the spec table;
  - `statusLabel("accepted", "company")` and `statusLabel("accepted", "professor")` return the expected labels;
  - `gmailComposeUrl("a@b.edu", "Hi & hello", "Line1\nLine2")` contains `to=a%40b.edu`, `su=Hi%20%26%20hello`, and `body=Line1%0ALine2`;
  - `fitsInGmailUrl` is false for a 3000-char body.
- [ ] **Step 2: Run** `npm run test -- --run` — expected FAIL. **Step 3: Implement.** **Step 4: Run** — expected PASS.
- [ ] **Step 5: Commit** — `feat: frontend contact types, api clients, store, and helpers`.

---

## Task 10: Contact Card, Status Buttons & Contacts Board

**Files:**
- Create: `frontend/src/lib/components/contacts/ContactStatusButtons.svelte`, `frontend/src/lib/components/contacts/NudgeBadge.svelte`, `frontend/src/lib/components/contacts/ContactCard.svelte`, `frontend/src/lib/components/contacts/ContactBoard.svelte`
- Test: `frontend/src/lib/components/contacts/ContactStatusButtons.test.ts`, `frontend/src/lib/components/contacts/ContactCard.test.ts`

**Interfaces:**
- Consumes: Task 9.
- Produces:
  - **`ContactStatusButtons.svelte`** (props `contact: Contact`):
    - renders one button per `ACTIONS_BY_STATUS[contact.status]`, labeled from `ACTION_LABELS`;
    - each has a small "it was actually on…" date input that is collapsed by default;
    - `meeting_set` opens a datetime input and is required before submit;
    - on click it calls `runContactAction`;
    - after a successful action it shows an **Undo** button for 60 s, which calls `undoContactAction` and `replaceContact`.
  - **`NudgeBadge.svelte`** (props `nudge: NudgeKind | null`): renders `NUDGE_LABELS[nudge]`, or nothing.
  - **`ContactCard.svelte`** (props `contact: Contact`, event `open`):
    - shows name, organization, title, and an email-confidence badge (`found` → "Email found", `pattern_guess` → "Email guessed", `not_found` → "No email");
    - shows a "Draft ready" badge when `draftBody && status === "to_contact"`, plus `NudgeBadge` and `ContactStatusButtons`;
    - is `draggable="true"` with the id as drag data;
    - all text is interpolated with `{…}` and never `{@html}`.
  - **`ContactBoard.svelte`**:
    - a filter toggle (Professors / Company / All) that calls `loadContacts(kind)`;
    - one column per `ContactStatus` in pipeline order, columns labeled with `statusLabel(status, filterKind ?? "professor")` (so `accepted` reads "Positive (referral/interview)" under the Company filter);
    - archived contacts are excluded;
    - dropping a card calls `moveContactStatus`, with a `showToast` on `ApiError` (an invalid drag shows the backend's 422 detail);
    - clicking a card dispatches `open` with the contact.

- [ ] **Step 1: Write the failing tests:**
  - for each status, `ContactStatusButtons` renders exactly the labels from the spec table (parametrized over the seven statuses; `accepted`/`declined` render no buttons);
  - clicking **Sent** calls `applyContactAction(id, "sent", …)` (mock `api/contacts`);
  - `ContactCard` shows "Draft ready" only for `to_contact` with a draft;
  - `ContactCard` renders `name: "<b>x</b>"` as literal text (`getByText("<b>x</b>")` exists, and `container.querySelector("b")` is null).
- [ ] **Step 2: Run** — expected FAIL. **Step 3: Implement.** **Step 4: Run** — expected PASS.
- [ ] **Step 5: Commit** — `feat: contact card, status buttons with undo, contacts board`.

---

## Task 11: Contact Detail Panel — Research, Drafts, Open in Gmail

**Files:**
- Create: `frontend/src/lib/components/contacts/DraftEditor.svelte`, `frontend/src/lib/components/contacts/ContactDetailPanel.svelte`
- Test: `frontend/src/lib/components/contacts/DraftEditor.test.ts`, `frontend/src/lib/components/contacts/ContactDetailPanel.test.ts`

**Interfaces:**
- Consumes: Task 9–10.
- Produces:
  - **`DraftEditor.svelte`** (props `contact: Contact`, `which: "draft" | "followup"`):
    - editable subject/body; **Save** calls `updateContact` with the matching fields;
    - **Open in Gmail** builds `gmailComposeUrl(contact.email ?? "", subject, body)`. If `!fitsInGmailUrl(url)` it is replaced by a note to use Copy. If `emailConfidence === "pattern_guess"`, clicking first shows a `confirm()` with exactly `"This address is a guess and may bounce. Open anyway?"`. On open, `window.open(url, "_blank", "noopener")` runs and the editor shows **"Did you send it?"** with [Sent] (calls `runContactAction(id, which === "draft" ? "sent" : "followed_up")`) and [Not yet] (hides the prompt).
    - **Copy** copies `Subject: …\n\n…` via `navigator.clipboard.writeText`.
  - **`ContactDetailPanel.svelte`** (props `contact: Contact`):
    - identity fields, `relevanceNote`, `researchSummary`, and `recentWork` as plain text, preserving line breaks with CSS `white-space: pre-wrap`, never `{@html}`;
    - `sources` as `<a href={url} target="_blank" rel="noopener noreferrer">{label}</a>`, rendered only when the url starts with `http://` or `https://` (defense in depth on top of Task 7);
    - a `DraftEditor` for the draft, and one for the follow-up when `followupBody` exists or status is `sent`/`followed_up`;
    - `ContactStatusButtons`, a history timeline via `getContactHistory`, an editable notes field and a priority select (Save → `updateContact`), and an **Archive** button (confirm, then `archiveContact`).

- [ ] **Step 1: Write the failing tests:**
  - `DraftEditor` with `pattern_guess` calls `confirm` before `window.open`, and doesn't open when confirm returns false;
  - with `found` it opens without confirm, and the opened URL starts with `https://mail.google.com/mail/?view=cm`;
  - after open, "Did you send it?" appears, and [Sent] calls `applyContactAction(id, "sent", …)`;
  - `ContactDetailPanel` renders `researchSummary: '<img src=x onerror="alert(1)">'` as text with no `img` element in the DOM;
  - a source with `url: "javascript:alert(1)"` produces no anchor.
- [ ] **Step 2: Run** — expected FAIL. **Step 3: Implement.** **Step 4: Run** — expected PASS.
- [ ] **Step 5: Commit** — `feat: contact detail panel with draft editor and open-in-gmail flow`.

---

## Task 12: Contacts & Research Queue Pages, Navigation

**Files:**
- Create: `frontend/src/routes/Contacts.svelte`, `frontend/src/routes/ResearchQueue.svelte`
- Modify: `frontend/src/App.svelte` (**add** `/contacts` and `/research-queue` routes; leave every existing route entry exactly as found), `frontend/src/lib/components/NavSidebar.svelte` (add "Contacts" and "Research Queue" links after "Applications"; leave the disabled "coming soon" entries as they are)
- Test: `frontend/src/routes/ResearchQueue.test.ts`

**Interfaces:**
- Consumes: Tasks 9–11.
- Produces:
  - **`Contacts.svelte`:** a `ContactBoard` plus a slide-over `ContactDetailPanel` for the opened contact, and an "Add contact" form (`kind`, `name`, `organization`, `email`, `title`) calling `createContact`.
  - **`ResearchQueue.svelte`:**
    - a form with a kind toggle ("A specific professor" → `professor_person`, "Search brief" → `professor_search` with a target-count input of 1–10), calling `addQueueItem`;
    - a list grouped Pending / Done / Failed showing `requestText`, `kind`, `createdAt`, and `resultNote` as plain text;
    - a short line explaining that items are processed by the daily Claude job.

- [ ] **Step 1: Write the failing test**: submitting the form in "Search brief" mode calls `addQueueItem({kind: "professor_search", requestText: "5 ML-for-robotics profs at UIUC", targetCount: 5})`; a failed item's `resultNote` is visible.
- [ ] **Step 2: Run** — expected FAIL. **Step 3: Implement** both pages, the routes, and the nav entries. **Step 4: Run** — expected PASS.
- [ ] **Step 5: Manually verify** with `npm run dev` against a seeded backend: the board filters by kind; a status button moves a card and Undo restores it; the queue form adds an item.
- [ ] **Step 6: Commit** — `feat: contacts and research queue pages with navigation`.

---

## Task 13: Dashboard & Application Integration — Needs Attention, Merged Activity, Application Contacts

**Files:**
- Create: `frontend/src/lib/components/widgets/NeedsAttention.svelte`, `frontend/src/lib/dashboard/activity.ts`
- Modify: `frontend/src/lib/components/widgets/RecentActivityFeed.svelte` (merge contact activity), `frontend/src/routes/Dashboard.svelte` (add the widget to `defaultLayout`), `frontend/src/lib/components/ApplicationDetailPanel.svelte` (Contacts section and Find contacts button)
- Test: `frontend/src/lib/dashboard/activity.test.ts`, `frontend/src/lib/components/widgets/NeedsAttention.test.ts`

**Interfaces:**
- Consumes: `getRecentActivity`, `ActivityEntry` (P1 Task 10), `DashboardGrid`/`WidgetLayoutEntry` (P1 Task 14), Task 9–11.
- Produces:
  - `dashboard/activity.ts`: `type FeedItem = { kind: "application" | "contact"; label: string; oldStatus: string | null; newStatus: string; changedAt: string }`; `mergeActivity(apps: ActivityEntry[], contacts: ContactActivityEntry[], limit: number): FeedItem[]`, sorted by `changedAt` descending and truncated to `limit`. The application label is `` `${company} — ${roleTitle}` ``; the contact label is `` `${name} (${organization})` ``.
  - `RecentActivityFeed.svelte` fetches both lists and renders `mergeActivity(...)`. Its existing content-amount setting (3/5/10) is passed as `limit`.
  - **`NeedsAttention.svelte`:**
    - loads `getNeedsAttention()` and lists each contact with `NUDGE_LABELS[nudge]` and that nudge's action buttons:
      - `unsent` → [Sent] (with date input) [Not yet] (snooze 3) [Skip] (archive);
      - `followup_due` → [Open follow-up] (opens `ContactDetailPanel`) [Followed up];
      - `gone_quiet` → [No response] [Wait longer] (snooze 7);
      - `replied_stale` → `ContactStatusButtons`;
      - `meeting_outcome` → [Accepted] [Declined] [Still talking] (snooze 7);
    - refreshes the list after each action;
    - widget id `"needs-attention"`, added to Dashboard's `defaultLayout`. Existing saved layouts that lack this id still render it: `loadLayout` returns saved entries, so Dashboard appends any `defaultLayout` entry whose id is missing from the loaded layout.
  - **`ApplicationDetailPanel.svelte` Contacts section:**
    - `listContacts({kind: "company", applicationId})` rendered as compact `ContactCard`s;
    - a **Find contacts** button calling `findContacts(application.id)`; a 409 shows the toast "Contacts already queued for this application.";
    - empty state text: "No contacts yet — they'll appear after the daily Claude run."

- [ ] **Step 1: Write the failing tests**: `mergeActivity` interleaves both sources newest first and respects `limit`; `NeedsAttention` renders "Gone quiet — close it out?" with [No response] and [Wait longer], and [Wait longer] calls `snoozeContact(id, 7)`.
- [ ] **Step 2: Run** — expected FAIL. **Step 3: Implement**, including the Dashboard layout-append for missing widget ids. **Step 4: Run** — expected PASS.
- [ ] **Step 5: Commit** — `feat: needs-attention widget, merged activity feed, application contacts section`.

---

## Task 14: Settings Page — Outreach Profile, Nudge Timings, Claude Tokens, Backup Sheet

**Files:**
- Create: `frontend/src/routes/Settings.svelte`, `frontend/src/lib/components/settings/ClaudeTokens.svelte`, `frontend/src/lib/components/settings/BackupSheetStatus.svelte`
- Modify: `frontend/src/App.svelte` (**add** a `/settings` route; leave the other entries untouched), `frontend/src/lib/components/NavSidebar.svelte` (a "Settings" link at the bottom)
- Test: `frontend/src/lib/components/settings/ClaudeTokens.test.ts`

**Interfaces:**
- Consumes: `api/settings.ts` (Task 9).
- Produces:
  - **`Settings.svelte`:** an outreach-profile textarea (placeholder: "Your background, interests, and what you're looking for — Claude uses this to personalize every draft."), four nudge-day number inputs (1–90), and a max-items-per-run input (1–25), saved with one **Save** button via `updateSettings`. It hosts the two components below.
  - **`ClaudeTokens.svelte`:**
    - lists tokens by `tokenPrefix`, `createdAt`, `lastUsedAt` and revoked state;
    - **Create token** shows the plaintext once in a read-only field with Copy and the text "Copy this now — it won't be shown again.";
    - the plaintext is cleared from component state when the user dismisses it or navigates away;
    - **Revoke** asks for confirmation, then calls `revokeClaudeToken`.
  - **`BackupSheetStatus.svelte`:** shows the sheet link (when `backupSheetId` is set), `lastSheetSyncAt`, and `lastSheetSyncError` (highlighted when present), plus a **Sync now** button calling `syncSheetNow`. When `lastSheetSyncError === "google not connected"`, it shows a "Connect Google" link to `/api/docs/google/authorize`.

- [ ] **Step 1: Write the failing test**: after **Create token**, the plaintext appears with the "won't be shown again" text; after dismiss, it's gone from the DOM; the token list (mocked) never renders a `token` field.
- [ ] **Step 2: Run** — expected FAIL. **Step 3: Implement**, including the route and nav link. **Step 4: Run** — expected PASS.
- [ ] **Step 5: Commit** — `feat: settings page with outreach profile, nudge timings, claude tokens, backup sheet status`.

---

## Task 15: Claude Routine Instructions & End-to-End Job Contract Test

**Files:**
- Create: `ops/claude-routine/outreach-job.md`
- Test: `backend/tests/api/test_claude_job_flow.py`

**Interfaces:**
- Consumes: Tasks 4, 6, 7 (the exact `/api/claude/*` contract).
- Produces:
  - `ops/claude-routine/outreach-job.md` — the routine's full instructions, written to Claude:
    - **Setup:** read `APP_BASE_URL` and `CLAUDE_TOKEN` from the routine's configuration and send `Authorization: Bearer $CLAUDE_TOKEN` on every call.
    - **Fetch:** `GET /api/claude/work` first.
    - **Per queue item:** research it with web search/fetch on public sources only. Never log into sites and never scrape LinkedIn; public search-result snippets are fine.
    - **Batch posting:** post contacts in batches of at most 25 with `queue_item_id` set, and every fact backed by a `sources` entry.
    - **Email confidence rules:** `found` only for an address seen published on a cited page; `pattern_guess` when inferring from the organization's published format, with the example address noted in `relevance_note`; `not_found` otherwise. Never present a guess as found.
    - **Draft guidelines:**
      - first-contact drafts are under 180 words, personalized from `outreach_profile` and one specific piece of the contact's work;
      - company-contact drafts reference the role applied to (from `request_text`);
      - follow-ups are under 90 words and reference the original.
    - **Item completion:** complete each item with a `result_note` stating how many contacts were found versus the target, and why any fell short. Fail an item only when research is impossible (e.g. the professor can't be identified).
    - **Error handling:** on 401, stop and report a token problem; on 422, fix the payload and retry once.
    - **Final step:** `POST /api/claude/followups` for every `followups_needed` entry.
    - **Setup appendix for the user:** how to create the scheduled routine (daily 07:00 local) with the `schedule` skill, and that it only works once the app is publicly deployed (spec §13.5).
  - `test_claude_job_flow.py` — one test that walks the documented contract end to end through the API with a real token:
    1. queue a professor and an application marked applied;
    2. `GET /work` lists both;
    3. post contacts for both (one with `pattern_guess`);
    4. complete both items;
    5. backdate a contact's `sent_at` by 9 days via the service;
    6. `GET /work` lists it in `followups_needed`;
    7. post the follow-up;
    8. assert the final DB state: two contacts, the right kinds, the company contact linked to the application, both queue items `done`, `followup_body` set.

- [ ] **Step 1: Write the failing flow test.** **Step 2: Run** — expected to PASS if Tasks 4–7 are correct. If it fails, fix the defect in the owning task's code, note it in the report, and re-run.
- [ ] **Step 3: Write `ops/claude-routine/outreach-job.md`**, making every endpoint, field name, and limit match `schemas/claude.py` exactly. Check by grepping each field name in the doc against the schema file.
- [ ] **Step 4: Run the full backend and frontend suites** — expected all PASS.
- [ ] **Step 5: Commit** — `feat: claude routine instructions and end-to-end job contract test`.
- [ ] **Post-deployment (not an implementer step):** once the app is live, the user creates a Claude token in Settings and the controller sets up the daily routine with the `schedule` skill using `ops/claude-routine/outreach-job.md`.
