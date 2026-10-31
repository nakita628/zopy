"""Primitives, coercion, literals and enums."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from enum import Enum

from zopy import z

from ..show import ok, section


class Color(Enum):
    RED = "red"
    GREEN = "green"


def run() -> None:
    section("Strings: checks & formats")
    ok("min/max", z.string().min(2).max(5), "abc")
    ok("too short", z.string().min(2), "a")
    ok("regex", z.string().regex(r"^[A-Z]{3}-\d{4}$"), "ABC-1234")
    ok("startsWith/endsWith", z.string().startsWith("img_").endsWith(".png"), "img_cat.png")
    ok("trim + toLowerCase", z.string().trim().toLowerCase(), "  HeLLo  ")
    ok("email", z.email(), "ada@example.com")
    ok("url", z.url(), "https://zod.dev/api?x=1")
    ok("httpUrl rejects ftp", z.httpUrl(), "ftp://example.com")
    ok("uuid v7", z.uuidv7(), "018f0a1e-7a1b-7b1a-9c1d-0123456789ab")
    ok("ipv6", z.ipv6(), "2001:db8::ff00:42:8329")
    ok("cidrv4", z.cidrv4(), "192.168.0.0/24")
    ok("iso.datetime (Z only)", z.iso.datetime(), "2024-05-01T12:00:00Z")
    ok("iso.datetime offset", z.iso.datetime({"offset": True}), "2024-05-01T12:00:00+09:00")
    ok("iso.datetime precision 3", z.iso.datetime({"precision": 3}), "2024-05-01T12:00:00.123Z")
    ok("iso.date leap year", z.iso.date(), "2024-02-29")
    ok("iso.date not leap", z.iso.date(), "2023-02-29")
    ok("iso.duration", z.iso.duration(), "P1Y2M3DT4H5M6S")
    ok("emoji", z.emoji(), "🎉🎉")
    ok("jwt (alg HS256)", z.jwt({"alg": "HS256"}), "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.abc")
    ok("base64", z.base64(), "aGVsbG8gd29ybGQ=")
    ok("e164", z.e164(), "+14155552671")
    ok("templateLiteral", z.templateLiteral([z.number(), z.enum(("px", "em", "rem"))]), "1.5rem")
    ok(
        "hash sha256 (hex)",
        z.hash("sha256"),
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    )
    ok(
        "hash sha256 base64url",
        z.hash("sha256", {"enc": "base64url"}),
        "47DEQpj8HBSa-_TImW-5JCeuQeRkm5NMpJWZG3hSuFU",
    )
    ok("hash md5 too short", z.hash("md5"), "abc")
    ok("mac", z.mac(), "00:1A:2B:3C:4D:5E")
    ok("mac dash needs delimiter opt", z.mac(), "00-1A-2B-3C-4D-5E")
    ok("mac delimiter '-'", z.mac({"delimiter": "-"}), "00-1A-2B-3C-4D-5E")
    ok("creditCard (Luhn)", z.creditCard(), "4111 1111 1111 1111")
    ok("creditCard bad checksum", z.creditCard(), "4111111111111112")
    ok("currencyCode", z.currencyCode(), "JPY")
    ok("currencyCode withdrawn ANG", z.currencyCode(), "ANG")
    ok("iban", z.iban(), "DE89370400440532013000")
    ok("iban with spaces", z.iban(), "DE89 3704 0044 0532 0130 00")
    ok("stringFormat(fn)", z.stringFormat("cool-id", lambda v: v.startswith("cool-")), "nope")
    ok("stringFormat(regex)", z.stringFormat("ticket", r"^[A-Z]+-\d+$"), "ABC-123")
    ok("email html5 pattern", z.email({"pattern": z.regexes.html5Email}), "a.b+c@example.io")
    ok("string().length(3) exact wording", z.string().length(3), "ab")

    section("Numbers")
    ok("float", z.number(), 3.14)
    ok("bool is not number", z.number(), True)
    ok("NaN rejected", z.number(), math.nan)
    ok("int accepts 5.0", z.int(), 5.0)
    ok("int rejects 5.5", z.int(), 5.5)
    ok("gt/lte", z.number().gt(0).lte(100), 100)
    ok("multipleOf 0.01", z.number().multipleOf(0.01), 19.99)
    ok("not multiple", z.number().multipleOf(0.01), 19.999)
    ok("int32 overflow", z.int32(), 2**31)
    ok("uint64 (bigint)", z.uint64(), 2**64 - 1)
    ok("bigint rejects float", z.bigint(), 1.0)
    ok("positive().int() chain", z.number().positive().int(), -1)

    section("Booleans, dates, null-ish")
    ok("boolean", z.boolean(), False)
    ok("date", z.date(), datetime(2024, 1, 1, tzinfo=timezone.utc))
    ok(
        "date.min",
        z.date().min(datetime.now(tz=timezone.utc) - timedelta(days=1)),
        datetime(2000, 1, 1, tzinfo=timezone.utc),
    )
    ok("null", z.null(), None)
    ok("undefined (None)", z.undefined(), None)
    ok("never", z.never(), "anything")
    ok("nan", z.nan(), math.nan)
    ok("any", z.any(), object())

    section("Coercion")
    ok("coerce.string(42)", z.coerce.string(), 42)
    ok("coerce.number('42')", z.coerce.number(), "42")
    ok("coerce.number('4.5e2')", z.coerce.number(), "4.5e2")
    ok("coerce.number('abc')", z.coerce.number(), "abc")
    ok("coerce.boolean('false') is True", z.coerce.boolean(), "false")
    ok("coerce.date(iso)", z.coerce.date(), "2024-01-01T00:00:00Z")
    ok("coerce.date(epoch seconds)", z.coerce.date(), 0)
    ok("coerce.bigint('99')", z.coerce.bigint(), "99")
    ok("stringbool('yes')", z.stringbool(), "yes")
    ok("stringbool('off')", z.stringbool(), "OFF")
    ok("stringbool custom", z.stringbool({"truthy": ["はい"], "falsy": ["いいえ"]}), "はい")

    section("Literals & enums")
    ok("literal", z.literal("tuna"), "tuna")
    ok("literal multi", z.literal(["a", "b", 3, None]), 3)
    ok("literal(True) rejects 1", z.literal(True), 1)
    Fish = z.enum(("Salmon", "Tuna", "Trout"))  # a tuple (not a list) keeps the literal types
    ok("enum", Fish, "Tuna")
    ok("enum invalid", Fish, "Cod")
    print(f"       Fish.enum.Salmon = {Fish.enum.Salmon!r}, options = {Fish.options}")
    print(f"       exclude(('Tuna',)).options = {Fish.exclude(('Tuna',)).options}")
    PyColor = z.enum(Color)
    ok("python Enum by value", PyColor, "red")
    ok("python Enum by member", PyColor, Color.GREEN)
    ok("python Enum invalid", PyColor, "blue")
    print(f"       PyColor.enum = {dict(PyColor.enum)}")
