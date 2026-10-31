"""ZodError, issues, global config and the error-formatting helpers."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, Self

from ._util import AttrDict, resolve_error
from .locales import en_error

# --------------------------------------------------------------------------- #
# Issue codes
# --------------------------------------------------------------------------- #


class ZodIssueCode:
    invalid_type = "invalid_type"
    too_big = "too_big"
    too_small = "too_small"
    invalid_format = "invalid_format"
    not_multiple_of = "not_multiple_of"
    unrecognized_keys = "unrecognized_keys"
    invalid_union = "invalid_union"
    invalid_key = "invalid_key"
    invalid_element = "invalid_element"
    invalid_value = "invalid_value"
    custom = "custom"


class ZodIssue(AttrDict):
    """A single validation issue. Behaves like a dict and like an object."""

    def __repr__(self) -> str:
        return f"ZodIssue({dict.__repr__(self)})"


# --------------------------------------------------------------------------- #
# Global config
# --------------------------------------------------------------------------- #


class _Config(AttrDict):
    """The global config. ``plain`` caches "no error map applies" (no ``customError``, English
    ``localeError``) for the failed-parse hot path; every mutation refreshes it."""

    __slots__ = ("plain",)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._refresh()

    def _refresh(self) -> None:
        plain = self.get("customError") is None and self.get("localeError") in (None, en_error)
        object.__setattr__(self, "plain", plain)  # a slot, not a config key

    def __setitem__(self, key: str, value: Any) -> None:
        super().__setitem__(key, value)
        self._refresh()

    def __delitem__(self, key: str) -> None:
        super().__delitem__(key)
        self._refresh()

    def update(self, *args: Any, **kwargs: Any) -> None:
        super().update(*args, **kwargs)
        self._refresh()

    def setdefault(self, key: str, default: Any = None) -> Any:
        value = super().setdefault(key, default)
        self._refresh()
        return value

    def pop(self, key: str, *default: Any) -> Any:
        value = super().pop(key, *default)
        self._refresh()
        return value

    def popitem(self) -> tuple[str, Any]:
        item = super().popitem()
        self._refresh()
        return item

    def clear(self) -> None:
        super().clear()
        self._refresh()

    def __ior__(self, other: Any) -> Self:
        super().__ior__(other)
        self._refresh()
        return self


_config = _Config(customError=None, localeError=en_error, jitless=False)


def config(params: Mapping[str, Any] | None = None, **kwargs: Any) -> _Config:
    """Read or update the global config (``z.config({"customError": fn})``)."""
    if params:
        _config.update(params)
    if kwargs:
        _config.update(kwargs)
    return _config


def _json_default(value: Any) -> Any:
    if isinstance(value, (set, frozenset)):
        return sorted(value, key=repr)
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return repr(value)


def finalize_issue(raw: Mapping[str, Any], ctx: Any, inst: Any) -> ZodIssue:
    """Resolve the message for a raw issue and return a finished ``ZodIssue``.

    Precedence: check-level ``error`` > schema-level ``error`` > per-parse
    ``error`` > ``config().customError`` > locale.
    """
    issue = ZodIssue(raw)
    issue.setdefault("path", [])
    message = issue.get("message")
    if message is None:
        candidates: list[Any] = []
        check_error = issue.pop("_check_error", None)
        if check_error is not None:
            candidates.append(check_error)
        if inst is not None:
            schema_error = inst._def.get("error")
            if schema_error is not None:
                candidates.append(schema_error)
        if ctx is not None and ctx.error is not None:
            candidates.append(ctx.error)
        if _config.get("customError") is not None:
            candidates.append(_config["customError"])
        for candidate in candidates:
            message = resolve_error(candidate, issue)
            if message is not None:
                break
        if message is None:
            message = (_config.get("localeError") or en_error)(issue)
        issue["message"] = message
    else:
        issue.pop("_check_error", None)
    issue.pop("inst", None)
    if ctx is None or not ctx.reportInput:
        issue.pop("input", None)
    return issue


# --------------------------------------------------------------------------- #
# ZodError
# --------------------------------------------------------------------------- #


class ZodError(Exception):
    """Raised by ``.parse()``; also the ``.error`` of a failed ``.safeParse()``."""

    name = "ZodError"

    # A lazy error holds a zero-argument build in ``_pending`` (Rust's ``PendingIssues``, or a
    # ``functools.partial``); it runs on first access to ``issues`` and returns finished
    # ``ZodIssue``s (``path`` and ``message`` set), so they skip ``_normalize``. Slots: one is set on
    # every failed parse, and a slot is cheaper than ``__dict__``.
    __slots__ = ("_issues", "_pending")
    _issues: list[ZodIssue]
    _pending: Callable[[], list[ZodIssue]] | None

    def __init__(self, issues: Iterable[Mapping[str, Any]] = ()) -> None:
        # ``message`` is JSON-encoded lazily by ``__str__``; building it here dominated failed parses.
        super().__init__()
        self._pending = None
        self._issues = self._normalize(issues)

    @classmethod
    def _lazy(cls, pending: Callable[[], list[ZodIssue]]) -> ZodError:
        """An error whose issues (and their messages) are built on first access, like pydantic.

        ``pending()`` builds them. This sits on every failed parse, so it stays minimal."""
        error = cls.__new__(cls)  # skips ``__init__``: nothing to normalize yet
        error._pending = pending
        return error

    @staticmethod
    def _normalize(issues: Iterable[Mapping[str, Any]]) -> list[ZodIssue]:
        out = [iss if isinstance(iss, ZodIssue) else ZodIssue(iss) for iss in issues]
        for iss in out:
            iss.setdefault("path", [])
            iss.setdefault("message", "Invalid input")
        return out

    @property
    def issues(self) -> list[ZodIssue]:
        pending = self._pending
        if pending is not None:
            self._pending = None
            self._issues = pending()
        return self._issues

    @issues.setter
    def issues(self, value: Iterable[Mapping[str, Any]]) -> None:
        self._pending = None
        self._issues = self._normalize(value)

    def __reduce__(self) -> tuple[Any, ...]:
        return (type(self), (self.issues,))

    # -- properties -------------------------------------------------------- #
    @property
    def message(self) -> str:
        return json.dumps([dict(i) for i in self.issues], indent=2, ensure_ascii=False, default=_json_default)

    def __str__(self) -> str:
        return self.message

    def __repr__(self) -> str:
        return f"ZodError({self.issues!r})"

    @staticmethod
    def assert_(value: Any) -> None:  # ``ZodError.assert`` in TS
        if not isinstance(value, ZodError):
            raise TypeError(f"Not a ZodError: {value!r}")


ZodRealError = ZodError


class ZodAsyncError(Exception):
    def __init__(self) -> None:
        super().__init__("Encountered Promise during synchronous parse. Use .parseAsync() instead.")


class ZodEncodeError(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(f"Encountered unidirectional transform during encode: {name}")


# --------------------------------------------------------------------------- #
# Error formatting helpers (``z.treeifyError`` etc.)
# --------------------------------------------------------------------------- #


def _issues_of(error: Any) -> list[ZodIssue]:
    if isinstance(error, ZodError):
        return error.issues
    if isinstance(error, Mapping) and "issues" in error:
        return [ZodIssue(i) for i in error["issues"]]
    if isinstance(error, Sequence):
        return [ZodIssue(i) for i in error]
    raise TypeError(f"Expected ZodError, got {error!r}")


def flattenError(error: Any, mapper: Callable[[ZodIssue], Any] | None = None) -> dict[str, Any]:  # noqa: N802
    mapper = mapper or (lambda issue: issue["message"])
    field_errors: dict[str, list[Any]] = {}
    form_errors: list[Any] = []
    for issue in _issues_of(error):
        path = issue.get("path") or []
        if path:
            key = str(path[0])
            field_errors.setdefault(key, []).append(mapper(issue))
        else:
            form_errors.append(mapper(issue))
    return {"formErrors": form_errors, "fieldErrors": field_errors}


def treeifyError(error: Any, mapper: Callable[[ZodIssue], Any] | None = None) -> dict[str, Any]:  # noqa: N802
    mapper = mapper or (lambda issue: issue["message"])
    result: dict[str, Any] = {"errors": []}

    def process(issue: ZodIssue, path: Sequence[Any]) -> None:
        full_path = list(path)
        if issue.get("code") == "invalid_union" and issue.get("errors"):
            for sub in issue["errors"]:
                for sub_issue in sub:
                    process(ZodIssue(sub_issue), full_path + list(sub_issue.get("path") or []))
            return
        curr = result
        for i, key in enumerate(full_path):
            terminal = i == len(full_path) - 1
            if isinstance(key, int):
                items = curr.setdefault("items", [])
                while len(items) <= key:
                    items.append(None)
                if items[key] is None:
                    items[key] = {"errors": []}
                curr = items[key]
            else:
                props = curr.setdefault("properties", {})
                curr = props.setdefault(str(key), {"errors": []})
            if terminal:
                curr["errors"].append(mapper(issue))
        if not full_path:
            result["errors"].append(mapper(issue))

    for issue in _issues_of(error):
        process(issue, issue.get("path") or [])
    return result


def _to_dot_path(path: Sequence[Any]) -> str:
    parts: list[str] = []
    for seg in path:
        if isinstance(seg, int):
            parts.append(f"[{seg}]")
        elif isinstance(seg, str) and seg.isidentifier():
            parts.append(("." if parts else "") + seg)
        else:
            parts.append(f"[{json.dumps(str(seg))}]")
    return "".join(parts)


def prettifyError(error: Any) -> str:  # noqa: N802
    lines: list[str] = []
    issues = sorted(_issues_of(error), key=lambda i: len(i.get("path") or []))
    for issue in issues:
        lines.append(f"✖ {issue['message']}")
        path = issue.get("path") or []
        if path:
            lines.append(f"  → at {_to_dot_path(path)}")
    return "\n".join(lines)


def toDotPath(path: Sequence[Any]) -> str:  # noqa: N802
    return _to_dot_path(path)
