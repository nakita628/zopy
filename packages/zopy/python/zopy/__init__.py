"""Zod for Python - the Zod 4 API (https://zod.dev).

from zopy import z

class User(z.Object):
    name = z.string().min(1)
    age = z.int().positive()
    email = z.email().optional()

User.parse({"name": "Ada", "age": 36})
result = User.safeParse({"name": ""})
if not result.success:
    print(z.prettifyError(result.error))
"""

from __future__ import annotations

import builtins as _b
import enum as _enum
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal, LiteralString, TypeVar, overload

from . import core as core
from . import regexes as regexes
from ._util import INVALID as NEVER
from ._util import normalize_params as _normalize_params
from .core import (
    Check,
    Params,
    ParseContext,
    Payload,
    RefinementCtx,
    SafeParseError,
    SafeParseResult,
    SafeParseSuccess,
    ZodType,
    custom_check,
    overwrite_check,
    refine_check,
    super_refine_check,
)
from .declarative import LooseObject, Object, ObjectMeta, StrictObject
from .errors import (
    ZodAsyncError,
    ZodEncodeError,
    ZodError,
    ZodIssue,
    ZodIssueCode,
    ZodRealError,
    config,
    flattenError,
    prettifyError,
    toDotPath,
    treeifyError,
)
from .json_schema import toJSONSchema
from .locales import en as _en
from .registries import ZodRegistry, globalRegistry, registry
from .schemas import (
    ZodAny,
    ZodArray,
    ZodBigInt,
    ZodBoolean,
    ZodCatch,
    ZodCodec,
    ZodCustom,
    ZodDate,
    ZodDefault,
    ZodDiscriminatedUnion,
    ZodEnum,
    ZodExactOptional,
    ZodFile,
    ZodFunction,
    ZodInstanceOf,
    ZodInt,
    ZodLazy,
    ZodLiteral,
    ZodMap,
    ZodNaN,
    ZodNever,
    ZodNonOptional,
    ZodNull,
    ZodNullable,
    ZodNumber,
    ZodObject,
    ZodOptional,
    ZodPipe,
    ZodPrefault,
    ZodReadonly,
    ZodRecord,
    ZodSet,
    ZodString,
    ZodStringBool,
    ZodSymbol,
    ZodTransform,
    ZodTuple,
    ZodUndefined,
    ZodUnion,
    ZodUnknown,
    ZodVoid,
    ZodXor,
    _enum_entries,
    invert_codec,
    properties_checks,
    property_check,
)

__version__ = "0.1.1"

_T = TypeVar("_T")
_U = TypeVar("_U")
_K = TypeVar("_K")
_V = TypeVar("_V")
_A = TypeVar("_A")
_B = TypeVar("_B")
_C = TypeVar("_C")
_D = TypeVar("_D")
_E = TypeVar("_E")
_F = TypeVar("_F")
_R = TypeVar("_R")
_EnumT = TypeVar("_EnumT", bound=_enum.Enum)
_S = TypeVar("_S", bound=LiteralString)
_O = TypeVar("_O", bound=Object)

# --------------------------------------------------------------------------- #
# Primitive factories
# --------------------------------------------------------------------------- #


def _p(params: Any, kwargs: Mapping[str, Any]) -> dict[str, Any]:
    return _normalize_params(params, kwargs)


def string(params: Params = None, **kwargs: Any) -> ZodString:
    return ZodString(**_p(params, kwargs))


def number(params: Params = None, **kwargs: Any) -> ZodNumber:
    return ZodNumber(**_p(params, kwargs))


def bigint(params: Params = None, **kwargs: Any) -> ZodBigInt:
    return ZodBigInt(**_p(params, kwargs))


def boolean(params: Params = None, **kwargs: Any) -> ZodBoolean:
    return ZodBoolean(**_p(params, kwargs))


def date(params: Params = None, **kwargs: Any) -> ZodDate:
    return ZodDate(**_p(params, kwargs))


def symbol(params: Params = None, **kwargs: Any) -> ZodSymbol:
    return ZodSymbol(**_p(params, kwargs))


def undefined(params: Params = None, **kwargs: Any) -> ZodUndefined:
    return ZodUndefined(**_p(params, kwargs))


def null(params: Params = None, **kwargs: Any) -> ZodNull:
    return ZodNull(**_p(params, kwargs))


def void(params: Params = None, **kwargs: Any) -> ZodVoid:
    return ZodVoid(**_p(params, kwargs))


def any(params: Params = None, **kwargs: Any) -> ZodAny:  # noqa: A001
    return ZodAny(**_p(params, kwargs))


def unknown(params: Params = None, **kwargs: Any) -> ZodUnknown:
    return ZodUnknown(**_p(params, kwargs))


def never(params: Params = None, **kwargs: Any) -> ZodNever:
    return ZodNever(**_p(params, kwargs))


def nan(params: Params = None, **kwargs: Any) -> ZodNaN:
    return ZodNaN(**_p(params, kwargs))


def file(params: Params = None, **kwargs: Any) -> ZodFile:
    return ZodFile(**_p(params, kwargs))


# -- numeric formats ---------------------------------------------------------- #


def int(params: Params = None, **kwargs: Any) -> ZodInt:  # noqa: A001
    return ZodInt(format="safeint", **_p(params, kwargs))


def _ranged_int(fmt: str, lo: Any, hi: Any, params: Any, kwargs: Mapping[str, Any]) -> ZodInt:
    return ZodInt(format=fmt, **_p(params, kwargs)).gte(lo).lte(hi)


def int32(params: Params = None, **kwargs: Any) -> ZodInt:
    return _ranged_int("int32", -(2**31), 2**31 - 1, params, kwargs)


