import math
from datetime import datetime, timezone
from enum import Enum

import pytest

from zopy import z


def test_string_basic():
    assert z.string().parse("tuna") == "tuna"
    r = z.string().safeParse(12)
    assert r.success is False
    assert r["success"] is False
    assert r.error.issues[0]["code"] == "invalid_type"
    assert r.error.issues[0].message == "Invalid input: expected string, received number"


def test_string_checks():
    s = z.string().min(5).max(10)
    assert s.parse("hello") == "hello"
    assert s.safeParse("hi").error.issues[0].message == "Too small: expected string to have >=5 characters"
    assert s.safeParse("x" * 11).error.issues[0].message == "Too big: expected string to have <=10 characters"
    assert z.string().length(3).safeParse("ab").success is False
    assert z.string().regex(r"^\d+$").parse("123") == "123"
    assert z.string().startsWith("a").endsWith("z").parse("abz") == "abz"
    assert (
        z.string().includes("mid").safeParse("nope").error.issues[0].message
        == 'Invalid string: must include "mid"'
    )
    assert z.string().trim().toLowerCase().parse("  HeLLo ") == "hello"
    assert z.string().uppercase().safeParse("Abc").success is False


def test_string_formats():
    assert z.email().parse("a@b.co") == "a@b.co"
    assert z.email().safeParse("nope").error.issues[0].message == "Invalid email address"
    assert z.url().parse("https://example.com/x?y=1") == "https://example.com/x?y=1"
    assert z.url().safeParse("not a url").success is False
    assert z.uuid().parse("123e4567-e89b-12d3-a456-426614174000")
    assert z.uuidv4().safeParse("123e4567-e89b-12d3-a456-426614174000").success is False
    assert z.ipv4().parse("192.168.0.1")
    assert z.ipv6().parse("2001:db8::1")
    assert z.cidrv4().parse("10.0.0.0/8")
    assert z.iso.date().parse("2024-02-29")
    assert z.iso.date().safeParse("2023-02-29").success is False
    assert z.iso.datetime().parse("2024-01-01T00:00:00Z")
    assert z.iso.datetime().safeParse("2024-01-01T00:00:00+09:00").success is False
    assert z.iso.datetime({"offset": True}).parse("2024-01-01T00:00:00+09:00")
    assert z.iso.time().parse("12:34:56.789")
    assert z.iso.duration().parse("P3Y6M4DT12H30M5S")
    assert z.base64().parse("aGVsbG8=")
    assert z.e164().parse("+819012345678")
    assert z.emoji().parse("😀")
    assert z.emoji().safeParse("a").success is False
    assert z.nanoid().parse("V1StGXR8_Z5jdHi6B-myT")


@pytest.mark.parametrize(
    ("make", "valid", "invalid"),
    [
        (z.guid, "123e4567-e89b-12d3-a456-426614174000", "nope"),
        (z.uuidv6, "1ef21d2f-1207-6660-8c4f-419efbd44d48", "123e4567-e89b-12d3-a456-426614174000"),
        (z.uuidv7, "01890a5d-ac96-774b-bcce-b302099a8057", "123e4567-e89b-12d3-a456-426614174000"),
        (z.cuid, "cjld2cjxh0000qzrmn831i7rn", "nope!"),
        (z.cuid2, "tz4a98xxat96iws9zmbrgj3a", "Tz4a98"),
        (z.ulid, "01ARZ3NDEKTSV4RRFFQ69G5FAV", "01ARZ3NDEKTSV4RRFFQ69G5FA"),
        (z.xid, "9m4e2mr0ui3e8a215n4g", "9m4e2mr0ui3e8a215n4"),
        (z.ksuid, "0ujtsYcgvSTl8PAuAdqWYSMnLOv", "short"),
        (z.nanoid, "V1StGXR8_Z5jdHi6B-myT", "short"),
        (z.base64, "aGVsbG8=", "aGVsbG8"),
        (z.base64url, "aGVsbG8", "aGVsbG8="),
        (z.hostname, "example.com", "exa mple.com"),
        (z.jwt, "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2ln", "a.b"),
        (z.url, "https://example.com", "example.com"),
        (z.ipv4, "192.168.0.1", "256.0.0.1"),
        (z.ipv6, "2001:db8::1", "2001:db8:::1"),
        (z.cidrv4, "10.0.0.0/8", "10.0.0.0/33"),
        (z.cidrv6, "2001:db8::/32", "2001:db8::/129"),
        (z.e164, "+819012345678", "09012345678"),
    ],
)
def test_string_format_accepts_and_rejects(make, valid, invalid):
    assert make().parse(valid) == valid
    assert make().safeParse(invalid).error.issues[0].code == "invalid_format"


