"""z.toJSONSchema in several targets."""

from __future__ import annotations

import json

from zopy import z

from ..show import section


class AddressFields(z.Object):
    street = z.string()
    zip = z.string().regex(r"^\d{3}-\d{4}$")


Address = AddressFields.meta({"id": "Address", "title": "Address"})  # emitted once under $defs


class User(z.Object):
    id = z.uuid()
    name = z.string().min(1).max(50).meta({"description": "Display name"})
    age = z.int().gte(0).lt(150).optional()
    role = z.enum(("admin", "user")).default("user")
    email = z.email().nullable()
    address = Address
    tags = z.array(z.string()).max(10)
    position = z.tuple((z.number(), z.number()))
    meta = z.record(z.string(), z.union([z.string(), z.number()]))
    friends = z.lazy(lambda: z.array(User)).optional()  # recursive -> $ref


class Event(z.Object):
    when = z.date()


def run() -> None:
    section("toJSONSchema")
    print(json.dumps(z.toJSONSchema(User), indent=2))
    print("\n  io=input (defaults optional, no additionalProperties):")
    inp = z.toJSONSchema(User, {"io": "input"})
    print(f"    required = {inp['required']}")
    print("\n  draft-7 tuple:", json.dumps(z.toJSONSchema(z.tuple((z.string(),)), {"target": "draft-7"})))
    print(
        "  openapi-3.0 nullable:",
        json.dumps(z.toJSONSchema(z.string().nullable(), {"target": "openapi-3.0"})),
    )
    print(
        "  unrepresentable=any:",
        json.dumps(z.toJSONSchema(Event, {"unrepresentable": "any"})),
    )
    try:
        z.toJSONSchema(z.date())
    except ValueError as e:
        print(f"  unrepresentable=throw: {e}")
    reg = z.registry()
    z.string().register(reg, {"id": "Name"})
    z.int().register(reg, {"id": "Age"})
    print("  registry:", json.dumps(z.toJSONSchema(reg)))
