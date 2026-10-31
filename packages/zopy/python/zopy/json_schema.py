"""``z.toJSONSchema`` - convert schemas to JSON Schema (draft 2020-12 by default)."""

from __future__ import annotations

import enum
from collections.abc import Mapping
from typing import Any

from . import schemas as s
from .core import ZodType
from .registries import globalRegistry

_FORMAT_MAP: dict[str, dict[str, Any]] = {
    "email": {"format": "email"},
    "url": {"format": "uri"},
    "uuid": {"format": "uuid"},
    "uuidv4": {"format": "uuid"},
    "uuidv6": {"format": "uuid"},
    "uuidv7": {"format": "uuid"},
    "guid": {"format": "uuid"},
    "datetime": {"format": "date-time"},
    "date": {"format": "date"},
    "time": {"format": "time"},
    "duration": {"format": "duration"},
    "ipv4": {"format": "ipv4"},
    "ipv6": {"format": "ipv6"},
    "cidrv4": {"format": "ipv4"},
    "cidrv6": {"format": "ipv6"},
    "hostname": {"format": "hostname"},
    "jwt": {"format": "jwt"},
    "e164": {"format": "e164"},
    "base64": {"contentEncoding": "base64"},
    "base64url": {"format": "base64url"},
    "emoji": {"format": "emoji"},
    "nanoid": {"format": "nanoid"},
    "cuid": {"format": "cuid"},
    "cuid2": {"format": "cuid2"},
    "ulid": {"format": "ulid"},
    "xid": {"format": "xid"},
    "ksuid": {"format": "ksuid"},
}


