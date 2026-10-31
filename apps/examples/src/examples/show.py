"""Tiny printing helpers shared by the demo sections."""

from __future__ import annotations

from typing import Any

from zopy import z


def section(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def ok(label: str, schema: Any, data: Any) -> Any:
    """Parse and print; failures are printed, not raised."""
    result = schema.safeParse(data)
    if result.success:
        print(f"  OK   {label:<42} -> {result.data!r}")
        return result.data
    print(f"  FAIL {label:<42} -> {_first_lines(z.prettifyError(result.error))}")
    return None


def _first_lines(text: str, limit: int = 4) -> str:
    lines = text.splitlines()
    shown = lines[:limit]
    more = f" ... (+{len(lines) - limit} lines)" if len(lines) > limit else ""
    return ("\n" + " " * 7).join(shown) + more
