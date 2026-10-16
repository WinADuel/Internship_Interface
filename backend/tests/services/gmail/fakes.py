"""An in-memory Gmail for sync tests, and helpers to build its messages."""

import re
from datetime import datetime

from app.core.security import encrypt_value
from app.models.gmail_account import GmailAccount
from app.services.gmail.client import GmailError, GmailMessage
from app.services.google_docs_service import GMAIL_SCOPE


def grant_gmail(db, email: str | None = "me@gmail.com", refresh_token: str = "refresh") -> GmailAccount:
    """Connect an inbox (`email=None`: one carried over from Phase 6)."""
    account = GmailAccount(email=email, encrypted_refresh_token=encrypt_value(refresh_token), scopes=GMAIL_SCOPE)
    db.add(account)
    db.commit()
    return account


def ms(when: datetime) -> int:
    return int(when.timestamp() * 1000)


def message(
    mid: str,
    when: datetime,
    *,
    from_: str = "Someone <someone@example.com>",
    subject: str = "Hello",
    snippet: str = "",
    to: str = "me@gmail.com",
    cc: str | None = None,
    labels: tuple[str, ...] = ("INBOX",),
    thread: str | None = None,
) -> GmailMessage:
    headers = {"from": from_, "to": to, "subject": subject}
    if cc is not None:
        headers["cc"] = cc
    return GmailMessage(
        id=mid,
        thread_id=thread or f"t{mid}",
        internal_date=ms(when),
        label_ids=labels,
        headers=headers,
        snippet=snippet,
    )


class FakeGmailClient:
    """One inbox (`address`). Lists the messages it holds, newest first,
    honouring the query's `after:<seconds>` (the query is recorded);
    `fail_on` makes a get raise for that id."""

    def __init__(
        self, messages=(), fail_on: dict[str, GmailError] | None = None, address: str = "me@gmail.com"
    ):
        self.messages = {m.id: m for m in messages}
        self.fail_on = fail_on or {}
        self.address = address
        self.queries: list[str] = []
        self.gets: list[str] = []
        self.profiles = 0
        self.closed = False

    def get_profile(self) -> str:
        self.profiles += 1
        return self.address

    def add(self, *messages: GmailMessage) -> None:
        for m in messages:
            self.messages[m.id] = m

    def list_message_ids(self, query: str, max_ids: int) -> tuple[list[str], bool]:
        self.queries.append(query)
        after = re.search(r"\bafter:(\d+)", query)
        since = int(after.group(1)) * 1000 if after else 0
        held = [m for m in self.messages.values() if m.internal_date > since]
        ids = [m.id for m in sorted(held, key=lambda m: m.internal_date, reverse=True)]
        return ids[:max_ids], len(ids) > max_ids

    def get_metadata(self, message_id: str) -> GmailMessage | None:
        self.gets.append(message_id)
        if message_id in self.fail_on:
            raise self.fail_on[message_id]
        return self.messages.get(message_id)

    def close(self) -> None:
        self.closed = True

    def factory(self, db, account):
        return self


class FakeInboxes:
    """A Gmail client factory over several fake inboxes, chosen by the
    account's id; records the order the inboxes were opened in. An entry
    that is an exception is raised instead (e.g. a refused token)."""

    def __init__(self, by_account: dict[int, "FakeGmailClient | Exception"]):
        self.by_account = by_account
        self.opened: list[int] = []

    def __call__(self, db, account):
        self.opened.append(account.id)
        client = self.by_account[account.id]
        if isinstance(client, Exception):
            raise client
        return client