def uint32(params: Params = None, **kwargs: Any) -> ZodInt:
    return _ranged_int("uint32", 0, 2**32 - 1, params, kwargs)


def int64(params: Params = None, **kwargs: Any) -> ZodBigInt:
    return ZodBigInt(format="int64", **_p(params, kwargs)).gte(-(2**63)).lte(2**63 - 1)


def uint64(params: Params = None, **kwargs: Any) -> ZodBigInt:
    return ZodBigInt(format="uint64", **_p(params, kwargs)).gte(0).lte(2**64 - 1)


def float32(params: Params = None, **kwargs: Any) -> ZodNumber:
    return (
        ZodNumber(format="float32", **_p(params, kwargs))
        .gte(-3.4028234663852886e38)
        .lte(3.4028234663852886e38)
    )


def float64(params: Params = None, **kwargs: Any) -> ZodNumber:
    return ZodNumber(format="float64", **_p(params, kwargs))


# -- string formats (top-level, Zod 4 style) ---------------------------------- #


def _fmt(name: str) -> Callable[..., ZodString]:
    def factory(params: Params = None, **kwargs: Any) -> ZodString:
        p = _p(params, kwargs)
        schema_params = {k: v for k, v in p.items() if k in ("error",)}
        return getattr(ZodString(**schema_params), name)(p)

    factory.__name__ = name
    return factory


def email(params: Params = None, **kwargs: Any) -> ZodString:
    return ZodString()._email(params, **kwargs)


def url(params: Params = None, **kwargs: Any) -> ZodString:
    return ZodString()._url(params, **kwargs)


def httpUrl(params: Params = None, **kwargs: Any) -> ZodString:
    return ZodString()._httpUrl(params, **kwargs)


def emoji(params: Params = None, **kwargs: Any) -> ZodString:
    return ZodString()._emoji(params, **kwargs)


def uuid(params: Params = None, **kwargs: Any) -> ZodString:
    return ZodString()._uuid(params, **kwargs)


def uuidv4(params: Params = None, **kwargs: Any) -> ZodString:
    return ZodString()._uuidv4(params, **kwargs)


def uuidv6(params: Params = None, **kwargs: Any) -> ZodString:
    return ZodString()._uuidv6(params, **kwargs)


def uuidv7(params: Params = None, **kwargs: Any) -> ZodString:
    return ZodString()._uuidv7(params, **kwargs)


def guid(params: Params = None, **kwargs: Any) -> ZodString:
    return ZodString()._guid(params, **kwargs)


def nanoid(params: Params = None, **kwargs: Any) -> ZodString:
    return ZodString()._nanoid(params, **kwargs)


def cuid(params: Params = None, **kwargs: Any) -> ZodString:
    return ZodString()._cuid(params, **kwargs)


def cuid2(params: Params = None, **kwargs: Any) -> ZodString:
    return ZodString()._cuid2(params, **kwargs)


def ulid(params: Params = None, **kwargs: Any) -> ZodString:
    return ZodString()._ulid(params, **kwargs)


def xid(params: Params = None, **kwargs: Any) -> ZodString:
    return ZodString()._xid(params, **kwargs)


def ksuid(params: Params = None, **kwargs: Any) -> ZodString:
    return ZodString()._ksuid(params, **kwargs)


def base64(params: Params = None, **kwargs: Any) -> ZodString:
    return ZodString()._base64(params, **kwargs)


def base64url(params: Params = None, **kwargs: Any) -> ZodString:
    return ZodString()._base64url(params, **kwargs)


def hex(params: Params = None, **kwargs: Any) -> ZodString:  # noqa: A001
    return ZodString()._hex(params, **kwargs)


def hostname(params: Params = None, **kwargs: Any) -> ZodString:
    return ZodString()._hostname(params, **kwargs)


def e164(params: Params = None, **kwargs: Any) -> ZodString:
    return ZodString()._e164(params, **kwargs)


def jwt(params: Params = None, **kwargs: Any) -> ZodString:
    return ZodString()._jwt(params, **kwargs)


def ipv4(params: Params = None, **kwargs: Any) -> ZodString:
    return ZodString()._ipv4(params, **kwargs)


def ipv6(params: Params = None, **kwargs: Any) -> ZodString:
    return ZodString()._ipv6(params, **kwargs)


def cidrv4(params: Params = None, **kwargs: Any) -> ZodString:
    return ZodString()._cidrv4(params, **kwargs)


def cidrv6(params: Params = None, **kwargs: Any) -> ZodString:
    return ZodString()._cidrv6(params, **kwargs)


def hash(alg: str, params: Params = None, **kwargs: Any) -> ZodString:  # noqa: A001
    return ZodString()._hash(alg, params, **kwargs)


def mac(params: Params = None, **kwargs: Any) -> ZodString:
    return ZodString()._mac(params, **kwargs)


def creditCard(params: Params = None, **kwargs: Any) -> ZodString:
    return ZodString()._creditCard(params, **kwargs)


def currencyCode(params: Params = None, **kwargs: Any) -> ZodString:
    return ZodString()._currencyCode(params, **kwargs)


def iban(params: Params = None, **kwargs: Any) -> ZodString:
    return ZodString()._iban(params, **kwargs)


def stringFormat(name: str, check: Any, params: Params = None, **kwargs: Any) -> ZodString:
    return ZodString()._stringFormat(name, check, params, **kwargs)


