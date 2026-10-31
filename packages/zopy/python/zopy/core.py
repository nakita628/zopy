"""Parsing machinery: payloads, checks and the ``ZodType`` base class."""

from __future__ import annotations

import asyncio
import copy
import functools
import inspect
from collections.abc import Awaitable, Callable, Coroutine, Iterator, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Generic, Literal, Never, NewType, Self, TypeVar, Union, overload

from ._util import INVALID, is_awaitable, normalize_params
from .errors import ZodAsyncError, ZodError, ZodIssue, finalize_issue

if TYPE_CHECKING:
    from .declarative import Object
    from .schemas import (
        ZodAny,
        ZodArray,
        ZodCatch,
        ZodCustom,
        ZodDefault,
        ZodExactOptional,
        ZodNonOptional,
        ZodNullable,
        ZodOptional,
        ZodPipe,
        ZodPrefault,
        ZodReadonly,
        ZodUnion,
    )

T = TypeVar("T")
U = TypeVar("U")
K = TypeVar("K")
V = TypeVar("V")
Output = TypeVar("Output", covariant=True)

# --------------------------------------------------------------------------- #
# Parse context / payload
# --------------------------------------------------------------------------- #


class ParseContext:
    __slots__ = ("async_", "direction", "error", "jitless", "reportInput")

    def __init__(
        self,
        *,
        error: Any = None,
        reportInput: bool = False,  # noqa: N803
        async_: bool = False,
        direction: str = "forward",
    ) -> None:
        self.error = error
        self.reportInput = reportInput
        self.async_ = async_
        self.direction = direction


class Payload:
    """Mutable parse state threaded through ``_parse`` (``ParsePayload`` in Zod 4)."""

    __slots__ = ("ctx", "issues", "missing", "path", "value")

    def __init__(
        self,
        value: Any,
        issues: list[ZodIssue] | None,
        ctx: ParseContext,
        path: list[Any],
        missing: bool = False,
    ) -> None:
        self.value = value
        self.issues = issues if issues is not None else []
        self.ctx = ctx
        self.path = path
        self.missing = missing

    def child(self, value: Any, key: Any, *, missing: bool = False) -> Payload:
        return Payload(value, [], self.ctx, [*self.path, key], missing)

    def sibling(self, value: Any) -> Payload:
        return Payload(value, [], self.ctx, list(self.path))

    def push(self, inst: Any, raw: Mapping[str, Any]) -> ZodIssue:
        issue = dict(raw)
        issue["path"] = [*self.path, *issue.get("path", [])]
        if issue.get("code") == "invalid_type" and self.missing and "received" not in issue:
            issue["received"] = "undefined"
        finalized = finalize_issue(issue, self.ctx, inst)
        self.issues.append(finalized)
        return finalized

    def merge(self, other: Payload) -> None:
        if other.issues:
            self.issues.extend(other.issues)


def _close(awaitable: Any) -> None:
    close = getattr(awaitable, "close", None)
    if callable(close):
        close()


def aborted(payload: Payload, start: int = 0) -> bool:
    return any(issue.get("continue") is not True for issue in payload.issues[start:])


def _strip_internal(issues: list[ZodIssue]) -> list[ZodIssue]:
    for issue in issues:
        issue.pop("continue", None)
    return issues


# --------------------------------------------------------------------------- #
# Checks
# --------------------------------------------------------------------------- #


class Check:
    """A validation step attached to a schema (``$ZodCheck``)."""

    __slots__ = ("abort", "error", "fn", "json", "kind", "params", "when")

    def __init__(
        self,
        kind: str,
        fn: Callable[[Payload, Check, Any], Any],
        *,
        params: Mapping[str, Any] | None = None,
        error: Any = None,
        when: Callable[[Payload], bool] | None = None,
        abort: bool = False,
        json: Mapping[str, Any] | None = None,
    ) -> None:
        self.kind = kind
        self.fn = fn
        self.params = dict(params or {})
        self.error = error
        self.when = when
        self.abort = abort
        self.json = dict(json or {})

    def run(self, payload: Payload, inst: Any) -> Any:
        return self.fn(payload, self, inst)

    def issue(self, payload: Payload, raw: Mapping[str, Any], inst: Any = None) -> ZodIssue:
        data = dict(raw)
        data.setdefault("input", payload.value)
        data.setdefault("continue", not self.abort)
        if self.error is not None:
            data["_check_error"] = self.error
        return payload.push(inst, data)

    def __repr__(self) -> str:  # pragma: no cover
        return f"Check({self.kind}, {self.params})"


