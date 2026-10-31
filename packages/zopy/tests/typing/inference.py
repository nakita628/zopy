# pyright: reportUnnecessaryTypeIgnoreComment=true
"""Static type-inference checks. Run with ``uv run pyright packages/zopy/tests/typing``.

``reveal_type(expr, expected_text=...)`` makes pyright report an error when the
inferred type differs, so this file doubles as a regression test for the generics.
"""

from enum import Enum
from typing import reveal_type

from zopy import z


class Color(Enum):
    RED = "red"


data: object = None

# primitives
reveal_type(z.string().min(1).trim().parse(data), expected_text="str")
reveal_type(z.number().int().positive().parse(data), expected_text="int")
reveal_type(z.int().parse(data), expected_text="int")
reveal_type(z.int32().parse(data), expected_text="int")
reveal_type(z.bigint().parse(data), expected_text="int")
reveal_type(z.boolean().parse(data), expected_text="bool")
reveal_type(z.date().parse(data), expected_text="datetime")
reveal_type(z.coerce.number().parse(data), expected_text="float")
reveal_type(z.stringbool().parse(data), expected_text="bool")
reveal_type(z.literal("tuna").parse(data), expected_text="Literal['tuna']")
reveal_type(z.literal(("a", "b")).parse(data), expected_text="Literal['a', 'b']")
reveal_type(z.literal(1).parse(data), expected_text="int")
reveal_type(
    z.enum(("admin", "user")).parse(data), expected_text="Literal['admin', 'user']"
)  # tuple keeps literals
reveal_type(z.enum(Color).parse(data), expected_text="Color")
Role = z.enum(("admin", "user", "guest"))
reveal_type(Role.extract(("admin", "user")).parse(data), expected_text="Literal['admin', 'user']")
reveal_type(Role.exclude(("guest",)).parse(data), expected_text="Literal['admin', 'user', 'guest']")

# readonly: the output is typed as the frozen value it is at runtime
reveal_type(z.array(z.int()).readonly().parse(data), expected_text="tuple[int, ...]")
reveal_type(z.record(z.string(), z.int()).readonly().parse(data), expected_text="Mapping[str, int]")
reveal_type(z.map(z.int(), z.string()).readonly().parse(data), expected_text="Mapping[int, str]")
reveal_type(z.set(z.int()).readonly().parse(data), expected_text="frozenset[int]")
reveal_type(z.tuple((z.int(), z.string())).readonly().parse(data), expected_text="tuple[int, str]")
reveal_type(z.readonly(z.array(z.string())).parse(data), expected_text="tuple[str, ...]")
z.array(z.int()).readonly().parse(data).append(1)  # pyright: ignore[reportAttributeAccessIssue]
z.array(z.int()).readonly().parse(data)[0] = 1  # pyright: ignore[reportIndexIssue]
z.record(z.string(), z.int()).readonly().parse(data)["a"] = 1  # pyright: ignore[reportIndexIssue]
z.map(z.int(), z.string()).readonly().parse(data)[1] = "a"  # pyright: ignore[reportIndexIssue]
z.set(z.int()).readonly().parse(data).add(1)  # pyright: ignore[reportAttributeAccessIssue]
reveal_type(z.any().readonly().parse(data), expected_text="Any")  # not a tuple: Any could be anything
reveal_type(z.string().optional().readonly().parse(data), expected_text="str | None")
Role.exclude(("root",))  # pyright: ignore[reportArgumentType]  -- not a member
reveal_type(z.instanceof(Color).parse(data), expected_text="Color")

# wrappers
reveal_type(z.string().optional().parse(data), expected_text="str | None")
reveal_type(z.string().nullable().parse(data), expected_text="str | None")
reveal_type(z.string().nullish().parse(data), expected_text="str | None")
reveal_type(z.string().exactOptional().parse(data), expected_text="str | None")
reveal_type(z.string().default("x").parse(data), expected_text="str")
reveal_type(z.string().optional().default("x").parse(data), expected_text="str")
reveal_type(z.array(z.string()).default(list).parse(data), expected_text="list[str]")
reveal_type(z.int().catch(0).parse(data), expected_text="int")
reveal_type(z.string().optional().nonoptional().parse(data), expected_text="str")
reveal_type(z.string().readonly().parse(data), expected_text="str")
reveal_type(z.string().refine(lambda s: s.startswith("a")).parse(data), expected_text="str")

