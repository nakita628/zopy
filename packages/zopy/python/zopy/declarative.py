# pyright: reportSelfClsParameterName=false
# (_ObjectMetaBody's methods receive the class as `cls`; statically it is a mixin, not a metaclass)
"""``class User(z.Object)``: declare an object schema as a class so the class is the type.

    class User(z.Object):
        name = z.string().min(1)
        age = z.int().optional()

    user = User.parse(data)   # -> User   (user.name: str, user.age: int | None)
    User.shape                # -> {"name": ZodString, "age": ZodOptional[int]}

The class object *is* a schema (its metaclass derives from ``ZodObject``), so it can be
nested in other schemas: ``z.array(User)``, ``z.object({"owner": User})``, ``z.toJSONSchema(User)``.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterator, KeysView, Mapping
from typing import TYPE_CHECKING, Any, Self, TypeVar, cast, overload

from .core import SafeParseResult, ZodType, aborted
from .schemas import (
    ZodArray,
    ZodCatch,
    ZodDefault,
    ZodNever,
    ZodNullable,
    ZodObject,
    ZodOptional,
    ZodReadonly,
    ZodUnknown,
    _then,
)

if TYPE_CHECKING:
    from .core import Payload, TransformFn
    from .schemas import ZodPipe

_RESERVED_KWARGS = ("strict", "loose", "catchall")
_O = TypeVar("_O", bound="Object")
_U = TypeVar("_U")


def _is_schema(value: object) -> bool:
    return isinstance(value, ZodType)


def _own_annotations(cls: type) -> dict[str, Any]:
    """Annotations written in ``cls``'s own body, without evaluating them."""
    if sys.version_info >= (3, 14):
        # Annotations are evaluated lazily (PEP 649); the class namespace holds an annotate
        # function, not ``__annotations__``. get_annotations returns only this class's own.
        import annotationlib

        return dict(annotationlib.get_annotations(cls, format=annotationlib.Format.FORWARDREF))
    return dict(vars(cls).get("__annotations__", {}))


def _reject_annotated_fields(cls: type) -> None:
    """Fields are ``name = z.string()`` (the schema is the value; its type is inferred).

    ``name: z.string()`` or ``name: Annotated[str, ...]`` would otherwise be silently ignored:
    an annotation alone defines no field. ``ClassVar`` and ``_private`` names are left alone.
    """
    for field, annotation in _own_annotations(cls).items():
        if field.startswith("_") or "ClassVar" in str(annotation):
            continue
        if _is_schema(vars(cls).get(field)):
            fix = f"drop the annotation and keep `{field} = ...` (the type comes from the schema)"
        elif isinstance(annotation, str) and annotation.startswith("z."):
            fix = f"write `{field} = {annotation}`"
        elif _is_schema(annotation):
            fix = f"write `{field} = z....` with `=` instead of `:`"
        else:
            shown = annotation if isinstance(annotation, str) else getattr(annotation, "__name__", annotation)
            fix = f"write `{field} = <schema>`, e.g. `{field} = z.string()` (got the annotation `{shown}`)"
        raise TypeError(f"{cls.__name__}.{field}: z.Object fields are assigned, not annotated; {fix}")


