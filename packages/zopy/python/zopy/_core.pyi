from collections.abc import Callable, Mapping, Sequence
from typing import Any

__version__: str
engine: str

class Compiled:
    """A compiled schema node tree; produced by :func:`compile`."""

    def run(self, data: Any, ctx: Any, backward: bool) -> tuple[Any, list[dict[str, Any]]]: ...
    def build_issues(self, issues: list[Any], ctx: Any) -> list[Any]:
        """``error.issues`` of a failed fast-path parse: default English messages written in Rust
        when no error map applies, the rest finished through the ``finalize_one`` / ``build_slow``
        helpers."""
    def finalize_plain(self, issues: list[Any], report_input: bool) -> list[int]:
        """Write default English messages into ``issues`` in place; returns indices left for Python."""

class PendingIssues:
    """The issues of a failed fast-path parse, kept in Rust until read: a lazy ``ZodError``'s pending
    build. Calling it returns the finished issues (as ``Compiled.build_issues`` would)."""

    def __call__(self) -> list[Any]: ...

class FastParse:
    """``schema.parse`` / ``safeParse`` / ``encode`` / ``safeEncode`` entry point installed by
    ``zopy._compile.install_fast`` (``backward``: the encode direction)."""

    def __init__(
        self,
        compiled: Compiled,
        ctx: Any,
        on_ok: Callable[[Any], Any] | None,
        on_issues: Callable[[PendingIssues], Any],
        slow: Callable[..., Any],
        owner: Any = None,
        fallback: Any = None,
        backward: bool = False,
        raises: type[BaseException] | None = None,
    ) -> None: ...
    def __get__(self, obj: Any, owner: Any = None) -> Any: ...
    def __call__(self, data: Any, params: Mapping[str, Any] | None = None, **kwargs: Any) -> Any: ...

def set_fast(enabled: bool) -> None:
    """Enable or disable every installed :class:`FastParse` (disabled ones call ``slow``)."""

def compile(nodes: Sequence[Mapping[str, Any]], root: int, helpers: Mapping[str, Any]) -> Compiled: ...  # noqa: A001

__all__ = [
    "Compiled",
    "FastParse",
    "PendingIssues",
    "__version__",
    "compile",
    "engine",
    "set_fast",
]
