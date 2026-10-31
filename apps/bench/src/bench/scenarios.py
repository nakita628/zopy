"""The schemas compared, written once for zopy and once for pydantic with the same rules.

Each scenario pairs a zopy call with the pydantic call doing the same validation, plus a check
that both libraries agree on the input (same accept / reject, same number of issues). Both sides
use their default mode and build typed objects (``z.Object`` instances / ``BaseModel`` instances).
"""

from __future__ import annotations

import contextlib
import datetime as dt
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import (
    AnyUrl,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    ValidationError,
)

from zopy import z

ZIP = r"^\d{3}-\d{4}$"

# --------------------------------------------------------------------------- #
# zopy
# --------------------------------------------------------------------------- #


class ZItem(z.Object):
    name = z.string().min(1)
    price = z.number().positive()
    qty = z.int().min(0)
    tags = z.array(z.string()).max(5)
    note = z.string().optional()


class ZAddress(z.Object):
    street = z.string().min(1)
    city = z.string().min(1)
    zip = z.string().regex(ZIP)


class ZFriend(z.Object):
    name = z.string().min(1)
    age = z.int().positive()


class ZUser(z.Object):
    id = z.int().positive()
    name = z.string().min(1).max(50)
    age = z.int().min(0).max(150)
    role = z.enum(("admin", "member", "guest"))
    active = z.boolean()
    score = z.number().min(0).max(100)
    tags = z.array(z.string()).max(10)
    address = ZAddress
    friends = z.array(ZFriend)
    nickname = z.string().optional()


class ZStrictUser(z.StrictObject):
    id = z.int().positive()
    name = z.string().min(1)


ZItems = z.array(ZItem)
ZInts = z.array(z.int())
ZNames = z.array(z.string().min(1))
ZScores = z.record(z.string(), z.int())
ZMixed = z.array(z.union([z.string(), z.int()]))


class ZCat(z.Object):
    kind = z.literal("cat")
    lives = z.int().min(0).max(9)


class ZDog(z.Object):
    kind = z.literal("dog")
    good = z.boolean()


class ZBird(z.Object):
    kind = z.literal("bird")
    wingspan = z.number().positive()


ZPets = z.array(z.discriminatedUnion("kind", [ZCat, ZDog, ZBird]))


class ZSettings(z.Object):
    theme = z.enum(("light", "dark")).default("light")
    page_size = z.int().min(1).default(20)
    language = z.string().default("en")
    beta = z.boolean().default(False)
    nickname = z.string().optional()


class ZEvent(z.Object):
    id = z.uuid()
    at = z.iso.datetime()
    url = z.url()


class ZNode(z.Object):
    value = z.int()
    children = z.lazy(lambda: z.array(ZNode))


# --------------------------------------------------------------------------- #
# pydantic
# --------------------------------------------------------------------------- #

NonEmpty = Annotated[str, StringConstraints(min_length=1)]


class PItem(BaseModel):
    name: NonEmpty
    price: float = Field(gt=0)
    qty: int = Field(ge=0)
    tags: list[str] = Field(max_length=5)
    note: str | None = None


class PAddress(BaseModel):
    street: NonEmpty
    city: NonEmpty
    zip: Annotated[str, StringConstraints(pattern=ZIP)]


class PFriend(BaseModel):
    name: NonEmpty
    age: int = Field(gt=0)


class PUser(BaseModel):
    id: int = Field(gt=0)
    name: Annotated[str, StringConstraints(min_length=1, max_length=50)]
    age: int = Field(ge=0, le=150)
    role: Literal["admin", "member", "guest"]
    active: bool
    score: float = Field(ge=0, le=100)
    tags: list[str] = Field(max_length=10)
    address: PAddress
    friends: list[PFriend]
    nickname: str | None = None


