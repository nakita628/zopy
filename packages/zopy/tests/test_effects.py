import asyncio
from types import MappingProxyType

import pytest

from zopy import z


def test_refine():
    s = z.string().refine(lambda v: len(v) <= 5, {"error": "Too long"})
    assert s.parse("abc") == "abc"
    r = s.safeParse("abcdefg")
    assert r.error.issues[0].code == "custom"
    assert r.error.issues[0].message == "Too long"
    assert z.string().refine(lambda v: False).safeParse("x").error.issues[0].message == "Invalid input"

    # path & multiple refinements continue
    class Passwords(z.Object):
        password = z.string()
        confirm = z.string()

    pw = Passwords.refine(
        lambda d: d["password"] == d["confirm"], {"error": "Passwords don't match", "path": ["confirm"]}
    )
    r = pw.safeParse({"password": "a", "confirm": "b"})
    assert r.error.issues[0].path == ["confirm"]
    assert r.error.issues[0].message == "Passwords don't match"
    # refine still runs after non-aborting check failure, not after type failure
    multi = z.string().min(5).refine(lambda v: v.startswith("a"), "must start with a")
    r = multi.safeParse("xyz")
    assert [i.code for i in r.error.issues] == ["too_small", "custom"]
    r = multi.safeParse(1)
    assert [i.code for i in r.error.issues] == ["invalid_type"]
    # abort stops subsequent refinements
    ab = z.string().refine(lambda v: False, {"abort": True}).refine(lambda v: False, "second")
    assert len(ab.safeParse("x").error.issues) == 1
    # refine receives ctx when accepting two args
    two = z.string().refine(lambda v, ctx: ctx.value == v, "ctx")
    assert two.parse("x") == "x"


def test_super_refine_and_check():
    def validate(val, ctx):
        if len(val) > 3:
            ctx.addIssue(
                {
                    "code": "too_big",
                    "maximum": 3,
                    "origin": "array",
                    "inclusive": True,
                    "message": "Too many items 😡",
                }
            )
        if len(val) != len(set(val)):
            ctx.addIssue({"code": "custom", "message": "No duplicates allowed."})

    s = z.array(z.string()).superRefine(validate)
    r = s.safeParse(["a", "a", "b", "c"])
    assert [i.message for i in r.error.issues] == ["Too many items 😡", "No duplicates allowed."]

    def check(ctx):
        if ctx.value > 10:
            ctx.issues.push({"code": "custom", "message": "too big", "input": ctx.value})

    assert z.number().check(check).safeParse(11).error.issues[0].message == "too big"
    assert z.number().check(z.gt(5), z.lt(10)).safeParse(11).error.issues[0].code == "too_big"
    assert z.string().check(z.minLength(3)).safeParse("ab").success is False

    # a non-continuable issue aborts the later checks
    def stop(val, ctx):
        ctx.addIssue({"code": "custom", "message": "stop", "continue": False})

    r = z.string().superRefine(stop).refine(lambda v: False, "never").safeParse("x")
    assert len(r.error.issues) == 1


def test_transform_pipe_preprocess():
    length = z.string().transform(lambda s: len(s))
    assert length.parse("abcd") == 4
    with_ctx = z.string().transform(lambda s, ctx: ctx.addIssue({"message": "no"}) or s)
    assert with_ctx.safeParse("x").error.issues[0].message == "no"
    piped = z.string().transform(lambda s: len(s)).pipe(z.number().max(5))
    assert piped.parse("abc") == 3
    assert piped.safeParse("abcdefg").error.issues[0].code == "too_big"
    # transform not run when the input is aborted
    r = z.string().transform(lambda s: 1 / 0).safeParse(1)
    assert r.error.issues[0].code == "invalid_type"
    pre = z.preprocess(lambda v: int(v), z.number())
    assert pre.parse("42") == 42
    assert z.string().overwrite(lambda s: s.upper()).parse("ab") == "AB"
    assert z.string().trim().min(1).safeParse("   ").success is False
    assert z.pipe(z.string(), z.transform(lambda s: s + "!")).parse("a") == "a!"
    assert piped.in_.type == "pipe"
    assert z.string().pipe(z.string()).in_.type == "string"


