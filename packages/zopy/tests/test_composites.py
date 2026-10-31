import pytest

from zopy import z


def test_object_basic():
    class User(z.Object):
        name = z.string()
        age = z.number().optional()

    assert User.parse({"name": "a"}) == {"name": "a"}
    assert User.parse({"name": "a", "age": 1, "extra": True}) == {"name": "a", "age": 1}
    r = User.safeParse({"age": 1})
    assert r.error.issues[0].path == ["name"]
    assert r.error.issues[0].message == "Invalid input: expected string, received undefined"
    r = User.safeParse({"name": None})
    assert r.error.issues[0].message == "Invalid input: expected string, received undefined"
    assert User.safeParse("x").error.issues[0].message == "Invalid input: expected object, received string"
    assert set(User.shape) == {"name", "age"}
    assert User.keyof().options == ["name", "age"]
    assert User["name"].type == "string"


def test_object_strict_loose_catchall():
    class Base(z.Object):
        a = z.string()

    class Strict(z.StrictObject):
        a = z.string()

    class Loose(z.LooseObject):
        a = z.string()

    class StrictBase(Base, z.StrictObject):  # a strict variant of an existing class
        pass

    class LooseBase(Base, z.LooseObject):
        pass

    assert StrictBase.safeParse({"a": "x", "b": 1}).error.issues[0].message == 'Unrecognized key: "b"'
    assert (
        Strict.safeParse({"a": "x", "b": 1, "c": 2}).error.issues[0].message == 'Unrecognized keys: "b", "c"'
    )
    assert LooseBase.parse({"a": "x", "b": 1}) == {"a": "x", "b": 1}
    assert Loose.parse({"a": "x", "b": 1}) == {"a": "x", "b": 1}
    assert Base.parse({"a": "x", "b": 1}) == {"a": "x"}
    c = Base.catchall(z.number())
    assert c.parse({"a": "x", "b": 1}) == {"a": "x", "b": 1}
    assert c.safeParse({"a": "x", "b": "no"}).error.issues[0].path == ["b"]


def test_array_and_tuple():
    arr = z.array(z.string())
    assert arr.parse(["a", "b"]) == ["a", "b"]
    assert arr.parse(("a",)) == ["a"]  # arrays always come back as lists
    r = arr.safeParse(["a", 1])
    assert r.error.issues[0].path == [1]
    assert arr.safeParse("a").error.issues[0].message == "Invalid input: expected array, received string"
    assert arr.min(1).safeParse([]).error.issues[0].message == "Too small: expected array to have >=1 items"
    assert (
        arr.max(1).safeParse(["a", "b"]).error.issues[0].message
        == "Too big: expected array to have <=1 items"
    )
    assert arr.nonempty().parse(["x"]) == ["x"]
    assert arr.length(2).safeParse(["x"]).success is False
    assert z.string().array().parse(["a"]) == ["a"]
    assert arr.element.type == "string"

    tup = z.tuple((z.string(), z.number()))
    assert tup.parse(["a", 1]) == ("a", 1)  # tuples always come back as tuples
    assert tup.parse(("a", 1)) == ("a", 1)
    assert tup.safeParse(["a"]).success is False
    assert tup.safeParse(["a", 1, 2]).error.issues[0].code == "too_big"
    rest = z.tuple((z.string(),)).rest(z.number())
    assert rest.parse(["a", 1, 2, 3]) == ("a", 1, 2, 3)
    assert rest.safeParse(["a", "b"]).error.issues[0].path == [1]
    opt = z.tuple((z.string(), z.number().optional()))
    assert opt.parse(["a"]) == ("a",)


def test_record_map_set():
    rec = z.record(z.string(), z.number())
    assert rec.parse({"a": 1}) == {"a": 1}
    r = rec.safeParse({"a": "x"})
    assert r.error.issues[0].path == ["a"]
    r = rec.safeParse({1: 1})
    assert r.error.issues[0].code == "invalid_key"
    exhaustive = z.record(z.enum(("a", "b")), z.number())
    assert exhaustive.parse({"a": 1, "b": 2}) == {"a": 1, "b": 2}
    assert exhaustive.safeParse({"a": 1}).success is False
    assert z.partialRecord(z.enum(("a", "b")), z.number()).parse({"a": 1}) == {"a": 1}

    m = z.map(z.string(), z.number())
    assert m.parse({"a": 1}) == {"a": 1}
    assert m.safeParse({1: 1}).error.issues[0].code == "invalid_key"
    assert m.safeParse({"a": "b"}).error.issues[0].path == ["a"]

    st = z.set(z.number())
    assert st.parse({1, 2}) == {1, 2}
    assert st.safeParse({1, "a"}).error.issues[0].code == "invalid_element"
    assert st.min(3).safeParse({1}).error.issues[0].message == "Too small: expected set to have >=3 items"
    assert st.safeParse([1]).success is False