class RefinementCtx:
    """``ctx`` passed to ``superRefine`` / ``transform`` / ``check`` callbacks."""

    def __init__(self, payload: Payload, check: Check | None, schema: Any) -> None:
        self._payload = payload
        self._check = check
        self._schema = schema
        self.issues = _IssueList(self)

    @property
    def value(self) -> Any:
        return self._payload.value

    @value.setter
    def value(self, new: Any) -> None:
        self._payload.value = new

    def addIssue(self, issue: Mapping[str, Any] | str, **kwargs: Any) -> None:  # noqa: N802
        if isinstance(issue, str):
            raw: dict[str, Any] = {"code": "custom", "message": issue}
        else:
            raw = dict(issue)
        raw.update(kwargs)
        raw.setdefault("code", "custom")
        raw.setdefault("input", self._payload.value)
        raw.setdefault("continue", not (self._check.abort if self._check else False))
        if "params" in raw and raw["params"] is None:
            raw.pop("params")
        self._payload.push(self._schema, raw)

    add_issue = addIssue


class _IssueList:
    """``ctx.issues.push({...})`` / ``ctx.issues.append({...})`` support.

    Issues are forwarded to the payload immediately; the list itself stays empty.
    """

    __slots__ = ("_ctx",)

    def __init__(self, ctx: RefinementCtx) -> None:
        self._ctx = ctx

    def append(self, issue: Any) -> None:
        self._ctx.addIssue(issue)

    def __len__(self) -> int:
        return len(self._ctx._payload.issues)

    def __iter__(self) -> Iterator[ZodIssue]:
        return iter(self._ctx._payload.issues)

    def push(self, *issues: Any) -> None:
        for issue in issues:
            self._ctx.addIssue(issue)


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #


class _SafeParseBase:
    """Dict-style access (``result["success"]``) on top of attribute access."""

    __slots__ = ()

    def __getitem__(self, key: str) -> Any:
        try:
            return getattr(self, key)
        except AttributeError:
            raise KeyError(key) from None

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __contains__(self, key: object) -> bool:
        return key in ("success", "data", "error")

    def keys(self) -> list[str]:
        return ["success", "data", "error"]

    def __iter__(self) -> Iterator[str]:
        return iter(self.keys())

    def __eq__(self, other: object) -> bool:
        if isinstance(other, _SafeParseBase):
            return (self["success"], self["data"]) == (other["success"], other["data"]) and (
                self["error"] is other["error"]
            )
        if isinstance(other, Mapping):
            return dict(other) == {k: self[k] for k in self.keys()}
        return NotImplemented

    __hash__ = None  # type: ignore[assignment]


class SafeParseSuccess(_SafeParseBase, Generic[T]):
    """``{"success": True, "data": ...}``

    Python type checkers do not narrow a union on ``if result.success:``, so the attribute that
    only the *other* variant has is declared ``Never`` here: ``result.data`` then reads as ``T``
    and ``result.error`` as ``ZodError`` (as after narrowing in TypeScript). At runtime it is ``None``.
    """

    __slots__ = ("data",)

    success: Literal[True] = True
    if TYPE_CHECKING:

        @property
        def error(self) -> Never: ...
    else:
        error = None

    def __init__(self, data: T) -> None:
        self.data: T = data

    def __bool__(self) -> Literal[True]:
        return True

    def __repr__(self) -> str:
        return f"SafeParseResult(success=True, data={self.data!r})"


class SafeParseError(_SafeParseBase):
    """``{"success": False, "error": ZodError}``"""

    __slots__ = ("_error", "_pending")

    success: Literal[False] = False
    if TYPE_CHECKING:

        @property
        def data(self) -> Never: ...  # see SafeParseSuccess
    else:
        data = None

    def __init__(self, error: ZodError) -> None:
        self._error: ZodError | None = error
        self._pending: Callable[[], list[ZodIssue]] | None = None

    @classmethod
    def _deferred(cls, pending: Callable[[], list[ZodIssue]]) -> SafeParseError:
        """A failure whose ``ZodError`` is created on first access to ``.error`` (``pending()``
        then makes its issues). Checking ``.success`` alone creates no exception object."""
        result = object.__new__(cls)
        result._error = None
        result._pending = pending
        return result

    @property
    def error(self) -> ZodError:
        error = self._error
        if error is None:
            assert self._pending is not None
            error = self._error = ZodError._lazy(self._pending)
            self._pending = None
        return error

    @error.setter
    def error(self, value: ZodError) -> None:
        self._error, self._pending = value, None

    def __bool__(self) -> Literal[False]:
        return False

    def __repr__(self) -> str:
        return f"SafeParseResult(success=False, error={self.error!r})"