class _ObjectMetaBody(ZodObject[Any]):
    """The behaviour of :class:`ObjectMeta` (combined with ``type`` below). Its methods take the
    class being built as ``cls``; it is annotated ``Any`` where ``type`` attributes are used."""

    def __new__(
        mcls, name: str, bases: tuple[type, ...], namespace: dict[str, Any], **kwargs: Any
    ) -> ObjectMeta:
        for key in _RESERVED_KWARGS:
            kwargs.pop(key, None)
        return cast(ObjectMeta, type.__new__(mcls, name, bases, namespace, **kwargs))

    def __init__(
        cls: Any,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
        *,
        strict: bool = False,
        loose: bool = False,
        catchall: ZodType[Any] | None = None,
        **kwargs: Any,
    ) -> None:
        type.__init__(cls, name, bases, namespace, **kwargs)
        _reject_annotated_fields(cls)
        shape: dict[str, ZodType[Any]] = {}
        owners: dict[str, type] = {}
        for klass in reversed(cls.__mro__):
            if klass is object or not isinstance(klass, ObjectMeta):
                continue
            for field, value in vars(klass).items():
                if field.startswith("_") or not _is_schema(value):
                    continue
                schema = cast("ZodType[Any]", value)
                prev = owners.get(field)
                if (
                    prev is not None
                    and klass is not cls
                    and not issubclass(klass, prev)
                    and shape[field] is not schema
                    and field not in vars(cls)
                ):
                    # Two unrelated bases declare the field differently. Keeping either one would
                    # silently drop the other's checks, so make the subclass choose.
                    raise TypeError(
                        f"{cls.__name__}.{field}: declared differently by {prev.__name__} and "
                        f"{klass.__name__}; redeclare `{field} = ...` in {cls.__name__} to choose one"
                    )
                owners[field] = klass
                shape[field] = schema
        if catchall is None:
            # The nearest base that sets a key policy (strict / loose / catchall), so that
            # `class X(Base, z.StrictObject)` is strict even when `Base` is not.
            inherited = next(
                (
                    c
                    for b in cls.__mro__[1:]
                    if isinstance(b, ObjectMeta)
                    and (c := vars(b).get("_def", {}).get("catchall")) is not None
                ),
                None,
            )
            catchall = ZodNever() if strict else ZodUnknown() if loose else inherited
        ZodObject.__init__(cls, shape=shape, catchall=catchall, objectClass=cls)

    # -- schema behaviour --------------------------------------------------- #
    def _clone(cls: Any, **changes: Any) -> Any:
        """Derived schemas (``.refine``, ``.extend`` ...) are subclasses; parse output stays an instance."""
        new = ObjectMeta(cls.__name__, (cls,), {})
        new._def = {**cls._def, **changes, "objectClass": new}
        return new

    def _parse(cls, payload: Payload) -> Any:
        if isinstance(payload.value, Object):
            payload.value = payload.value.to_dict(deep=False)
        result = ZodObject._parse(cls, payload)

        def finish(r: Payload) -> Payload:
            if isinstance(r.value, dict) and not aborted(r):
                r.value = cls._from_dict(r.value)
            return r

        return _then(result, finish)

    def _from_dict(cls, values: Mapping[str, Any]) -> Any:
        instance = object.__new__(cast(type, cls))
        vars(instance).update(values)  # absent optional fields stay absent (``"x" in obj`` is False)
        return instance

    def __repr__(cls: Any) -> str:
        return f"<z.Object {cls.__name__} {list(cls._def['shape'])}>"

    # Nested use as a field (``author = User``): the attribute reads as a ``User`` on instances.
    @overload
    def __get__(self: type[_O], instance: None, owner: Any = None) -> type[_O]: ...  # type: ignore[misc]

    @overload
    def __get__(self: type[_O], instance: Object, owner: Any = None) -> _O: ...  # type: ignore[misc]

    @overload
    def __get__(self, instance: object, owner: Any = None) -> ObjectMeta: ...

    def __get__(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, instance: Any, owner: Any = None
    ) -> Any:
        return ZodType.__get__(self, instance, owner)

    if TYPE_CHECKING:  # see ``ZodType.__set__``: runtime fields are non-data descriptors

        def __set__(self: type[_O], instance: Object, value: _O) -> None: ...  # type: ignore[misc]

    # ``User | z.string()`` is a union schema (ZodType's meaning) while ``User | None`` stays a
    # typing union, so the class still works in annotations.
    if not TYPE_CHECKING:

        def __or__(cls, other):
            if isinstance(other, ZodType):
                return ZodType.__or__(cls, other)
            return type.__or__(cls, other)

        def __ror__(cls, other):
            if isinstance(other, ZodType):
                return ZodType.__or__(other, cls)
            return type.__ror__(cls, other)


if TYPE_CHECKING:
    # `type` first for type checkers: they treat `X | None` as a union only when the metaclass's
    # `__or__` is `type`'s, so `def f() -> User | None` stays a valid annotation.
    class ObjectMeta(type, _ObjectMetaBody):
        """Metaclass of ``z.Object``: every subclass is itself a ``ZodObject`` instance."""

else:

    class ObjectMeta(_ObjectMetaBody, type):
        """Metaclass of ``z.Object``: every subclass is itself a ``ZodObject`` instance."""


