"""Regressions and idioms surfaced by the example app."""

from datetime import datetime, timezone
from types import MappingProxyType

import pytest

from zopy import z


def test_builtin_callables_in_transform_and_refine():
    assert z.number().pipe(z.transform(str)).parse(10) == "10"
    assert z.string().transform(len).parse("abcd") == 4
    assert z.string().transform(int).pipe(z.int()).parse("42") == 42
    assert z.array(z.string()).refine(any).safeParse([""]).success is False
    assert z.string().transform(lambda s, ctx=None: s.upper()).parse("a") == "A"


def test_xor_idioms():
    class ContactFields(z.Object):
        email = z.email().optional()
        phone = z.e164().optional()

    Contact = ContactFields.refine(lambda d: (d.email is None) != (d.phone is None), "one of email/phone")
    assert Contact.safeParse({"email": "a@b.co"}).success
    assert Contact.safeParse({"phone": "+819012345678"}).success
    assert not Contact.safeParse({}).success
    assert not Contact.safeParse({"email": "a@b.co", "phone": "+819012345678"}).success

    def xor(a, b):
        def exactly_one(value, ctx):
            if len([s for s in (a, b) if s.safeParse(value).success]) != 1:
                ctx.addIssue({"code": "custom", "message": "xor"})

        return z.union([a, b]).superRefine(exactly_one)

    EvenXorPositive = xor(z.int().multipleOf(2), z.int().positive())
    assert EvenXorPositive.parse(-4) == -4
    assert EvenXorPositive.parse(3) == 3
    assert EvenXorPositive.safeParse(4).error.issues[0].message == "xor"
    assert EvenXorPositive.safeParse(-3).error.issues[0].code == "invalid_union"

    class ById(z.StrictObject):
        id = z.int()

    class BySlug(z.StrictObject):
        slug = z.string()

    Lookup = z.union([ById, BySlug])
    assert not Lookup.safeParse({"id": 1, "slug": "x"}).success


def test_date_bounds_message_uses_isoformat():
    lower = datetime(2024, 1, 1, tzinfo=timezone.utc)
    r = z.date().min(lower).safeParse(datetime(2000, 1, 1, tzinfo=timezone.utc))
    assert r.error.issues[0].message == "Too small: expected date to be >=2024-01-01T00:00:00+00:00"


def test_readonly_is_shallow_like_object_freeze():
    out = z.record(z.string(), z.array(z.int())).readonly().parse({"a": [1]})
    assert isinstance(out, MappingProxyType)
    assert isinstance(out["a"], list)


def test_readonly_freezes_each_container_kind():
    assert z.array(z.int()).readonly().parse([1]) == (1,)
    assert z.set(z.int()).readonly().parse({1}) == frozenset({1})
    frozen_map = z.map(z.int(), z.string()).readonly().parse({1: "a"})
    assert isinstance(frozen_map, MappingProxyType)
    assert frozen_map == {1: "a"}
    assert z.tuple((z.int(), z.string())).readonly().parse([1, "a"]) == (1, "a")
    with pytest.raises(TypeError):
        z.record(z.string(), z.int()).readonly().parse({"a": 1})["a"] = 2  # type: ignore[index]

    class Point(z.Object):
        x = z.int()

    for schema in (Point.readonly(), z.readonly(Point)):
        point = schema.parse({"x": 1})
        with pytest.raises(AttributeError, match="Point is readonly"):
            point.x = 2


def test_discriminated_union_enum_and_optional_discriminators():
    class Tri(z.Object):
        kind = z.enum(("tri", "triangle"))
        n = z.literal(3)

    class Sq(z.Object):
        kind = z.literal("sq").optional()
        n = z.literal(4)

    S = z.discriminatedUnion("kind", [Tri, Sq])
    assert S.parse({"kind": "triangle", "n": 3})["n"] == 3
    sq = S.parse({"n": 4})
    assert isinstance(sq, Sq)
    assert sq == {"n": 4}
    assert sq.kind is None


@pytest.mark.parametrize(
    "value",
    [
        "7",
        "-12",
        "007",
        "-0",
        "123456789012345678",
        "1234567890123456789012",
        " 7 ",
        "+7",
        "1.5",
        "1e3",
        "1_000",
        "",
        "abc",
        "٣",
        "inf",
        True,
        False,
        None,
        3,
        2.5,
        2**70,
    ],
)
def test_coerce_number_matches_between_engines(value):
    from zopy._compile import set_engine

    results = []
    for engine in ("rust", "python"):
        set_engine(engine)
        for schema in (z.coerce.number(), z.coerce.bigint(), z.coerce.number().int()):
            r = schema.safeParse(value)
            results.append((engine, r.success, repr(r.data) if r.success else r.error.issues[0]["code"]))
    set_engine("rust")
    rust = [r[1:] for r in results if r[0] == "rust"]
    python = [r[1:] for r in results if r[0] == "python"]
    assert rust == python, (value, rust, python)