SafeParseResult = Union[SafeParseSuccess[T], SafeParseError]
"""Result of ``safeParse``: ``if result.success: result.data`` / ``else: result.error``."""


def _success(data: T) -> SafeParseSuccess[T]:
    return SafeParseSuccess(data)


def _failure(issues: list[ZodIssue]) -> SafeParseError:
    return SafeParseError(ZodError(issues))


# --------------------------------------------------------------------------- #
# Base schema
# --------------------------------------------------------------------------- #


# ``zopy._compile`` imports this module, so it is bound on first parse; a function-level
# ``from . import _compile`` costs ~0.5 µs per call.
_COMPILE: Any = None


def _load_compile() -> Any:
    global _COMPILE
    from . import _compile

    _COMPILE = _compile
    return _compile


# Python types a primitive schema outputs, for checking ``.brand(NewType(...))``.
_BRAND_BASES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "number": (int, float),
    "boolean": (bool,),
    "bigint": (int,),
}


# Contexts are never mutated, so option-less parses share one per (async_, direction).
_DEFAULT_CTX = {
    (a, d): ParseContext(async_=a, direction=d) for a in (False, True) for d in ("forward", "backward")
}


def _ctx_from_params(params: Any, kwargs: Mapping[str, Any], *, async_: bool, direction: str) -> ParseContext:
    if not params and not kwargs:
        return _DEFAULT_CTX[async_, direction]
    p = dict(params or {})
    p.update(kwargs)
    return ParseContext(
        error=p.get("error"),
        reportInput=bool(p.get("reportInput", False)),
        async_=async_,
        direction=direction,
    )


Params = Union[str, Mapping[str, Any], None]
"""Error params: ``"message"`` or ``{"error": "message" | (issue) -> message}`` (plus check options)."""

# Refinement callbacks may take ``(value)`` or ``(value, ctx)``.
RefineFn = Union[Callable[[T], object], Callable[[T, "RefinementCtx"], object]]
TransformFn = Union[Callable[[T], U], Callable[[T, "RefinementCtx"], U]]


