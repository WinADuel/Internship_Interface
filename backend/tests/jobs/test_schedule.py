"""app/jobs/schedule: the nightly jobs' local-time schedule across
daylight-saving changes."""

import logging
from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.jobs import configure_job_logging, schedule
from app.jobs.schedule import local_zone, next_daily_run, wait_for_daily_run

CHICAGO = ZoneInfo("America/Chicago")  # springs forward 02:00 -> 03:00, falls back 02:00 -> 01:00
BERLIN = ZoneInfo("Europe/Berlin")  # falls back 03:00 -> 02:00, so 02:30 happens twice


def local(zone, *args, fold=0):
    return datetime(*args, tzinfo=zone, fold=fold)


class Clock:
    """A fake clock: sleep() moves it forward by `step(seconds)` (all of it by
    default), and every sleep and the times the job ran are recorded."""

    def __init__(self, start: datetime, step=lambda seconds: seconds):
        self.now = start.astimezone(UTC)
        self.step = step
        self.sleeps: list[float] = []

    def time(self) -> datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += timedelta(seconds=self.step(seconds))


def runs_over(clock: Clock, zone, hour: int, minute: int, until: datetime) -> list[datetime]:
    """The local times a daily hour:minute job would run, from the clock's start until `until`."""
    ran = []
    while True:
        target = next_daily_run(clock.time(), hour, minute, zone)
        if target > until:
            return ran
        wait_for_daily_run(hour, minute, sleep=clock.sleep, now=clock.time, zone=zone)
        ran.append(clock.time().astimezone(zone))
        clock.now += timedelta(minutes=3)  # the job itself takes a while


def test_a_normal_day_runs_at_0230_local():
    now = local(CHICAGO, 2026, 10, 6, 2, 0)
    assert next_daily_run(now, 2, 30, CHICAGO) == local(CHICAGO, 2026, 10, 6, 2, 30)
    assert next_daily_run(now, 2, 30, CHICAGO) == datetime(2026, 10, 6, 7, 30, tzinfo=UTC)  # CDT is UTC-5
    assert next_daily_run(local(CHICAGO, 2026, 10, 6, 23, 30), 2, 30, CHICAGO) == local(CHICAGO, 2026, 10, 7, 2, 30)


def test_right_at_or_just_after_the_run_time_schedules_tomorrow():
    assert next_daily_run(local(CHICAGO, 2026, 10, 6, 2, 30), 2, 30, CHICAGO) == local(CHICAGO, 2026, 10, 7, 2, 30)
    assert next_daily_run(local(CHICAGO, 2026, 10, 6, 2, 30, 1), 2, 30, CHICAGO) == local(
        CHICAGO, 2026, 10, 7, 2, 30
    )


def test_the_answer_is_the_same_instant_whatever_zone_now_is_given_in():
    now = local(CHICAGO, 2026, 10, 6, 2, 0)
    assert next_daily_run(now.astimezone(UTC), 2, 30, CHICAGO) == next_daily_run(now, 2, 30, CHICAGO)
    assert next_daily_run(now, 2, 30, CHICAGO).tzinfo is UTC


def test_the_sleep_across_a_spring_forward_night_is_an_hour_shorter():
    # 2026-03-08: Chicago skips 02:00-03:00. From 01:00 to 03:00 CDT is one hour.
    now = local(CHICAGO, 2026, 3, 7, 23, 0)
    assert next_daily_run(now, 3, 0, CHICAGO) - now == timedelta(hours=3)
    # A naive "same clock time tomorrow" would be 24 h; it's 23 h of real time.
    assert next_daily_run(local(CHICAGO, 2026, 3, 7, 3, 0), 3, 0, CHICAGO) - local(
        CHICAGO, 2026, 3, 7, 3, 0
    ) == timedelta(hours=23)


def test_spring_forward_day_runs_once_at_0330():
    # 02:30 doesn't exist on 2026-03-08 in Chicago; it runs as long after the
    # jump as 02:30 is after 02:00, i.e. at 03:30 CDT.
    clock = Clock(local(CHICAGO, 2026, 3, 6, 12, 0))
    ran = runs_over(clock, CHICAGO, 2, 30, until=local(CHICAGO, 2026, 3, 9, 12, 0))
    assert [(r.month, r.day, r.hour, r.minute) for r in ran] == [(3, 7, 2, 30), (3, 8, 3, 30), (3, 9, 2, 30)]
    assert ran[1].astimezone(UTC) == datetime(2026, 3, 8, 8, 30, tzinfo=UTC)


def test_fall_back_day_runs_once_at_the_first_0230():
    # 2026-10-25: Berlin goes from 03:00 CEST back to 02:00 CET; 02:30 happens twice.
    clock = Clock(local(BERLIN, 2026, 10, 24, 12, 0))
    ran = runs_over(clock, BERLIN, 2, 30, until=local(BERLIN, 2026, 10, 26, 12, 0))
    assert [(r.day, r.hour, r.minute) for r in ran] == [(25, 2, 30), (26, 2, 30)]
    assert ran[0].astimezone(UTC) == datetime(2026, 10, 25, 0, 30, tzinfo=UTC)  # the first one, CEST (UTC+2)


