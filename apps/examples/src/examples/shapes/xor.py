"""XOR (exactly one of) patterns.

``z.xor`` plus the idioms Zod users reach for; objects are ``class X(z.Object)`` schemas,
everything else is written as in Zod.
"""

from __future__ import annotations

from zopy import z

from ..show import ok, section


def xor(a: z.ZodType, b: z.ZodType, message: str = "Expected exactly one of the alternatives to match"):
    """Reusable helper: accepts a value iff exactly one of ``a`` / ``b`` accepts it."""

    def exactly_one(value, ctx):
        matched = [s for s in (a, b) if s.safeParse(value).success]
        if len(matched) == 1:
            return
        ctx.addIssue({"code": "custom", "message": message, "params": {"matched": len(matched)}})

    return z.union([a, b]).superRefine(exactly_one)


class Name(z.Object):
    name = z.string()


class Version(Name):  # Name.extend({"version": z.string()})
    version = z.string()


class StrictName(Name, z.StrictObject):  # (Zod: Name.strict())
    pass


class ContactFields(z.Object):
    email = z.email().optional()
    phone = z.e164().optional()


Contact = ContactFields.refine(
    lambda c: (c.email is None) != (c.phone is None),  # c: ContactFields
    {"error": "Provide either email or phone, not both", "path": ["email"]},
)


class ById(z.StrictObject):
    id = z.uuid()


class BySlug(z.StrictObject):
    slug = z.string().regex(r"^[a-z0-9-]+$")


class Card(z.Object):
    method = z.literal("card")
    last4 = z.string().length(4)


class Bank(z.Object):
    method = z.literal("bank")
    iban = z.string().min(15)


class Cash(z.Object):
    method = z.literal("cash")


def run() -> None:
    section("XOR: built-in z.xor (exclusive union)")
    StrOrNum = z.xor([z.string(), z.number()])
    ok("z.xor string", StrOrNum, "hello")
    ok("z.xor zero matches -> fail", StrOrNum, True)
    ok("z.xor both match -> fail", z.xor([Name, Version]), {"name": "zod", "version": "4"})
    ok("z.xor with strict disambiguates", z.xor([StrictName, Version]), {"name": "zod", "version": "4"})
    r = z.xor([z.int().multipleOf(2), z.int().positive()]).safeParse(4)
    assert r.error is not None
    iss = r.error.issues[0]
    print(f"       issue for 4 (even & positive): inclusive={iss['inclusive']}, matches={iss['matches']}")

    section("XOR: exactly one of two keys (refine on object)")
    ok("email only", Contact, {"email": "a@b.co"})
    ok("phone only", Contact, {"phone": "+819012345678"})
    ok("both -> fail", Contact, {"email": "a@b.co", "phone": "+819012345678"})
    ok("neither -> fail", Contact, {})

    section("XOR: union of strict objects (shape-level exclusivity)")
    Lookup = z.union([ById, BySlug])  # output: ById | BySlug
    ok("by id", Lookup, {"id": "123e4567-e89b-12d3-a456-426614174000"})
    ok("by slug", Lookup, {"slug": "hello-world"})
    ok("both keys -> fail (strict)", Lookup, {"id": "123e4567-e89b-12d3-a456-426614174000", "slug": "x"})

    section("XOR: discriminatedUnion (tagged alternatives)")
    Payment = z.discriminatedUnion("method", [Card, Bank, Cash])  # output: Card | Bank | Cash
    ok("card", Payment, {"method": "card", "last4": "4242"})
    ok("cash", Payment, {"method": "cash"})
    ok("unknown tag -> fail", Payment, {"method": "crypto"})
    ok("card with bad last4 -> fail", Payment, {"method": "card", "last4": "42"})

    section("XOR: generic xor() helper over arbitrary schemas")
    IntOrShortString = xor(z.int(), z.string().max(3))
    ok("int", IntOrShortString, 7)
    ok("short string", IntOrShortString, "abc")
    ok("long string -> fail (neither)", IntOrShortString, "abcd")
    Even = z.int().multipleOf(2)
    Positive = z.int().positive()
    EvenXorPositive = xor(Even, Positive)
    ok("-4 (even only)", EvenXorPositive, -4)
    ok("3 (positive only)", EvenXorPositive, 3)
    ok("4 (both) -> fail", EvenXorPositive, 4)
    ok("-3 (neither) -> fail", EvenXorPositive, -3)

    section("XOR: at-most-one / at-least-one of N keys (superRefine)")

    def exactly_one_of(*keys):
        def check(value, ctx):
            present = [k for k in keys if getattr(value, k) is not None]
            if len(present) != 1:
                ctx.addIssue(
                    {
                        "code": "custom",
                        "message": f"Exactly one of {', '.join(keys)} is required (got {len(present)})",
                    }
                )

        return check

    class TriggerFields(z.Object):
        cron = z.string().optional()
        interval = z.int().positive().optional()
        webhook = z.url().optional()

    Trigger = TriggerFields.superRefine(exactly_one_of("cron", "interval", "webhook"))
    ok("cron", Trigger, {"cron": "* * * * *"})
    ok("two -> fail", Trigger, {"cron": "* * * * *", "interval": 5})
    ok("none -> fail", Trigger, {})
