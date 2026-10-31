"""Compile schemas into the node tree understood by the Rust engine (``zopy._core``).

The pure-Python engine in ``core.py`` stays the reference implementation; this module
flattens a schema graph into node dicts, hands them to ``zopy._core.compile`` once, and
provides the callbacks Rust uses for anything that must run in Python (refinements,
transforms, custom regexes, unsupported node types).
"""

from __future__ import annotations

import datetime as _dt
import enum as _enum
import functools
import inspect
import os
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any, NoReturn, cast

from . import regexes
from . import schemas as s
from ._util import INVALID, AttrDict, is_awaitable
from .core import (
    _DEFAULT_CTX,
    Check,
    ParseContext,
    Payload,
    SafeParseError,
    SafeParseSuccess,
    ZodType,
    _close,
    _strip_internal,
    _takes_ctx,
)
from .errors import ZodAsyncError, ZodError, ZodIssue, _config, finalize_issue

try:  # the Rust extension is a normal dependency, but keep working without it
    from zopy import _core as _zod_core
except Exception:  # pragma: no cover - exercised only when the wheel is missing
    _zod_core = None

_ENGINE_ENV = os.environ.get("ZOD_ENGINE", "").lower()
_engine_name: str = "python" if (_zod_core is None or _ENGINE_ENV == "python") else "rust"


def engine() -> str:
    """Active engine: ``"rust"`` or ``"python"``."""
    return _engine_name


def set_engine(name: str) -> None:
    """Switch engines at runtime (``"rust"`` requires the ``zopy._core`` extension)."""
    global _engine_name
    if name not in ("rust", "python"):
        raise ValueError(f"unknown engine {name!r}")
    if name == "rust" and _zod_core is None:
        raise RuntimeError("zopy._core extension is not installed")
    _engine_name = name
    if _zod_core is not None:
        _zod_core.set_fast(name == "rust")


if _zod_core is not None:
    _zod_core.set_fast(_engine_name == "rust")


def rust_available() -> bool:
    return _zod_core is not None


# --------------------------------------------------------------------------- #
# Checks
# --------------------------------------------------------------------------- #

_SIZE_KINDS = {"min_length", "max_length", "length_equals", "min_size", "max_size", "size_equals"}
_NATIVE_FORMATS = {
    "email",
    "uuid",
    "uuidv4",
    "uuidv6",
    "uuidv7",
    "guid",
    "cuid",
    "cuid2",
    "ulid",
    "xid",
    "ksuid",
    "nanoid",
    "emoji",
    "ipv4",
    "ipv6",
    "ip",
    "cidrv4",
    "cidrv6",
    "cidr",
    "base64",
    "base64url",
    "hex",
    "hostname",
    "e164",
    "jwt",
    "date",
    "time",
    "datetime",
    "duration",
    "lowercase",
    "uppercase",
    "mac",
    "md5",
    "sha1",
    "sha256",
    "sha384",
    "sha512",
    "url",
    "credit_card",
    "currency_code",
    "iban",
}
_OVERWRITE_OPS = {"trim": "trim", "toLowerCase": "lower", "toUpperCase": "upper", "normalize": "normalize"}


_RE_FLAGS = {re.IGNORECASE: "i", re.MULTILINE: "m", re.DOTALL: "s"}
# Escapes whose meaning differs between Python ``re`` and Rust ``regex`` (Unicode classes, ``\Z``).
_RE_UNSAFE_ESCAPES = frozenset("wWsSbBZ")


def _rust_regex(pattern: re.Pattern[Any]) -> tuple[str, bool] | None:
    """Translate a Python regex into Rust syntax when both engines provably agree.

    Returns ``(source, dollar)``; ``dollar`` means the pattern uses ``$``, which in Python also
    matches before a trailing newline, so Rust hands such values back to Python. ``None`` keeps
    the check in Python.
    """
    source = pattern.pattern
    if not isinstance(source, str):
        return None
    flags = pattern.flags & ~re.UNICODE
    prefix = ""
    for flag, letter in _RE_FLAGS.items():
        if flags & flag:
            prefix += letter
            flags &= ~flag
    if flags:
        return None
    dollar = False
    in_class = False
    i, n = 0, len(source)
    while i < n:
        ch = source[i]
        if ch == "\\":
            if i + 1 < n and source[i + 1] in _RE_UNSAFE_ESCAPES:
                return None
            i += 2
            continue
        if in_class:
            if ch == "[" or source[i : i + 2] in ("&&", "--", "~~"):
                return None  # Rust nests classes and has set operators; Python reads them literally
            if ch == "]":
                in_class = False
        elif ch == "[":
            in_class = True
            i += 1
            if source.startswith("^", i):
                i += 1
            if source.startswith("]", i):  # a leading ``]`` is a literal in both engines
                i += 1
            continue
        elif ch == "$":
            dollar = True
        elif source.startswith("{,", i):
            return None  # Python reads ``{,n}`` as ``{0,n}``
        i += 1
    return (f"(?{prefix}){source}" if prefix else source), dollar