class _ISO:
    @staticmethod
    def date(params: Params = None, **kwargs: Any) -> ZodString:
        return ZodString()._date(params, **kwargs)

    @staticmethod
    def time(params: Params = None, **kwargs: Any) -> ZodString:
        return ZodString()._time(params, **kwargs)

    @staticmethod
    def datetime(params: Params = None, **kwargs: Any) -> ZodString:
        return ZodString()._datetime(params, **kwargs)

    @staticmethod
    def duration(params: Params = None, **kwargs: Any) -> ZodString:
        return ZodString()._duration(params, **kwargs)


iso = _ISO()


def stringbool(params: Params = None, **kwargs: Any) -> ZodStringBool:
    p = _p(params, kwargs)
    truthy = [v.lower() for v in p.pop("truthy", ["true", "1", "yes", "on", "y", "enabled"])]
    falsy = [v.lower() for v in p.pop("falsy", ["false", "0", "no", "off", "n", "disabled"])]
    case = p.pop("case", "insensitive")
    return ZodStringBool(truthy=truthy, falsy=falsy, case=case, **p)


# --------------------------------------------------------------------------- #
# Coercion
# --------------------------------------------------------------------------- #


class _Coerce:
    @staticmethod
    def string(params: Params = None, **kwargs: Any) -> ZodString:
        return ZodString(coerce=True, **_p(params, kwargs))

    @staticmethod
    def number(params: Params = None, **kwargs: Any) -> ZodNumber:
        return ZodNumber(coerce=True, **_p(params, kwargs))

    @staticmethod
    def boolean(params: Params = None, **kwargs: Any) -> ZodBoolean:
        return ZodBoolean(coerce=True, **_p(params, kwargs))

    @staticmethod
    def bigint(params: Params = None, **kwargs: Any) -> ZodBigInt:
        return ZodBigInt(coerce=True, **_p(params, kwargs))

    @staticmethod
    def date(params: Params = None, **kwargs: Any) -> ZodDate:
        return ZodDate(coerce=True, **_p(params, kwargs))


coerce = _Coerce()

# --------------------------------------------------------------------------- #
# Literals / enums
# --------------------------------------------------------------------------- #


@overload
def literal(value: _S, params: Params = None, **kwargs: Any) -> ZodLiteral[_S]: ...


@overload
def literal(
    value: Sequence[_T] | _b.set[_T] | _b.frozenset[_T], params: Params = None, **kwargs: Any
) -> ZodLiteral[_T]: ...


@overload
def literal(value: _T, params: Params = None, **kwargs: Any) -> ZodLiteral[_T]: ...


def literal(value: Any, params: Params = None, **kwargs: Any) -> ZodLiteral[Any]:
    values = _b.list(value) if isinstance(value, (_b.list, _b.tuple, _b.set, _b.frozenset)) else [value]
    return ZodLiteral(values=values, **_p(params, kwargs))


@overload
def enum(values: _b.type[_EnumT], params: Params = None, **kwargs: Any) -> ZodEnum[_EnumT]: ...


@overload
def enum(values: Mapping[str, _T], params: Params = None, **kwargs: Any) -> ZodEnum[_T]: ...


# Values are a tuple so the type checker keeps the literals: ``z.enum(("a", "b"))`` -> ``Literal["a", "b"]``.
@overload
def enum(values: _b.tuple[_S, ...], params: Params = None, **kwargs: Any) -> ZodEnum[_S]: ...


def enum(values: Any, params: Params = None, **kwargs: Any) -> ZodEnum[Any]:
    if isinstance(values, _b.list):
        raise TypeError('z.enum takes a tuple, an Enum class or a mapping, e.g. z.enum(("a", "b"))')
    return ZodEnum(entries=_enum_entries(values), **_p(params, kwargs))


# --------------------------------------------------------------------------- #
# Composites
# --------------------------------------------------------------------------- #


@overload
def array(element: _b.type[_O], params: Params = None, **kwargs: Any) -> ZodArray[_O]: ...


@overload
def array(element: ZodType[_T], params: Params = None, **kwargs: Any) -> ZodArray[_T]: ...


def array(element: Any, params: Params = None, **kwargs: Any) -> ZodArray[Any]:
    return ZodArray(element=element, **_p(params, kwargs))


# Items are schemas or ``class X(z.Object)`` classes, passed as a tuple so each position keeps its
# type: ``z.tuple((z.string(), User))`` -> ``tuple[str, User]``; ``rest`` adds ``*tuple[R, ...]``.
@overload
def tuple(  # noqa: A001
    items: _b.tuple[ZodType[_A] | _b.type[_A]],
    rest: None = None,
    params: Params = None,
    **kwargs: Any,
) -> ZodTuple[_b.tuple[_A]]: ...


@overload
def tuple(  # noqa: A001
    items: _b.tuple[ZodType[_A] | _b.type[_A]],
    rest: ZodType[_R] | _b.type[_R],
    params: Params = None,
    **kwargs: Any,
) -> ZodTuple[_b.tuple[_A, *_b.tuple[_R, ...]]]: ...


@overload
def tuple(  # noqa: A001
    items: _b.tuple[ZodType[_A] | _b.type[_A], ZodType[_B] | _b.type[_B]],
    rest: None = None,
    params: Params = None,
    **kwargs: Any,
) -> ZodTuple[_b.tuple[_A, _B]]: ...


@overload
def tuple(  # noqa: A001
    items: _b.tuple[ZodType[_A] | _b.type[_A], ZodType[_B] | _b.type[_B]],
    rest: ZodType[_R] | _b.type[_R],
    params: Params = None,
    **kwargs: Any,
) -> ZodTuple[_b.tuple[_A, _B, *_b.tuple[_R, ...]]]: ...


