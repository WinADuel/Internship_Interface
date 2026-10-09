"""A one-event iCalendar file (RFC 5545) for "Add to calendar" on a prep page
(Phase 4 spec §4). It is a download from the logged-in session; there is no
calendar feed.

Text values are escaped (backslash, semicolon, comma, newline), control
characters other than tab are dropped, lines end in CRLF and are folded at
75 octets without splitting a UTF-8 character. Times are written in UTC."""

import re
from datetime import datetime, timedelta, timezone

PRODID = "-//Internship Tracker//Interview Prep//EN"
MAX_LINE_OCTETS = 75
DEFAULT_DURATION_MINUTES = 60

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def escape_text(value: str) -> str:
    """A TEXT property value: newlines become `\\n`, and `\\ ; ,` are escaped."""
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = _CONTROL_CHARS.sub("", value)  # keeps tab and newline
    value = value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return value.replace("\n", "\\n")


def fold_line(line: str) -> str:
    """Splits a content line so no physical line exceeds 75 octets; each
    continuation starts with one space (which counts toward its 75)."""
    if len(line.encode("utf-8")) <= MAX_LINE_OCTETS:
        return line
    parts: list[str] = []
    current, size = "", 0
    for char in line:
        width = len(char.encode("utf-8"))
        if size + width > MAX_LINE_OCTETS:
            parts.append(current)
            current, size = char, 1 + width
        else:
            current += char
            size += width
    parts.append(current)
    return "\r\n ".join(parts)


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def event_calendar(
    *,
    uid: str,
    start: datetime,
    summary: str,
    duration_minutes: int | None = None,
    location: str | None = None,
    description: str | None = None,
    url: str | None = None,
    now: datetime | None = None,
) -> str:
    """A VCALENDAR holding a single VEVENT."""
    now = now or datetime.now(timezone.utc)
    end = start + timedelta(minutes=duration_minutes or DEFAULT_DURATION_MINUTES)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{escape_text(uid)}",
        f"DTSTAMP:{_utc(now)}",
        f"DTSTART:{_utc(start)}",
        f"DTEND:{_utc(end)}",
        f"SUMMARY:{escape_text(summary)}",
    ]
    if location:
        lines.append(f"LOCATION:{escape_text(location)}")
    if description:
        lines.append(f"DESCRIPTION:{escape_text(description)}")
    if url:
        # URL is a URI value, not TEXT: it is not escaped.
        lines.append(f"URL:{_CONTROL_CHARS.sub('', url)}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "".join(fold_line(line) + "\r\n" for line in lines)
