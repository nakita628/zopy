"""exactOptional, xor, looseRecord, new string formats, properties, invertCodec."""

import datetime as dt

import pytest

from zopy import z


def test_exact_optional():
    class User(z.Object):
        name = z.string().optional()
        nick = z.string().exactOptional()

    assert User.parse({}) == {}
    assert User.parse({})._wire_dict() == {}
    assert User.parse({"name": None}) == {"name": None}
    assert User.parse({"nick": "n"}).nick == "n"
    r = User.safeParse({"nick": None})
    assert r.success is False
    assert r.error.issues[0].path == ["nick"]
    assert r.error.issues[0].message == "Invalid input: expected string, received undefined"
    assert z.exactOptional(z.string()).unwrap().type == "string"
    assert z.exactOptional(z.string()).isOptional() is False
    # JSON schema: exactOptional keys are not required
    js = z.toJSONSchema(User)
    assert "required" not in js


def test_optional_default_rungs():
    class S(z.Object):
        a = z.string().default("x").optional()
        b = z.string().optional().default("y")

    class D(z.Object):
        a = z.string().default("x")

    assert S.parse({}) == {"a": "x", "b": "y"}
    assert S.parse({"a": None, "b": None}) == {"a": "x", "b": "y"}
    assert z.string().default("d")._optin == "defaulted"
    assert z.string().optional()._optin == "optional"
    inp = z.toJSONSchema(D, {"io": "input"})
    assert "required" not in inp


def test_xor():
    schema = z.xor([z.string(), z.number()])
    assert schema.parse("hello") == "hello"
    assert schema.parse(1) == 1
    r = schema.safeParse(True)
    assert r.error.issues[0].code == "invalid_union"
    assert r.error.issues[0].message == "Invalid input"

    class Name(z.Object):
        name = z.string()

    class Version(Name):
        version = z.string()

    r = z.xor([Name, Version]).safeParse({"name": "zod", "version": "4"})
    assert r.success is False
    issue = r.error.issues[0]
    assert issue.code == "invalid_union"
    assert issue["inclusive"] is False
    assert issue["matches"] == [0, 1]
    assert issue.message == "Invalid input: more than one option matched"

    class StrictName(Name, z.StrictObject):
        pass

    assert z.xor([StrictName, Version]).parse({"name": "zod", "version": "4"}) == {
        "name": "zod",
        "version": "4",
    }
    assert len(schema.options) == 2


def test_discriminated_union_options_message_and_lookup():
    class Success(z.Object):
        status = z.literal("success")
        data = z.string()

    class Failed(z.Object):
        status = z.literal("failed")
        error = z.string()

    R = z.discriminatedUnion("status", [Success, Failed])
    r = R.safeParse({"status": "pending"})
    assert r.error.issues[0].message == "Invalid discriminator value. Expected 'success' | 'failed'"
    assert z.getDiscriminatedOption(R, "success") is Success
    assert R.getDiscriminatedOption("failed") is Failed
    with pytest.raises(KeyError):
        z.getDiscriminatedOption(R, "pending")


def test_loose_record():
    phones = z.looseRecord(z.string().regex(r"_phone$"), z.e164())
    assert phones.parse({"home_phone": "+14155552671", "other": 1}) == {
        "home_phone": "+14155552671",
        "other": 1,
    }
    assert phones.safeParse({"name": "a", "home_phone": "nope"}).error.issues[0].path == ["home_phone"]
    assert z.looseRecord(z.enum(("a",)), z.int()).parse({"a": 1, "b": "x"}) == {"a": 1, "b": "x"}
    assert z.record(z.enum(("a",)), z.int()).safeParse({"a": 1, "b": "x"}).success is False


