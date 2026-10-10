from datetime import datetime, timezone

from app.services.ics import escape_text, event_calendar, fold_line

START = datetime(2026, 10, 12, 15, 30, tzinfo=timezone.utc)
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)


def test_escape_text():
    assert escape_text("a,b;c\\d") == "a\\,b\\;c\\\\d"
    assert escape_text("one\r\ntwo\rthree\nfour") == "one\\ntwo\\nthree\\nfour"
    assert escape_text("tab\there\x00\x07\x1b") == "tab\there"


def test_short_line_is_not_folded():
    line = "S" * 75
    assert fold_line(line) == line


def test_long_line_folds_at_75_octets():
    folded = fold_line("SUMMARY:" + "x" * 200)
    physical = folded.split("\r\n")
    assert all(len(p.encode()) <= 75 for p in physical)
    assert len(physical[0].encode()) == 75
    assert all(p.startswith(" ") for p in physical[1:])
    assert "".join([physical[0], *(p[1:] for p in physical[1:])]) == "SUMMARY:" + "x" * 200


def test_folding_never_splits_a_multibyte_character():
    line = "SUMMARY:" + "é—" * 60
    physical = fold_line(line).split("\r\n")
    assert all(len(p.encode("utf-8")) <= 75 for p in physical)
    assert "".join([physical[0], *(p[1:] for p in physical[1:])]) == line


def test_event_calendar_content():
    body = event_calendar(
        uid="interview-round-7@internship-tracker",
        start=START,
        summary="Interview: Acme, Inc. — Technical",
        location="https://meet.example.com/abc",
        description="Role: SWE\nPrep page: https://t.example.com/#/interviews/7",
        url="https://t.example.com/#/interviews/7",
        now=NOW,
    )
    assert body.endswith("\r\n")
    assert "\n" not in body.replace("\r\n", "")
    lines = body.split("\r\n")
    assert lines[:6] == [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Internship Tracker//Interview Prep//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
    ]
    assert "UID:interview-round-7@internship-tracker" in lines
    assert "DTSTAMP:20261009T120000Z" in lines
    assert "DTSTART:20261012T153000Z" in lines
    assert "DTEND:20261012T163000Z" in lines  # default 60 minutes
    assert "SUMMARY:Interview: Acme\\, Inc. — Technical" in lines
    assert "LOCATION:https://meet.example.com/abc" in lines
    assert "DESCRIPTION:Role: SWE\\nPrep page: https://t.example.com/#/interviews/7" in lines
    assert "URL:https://t.example.com/#/interviews/7" in lines
    assert lines[-3:] == ["END:VEVENT", "END:VCALENDAR", ""]


def test_event_calendar_duration_times_in_utc_and_optional_fields():
    from datetime import timedelta

    local = START.astimezone(timezone(timedelta(hours=-7)))
    body = event_calendar(uid="u", start=local, summary="s", duration_minutes=45, now=NOW)
    assert "DTSTART:20261012T153000Z\r\n" in body and "DTEND:20261012T161500Z\r\n" in body
    assert "LOCATION" not in body and "DESCRIPTION" not in body and "URL:" not in body