def test_optional_nullable_default_catch():
    assert z.string().optional().parse(None) is None
    assert z.string().optional().parse("a") == "a"
    assert z.string().nullable().parse(None) is None
    assert z.string().nullish().parse(None) is None
    assert z.optional(z.string()).unwrap().type == "string"
    assert z.string().optional().isOptional() is True
    assert z.string().isOptional() is False
    assert z.string().nullable().isNullable() is True
    d = z.string().default("tuna")
    assert d.parse(None) == "tuna"
    assert d.parse("x") == "x"
    assert d.defaultValue == "tuna"
    assert d.removeDefault().type == "string"
    assert z.array(z.string()).default(list).parse(None) == []
    # default short-circuits (no validation), prefault validates
    assert z.string().transform(lambda s: len(s)).default(10).parse(None) == 10
    assert z.string().transform(lambda s: len(s)).prefault("abc").parse(None) == 3
    assert z.string().trim().prefault("  a ").parse(None) == "a"
    c = z.number().catch(42)
    assert c.parse("x") == 42
    assert c.parse(1) == 1
    assert c.removeCatch().type == "number"
    fn_catch = z.number().catch(lambda ctx: len(ctx.error.issues))
    assert fn_catch.parse("x") == 1
    assert z.string().optional().nonoptional().safeParse(None).error.issues[0].code == "invalid_type"
    assert z.string().optional().nonoptional().parse("a") == "a"

    # object: optional key omitted, default applied
    class S(z.Object):
        a = z.string().optional()
        b = z.number().default(5)

    assert S.parse({}) == {"b": 5}
    assert S.parse({"a": None}) == {"a": None, "b": 5}


def test_readonly_brand_describe_meta():
    ro = z.record(z.string(), z.string()).readonly().parse({"a": "x"})
    assert isinstance(ro, MappingProxyType)
    assert z.array(z.string()).readonly().parse(["a"]) == ("a",)
    assert z.string().brand("UserId").parse("x") == "x"
    d = z.string().meta({"description": "A string"})
    assert d.description == "A string"
    m = z.string().meta({"title": "T", "examples": ["a"]})
    assert m.meta() == {"title": "T", "examples": ["a"]}
    registered = z.globalRegistry.get(m)
    assert registered is not None
    assert registered["title"] == "T"
    reg = z.registry()
    s = z.string().register(reg, {"id": "s1"})
    assert reg.get(s) == {"id": "s1"}
    assert reg.has(s)