def _check_node(check: Check) -> dict[str, Any]:
    p = check.params
    base = {"error": check.error, "abort": check.abort}
    kind = check.kind
    if kind in _SIZE_KINDS:
        return {
            "k": "size",
            "min": p.get("minimum"),
            "max": p.get("maximum"),
            "exact": bool(p.get("exact")),
            "origin": p.get("origin", "value"),
            **base,
        }
    if kind in ("greater_than", "less_than"):
        return {
            "k": "bound",
            "min": p.get("minimum"),
            "min_inclusive": p.get("inclusive", True),
            "max": p.get("maximum"),
            "max_inclusive": p.get("inclusive", True),
            "origin": p.get("origin", "number"),
            **base,
        }
    if kind == "multiple_of":
        return {"k": "multiple_of", "divisor": p["divisor"], "origin": p.get("origin", "number"), **base}
    if kind == "overwrite" and p.get("op") in _OVERWRITE_OPS:
        return {"k": "overwrite", "op": _OVERWRITE_OPS[p["op"]], "form": p.get("form"), **base}
    if kind == "includes":
        return {"k": "includes", "needle": p["includes"], "position": p.get("position") or 0, **base}
    if kind == "starts_with":
        return {"k": "starts_with", "needle": p["prefix"], **base}
    if kind == "ends_with":
        return {"k": "ends_with", "needle": p["suffix"], **base}
    if kind in _NATIVE_FORMATS and not p.get("python"):
        pattern = p.get("pattern")
        return {
            "k": "format",
            "format": kind,
            "opts": p.get("opts") or {},
            "pattern": s._pattern_str(pattern) if pattern is not None else None,
            "extra": {k: v for k, v in p.items() if k in ("alg",) and v is not None},
            **base,
        }
    pattern = p.get("pattern")
    if (kind == "regex" or p.get("python")) and isinstance(pattern, re.Pattern):
        translated = _rust_regex(pattern)
        if translated is not None:
            return {
                "k": "regex",
                "format": kind,
                "source": translated[0],
                "dollar": translated[1],
                "pattern": s._pattern_str(pattern),
                "fallback": check,
                **base,
            }
    return {"k": "py", "check": check, **base}


# --------------------------------------------------------------------------- #
# Nodes
# --------------------------------------------------------------------------- #


