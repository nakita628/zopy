# zopy

**[Zod](https://zod.dev) for Python** — the Zod 4 API, typed for Pylance / pyright, validated by a
Rust engine.

```python
from zopy import z


class User(z.Object):
    name = z.string().min(1)
    email = z.email()
    age = z.int().nonnegative().optional()


user = User.parse({"name": "Ada", "email": "ada@example.com"})  # => User
user.name  # => "Ada"  (str)
user.age  # => None   (int | None)
```

Schemas, checks and helpers keep Zod's names and behaviour (`z.string().min(1)`, `safeParse`,
`refine`, `transform`, `pipe`, `codec`, `discriminatedUnion`, `prettifyError`, `toJSONSchema`, …),
so the **[Zod documentation](https://zod.dev/api) is the API reference**. This README covers what
is specific to zopy: how Zod maps onto Python.

## Contents

- [Installation](#installation)
- [Quick start](#quick-start)
- [Differences from Zod](#differences-from-zod)
- [Schemas](#schemas)
  - [Primitives](#primitives) · [Coercion](#coercion) · [Literals](#literals)
  - [Strings](#strings) · [String formats](#string-formats) · [Template literals](#template-literals)
  - [Numbers](#numbers) · [Integers](#integers) · [BigInts](#bigints)
  - [Booleans](#booleans) · [Stringbool](#stringbool) · [Dates](#dates)
  - [Enums](#enums) · [Optionals and nullables](#optionals-and-nullables)
- [Objects are classes](#objects-are-classes)
- [Type inference](#type-inference)
- [Python types](#python-types)
- [Missing keys and None](#missing-keys-and-none)
- [Readonly](#readonly)
- [Brands](#brands)
- [Refinements](#refinements)
- [Errors](#errors)
  - [Customizing errors](#customizing-errors)
- [Async](#async)
- [Engines](#engines)
- [Development](#development)

## Installation

zopy requires **Python 3.11+**. It is not published to PyPI yet; install it from the repository
(building the Rust engine needs a [Rust toolchain](https://rustup.rs)):

```bash
uv add "zopy @ git+https://github.com/nakita628/zopy#subdirectory=packages/zopy"
# or
pip install "zopy @ git+https://github.com/nakita628/zopy#subdirectory=packages/zopy"
```

Everything is reached through `z`:

```python
from zopy import z  # or: import zopy as z
```

## Quick start

```python
class Player(z.Object):
    username = z.string()
    xp = z.number()


player = Player.parse({"username": "billie", "xp": 100})  # => Player
player.username  # => "billie"

result = Player.safeParse({"username": 42, "xp": "100"})
if not result.success:
    print(z.prettifyError(result.error))
    # ✖ Invalid input: expected string, received number
    #   → at username
    # ✖ Invalid input: expected number, received string
    #   → at xp
```

`.parse()` returns the parsed value or raises `z.ZodError`; `.safeParse()` returns
`SafeParseSuccess[Player] | SafeParseError`, and checking `result.success` narrows it.

## Differences from Zod

| Zod (TypeScript) | zopy (Python) |
|---|---|
| `z.object({ name: z.string() })` | `class X(z.Object): name = z.string()` |
| `z.strictObject({...})` / `z.looseObject({...})` | `class X(z.StrictObject)` / `class X(z.LooseObject)` |
| `A.extend({...})` / `A.merge(B)` | a subclass: `class C(A): ...` |
| `A.pick` / `omit` / `partial` / `required` | declare the shape you need as its own class |
| `z.intersection(A, B)` / `A.and(B)` | multiple inheritance: `class C(A, B): ...` |
| `z.infer<typeof X>` | the class `X`, or the return type of `parse()` |
| `z.enum(["a", "b"])` | `z.enum(("a", "b"))` — a tuple |
| `z.tuple([a, b])` | `z.tuple((a, b))` — a tuple |
| `undefined` | `None` (and a missing key) |
| `.or(b)` | `.or_(b)` or `a \| b` |
| `.brand<"UserId">()` | `.brand(UserId)` with `UserId = NewType("UserId", str)` |

Only APIs whose output type pyright can infer are provided. That is why object schemas are classes,
and why the shape-deriving helpers (`pick`, `omit`, `partial`, `extend`, `merge`, intersections)
and list-form `z.enum([...])` / `z.tuple([...])` are not: their results could only be typed as
`Any`. Most camelCase names also have a snake_case alias (`safe_parse`, `to_json_schema`, …).

zopy implements Zod 4 only. Zod 3 syntax — the `message`, `required_error`,
`invalid_type_error` and `errorMap` params, `.strict()` / `.passthrough()`, `z.string().email()`
and the other format methods, `z.nativeEnum`, `error.format()` / `.flatten()` … — is not
provided.

## Schemas

The primitive schemas and their checks. Objects are covered in [Objects are classes](#objects-are-classes).

### Primitives

```python
z.string()  # str
z.number()  # float (ints are accepted; bool is not)
z.int()  # int
z.bigint()  # int (no safe-integer bound)
z.boolean()  # bool
z.date()  # datetime / date
z.symbol()

# None-like
z.null()  # None
z.undefined()  # None
z.void()  # None

# catch-all
z.any()
z.unknown()

# accepts nothing
z.never()
z.nan()  # float("nan")
```

### Coercion

`z.coerce` converts the input before validating it:

```python
z.coerce.string().parse(42)  # => "42"
z.coerce.number().parse("4.5e2")  # => 450.0
z.coerce.boolean().parse("false")  # => True   (truthiness, like JavaScript's Boolean())
z.coerce.bigint().parse("99")  # => 99
z.coerce.date().parse("2024-01-01T00:00:00Z")  # => datetime(2024, 1, 1, tzinfo=utc)
z.coerce.date().parse(1_704_067_200_000)  # => datetime(2024, 1, 1, tzinfo=utc)  (epoch ms)
```

### Literals

```python
tuna = z.literal("tuna")  # Literal["tuna"]
twelve = z.literal(12)
yes = z.literal(True)

colors = z.literal(["red", "green", "blue"])  # any of several literals
colors.parse("green")  # => "green"
```

### Strings

```python
z.string().max(5)
z.string().min(5)
z.string().length(5)
z.string().nonempty()
z.string().regex(r"^[a-z]+$")
z.string().startsWith("aaa")
z.string().endsWith("zzz")
z.string().includes("---")
z.string().uppercase()
z.string().lowercase()
```

String transforms run as part of parsing:

```python
z.string().trim().parse("  hello  ")  # => "hello"
z.string().toLowerCase().parse("HeLLo")  # => "hello"
z.string().toUpperCase().parse("hello")  # => "HELLO"
z.string().normalize().parse("ｈｅｌｌｏ")  # NFC by default; .normalize("NFKC") etc.
```

### String formats

Formats are top-level functions, as in Zod 4.

```python
z.email()
z.uuid()
z.uuidv4()
z.uuidv7()
z.url()
z.httpUrl()  # http / https only
z.hostname()
z.emoji()
z.base64()
z.base64url()
z.hex()
z.jwt()
z.nanoid()
z.cuid()
z.cuid2()
z.ulid()
z.ipv4()
z.ipv6()
z.mac()
z.cidrv4()
z.cidrv6()
z.hash("sha256")  # or "sha1", "sha384", "sha512", "md5"
z.e164()  # phone numbers
z.creditCard()  # Luhn check
z.iban()
z.currencyCode()  # ISO 4217
z.iso.date()
z.iso.time()
z.iso.datetime()
z.iso.duration()
```

Formats take options:

```python
z.email({"pattern": z.regexes.html5Email})  # the regex browsers use
z.url({"protocol": r"^https$", "hostname": r"^example\.com$"})
z.iso.datetime({"offset": True})  # allow +09:00 offsets (default: Z only)
z.iso.datetime({"precision": 3})  # exactly millisecond precision
z.mac({"delimiter": "-"})
z.jwt({"alg": "HS256"})
z.hash("sha256", {"enc": "base64url"})
```

Define your own format with a regex or a predicate:

```python
ticket = z.stringFormat("ticket", r"^[A-Z]+-\d+$")
cool = z.stringFormat("cool-id", lambda value: value.startswith("cool-"))

ticket.parse("ABC-123")  # => "ABC-123"
cool.safeParse("nope").error.issues[0]["message"]  # => "Invalid cool-id"
```

### Template literals

```python
css = z.templateLiteral([z.number(), z.enum(("px", "em", "rem"))])
css.parse("1.5rem")  # => "1.5rem"
css.safeParse("1.5pt").success  # => False
```

### Numbers

`z.number()` accepts any finite `int` or `float` (not `bool`, not NaN / infinity).

```python
z.number().gt(5)
z.number().gte(5)  # alias: .min(5)
z.number().lt(5)
z.number().lte(5)  # alias: .max(5)
z.number().positive()
z.number().nonnegative()
z.number().negative()
z.number().nonpositive()
z.number().multipleOf(5)  # alias: .step(5)
```

### Integers

```python
z.int()  # a safe integer; 5.0 is accepted and returned as 5
z.int32()
z.uint32()

z.int().parse(5.0)  # => 5
z.int().safeParse(5.5).success  # => False
```

### BigInts

Python has one `int` type; `z.bigint()` is an `int` without the safe-integer bounds of `z.int()`:

```python
z.bigint().parse(2**80)  # => 1208925819614629174706176
z.int64()
z.uint64()
```

### Booleans

```python
z.boolean().parse(True)  # => True
z.boolean().safeParse(1).success  # => False
```

### Stringbool

`z.stringbool()` parses environment-variable-style strings into `bool`:

```python
flag = z.stringbool()
flag.parse("yes")  # => True
flag.parse("OFF")  # => False   (case-insensitive by default)

z.stringbool({"truthy": ["はい"], "falsy": ["いいえ"]}).parse("はい")  # => True
```

### Dates

`z.date()` accepts `datetime` and `date` objects:

```python
from datetime import datetime, timezone

z.date().min(datetime(1900, 1, 1, tzinfo=timezone.utc))
z.date().max(datetime(2100, 1, 1, tzinfo=timezone.utc))
```

For ISO 8601 *strings*, use `z.iso.date()`, `z.iso.datetime()` … (see [String formats](#string-formats)).

### Enums

Pass a **tuple** of strings — a tuple (unlike a list) keeps the literal types:

```python
Fish = z.enum(("Salmon", "Tuna", "Trout"))
Fish.parse("Salmon")  # => "Salmon"  (Literal["Salmon", "Tuna", "Trout"])
Fish.safeParse("Swordfish").success  # => False

Fish.enum.Salmon  # => "Salmon"
Fish.options  # => ["Salmon", "Tuna", "Trout"]

Fish.extract(("Salmon", "Trout")).options  # => ["Salmon", "Trout"]
Fish.exclude(("Salmon",)).options  # => ["Tuna", "Trout"]
```

Python `Enum` classes work too; members and their values are accepted and a member is returned:

```python
from enum import Enum


class Color(Enum):
    RED = "red"
    GREEN = "green"


z.enum(Color).parse("red")  # => Color.RED
z.enum(Color).parse(Color.GREEN)  # => Color.GREEN
```

### Optionals and nullables

```python
z.string().optional()  # str | None — the key may be missing (or None)
z.string().nullable()  # str | None — None is allowed, but the key must be present
z.string().nullish()  # both
z.string().exactOptional()  # the key may be missing, but an explicit None is rejected

z.string().optional().unwrap()  # => the inner z.string()
z.string().optional().nonoptional()  # rejects None again
```

## Objects are classes

An object schema is a class deriving from `z.Object`. The class is the schema, and its instances
are the parsed values, so the class is also the type:

```python
class Dog(z.Object):
    name = z.string()
    age = z.int().nonnegative()
    tags = z.array(z.string()).default(list)
    nickname = z.string().optional()


dog = Dog.parse({"name": "Rex", "age": 3})  # => Dog(name='Rex', age=3, tags=[])
```

Fields are **assigned**, not annotated: `name: z.string()` raises `TypeError` when the class is
defined. Attributes starting with `_` and `ClassVar`s are ordinary class attributes.

### Instances

An instance is an attribute object that also reads like a mapping:

```python
dog.name  # => "Rex"
dog["name"]  # => "Rex"
dog.get("nickname", "-")  # => "-"
dog.to_dict()  # => {"name": "Rex", "age": 3, "tags": []}
dog == {"name": "Rex", "age": 3, "tags": []}  # => True
```

The constructor validates too:

```python
Dog(name="Fido", age=1)  # => Dog(name='Fido', age=1, tags=[])
try:
    Dog(name="Fido", age=-1)
except z.ZodError:
    pass  # age: Too small
```

### Nesting

A class is used as a field like any other schema, and `z.array(Dog)`, `z.union([Cat, Dog])`,
`Dog.optional()` … keep the class as the type:

```python
class Owner(z.Object):
    name = z.string()
    dog = Dog
    pets = z.array(Dog).default(list)


owner = Owner.parse({"name": "Ada", "dog": {"name": "Rex", "age": 3}})
owner.dog.name  # => "Rex"   (owner.dog is a Dog)
```

Refer to a class before it exists (recursion) with `z.lazy`:

```python
class Category(z.Object):
    name = z.string()
    subcategories = z.lazy(lambda: z.array(Category)).default(list)


Category.parse({"name": "root", "subcategories": [{"name": "leaf"}]}).subcategories[0].name
# => "leaf"
```

### Unknown keys

Unknown keys are stripped by default. Choose another policy with the base class or a class keyword:

```python
class Strict(z.StrictObject):  # unknown keys are an error
    a = z.string()


class Loose(z.LooseObject):  # unknown keys are kept
    a = z.string()


class Extras(z.Object, catchall=z.number()):  # unknown keys must be numbers
    a = z.string()


Strict.safeParse({"a": "x", "b": 1}).success  # => False
Loose.parse({"a": "x", "b": 1}).to_dict()  # => {"a": "x", "b": 1}
```

`class X(z.Object, strict=True)` / `loose=True` are the same. For a strict or loose variant of an
existing class, inherit from it: `class StrictDog(Dog, z.StrictObject): ...`.

### Deriving shapes

Where Zod derives a shape (`extend`, `pick`, `omit`, `partial`), declare it as a class and share
fields through inheritance, so every shape stays fully typed:

```python
class Animal(z.Object):  # the smaller shape is the base
    name = z.string()


class Cat(Animal):  # Animal.extend({ lives: ... })
    lives = z.int().min(0).max(9)


class CatPatch(z.Object):  # Cat.partial()
    name = z.string().optional()
    lives = z.int().min(0).max(9).optional()


isinstance(Cat.parse({"name": "Tom", "lives": 9}), Animal)  # => True
```

### Combining objects

The intersection of object schemas is multiple inheritance:

```python
class Person(z.Object):
    name = z.string()


class Employee(z.Object):
    role = z.string()


class EmployedPerson(Person, Employee):  # z.intersection(Person, Employee)
    pass
```

If two bases declare the same field differently, defining the subclass raises `TypeError` until the
subclass redeclares the field — no base's checks are silently dropped.

### Class-level helpers

Methods on the class keep the class as the type, and callbacks receive instances:

```python
class SignupForm(z.Object):
    password = z.string().min(8)
    confirm = z.string()


Signup = SignupForm.refine(
    lambda form: form.password == form.confirm,  # form: SignupForm
    {"error": "Passwords don't match", "path": ["confirm"]},
)

Dog.default({"name": "Rex", "age": 3})  # a dict default is parsed into a Dog
Dog.shape  # => {"name": ZodString(), "age": ZodInt(), "tags": ZodDefault(), "nickname": ZodOptional()}
Dog.keyof().options  # => ["name", "age", "tags", "nickname"]
```

## Type inference

There is no `z.infer` (Python has no `typeof`); the type lives on `parse()`, and for objects on the
class. Hover a value in VS Code to see it:

```python
z.string().trim().parse("  Ada  ")  # => "Ada"           str
z.int().optional().parse(None)  # => None            int | None
z.enum(("admin", "user")).parse("admin")  # => "admin"         Literal["admin", "user"]
z.tuple((z.string(), Dog)).parse(["x", {"name": "Rex", "age": 3}])  # tuple[str, Dog]
z.union([z.string(), z.int()]).parse(1)  # => 1               int | str
z.record(z.string(), Dog).parse({})  # => {}              dict[str, Dog]
z.string().transform(len).parse("hello")  # => 5               int
```

Lambdas get their parameter types from the schema (`transform(lambda s: ...)` knows `s: str`), and
the code that uses parsed values is type-checked as usual.

Pass **tuples** to `z.enum` and `z.tuple`: a tuple keeps each literal / position type, a list
would not (and is rejected).

## Python types

| Zod | zopy schema | Python value |
|---|---|---|
| `string` | `z.string()` | `str` |
| `number` | `z.number()` | `float` (an `int` is accepted; `bool` is not) |
| `int` | `z.int()` | `int` (a safe integer; `5.0` is returned as `5`) |
| `bigint` | `z.bigint()` | `int` (no safe-integer bound) |
| `boolean` | `z.boolean()` | `bool` |
| `Date` | `z.date()` | `datetime` / `date` |
| `null` / `undefined` | `z.null()` / `z.undefined()` | `None` |
| `T[]` | `z.array(t)` | `list` (a `tuple` input is accepted) |
| `[A, B]` | `z.tuple((a, b))` | `tuple` |
| `Record<K, V>` | `z.record(k, v)` | `dict` |
| `Map<K, V>` | `z.map(k, v)` | `dict` (keys of any type) |
| `Set<T>` | `z.set(t)` | `set` |
| `File` | `z.file()` | `bytes` |
| TS `enum` | `z.enum(MyEnum)` | the `Enum` member (values are accepted as input) |
| branded type | `.brand(MyNewType)` | the `typing.NewType` |

```python
from enum import Enum
from typing import NewType


class Color(Enum):
    RED = "red"


UserId = NewType("UserId", str)

z.enum(Color).parse("red")  # => Color.RED
z.uuid().brand(UserId).parse("123e4567-e89b-12d3-a456-426614174000")  # UserId
```

## Missing keys and None

`None` plays the part of `undefined`. An optional field that was not given stays absent from the
instance, but reading it as an attribute gives `None`:

```python
dog = Dog.parse({"name": "Rex", "age": 3})
"nickname" in dog  # => False
dog.nickname  # => None
dog.to_dict()  # => {"name": "Rex", "age": 3, "tags": []}

dog = Dog.parse({"name": "Rex", "age": 3, "nickname": None})
"nickname" in dog  # => True
```

`.exactOptional()` accepts a missing key but rejects an explicit `None`.

## Readonly

`.readonly()` freezes the parsed value shallowly (like Zod's `Object.freeze`), and the output type
is the frozen type:

| schema | value | type |
|---|---|---|
| `z.array(t).readonly()` | `tuple` | `tuple[T, ...]` |
| `z.record(k, v).readonly()` / `z.map(k, v).readonly()` | `mappingproxy` | `Mapping[K, V]` |
| `z.set(t).readonly()` | `frozenset` | `frozenset[T]` |
| `z.tuple(...).readonly()` | `tuple` | the same `tuple[...]` |
| `MyObject.readonly()` | a frozen instance | `MyObject` |

```python
tags = z.array(z.string()).readonly().parse(["a"])  # => ("a",)   tuple[str, ...]
# tags.append("b") is a type error, as it would be in TypeScript

frozen = Dog.readonly().parse({"name": "Rex", "age": 3})
try:
    frozen.name = "Max"
except AttributeError:
    pass  # Dog is readonly: cannot change 'name'
```

A frozen instance rejects attribute assignment and deletion at runtime. Python's type system has no
`Readonly<T>` for classes, so pyright does not flag `frozen.name = ...` statically.

## Brands

Zod's `.brand<"UserId">()` makes a nominal type: structurally a `string`, but not assignable from
a plain `string` or from another brand. Python's equivalent is `typing.NewType`, so `.brand()`
takes one:

```python
from typing import NewType

UserId = NewType("UserId", str)
OrderId = NewType("OrderId", str)

UserIdSchema: z.ZodType[UserId] = z.uuid().brand(UserId)

uid = UserIdSchema.parse("123e4567-e89b-12d3-a456-426614174000")  # UserId
z.array(UserIdSchema).parse([])  # list[UserId]


def load_user(user_id: UserId) -> None: ...


load_user(uid)  # OK
load_user("123e4567-e89b-12d3-a456-426614174000")  # type error: a plain str is not a UserId
load_user(OrderId("x"))  # type error: nor is another brand
```

Annotate the schema variable (`z.ZodType[UserId]`): type checkers cannot infer the branded type
from a `NewType` argument, so the annotation is what gives `.parse()` its output type. Without it
the schema is a `ZodType[Any]`.

As in Zod, a brand is **static only**. The parsed value is unchanged (`type(uid) is str`), and
validation, errors and `toJSONSchema` are those of the schema being branded. Brand after the
checks, which keep running as before:

```python
Age = NewType("Age", int)
AgeSchema: z.ZodType[Age] = z.int().nonnegative().brand(Age)
```

The `NewType` must fit what the schema outputs. An obvious mismatch is caught when the schema is
built:

```python
try:
    z.int().brand(UserId)
except TypeError:
    pass  # brand(UserId): UserId is a NewType of str, but this number schema outputs int | float
```

`.brand("UserId")` with a string label is also accepted, for code ported from Zod. It is a no-op
for typing: the schema keeps its own type (`z.string().brand("UserId")` parses to `str`). Anything
other than a label or a `NewType` (a class such as `str`, for instance) raises `TypeError`.

## Refinements

`.refine(check, options)` adds a custom check: return a truthy value to accept the input. The
options are Zod 4's:

| option | |
|---|---|
| `"error"` | the message, or a function of the issue (see [Customizing errors](#customizing-errors)) |
| `"path"` | where the issue points, e.g. `["confirm"]` |
| `"abort"` | `True`: stop at this check when it fails (by default later checks still run) |
| `"when"` | `when(payload)` decides whether the check runs (see below) |

```python
Password = (
    z.string()
    .min(8)
    .refine(
        lambda s: any(c.isdigit() for c in s),
        {"error": "Must contain a digit"},
    )
)
Password.safeParse("password").error.issues[0]["message"]  # => "Must contain a digit"

Even = z.int().refine(lambda n: n % 2 == 0, {"error": lambda issue: f"{issue['input']} is odd"})
Even.safeParse(3).error.issues[0]["message"]  # => "3 is odd"
```

On a class, the check receives the instance:

```python
class PasswordForm(z.Object):
    password = z.string().min(8)
    confirm = z.string()


Passwords = PasswordForm.refine(
    lambda form: form.password == form.confirm,  # form: PasswordForm
    {"error": "Passwords don't match", "path": ["confirm"]},
)
Passwords.safeParse({"password": "secret123", "confirm": "nope"}).error.issues[0]["path"]
# => ["confirm"]
```

All failing refinements are reported; `"abort": True` stops at the first:

```python
Both = z.string().refine(lambda s: False, {"error": "a"}).refine(lambda s: False, {"error": "b"})
[issue["message"] for issue in Both.safeParse("x").error.issues]  # => ["a", "b"]

First = (
    z.string().refine(lambda s: False, {"error": "a", "abort": True}).refine(lambda s: False, {"error": "b"})
)
[issue["message"] for issue in First.safeParse("x").error.issues]  # => ["a"]
```

#### when

A refinement does not run once the value already has an aborting issue — for an object, for
example, a missing field. `"when"` replaces that rule: it receives the payload (`payload.value`,
`payload.issues`) and returns whether to run. The object has not been built into an instance at
that point, so read the fields with `["..."]`, which works on both:

```python
class SignupForm(z.Object):
    password = z.string().min(8)
    confirm = z.string()
    nickname = z.string()


def passwords_given(payload):
    value = payload.value
    return isinstance(value.get("password"), str) and isinstance(value.get("confirm"), str)


Signup = SignupForm.refine(
    lambda form: form["password"] == form["confirm"],
    {"error": "Passwords don't match", "path": ["confirm"], "when": passwords_given},
)
result = Signup.safeParse({"password": "secret123", "confirm": "nope"})  # nickname is missing
[issue["path"] for issue in result.error.issues]  # => [["nickname"], ["confirm"]]
```

### superRefine

`.superRefine(fn, options)` adds any number of issues through `ctx.addIssue`. An issue is a dict
with a `code` (usually `"custom"`), its `message`, and optionally a `path` relative to the value:

```python
def unique(items, ctx):
    if len(items) != len(set(items)):
        ctx.addIssue({"code": "custom", "message": "No duplicates allowed"})
    if len(items) > 3:
        ctx.addIssue(
            {
                "code": "too_big",
                "maximum": 3,
                "origin": "array",
                "inclusive": True,
                "message": "Too many items",
            }
        )


Tags = z.array(z.string()).superRefine(unique)
[issue["message"] for issue in Tags.safeParse(["a", "a", "b", "c"]).error.issues]
# => ["No duplicates allowed", "Too many items"]
```

An issue with `"continue": False` aborts the remaining checks. `superRefine` takes the same
`"error"`, `"abort"` and `"when"` options as `refine`.

### check

`.check(fn)` is the low-level form: `fn(ctx)` reads `ctx.value` and pushes issues onto
`ctx.issues`. Built-in checks such as `z.gt(0)` can be passed too:

```python
def positive(ctx):
    if ctx.value <= 0:
        ctx.issues.push({"code": "custom", "message": "Must be positive", "input": ctx.value})


z.int().check(positive).safeParse(-1).error.issues[0]["message"]  # => "Must be positive"
z.number().check(z.gt(0), z.lt(10)).safeParse(42).success  # => False
```

Async checks (coroutine functions) need `parseAsync` / `safeParseAsync` — see [Async](#async).

## Errors

A failed `parse()` raises `z.ZodError`; its `issues` are dicts that also allow attribute access.
Messages are built only when the issues are read, so a failure you don't inspect is cheap:

```python
try:
    Player.parse({"username": 1, "xp": 0})
except z.ZodError as error:
    issue = error.issues[0]
    issue["path"]  # => ["username"]
    issue.message  # => "Invalid input: expected string, received number"
```

Issues leave out the input unless you pass `{"reportInput": True}` to the parse.

### Customizing errors

Every schema and every check takes `{"error": ...}`:

```python
z.string({"error": "Not a string!"}).safeParse(1).error.issues[0]["message"]  # => "Not a string!"
z.string().min(5, {"error": "Too short!"}).safeParse("ab").error.issues[0]["message"]  # => "Too short!"
```

Set them per field to build form-friendly messages:

```python
class SignupFields(z.Object):
    email = z.email({"error": "Enter a valid email address"})
    age = z.int({"error": "Age must be a whole number"}).min(18, {"error": "You must be 18 or older"})


result = SignupFields.safeParse({"email": "nope", "age": 16})
[(issue["path"], issue["message"]) for issue in result.error.issues]
# => [(["email"], "Enter a valid email address"), (["age"], "You must be 18 or older")]
```

#### Error functions

`error` can be a function of the issue. It receives the issue dict — `code`, `input`, `path` and
the code-specific fields such as `minimum` or `expected` — and returns the message:

```python
MinFive = z.string().min(
    5,
    {"error": lambda issue: f"Need {issue['minimum']} characters, got {len(issue['input'])}"},
)
MinFive.safeParse("ab").error.issues[0]["message"]  # => "Need 5 characters, got 2"
```

Tell a missing value from a wrong type with `issue["input"]`:

```python
RequiredString = z.string({"error": lambda issue: "Required" if issue["input"] is None else "Not a string"})
RequiredString.safeParse(None).error.issues[0]["message"]  # => "Required"
RequiredString.safeParse(1).error.issues[0]["message"]  # => "Not a string"
```

Return `None` to fall back to the next error in the [precedence](#precedence) order (for an error
function on a schema, that is the default message):

```python
OnlyTooSmall = z.int({"error": lambda issue: "Too small!" if issue["code"] == "too_small" else None})
OnlyTooSmall.min(3).safeParse(1).error.issues[0]["message"]  # => "Too small!"
```

#### Per parse

Pass `{"error": ...}` to a single `parse` / `safeParse` call:

```python
class Counter(z.Object):
    n = z.int()


Counter.safeParse({"n": "x"}, {"error": lambda issue: f"bad {issue['code']}"}).error.issues[0]["message"]
# => "bad invalid_type"
```

#### Globally

`z.config({"customError": ...})` sets an error function for every schema — for example to
translate messages. Return `None` for the issues you leave to the default messages:

```python
def japanese(issue):
    if issue["code"] == "invalid_type":
        return f"{issue['expected']} を入力してください"
    return None  # other codes: the default message


z.config({"customError": japanese})
z.int().safeParse("x").error.issues[0]["message"]  # => "number を入力してください"
z.int().min(3).safeParse(1).error.issues[0]["message"]  # => "Too small: expected number to be >=3"
z.config({"customError": None})  # back to the default messages
```

#### Precedence

The first error that gives a message wins:

1. the `error` of the check (`.min(5, {"error": ...})`)
2. the `error` of the schema (`z.string({"error": ...})`)
3. the per-parse `error` (`.safeParse(data, {"error": ...})`)
4. `z.config({"customError": ...})`
5. `z.config({"localeError": ...})` — the default English messages

```python
SchemaError = z.int({"error": "schema wins"})
SchemaError.safeParse("x", {"error": lambda issue: "per-parse"}).error.issues[0]["message"]
# => "schema wins"
```

## Async

Async refinements and transforms take coroutine functions and need the async methods
(`parseAsync`, `safeParseAsync`), which work with `asyncio`:

```python
import asyncio


async def available(name: str) -> bool:
    await asyncio.sleep(0)  # e.g. a database lookup
    return name != "root"


Username = z.string().min(3).refine(available, {"error": "Username is taken"})
asyncio.run(Username.parseAsync("ada"))  # => "ada"
```

`.parse()` on a schema with async parts raises `z.ZodAsyncError`.

## Engines

A schema is compiled on first use and validated by the Rust engine (`zopy._core`, built with
PyO3). Parts it does not run itself — Python callbacks such as `refine` / `transform`, async
schemas — are handed to the pure-Python engine, with identical results.

To run everything on the pure-Python engine (for debugging, or without the extension), set
`ZOD_ENGINE=python`, or call `zopy._compile.set_engine("python")` at runtime.

## Development

The repository is a uv + Cargo workspace:

```
.
├── packages/zopy/     # the library (maturin: Rust in src/, Python in python/zopy/, tests/)
└── apps/examples/      # runnable demos (`just examples`)
```

Requires [uv](https://docs.astral.sh/uv/) and a Rust toolchain.

```bash
uv sync         # install everything (builds the Rust extension; also installs `just`)
just            # list the tasks
just check      # lint + typecheck + test (what CI runs)
just fmt        # format Python and Rust
just build      # rebuild the extension after changing Rust code
just examples   # run the demos
```

The code blocks in this README are executed by the test suite, so the examples stay accurate.

## License

[MIT](LICENSE)
# zopy
