# Task runner for the zopy workspace. `just` comes with `uv sync` (the rust-just dev dependency).
# Recipes go through `uv run` so they use the workspace .venv (and its Python for PyO3).

set shell := ["bash", "-euo", "pipefail", "-c"]

# List the recipes
default:
    @just --list

# Install every workspace member editable (builds the Rust extension)
sync:
    uv sync

# Rebuild the Rust extension after changing Rust code
build:
    uv sync --reinstall-package zopy

# Format Python and Rust, and apply safe lint fixes
fmt:
    uv run ruff check --fix .
    uv run ruff format .
    cargo fmt --all

# Lint and check formatting without changing files (workflows too: actionlint, zizmor)
lint:
    uv run ruff check .
    uv run ruff format --check .
    cargo fmt --all --check
    uv run cargo clippy --workspace --all-targets -- -D warnings
    uv run actionlint
    uv run zizmor --offline .github

# Type-check with pyright
typecheck:
    uv run pyright

# Run the Python tests (both engines) and the Rust tests
test: test-py test-rs

# Run the Python tests
test-py *args:
    uv run pytest {{ args }}

# Run the Rust tests
test-rs:
    uv run cargo test --workspace

# Everything CI runs
check: lint typecheck test

# Compare zopy with pydantic (Markdown table), e.g. `just bench -k nested`
bench *args:
    uv run bench {{ args }}

# Fail when zopy is slower than pydantic in any benchmark scenario
bench-check:
    uv run bench --check

# Run the example app, e.g. `just examples xor effects`
examples *sections:
    uv run examples {{ sections }}
