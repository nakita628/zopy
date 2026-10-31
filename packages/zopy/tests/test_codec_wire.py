"""Codecs in both directions, pipes stopping like Zod's, and objects' JSON wire form."""

import datetime as dt

import pytest

from zopy import z

WHEN = dt.datetime(2026, 7, 18, 9, 30, 0, 123000, tzinfo=dt.UTC)
IsoDateTime = z.codec(
    z.iso.datetime(),
    z.date(),
    decode=dt.datetime.fromisoformat,
    encode=lambda d: d.astimezone(dt.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
)


class Event(z.Object):
    title = z.string()
    at = IsoDateTime
    until = IsoDateTime.optional()


def test_codec_decodes_and_encodes_inside_objects():
    wire = {"title": "t", "at": "2026-07-18T09:30:00.123Z"}
    event = Event.decode(wire)
    assert isinstance(event, Event)
    assert event.at == WHEN
    assert event.until is None
    encoded = Event.encode({"title": "t", "at": WHEN})
    assert isinstance(encoded, Event)
    assert encoded.at == "2026-07-18T09:30:00.123Z"
    assert z.encode(z.array(IsoDateTime), [WHEN]) == ["2026-07-18T09:30:00.123Z"]


def test_codec_errors_in_each_direction():
    decoded = Event.safeDecode({"title": "t", "at": "soon"})  # not an ISO datetime string
    assert [i["code"] for i in decoded.error.issues] == ["invalid_format"]
    encoded = Event.safeEncode({"title": "t", "at": "2026"})  # a string where a datetime belongs
    assert [i["code"] for i in encoded.error.issues] == ["invalid_type"]


def test_one_way_transform_cannot_encode():
    with pytest.raises(z.ZodEncodeError):
        z.encode(z.date().transform(str), WHEN)


def test_encode_of_a_plain_schema_validates_like_parse():
    class Schema(z.Object):
        n = z.int().min(1)

    schema = Schema
    assert z.encode(schema, {"n": 2}) == {"n": 2}
    assert not z.safeEncode(schema, {"n": 0}).success


def test_a_pipe_stops_at_the_first_side_with_issues():
    """Zod's handlePipeResult: the transform after a failed format check never runs."""
    domain = z.email().pipe(z.transform(lambda s: s.split("@")[1]))
    assert domain.parse("a@example.com") == "example.com"
    assert [i["code"] for i in domain.safeParse("nope").error.issues] == ["invalid_format"]
    checked = z.email().pipe(z.string()).refine(lambda s: False, "never reached")
    assert [i["code"] for i in checked.safeParse("nope").error.issues] == ["invalid_format"]


def test_unset_optional_fields_are_left_out_of_the_wire_dict():
    class Patch(z.Object):
        a = z.string().exactOptional()
        b = z.string().optional()
        c = z.string().nullable()
        d = z.string().nullish()
        e = z.int()

    patch = Patch.parse({"e": 1, "c": None})
    assert patch._wire_dict() == {"c": None, "e": 1}
    assert patch.to_dict() == {"c": None, "e": 1}  # absent fields are not keys
    assert (patch.a, patch.b, patch.d) == (None, None, None)  # ... but read as None
    explicit = Patch.parse({"e": 1, "b": None, "d": None})
    assert explicit.to_dict() == {"b": None, "d": None, "e": 1}
    assert explicit._wire_dict() == {"d": None, "e": 1}  # b rejects None on the wire
