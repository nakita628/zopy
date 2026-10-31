"""Default messages written by Rust (``finalize_plain``) match Python's ``finalize_issue`` exactly."""

import datetime as dt
import re

import pytest

from zopy import z
from zopy._compile import rust_available, set_engine

pytestmark = pytest.mark.skipif(not rust_available(), reason="needs the zopy._core extension")


class Thing:
    pass


class StrictA(z.StrictObject):
    a = z.string()


class Inner(z.Object):
    c = z.int()


class Outer(z.Object):
    a = z.string()
    b = Inner


CASES = [
    (
        z.string(),
        [
            None,
            True,
            1,
            1.5,
            float("nan"),
            [1],
            (1,),
            {"a": 1},
            {1},
            frozenset(),
            dt.date(2020, 1, 1),
            Thing(),
            b"x",
        ],
    ),
    (z.int(), ["1", 1.5, float("inf"), 2**60]),
    (z.number(), [float("nan"), "x"]),
    (z.string().min(3), ["ab"]),
    (z.string().max(1), ["ab"]),
    (z.string().length(2), ["abc"]),
    (z.array(z.int()).min(2).max(3), [[1], [1, 2, 3, 4]]),
    (z.number().gt(1.5).lt(2.25), [1.5, 2.25]),
    (z.number().gte(1e16), [1.0]),
    (z.int().positive(), [0, -5]),
    (z.int().nonnegative().lte(10), [11, -1]),
    (z.int().multipleOf(3), [4]),
    (z.number().multipleOf(0.5), [0.3]),
    (z.email(), ["nope"]),
    (z.uuid(), ["x"]),
    (z.url(), ["x"]),
    (z.ipv4(), ["x"]),
    (z.iso.datetime(), ["x"]),
    (z.string().regex(re.compile(r"^\d+$")), ["a"]),
    (z.string().startsWith('a"b'), ["x"]),
    (z.string().endsWith("ü\n"), ["x"]),
    (z.string().includes("\\"), ["x"]),
    (StrictA, [{"a": "x", "b": 1, "c": 2}, {"a": "x", 'q"': 1}]),
    (Outer, [{}, {"a": 1, "b": {"c": "x"}}]),
    (z.array(z.string()), [[1, "a", None]]),
    (z.record(z.string(), z.int()), [{"a": "x"}]),
]


def issues_of(schema, value, **params):
    result = schema.safeParse(value, **params)
    assert result.success is False
    return [list(issue.items()) for issue in result.error.issues]


@pytest.mark.parametrize(("schema", "values"), CASES)
def test_plain_messages_match_python(schema, values):
    set_engine("rust")
    for value in values:
        plain = issues_of(schema, value)
        # An error map that returns None falls through to the locale, via Python's finalize.
        resolved = issues_of(schema, value, error=lambda issue: None)
        assert plain == resolved, value


def test_report_input_and_custom_errors_still_apply():
    set_engine("rust")

    class Schema(z.Object):
        a = z.string("need a")
        b = z.int().min(5, "too low")

    issues = Schema.safeParse({"a": 1, "b": 1}).error.issues
    assert [i["message"] for i in issues] == ["need a", "too low"]
    reported = z.string().safeParse(1, reportInput=True).error.issues
    assert reported[0]["input"] == 1
    plain = z.string().safeParse(1).error.issues
    assert "input" not in plain[0]
    z.config(customError=lambda issue: "global")
    try:
        assert z.string().safeParse(1).error.issues[0]["message"] == "global"
    finally:
        z.config(customError=None)