@overload
def tuple(  # noqa: A001
    items: _b.tuple[ZodType[_A] | _b.type[_A], ZodType[_B] | _b.type[_B], ZodType[_C] | _b.type[_C]],
    rest: None = None,
    params: Params = None,
    **kwargs: Any,
) -> ZodTuple[_b.tuple[_A, _B, _C]]: ...


@overload
def tuple(  # noqa: A001
    items: _b.tuple[ZodType[_A] | _b.type[_A], ZodType[_B] | _b.type[_B], ZodType[_C] | _b.type[_C]],
    rest: ZodType[_R] | _b.type[_R],
    params: Params = None,
    **kwargs: Any,
) -> ZodTuple[_b.tuple[_A, _B, _C, *_b.tuple[_R, ...]]]: ...


@overload
def tuple(  # noqa: A001
    items: _b.tuple[
        ZodType[_A] | _b.type[_A],
        ZodType[_B] | _b.type[_B],
        ZodType[_C] | _b.type[_C],
        ZodType[_D] | _b.type[_D],
    ],
    rest: None = None,
    params: Params = None,
    **kwargs: Any,
) -> ZodTuple[_b.tuple[_A, _B, _C, _D]]: ...


@overload
def tuple(  # noqa: A001
    items: _b.tuple[
        ZodType[_A] | _b.type[_A],
        ZodType[_B] | _b.type[_B],
        ZodType[_C] | _b.type[_C],
        ZodType[_D] | _b.type[_D],
    ],
    rest: ZodType[_R] | _b.type[_R],
    params: Params = None,
    **kwargs: Any,
) -> ZodTuple[_b.tuple[_A, _B, _C, _D, *_b.tuple[_R, ...]]]: ...


@overload
def tuple(  # noqa: A001
    items: _b.tuple[
        ZodType[_A] | _b.type[_A],
        ZodType[_B] | _b.type[_B],
        ZodType[_C] | _b.type[_C],
        ZodType[_D] | _b.type[_D],
        ZodType[_E] | _b.type[_E],
    ],
    rest: None = None,
    params: Params = None,
    **kwargs: Any,
) -> ZodTuple[_b.tuple[_A, _B, _C, _D, _E]]: ...


@overload
def tuple(  # noqa: A001
    items: _b.tuple[
        ZodType[_A] | _b.type[_A],
        ZodType[_B] | _b.type[_B],
        ZodType[_C] | _b.type[_C],
        ZodType[_D] | _b.type[_D],
        ZodType[_E] | _b.type[_E],
    ],
    rest: ZodType[_R] | _b.type[_R],
    params: Params = None,
    **kwargs: Any,
) -> ZodTuple[_b.tuple[_A, _B, _C, _D, _E, *_b.tuple[_R, ...]]]: ...


@overload
def tuple(  # noqa: A001
    items: _b.tuple[
        ZodType[_A] | _b.type[_A],
        ZodType[_B] | _b.type[_B],
        ZodType[_C] | _b.type[_C],
        ZodType[_D] | _b.type[_D],
        ZodType[_E] | _b.type[_E],
        ZodType[_F] | _b.type[_F],
    ],
    rest: None = None,
    params: Params = None,
    **kwargs: Any,
) -> ZodTuple[_b.tuple[_A, _B, _C, _D, _E, _F]]: ...


@overload
def tuple(  # noqa: A001
    items: _b.tuple[
        ZodType[_A] | _b.type[_A],
        ZodType[_B] | _b.type[_B],
        ZodType[_C] | _b.type[_C],
        ZodType[_D] | _b.type[_D],
        ZodType[_E] | _b.type[_E],
        ZodType[_F] | _b.type[_F],
    ],
    rest: ZodType[_R] | _b.type[_R],
    params: Params = None,
    **kwargs: Any,
) -> ZodTuple[_b.tuple[_A, _B, _C, _D, _E, _F, *_b.tuple[_R, ...]]]: ...


def tuple(  # noqa: A001
    items: _b.tuple[Any, ...], rest: Any = None, params: Params = None, **kwargs: Any
) -> ZodTuple[Any]:
    if not isinstance(items, _b.tuple):
        raise TypeError("z.tuple takes a tuple of schemas, e.g. z.tuple((z.string(), z.int()))")
    if isinstance(rest, (str, Mapping)) and params is None:
        params, rest = rest, None
    return ZodTuple(items=_b.list(items), rest=rest, **_p(params, kwargs))


@overload
def record(
    keyType: ZodType[_K], valueType: _b.type[_O], params: Params = None, **kwargs: Any
) -> ZodRecord[_K, _O]: ...


@overload
def record(
    keyType: ZodType[_K], valueType: ZodType[_V], params: Params = None, **kwargs: Any
) -> ZodRecord[_K, _V]: ...


def record(
    keyType: ZodType[Any], valueType: ZodType[Any], params: Params = None, **kwargs: Any
) -> ZodRecord[Any, Any]:
    return ZodRecord(keyType=keyType, valueType=valueType, **_p(params, kwargs))


def looseRecord(
    keyType: ZodType[_K],
    valueType: ZodType[_V],
    params: Params = None,
    **kwargs: Any,
) -> ZodRecord[_K, _V]:
    return ZodRecord(keyType=keyType, valueType=valueType, mode="loose", **_p(params, kwargs))


def partialRecord(
    keyType: ZodType[_K],
    valueType: ZodType[_V],
    params: Params = None,
    **kwargs: Any,
) -> ZodRecord[_K, _V]:
    return ZodRecord(keyType=keyType, valueType=valueType, mode="partial", **_p(params, kwargs))


def map(  # noqa: A001
    keyType: ZodType[_K], valueType: ZodType[_V] | _b.type[_V], params: Params = None, **kwargs: Any
) -> ZodMap[_K, _V]:
    return ZodMap(keyType=keyType, valueType=valueType, **_p(params, kwargs))


