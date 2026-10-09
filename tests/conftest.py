import os
import shutil
from pathlib import Path

import pytest

os.environ.setdefault("QT_API", "pyside6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "hello"


@pytest.fixture
def example_source(tmp_path) -> Path:
    """A private copy of the example project."""
    dest = tmp_path / "hello"
    shutil.copytree(EXAMPLE, dest, ignore=shutil.ignore_patterns("build"))
    return dest


requires_cmake = pytest.mark.skipif(shutil.which("cmake") is None, reason="cmake not on PATH")
