"""Async refinements / transforms."""

from __future__ import annotations

import asyncio

from zopy import z

from ..show import section

TAKEN = {"admin", "root"}


async def username_available(name: str) -> bool:
    await asyncio.sleep(0)  # pretend DB call
    return name not in TAKEN


Username = z.string().min(3).refine(username_available, "Username is taken")


class Signup(z.Object):
    username = Username
    friends = z.array(Username).max(2)


async def _main() -> None:
    r = await Signup.safeParseAsync({"username": "ada", "friends": ["bob", "root"]})
    if not r.success:
        print(f"  friends[1] taken -> {[(i['path'], i['message']) for i in r.error.issues]}")
    r = await Signup.safeParseAsync({"username": "ada", "friends": ["bob"]})
    if r.success:
        print(f"  all good -> {r.data}  friends={r.data.friends}")  # r.data: Signup

    async def fetch_length(s: str) -> int:
        await asyncio.sleep(0)
        return len(s)

    print(f"  async transform -> {await z.string().transform(fetch_length).parseAsync('hello')}")
    try:
        Username.parse("ada")
    except z.ZodAsyncError as e:
        print(f"  sync parse of async schema -> ZodAsyncError: {e}")

    Lookup = z.function({"input": [z.string()], "output": z.int()}).implementAsync(fetch_length)
    print(f"  implementAsync -> {await Lookup('abcd')}")


def run() -> None:
    section("Async")
    asyncio.run(_main())