def set(valueType: ZodType[_T], params: Params = None, **kwargs: Any) -> ZodSet[_T]:  # noqa: A001
    return ZodSet(valueType=valueType, **_p(params, kwargs))


# Options may be schemas, ``class X(z.Object)`` classes, or a mix: ``z.union([Cat, Dog])`` -> ``Cat | Dog``.
# The mixed overload also covers schema-only lists (``_O`` is then unsolved and drops out).
@overload
def union(options: Sequence[_b.type[_O]], params: Params = None, **kwargs: Any) -> ZodUnion[_O]: ...


@overload
def union(
    options: Sequence[_b.type[_O] | ZodType[_T]], params: Params = None, **kwargs: Any
) -> ZodUnion[_O | _T]: ...


def union(options: Sequence[Any], params: Params = None, **kwargs: Any) -> ZodUnion[Any]:
    return ZodUnion(options=_b.list(options), **_p(params, kwargs))


@overload
def xor(options: Sequence[_b.type[_O]], params: Params = None, **kwargs: Any) -> ZodXor[_O]: ...


@overload
def xor(
    options: Sequence[_b.type[_O] | ZodType[_T]], params: Params = None, **kwargs: Any
) -> ZodXor[_O | _T]: ...


def xor(options: Sequence[Any], params: Params = None, **kwargs: Any) -> ZodXor[Any]:
    return ZodXor(options=_b.list(options), **_p(params, kwargs))


@overload
def discriminatedUnion(
    discriminator: str, options: Sequence[_b.type[_O]], params: Params = None, **kwargs: Any
) -> ZodDiscriminatedUnion[_O]: ...


@overload
def discriminatedUnion(
    discriminator: str, options: Sequence[_b.type[_O] | ZodType[_T]], params: Params = None, **kwargs: Any
) -> ZodDiscriminatedUnion[_O | _T]: ...


def discriminatedUnion(
    discriminator: str, options: Sequence[Any], params: Params = None, **kwargs: Any
) -> ZodDiscriminatedUnion[Any]:
    return ZodDiscriminatedUnion(discriminator=discriminator, options=_b.list(options), **_p(params, kwargs))


def getDiscriminatedOption(union: ZodDiscriminatedUnion[Any], value: Any) -> ZodObject[Any]:
    return union.getDiscriminatedOption(value)


@overload
def lazy(getter: Callable[[], _b.type[_O]], params: Params = None, **kwargs: Any) -> ZodLazy[_O]: ...


@overload
def lazy(getter: Callable[[], ZodType[_T]], params: Params = None, **kwargs: Any) -> ZodLazy[_T]: ...


def lazy(getter: Callable[[], Any], params: Params = None, **kwargs: Any) -> ZodLazy[Any]:
    """``z.lazy(lambda: Node)``: a schema resolved on first use (recursive / mutually recursive)."""
    return ZodLazy(getter=getter, **_p(params, kwargs))


def function(params: Any = None, **kwargs: Any) -> ZodFunction:
    if params is None:
        return ZodFunction(**kwargs)
    return ZodFunction(params, **kwargs)


# --------------------------------------------------------------------------- #
# Wrappers / effects
# --------------------------------------------------------------------------- #


@overload
def optional(inner: _b.type[_O]) -> ZodOptional[_O]: ...


@overload
def optional(inner: ZodType[_T]) -> ZodOptional[_T]: ...


def optional(inner: Any) -> ZodOptional[Any]:
    return ZodOptional(innerType=inner)


def exactOptional(inner: ZodType[_T]) -> ZodExactOptional[_T]:
    return ZodExactOptional(innerType=inner)


@overload
def nullable(inner: _b.type[_O]) -> ZodNullable[_O]: ...


@overload
def nullable(inner: ZodType[_T]) -> ZodNullable[_T]: ...


def nullable(inner: Any) -> ZodNullable[Any]:
    return ZodNullable(innerType=inner)


@overload
def nullish(inner: _b.type[_O]) -> ZodOptional[_O | None]: ...


@overload
def nullish(inner: ZodType[_T]) -> ZodOptional[_T | None]: ...


def nullish(inner: Any) -> ZodOptional[Any]:
    return ZodOptional(innerType=ZodNullable(innerType=inner))


def nonoptional(inner: ZodType[_T | None], params: Params = None, **kwargs: Any) -> ZodNonOptional[_T]:
    return ZodNonOptional(innerType=inner, **_p(params, kwargs))


def default(
    inner: ZodType[_T | None], value: _T | Callable[[], _T]
) -> ZodDefault[_T]:  # ``z._default`` in TS
    return ZodDefault(innerType=inner, defaultValue=value)


_default = default


def prefault(inner: ZodType[_T], value: Any) -> ZodPrefault[_T]:
    return ZodPrefault(innerType=inner, defaultValue=value)


def catch(inner: ZodType[_T], value: _T | Callable[[Any], _T]) -> ZodCatch[_T]:
    return ZodCatch(innerType=inner, catchValue=value)


# A z.Object class and the `Any`-output schemas first: statically they would match the list overload.
@overload
def readonly(inner: _b.type[_O]) -> ZodReadonly[_O]: ...


@overload
def readonly(inner: ZodAny) -> ZodReadonly[Any]: ...


@overload
def readonly(inner: ZodCustom[_T]) -> ZodReadonly[_T]: ...


@overload
def readonly(inner: ZodType[list[_T]]) -> ZodReadonly[_b.tuple[_T, ...]]: ...


