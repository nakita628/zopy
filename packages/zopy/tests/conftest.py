"""Run every test against both engines (Rust extension and pure Python)."""

import pytest

from zopy._compile import rust_available, set_engine

ENGINES = ["rust", "python"] if rust_available() else ["python"]


@pytest.fixture(autouse=True, params=ENGINES)
def engine(request):
    set_engine(request.param)
    yield request.param
    set_engine(ENGINES[0])
