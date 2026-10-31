"""Dates: ``z.date()`` on datetime / date objects, ``z.coerce.date()``, and the ``z.iso`` strings."""

from datetime import date, datetime, timedelta, timezone

import pytest

from zopy import z

UTC = timezone.utc
JST = timezone(timedelta(hours=9))
NEW_YEAR = datetime(2024, 1, 1, tzinfo=UTC)


def test_date_accepts_datetime_and_date_objects_only():
    assert z.date().parse(NEW_YEAR) is NEW_YEAR
    assert z.date().parse(date(2024, 1, 1)) == date(2024, 1, 1)
    assert z.date().parse(datetime(2024, 1, 1)) == datetime(2024, 1, 1)  # naive is a datetime too
    for value in ("2024-01-01", 0, None):
        assert z.date().safeParse(value).error.issues[0].code == "invalid_type"


def test_min_and_max_are_inclusive():
    assert z.date().min(NEW_YEAR).parse(NEW_YEAR) == NEW_YEAR
    assert z.date().max(NEW_YEAR).parse(NEW_YEAR) == NEW_YEAR
    too_late = z.date().max(NEW_YEAR).safeParse(NEW_YEAR + timedelta(microseconds=1))
    assert too_late.error.issues[0].message == "Too big: expected date to be <=2024-01-01T00:00:00+00:00"
    too_early = z.date().min(date(2024, 1, 1)).safeParse(date(2023, 12, 31))
    assert too_early.error.issues[0].message == "Too small: expected date to be >=2024-01-01"


def test_bounds_compare_instants_across_timezones():
    same_instant = datetime(2024, 1, 1, 9, tzinfo=JST)
    assert z.date().min(NEW_YEAR).max(NEW_YEAR).parse(same_instant) == same_instant
    assert z.date().min(NEW_YEAR).safeParse(datetime(2024, 1, 1, 8, 59, tzinfo=JST)).success is False


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2024-01-01T00:00:00Z", NEW_YEAR),
        ("2024-01-01T09:00:00+09:00", datetime(2024, 1, 1, 9, tzinfo=JST)),
        ("2024-01-01T00:00:00", datetime(2024, 1, 1)),  # no offset: naive
        ("2024-01-01", datetime(2024, 1, 1)),  # a date alone: naive midnight
    ],
)
def test_coerce_date_parses_iso_strings(text, expected):
    out = z.coerce.date().parse(text)
    assert out == expected
    assert out.tzinfo == expected.tzinfo


@pytest.mark.parametrize("value", ["nope", "2023-02-29", "", None, True])
def test_coerce_date_rejects_what_is_not_a_date(value):
    assert z.coerce.date().safeParse(value).error.issues[0].code == "invalid_type"


def test_coerce_date_keeps_dates_and_runs_checks():
    assert z.coerce.date().parse(NEW_YEAR) is NEW_YEAR
    assert z.coerce.date().min(NEW_YEAR).safeParse("2023-12-31T23:59:59Z").success is False


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("2024-02-29", True),  # leap year
        ("2000-02-29", True),  # divisible by 400
        ("1900-02-29", False),  # divisible by 100 only
        ("2023-02-29", False),
        ("2024-04-31", False),
        ("2024-00-10", False),
        ("2024-13-01", False),
        ("2024-1-01", False),
    ],
)
def test_iso_date(text, ok):
    assert z.iso.date().safeParse(text).success is ok


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("2024-01-01T00:00:00Z", True),
        ("2024-01-01T00:00:00.123Z", True),
        ("2024-01-01T00:00Z", True),  # seconds are optional
        ("2024-01-01T00:00:00", False),  # local time needs {"local": True}
        ("2024-01-01T00:00:00+09:00", False),  # an offset needs {"offset": True}
        ("2024-01-01 00:00:00Z", False),
        ("2024-01-01t00:00:00z", False),
        ("2024-01-01T24:00:00Z", False),
        ("2024-01-01T00:00:60Z", False),
        ("2024-02-30T00:00:00Z", False),
    ],
)
def test_iso_datetime(text, ok):
    assert z.iso.datetime().safeParse(text).success is ok


def test_iso_datetime_options():
    assert z.iso.datetime({"local": True}).parse("2024-01-01T00:00:00")
    offset = z.iso.datetime({"offset": True})
    assert offset.parse("2024-01-01T00:00:00+09:00")
    assert offset.safeParse("2024-01-01T00:00:00+0900").success is False
    millis = z.iso.datetime({"precision": 3})
    assert millis.parse("2024-01-01T00:00:00.123Z")
    assert millis.safeParse("2024-01-01T00:00:00Z").success is False
    assert z.iso.datetime({"precision": -1}).parse("2024-01-01T00:00Z")
    assert z.iso.datetime({"precision": 0}).safeParse("2024-01-01T00:00:00.1Z").success is False
    assert z.iso.datetime().safeParse(NEW_YEAR).error.issues[0].code == "invalid_type"


@pytest.mark.parametrize(
    ("text", "ok"),
    [("12:34", True), ("12:34:56.789", True), ("24:00:00", False), ("1:00", False), ("12:34:56Z", False)],
)
def test_iso_time(text, ok):
    assert z.iso.time().safeParse(text).success is ok


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("P1D", True),
        ("PT1H", True),
        ("P1W", True),
        ("P", False),
        ("PT", False),
        ("1D", False),
        ("P1.5D", False),
    ],
)
def test_iso_duration(text, ok):
    assert z.iso.duration().safeParse(text).success is ok


def test_json_schema_of_dates():
    assert z.toJSONSchema(z.iso.datetime())["format"] == "date-time"
    with pytest.raises(ValueError, match="Date cannot be represented"):
        z.toJSONSchema(z.date())
