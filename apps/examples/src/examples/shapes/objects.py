"""Objects declared as ``class X(z.Object)``: nesting, unknown keys, shapes built by inheritance, records/maps/sets."""

from __future__ import annotations

from typing import NewType

from zopy import z

from ..show import ok, section

UserId = NewType("UserId", str)


class Profile(z.Object):
    bio = z.string().max(160).optional()
    links = z.array(z.url()).max(3).default(list)


class User(z.Object):
    id = z.int().positive()
    name = z.string().min(1)
    nickname = z.string().optional()
    role = z.enum(("admin", "user")).default("user")
    profile = Profile.default({"links": []})  # a dict default is parsed into a Profile


class Nick(z.Object):
    name = z.string().optional()
    nick = z.string().exactOptional()


class RecipeDraft(z.Object):  # Recipe.exactPartial(): declare the fields .exactOptional()
    title = z.string().exactOptional()
    description = z.string().optional()
    steps = z.array(z.string()).exactOptional()


class Base(z.Object):
    a = z.string()


class StrictBase(z.StrictObject):  # (Zod: z.strictObject) unknown keys are an error
    a = z.string()


class LooseBase(z.LooseObject):  # (Zod: z.looseObject) unknown keys are kept
    a = z.string()


class StrictFull(Base, z.StrictObject):  # a strict variant of an existing class (or `Base, strict=True`)
    pass


class NumberExtras(Base, catchall=z.number()):  # every unknown key must be a number
    pass


# Zod derives shapes with .pick/.omit/.extend/.partial; with classes you declare each shape and
# share fields through inheritance, so every derived shape is still a fully typed class.
class AB(z.Object):  # Full.pick({a, b}) -> the smaller class is the base
    a = z.string()
    b = z.number()


class Full(AB):  # AB.extend({c}) -> a subclass
    c = z.boolean()


class FullWithD(Full):  # Full.extend({d})
    d = z.string()


class FullPatch(z.Object):  # Full.partial() -> a class with optional fields
    a = z.string().optional()
    b = z.number().optional()
    c = z.boolean().optional()


class Point(z.Object):
    x = z.number()


def run() -> None:
    section("Objects: basics")
    ok("minimal", User, {"id": 1, "name": "Ada"})
    ok("unknown keys stripped", User, {"id": 1, "name": "Ada", "hacker": True})
    ok("nested failure path", User, {"id": 1, "name": "Ada", "profile": {"links": ["nope"]}})
    ok("missing key -> received undefined", User, {"name": "Ada"})
    ok("None explicit -> received undefined", User, {"id": None, "name": "Ada"})
    user = User.parse({"id": 1, "name": "Ada"})
    print(f"       user.profile.links = {user.profile.links}  (typed: list[str])")
    print(f"       User.keyof().options = {User.keyof().options}")

    section("Objects: optional vs exactOptional")
    ok("both absent", Nick, {})
    ok("name: None allowed (optional)", Nick, {"name": None})
    ok("nick: None rejected (exactOptional)", Nick, {"nick": None})
    ok("nick present", Nick, {"nick": "ada"})
    ok("all exactOptional: {}", RecipeDraft, {})
    ok("description None ok (optional)", RecipeDraft, {"description": None})
    ok("title None rejected (exactOptional)", RecipeDraft, {"title": None})

    section("Objects: strict / loose / catchall")
    ok("z.StrictObject rejects extra", StrictBase, {"a": "x", "b": 1})
    ok("z.LooseObject keeps extra", LooseBase, {"a": "x", "b": 1})
    ok("(Base, z.StrictObject) rejects extra", StrictFull, {"a": "x", "b": 1})
    ok("Base strips extra", Base, {"a": "x", "b": 1})
    ok("catchall=z.number()", NumberExtras, {"a": "x", "b": 1, "c": 2})
    ok("catchall rejects wrong extra", NumberExtras, {"a": "x", "b": "str"})
    ok(".catchall(z.number()) method", Base.catchall(z.number()), {"a": "x", "b": 1})

    section("Objects: shapes built by inheritance")
    ok("AB (= Full.pick a,b) strips c", AB, {"a": "x", "b": 1, "c": True})
    ok("Full (= AB.extend c)", Full, {"a": "x", "b": 1, "c": True})
    ok("FullWithD needs d", FullWithD, {"a": "x", "b": 1, "c": True})
    ok("FullPatch (= Full.partial())", FullPatch, {})
    ok("FullPatch still validates types", FullPatch, {"b": "two"})
    full = FullWithD.parse({"a": "x", "b": 1, "c": True, "d": "y"})  # => FullWithD
    print(f"       full.b + 1 = {full.b + 1}  isinstance(full, AB) = {isinstance(full, AB)}")

    section("Records / maps / sets")
    Scores = z.record(z.string(), z.int().min(0).max(100))
    ok("record", Scores, {"math": 90, "art": 75})
    ok("record bad value path", Scores, {"math": 101})
    ok("record bad key (int)", Scores, {1: 50})
    ok("record of objects", z.record(z.string(), Point), {"origin": {"x": 0}})
    Weekday = z.enum(("mon", "tue"))
    ok("record(enum) exhaustive", z.record(Weekday, z.boolean()), {"mon": True, "tue": False})
    ok("record(enum) missing key", z.record(Weekday, z.boolean()), {"mon": True})
    ok("partialRecord(enum)", z.partialRecord(Weekday, z.boolean()), {"mon": True})
    Phones = z.looseRecord(z.string().regex(r"_phone$"), z.e164())
    ok("looseRecord: *_phone validated, rest pass", Phones, {"home_phone": "+14155552671", "n": 1})
    ok("looseRecord: bad phone", Phones, {"home_phone": "nope"})
    ok("record key regex", z.record(z.string().regex(r"^[a-z]+$"), z.any()), {"ok": 1, "Not-OK": 2})
    ok("map(int -> str)", z.map(z.int(), z.string()), {1: "one", 2: "two"})
    ok("map bad key", z.map(z.int(), z.string()), {"1": "one"})
    ok("set(uuid)", z.set(z.uuid()).min(1), {"123e4567-e89b-12d3-a456-426614174000"})
    ok("set bad element", z.set(z.int()), {1, "two"})
    ok("set max", z.set(z.int()).max(1), {1, 2})

    section("Readonly, brand, meta")
    frozen = ok("readonly object", Point.readonly(), {"x": 1})
    print(f"       type(frozen) = {type(frozen).__name__}")
    # Brands are typing.NewType (Python's branded types); the annotation gives the parsed type.
    UserIdSchema: z.ZodType[UserId] = z.uuid().brand(UserId)
    uid = UserIdSchema.parse("123e4567-e89b-12d3-a456-426614174000")  # => UserId (value: a plain str)
    print(f"       branded: {uid!r}  type(uid) = {type(uid).__name__}")
    ok("branded uuid rejects non-uuid", UserIdSchema, "nope")
    Named = z.string().meta({"description": "A display name", "title": "Name", "examples": ["Ada"]})
    print(f"       description = {Named.description!r}, meta = {Named.meta()}")