class _Compiler:
    def __init__(self) -> None:
        self.nodes: list[dict[str, Any] | None] = []
        self.schemas: list[ZodType[Any]] = []
        self.ids: dict[int, int] = {}

    def node(self, schema: ZodType[Any]) -> int:
        key = id(schema)
        if key in self.ids:
            return self.ids[key]
        if isinstance(schema, s.ZodLazy):
            inner = schema._inner
            idx = self.node(inner)
            self.ids[key] = idx
            return idx
        idx = len(self.nodes)
        self.ids[key] = idx
        self.nodes.append(None)
        self.schemas.append(schema)
        if any(check.when is not None for check in schema._def["checks"]):
            # `when(payload)` reads the issues so far: run this schema in the Python engine.
            built: dict[str, Any] = {"t": "python", "checks": []}
        else:
            built = self.build(schema)
        built["schema"] = schema
        built["has_error"] = schema._def.get("error") is not None
        if "checks" not in built:
            built["checks"] = [_check_node(c) for c in schema._def["checks"]]
        self.nodes[idx] = built
        return idx

    def build(self, schema: ZodType[Any]) -> dict[str, Any]:
        d = schema._def
        if isinstance(schema, s.ZodString):
            return {"t": "string", "coerce": bool(d.get("coerce"))}
        if isinstance(schema, s.ZodInt):
            return {
                "t": "number",
                "kind": "int",
                "coerce": bool(d.get("coerce")),
                "safeint": d.get("format") in (None, "safeint"),
                "int_error": d.get("intError"),
            }
        if isinstance(schema, s.ZodBigInt):
            return {"t": "number", "kind": "bigint", "coerce": bool(d.get("coerce"))}
        if isinstance(schema, s.ZodNumber):
            return {"t": "number", "kind": "float", "coerce": bool(d.get("coerce"))}
        if isinstance(schema, s.ZodBoolean):
            return {"t": "boolean", "coerce": bool(d.get("coerce"))}
        if isinstance(schema, s.ZodDate):
            return {"t": "date", "coerce": s._coerce_date if d.get("coerce") else None}
        if isinstance(schema, s.ZodVoid):
            return {"t": "none", "expected": "void"}
        if isinstance(schema, s.ZodUndefined):
            return {"t": "none", "expected": "undefined"}
        if isinstance(schema, s.ZodNull):
            return {"t": "none", "expected": "null"}
        if isinstance(schema, s.ZodAny):  # includes ZodUnknown
            return {"t": "any"}
        if isinstance(schema, s.ZodNever):
            return {"t": "never"}
        if isinstance(schema, s.ZodNaN):
            return {"t": "nan"}
        if isinstance(schema, s.ZodLiteral):
            return {"t": "literal", "values": list(d["values"])}
        if isinstance(schema, s.ZodEnum):
            entries = list(d["entries"].values())
            return {
                "t": "enum",
                "values": [v.value if isinstance(v, _enum.Enum) else v for v in entries],
                "members": [v if isinstance(v, _enum.Enum) else None for v in entries],
            }
        if isinstance(schema, s.ZodArray):
            return {"t": "array", "element": self.node(d["element"])}
        if isinstance(schema, s.ZodTuple):
            return {
                "t": "tuple",
                "items": [self.node(i) for i in d["items"]],
                "optional": [s._is_optional_marker(i) for i in d["items"]],
                "rest": self.node(d["rest"]) if d.get("rest") is not None else None,
            }
        if isinstance(schema, s.ZodObject):
            catchall = d.get("catchall")
            if catchall is None:
                catchall_node: Any = "strip"
            elif isinstance(catchall, s.ZodNever):
                catchall_node = "strict"
            elif isinstance(catchall, s.ZodUnknown):
                catchall_node = "loose"
            else:
                catchall_node = self.node(catchall)
            return {
                "t": "object",
                "fields": [
                    (k, self.node(v), v._optin, v._optout == "optional") for k, v in d["shape"].items()
                ],
                "catchall": catchall_node,
                "cls": d.get("objectClass"),
            }
        if isinstance(schema, s.ZodRecord):
            mode = d.get("mode") or "normal"
            return {
                "t": "record",
                "key": self.node(d["keyType"]),
                "value": self.node(d["valueType"]),
                "mode": mode,
                "exhaustive": s._exhaustive_values(d["keyType"]) if mode != "partial" else None,
            }
        if isinstance(schema, s.ZodMap):
            return {"t": "map", "key": self.node(d["keyType"]), "value": self.node(d["valueType"])}
        if isinstance(schema, s.ZodSet):
            return {"t": "set", "value": self.node(d["valueType"])}
        if isinstance(schema, s.ZodDiscriminatedUnion):
            all_values: list[Any] = []
            options = []
            for values, option in d["discriminatorMap"]:
                options.append((list(values), self.node(option)))
                for v in values:
                    if v is not None and v not in all_values:
                        all_values.append(v)
            return {
                "t": "discriminated",
                "disc": d["discriminator"],
                "options": options,
                "all": all_values,
                "fallback": bool(d.get("unionFallback")),
            }
        if isinstance(schema, s.ZodXor):
            return {"t": "union", "options": [self.node(o) for o in d["options"]], "exclusive": True}
        if isinstance(schema, s.ZodUnion):
            return {"t": "union", "options": [self.node(o) for o in d["options"]], "exclusive": False}
        if isinstance(schema, s.ZodExactOptional):
            return {"t": "optional", "inner": self.node(d["innerType"]), "exact": True, "defaulted": False}
        if isinstance(schema, s.ZodOptional):
            inner = d["innerType"]
            return {
                "t": "optional",
                "inner": self.node(inner),
                "exact": False,
                "defaulted": inner._optin == "defaulted",
            }
        if isinstance(schema, s.ZodNullable):
            inner = d["innerType"]
            return {"t": "nullable", "inner": self.node(inner), "defaulted": inner._optin == "defaulted"}
        if isinstance(schema, s.ZodNonOptional):
            return {"t": "nonoptional", "inner": self.node(d["innerType"])}
        if isinstance(schema, s.ZodDefault):  # includes ZodPrefault
            value = d["defaultValue"]
            return {
                "t": "default",
                "inner": self.node(d["innerType"]),
                "value": value,
                "callable": callable(value) and not isinstance(value, ZodType),
                "prefault": isinstance(schema, s.ZodPrefault),
            }
        if isinstance(schema, s.ZodCatch):
            value = d["catchValue"]
            return {
                "t": "catch",
                "inner": self.node(d["innerType"]),
                "value": value,
                "callable": callable(value) and not isinstance(value, ZodType),
            }
        if isinstance(schema, s.ZodStringBool):
            return {
                "t": "stringbool",
                "truthy": d["truthy"],
                "falsy": d["falsy"],
                "sensitive": d.get("case") == "sensitive",
            }
        if type(schema) is s.ZodPipe:
            return {"t": "pipe", "left": self.node(d["in_"]), "right": self.node(d["out"])}
        if type(schema) is s.ZodCodec:
            decode, encode = d["transform"], d["reverseTransform"]
            # Rust calls plain `(value) -> value` functions; ctx-taking or async ones stay in Python.
            if not any(_takes_ctx(f) or inspect.iscoroutinefunction(f) for f in (decode, encode)):
                return {
                    "t": "codec",
                    "left": self.node(d["in_"]),
                    "right": self.node(d["out"]),
                    "decode": decode,
                    "encode": encode,
                }
        # transform, codec, readonly, promise, custom, instanceof, file, symbol, ...
        return {"t": "python", "checks": []}