@overload
def readonly(inner: ZodType[dict[_K, _V]]) -> ZodReadonly[Mapping[_K, _V]]: ...


@overload
def readonly(inner: ZodType[_b.set[_T]]) -> ZodReadonly[_b.frozenset[_T]]: ...


@overload
def readonly(inner: ZodType[_T]) -> ZodReadonly[_T]: ...


def readonly(inner: Any) -> ZodReadonly[Any]:
    return ZodReadonly(innerType=inner)


@overload
def transform(fn: Callable[[Any], _T]) -> ZodTransform[_T]: ...


@overload
def transform(fn: Callable[[Any, RefinementCtx], _T]) -> ZodTransform[_T]: ...


def transform(fn: Callable[..., Any]) -> ZodTransform[Any]:
    return ZodTransform(transform=fn)


def pipe(in_: ZodType[Any], out: ZodType[_T]) -> ZodPipe[_T]:
    return ZodPipe(in_=in_, out=out)


def preprocess(fn: Callable[..., Any], schema: ZodType[_T]) -> ZodPipe[_T]:
    return ZodPipe(in_=ZodTransform(transform=fn), out=schema)


def codec(
    in_: ZodType[Any], out: ZodType[_T], params: Mapping[str, Any] | None = None, **kwargs: Any
) -> ZodCodec[_T]:
    p = dict(params or {})
    p.update(kwargs)
    return ZodCodec(in_=in_, out=out, transform=p["decode"], reverseTransform=p["encode"])


def invertCodec(codec: ZodCodec[Any]) -> ZodCodec[Any]:
    return invert_codec(codec)


def property(key: Any, schema: ZodType[Any]) -> Check:  # noqa: A001
    return property_check(key, schema)


def properties(shape: Mapping[str, ZodType[Any]]) -> _b.list[Check]:
    return properties_checks(shape)


def custom(fn: Callable[..., Any] | None = None, params: Params = None, **kwargs: Any) -> ZodCustom[Any]:
    p = _p(params, kwargs)
    return ZodCustom(
        fn=fn, abort=p.pop("abort", False), path=p.pop("path", None), params=p.pop("params", None), **p
    )


def instanceof(cls: _b.type[_C], params: Params = None, **kwargs: Any) -> ZodInstanceOf[_C]:
    p = _p(params, kwargs)
    msg = p.get("error") if isinstance(p.get("error"), str) else None
    return ZodInstanceOf(cls=cls, defaultMessage=msg, **({} if msg else p))


def json(params: Params = None, **kwargs: Any) -> ZodLazy[Any]:
    def getter() -> ZodType[Any]:
        return union(
            [string(params, **kwargs), number(), boolean(), null(), array(schema), record(string(), schema)]
        )

    schema: ZodLazy[Any] = lazy(getter)
    return schema


def keyof(schema: ZodObject[Any]) -> ZodEnum[str]:
    return schema.keyof()


def templateLiteral(parts: Sequence[Any], params: Params = None, **kwargs: Any) -> ZodString:
    import re as _re

    pieces: _b.list[str] = []
    for part in parts:
        if isinstance(part, ZodType):
            d = part._def
            if isinstance(part, ZodLiteral):
                pieces.append("(?:" + "|".join(_re.escape(str(v)) for v in d["values"]) + ")")
            elif isinstance(part, ZodEnum):
                pieces.append("(?:" + "|".join(_re.escape(str(v)) for v in d["entries"].values()) + ")")
            elif isinstance(part, (ZodNumber, ZodInt, ZodBigInt)):
                pieces.append(r"-?\d+(?:\.\d+)?")
            elif isinstance(part, ZodBoolean):
                pieces.append("(?:true|false)")
            elif isinstance(part, ZodNull):
                pieces.append("null")
            elif isinstance(part, ZodUndefined):
                pieces.append("undefined")
            else:
                pieces.append(".*?")
        else:
            pieces.append(_re.escape(str(part)))
    pattern = _re.compile("^" + "".join(pieces) + "$")
    return ZodString(**_p(params, kwargs)).regex(pattern)


# --------------------------------------------------------------------------- #
# Standalone checks (``schema.check(z.minLength(3))``) and refinements
# --------------------------------------------------------------------------- #


def refine(fn: Callable[..., Any], params: Params = None, **kwargs: Any) -> Check:
    return refine_check(fn, _p(params, kwargs))


def superRefine(fn: Callable[..., Any], params: Params = None, **kwargs: Any) -> Check:
    return super_refine_check(fn, _p(params, kwargs))


def check(fn: Callable[[RefinementCtx], Any], params: Params = None, **kwargs: Any) -> Check:
    return custom_check(fn, _p(params, kwargs))


def overwrite(fn: Callable[[Any], Any]) -> Check:
    return overwrite_check(fn)


def _last_check(schema: ZodType[Any]) -> Check:
    return schema._def["checks"][-1]


def lt(value: float, params: Params = None, **kwargs: Any) -> Check:
    return _last_check(ZodNumber().lt(value, params, **kwargs))


def lte(value: float, params: Params = None, **kwargs: Any) -> Check:
    return _last_check(ZodNumber().lte(value, params, **kwargs))


def gt(value: float, params: Params = None, **kwargs: Any) -> Check:
    return _last_check(ZodNumber().gt(value, params, **kwargs))


def gte(value: float, params: Params = None, **kwargs: Any) -> Check:
    return _last_check(ZodNumber().gte(value, params, **kwargs))


def positive(params: Params = None, **kwargs: Any) -> Check:
    return _last_check(ZodNumber().positive(params, **kwargs))


def negative(params: Params = None, **kwargs: Any) -> Check:
    return _last_check(ZodNumber().negative(params, **kwargs))