class ZodType(Generic[Output]):
    """Base class of every schema. Subclasses implement ``_parse(payload)``.

    ``Output`` is the type returned by ``.parse()``; it is covariant so that
    ``[z.string(), z.number()]`` can be inferred as ``Sequence[ZodType[str | float]]``.
    """

    _type: str = "unknown"

    def __init__(self, **definition: Any) -> None:
        d: dict[str, Any] = {"checks": [], "error": None}
        d.update(definition)
        d["type"] = self._type
        self._def: dict[str, Any] = d

    # -- cloning ----------------------------------------------------------- #
    def _clone(self, **changes: Any) -> Self:
        new = copy.copy(self)
        new.__dict__.pop("_field_names", None)  # a clone is not bound to any z.Object field
        # The clone has a different definition: drop the compiled tree and its fast entry points.
        for key in ("_compiled", "parse", "safeParse"):
            new.__dict__.pop(key, None)
        new._def = {**self._def, **changes}
        return new

    # -- descriptor protocol: fields of ``class User(z.Object)`` ------------ #
    # ``User.name`` is the schema; ``user.name`` is the parsed value, typed as ``Output``.
    def __set_name__(self, owner: type, name: str) -> None:
        if "_field_names" not in vars(self):
            self._field_names: dict[type, str] = {}
        self._field_names[owner] = name

    def _field_for(self, instance: object) -> str | None:
        names = vars(self).get("_field_names")
        if not names:
            return None
        for klass in type(instance).__mro__:
            if klass in names:
                return names[klass]
        return None

    @overload
    def __get__(self, instance: None, owner: Any = None) -> Self: ...

    @overload
    def __get__(self, instance: Object, owner: Any = None) -> Output: ...

    @overload
    def __get__(self, instance: object, owner: Any = None) -> Self: ...

    def __get__(self, instance: Any, owner: Any = None) -> Any:
        if instance is None:
            return self
        # Fields are non-data descriptors, so this only runs when the instance has no value for the
        # field: an absent optional field, which reads as None (Zod's ``undefined``).
        from .declarative import Object

        if isinstance(instance, Object) and self._field_for(instance) is not None:
            return None
        return self

    if TYPE_CHECKING:
        # Declared for type checkers only (``user.name = "x"`` must be a ``str``). At runtime a
        # field is a *non-data* descriptor, so ``user.name`` is a plain instance-dict read: parsed
        # values live in the instance ``__dict__`` under the field name.
        def __set__(self, instance: Object, value: Output) -> None: ...  # pyright: ignore[reportGeneralTypeIssues]

    def clone(self, definition: Mapping[str, Any] | None = None) -> Self:
        return self._clone(**(definition or {}))

    @property
    def def_(self) -> dict[str, Any]:
        """The schema definition (``schema.def`` in TS; ``def`` is reserved in Python)."""
        return self._def

    @property
    def type(self) -> str:
        return self._type

    @property
    def description(self) -> str | None:
        from .registries import globalRegistry

        meta = globalRegistry.get(self)
        return meta.get("description") if meta else None

    @property
    def _optin(self) -> str | None:
        return None

    @property
    def _optout(self) -> str | None:
        return None

    # -- parsing (internal) ------------------------------------------------ #
    def _parse(self, payload: Payload) -> Payload | Awaitable[Payload]:  # pragma: no cover - abstract
        raise NotImplementedError

    def _run(self, payload: Payload) -> Payload | Awaitable[Payload]:
        result = self._parse(payload)
        checks = self._def["checks"]
        if is_awaitable(result):
            if not payload.ctx.async_:
                _close(result)
                raise ZodAsyncError()
            return self._await_then_checks(result, checks)
        return self._run_checks(result, checks)

    async def _await_then_checks(self, awaitable: Awaitable[Payload], checks: list[Check]) -> Payload:
        result = await awaitable
        out = self._run_checks(result, checks)
        if is_awaitable(out):
            out = await out
        return out

    def _run_checks(self, payload: Payload, checks: Sequence[Check]) -> Payload | Awaitable[Payload]:
        if not checks:
            return payload
        is_aborted = aborted(payload)
        for index, check in enumerate(checks):
            if check.when is not None:
                if not check.when(payload):
                    continue
            elif is_aborted:
                continue
            start = len(payload.issues)
            result = check.run(payload, self)
            if is_awaitable(result):
                if not payload.ctx.async_:
                    _close(result)
                    raise ZodAsyncError()
                return self._run_checks_async(payload, checks, index, start, is_aborted, result)
            if len(payload.issues) != start and not is_aborted:
                is_aborted = aborted(payload, start)
        return payload

    async def _run_checks_async(
        self,
        payload: Payload,
        checks: Sequence[Check],
        index: int,
        start: int,
        is_aborted: bool,
        pending: Awaitable[Any],
    ) -> Payload:
        await pending
        if len(payload.issues) != start and not is_aborted:
            is_aborted = aborted(payload, start)
        for check in checks[index + 1 :]:
            if check.when is not None:
                if not check.when(payload):
                    continue
            elif is_aborted:
                continue
            start = len(payload.issues)
            result = check.run(payload, self)
            if is_awaitable(result):
                await result
            if len(payload.issues) != start and not is_aborted:
                is_aborted = aborted(payload, start)
        return payload

    # -- parsing (public) -------------------------------------------------- #
    def _parse_sync(self, data: Any, ctx: ParseContext) -> tuple[Any, ZodError | None]:
        _compile = _COMPILE or _load_compile()
        if _compile._engine_name == "rust":
            try:
                compiled = self.__dict__["_compiled"]
            except KeyError:
                compiled = self._compiled = _compile.compile_schema(self)
                _compile.install_fast(self, compiled)
            return compiled.run(data, ctx)
        result = self._run(Payload(data, [], ctx, []))
        if is_awaitable(result):
            raise ZodAsyncError()
        return result.value, (ZodError(_strip_internal(result.issues)) if result.issues else None)

    async def _parse_async(self, data: Any, ctx: ParseContext) -> Payload:
        result = self._run(Payload(data, [], ctx, []))
        if is_awaitable(result):
            result = await result
        return result

    def parse(self, data: Any, params: Mapping[str, Any] | None = None, **kwargs: Any) -> Output:
        ctx = _ctx_from_params(params, kwargs, async_=False, direction="forward")
        value, error = self._parse_sync(data, ctx)
        if error is not None:
            raise error
        return value

    def safeParse(  # noqa: N802
        self, data: Any, params: Mapping[str, Any] | None = None, **kwargs: Any
    ) -> SafeParseResult[Output]:
        ctx = _ctx_from_params(params, kwargs, async_=False, direction="forward")
        value, error = self._parse_sync(data, ctx)
        if error is not None:
            return SafeParseError(error)
        return _success(value)

    async def parseAsync(  # noqa: N802
        self, data: Any, params: Mapping[str, Any] | None = None, **kwargs: Any
    ) -> Output:
        ctx = _ctx_from_params(params, kwargs, async_=True, direction="forward")
        payload = await self._parse_async(data, ctx)
        if payload.issues:
            raise ZodError(_strip_internal(payload.issues))
        return payload.value

    async def safeParseAsync(  # noqa: N802
        self, data: Any, params: Mapping[str, Any] | None = None, **kwargs: Any
    ) -> SafeParseResult[Output]:
        ctx = _ctx_from_params(params, kwargs, async_=True, direction="forward")
        payload = await self._parse_async(data, ctx)
        if payload.issues:
            return _failure(_strip_internal(payload.issues))
        return _success(payload.value)

    # snake_case conveniences
    safe_parse = safeParse
    parse_async = parseAsync
    safe_parse_async = safeParseAsync
    spa = safeParseAsync

    # codec direction (``z.encode`` / ``z.decode``)
    def decode(self, data: Any, params: Mapping[str, Any] | None = None, **kwargs: Any) -> Output:
        return self.parse(data, params, **kwargs)

    def encode(self, data: Any, params: Mapping[str, Any] | None = None, **kwargs: Any) -> Any:
        ctx = _ctx_from_params(params, kwargs, async_=False, direction="backward")
        value, error = self._parse_sync(data, ctx)
        if error is not None:
            raise error
        return value

    def safeDecode(  # noqa: N802
        self, data: Any, params: Mapping[str, Any] | None = None, **kwargs: Any
    ) -> SafeParseResult[Output]:
        return self.safeParse(data, params, **kwargs)

    def safeEncode(  # noqa: N802
        self, data: Any, params: Mapping[str, Any] | None = None, **kwargs: Any
    ) -> SafeParseResult[Any]:
        ctx = _ctx_from_params(params, kwargs, async_=False, direction="backward")
        value, error = self._parse_sync(data, ctx)
        if error is not None:
            return SafeParseError(error)
        return _success(value)

    async def decodeAsync(  # noqa: N802
        self, data: Any, params: Mapping[str, Any] | None = None, **kwargs: Any
    ) -> Output:
        return await self.parseAsync(data, params, **kwargs)

    async def encodeAsync(  # noqa: N802
        self, data: Any, params: Mapping[str, Any] | None = None, **kwargs: Any
    ) -> Any:
        ctx = _ctx_from_params(params, kwargs, async_=True, direction="backward")
        payload = await self._parse_async(data, ctx)
        if payload.issues:
            raise ZodError(_strip_internal(payload.issues))
        return payload.value

    async def safeDecodeAsync(  # noqa: N802
        self, data: Any, params: Mapping[str, Any] | None = None, **kwargs: Any
    ) -> SafeParseResult[Output]:
        return await self.safeParseAsync(data, params, **kwargs)

    async def safeEncodeAsync(  # noqa: N802
        self, data: Any, params: Mapping[str, Any] | None = None, **kwargs: Any
    ) -> SafeParseResult[Any]:
        ctx = _ctx_from_params(params, kwargs, async_=True, direction="backward")
        payload = await self._parse_async(data, ctx)
        if payload.issues:
            return _failure(_strip_internal(payload.issues))
        return _success(payload.value)

    # -- checks / refinements --------------------------------------------- #
    def _add_check(self, check: Check) -> Self:
        return self._clone(checks=[*self._def["checks"], check])

    def check(self, *checks: Check | ZodType[Any] | Callable[[RefinementCtx], object]) -> Self:
        """Attach raw checks: ``Check`` objects or ``fn(ctx)`` callables (Zod 4 ``.check()``)."""
        schema = self
        for ch in checks:
            if isinstance(ch, Check):
                schema = schema._add_check(ch)
            elif isinstance(ch, ZodType):
                schema = schema._add_check(_schema_as_check(ch))
            elif callable(ch):
                schema = schema._add_check(custom_check(ch))
            else:
                raise TypeError(f"Invalid check: {ch!r}")
        return schema

    def refine(self, fn: RefineFn[Output], params: Params = None, **kwargs: Any) -> Self:  # pyright: ignore[reportGeneralTypeIssues]
        return self._add_check(refine_check(fn, normalize_params(params, kwargs)))

    def superRefine(  # noqa: N802
        self,
        fn: Callable[[Output, RefinementCtx], object],  # pyright: ignore[reportGeneralTypeIssues]
        params: Params = None,
        **kwargs: Any,
    ) -> Self:
        return self._add_check(super_refine_check(fn, normalize_params(params, kwargs)))

    super_refine = superRefine

    def overwrite(self, fn: Callable[[Output], Output]) -> Self:  # pyright: ignore[reportGeneralTypeIssues]
        return self._add_check(overwrite_check(fn))

    # -- wrappers (implemented in schemas.py, imported lazily) ------------- #
    def optional(self: ZodType[T]) -> ZodOptional[T]:
        from .schemas import ZodOptional

        return ZodOptional(innerType=self)

    def exactOptional(self: ZodType[T]) -> ZodExactOptional[T]:  # noqa: N802
        from .schemas import ZodExactOptional

        return ZodExactOptional(innerType=self)

    exact_optional = exactOptional

    def nullable(self: ZodType[T]) -> ZodNullable[T]:
        from .schemas import ZodNullable

        return ZodNullable(innerType=self)

    def nullish(self: ZodType[T]) -> ZodOptional[T | None]:
        return self.nullable().optional()

    def nonoptional(self: ZodType[T | None], params: Params = None, **kwargs: Any) -> ZodNonOptional[T]:
        from .schemas import ZodNonOptional

        return ZodNonOptional(innerType=self, **normalize_params(params, kwargs))

    def default(self: ZodType[T | None], value: T | Callable[[], T]) -> ZodDefault[T]:
        from .schemas import ZodDefault

        return ZodDefault(innerType=self, defaultValue=value)

    _default = default

    def prefault(self: ZodType[T], value: Any) -> ZodPrefault[T]:
        from .schemas import ZodPrefault

        return ZodPrefault(innerType=self, defaultValue=value)

    def catch(self: ZodType[T], value: T | Callable[[Any], T]) -> ZodCatch[T]:
        from .schemas import ZodCatch

        return ZodCatch(innerType=self, catchValue=value)

    def array(self: ZodType[T]) -> ZodArray[T]:
        from .schemas import ZodArray

        return ZodArray(element=self)

    def or_(self: ZodType[T], other: ZodType[U]) -> ZodUnion[T | U]:
        from .schemas import ZodUnion

        return ZodUnion(options=[self, other])

    def __or__(self: ZodType[T], other: ZodType[U]) -> ZodUnion[T | U]:
        return self.or_(other)

    def transform(self: ZodType[T], fn: TransformFn[T, U]) -> ZodPipe[U]:
        from .schemas import ZodPipe, ZodTransform

        return ZodPipe(in_=self, out=ZodTransform(transform=fn))

    def pipe(self, target: ZodType[U]) -> ZodPipe[U]:
        from .schemas import ZodPipe

        return ZodPipe(in_=self, out=target)

    # The output is frozen (shallowly, like Zod's Object.freeze), and typed as the frozen type:
    # a list becomes a tuple, a dict a read-only Mapping (mappingproxy), a set a frozenset.
    # Schemas with an `Any` output come first: `Any` would otherwise match the list overload.
    @overload
    def readonly(self: ZodAny) -> ZodReadonly[Any]: ...

    @overload
    def readonly(self: ZodCustom[T]) -> ZodReadonly[T]: ...

    @overload
    def readonly(self: ZodType[list[T]]) -> ZodReadonly[tuple[T, ...]]: ...

    @overload
    def readonly(self: ZodType[dict[K, V]]) -> ZodReadonly[Mapping[K, V]]: ...

    @overload
    def readonly(self: ZodType[set[T]]) -> ZodReadonly[frozenset[T]]: ...

    @overload
    def readonly(self: ZodType[T]) -> ZodReadonly[T]: ...

    def readonly(self) -> ZodReadonly[Any]:
        from .schemas import ZodReadonly

        return ZodReadonly(innerType=self)

    @overload
    def brand(self, brand: str | None = None) -> Self: ...

    @overload
    def brand(self, brand: Callable[[Any], Any]) -> ZodType[Any]: ...  # a typing.NewType

    def brand(self, brand: Any = None) -> Any:
        """Zod's ``.brand()``. Static-only, as in Zod: the parsed value is unchanged.

        ``.brand("UserId")`` keeps the type. With a ``typing.NewType`` the branded type comes from
        the variable annotation (type checkers do not infer it from a NewType argument)::

            UserId = NewType("UserId", str)
            UserIdSchema: z.ZodType[UserId] = z.uuid().brand(UserId)
            UserIdSchema.parse(raw)  # UserId; a plain str or another NewType is a type error
        """
        if brand is not None and not isinstance(brand, (str, NewType)):
            raise TypeError(
                f"brand() takes a label or a typing.NewType, not {brand!r}; "
                "e.g. UserId = NewType('UserId', str) and .brand(UserId)"
            )
        if isinstance(brand, NewType):
            # The annotation cannot be checked against the schema statically; catch the obvious
            # mismatch (`z.int().brand(NewType("UserId", str))`) when the schema is built.
            base = _BRAND_BASES.get(self._type)
            supertype = brand.__supertype__
            if base and isinstance(supertype, type) and not issubclass(supertype, base):
                raise TypeError(
                    f"brand({brand.__name__}): {brand.__name__} is a NewType of {supertype.__name__}, "
                    f"but this {self._type} schema outputs {' | '.join(b.__name__ for b in base)}"
                )
        return self._clone(brand=brand)

    @overload
    def meta(self) -> dict[str, Any] | None: ...

    @overload
    def meta(self, meta: Mapping[str, Any], **kwargs: Any) -> Self: ...

    def meta(self, meta: Mapping[str, Any] | None = None, **kwargs: Any) -> Any:
        from .registries import globalRegistry

        if meta is None and not kwargs:
            return globalRegistry.get(self)
        new = self._clone()
        merged = dict(globalRegistry.get(self) or {})
        merged.update(meta or {})
        merged.update(kwargs)
        globalRegistry.add(new, merged)
        return new

    @overload
    def openapi(self, metadata: Mapping[str, Any], /) -> Self: ...

    @overload
    def openapi(self, refId: str, metadata: Mapping[str, Any] | None = None, /) -> Self: ...  # noqa: N803

    def openapi(self, first: Any, second: Mapping[str, Any] | None = None, /) -> Any:
        """``@hono/zod-openapi``'s ``.openapi()``: OpenAPI metadata, and with a name a component.

        ``.openapi({"description": ..., "example": ...})`` adds metadata (copied into the generated
        schema); ``.openapi("Todo")`` names the schema, so OpenAPI documents emit it once under
        ``components.schemas.Todo`` and ``$ref`` it. ``{"param": {"name": ..., "in": ...}}`` is
        parameter metadata and stays out of the schema itself.
        """
        from .registries import openapiParamRegistry

        meta = dict(second or {}) if isinstance(first, str) else dict(first)
        if isinstance(first, str):
            meta["id"] = first
        param = {**(openapiParamRegistry.get(self) or {}), **meta.pop("param", {})}
        new = self.meta(meta)
        if param:
            openapiParamRegistry.add(new, param)
        return new

    def register(self, registry: Any, meta: Mapping[str, Any] | None = None, **kwargs: Any) -> Self:
        merged = dict(meta or {})
        merged.update(kwargs)
        registry.add(self, merged)
        return self

    # -- introspection ----------------------------------------------------- #
    def isOptional(self) -> bool:  # noqa: N802
        return bool(self.safeParse(None).success)

    def isNullable(self) -> bool:  # noqa: N802
        return bool(self.safeParse(None).success)

    def unwrap(self) -> ZodType[Any]:
        return self

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    # Python ``in`` convenience: ``value in schema``
    def __contains__(self, value: Any) -> bool:
        return bool(self.safeParse(value).success)