class PStrictUser(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int = Field(gt=0)
    name: NonEmpty


PItems = TypeAdapter(list[PItem])
PInts = TypeAdapter(list[int])
PNames = TypeAdapter(list[NonEmpty])
PScores = TypeAdapter(dict[str, int])
PMixed = TypeAdapter(list[str | int])


class PCat(BaseModel):
    kind: Literal["cat"]
    lives: int = Field(ge=0, le=9)


class PDog(BaseModel):
    kind: Literal["dog"]
    good: bool


class PBird(BaseModel):
    kind: Literal["bird"]
    wingspan: float = Field(gt=0)


PPets = TypeAdapter(list[Annotated[PCat | PDog | PBird, Field(discriminator="kind")]])


class PSettings(BaseModel):
    theme: Literal["light", "dark"] = "light"
    page_size: int = Field(default=20, ge=1)
    language: str = "en"
    beta: bool = False
    nickname: str | None = None


class PEvent(BaseModel):  # pydantic builds UUID / datetime / Url objects; zopy keeps strings
    id: uuid.UUID
    at: dt.datetime
    url: AnyUrl


class PNode(BaseModel):
    value: int
    children: list[PNode]


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #

ITEM = {"name": "Widget", "price": 9.5, "qty": 3, "tags": ["a", "b"]}
ITEMS = [{**ITEM, "name": f"Widget {i}", "qty": i} for i in range(1000)]

USER = {
    "id": 1,
    "name": "Ada Lovelace",
    "age": 36,
    "role": "admin",
    "active": True,
    "score": 99.5,
    "tags": ["math", "code", "poetry"],
    "address": {"street": "1 Main St", "city": "London", "zip": "123-4567"},
    "friends": [{"name": "Charles", "age": 45}, {"name": "Mary", "age": 30}],
}
# Five issues: name too short, age too large, role not an option, address.zip pattern, friends[1].age.
BAD_USER = {
    **USER,
    "name": "",
    "age": 200,
    "role": "owner",
    "address": {**USER["address"], "zip": "x"},
    "friends": [{"name": "Charles", "age": 45}, {"name": "Mary", "age": -1}],
}
BAD_ISSUES = 5

STRICT_EXTRA = {"id": 1, "name": "a", "extra": True}

INTS = list(range(1000))
NAMES = [f"name{i}" for i in range(1000)]
SCORES = {f"player{i}": i for i in range(100)}
MIXED = [i if i % 2 else str(i) for i in range(1000)]
PETS = [
    [{"kind": "cat", "lives": 7}, {"kind": "dog", "good": True}, {"kind": "bird", "wingspan": 0.3}][i % 3]
    for i in range(300)
]
EVENT = {
    "id": "123e4567-e89b-12d3-a456-426614174000",
    "at": "2026-10-30T12:34:56Z",
    "url": "https://example.com/path?q=1",
}


def _tree(depth: int) -> dict[str, Any]:
    return {"value": depth, "children": [_tree(depth - 1) for _ in range(2)] if depth else []}


TREE = _tree(6)  # 127 nodes


# --------------------------------------------------------------------------- #
# Scenarios
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Scenario:
    name: str
    zopy: Callable[[], object]
    pydantic: Callable[[], object]
    number: int  # calls per timing round
    verify: Callable[[], None]


def _pydantic_errors(model: Any, data: Any) -> list[Any]:
    try:
        model.model_validate(data)
    except ValidationError as e:
        return e.errors()
    return []


def _zopy_issues(schema: Any, data: Any) -> list[Any]:
    result = schema.safeParse(data)
    return [] if result.success else result.error.issues


def _same_outcome(zschema: Any, pmodel: Any, data: Any, issues: int) -> Callable[[], None]:
    def verify() -> None:
        zi, pi = _zopy_issues(zschema, data), _pydantic_errors(pmodel, data)
        assert len(zi) == len(pi) == issues, (len(zi), len(pi), issues)

    return verify


def _zopy_raises(schema: Any, data: Any) -> int:
    try:
        schema.parse(data)
    except z.ZodError as e:
        return len(e.issues)
    return 0


def _pydantic_raises(model: Any, data: Any) -> int:
    try:
        model.model_validate(data)
    except ValidationError as e:
        return e.error_count()
    return 0


def _zopy_raise_only(schema: Any, data: Any) -> None:
    with contextlib.suppress(z.ZodError):
        schema.parse(data)


def _pydantic_raise_only(model: Any, data: Any) -> None:
    with contextlib.suppress(ValidationError):
        model.model_validate(data)


def _verify_raises() -> None:
    assert _zopy_raises(ZUser, BAD_USER) == _pydantic_raises(PUser, BAD_USER) == BAD_ISSUES


def _same_values(zschema: Any, adapter: Any, data: Any) -> Callable[[], None]:
    def verify() -> None:
        zout, pout = zschema.parse(data), adapter.validate_python(data)
        assert zout == pout, "outputs differ"

    return verify


def _verify_pets() -> None:
    zout, pout = ZPets.parse(PETS), PPets.validate_python(PETS)
    assert [type(p).__name__[1:] for p in zout] == [type(p).__name__[1:] for p in pout]


def _verify_settings() -> None:
    zout, pout = ZSettings.parse({}), PSettings.model_validate({})
    assert (zout.theme, zout.page_size, zout.language, zout.beta) == (
        pout.theme,
        pout.page_size,
        pout.language,
        pout.beta,
    )


def _verify_event() -> None:
    zout, pout = ZEvent.parse(EVENT), PEvent.model_validate(EVENT)
    assert zout.id == str(pout.id)
    assert _zopy_issues(ZEvent, {**EVENT, "id": "x"})
    assert _pydantic_errors(PEvent, {**EVENT, "id": "x"})


def _count_nodes(node: Any) -> int:
    return 1 + sum(_count_nodes(c) for c in node.children)


def _verify_tree() -> None:
    assert _count_nodes(ZNode.parse(TREE)) == _count_nodes(PNode.model_validate(TREE)) == 127


def _verify_items() -> None:
    zout, pout = ZItems.parse(ITEMS), PItems.validate_python(ITEMS)
    assert len(zout) == len(pout) == len(ITEMS)
    assert zout[-1].qty == pout[-1].qty == len(ITEMS) - 1


SCENARIOS = [
    Scenario(
        "flat object, valid",
        lambda: ZItem.parse(ITEM),
        lambda: PItem.model_validate(ITEM),
        20_000,
        _same_outcome(ZItem, PItem, ITEM, 0),
    ),
    Scenario(
        "nested object, valid",
        lambda: ZUser.parse(USER),
        lambda: PUser.model_validate(USER),
        10_000,
        _same_outcome(ZUser, PUser, USER, 0),
    ),
    Scenario(
        "nested object, 5 errors (read them)",
        lambda: _zopy_issues(ZUser, BAD_USER),
        lambda: _pydantic_errors(PUser, BAD_USER),
        5_000,
        _same_outcome(ZUser, PUser, BAD_USER, BAD_ISSUES),
    ),
    Scenario(
        "strict object, unknown key (read error)",
        lambda: _zopy_issues(ZStrictUser, STRICT_EXTRA),
        lambda: _pydantic_errors(PStrictUser, STRICT_EXTRA),
        20_000,
        _same_outcome(ZStrictUser, PStrictUser, STRICT_EXTRA, 1),
    ),
    Scenario(
        "nested object, 5 errors (parse raises)",
        lambda: _zopy_raise_only(ZUser, BAD_USER),
        lambda: _pydantic_raise_only(PUser, BAD_USER),
        5_000,
        _verify_raises,
    ),
    Scenario(
        "list of 1000 objects, valid",
        lambda: ZItems.parse(ITEMS),
        lambda: PItems.validate_python(ITEMS),
        20,
        _verify_items,
    ),
    Scenario(
        "list of 1000 ints",
        lambda: ZInts.parse(INTS),
        lambda: PInts.validate_python(INTS),
        200,
        _same_values(ZInts, PInts, INTS),
    ),
    Scenario(
        "list of 1000 strings, min length",
        lambda: ZNames.parse(NAMES),
        lambda: PNames.validate_python(NAMES),
        200,
        _same_values(ZNames, PNames, NAMES),
    ),
    Scenario(
        "record of 100 str -> int",
        lambda: ZScores.parse(SCORES),
        lambda: PScores.validate_python(SCORES),
        2_000,
        _same_values(ZScores, PScores, SCORES),
    ),
    Scenario(
        "list of 1000 str-or-int unions",
        lambda: ZMixed.parse(MIXED),
        lambda: PMixed.validate_python(MIXED),
        200,
        _same_values(ZMixed, PMixed, MIXED),
    ),
    Scenario(
        "list of 300 discriminated unions",
        lambda: ZPets.parse(PETS),
        lambda: PPets.validate_python(PETS),
        100,
        _verify_pets,
    ),
    Scenario(
        "object with defaults, empty input",
        lambda: ZSettings.parse({}),
        lambda: PSettings.model_validate({}),
        20_000,
        _verify_settings,
    ),
    Scenario(
        "string formats: uuid, iso datetime, url",
        lambda: ZEvent.parse(EVENT),
        lambda: PEvent.model_validate(EVENT),
        10_000,
        _verify_event,
    ),
    Scenario(
        "recursive tree, 127 nodes",
        lambda: ZNode.parse(TREE),
        lambda: PNode.model_validate(TREE),
        200,
        _verify_tree,
    ),
]