def test_number():
    assert z.number().parse(3.14) == 3.14
    assert (
        z.number().safeParse("3").error.issues[0].message == "Invalid input: expected number, received string"
    )
    assert (
        z.number().safeParse(math.nan).error.issues[0].message
        == "Invalid input: expected number, received NaN"
    )
    assert (
        z.number().safeParse(math.inf).error.issues[0].message
        == "Invalid input: expected number, received Infinity"
    )
    assert z.number().safeParse(True).success is False
    assert z.number().int().parse(5) == 5
    assert (
        z.number().int().safeParse(5.5).error.issues[0].message
        == "Invalid input: expected int, received number"
    )
    assert z.int().positive().safeParse(0).error.issues[0].message == "Too small: expected number to be >0"
    assert z.number().gte(1).lte(10).parse(10) == 10
    assert z.number().lt(10).safeParse(10).error.issues[0].message == "Too big: expected number to be <10"
    assert z.number().multipleOf(5).parse(15) == 15
    assert z.number().multipleOf(0.1).parse(0.3) == 0.3
    assert (
        z.number().step(5).safeParse(7).error.issues[0].message == "Invalid number: must be a multiple of 5"
    )
    assert z.int32().safeParse(2**31).success is False
    assert z.uint32().parse(2**32 - 1) == 2**32 - 1
    assert z.bigint().parse(10**30) == 10**30
    assert z.bigint().safeParse(1.5).success is False


def test_boolean_date_misc():
    assert z.boolean().parse(True) is True
    assert z.boolean().safeParse("true").success is False
    now = datetime.now(tz=timezone.utc)
    assert z.date().parse(now) == now
    assert z.date().safeParse("2020-01-01").success is False
    assert z.date().min(now).safeParse(datetime(2000, 1, 1, tzinfo=timezone.utc)).success is False
    assert z.null().parse(None) is None
    assert z.undefined().parse(None) is None
    assert z.void().parse(None) is None
    assert z.any().parse({"a": 1}) == {"a": 1}
    assert z.unknown().parse(1) == 1
    assert z.never().safeParse(1).success is False
    assert math.isnan(z.nan().parse(math.nan))
    assert z.nan().safeParse(1).success is False


def test_literal_and_enum():
    tuna = z.literal("tuna")
    assert tuna.parse("tuna") == "tuna"
    assert tuna.value == "tuna"
    assert tuna.safeParse("salmon").error.issues[0].message == 'Invalid input: expected "tuna"'
    assert z.literal(True).safeParse(1).success is False
    multi = z.literal(["red", "green"])
    assert multi.parse("red") == "red"
    assert multi.values == ["red", "green"]

    Fish = z.enum(("Salmon", "Tuna", "Trout"))
    assert Fish.parse("Salmon") == "Salmon"
    assert Fish.enum.Salmon == "Salmon"
    assert Fish.options == ["Salmon", "Tuna", "Trout"]
    assert (
        Fish.safeParse("Cod").error.issues[0].message
        == 'Invalid option: expected one of "Salmon"|"Tuna"|"Trout"'
    )
    assert Fish.extract(("Salmon",)).options == ["Salmon"]
    assert Fish.exclude(("Salmon",)).options == ["Tuna", "Trout"]
    with pytest.raises(TypeError, match="takes a tuple"):
        Fish.extract(["Salmon"])  # pyright: ignore[reportCallIssue, reportArgumentType]
    with pytest.raises(ValueError, match="Key 'Cod' not found in enum"):
        Fish.exclude(("Cod",))  # pyright: ignore[reportArgumentType]

    class Color(Enum):
        RED = "red"
        BLUE = "blue"

    C = z.enum(Color)
    assert C.parse("red") is Color.RED  # values are accepted, members are returned
    assert C.parse(Color.BLUE) is Color.BLUE
    assert C.safeParse("green").success is False
    assert C.safeParse("green").error.issues[0].message == 'Invalid option: expected one of "red"|"blue"'
    assert C.enum.RED is Color.RED
    # z.int() returns int (5.0 is accepted like in JS and normalised to 5)
    assert z.int().parse(5.0) == 5
    assert isinstance(z.int().parse(5.0), int)
    assert z.number().int().parse(7) == 7
    assert z.int().safeParse(5.5).error.issues[0].message == "Invalid input: expected int, received number"
    assert z.int().safeParse(2**53).error.issues[0].code == "too_big"
    assert z.int("not int").safeParse("x").error.issues[0].message == "not int"


