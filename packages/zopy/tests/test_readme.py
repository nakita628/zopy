"""The ``python`` code blocks in README.md run, in order, as one session (on both engines)."""

import re
from pathlib import Path

README = Path(__file__).resolve().parents[1] / "README.md"


def test_readme_examples_run():
    blocks = re.findall(r"```python\n(.*?)```", README.read_text(encoding="utf-8"), re.S)
    assert blocks
    namespace: dict[str, object] = {"__name__": "readme"}
    for number, block in enumerate(blocks):
        exec(compile(block, f"README.md (python block {number})", "exec"), namespace)
