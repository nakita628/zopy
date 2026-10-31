"""class User(z.Object): class-declared object schemas."""

import pytest

from zopy import z


class User(z.Object):
    name = z.string().min(1)
    age = z.int().optional()
    tags = z.array(z.string()).default(list)


class Admin(User, strict=True):
    level = z.int()


class Post(z.Object):
    title = z.string()
    author = User
    reviewers = z.array(User).default(list)
    editor = User.optional()


def test_parse_returns_instances():
    u = User.parse({"name": "Ada", "extra": 1})
    assert isinstance(u, User)
    assert (u.name, u.age, u.tags) == ("Ada", None, [])
    assert u == {"name": "Ada", "tags": []}
    assert dict(u) == {"name": "Ada", "tags": []}
    assert "age" not in u
    assert u["name"] == "Ada"
    assert "name" in u
    assert len(u) == 2
    assert repr(u) == "User(name='Ada', tags=[])"
    assert u.get("name") == "Ada"
    assert u.get("age") is None
    assert u.get("age", 0) == 0
    assert list(u.keys()) == ["name", "tags"]
    r = User.safeParse({"name": ""})
    assert r.success is False
    assert r.error.issues[0].path == ["name"]
    assert User.safeParse({"name": "x"}).data == User(name="x")


def test_class_is_a_schema():
    assert isinstance(User, z.ZodType)
    assert list(User.shape) == ["name", "age", "tags"]
    assert User.name.type == "string"
    assert z.toJSONSchema(User)["required"] == ["name", "tags"]
    assert z.array(User).parse([{"name": "x"}]) == [User(name="x")]
    assert User.array().parse([{"name": "x"}])[0].name == "x"
    assert User.optional().parse(None) is None
    nullable = User.nullable().parse({"name": "x"})
    assert nullable is not None
    assert nullable.name == "x"

    class Holder(z.Object):
        owner = User

    assert Holder.parse({"owner": {"name": "x"}})["owner"].name == "x"
    assert "name" in User.keyof().options


def test_inheritance_and_options():
    a = Admin.parse({"name": "A", "level": 2})
    assert isinstance(a, User)
    assert a.level == 2
    assert a.tags == []
    assert Admin.safeParse({"name": "A", "level": 2, "x": 1}).error.issues[0].code == "unrecognized_keys"

    class Loose(User, loose=True):
        pass

    assert Loose.parse({"name": "a", "extra": 1}).to_dict() == {
        "name": "a",
        "tags": [],
        "extra": 1,
    }

    class Mapped(z.Object, catchall=z.int()):
        name = z.string()

    assert Mapped.safeParse({"name": "a", "x": "no"}).success is False


def test_nested_and_to_dict():
    p = Post.parse({"title": "t", "author": {"name": "Ada"}, "reviewers": [{"name": "r"}]})
    assert isinstance(p.author, User)
    assert p.author.name == "Ada"
    assert p.reviewers[0].name == "r"
    assert p.editor is None
    assert p.to_dict() == {
        "title": "t",
        "author": {"name": "Ada", "tags": []},
        "reviewers": [{"name": "r", "tags": []}],
    }
    assert (
        Post.parse({"title": "t", "author": User(name="x")}).author.name == "x"
    )  # instances accepted as input
    assert Post.safeParse({"title": "t", "author": {"name": ""}}).error.issues[0].path == ["author", "name"]


def test_derived_schemas_keep_instances():
    refined = User.refine(lambda u: u.name != "root", "no root")
    assert refined.safeParse({"name": "root"}).error.issues[0].message == "no root"
    assert isinstance(refined.parse({"name": "ok"}), User)
    assert User.parse({"name": "a"}).name == "a"  # original untouched


def test_multiple_inheritance_combines_fields():
    class Person(z.Object):
        name = z.string()

    class Employee(z.Object):
        company = z.string()

    class Staff(Person, Employee):
        pass

    assert set(Staff.shape) == {"name", "company"}
    assert Staff.parse({"name": "a", "company": "c"}) == {"name": "a", "company": "c"}
    assert Staff.safeParse({"name": "a"}).success is False


