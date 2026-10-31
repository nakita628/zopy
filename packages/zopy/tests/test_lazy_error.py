"""Failed parses defer message building until ``error.issues`` / ``str(error)`` is read."""

import pickle

import pytest

from zopy import z


class Schema(z.Object):
    name = z.string().min(1)
    age = z.int().positive()


schema = Schema
BAD = {"name": "", "age": -1}


def test_issues_built_on_access():
    calls = []

    def error_map(issue):
        calls.append(issue["code"])
        return "custom"

    result = schema.safeParse(BAD, error=error_map)
    assert result.success is False
    assert result.error is not None
    issues = result.error.issues
    assert [i["message"] for i in issues] == ["custom", "custom"]
    assert result.error.issues is issues  # built once
    assert len(calls) == 2


def test_str_pickle_and_mutation():
    with pytest.raises(z.ZodError) as info:
        schema.parse(BAD)
    error = info.value
    assert '"too_small"' in str(error)
    clone = pickle.loads(pickle.dumps(error))
    assert clone.issues == error.issues
    error.issues.append(z.ZodIssue({"code": "custom", "path": [], "message": "extra"}))
    assert error.issues[-1]["message"] == "extra"
    assert len(error.issues) == 3
