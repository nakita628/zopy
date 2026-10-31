"""parse / safeParse in a few lines: ``uv run examples quickstart``.

Hover any variable in VS Code to see its type; the ``# =>`` comments show what Pylance reports.
"""

from __future__ import annotations

from zopy import z

from ..show import section


class User(z.Object):
    name = z.string().trim().min(1)
    age = z.int().nonnegative()
    email = z.email()
    tags = z.array(z.string()).default(list)
    nickname = z.string().optional()


GOOD = {"name": "  Ada  ", "age": 36, "email": "ada@example.com"}
BAD = {"name": "", "age": -1, "email": "nope"}


def run() -> None:
    section("Quickstart: parse (valid input)")
    user = User.parse(GOOD)  # => User
    print(f"  user            = {user!r}")
    print(f"  user.name       = {user.name!r}  (trimmed)  type: {type(user.name).__name__}")  # => str
    print(f"  user.age + 1    = {user.age + 1}  type: {type(user.age).__name__}")  # => int
    print(f"  user.tags       = {user.tags}  (default)")  # => list[str]
    print(f"  user.nickname   = {user.nickname}")  # => str | None

    section("Quickstart: parse (invalid input raises ZodError)")
    try:
        User.parse(BAD)
    except z.ZodError as error:
        for issue in error.issues:
            print(f"  {'.'.join(map(str, issue['path'])):<8} {issue['message']}")

    section("Quickstart: safeParse (no exception)")
    for label, data in (("GOOD", GOOD), ("BAD", BAD)):
        result = User.safeParse(data)  # => SafeParseSuccess[User] | SafeParseError
        if result.success:
            print(f"  {label}: success  data.name={result.data.name!r}")  # result.data => User
        else:
            messages = [issue["message"] for issue in result.error.issues]  # result.error => ZodError
            print(f"  {label}: failure  {len(messages)} issues: {messages}")

    section("Quickstart: plain schemas")
    print(f"  z.string().parse('hi')              = {z.string().parse('hi')!r}")  # => str
    print(f"  z.array(z.int()).parse([1, 2])      = {z.array(z.int()).parse([1, 2])}")  # => list[int]
    print(f"  z.int().safeParse('x').success      = {z.int().safeParse('x').success}")
    print("  error message (z.prettifyError):")
    result = z.int().positive().safeParse(-5)
    if not result.success:
        print("    " + z.prettifyError(result.error).replace("\n", "\n    "))
