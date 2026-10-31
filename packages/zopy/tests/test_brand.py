"""``.brand()``: a label, or a ``typing.NewType`` for a statically distinct type (value unchanged)."""

from typing import NewType

import pytest

from zopy import z

UserId = NewType("UserId", str)
Age = NewType("Age", int)


def test_newtype_brand_keeps_the_value():
    schema: z.ZodType[UserId] = z.uuid().brand(UserId)
    value = schema.parse("123e4567-e89b-12d3-a456-426614174000")
    assert type(value) is str  # NewType is static only, like Zod's brand
    assert schema.safeParse("nope").success is False
    assert z.int().positive().brand(Age).parse(3) == 3


def test_label_brand_and_invalid_tags():
    assert z.string().brand("Label").parse("x") == "x"

    class NotANewType(str):
        pass

    with pytest.raises(TypeError, match="NewType"):
        z.string().brand(NotANewType)  # pyright: ignore[reportCallIssue, reportArgumentType]
    with pytest.raises(TypeError, match="NewType of str"):
        z.int().brand(UserId)
    with pytest.raises(TypeError, match="NewType of int"):
        z.string().brand(Age)


def test_brand_in_objects():
    Id: z.ZodType[UserId] = z.uuid().brand(UserId)

    class Account(z.Object):
        id = Id
        friends = z.array(Id)

    account = Account.parse({"id": "123e4567-e89b-12d3-a456-426614174000", "friends": []})
    assert account.id == "123e4567-e89b-12d3-a456-426614174000"
    assert Account.safeParse({"id": "nope", "friends": []}).success is False
    assert (
        Account.safeParse({"id": "123e4567-e89b-12d3-a456-426614174000", "friends": ["nope"]}).success
        is False
    )


def test_brand_changes_nothing_but_the_static_type():
    plain = z.int().nonnegative()
    branded = plain.brand(Age)
    assert branded.safeParse(-1).error.issues == plain.safeParse(-1).error.issues
    assert z.toJSONSchema(branded) == z.toJSONSchema(plain)