class Object(metaclass=ObjectMeta):
    """Base class for class-declared object schemas. See the module docstring."""

    # Field values live in ``__dict__`` (``vars(self)`` is the mapping view); the readonly flag is a
    # slot so it never shows up as a field.
    __slots__ = ("__dict__", "_zod_frozen")

    if not TYPE_CHECKING:  # keep type checkers flagging assignments to undeclared attributes

        def __setattr__(self, name, value):
            self._check_mutable(name)
            object.__setattr__(self, name, value)

        def __delattr__(self, name):
            self._check_mutable(name)
            object.__delattr__(self, name)

    def _check_mutable(self, name: str) -> None:
        if getattr(self, "_zod_frozen", False):
            raise AttributeError(f"{type(self).__name__} is readonly: cannot change {name!r}")

    if TYPE_CHECKING:
        # The class keywords handled by ObjectMeta (``class X(z.Object, strict=True)``).
        def __init_subclass__(
            cls, *, strict: bool = False, loose: bool = False, catchall: ZodType[Any] | None = None
        ) -> None: ...

    def __init__(self, **fields: Any) -> None:
        parsed = type(self).parse(fields)
        vars(self).update(vars(parsed))

    # -- parsing (typed: the class is the output type) ----------------------- #
    @classmethod
    def parse(cls, data: Any, params: Mapping[str, Any] | None = None, **kwargs: Any) -> Self:
        return ZodType.parse(cast("ZodType[Self]", cls), data, params, **kwargs)

    @classmethod
    def safeParse(  # noqa: N802
        cls, data: Any, params: Mapping[str, Any] | None = None, **kwargs: Any
    ) -> SafeParseResult[Self]:
        return ZodType.safeParse(cast("ZodType[Self]", cls), data, params, **kwargs)

    @classmethod
    async def parseAsync(cls, data: Any, params: Mapping[str, Any] | None = None, **kwargs: Any) -> Self:  # noqa: N802
        return await ZodType.parseAsync(cast("ZodType[Self]", cls), data, params, **kwargs)

    @classmethod
    async def safeParseAsync(  # noqa: N802
        cls, data: Any, params: Mapping[str, Any] | None = None, **kwargs: Any
    ) -> SafeParseResult[Self]:
        return await ZodType.safeParseAsync(cast("ZodType[Self]", cls), data, params, **kwargs)

    safe_parse = safeParse
    parse_async = parseAsync
    safe_parse_async = safeParseAsync

    # -- codec direction (``z.decode`` / ``z.encode``) --------------------------- #
    @classmethod
    def decode(cls, data: Any, params: Mapping[str, Any] | None = None, **kwargs: Any) -> Self:
        return cls.parse(data, params, **kwargs)

    @classmethod
    def safeDecode(  # noqa: N802
        cls, data: Any, params: Mapping[str, Any] | None = None, **kwargs: Any
    ) -> SafeParseResult[Self]:
        return cls.safeParse(data, params, **kwargs)

    @classmethod
    def encode(cls, data: Any, params: Mapping[str, Any] | None = None, **kwargs: Any) -> Any:
        """The wire form of ``data`` (codecs run their ``encode``); an instance of this class."""
        return ZodType.encode(cast("ZodType[Self]", cls), data, params, **kwargs)

    @classmethod
    def safeEncode(  # noqa: N802
        cls, data: Any, params: Mapping[str, Any] | None = None, **kwargs: Any
    ) -> SafeParseResult[Any]:
        return ZodType.safeEncode(cast("ZodType[Self]", cls), data, params, **kwargs)

    # -- wrappers that keep the class as the output type ---------------------- #
    @classmethod
    def optional(cls) -> ZodOptional[Self]:
        return ZodOptional(innerType=cls)

    @classmethod
    def nullable(cls) -> ZodNullable[Self]:
        return ZodNullable(innerType=cls)

    @classmethod
    def nullish(cls) -> ZodOptional[Self | None]:
        return ZodOptional(innerType=ZodNullable(innerType=cls))

    @classmethod
    def array(cls) -> ZodArray[Self]:
        return ZodArray(element=cls)

    @classmethod
    def readonly(cls) -> ZodReadonly[Self]:
        """The parsed instance is frozen: setting or deleting an attribute raises AttributeError."""
        return ZodReadonly(innerType=cls)

    @classmethod
    def default(cls, value: Self | Mapping[str, Any] | Callable[[], Any]) -> ZodDefault[Self]:
        """``.default({...})``: a dict is parsed into an instance, so ``user.profile.links`` works."""
        return ZodDefault(innerType=cls, defaultValue=cls._instance_value(value))

    @classmethod
    def catch(cls, value: Self | Mapping[str, Any] | Callable[[Any], Any]) -> ZodCatch[Self]:
        return ZodCatch(innerType=cls, catchValue=cls._instance_value(value))

    @classmethod
    def _instance_value(cls, value: Any) -> Any:
        def convert(v: Any) -> Any:
            return cls.parse(v) if isinstance(v, Mapping) and not isinstance(v, Object) else v

        if callable(value) and not isinstance(value, Object):
            return lambda *args: convert(value(*args))
        return convert(value)

    if TYPE_CHECKING:
        # Static signatures only; at runtime these are the ZodObject methods on the metaclass.

        @classmethod
        def transform(cls, fn: TransformFn[Self, _U]) -> ZodPipe[_U]: ...

    # -- instance behaviour: attribute access plus a read-only mapping view --- #
    @classmethod
    def _absent_when_none(cls) -> frozenset[str]:
        """Fields where ``None`` can only mean "not set": optional (or exactOptional) fields whose
        inner schema rejects ``None``. JSON leaves them out instead of writing ``null`` (which the
        schema, and its JSON Schema, would reject). Nullable fields keep their ``null``."""
        cached = cls.__dict__.get("_zod_absent_when_none")
        if cached is not None:
            return cached
        names = []
        for name, schema in cls._def["shape"].items():
            optional = False
            while isinstance(schema, (ZodOptional, ZodNullable)):
                if isinstance(schema, ZodNullable):
                    break
                optional = True
                schema = schema._def["innerType"]
            if optional and not isinstance(schema, ZodNullable) and not schema.safeParse(None).success:
                names.append(name)
        cached = frozenset(names)
        type.__setattr__(cls, "_zod_absent_when_none", cached)
        return cached

    def _wire_dict(self) -> dict[str, Any]:
        """The fields JSON should carry: ``to_dict(deep=False)`` minus unset optional fields."""
        absent = type(self)._absent_when_none()
        return {k: v for k, v in vars(self).items() if not (v is None and k in absent)}

    def to_dict(self, deep: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in vars(self).items():
            out[key] = _to_plain(value) if deep else value
        return out

    def __getitem__(self, key: str) -> Any:
        try:
            return vars(self)[key]
        except KeyError:
            raise KeyError(key) from None

    def keys(self) -> KeysView[str]:
        return vars(self).keys()

    # No ``values()`` / ``items()``: they are common field names (``items = z.array(Item)``) and a
    # method would shadow them. Use ``dict(obj)`` or ``obj.to_dict()`` for a full mapping.

    @overload
    def get(self, key: str, /) -> Any: ...

    @overload
    def get(self, key: str, default: _U, /) -> Any | _U: ...

    def get(self, key: str, default: Any = None, /) -> Any:
        """``obj.get("x")``: the value, or ``default`` when the key is absent (an unset optional field)."""
        return vars(self).get(key, default)

    def __iter__(self) -> Iterator[str]:
        return iter(vars(self))

    def __len__(self) -> int:
        return len(vars(self))

    def __contains__(self, key: object) -> bool:
        return key in vars(self)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Object):
            return type(other) is type(self) and vars(other) == vars(self)
        if isinstance(other, Mapping):
            return self.to_dict(deep=False) == dict(other)
        return NotImplemented

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        fields = ", ".join(f"{k}={v!r}" for k, v in vars(self).items())
        return f"{type(self).__name__}({fields})"


class StrictObject(Object, strict=True):
    """``class X(z.StrictObject)`` is ``z.strictObject({...})`` as a class: unknown keys are an error."""


class LooseObject(Object, loose=True):
    """``class X(z.LooseObject)`` is ``z.looseObject({...})`` as a class: unknown keys are kept."""


def _to_plain(value: Any) -> Any:
    if isinstance(value, Object):
        return value.to_dict()
    if isinstance(value, dict):
        return {k: _to_plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_plain(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_to_plain(v) for v in value)
    return value