def test_new_string_formats():
    assert z.hash("sha256").parse("a" * 64)
    assert z.hash("sha256").safeParse("a" * 63).error.issues[0].message == "Invalid sha256"
    assert z.hash("md5", {"enc": "base64"}).parse("1B2M2Y8AsgTpgAmY7PhCfg==")
    assert z.hash("sha256", {"enc": "base64url"}).parse("47DEQpj8HBSa-_TImW-5JCeuQeRkm5NMpJWZG3hSuFU")
    assert (
        z.hash("sha256", {"enc": "base64url"})
        .safeParse("47DEQpj8HBSa-_TImW-5JCeuQeRkm5NMpJWZG3hSuFU=")
        .success
        is False
    )
    with pytest.raises(ValueError, match="Unknown hash algorithm"):
        z.hash("crc32")
    assert z.mac().parse("00:1A:2B:3C:4D:5E")
    assert z.mac().safeParse("00-1a-2b-3c-4d-5e").error.issues[0].message == "Invalid MAC address"
    assert z.mac().safeParse("00:1a:2B:3c:4d:5e").success is False  # mixed case
    assert z.mac({"delimiter": "-"}).parse("00-1A-2B-3C-4D-5E")
    assert z.creditCard().parse("4111111111111111")
    assert z.creditCard().parse("4111 1111 1111 1111")
    assert z.creditCard().parse("4111-1111-1111-1111")
    assert (
        z.creditCard().safeParse("4111111111111112").error.issues[0].message == "Invalid credit card number"
    )
    assert z.creditCard().safeParse("4111  1111 1111 1111").success is False
    assert z.currencyCode().parse("USD") == "USD"
    assert z.currencyCode().safeParse("usd").error.issues[0].message == "Invalid currency code"
    assert z.currencyCode().safeParse("ANG").success is False
    assert z.iban().parse("DE89370400440532013000")
    assert z.iban().safeParse("DE89 3704 0044 0532 0130 00").error.issues[0].message == "Invalid IBAN"
    assert z.iban().safeParse("DE89370400440532013001").success is False
    cool = z.stringFormat("cool-id", lambda v: v.startswith("cool-"))
    assert cool.parse("cool-1")
    r = cool.safeParse("nope")
    assert r.error.issues[0].code == "invalid_format"
    assert r.error.issues[0]["format"] == "cool-id"
    assert r.error.issues[0].message == "Invalid cool-id"
    assert z.stringFormat("cool-id", r"^cool-[a-z0-9]+$").parse("cool-abc")
    assert z.email({"pattern": z.regexes.html5Email}).parse("a@b.co")
    assert z.email({"pattern": z.regexes.rfc5322Email}).parse("a@b.co")


def test_length_exact_message():
    assert (
        z.string().length(3).safeParse("ab").error.issues[0].message
        == "Too small: expected string to have exactly 3 characters"
    )
    assert (
        z.array(z.any()).length(1).safeParse([1, 2]).error.issues[0].message
        == "Too big: expected array to have exactly 1 items"
    )


def test_properties_and_property():
    class Resp:
        def __init__(self, status, redirected):
            self.status = status
            self.redirected = redirected

    ok_response = z.instanceof(Resp).properties(
        {"status": z.number().min(200).max(299), "redirected": z.literal(False)}
    )
    good = Resp(204, False)
    assert ok_response.parse(good) is good
    r = ok_response.safeParse(Resp(500, True))
    assert [i.path for i in r.error.issues] == [["status"], ["redirected"]]
    via_check = z.instanceof(Resp).check(*z.properties({"status": z.literal(200)}))
    assert via_check.safeParse(Resp(201, False)).success is False
    single = z.any().check(z.property("x", z.int()))
    assert single.parse({"x": 1}) == {"x": 1}
    assert single.safeParse({"x": "no"}).error.issues[0].path == ["x"]
    # transforms inside property checks never change the parsed value
    keep = z.any().check(z.property("x", z.int().transform(lambda n: n * 100)))
    assert keep.parse({"x": 1}) == {"x": 1}


def test_invert_codec_and_never():
    stringToDate = z.codec(
        z.iso.datetime(),
        z.date(),
        {
            "decode": lambda s: dt.datetime.fromisoformat(s.replace("Z", "+00:00")),
            "encode": lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    )
    dateToString = z.invertCodec(stringToDate)
    d = dt.datetime(2024, 1, 15, tzinfo=dt.timezone.utc)
    assert z.decode(dateToString, d) == "2024-01-15T00:00:00Z"
    assert z.encode(dateToString, "2024-01-15T00:00:00Z") == d

    def to_num(val, ctx):
        try:
            return float(val)
        except ValueError:
            ctx.issues.push({"code": "custom", "message": "Not a number", "input": val})
            return z.NEVER

    schema = z.string().transform(to_num)
    assert schema.parse("1.5") == 1.5
    assert schema.safeParse("x").error.issues[0].message == "Not a number"