def test_just_after_the_first_of_two_0230s_waits_for_tomorrow():
    just_after_first = datetime(2026, 10, 25, 0, 31, tzinfo=UTC)  # 02:31 CEST
    assert next_daily_run(just_after_first, 2, 30, BERLIN) == local(BERLIN, 2026, 10, 26, 2, 30)
    # Also when "now" is given as the second 02:31 (CET) in Berlin's own zone.
    second = local(BERLIN, 2026, 10, 25, 2, 31, fold=1)
    assert second.astimezone(UTC) == datetime(2026, 10, 25, 1, 31, tzinfo=UTC)
    assert next_daily_run(second, 2, 30, BERLIN) == local(BERLIN, 2026, 10, 26, 2, 30)


def test_chicago_fall_back_day_runs_once():
    # 2026-11-01: Chicago repeats 01:00-02:00; 02:30 happens once, and 01:30 twice.
    clock = Clock(local(CHICAGO, 2026, 10, 31, 12, 0))
    ran = runs_over(clock, CHICAGO, 1, 30, until=local(CHICAGO, 2026, 11, 2, 12, 0))
    assert [(r.day, r.hour, r.minute) for r in ran] == [(1, 1, 30), (2, 1, 30)]
    assert ran[0].astimezone(UTC) == datetime(2026, 11, 1, 6, 30, tzinfo=UTC)  # CDT, the first 01:30


def test_waking_early_sleeps_again_instead_of_running():
    start = local(CHICAGO, 2026, 10, 6, 1, 30)
    clock = Clock(start, step=lambda seconds: min(seconds, 1000))
    ran_at = wait_for_daily_run(2, 30, sleep=clock.sleep, now=clock.time, zone=CHICAGO)
    assert ran_at == local(CHICAGO, 2026, 10, 6, 2, 30)
    assert clock.time() == ran_at
    assert clock.sleeps == [3600, 2600, 1600, 600]


def test_already_due_does_not_sleep():
    clock = Clock(local(CHICAGO, 2026, 10, 6, 2, 29, 59))
    clock.step = lambda seconds: seconds + 5  # oversleeps
    wait_for_daily_run(2, 30, sleep=clock.sleep, now=clock.time, zone=CHICAGO)
    assert clock.sleeps == [1]


@pytest.mark.parametrize(
    ("tz", "expected"),
    [("America/Chicago", CHICAGO), (":Europe/Berlin", BERLIN), ("UTC", ZoneInfo("UTC"))],
)
def test_local_zone_follows_tz(monkeypatch, tz, expected):
    monkeypatch.setenv("TZ", tz)
    assert local_zone() == expected


def test_an_unknown_tz_falls_back_to_utc_with_a_warning(monkeypatch, caplog):
    monkeypatch.setenv("TZ", "Mars/Olympus_Mons")
    with caplog.at_level(logging.WARNING, logger=schedule.__name__):
        assert local_zone() is UTC
    assert "unknown time zone TZ='Mars/Olympus_Mons'" in caplog.text


def test_without_tz_the_system_offset_is_used(monkeypatch):
    monkeypatch.delenv("TZ", raising=False)
    zone = local_zone()
    assert isinstance(zone, timezone)
    assert zone.utcoffset(None) == datetime.now().astimezone().utcoffset()


@pytest.fixture()
def fresh_logging():
    """Call it for an unconfigured root logger (as at a job's start-up; pytest
    adds its own capture handlers before each test body); every handler and
    level is put back after."""
    root = logging.getLogger()
    names = ("httpx", "httpcore")
    saved = (root.handlers[:], root.level, [logging.getLogger(n).level for n in names])

    def reset():
        root.handlers = []
        root.setLevel(logging.WARNING)
        for name in names:
            logging.getLogger(name).setLevel(logging.NOTSET)

    yield reset
    handlers, level, levels = saved
    root.handlers = handlers
    root.setLevel(level)
    for name, saved_level in zip(names, levels, strict=True):
        logging.getLogger(name).setLevel(saved_level)


def test_job_logging_is_info_but_http_clients_only_warn(fresh_logging):
    fresh_logging()
    configure_job_logging()
    assert logging.getLogger().level == logging.INFO
    assert len(logging.getLogger().handlers) == 1
    assert logging.getLogger("app.jobs.db_backup").isEnabledFor(logging.INFO)
    for name in ("httpx", "httpcore"):
        assert logging.getLogger(name).level == logging.WARNING
        assert not logging.getLogger(f"{name}.child").isEnabledFor(logging.INFO)
        assert logging.getLogger(f"{name}.child").isEnabledFor(logging.WARNING)
