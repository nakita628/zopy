"""``from zopy import z`` - re-exports the whole ``zopy`` namespace with full type information."""

from zopy import *  # noqa: F403  # pyright: ignore[reportWildcardImportFromLibrary]
from zopy import __all__ as __all__
from zopy import __version__ as __version__
from zopy import _default as _default
