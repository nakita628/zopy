"""``.readonly()`` on objects: where the freeze reaches, and where it does not."""

import pytest

from zopy import z


class Point(z.Object):
    x = z.int()


class Shape(z.Object):
    name = z.string()
    tags = z.array(z.string()).readonly()
    origin = Point.readonly()
    center = Point


DATA = {"name": "a", "tags": ["t"], "origin": {"x": 1}, "center": {"x": 2}}


def test_readonly_fields_are_frozen_inside_a_mutable_object():
    shape = Shape.parse(DATA)
    shape.name = "b"  # the object itself is not readonly
    assert shape.tags == ("t",)
    with pytest.raises(AttributeError, match="Point is readonly"):
        shape.origin.x = 9
    shape.center.x = 9  # a plain nested object stays mutable
    assert shape.center.x == 9


def test_freeze_is_shallow():
    shape = Shape.readonly().parse({**DATA, "tags": ["t"]})
    with pytest.raises(AttributeError, match="Shape is readonly"):
        shape.name = "b"
    shape.center.x = 9  # the nested object was not marked readonly
    assert shape.center.x == 9


@pytest.mark.asyncio
async def test_every_parse_entry_point_freezes():
    schema = Point.readonly()
    result = schema.safeParse({"x": 1})
    assert result.success
    for point in (schema.parse({"x": 1}), result.data, await schema.parseAsync({"x": 1})):
        with pytest.raises(AttributeError, match="Point is readonly"):
            point.x = 2


def test_readonly_items_and_wrappers():
    points = z.array(Point.readonly()).parse([{"x": 1}, {"x": 2}])
    with pytest.raises(AttributeError, match="Point is readonly"):
        points[1].x = 0
    points.append(Point(x=3))  # the list itself is not readonly

    maybe = Point.readonly().optional()
    assert maybe.parse(None) is None
    with pytest.raises(AttributeError, match="Point is readonly"):
        maybe.parse({"x": 1}).x = 2  # pyright: ignore[reportOptionalMemberAccess]


def test_readonly_does_not_leak_into_other_parses():
    frozen = Point.readonly().parse({"x": 1})
    for _ in range(2):  # the compiled schema is cached: parse twice
        point = Point.parse({"x": 1})
        point.x = 2
        assert point.x == 2
    assert frozen.x == 1


def test_frozen_instances_compare_and_serialize_like_mutable_ones():
    frozen = Shape.readonly().parse(DATA)
    assert frozen == Shape.parse(DATA)
    assert frozen.to_dict() == {**DATA, "tags": ("t",)}
