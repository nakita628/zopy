"""Type inference in practice.

Every ``# =>`` comment is what Pylance shows on hover. ``uv run pyright apps/examples``
checks this file, so the comments are verified, not aspirational.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from zopy import z

from ..show import section

raw: object = {
    "id": "123e4567-e89b-12d3-a456-426614174000",
    "name": "  Ada ",
    "age": 36,
    "tags": ["math", "code"],
    "role": "admin",
}


# --- 1. Primitives: the schema decides the type of parse() --------------------------------------
Name = z.string().trim().min(1)
Age = z.int().positive().optional()
Tags = z.array(z.string()).max(5).default(list)
Role = z.enum(("admin", "member")).default("member")  # tuple keeps the literals
Score = z.number().gte(0).lte(100).catch(0)
CreatedAt = z.iso.datetime().transform(lambda s: datetime.fromisoformat(s.replace("Z", "+00:00")))


def primitives() -> None:
    name = Name.parse("  Ada ")  # => str
    age = Age.parse(None)  # => int | None
    tags = Tags.parse(None)  # => list[str]
    role = Role.parse(None)  # => Literal['admin', 'member']
    score = Score.parse("oops")  # => float
    created = CreatedAt.parse("2024-01-01T00:00:00Z")  # => datetime
    kind = z.literal("tuna").parse("tuna")  # => Literal['tuna']

    # Because the types are known, the rest of the code is checked too:
    print(f"  {name.upper()=} {len(tags)=} {role=} {score + 1=} {created.year=} {kind=}")
    if age is not None:  # narrowing works like any Optional
        print(f"  {age + 1=}")


# --- 2. Lambdas get their parameter types from the schema ---------------------------------------
Csv = (
    z.string()
    .transform(lambda s: [part.strip() for part in s.split(",")])  # s: str   => list[str]
    .pipe(z.array(z.string().min(1)).min(1))  #                                 => list[str]
    .transform(lambda items: {item: len(item) for item in items})  # items: list[str] => dict[str, int]
)

Even = z.int().refine(lambda n: n % 2 == 0, "must be even")  # n: int


def lambdas() -> None:
    lengths = Csv.parse("a, bb ,ccc")  # => dict[str, int]
    print(f"  {lengths=} {sum(lengths.values())=}")
    print(f"  {Even.safeParse(3).success=}")


# --- 3. Collections, unions, tuples, enums ------------------------------------------------------
class Color(Enum):
    RED = "red"
    GREEN = "green"


Point = z.tuple((z.number(), z.number()))  # Python tuple of schemas => tuple[float, float]
IdOrIndex = z.union([z.uuid(), z.int()])  # => int | str
Scores = z.record(z.string(), z.int().min(0))  # => dict[str, int]
Flags = z.set(z.enum(("a", "b")))  # => set[Literal['a', 'b']]
Paint = z.enum(Color)  # => Color (members are returned, values are accepted)


def collections() -> None:
    x, y = Point.parse([1.5, 2])  # x: float, y: float
    ident = IdOrIndex.parse(3)  # => int | str
    scores = Scores.parse({"math": 90})  # => dict[str, int]
    flags = Flags.parse({"a"})  # => set[Literal['a', 'b']]
    paint = Paint.parse("red")  # => Color
    label = ident.upper() if isinstance(ident, str) else f"#{ident}"  # narrowing on the union
    print(f"  {x + y=} {label=} {max(scores.values())=} {sorted(flags)=} {paint.name=}")


# --- 4. safeParse is a discriminated union ------------------------------------------------------
def safe_parse() -> None:
    result = Name.safeParse(42)  # => SafeParseSuccess[str] | SafeParseError
    if result.success is True:  # (or: `if result:` / `if result.error is None:`)
        print(f"  ok: {result.data.upper()}")  # result.data => str
    else:
        print(f"  error: {result.error.issues[0]['message']}")  # result.error => ZodError


# --- 5. Objects: the class IS the type (closest thing to z.infer) --------------------------------
class Account(z.Object):
    name = Name  # any schema expression; Account.name is the schema, account.name is the value
    age = Age
    tags = Tags
    role = Role


class Team(z.Object, strict=True):
    owner = Account  # nested class schema
    members = z.array(Account).default(list)
    lead = Account.optional()


def declared() -> None:
    account = Account.parse(raw)  # => Account
    print(
        f"  {account.name=} {account.age=} {account.role=}"
    )  # account.name => str, account.age => int | None
    team = Team.parse({"owner": raw, "members": [raw]})  # => Team
    print(f"  {team.owner.name=} {len(team.members)=} {team.lead=}")  # team.owner => Account
    result = Team.safeParse({"owner": raw, "unknown": 1})  # => SafeParseSuccess[Team] | SafeParseError
    if result:
        print(f"  ok: {result.data.owner.name}")
    else:
        print(f"  strict: {result.error.issues[0]['message']}")
    account.name = "Grace"  # typed assignment (account.name = 1 is a type error)
    print(f"  as dict: {account.to_dict()}  json schema required: {z.toJSONSchema(Account)['required']}")


# --- 6. There is no z.infer -----------------------------------------------------------------------
# Python has no `typeof`, so a schema value such as Name can never become a type. The type lives
# on parse() (sections 1-4), and for objects on the class you declared (section 5).


def run() -> None:
    section("Typing: inferred types (see `# =>` comments; verified by pyright)")
    primitives()
    lambdas()
    collections()
    safe_parse()
    declared()