# --------------------------------------------------------------------------- #
# Callbacks used by the Rust engine
# --------------------------------------------------------------------------- #


def _run_schema(
    schema: ZodType[Any], value: Any, path: list[Any], ctx: ParseContext, missing: bool
) -> tuple[Any, list[Any]]:
    payload = Payload(value, [], ctx, list(path), missing)
    result = schema._run(payload)
    if is_awaitable(result):
        _close(result)
        raise ZodAsyncError()
    return result.value, result.issues


def _run_check(
    schema: ZodType[Any], check: Check, value: Any, path: list[Any], ctx: ParseContext
) -> tuple[Any, list[Any]]:
    payload = Payload(value, [], ctx, list(path))
    result = check.run(payload, schema)
    if is_awaitable(result):
        _close(result)
        raise ZodAsyncError()
    return payload.value, payload.issues


def _coerce_number(value: Any, expected: str) -> Any:
    if expected == "bigint":
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    return s._coerce_number(value)


class CompiledSchema:
    """Holds the Rust ``Compiled`` object plus what Python needs to finish issues."""

    __slots__ = ("compiled", "schemas")

    def __init__(self, compiled: Any, schemas: Sequence[ZodType[Any]]) -> None:
        self.compiled = compiled
        self.schemas = list(schemas)

    def finalize(self, raw: Mapping[str, Any], ctx: ParseContext | None) -> ZodIssue:
        issue = dict(raw)
        node = issue.pop("_node", None)
        inst = self.schemas[node] if node is not None else None
        for key in ("errors", "issues"):
            nested = issue.get(key)
            if nested:
                if key == "errors":
                    issue[key] = [[dict(self.finalize(i, ctx)) for i in group] for group in nested]
                else:
                    issue[key] = [dict(self.finalize(i, ctx)) for i in nested]
        if "message" in issue:  # produced by the Python engine; already finalized
            return issue if isinstance(issue, ZodIssue) else ZodIssue(issue)
        return finalize_issue(issue, ctx, inst)

    def run(self, data: Any, ctx: ParseContext) -> tuple[Any, ZodError | None]:
        value, raw_issues = self.compiled.run(data, ctx, ctx.direction == "backward")
        if not raw_issues:
            return value, None
        return value, self.lazy_error(raw_issues, ctx)

    def lazy_error(self, raw_issues: list[Any], ctx: ParseContext) -> ZodError:
        """Messages are only finalized when ``error.issues`` is first read."""
        return ZodError._lazy(functools.partial(self.compiled.build_issues, raw_issues, ctx))

    def build_slow(self, raw_issues: list[Any], ctx: ParseContext) -> list[ZodIssue]:
        """``error.issues`` when an error map may apply (Rust's ``build_issues`` handles the rest)."""
        return _strip_internal([self.finalize(raw, ctx) for raw in raw_issues])


