"""Example app: exercises many schema shapes. Run with ``uv run examples``.

Pass section names to run a subset: ``uv run examples xor effects``.
"""

from __future__ import annotations

import sys

from .shapes import (
    async_demo,
    classstyle,
    collections,
    effects,
    errors,
    jsonschema,
    objects,
    primitives,
    quickstart,
    sample,
    typing_demo,
    xor,
)

SECTIONS = {
    "quickstart": quickstart.run,
    "classstyle": classstyle.run,
    "primitives": primitives.run,
    "objects": objects.run,
    "collections": collections.run,
    "xor": xor.run,
    "effects": effects.run,
    "errors": errors.run,
    "async": async_demo.run,
    "jsonschema": jsonschema.run,
    "typing": typing_demo.run,
    "sample": sample.run,
}


def main() -> None:
    wanted = sys.argv[1:] or list(SECTIONS)
    unknown = [w for w in wanted if w not in SECTIONS]
    if unknown:
        print(f"unknown sections: {unknown}; available: {list(SECTIONS)}")
        raise SystemExit(2)
    for name in wanted:
        SECTIONS[name]()


if __name__ == "__main__":
    main()
