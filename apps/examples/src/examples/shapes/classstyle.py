"""Zod's examples with ``class X(z.Object)`` schemas: typed fields, no code generation.

``uv run examples classstyle``. Each block shows the TypeScript from zod.dev, then the Python.
Objects are declared as classes: each field is a class attribute (``name = z.string()``), and the
class is both the schema and the parsed type. Every other ``z.`` call and method chain reads as in
Zod. The ``# =>`` comments are the types Pylance shows.
"""

from __future__ import annotations

from typing import Any

from zopy import z

from ..show import section

# const Player = z.object({ username: z.string(), xp: z.number() });


class Player(z.Object):
    username = z.string()
    xp = z.number()


# const Owner = z.object({ id: z.uuid(), email: z.email() });
# const Dog = z.object({
#   name: z.string(),
#   age: z.number().optional(),
#   tags: z.array(z.string()),
#   kind: z.enum(["dog", "wolf"]),
#   owner: Owner,
# });


class Owner(z.Object):
    id = z.uuid()
    email = z.email()


class Dog(z.Object):
    name = z.string()
    age = z.number().optional()
    tags = z.array(z.string())
    kind = z.enum(("dog", "wolf"))  # a tuple keeps the literals: Literal['dog', 'wolf']
    owner = Owner


# const Cat = z.object({ type: z.literal("cat"), lives: z.int() });
# const Bird = z.object({ type: z.literal("bird"), canFly: z.boolean() });
# const Pet = z.discriminatedUnion("type", [Cat, Bird]);


class Cat(z.Object):
    type = z.literal("cat")
    lives = z.int().min(0).max(9)


class Bird(z.Object):
    type = z.literal("bird")
    canFly = z.boolean()


Pet = z.discriminatedUnion("type", [Cat, Bird])  # => output Cat | Bird


# const Signup = z.strictObject({ email: z.email() })  ->  class Signup(z.StrictObject)
# const Extra = z.looseObject({ id: z.int() })        ->  class Extra(z.LooseObject)
class Signup(z.StrictObject):
    email = z.email()


# const Admin = User.extend({ level: z.int() })  ->  a subclass keeps every field typed
class User(z.Object):
    name = z.string().trim().min(1)
    age = z.int().positive()


class Admin(User):
    level = z.int().min(1)


def run() -> None:
    basic_usage()
    error_handling()
    nested_and_collections()
    unions_and_inheritance()
    refinements_and_transforms()


def basic_usage() -> None:
    section("Class-style: parse / safeParse")
    # Player.parse({ username: "billie", xp: 100 });
    player = Player.parse({"username": "billie", "xp": 100})  # => Player
    print(f"  player.username = {player.username!r}  player.xp + 1 = {player.xp + 1}")  # str / float

    # const result = Player.safeParse({ username: 42, xp: "100" });
    # if (!result.success) { result.error } else { result.data }
    result = Player.safeParse({"username": 42, "xp": "100"})  # => SafeParseSuccess[Player] | SafeParseError
    if not result.success:
        print("  safeParse error  =", [issue["message"] for issue in result.error.issues])  # ZodError
    else:
        print("  safeParse data   =", result.data.username)  # => str

    ok = Player.safeParse({"username": "billie", "xp": 100})
    if ok.success:
        print(f"  safeParse data   = {ok.data!r}")  # => Player

    # Instances also come from keyword arguments (validated) and convert back to dicts.
    built = Player(username="ada", xp=1)
    print(f"  Player(...)      = {built!r}  to_dict() = {built.to_dict()}")


def error_handling() -> None:
    section("Class-style: errors")
    try:
        User.parse({"name": " ", "age": -1})
    except z.ZodError as error:
        for issue in error.issues:
            print(f"  path={issue['path']!s:<9} code={issue['code']:<10} {issue['message']}")
    result = User.safeParse({"name": " ", "age": -1})
    if not result.success:
        print("  z.flattenError  =", z.flattenError(result.error))
    strict = Signup.safeParse({"email": "a@b.co", "admin": True})  # z.StrictObject: unknown keys fail
    if not strict.success:
        print("  StrictObject    =", strict.error.issues[0]["message"])


def nested_and_collections() -> None:
    section("Class-style: nested objects, arrays, records")
    dog = Dog.parse(
        {
            "name": "Rex",
            "tags": ["good"],
            "kind": "dog",
            "owner": {"id": "123e4567-e89b-12d3-a456-426614174000", "email": "a@b.co"},
        }
    )  # => Dog
    print(f"  dog.owner.email  = {dog.owner.email}")  # => str
    print(f"  dog.kind         = {dog.kind}")  # => Literal['dog', 'wolf']
    print(f"  dog.age          = {dog.age}")  # => float | None (omitted)
    dogs = z.array(Dog).min(1).safeParse([])  # => list[Dog] on success
    print(f"  z.array(Dog).min(1) on [] -> success={dogs.success}")
    by_name = z.record(z.string(), Player).parse({"a": {"username": "a", "xp": 1}})  # => dict[str, Player]
    print(f"  record           = {by_name['a'].username}")
    print(
        "  nested error paths =",
        _paths(Dog.safeParse({"name": "Rex", "tags": [1], "kind": "cat", "owner": {}})),
    )


def unions_and_inheritance() -> None:
    section("Class-style: discriminated unions, inheritance")
    pet = Pet.parse({"type": "cat", "lives": 7})  # => Cat | Bird
    if isinstance(pet, Cat):
        print(f"  Cat with {pet.lives} lives")  # pet: Cat
    else:
        print(f"  Bird canFly={pet.canFly}")  # pet: Bird
    print("  bad discriminator ->", _messages(Pet.safeParse({"type": "fish"})))

    admin = Admin.parse({"name": "  Ada ", "age": 36, "level": 3})  # => Admin
    print(f"  Admin: name={admin.name!r} age={admin.age} level={admin.level}")  # str / int / int
    print(f"  isinstance(admin, User) = {isinstance(admin, User)}")


def refinements_and_transforms() -> None:
    section("Class-style: refine, transform, default")

    # const Password = z.object({ password: z.string(), confirm: z.string() })
    #   .refine((data) => data.password === data.confirm, { message: "...", path: ["confirm"] });
    class PasswordForm(z.Object):
        password = z.string().min(8)
        confirm = z.string()

    Password = PasswordForm.refine(
        lambda form: form.password == form.confirm,  # form: PasswordForm
        {"error": "Passwords don't match", "path": ["confirm"]},
    )
    print("  refine   ->", _messages(Password.safeParse({"password": "12345678", "confirm": "x"})))

    # User.transform((u) => `${u.name} (${u.age})`)
    Label = User.transform(lambda u: f"{u.name} ({u.age})")  # u: User
    print("  transform ->", Label.parse({"name": "Ada", "age": 36}))  # => str

    class Settings(z.Object):
        theme = z.enum(("light", "dark")).default("light")
        pageSize = z.coerce.number().int().default(20)

    settings = Settings.parse({"pageSize": "50"})  # => Settings
    print(f"  defaults/coerce -> theme={settings.theme} pageSize={settings.pageSize}")


def _messages(result: Any) -> list[str] | str:
    return "ok" if result.success else [issue["message"] for issue in result.error.issues]


def _paths(result: Any) -> list[str] | str:
    return "ok" if result.success else [".".join(map(str, i["path"])) for i in result.error.issues]
