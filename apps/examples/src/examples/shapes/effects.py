"""Refinements, transforms, pipes, defaults, catch, codecs, functions."""

from __future__ import annotations

from datetime import datetime, timezone

from zopy import z

from ..show import ok, section


class PasswordForm(z.Object):
    password = z.string().min(8)
    confirm = z.string()


Password = PasswordForm.refine(
    lambda form: form.password == form.confirm,  # form: PasswordForm
    {"error": "Passwords don't match", "path": ["confirm"]},
)


class Settings(z.Object):
    theme = z.enum(("light", "dark")).default("light")
    size = z.int().catch(12)
    beta = z.boolean().optional()


class Counter(z.Object):
    n = z.int()


class Success(z.Object):
    status = z.literal("success")
    data = z.string()


class Failed(z.Object):
    status = z.literal("failed")
    error = z.string()


def run() -> None:
    section("refine / superRefine / check")
    ok("match", Password, {"password": "secret123", "confirm": "secret123"})
    ok("mismatch -> path confirm", Password, {"password": "secret123", "confirm": "nope"})
    ok("min fails AND refine still runs", Password, {"password": "short", "confirm": "x"})

    def unique_and_small(items, ctx):
        if len(items) > 3:
            ctx.addIssue(
                {
                    "code": "too_big",
                    "maximum": 3,
                    "origin": "array",
                    "inclusive": True,
                    "message": "Max 3 items",
                }
            )
        if len(items) != len(set(items)):
            ctx.addIssue({"code": "custom", "message": "No duplicates"})

    ok("superRefine two issues", z.array(z.string()).superRefine(unique_and_small), ["a", "a", "b", "c"])

    def even_check(ctx):
        if ctx.value % 2:
            ctx.issues.push({"code": "custom", "message": f"{ctx.value} is odd", "input": ctx.value})

    ok(".check(fn)", z.int().check(even_check), 3)
    ok(".check(z.gt, z.lt)", z.number().check(z.gt(0), z.lt(10)), 42)
    ok(
        "abort stops later refinements",
        z.string()
        .refine(lambda s: False, {"abort": True, "error": "first"})
        .refine(lambda s: False, "second"),
        "x",
    )
    ok(
        "refine error fn",
        z.int().refine(lambda n: n % 2 == 0, {"error": lambda iss: f"{iss['input']} is not even"}),
        7,
    )

    section("transform / pipe / preprocess / overwrite")
    Csv = (
        z.string()
        .transform(lambda s: [p.strip() for p in s.split(",")])
        .pipe(z.array(z.string().min(1)).min(2))
    )
    ok("csv -> list", Csv, "a, b ,c")
    ok("csv too few", Csv, "a")
    ok("csv empty item", Csv, "a,,b")
    ok("transform skipped on type error", z.string().transform(lambda s: 1 / 0), 1)
    ok(
        "transform with ctx issue",
        z.string().transform(lambda s, ctx: ctx.addIssue({"message": "nope"}) or s),
        "x",
    )
    ok("preprocess", z.preprocess(lambda v: int(v) if isinstance(v, str) else v, z.int()), "42")
    ok("overwrite keeps type", z.string().overwrite(lambda s: s.upper()).min(2), "ab")
    ok(
        "string -> datetime",
        z.iso.datetime().transform(lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))),
        "2024-01-01T00:00:00Z",
    )
    ok("number -> string -> length", z.number().pipe(z.transform(str)).pipe(z.string().max(2)), 1000)

    section("optional / nullable / default / prefault / catch")
    ok("optional", z.string().optional(), None)
    ok("nullish", z.string().nullish(), None)
    ok("nonoptional", z.string().optional().nonoptional(), None)
    ok("default short-circuits", z.string().min(5).default("ab"), None)
    ok("prefault validates", z.string().min(5).prefault("ab"), None)
    ok("default fn", z.array(z.int()).default(lambda: [1]), None)
    ok("catch", z.int().catch(0), "nope")
    ok("catch fn gets ctx", z.int().catch(lambda ctx: -len(ctx.error.issues)), "nope")
    ok("object defaults applied", Settings, {"size": "huge"})
    print(f"       isOptional: {z.string().optional().isOptional()}, {z.string().isOptional()}")

    section("codec (bidirectional)")
    IsoDate = z.codec(
        z.iso.datetime(),
        z.date(),
        {
            "decode": lambda s: datetime.fromisoformat(s.replace("Z", "+00:00")),
            "encode": lambda d: d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    )
    d = ok("decode", IsoDate, "2024-06-01T10:00:00Z")
    print(f"       encode -> {z.encode(IsoDate, d)!r}")
    print(f"       safeEncode(bad).success -> {IsoDate.safeEncode('x').success}")
    JsonStr = z.codec(
        z.string(),
        Counter,
        {"decode": __import__("json").loads, "encode": lambda c: __import__("json").dumps(c.to_dict())},
    )
    ok("json codec decode", JsonStr, '{"n": 1}')
    print(f"       json codec encode -> {z.encode(JsonStr, Counter(n=2))!r}")
    try:
        z.encode(z.string().transform(len), 3)
    except z.ZodEncodeError as e:
        print(f"       encode through transform -> ZodEncodeError: {e}")
    DateToIso = z.invertCodec(IsoDate)
    print(f"       invertCodec decode(datetime) -> {z.decode(DateToIso, d)!r}")
    print(f"       invertCodec encode(str) -> {z.encode(DateToIso, '2024-06-01T10:00:00Z')!r}")

    def to_num(val, ctx):
        try:
            return float(val)
        except ValueError:
            ctx.issues.push({"code": "custom", "message": "Not a number", "input": val})
            return z.NEVER

    ok("transform returning z.NEVER", z.string().transform(to_num), "abc")

    section("instanceof + properties")

    class Response:
        def __init__(self, status, redirected):
            self.status, self.redirected = status, redirected

        def __repr__(self):
            return f"Response({self.status}, {self.redirected})"

    OkResponse = z.instanceof(Response).properties(
        {"status": z.number().min(200).max(299), "redirected": z.literal(False)}
    )
    ok("properties ok", OkResponse, Response(204, False))
    ok("properties fail (paths)", OkResponse, Response(500, True))
    ok("z.property on dict", z.any().check(z.property("x", z.int())), {"x": "no"})
    Result = z.discriminatedUnion("status", [Success, Failed])  # output: Success | Failed
    opt = z.getDiscriminatedOption(Result, "success")
    print(f"       getDiscriminatedOption(Result, 'success').shape keys = {list(opt.shape)}")
    ok("discriminator message lists options", Result, {"status": "pending"})

    section("function schemas")
    Add = z.function({"input": [z.number(), z.number()], "output": z.number()})

    @Add.implement
    def add(a, b):
        return a + b

    print(f"       add(1, 2) = {add(1, 2)}")
    try:
        add("1", 2)
    except z.ZodError as e:
        print(f"       add('1', 2) -> {e.issues[0]['message']} at {e.issues[0]['path']}")
    Bad = z.function({"input": [z.string()], "output": z.int()}).implement(lambda s: s)
    try:
        Bad("x")
    except z.ZodError as e:
        print(f"       bad return -> {e.issues[0]['message']}")
