# pyright: reportUnnecessaryTypeIgnoreComment=true
"""Static types after ``parse`` / ``safeParse`` on a realistic nested model (checked by pyright).

``reveal_type(..., expected_text=...)`` fails the run when an inferred type changes, and each
``# pyright: ignore[...]`` below fails it when that mistake is *no longer* reported.
"""

from typing import Any, NewType, reveal_type

from zopy import z

data: Any = {}


class Customer(z.Object):
    name = z.string().min(1)
    email = z.email().toLowerCase()
    phone = z.string().optional()


class Item(z.Object):
    sku = z.string()
    quantity = z.int().positive()
    unit_price = z.number()


class Order(z.Object):
    customer = Customer
    items = z.array(Item).min(1)
    country = z.enum(("JP", "US")).default("JP")
    coupon = z.string().optional()
    paid = z.boolean()


Checked = Order.refine(lambda o: len(o.items) < 10, "too many lines")

# parse: the class itself is the output type, all the way down
order = Order.parse(data)
reveal_type(order, expected_text="Order")
reveal_type(order.customer, expected_text="Customer")
reveal_type(order.customer.email, expected_text="str")
reveal_type(order.customer.phone, expected_text="str | None")
reveal_type(order.items, expected_text="list[Item]")
reveal_type(order.items[0].quantity, expected_text="int")
reveal_type(order.items[0].unit_price, expected_text="float")
reveal_type(order.country, expected_text="Literal['JP', 'US']")
reveal_type(order.coupon, expected_text="str | None")
reveal_type(order.paid, expected_text="bool")
reveal_type(Checked.parse(data), expected_text="Order")

# safeParse: Zod's `if result.success` / `if not result.success`
result = Order.safeParse(data)
reveal_type(result, expected_text="SafeParseSuccess[Order] | SafeParseError")
if result.success:
    reveal_type(result.data, expected_text="Order")
    reveal_type(result.data.items[0].sku, expected_text="str")
else:
    reveal_type(result.error, expected_text="ZodError")
    reveal_type(result.error.issues, expected_text="list[ZodIssue]")
if not result.success:
    for issue in result.error.issues:
        reveal_type(issue, expected_text="ZodIssue")


# classes inside unions, records and transforms
class Cat(z.Object):
    kind = z.literal("cat")
    lives = z.int()


class Bird(z.Object):
    kind = z.literal("bird")
    can_fly = z.boolean()


class Admin(Customer):
    level = z.int()


pet = z.discriminatedUnion("kind", [Cat, Bird]).parse(data)
reveal_type(pet, expected_text="Cat | Bird")
if isinstance(pet, Cat):
    reveal_type(pet.lives, expected_text="int")
reveal_type(z.union([Cat, Bird]).parse(data), expected_text="Cat | Bird")
reveal_type(z.union([Cat, z.string()]).parse(data), expected_text="Cat | str")
reveal_type(z.union([z.string(), z.int()]).parse(data), expected_text="int | str")
reveal_type(z.record(z.string(), Item).parse(data), expected_text="dict[str, Item]")
reveal_type(Item.transform(lambda i: i.quantity * 2).parse(data), expected_text="int")
reveal_type(Admin.parse(data).level, expected_text="int")
reveal_type(Admin.parse(data).email, expected_text="str")


# self-reference: z.lazy over a schema or directly over a class
class Category(z.Object):
    name = z.string()
    children = z.lazy(lambda: z.array(Category)).default(list)


class Author(z.Object):
    name = z.string()
    posts = z.lazy(lambda: z.array(Article)).default(list)


class Article(z.Object):
    author = z.lazy(lambda: Author).optional()


reveal_type(Category.parse(data).children[0].children[0].name, expected_text="str")
reveal_type(Author.parse(data).posts[0].author, expected_text="Author | None")


# classes in ordinary annotations: `X | None` is a typing union for type checkers
def find_customer() -> Customer | None: ...


reveal_type(find_customer(), expected_text="Customer | None")

# brands: typing.NewType + a variable annotation (Python's branded types)
UserId = NewType("UserId", str)
OrderId = NewType("OrderId", str)
UserIdSchema: z.ZodType[UserId] = z.uuid().brand(UserId)
uid = UserIdSchema.parse(data)
reveal_type(uid, expected_text="UserId")
reveal_type(z.array(UserIdSchema).parse(data), expected_text="list[UserId]")
reveal_type(z.string().brand("Label").parse(data), expected_text="str")


def load_user(user_id: UserId) -> None: ...


load_user(uid)
load_user("plain")  # pyright: ignore[reportArgumentType]  # a plain str is not a UserId
load_user(OrderId("x"))  # pyright: ignore[reportArgumentType]  # nor is another brand

# function-style schemas
reveal_type(z.string().parse(data), expected_text="str")
reveal_type(z.int().optional().parse(data), expected_text="int | None")
reveal_type(z.array(z.number()).parse(data), expected_text="list[float]")
reveal_type(z.array(Item).parse(data), expected_text="list[Item]")
reveal_type(z.enum(("a", "b")).parse(data), expected_text="Literal['a', 'b']")
reveal_type(z.tuple((z.string(), Item)).parse(data), expected_text="tuple[str, Item]")
reveal_type(z.map(z.string(), Item).parse(data), expected_text="dict[str, Item]")
tags = z.array(z.string()).safeParse(data)
if tags.success:
    reveal_type(tags.data, expected_text="list[str]")

# mistakes the checker must keep reporting
order.items[0].quantity.upper()  # pyright: ignore[reportAttributeAccessIssue]
order.customer.phone.lower()  # pyright: ignore[reportOptionalMemberAccess]
wrong: str = order.paid  # pyright: ignore[reportAssignmentType]
order.customer.name = 1  # pyright: ignore[reportAttributeAccessIssue]