# ``.or`` is a keyword in Python; expose it anyway for getattr().
setattr(ZodType, "or", ZodType.or_)


# --------------------------------------------------------------------------- #
# Built-in check factories (used by ``.refine`` etc. and exported as ``z.refine``)
# --------------------------------------------------------------------------- #


def _inspect_takes_ctx(fn: Callable[..., Any]) -> bool:
    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return False
    required = [
        p for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) and p.default is p.empty
    ]
    return len(required) >= 2


_cached_takes_ctx = functools.lru_cache(maxsize=4096)(_inspect_takes_ctx)


def _takes_ctx(fn: Callable[..., Any]) -> bool:
    """Whether a refine/transform callback is ``(value, ctx)`` rather than ``(value)``.

    Cached per callable: ``inspect.signature`` cost more than the rest of a parse.
    """
    try:
        return _cached_takes_ctx(fn)
    except TypeError:  # unhashable callable
        return _inspect_takes_ctx(fn)


def _call_refine(fn: Callable[..., Any], value: Any, ctx: RefinementCtx) -> Any:
    return fn(value, ctx) if _takes_ctx(fn) else fn(value)


def refine_check(fn: Callable[..., Any], params: Mapping[str, Any] | None = None) -> Check:
    params = dict(params or {})
    abort = bool(params.pop("abort", False))
    error = params.pop("error", None)
    path = params.pop("path", None)
    when = params.pop("when", None)
    extra_params = params.pop("params", None)

    def run(payload: Payload, check: Check, inst: Any) -> Any:
        ctx = RefinementCtx(payload, check, inst)
        result = _call_refine(fn, payload.value, ctx)

        def finish(res: Any) -> None:
            if not res:
                raw: dict[str, Any] = {"code": "custom", "input": payload.value}
                if path:
                    raw["path"] = list(path)
                if extra_params is not None:
                    raw["params"] = extra_params
                for key, value in params.items():
                    raw.setdefault(key, value)
                check.issue(payload, raw, inst)

        if is_awaitable(result):
            if not payload.ctx.async_:
                _close(result)
                raise ZodAsyncError()

            async def wait() -> None:
                finish(await result)

            return wait()
        finish(result)
        return None

    return Check("custom", run, error=error, abort=abort, when=when, params={"path": path})


