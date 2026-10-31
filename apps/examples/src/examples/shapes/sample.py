"""A realistic payload: an order posted to an API, parsed end to end (``uv run examples sample``)."""

from __future__ import annotations

import json
import timeit
from typing import Any

from zopy import z
from zopy._compile import engine, rust_available, set_engine

from ..show import section


class Address(z.Object):
    street = z.string().trim().min(1)
    city = z.string().min(1)
    zip = z.string().regex(r"^\d{3}-\d{4}$")
    country = z.enum(("JP", "US")).default("JP")


class Item(z.Object):
    sku = z.string().regex(r"^[A-Z]{3}-\d{4}$")
    name = z.string().min(1).max(80)
    quantity = z.int().positive().max(99)
    unit_price = z.number().nonnegative()


class Customer(z.Object):
    id = z.uuid()
    name = z.string().min(1)
    email = z.email().toLowerCase()
    phone = z.string().optional()


class Order(z.Object):
    order_id = z.string().startsWith("ORD-")
    created_at = z.iso.datetime()
    customer = Customer
    shipping = Address
    items = z.array(Item).min(1).max(50)
    coupon = z.string().toUpperCase().optional()
    note = z.string().max(200).default("")
    # refine runs in Python; the rest of the tree stays in Rust.
    paid = z.boolean()


# Order-level rule written with refine: at most 10 units of one SKU in total.
OrderChecked = Order.refine(
    lambda o: all(sum(i.quantity for i in o.items if i.sku == s.sku) <= 10 for s in o.items),
    "too many units of one SKU",
)

SAMPLE: dict[str, Any] = {
    "order_id": "ORD-20261028-0001",
    "created_at": "2026-10-28T09:30:00Z",
    "customer": {
        "id": "123e4567-e89b-12d3-a456-426614174000",
        "name": "Ada Lovelace",
        "email": "Ada@Example.COM",
    },
    "shipping": {"street": "  1-2-3 Chiyoda  ", "city": "Tokyo", "zip": "100-0001"},
    "items": [
        {"sku": "BOK-0001", "name": "Analytical Engine Manual", "quantity": 2, "unit_price": 3200},
        {"sku": "PEN-0420", "name": "Fountain pen", "quantity": 1, "unit_price": 1500.5},
    ],
    "coupon": "autumn10",
    "paid": True,
}

BROKEN: dict[str, Any] = {
    **SAMPLE,
    "created_at": "yesterday",
    "customer": {**SAMPLE["customer"], "email": "not-an-email"},
    "shipping": {**SAMPLE["shipping"], "zip": "1000001"},
    "items": [{"sku": "bok-1", "name": "", "quantity": 0, "unit_price": -1}],
}


def run() -> None:
    section("Sample: input JSON")
    print(json.dumps(SAMPLE, indent=2, ensure_ascii=False))

    section("Sample: Order.parse(SAMPLE)")
    order = OrderChecked.parse(SAMPLE)  # an Order instance; fields are typed
    print(f"  {order!r}")
    print(f"  customer.email (lower-cased) : {order.customer.email}")
    print(f"  shipping.street (trimmed)    : {order.shipping.street!r}")
    print(f"  shipping.country (default)   : {order.shipping.country}")
    print(f"  coupon (upper-cased)         : {order.coupon}")
    total = sum(item.quantity * item.unit_price for item in order.items)
    print(f"  total                        : {total:,.1f} JPY ({len(order.items)} lines)")

    section("Sample: safeParse(BROKEN) -> issues")
    result = OrderChecked.safeParse(BROKEN)
    if result.success:
        print("  unexpectedly valid")
    else:
        for issue in result.error.issues:
            path = ".".join(str(p) for p in issue["path"])
            print(f"  {path:<24} {issue['code']:<16} {issue['message']}")

    section("Sample: refine (Python) on top of the Rust-validated tree")
    over = {**SAMPLE, "items": [{**SAMPLE["items"][0], "quantity": 6}, {**SAMPLE["items"][0], "quantity": 5}]}
    refined = OrderChecked.safeParse(over)
    print(f"  Order.parse ok       : {Order.safeParse(over).success}")
    print(f"  OrderChecked ok      : {refined.success}")
    if not refined.success:
        print(f"  message              : {refined.error.issues[0]['message']}")

    _timings()


def _timings() -> None:
    section("Sample: speed (per parse, best of 7)")

    def best(fn: Any, n: int = 5000) -> float:
        fn()
        return min(timeit.repeat(fn, number=n, repeat=7)) / n * 1e6

    engines = ["rust", "python"] if rust_available() else ["python"]
    previous = engine()
    try:
        for name in engines:
            set_engine(name)
            print(f"  zod ({name:<6}) Order.parse         {best(lambda: Order.parse(SAMPLE)):7.2f} µs")
            print(f"  zod ({name:<6}) OrderChecked.parse  {best(lambda: OrderChecked.parse(SAMPLE)):7.2f} µs")
            print(f"  zod ({name:<6}) safeParse(BROKEN)   {best(lambda: _read_issues(Order)):7.2f} µs")
    finally:
        set_engine(previous)
    pydantic_model = _pydantic_order()
    if pydantic_model is None:
        print("  (pydantic not installed; skipped)")
        return
    print(f"  pydantic     model_validate      {best(lambda: pydantic_model.model_validate(SAMPLE)):7.2f} µs")
    print(f"  pydantic     invalid + errors()  {best(lambda: _pydantic_errors(pydantic_model)):7.2f} µs")


def _read_issues(schema: Any) -> None:
    result = schema.safeParse(BROKEN)
    assert result.error is not None
    _ = result.error.issues


def _pydantic_errors(model: Any) -> None:
    from pydantic import ValidationError  # pyright: ignore[reportMissingImports]

    try:
        model.model_validate(BROKEN)
    except ValidationError as e:
        e.errors()


def _pydantic_order() -> Any:
    """The same rules in pydantic, for comparison (only if pydantic happens to be installed)."""
    try:
        from pydantic import (  # pyright: ignore[reportMissingImports]
            BaseModel,
            EmailStr,
            Field,
            StringConstraints,
        )
    except ImportError:
        return None
    from importlib.util import find_spec
    from typing import Annotated, Literal

    # ``EmailStr`` needs the optional ``email-validator`` package; without it the email is a plain ``str``.
    email_type: Any = EmailStr if find_spec("email_validator") else str
    from datetime import datetime
    from uuid import UUID

    class PAddress(BaseModel):
        street: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
        city: Annotated[str, StringConstraints(min_length=1)]
        zip: Annotated[str, StringConstraints(pattern=r"^\d{3}-\d{4}$")]
        country: Literal["JP", "US"] = "JP"

    class PItem(BaseModel):
        sku: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}-\d{4}$")]
        name: Annotated[str, StringConstraints(min_length=1, max_length=80)]
        quantity: int = Field(gt=0, le=99)
        unit_price: float = Field(ge=0)

    class PCustomer(BaseModel):
        id: UUID
        name: Annotated[str, StringConstraints(min_length=1)]
        email: email_type  # type: ignore[valid-type]
        phone: str | None = None

    class POrder(BaseModel):
        order_id: Annotated[str, StringConstraints(pattern=r"^ORD-")]
        created_at: datetime
        customer: PCustomer
        shipping: PAddress
        items: list[PItem] = Field(min_length=1, max_length=50)
        coupon: Annotated[str, StringConstraints(to_upper=True)] | None = None
        note: Annotated[str, StringConstraints(max_length=200)] = ""
        paid: bool

    return POrder