class _Converter:
    def __init__(self, params: Mapping[str, Any]) -> None:
        self.target = params.get("target", "draft-2020-12")
        self.unrepresentable = params.get("unrepresentable", "throw")
        self.io = params.get("io", "output")
        self.metadata = params.get("metadata", globalRegistry)
        self.cycles = params.get("cycles", "ref")
        self.reused = params.get("reused", "inline")
        self.override = params.get("override")
        # Zod's ``uri``: where an extracted schema's $ref points (default ``#/$defs/<id>``).
        self.uri = params.get("uri")
        # Targets without `const` / numeric `exclusiveMinimum` (Zod's "legacy" targets).
        self._legacy = self.target in ("draft-4", "draft-04", "openapi-3.0")
        self.seen: dict[int, dict[str, Any]] = {}
        self.defs: dict[str, dict[str, Any]] = {}
        self.in_progress: set[int] = set()
        self.counts: dict[int, int] = {}
        self.names: dict[int, str] = {}
        self.root_id: int | None = None
        # As in Zod, a schema with an ``id`` in its metadata is always extracted into $defs under
        # that id and referenced by $ref (the id key itself is dropped from the definition).
        # Registry conversion keeps ids inline instead (``extract_ids = False``).
        self.extract_ids = True
        self.extracted: set[int] = set()

    # -- public ------------------------------------------------------------ #
    def convert(self, schema: ZodType) -> dict[str, Any]:
        self._count(schema)
        result = self._process(schema, root=True)
        if self.defs:
            key = "$defs" if self.target == "draft-2020-12" else "definitions"
            result[key] = self.defs
        if self.target == "draft-2020-12":
            result = {"$schema": "https://json-schema.org/draft/2020-12/schema", **result}
        elif self.target == "draft-7":
            result = {"$schema": "http://json-schema.org/draft-07/schema#", **result}
        return result

    # -- counting (for ``reused: "ref"``) ----------------------------------- #
    def _count(self, schema: ZodType, visited: set[int] | None = None) -> None:
        visited = visited or set()
        self.counts[id(schema)] = self.counts.get(id(schema), 0) + 1
        if id(schema) in visited:
            return
        visited.add(id(schema))
        for child in _children(schema):
            self._count(child, visited)

    # -- conversion -------------------------------------------------------- #
    def _ref_path(self, name: str) -> str:
        if self.uri is not None:
            return self.uri(name)
        return f"#/$defs/{name}" if self.target == "draft-2020-12" else f"#/definitions/{name}"

    def _process(self, schema: ZodType, root: bool = False) -> dict[str, Any]:
        key = id(schema)
        if root:
            self.root_id = key
        if key in self.in_progress:
            if self.cycles == "throw":
                raise ValueError(
                    "Cycle detected: cannot convert recursive schema to JSON Schema without $ref"
                )
            if key == self.root_id and not (self.extract_ids and self._schema_id(schema)):
                return {"$ref": "#"}
            return {"$ref": self._ref_path(self._def_name(schema))}
        if key in self.seen:
            if self.reused == "ref" and not root:
                name = self._def_name(schema)
                self.defs.setdefault(name, self.seen[key])
                return {"$ref": self._ref_path(name)}
            if key in self.names and (key != self.root_id or key in self.extracted):
                return {"$ref": self._ref_path(self.names[key])}
            return dict(self.seen[key])
        self.in_progress.add(key)
        try:
            result = self._convert(schema)
        finally:
            self.in_progress.discard(key)
        meta = self.metadata.get(schema) if self.metadata is not None else None
        if meta:
            for k, v in meta.items():
                if k == "id":
                    if not self.extract_ids:
                        result["id" if self.target == "draft-7" else "$id"] = v
                else:
                    result[k] = v
        if self.override is not None:
            self.override({"zodSchema": schema, "jsonSchema": result, "path": []})
        self.seen[key] = result
        schema_id = self._schema_id(schema) if self.extract_ids else None
        if schema_id:
            self.names[key] = schema_id
            self.extracted.add(key)
            self.defs[schema_id] = result
            return {"$ref": self._ref_path(schema_id)}
        if key in self.names and key != self.root_id:
            # Referenced recursively while being converted: hoist into $defs.
            name = self.names[key]
            self.defs[name] = result
            return {"$ref": self._ref_path(name)}
        return result

    def _schema_id(self, schema: ZodType) -> str | None:
        meta = self.metadata.get(schema) if self.metadata is not None else None
        return (meta or {}).get("id") or None

    def _def_name(self, schema: ZodType) -> str:
        if id(schema) not in self.names:
            meta = self.metadata.get(schema) if self.metadata is not None else None
            base = (meta or {}).get("id") or f"__schema{len(self.names)}"
            self.names[id(schema)] = base
        return self.names[id(schema)]

    def _unrepresentable(self, what: str) -> dict[str, Any]:
        if self.unrepresentable == "any":
            return {}
        raise ValueError(f"{what} cannot be represented in JSON Schema")

    def _convert(self, schema: ZodType) -> dict[str, Any]:
        d = schema._def
        checks_json: dict[str, Any] = {}
        for ch in d.get("checks", []):
            checks_json.update(ch.json)

        if isinstance(schema, s.ZodString):
            out: dict[str, Any] = {"type": "string"}
            if checks_json.get("minimum") is not None:
                out["minLength"] = checks_json["minimum"]
            if checks_json.get("maximum") is not None:
                out["maxLength"] = checks_json["maximum"]
            patterns: list[str] = []
            for ch in d["checks"]:
                fmt = ch.params.get("format")
                if fmt in _FORMAT_MAP:
                    out.update(_FORMAT_MAP[fmt])
                pattern = ch.params.get("pattern")
                if pattern is not None and fmt not in _FORMAT_MAP:
                    patterns.append(pattern.pattern if hasattr(pattern, "pattern") else str(pattern))
                if fmt == "starts_with":
                    import re

                    patterns.append("^" + re.escape(ch.params["prefix"]))
                if fmt == "ends_with":
                    import re

                    patterns.append(re.escape(ch.params["suffix"]) + "$")
                if fmt == "includes":
                    import re

                    patterns.append(re.escape(ch.params["includes"]))
            if len(patterns) == 1:
                out["pattern"] = patterns[0]
            elif patterns:
                out["allOf"] = [{"pattern": p} for p in patterns]
            return out

        if isinstance(schema, s.ZodBigInt):
            return self._unrepresentable("BigInt")

        if isinstance(schema, (s.ZodNumber, s.ZodInt)):
            out = {"type": "integer" if isinstance(schema, s.ZodInt) else "number"}
            for ch in d["checks"]:
                if ch.kind == "int":
                    continue
                p = ch.params
                if p.get("minimum") is not None:
                    if p.get("inclusive", True):
                        out["minimum"] = p["minimum"]
                    elif self._legacy:
                        out["minimum"] = p["minimum"]
                        out["exclusiveMinimum"] = True
                    else:
                        out["exclusiveMinimum"] = p["minimum"]
                if p.get("maximum") is not None:
                    if p.get("inclusive", True):
                        out["maximum"] = p["maximum"]
                    elif self._legacy:
                        out["maximum"] = p["maximum"]
                        out["exclusiveMaximum"] = True
                    else:
                        out["exclusiveMaximum"] = p["maximum"]
                if p.get("divisor") is not None:
                    out["multipleOf"] = p["divisor"]
            fmt = d.get("format")
            if fmt in ("int32", "uint32", "int64", "uint64", "safeint"):
                out["type"] = "integer"
            return out

        if isinstance(schema, s.ZodBoolean):
            return {"type": "boolean"}
        if isinstance(schema, s.ZodNull):
            return {"type": "null"}
        if isinstance(schema, s.ZodUndefined):
            return (
                self._unrepresentable("Undefined")
                if not isinstance(schema, s.ZodVoid)
                else self._unrepresentable("Void")
            )
        if isinstance(schema, s.ZodAny):  # includes Unknown
            return {}
        if isinstance(schema, s.ZodNever):
            return {"not": {}}
        if isinstance(schema, s.ZodNaN):
            return self._unrepresentable("NaN")
        if isinstance(schema, s.ZodDate):
            return self._unrepresentable("Date")
        if isinstance(schema, s.ZodSymbol):
            return self._unrepresentable("Symbol")
        if isinstance(schema, s.ZodFile):
            return {"type": "string", "format": "binary", "contentEncoding": "binary"}

        if isinstance(schema, s.ZodLiteral):
            values = list(d["values"])
            if any(v is None for v in values):
                values = [v for v in values if v is not None]
                if not values:
                    return self._unrepresentable("Literal `undefined`")
            # As Zod's literalProcessor: a JSON type plus `const` (`enum: [v]` for draft-04 /
            # openapi-3.0, which have no `const`); several values give `enum`.
            types = {_json_type(v) for v in values}
            out = {"type": types.pop()} if len(types) == 1 and None not in types else {}
            if len(values) == 1:
                out["enum" if self._legacy else "const"] = [values[0]] if self._legacy else values[0]
            else:
                out["enum"] = values
            return out

        if isinstance(schema, s.ZodEnum):
            # As Zod's enumProcessor: `type` when every value is a string (or every one a number).
            values = [v.value if isinstance(v, enum.Enum) else v for v in d["entries"].values()]
            if not values:
                return {"not": {}}
            types = {_json_type(v) for v in values}
            out = {"type": types.pop()} if len(types) == 1 and types <= {"string", "number"} else {}
            out["enum"] = values
            return out

        if isinstance(schema, s.ZodStringBool):
            return {"type": "string"} if self.io == "input" else {"type": "boolean"}

        if isinstance(schema, s.ZodArray):
            out = {"type": "array", "items": self._process(d["element"])}
            if checks_json.get("minimum") is not None:
                out["minItems"] = checks_json["minimum"]
            if checks_json.get("maximum") is not None:
                out["maxItems"] = checks_json["maximum"]
            return out

        if isinstance(schema, s.ZodTuple):
            prefix = [self._process(i) for i in d["items"]]
            out = {"type": "array"}
            if self.target == "draft-2020-12":
                out["prefixItems"] = prefix
                if d.get("rest") is not None:
                    out["items"] = self._process(d["rest"])
            else:
                out["items"] = prefix
                if d.get("rest") is not None:
                    out["additionalItems"] = self._process(d["rest"])
            out["minItems"] = len([i for i in d["items"] if i._optin is None])
            if d.get("rest") is None:
                out["maxItems"] = len(d["items"])
            return out

        if isinstance(schema, s.ZodObject):
            properties: dict[str, Any] = {}
            required: list[str] = []
            for key, child in d["shape"].items():
                properties[key] = self._process(child)
                optional = child._optin is not None if self.io == "input" else child._optout == "optional"
                if not optional:
                    required.append(key)
            out = {"type": "object", "properties": properties}
            if required:
                out["required"] = required
            catchall = d.get("catchall")
            if catchall is None:
                if self.io == "output":
                    out["additionalProperties"] = False
            elif isinstance(catchall, s.ZodNever):
                out["additionalProperties"] = False
            else:
                out["additionalProperties"] = self._process(catchall)
            return out

        if isinstance(schema, s.ZodRecord):
            out = {"type": "object"}
            key_schema = self._process(d["keyType"])
            if key_schema and key_schema != {"type": "string"}:
                out["propertyNames"] = key_schema
            out["additionalProperties"] = self._process(d["valueType"])
            exhaustive = s._exhaustive_values(d["keyType"])
            if exhaustive and d.get("mode") != "partial":
                out["properties"] = {str(k): out["additionalProperties"] for k in exhaustive}
                out["required"] = [str(k) for k in exhaustive]
            return out

        if isinstance(schema, s.ZodMap):
            return self._unrepresentable("Map")
        if isinstance(schema, s.ZodSet):
            return self._unrepresentable("Set")

        if isinstance(schema, s.ZodDiscriminatedUnion | s.ZodUnion):
            return {"anyOf": [self._process(o) for o in d["options"]]}

        if isinstance(schema, s.ZodOptional):
            return self._process(d["innerType"])

        if isinstance(schema, s.ZodNullable):
            inner = self._process(d["innerType"])
            if self.target == "openapi-3.0":
                return {**inner, "nullable": True}
            return {"anyOf": [inner, {"type": "null"}]}

        if isinstance(schema, s.ZodDefault | s.ZodPrefault):
            inner = self._process(d["innerType"])
            value = d["defaultValue"]
            inner = dict(inner)
            inner["default"] = _json_value(value() if callable(value) else value)
            return inner

        if isinstance(schema, s.ZodCatch):
            inner = dict(self._process(d["innerType"]))
            value = d["catchValue"]
            if not callable(value):
                inner["default"] = _json_value(value)
            return inner

        if isinstance(schema, s.ZodNonOptional | s.ZodReadonly):
            out = dict(self._process(d["innerType"]))
            if isinstance(schema, s.ZodReadonly):
                out["readOnly"] = True
            return out

        if isinstance(schema, s.ZodLazy):
            return self._process(schema._inner)

        if isinstance(schema, s.ZodCodec):
            return self._process(d["in_"] if self.io == "input" else d["out"])

        if isinstance(schema, s.ZodPipe):
            if isinstance(d["out"], s.ZodTransform):
                if self.io == "input":
                    return self._process(d["in_"])
                return self._unrepresentable("Transforms")
            return self._process(d["in_"] if self.io == "input" else d["out"])

        if isinstance(schema, s.ZodTransform):
            return self._unrepresentable("Transforms")

        if isinstance(schema, s.ZodCustom):
            return self._unrepresentable("Custom types")

        return self._unrepresentable(type(schema).__name__)


