"""Arrays, tuples, unions, combining objects (multiple inheritance), recursion."""

from __future__ import annotations

from zopy import z

from ..show import ok, section


class Count(z.Object):
    n = z.int()


class Person(z.Object):
    name = z.string()


class Employee(z.Object):
    company = z.string()


# z.intersection(Person, Employee) -> a class with both bases: the fields of each are combined.
# A field declared differently by both bases is a TypeError until the subclass redeclares it.
class Staff(Person, Employee):
    pass


class StrictStaff(Staff, z.StrictObject):  # a strict variant of Staff
    pass


class Node(z.Object):
    value = z.int()
    children = z.lazy(lambda: z.array(Node)).default(list)  # recursive: list[Node]


class Circle(z.Object):
    kind = z.literal("circle")
    r = z.number().positive()


class Rect(z.Object):
    kind = z.literal("rect")
    w = z.number().positive()
    h = z.number().positive()


class Triangle(z.Object):
    kind = z.enum(("tri", "triangle"))
    sides = z.tuple((z.number(), z.number(), z.number()))


def run() -> None:
    section("Arrays")
    Tags = z.array(z.string().min(1)).min(1).max(3)
    ok("array ok", Tags, ["a", "b"])
    ok("array empty", Tags, [])
    ok("array too many", Tags, ["a", "b", "c", "d"])
    ok("array element path", Tags, ["a", ""])
    ok("tuple input keeps tuple", Tags, ("x",))
    ok("nonempty", z.string().array().nonempty(), ["x"])
    ok("array of objects", z.array(Count), [{"n": 1}, {"n": "2"}])

    section("Tuples")
    Point = z.tuple((z.number(), z.number()))  # a Python tuple of schemas
    ok("tuple", Point, [1.5, 2])
    ok("tuple too long", Point, [1, 2, 3])
    ok("tuple too short", Point, [1])
    Row = z.tuple((z.string(), z.int()), z.boolean())  # rest as 2nd arg (or .rest(z.boolean()))
    ok("tuple rest", Row, ["id", 1, True, False])
    ok("tuple rest wrong", Row, ["id", 1, "no"])
    ok("tuple optional tail", z.tuple((z.string(), z.int().optional())), ["only"])

    section("Unions")
    StrOrNum = z.union([z.string(), z.number()])
    ok("union str", StrOrNum, "x")
    ok("union num", StrOrNum, 1)
    ok("union neither", StrOrNum, True)
    ok("union via |", (z.literal("a") | z.literal("b")), "b")
    ok("union dirty option surfaces its issue", z.union([z.string().min(3), z.number()]), "ab")
    ok("union of literals", z.union([z.literal(1), z.literal(2)]), 3)

    section("Combining objects (multiple inheritance)")
    ok("class Staff(Person, Employee)", Staff, {"name": "Ada", "company": "Acme"})
    ok("fields from both bases required", Staff, {"name": "Ada"})
    staff = Staff.parse({"name": "Ada", "company": "Acme"})  # => Staff
    both = isinstance(staff, Person) and isinstance(staff, Employee)
    print(f"       staff.name={staff.name!r} staff.company={staff.company!r} is Person & Employee: {both}")
    ok("StrictStaff rejects extra", StrictStaff, {"name": "Ada", "company": "X", "x": 1})

    section("Recursive (lazy)")
    tree = {"value": 1, "children": [{"value": 2}, {"value": 3, "children": [{"value": "x"}]}]}
    ok("tree", Node, tree)
    ok("tree ok", Node, {"value": 1, "children": [{"value": 2}]})
    JSON = z.json()
    ok("z.json()", JSON, {"a": [1, 2.5, "s", None, True, {"b": {}}]})
    ok("z.json() rejects set", JSON, {"a": {1, 2}})

    section("Discriminated union with nested shapes")
    Shape = z.discriminatedUnion("kind", [Circle, Rect, Triangle])  # output: Circle | Rect | Triangle
    ok("circle", Shape, {"kind": "circle", "r": 1})
    ok("enum discriminator", Shape, {"kind": "triangle", "sides": [3, 4, 5]})
    ok("rect wrong field", Shape, {"kind": "rect", "w": 1, "h": -1})
    ok("no discriminator", Shape, {"r": 1})
    print(f"       Shape.options = {len(Shape.options)}, discriminator = {Shape.discriminator!r}")
    shape = Shape.parse({"kind": "rect", "w": 2, "h": 3})
    if isinstance(shape, Rect):  # narrowing works like a TS discriminated union
        print(f"       area of Rect = {shape.w * shape.h}")