# collections
reveal_type(z.array(z.string()).min(1).parse(data), expected_text="list[str]")
reveal_type(z.string().array().parse(data), expected_text="list[str]")
reveal_type(z.tuple((z.string(), z.number())).parse(data), expected_text="tuple[str, float]")
reveal_type(z.tuple((z.string(),), z.int()).parse(data), expected_text="tuple[str, *tuple[int, ...]]")
reveal_type(z.record(z.string(), z.int()).parse(data), expected_text="dict[str, int]")
reveal_type(z.map(z.int(), z.string()).parse(data), expected_text="dict[int, str]")
reveal_type(z.set(z.uuid()).parse(data), expected_text="set[str]")

# unions / effects
reveal_type(z.union([z.string(), z.number()]).parse(data), expected_text="float | str")
reveal_type((z.string() | z.boolean()).parse(data), expected_text="str | bool")
reveal_type(z.xor([z.string(), z.number()]).parse(data), expected_text="float | str")
reveal_type(z.string().transform(lambda s: len(s)).parse(data), expected_text="int")
reveal_type(z.string().transform(lambda s, ctx: s.upper()).parse(data), expected_text="str")
reveal_type(z.string().transform(len).pipe(z.number().max(5)).parse(data), expected_text="float")
reveal_type(z.preprocess(lambda v: v, z.int()).parse(data), expected_text="int")
reveal_type(z.lazy(lambda: z.string()).parse(data), expected_text="str")

# class-declared objects: the class is the output type


class Account(z.Object):
    name = z.string().min(1)
    age = z.int().optional()
    tags = z.array(z.string()).default(list)


class Team(z.Object):
    owner = Account
    members = z.array(Account)
    lead = Account.optional()


acct = Account.parse(data)
reveal_type(acct, expected_text="Account")
reveal_type(Account.readonly().parse(data), expected_text="Account")
reveal_type(z.readonly(Account).parse(data), expected_text="Account")
reveal_type(z.array(Account).readonly().parse(data), expected_text="tuple[Account, ...]")
reveal_type(Account.readonly().parse(data).tags, expected_text="list[str]")  # shallow: fields keep their type


class Tagged(z.Object):
    tags = z.array(z.string()).readonly()


reveal_type(Tagged.parse(data).tags, expected_text="tuple[str, ...]")
Tagged.parse(data).tags.append("x")  # pyright: ignore[reportAttributeAccessIssue]
reveal_type(acct.name, expected_text="str")
reveal_type(acct.age, expected_text="int | None")
reveal_type(acct.tags, expected_text="list[str]")
reveal_type(Account.name, expected_text="ZodString")
reveal_type(Account.safeParse(data), expected_text="SafeParseSuccess[Account] | SafeParseError")
reveal_type(Account.array().parse(data), expected_text="list[Account]")
reveal_type(z.array(Account).parse(data), expected_text="list[Account]")
reveal_type(z.optional(Account).parse(data), expected_text="Account | None")
team = Team.parse(data)
reveal_type(team.owner, expected_text="Account")
reveal_type(team.members, expected_text="list[Account]")
reveal_type(team.lead, expected_text="Account | None")
reveal_type(z.tuple((z.string(), Account)).parse(data), expected_text="tuple[str, Account]")
reveal_type(z.map(z.string(), Account).parse(data), expected_text="dict[str, Account]")
reveal_type(z.record(z.string(), Account).parse(data), expected_text="dict[str, Account]")

# safeParse narrowing
r = z.string().safeParse(data)
reveal_type(r, expected_text="SafeParseSuccess[str] | SafeParseError")
if r.success is True:
    reveal_type(r.data, expected_text="str")
else:
    reveal_type(r.error, expected_text="ZodError")
if r.error is None:
    reveal_type(r.data, expected_text="str")
if r:
    reveal_type(r.data, expected_text="str")
else:
    reveal_type(r.error, expected_text="ZodError")
# Zod's own idioms: ``if result.success`` / ``if not result.success`` / early return
if r.success:
    reveal_type(r.data, expected_text="str")
else:
    reveal_type(r.error.issues, expected_text="list[ZodIssue]")
if not r.success:
    reveal_type(r.error, expected_text="ZodError")
reveal_type(r.data, expected_text="str")
users = Account.array().safeParse(data)
if users.success:
    reveal_type(users.data, expected_text="list[Account]")
acct_result = Account.safeParse(data)
if acct_result.success:
    reveal_type(acct_result.data, expected_text="Account")
    reveal_type(acct_result.data.age, expected_text="int | None")

# top-level helpers
reveal_type(z.parse(z.boolean(), data), expected_text="bool")
