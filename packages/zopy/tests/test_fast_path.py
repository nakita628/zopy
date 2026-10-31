"""After the first Rust compile, ``parse`` / ``safeParse`` are Rust entry points on the schema."""

import pytest

from zopy import z
from zopy._compile import rust_available, set_engine

pytestmark = pytest.mark.skipif(not rust_available(), reason="needs the zopy._core extension")


def test_fast_entry_points_behave_like_methods(engine):
    schema = z.string().min(2)
    assert schema.parse("ab") == "ab"
    assert schema.parse("ab") == "ab"  # second call uses the installed entry point when on Rust
    with pytest.raises(z.ZodError) as info:
        schema.parse("a")
    assert info.value.issues[0]["code"] == "too_small"
    ok = schema.safeParse("abc")
    assert ok.success is True
    assert ok.data == "abc"
    bad = schema.safeParse(1)
    assert bad.success is False
    assert bad.error.issues[0]["code"] == "invalid_type"


def test_options_and_engine_switch_fall_back():
    set_engine("rust")
    schema = z.string()
    schema.parse("x")
    assert "parse" in vars(schema)
    result = schema.safeParse(1, error=lambda issue: "custom")
    assert result.success is False
    assert result.error.issues[0]["message"] == "custom"
    set_engine("python")
    try:
        assert schema.parse("x") == "x"
        assert schema.safeParse(1).success is False
    finally:
        set_engine("rust")


def test_clones_do_not_inherit_entry_points():
    set_engine("rust")
    base = z.string()
    base.parse("x")
    derived = base.min(3)
    assert "parse" not in vars(derived)
    assert derived.safeParse("ab").success is False
    assert base.safeParse("ab").success is True


def test_object_class_entry_points_are_per_class():
    set_engine("rust")

    class User(z.Object):
        name = z.string()

    class Admin(User):
        level = z.int().positive()

    Strict = User.refine(lambda u: u.name != "root", "no root")
    assert isinstance(User.parse({"name": "a"}), User)
    assert type(vars(User)["parse"]).__name__ == "FastParse"
    # Subclasses and derived schemas must not run User's compiled tree.
    assert Admin.safeParse({"name": "a"}).success is False
    admin = Admin.parse({"name": "a", "level": 2})
    assert type(admin) is Admin
    assert admin.level == 2
    assert Admin.parse({"name": "a", "level": 3}).level == 3
    assert Strict.safeParse({"name": "root"}).success is False
    assert Strict.safeParse({"name": "ada"}).success is True
    assert User.safeParse({"name": "root"}).success is True
    with pytest.raises(z.ZodError):
        User.parse({})
    set_engine("python")
    try:
        assert isinstance(User.parse({"name": "a"}), User)
        assert Admin.safeParse({"name": "a"}).success is False
    finally:
        set_engine("rust")


class Tag(str):
    pass


class NS(z.Object):
    n = z.int().max(3)
    s = z.string().length(1)


QUICK_CASES = [
    (z.array(z.int().positive()), [[1, 0], [1, True], [2**70], [2**53, 2**53 + 1], [-(2**53) - 1]]),
    (z.array(z.int().gte(5).lt(10)), [[5, 9], [4], [10], [5.0], [9.5]]),
    (z.array(z.number().gt(2**70)), [[2**71], [2**70]]),
    (z.array(z.string().min(2).max(3)), [["🎉🎉", "abc"], ["🎉"], ["abcd"], [Tag("ab")]]),
    (z.array(z.boolean()), [[True, False], [1]]),
    (NS, [{"n": 3, "s": "é"}, {"n": 4, "s": "ab"}]),
    (z.record(z.string(), z.int().min(0)), [{"a": 1}, {"a": -1}, {"a": None}]),
]


@pytest.mark.parametrize(("schema", "values"), QUICK_CASES)
def test_quick_path_matches_python_engine(schema, values):
    for value in values:
        set_engine("rust")
        fast = schema.safeParse(value)
        fast_out = (
            fast.success,
            fast.data if fast.success else [(i["code"], i["path"]) for i in fast.error.issues],
        )
        set_engine("python")
        try:
            slow = schema.safeParse(value)
        finally:
            set_engine("rust")
        slow_out = (
            slow.success,
            slow.data if slow.success else [(i["code"], i["path"]) for i in slow.error.issues],
        )
        assert fast_out == slow_out, value