def nonpositive(params: Params = None, **kwargs: Any) -> Check:
    return _last_check(ZodNumber().nonpositive(params, **kwargs))


def nonnegative(params: Params = None, **kwargs: Any) -> Check:
    return _last_check(ZodNumber().nonnegative(params, **kwargs))


def multipleOf(value: float, params: Params = None, **kwargs: Any) -> Check:
    return _last_check(ZodNumber().multipleOf(value, params, **kwargs))


def regex(pattern: Any, params: Params = None, **kwargs: Any) -> Check:
    return _last_check(ZodString().regex(pattern, params, **kwargs))


def lowercase(params: Params = None, **kwargs: Any) -> Check:
    return _last_check(ZodString().lowercase(params, **kwargs))


def uppercase(params: Params = None, **kwargs: Any) -> Check:
    return _last_check(ZodString().uppercase(params, **kwargs))


def includes(value: str, params: Params = None, **kwargs: Any) -> Check:
    return _last_check(ZodString().includes(value, params, **kwargs))


def startsWith(value: str, params: Params = None, **kwargs: Any) -> Check:
    return _last_check(ZodString().startsWith(value, params, **kwargs))


def endsWith(value: str, params: Params = None, **kwargs: Any) -> Check:
    return _last_check(ZodString().endsWith(value, params, **kwargs))


def trim() -> Check:
    return _last_check(ZodString().trim())


def toLowerCase() -> Check:
    return _last_check(ZodString().toLowerCase())


def toUpperCase() -> Check:
    return _last_check(ZodString().toUpperCase())


def normalize(form: Literal["NFC", "NFD", "NFKC", "NFKD"] = "NFC") -> Check:
    return _last_check(ZodString().normalize(form))


def minLength(minimum: _b.int, params: Params = None, **kwargs: Any) -> Check:
    return _last_check(ZodArray(element=ZodAny()).min(minimum, params, **kwargs))


def maxLength(maximum: _b.int, params: Params = None, **kwargs: Any) -> Check:
    return _last_check(ZodArray(element=ZodAny()).max(maximum, params, **kwargs))


def length(length: _b.int, params: Params = None, **kwargs: Any) -> Check:
    return _last_check(ZodArray(element=ZodAny()).length(length, params, **kwargs))


def minSize(minimum: _b.int, params: Params = None, **kwargs: Any) -> Check:
    return _last_check(ZodSet(valueType=ZodAny()).min(minimum, params, **kwargs))


def maxSize(maximum: _b.int, params: Params = None, **kwargs: Any) -> Check:
    return _last_check(ZodSet(valueType=ZodAny()).max(maximum, params, **kwargs))


def size(size: _b.int, params: Params = None, **kwargs: Any) -> Check:
    return _last_check(ZodSet(valueType=ZodAny()).size(size, params, **kwargs))


# --------------------------------------------------------------------------- #
# Top-level parse helpers
# --------------------------------------------------------------------------- #


def parse(schema: ZodType[_T], data: Any, params: Mapping[str, Any] | None = None, **kwargs: Any) -> _T:
    return schema.parse(data, params, **kwargs)


def safeParse(
    schema: ZodType[_T], data: Any, params: Mapping[str, Any] | None = None, **kwargs: Any
) -> SafeParseResult[_T]:
    return schema.safeParse(data, params, **kwargs)


async def parseAsync(
    schema: ZodType[_T], data: Any, params: Mapping[str, Any] | None = None, **kwargs: Any
) -> _T:
    return await schema.parseAsync(data, params, **kwargs)


async def safeParseAsync(
    schema: ZodType[_T], data: Any, params: Mapping[str, Any] | None = None, **kwargs: Any
) -> SafeParseResult[_T]:
    return await schema.safeParseAsync(data, params, **kwargs)


def decode(schema: ZodType[_T], data: Any, params: Mapping[str, Any] | None = None, **kwargs: Any) -> _T:
    return schema.decode(data, params, **kwargs)


def encode(schema: ZodType[Any], data: Any, params: Mapping[str, Any] | None = None, **kwargs: Any) -> Any:
    return schema.encode(data, params, **kwargs)


def safeDecode(
    schema: ZodType[_T], data: Any, params: Mapping[str, Any] | None = None, **kwargs: Any
) -> SafeParseResult[_T]:
    return schema.safeDecode(data, params, **kwargs)


def safeEncode(
    schema: ZodType[Any], data: Any, params: Mapping[str, Any] | None = None, **kwargs: Any
) -> SafeParseResult[Any]:
    return schema.safeEncode(data, params, **kwargs)


async def decodeAsync(
    schema: ZodType[_T], data: Any, params: Mapping[str, Any] | None = None, **kwargs: Any
) -> _T:
    return await schema.decodeAsync(data, params, **kwargs)


async def encodeAsync(
    schema: ZodType[Any], data: Any, params: Mapping[str, Any] | None = None, **kwargs: Any
) -> Any:
    return await schema.encodeAsync(data, params, **kwargs)


async def safeDecodeAsync(
    schema: ZodType[_T], data: Any, params: Mapping[str, Any] | None = None, **kwargs: Any
) -> SafeParseResult[_T]:
    return await schema.safeDecodeAsync(data, params, **kwargs)


async def safeEncodeAsync(
    schema: ZodType[Any], data: Any, params: Mapping[str, Any] | None = None, **kwargs: Any
) -> SafeParseResult[Any]:
    return await schema.safeEncodeAsync(data, params, **kwargs)


