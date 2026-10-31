"""Runs pyright over ``tests/typing`` when pyright is installed (``uv sync`` installs it)."""

import shutil
import subprocess
from pathlib import Path

import pytest

TYPING_DIR = Path(__file__).parent / "typing"
REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.skipif(shutil.which("pyright") is None, reason="pyright not installed")
def test_inference_expectations_hold():
    proc = subprocess.run(
        ["pyright", "--project", str(REPO_ROOT), str(TYPING_DIR)],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