def test_conflicting_inherited_fields_must_be_redeclared():
    class Person(z.Object):
        name = z.string()

    class Employee(z.Object):
        name = z.string().min(2)

    with pytest.raises(TypeError, match=r"Staff\.name: declared differently by Employee and Person"):

        class Staff(Person, Employee):
            pass

    class Chosen(Person, Employee):
        name = z.string().min(2)

    assert Chosen.safeParse({"name": "A"}).success is False

    # Overriding along one inheritance line is not a conflict, even in a diamond.
    class Base(z.Object):
        name = z.string()

    class Plain(Base):
        pass

    class Longer(Base):
        name = z.string().min(3)

    class Both(Plain, Longer):
        pass

    assert Both.safeParse({"name": "ab"}).success is False


def test_readonly_freezes_instances():
    class Point(z.Object):
        x = z.int()

    p = Point.readonly().parse({"x": 1})
    assert isinstance(p, Point)
    assert p == {"x": 1}
    assert vars(p) == {"x": 1}
    for mutate in (lambda: setattr(p, "x", 2), lambda: delattr(p, "x"), lambda: setattr(p, "y", 0)):
        with pytest.raises(AttributeError, match="Point is readonly"):
            mutate()
    assert p.x == 1

    q = Point.parse({"x": 1})
    q.x = 2  # not readonly: still assignable
    assert q.x == 2


def test_constructor_and_assignment():
    u = User(name="Zed", age=3)
    assert u.age == 3
    with pytest.raises(z.ZodError):
        User(name=1)
    u.name = "Bob"
    assert u.name == "Bob"
    assert u["name"] == "Bob"
    assert User.name.parse("still a schema") == "still a schema"


def test_same_schema_reused_for_two_fields():
    Name = z.string()

    class Pair(z.Object):
        first = Name
        second = Name

    p = Pair.parse({"first": "a", "second": "b"})
    assert (p.first, p.second) == ("a", "b")


def test_class_default_and_catch_dicts_become_instances():
    class Profile(z.Object):
        links = z.array(z.string())

    class Account(z.Object):
        profile = Profile.default({"links": []})
        backup = Profile.catch(lambda ctx: {"links": ["x"]})
        lazy = Profile.default(lambda: {"links": ["y"]})

    account = Account.parse({"backup": 1})
    assert isinstance(account.profile, Profile)
    assert account.profile.links == []
    assert isinstance(account.backup, Profile)
    assert account.backup.links == ["x"]
    assert isinstance(account.lazy, Profile)
    assert account.lazy.links == ["y"]
    schema = z.toJSONSchema(Account)
    assert schema["properties"]["profile"]["default"] == {"links": []}


def test_strict_and_loose_object_classes():
    class Name(z.Object):
        name = z.string()

    class Strict(z.StrictObject):
        a = z.string()

    class StrictChild(Strict):
        b = z.int()

    class Loose(z.LooseObject):
        a = z.string()

    class StrictName(Name, z.StrictObject):
        pass

    assert Strict.safeParse({"a": "x", "extra": 1}).error.issues[0]["code"] == "unrecognized_keys"
    assert StrictChild.safeParse({"a": "x", "b": 1, "extra": 1}).success is False
    assert StrictChild.parse({"a": "x", "b": 1}).b == 1
    loose = Loose.parse({"a": "x", "extra": 1})
    assert loose.a == "x"
    assert loose["extra"] == 1
    assert StrictName.safeParse({"name": "n", "extra": 1}).success is False
    assert Name.safeParse({"name": "n", "extra": 1}).success is True
    assert isinstance(StrictName.parse({"name": "n"}), Name)


def test_annotated_fields_are_rejected():
    from typing import Annotated, ClassVar

    with pytest.raises(TypeError, match=r"write `id = z\.uuid\(\)`|with `=` instead of `:`"):

        class A(z.Object):
            id: z.uuid()  # type: ignore[valid-type]  # pyright: ignore[reportInvalidTypeForm]

    with pytest.raises(TypeError, match=r"z\.Object fields are assigned, not annotated"):

        class B(z.Object):
            id: Annotated[str, z.uuid()]

    with pytest.raises(TypeError, match="drop the annotation"):

        class C(z.Object):
            id: str = z.uuid()  # pyright: ignore[reportAssignmentType]

    class Ok(z.Object):
        VERSION: ClassVar[int] = 1
        _cache: dict = {}  # noqa: RUF012
        on = z.boolean()

    assert Ok.parse({"on": True}).on is True
    assert list(Ok.shape) == ["on"]


def test_class_union_operator_at_runtime():
    import typing

    class U(z.Object):
        a = z.int()

    assert isinstance(U | z.string(), z.ZodUnion)  # a schema union
    assert typing.get_args(U | None) == (U, type(None))  # a typing union, for annotations