def test_stringbool():
    s = z.stringbool()
    assert s.parse("true") is True
    assert s.parse("NO") is False
    assert s.safeParse("maybe").success is False
    assert z.stringbool({"truthy": ["yes"], "falsy": ["no"]}).safeParse("true").success is False


def test_coerce():
    assert z.coerce.string().parse(42) == "42"
    assert z.coerce.string().parse(True) == "true"
    assert z.coerce.number().parse("42") == 42
    assert z.coerce.number().parse("4.5") == 4.5
    assert z.coerce.number().safeParse("abc").success is False
    assert z.coerce.boolean().parse("") is False
    assert z.coerce.boolean().parse("false") is True
    assert z.coerce.bigint().parse("12") == 12
    assert z.coerce.date().parse("2024-01-01T00:00:00Z") == datetime(2024, 1, 1, tzinfo=timezone.utc)
    assert z.coerce.date().safeParse("garbage").success is False


def test_custom_error_messages():
    assert z.string("Not a string!").safeParse(1).error.issues[0].message == "Not a string!"
    assert z.string({"error": "Nope"}).safeParse(1).error.issues[0].message == "Nope"
    assert z.string(error="Nope").safeParse(1).error.issues[0].message == "Nope"
    assert z.string().min(5, "Too short").safeParse("a").error.issues[0].message == "Too short"
    assert z.string().min(5, error="Too short").safeParse("a").error.issues[0].message == "Too short"

    def err(issue):
        if issue["code"] == "too_small":
            return f"min is {issue['minimum']}"
        return None

    assert z.string().min(5, {"error": err}).safeParse("a").error.issues[0].message == "min is 5"
    # "required" vs "wrong type" with an error function (Zod 4's replacement for Zod 3's params)
    s = z.string({"error": lambda iss: "Required!" if iss["input"] is None else "Bad type"})
    assert s.safeParse(None).error.issues[0].message == "Required!"
    assert s.safeParse(1).error.issues[0].message == "Bad type"
    # per-parse error map
    r = z.string().safeParse(1, {"error": lambda iss: "custom per parse"})
    assert r.error.issues[0].message == "custom per parse"
    # global
    z.config({"customError": lambda iss: "GLOBAL"})
    try:
        assert z.string().safeParse(1).error.issues[0].message == "GLOBAL"
    finally:
        z.config({"customError": None})


def test_parse_raises_zod_error():
    with pytest.raises(z.ZodError) as exc:
        z.string().parse(1)
    assert exc.value.issues[0].path == []
    assert "invalid_type" in str(exc.value)
    assert isinstance(exc.value, Exception)


@pytest.mark.parametrize(
    ("params", "key"),
    [
        ({"message": "x"}, "message"),
        ({"required_error": "x"}, "required_error"),
        ({"invalid_type_error": "x"}, "invalid_type_error"),
        ({"errorMap": lambda iss: "x"}, "errorMap"),
    ],
)
def test_zod3_error_params_are_rejected(params, key):
    with pytest.raises(TypeError, match=f"'{key}' is Zod 3 syntax"):
        z.string(params)
    with pytest.raises(TypeError, match=f"'{key}' is Zod 3 syntax"):
        z.string().min(1, params)