# snake_case aliases for Pythonic code
safe_parse = safeParse
parse_async = parseAsync
safe_parse_async = safeParseAsync
to_json_schema = toJSONSchema
treeify_error = treeifyError
prettify_error = prettifyError
flatten_error = flattenError
discriminated_union = discriminatedUnion
partial_record = partialRecord
super_refine = superRefine
string_bool = stringbool
exact_optional = exactOptional
loose_record = looseRecord
get_discriminated_option = getDiscriminatedOption
credit_card = creditCard
currency_code = currencyCode
string_format = stringFormat


class _Locales:
    en = staticmethod(_en)


locales = _Locales()

__all__ = [  # noqa: RUF022 (grouped by category, like the Zod docs)
    # modules / namespaces
    "core",
    "regexes",
    "coerce",
    "iso",
    "locales",
    "NEVER",
    # core classes
    "Check",
    "Params",
    "ParseContext",
    "Payload",
    "RefinementCtx",
    "SafeParseError",
    "SafeParseResult",
    "SafeParseSuccess",
    "ZodType",
    "Object",
    "StrictObject",
    "LooseObject",
    "ObjectMeta",
    "custom_check",
    "overwrite_check",
    "refine_check",
    "super_refine_check",
    # errors
    "ZodAsyncError",
    "ZodEncodeError",
    "ZodError",
    "ZodIssue",
    "ZodIssueCode",
    "ZodRealError",
    "config",
    "flattenError",
    "prettifyError",
    "toDotPath",
    "treeifyError",
    "toJSONSchema",
    # registries
    "ZodRegistry",
    "globalRegistry",
    "registry",
    # schema classes
    "ZodAny",
    "ZodArray",
    "ZodBigInt",
    "ZodBoolean",
    "ZodCatch",
    "ZodCodec",
    "ZodCustom",
    "ZodDate",
    "ZodDefault",
    "ZodDiscriminatedUnion",
    "ZodEnum",
    "ZodExactOptional",
    "ZodFile",
    "ZodFunction",
    "ZodInstanceOf",
    "ZodInt",
    "ZodLazy",
    "ZodLiteral",
    "ZodMap",
    "ZodNaN",
    "ZodNever",
    "ZodNonOptional",
    "ZodNull",
    "ZodNullable",
    "ZodNumber",
    "ZodObject",
    "ZodOptional",
    "ZodPipe",
    "ZodPrefault",
    "ZodReadonly",
    "ZodRecord",
    "ZodSet",
    "ZodString",
    "ZodStringBool",
    "ZodSymbol",
    "ZodTransform",
    "ZodTuple",
    "ZodUndefined",
    "ZodUnion",
    "ZodUnknown",
    "ZodVoid",
    "ZodXor",
    # primitives
    "string",
    "number",
    "bigint",
    "boolean",
    "date",
    "symbol",
    "undefined",
    "null",
    "void",
    "any",
    "unknown",
    "never",
    "nan",
    "file",
    "int",
    "int32",
    "uint32",
    "int64",
    "uint64",
    "float32",
    "float64",
    # string formats
    "email",
    "url",
    "httpUrl",
    "emoji",
    "uuid",
    "uuidv4",
    "uuidv6",
    "uuidv7",
    "guid",
    "nanoid",
    "cuid",
    "cuid2",
    "ulid",
    "xid",
    "ksuid",
    "base64",
    "base64url",
    "hex",
    "hostname",
    "e164",
    "jwt",
    "ipv4",
    "ipv6",
    "cidrv4",
    "cidrv6",
    "hash",
    "mac",
    "creditCard",
    "currencyCode",
    "iban",
    "stringFormat",
    "stringbool",
    # literals / enums
    "literal",
    "enum",
    # composites
    "array",
    "tuple",
    "record",
    "looseRecord",
    "partialRecord",
    "map",
    "set",
    "union",
    "xor",
    "discriminatedUnion",
    "getDiscriminatedOption",
    "lazy",
    "function",
    # wrappers / effects
    "optional",
    "exactOptional",
    "nullable",
    "nullish",
    "nonoptional",
    "default",
    "_default",
    "prefault",
    "catch",
    "readonly",
    "transform",
    "pipe",
    "preprocess",
    "codec",
    "invertCodec",
    "property",
    "properties",
    "custom",
    "instanceof",
    "json",
    "keyof",
    "templateLiteral",
    # checks
    "refine",
    "superRefine",
    "check",
    "overwrite",
    "lt",
    "lte",
    "gt",
    "gte",
    "positive",
    "negative",
    "nonpositive",
    "nonnegative",
    "multipleOf",
    "regex",
    "lowercase",
    "uppercase",
    "includes",
    "startsWith",
    "endsWith",
    "trim",
    "toLowerCase",
    "toUpperCase",
    "normalize",
    "minLength",
    "maxLength",
    "length",
    "minSize",
    "maxSize",
    "size",
    # parse helpers
    "parse",
    "safeParse",
    "parseAsync",
    "safeParseAsync",
    "decode",
    "encode",
    "safeDecode",
    "safeEncode",
    "decodeAsync",
    "encodeAsync",
    "safeDecodeAsync",
    "safeEncodeAsync",
    # snake_case aliases
    "safe_parse",
    "parse_async",
    "safe_parse_async",
    "to_json_schema",
    "treeify_error",
    "prettify_error",
    "flatten_error",
    "discriminated_union",
    "partial_record",
    "super_refine",
    "string_bool",
    "exact_optional",
    "loose_record",
    "get_discriminated_option",
    "credit_card",
    "currency_code",
    "string_format",
    "invert_codec",
]

# ``from zopy import z`` / ``import zopy as z``: ``z`` is a module re-exporting everything here,
# so type checkers see the real signatures instead of ``ModuleType``.
from . import z as z  # noqa: E402