def test_union():
    u = z.union([z.string(), z.number()])
    assert u.parse("a") == "a"
    assert u.parse(1) == 1
    r = u.safeParse(True)
    assert r.error.issues[0].code == "invalid_union"
    assert r.error.issues[0].message == "Invalid input"
    assert len(r.error.issues[0]["errors"]) == 2
    assert z.string().or_(z.number()).parse(1) == 1
    assert (z.string() | z.number()).parse("x") == "x"
    assert getattr(z.string(), "or")(z.number()).parse(2) == 2
    # dirty-but-not-aborted single option propagates its issues
    u2 = z.union([z.string().min(3), z.number()])
    r = u2.safeParse("ab")
    assert r.error.issues[0].code == "too_small"


def test_discriminated_union():
    class Success(z.Object):
        status = z.literal("success")
        data = z.string()

    class Failed(z.Object):
        status = z.literal("failed")
        error = z.string()

    class NoTag(z.Object):
        x = z.string()

    Result = z.discriminatedUnion("status", [Success, Failed])
    assert Result.parse({"status": "success", "data": "x"}) == {"status": "success", "data": "x"}
    r = Result.safeParse({"status": "nope"})
    assert r.error.issues[0].code == "invalid_union"
    assert r.error.issues[0].path == ["status"]
    r = Result.safeParse({"status": "failed"})
    assert r.error.issues[0].path == ["error"]
    assert Result.discriminator == "status"
    assert len(Result.options) == 2
    with pytest.raises(ValueError, match="Invalid discriminated union option"):
        z.discriminatedUnion("status", [NoTag])


def test_lazy_recursive():
    class Category(z.Object):
        name = z.string()
        subcategories = z.lazy(lambda: z.array(Category))

    data = {"name": "a", "subcategories": [{"name": "b", "subcategories": []}]}
    assert Category.parse(data) == data
    r = Category.safeParse({"name": "a", "subcategories": [{"name": 1, "subcategories": []}]})
    assert r.error.issues[0].path == ["subcategories", 0, "name"]


def test_json():
    assert z.json().parse({"a": [1, "b", None, True, {"c": 2.5}]}) == {"a": [1, "b", None, True, {"c": 2.5}]}
    assert z.json().safeParse({"a": {1, 2}}).success is False


def test_instanceof_custom():
    class Dog:
        pass

    assert isinstance(z.instanceof(Dog).parse(Dog()), Dog)
    assert z.instanceof(Dog).safeParse("x").error.issues[0].message == "Input not instance of Dog"
    px = z.custom(lambda v: isinstance(v, str) and v.startswith("p"), "must start with p")
    assert px.parse("px") == "px"
    assert px.safeParse("x").error.issues[0].message == "must start with p"
    assert z.custom().parse(123) == 123


def test_function():
    fn = z.function({"input": [z.string()], "output": z.number()})
    impl = fn.implement(lambda s: len(s))
    assert impl("abc") == 3
    with pytest.raises(z.ZodError):
        impl(1)
    bad = fn.implement(lambda s: "no")
    with pytest.raises(z.ZodError):
        bad("x")
    assert z.function().implement(lambda *a: list(a))(1, 2) == [1, 2]


def test_template_literal():
    s = z.templateLiteral(["hello, ", z.string()])
    assert s.parse("hello, world") == "hello, world"
    assert s.safeParse("bye").success is False
    css = z.templateLiteral([z.number(), z.enum(("px", "em"))])
    assert css.parse("12px") == "12px"
    assert css.safeParse("12pt").success is False


def test_union_first_success_wins_and_failures_report_every_option():
    # Order matters even when a later option is a plain type check.
    assert z.union([z.string().transform(len), z.string()]).parse("ab") == 2
    assert z.union([z.int(), z.string()]).parse("x") == "x"
    assert z.union([z.string(), z.int()]).parse(3) == 3

    calls = []

    def positive(n: int) -> bool:
        calls.append(n)
        return n > 0

    r = z.union([z.string(), z.int().refine(positive), z.boolean()]).safeParse(-1)
    assert r.success is False
    assert calls == [-1]  # every option runs once, even on the failure path
    # Only the refine failure did not abort, so (as in Zod) its issue is reported directly.
    assert [i["code"] for i in r.error.issues] == ["custom"]

    r = z.union([z.string(), z.int(), z.boolean()]).safeParse(None)
    issue = r.error.issues[0]
    assert issue["code"] == "invalid_union"
    assert [[i["expected"] for i in group] for group in issue["errors"]] == [
        ["string"],
        ["number"],
        ["boolean"],
    ]