def _children(schema: ZodType) -> list[ZodType]:
    d = schema._def
    out: list[ZodType] = []
    for key in (
        "element",
        "innerType",
        "left",
        "right",
        "in_",
        "out",
        "keyType",
        "valueType",
        "catchall",
        "rest",
    ):
        v = d.get(key)
        if isinstance(v, ZodType):
            out.append(v)
    out.extend(d.get("shape", {}).values() if isinstance(d.get("shape"), dict) else [])
    out.extend(d.get("items", []) or [])
    out.extend(d.get("options", []) or [])
    if isinstance(schema, s.ZodLazy):
        out.append(schema._inner)
    return out


def toJSONSchema(schema: Any, params: Mapping[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:  # noqa: N802
    """Convert a schema (or a registry) to JSON Schema."""
    p = dict(params or {})
    p.update(kwargs)
    from .registries import ZodRegistry

    if isinstance(schema, ZodRegistry):
        converter = _Converter(p)
        converter.extract_ids = False
        schemas: dict[str, Any] = {}
        for sch, meta in schema:
            name = meta.get("id") or f"__schema{len(schemas)}"
            converter.names[id(sch)] = name
        for sch, _meta in schema:
            name = converter.names[id(sch)]
            schemas[name] = converter._process(sch, root=True)
        out = {"schemas": schemas}
        return out
    return _Converter(p).convert(schema)


to_json_schema = toJSONSchema


def _json_type(value: Any) -> str | None:
    """JavaScript's ``typeof`` for a literal value, as JSON Schema ``type``."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    return None


def _json_value(value: Any) -> Any:
    """Default values in JSON Schema: ``z.Object`` instances become plain dicts."""
    from .declarative import Object

    return value.to_dict() if isinstance(value, Object) else value