def super_refine_check(
    fn: Callable[[Any, RefinementCtx], Any], params: Mapping[str, Any] | None = None
) -> Check:
    params = dict(params or {})
    abort = bool(params.pop("abort", False))

    def run(payload: Payload, check: Check, inst: Any) -> Any:
        ctx = RefinementCtx(payload, check, inst)
        return fn(payload.value, ctx)

    return Check("custom", run, error=params.get("error"), abort=abort, when=params.get("when"))


def custom_check(fn: Callable[[RefinementCtx], Any], params: Mapping[str, Any] | None = None) -> Check:
    params = dict(params or {})

    def run(payload: Payload, check: Check, inst: Any) -> Any:
        ctx = RefinementCtx(payload, check, inst)
        return fn(ctx)

    return Check(
        "custom",
        run,
        error=params.get("error"),
        abort=bool(params.get("abort", False)),
        when=params.get("when"),
    )


def overwrite_check(fn: Callable[[Any], Any], op: str | None = None, **params: Any) -> Check:
    def run(payload: Payload, check: Check, inst: Any) -> None:
        payload.value = fn(payload.value)

    return Check("overwrite", run, params={"op": op, **params})


def _schema_as_check(schema: ZodType) -> Check:
    def run(payload: Payload, check: Check, inst: Any) -> Any:
        result = schema._run(payload)
        if is_awaitable(result):
            return result
        return None

    return Check("schema", run)


def run_sync_or_async(coro_fn: Callable[[], Coroutine[Any, Any, Any]]) -> Any:
    """Utility for tests/examples: run a coroutine from sync code."""
    return asyncio.run(coro_fn())


__all__ = [
    "INVALID",
    "Check",
    "ParseContext",
    "Payload",
    "RefinementCtx",
    "SafeParseError",
    "SafeParseResult",
    "SafeParseSuccess",
    "ZodType",
    "aborted",
    "custom_check",
    "overwrite_check",
    "refine_check",
    "super_refine_check",
]
