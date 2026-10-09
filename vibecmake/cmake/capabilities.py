"""Locating ``cmake`` and asking it what it can do."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

_CANDIDATE_PATHS = {
    "darwin": [
        "/Applications/CMake.app/Contents/bin/cmake",
        "/opt/homebrew/bin/cmake",
        "/usr/local/bin/cmake",
    ],
    "win32": [
        r"C:\Program Files\CMake\bin\cmake.exe",
        r"C:\Program Files (x86)\CMake\bin\cmake.exe",
    ],
    "linux": ["/usr/local/bin/cmake", "/usr/bin/cmake", "/snap/bin/cmake"],
}


@dataclass
class Generator:
    name: str
    platform_support: bool = False
    toolset_support: bool = False
    supported_platforms: list[str] = field(default_factory=list)

    @property
    def is_multi_config(self) -> bool:
        return self.name.startswith(("Visual Studio", "Xcode", "Ninja Multi-Config"))

    @property
    def can_open(self) -> bool:
        """Whether ``cmake --open`` works for projects using this generator."""
        return self.name.startswith(("Visual Studio", "Xcode"))


@dataclass
class CMakeInfo:
    executable: str
    version: str
    generators: list[Generator]
    has_fresh: bool = True

    def generator(self, name: str | None) -> Generator | None:
        return next((g for g in self.generators if g.name == name), None)


def find_cmake(preferred: str | None = None) -> str | None:
    """Return the path of a usable cmake executable."""
    if preferred and Path(preferred).is_file():
        return preferred
    found = shutil.which("cmake")
    if found:
        return found
    platform = "linux" if sys.platform.startswith("linux") else sys.platform
    for candidate in _CANDIDATE_PATHS.get(platform, []):
        if Path(candidate).is_file():
            return candidate
    return None


def parse_capabilities(executable: str, data: dict) -> CMakeInfo:
    version = data.get("version", {})
    generators = [
        Generator(
            name=g["name"],
            platform_support=bool(g.get("platformSupport")),
            toolset_support=bool(g.get("toolsetSupport")),
            supported_platforms=list(g.get("supportedPlatforms", [])),
        )
        for g in data.get("generators", [])
    ]
    major, minor = version.get("major", 0), version.get("minor", 0)
    return CMakeInfo(
        executable=executable,
        version=version.get("string", "unknown"),
        generators=generators,
        has_fresh=(major, minor) >= (3, 24),
    )


def query_cmake(executable: str) -> CMakeInfo:
    """Run ``cmake -E capabilities``; raises on failure."""
    result = subprocess.run(
        [executable, "-E", "capabilities"],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return parse_capabilities(executable, json.loads(result.stdout))


def default_generator(info: CMakeInfo) -> str | None:
    names = [g.name for g in info.generators]
    env = os.environ.get("CMAKE_GENERATOR")
    if env in names:
        return env
    if "Ninja" in names and shutil.which("ninja"):
        return "Ninja"
    if sys.platform == "win32":
        vs = [n for n in names if n.startswith("Visual Studio")]
        if vs:
            return vs[0]
    if "Unix Makefiles" in names:
        return "Unix Makefiles"
    return names[0] if names else None
