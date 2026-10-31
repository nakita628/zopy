"""Internal helpers shared by the zod package."""

from __future__ import annotations

import datetime as _dt
import inspect
import json
import math
from collections.abc import Mapping
from typing import Any


class _Sentinel:
    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{self.name}>"

    def __bool__(self) -> bool:
        return False


INVALID = _Sentinel("INVALID")
NOT_SET = _Sentinel("NOT_SET")


class AttrDict(dict):
    """A dict that also exposes its keys as attributes (``result.success``)."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value

    def __delattr__(self, name: str) -> None:
        try:
            del self[name]
        except KeyError:
            raise AttributeError(name) from None


is_awaitable = inspect.isawaitable  # keeps typeshed's TypeIs narrowing


def get_parsed_type(value: Any) -> str:
    """Mirror of Zod's ``getParsedType`` for Python values."""
    if value is None:
        return "undefined"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "number"
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (list, tuple)):
        return "array"
    if isinstance(value, (_dt.datetime, _dt.date)):
        return "date"
    if isinstance(value, (set, frozenset)):
        return "set"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, (bytes, bytearray)):
        return "bytes"
    if inspect.isawaitable(value):
        return "promise"
    if callable(value):
        return "function"
    return "object"


def stringify(value: Any) -> str:
    """JS-like ``stringifyPrimitive`` used in default error messages."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "undefined"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, float):
        if value.is_integer() and math.isfinite(value):
            return str(int(value))
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return repr(value)
    return str(value)


def join_values(values: Any, separator: str = "|") -> str:
    return separator.join(stringify(v) for v in values)


def format_number(value: Any) -> str:
    if isinstance(value, float) and value.is_integer() and math.isfinite(value):
        return str(int(value))
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.isoformat()
    return str(value)


def is_plain_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# Zod 3 error params and what Zod 4 (and zopy) uses instead.
_ZOD3_PARAMS = {
    "message": '{"error": "..."}',
    "invalid_type_error": '{"error": lambda issue: ...} (check issue["input"])',
    "required_error": '{"error": lambda issue: ...} (check issue["input"] is None)',
    "errorMap": '{"error": lambda issue: ...}',
}


def normalize_params(params: Any = None, kwargs: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Accept ``"message"``, ``{"error": ...}`` (plus other options) or keyword arguments.

    Returns a dict whose ``error`` holds a str or a function of the issue.
    """
    out: dict[str, Any] = {}
    if params is None:
        pass
    elif isinstance(params, str):
        out["error"] = params
    elif isinstance(params, Mapping):
        out.update(params)
    else:
        raise TypeError(f'Invalid params: {params!r}; pass a message or {{"error": ...}}')
    if kwargs:
        out.update({k: v for k, v in kwargs.items() if v is not None})
    for key, replacement in _ZOD3_PARAMS.items():
        if key in out:
            raise TypeError(f"{key!r} is Zod 3 syntax; use {replacement}")
    return out


def resolve_error(error: Any, issue: Mapping[str, Any]) -> str | None:
    if error is None:
        return None
    if callable(error):
        result = error(issue)
        if result is None:
            return None
        if isinstance(result, Mapping):
            return result.get("message")
        return str(result)
    return str(error)