def compile_schema(schema: ZodType[Any]) -> CompiledSchema:
    if _zod_core is None:
        raise RuntimeError("zopy._core extension is not installed")
    compiler = _Compiler()
    root = compiler.node(schema)
    holder: dict[str, Any] = {}

    def catch_value(fn: Callable[[Any], Any], raw_issues: list[Any], value: Any) -> Any:
        compiled: CompiledSchema = holder["compiled"]
        issues = [compiled.finalize(i, None) for i in raw_issues]
        return fn(AttrDict(error=ZodError(issues), input=value, issues=issues))

    from .declarative import Object

    helpers = {
        "run_schema": _run_schema,
        "run_check": _run_check,
        "catch_value": catch_value,
        "coerce_number": _coerce_number,
        "date_types": (_dt.datetime, _dt.date),
        "enum_type": _enum.Enum,
        "object_base": Object,
        "object_new": object.__new__,
        # Bypasses z.Object.__setattr__ (the readonly guard), a Python call per instance.
        "object_setattr": object.__setattr__,
        "exception_new": BaseException.__new__,
        "issue_type": ZodIssue,
        "config": _config,
        "finalize_one": lambda raw, ctx: holder["compiled"].finalize(raw, ctx),
        "build_slow": lambda raw_issues, ctx: holder["compiled"].build_slow(raw_issues, ctx),
    }
    nodes = cast("list[dict[str, Any]]", compiler.nodes)
    compiled = CompiledSchema(_zod_core.compile(nodes, root, helpers), compiler.schemas)
    holder["compiled"] = compiled
    return compiled


def _raise_lazy(pending: Callable[[], list[ZodIssue]]) -> NoReturn:
    raise ZodError._lazy(pending)


def install_fast(schema: ZodType[Any], compiled: CompiledSchema) -> None:
    """Shadow ``schema.parse`` / ``safeParse`` / ``encode`` / ``safeEncode`` with Rust entry points.

    An option-less call then goes straight into Rust; calls with options, or after
    ``set_engine("python")``, fall back to the regular methods. On a ``class X(z.Object)`` the
    entry points are class attributes that only ``X`` itself uses; subclasses (including derived
    schemas such as ``X.refine(...)``) still get the classmethods until they are compiled.
    """
    if _zod_core is None:
        return
    # Failures hand ``on_issues`` the lazy error's pending build, ``(build_issues, raw_issues, ctx)``.
    # ``parse`` / ``encode`` raise ``ZodError`` straight from Rust (``raises``); ``_raise_lazy`` is the
    # same thing in Python, kept as their ``on_issues``.
    entries = []  # (method name, backward, on_ok, on_issues, default context, raises)
    directions = ((False, "parse", "safeParse"), (True, "encode", "safeEncode"))
    for backward, parse_name, safe_name in directions:
        ctx = _DEFAULT_CTX[False, "backward" if backward else "forward"]
        entries.append((parse_name, backward, None, _raise_lazy, ctx, ZodError))
        entries.append((safe_name, backward, SafeParseSuccess, SafeParseError._deferred, ctx, None))

    if isinstance(schema, type):
        from .declarative import Object

        for name, backward, on_ok, on_issues, ctx, raises in entries:
            method = vars(Object).get(name)  # the classmethod
            if method is None:
                continue
            entry = _zod_core.FastParse(
                compiled.compiled,
                ctx,
                on_ok,
                on_issues,
                functools.partial(method.__func__, schema),
                owner=schema,
                fallback=method,
                backward=backward,
                raises=raises,
            )
            type.__setattr__(schema, name, entry)
        return
    cls = type(schema)
    d = vars(schema)
    for name, backward, on_ok, on_issues, ctx, raises in entries:
        d[name] = _zod_core.FastParse(
            compiled.compiled,
            ctx,
            on_ok,
            on_issues,
            functools.partial(getattr(cls, name), schema),
            backward=backward,
            raises=raises,
        )


__all__ = ["INVALID", "CompiledSchema", "compile_schema", "engine", "regexes", "rust_available", "set_engine"]
