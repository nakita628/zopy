"""Schema registries (``z.registry()``, ``z.globalRegistry``)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class ZodRegistry:
    def __init__(self) -> None:
        self._map: dict[int, tuple[Any, dict[str, Any]]] = {}

    def add(self, schema: Any, meta: Mapping[str, Any] | None = None, **kwargs: Any) -> ZodRegistry:
        merged = dict(meta or {})
        merged.update(kwargs)
        self._map[id(schema)] = (schema, merged)
        return self

    def remove(self, schema: Any) -> ZodRegistry:
        self._map.pop(id(schema), None)
        return self

    def get(self, schema: Any) -> dict[str, Any] | None:
        entry = self._map.get(id(schema))
        return entry[1] if entry else None

    def has(self, schema: Any) -> bool:
        return id(schema) in self._map

    def clear(self) -> ZodRegistry:
        self._map.clear()
        return self

    def schemas(self) -> list[Any]:
        return [schema for schema, _ in self._map.values()]

    def __iter__(self):
        return iter(self._map.values())

    def __len__(self) -> int:
        return len(self._map)


def registry() -> ZodRegistry:
    return ZodRegistry()


globalRegistry = ZodRegistry()  # noqa: N816 (zod API name)

# ``.openapi({"param": {...}})``: OpenAPI parameter metadata, kept out of the JSON Schema output.
openapiParamRegistry = ZodRegistry()  # noqa: N816