def test_codec():
    stringToDate = z.codec(
        z.iso.datetime(),
        z.date(),
        {
            "decode": lambda s: __import__("datetime").datetime.fromisoformat(s.replace("Z", "+00:00")),
            "encode": lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    )
    import datetime as dt

    d = z.decode(stringToDate, "2024-01-01T00:00:00Z")
    assert d == dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
    assert z.encode(stringToDate, d) == "2024-01-01T00:00:00Z"
    assert stringToDate.safeEncode("not a date").success is False
    with pytest.raises(z.ZodEncodeError):
        z.encode(z.string().transform(lambda s: len(s)), 3)
    # pipes reverse, defaults pass through on encode
    assert z.string().default("x").encode("y") == "y"
    assert z.stringbool().encode(True) == "true"


@pytest.mark.asyncio
async def test_async():
    async def is_available(name):
        await asyncio.sleep(0)
        return name != "taken"

    s = z.string().refine(is_available, "taken!")
    assert await s.parseAsync("free") == "free"
    r = await s.safeParseAsync("taken")
    assert r.error.issues[0].message == "taken!"
    with pytest.raises(z.ZodAsyncError):
        s.parse("free")

    async def to_len(v):
        return len(v)

    assert await z.string().transform(to_len).parseAsync("abc") == 3

    class Obj(z.Object):
        name = s
        tags = z.array(s)

    r = await Obj.safeParseAsync({"name": "taken", "tags": ["ok", "taken"]})
    assert [i.path for i in r.error.issues] == [["name"], ["tags", 1]]
    assert await z.union([s, z.number()]).parseAsync(1) == 1
    r = await z.union([s, z.number()]).safeParseAsync("taken")
    assert r.error.issues[0].code == "custom"
    f = z.function({"input": [z.string()], "output": z.number()}).implementAsync(to_len)
    assert await f("ab") == 2


def test_error_helpers():
    class Nested(z.Object):
        x = z.number()

    class S(z.Object):
        name = z.string()
        tags = z.array(z.string())
        nested = Nested

    r = S.safeParse({"name": 1, "tags": ["a", 2], "nested": {"x": "no"}})
    err = r.error
    tree = z.treeifyError(err)
    assert tree["properties"]["name"]["errors"] == ["Invalid input: expected string, received number"]
    assert tree["properties"]["tags"]["items"][1]["errors"] == [
        "Invalid input: expected string, received number"
    ]
    assert tree["properties"]["nested"]["properties"]["x"]["errors"]
    pretty = z.prettifyError(err)
    assert "✖ Invalid input: expected string, received number\n  → at name" in pretty
    assert "→ at tags[1]" in pretty
    assert "→ at nested.x" in pretty
    flat = z.flattenError(err)
    assert set(flat["fieldErrors"]) == {"name", "tags", "nested"}
    assert flat["formErrors"] == []
    assert r.error.issues[0].path == ["name"]
    assert z.string().safeParse(1, {"reportInput": True}).error.issues[0]["input"] == 1
    assert "input" not in z.string().safeParse(1).error.issues[0]
    assert z.toDotPath(["a", 0, "b c"]) == 'a[0]["b c"]'


def test_z_import_styles():
    import zopy
    import zopy as z2
    from zopy import z as z3

    assert zopy.string().parse("a") == "a"

    class A(z2.Object):
        a = z2.string()

    assert A.parse({"a": "x"}) == {"a": "x"}
    assert z3 is z

    class User(z.Object):
        a = z.string()

    assert not hasattr(z, "infer")  # removed: Python has no typeof, so it could only ever be Any
    assert {"a": "x"} in User
    assert 1 not in User


def test_refine_options_error_path_abort_when():
    class Form(z.Object):
        password = z.string().min(8)
        confirm = z.string()
        nickname = z.string()

    def passwords_ok(payload):  # payload.value is the input mapping
        value = payload.value
        return isinstance(value.get("password"), str) and isinstance(value.get("confirm"), str)

    matches = {"error": "Passwords don't match", "path": ["confirm"]}
    same = lambda f: f["password"] == f["confirm"]  # noqa: E731
    data = {"password": "secret123", "confirm": "nope"}  # nickname missing: an aborting issue

    # By default a refinement is skipped once the object has an aborting issue ...
    issues = Form.refine(same, matches).safeParse(data).error.issues
    assert [i.path for i in issues] == [["nickname"]]
    # ... and `when` decides instead.
    issues = Form.refine(same, {**matches, "when": passwords_ok}).safeParse(data).error.issues
    assert [(i.path, i.message) for i in issues] == [
        (["nickname"], "Invalid input: expected string, received undefined"),
        (["confirm"], "Passwords don't match"),
    ]

    # error as a function of the issue
    even = z.int().refine(lambda n: n % 2 == 0, {"error": lambda iss: f"{iss['input']} is odd"})
    assert even.safeParse(3).error.issues[0].message == "3 is odd"

    # abort: stop at the first failing refinement
    both = z.string().refine(lambda s: False, {"error": "a"}).refine(lambda s: False, {"error": "b"})
    assert [i.message for i in both.safeParse("x").error.issues] == ["a", "b"]
    first = (
        z.string()
        .refine(lambda s: False, {"error": "a", "abort": True})
        .refine(lambda s: False, {"error": "b"})
    )
    assert [i.message for i in first.safeParse("x").error.issues] == ["a"]


def test_super_refine_and_check_options():
    def no_duplicates(items, ctx):
        if len(items) != len(set(items)):
            ctx.addIssue({"code": "custom", "message": "No duplicates", "path": [0]})

    issues = z.array(z.string()).superRefine(no_duplicates).safeParse(["a", "a"]).error.issues
    assert [(i.path, i.message) for i in issues] == [([0], "No duplicates")]

    # superRefine with `when`: runs although an earlier check aborted
    always = z.string().refine(lambda s: False, {"error": "first", "abort": True})
    late = always.superRefine(
        lambda s, ctx: ctx.addIssue({"code": "custom", "message": "late"}),
        {"when": lambda payload: True},
    )
    assert [i.message for i in late.safeParse("x").error.issues] == ["first", "late"]

    def positive(ctx):
        if ctx.value <= 0:
            ctx.issues.push({"code": "custom", "message": "must be positive", "input": ctx.value})

    assert z.int().check(positive).safeParse(-1).error.issues[0].message == "must be positive"
