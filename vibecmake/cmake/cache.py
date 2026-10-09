"""Reading ``CMakeCache.txt`` files.

The parser mirrors the rules CMake itself uses (``cmCacheManager::ParseEntry``)
so that quoted names, ``//`` help comments and the ``-ADVANCED`` / ``-STRINGS``
property pseudo-entries are all understood.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

CACHE_FILENAME = "CMakeCache.txt"

#: Types a user can sensibly edit in the GUI.
EDITABLE_TYPES = ("BOOL", "PATH", "FILEPATH", "STRING")

#: Types that are never shown to the user.
HIDDEN_TYPES = ("INTERNAL", "STATIC")

#: Cache "properties" that CMake stores as separate INTERNAL entries.
_PROPERTY_SUFFIXES = ("-ADVANCED", "-STRINGS", "-MODIFIED")

_TRUE_VALUES = {"1", "ON", "YES", "TRUE", "Y"}

_ENTRY_RE = re.compile(r"^([^=:]*):([^=]*)=(.*[^\r\t ]|[\r\t ]*)[\r\t ]*$")
_QUOTED_ENTRY_RE = re.compile(r'^"([^"]*)":([^=]*)=(.*[^\r\t ]|[\r\t ]*)[\r\t ]*$')


def is_on(value: str) -> bool:
    """Return True if *value* is a CMake "on" constant (like ``cmIsOn``)."""
    return value.strip().upper() in _TRUE_VALUES


@dataclass
class CacheEntry:
    name: str
    type: str
    value: str
    help: str = ""
    advanced: bool = False
    strings: list[str] = field(default_factory=list)

    @property
    def is_hidden(self) -> bool:
        return self.type in HIDDEN_TYPES


@dataclass
class CMakeCache:
    path: Path | None
    entries: dict[str, CacheEntry] = field(default_factory=dict)

    @property
    def visible_entries(self) -> list[CacheEntry]:
        return [e for e in self.entries.values() if not e.is_hidden]

    def get(self, name: str, default: str | None = None) -> str | None:
        entry = self.entries.get(name)
        return entry.value if entry is not None else default

    @property
    def home_directory(self) -> str | None:
        return self.get("CMAKE_HOME_DIRECTORY")

    @property
    def generator(self) -> str | None:
        return self.get("CMAKE_GENERATOR")

    @property
    def project_name(self) -> str | None:
        return self.get("CMAKE_PROJECT_NAME")


def parse_entry_line(line: str) -> tuple[str, str, str] | None:
    """Split ``NAME:TYPE=VALUE`` into its parts, or return None."""
    match = _QUOTED_ENTRY_RE.match(line) or _ENTRY_RE.match(line)
    if not match:
        return None
    name, type_, value = match.groups()
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        value = value[1:-1]
    return name, type_, value


def parse_cache_text(text: str, path: Path | None = None) -> CMakeCache:
    entries: dict[str, CacheEntry] = {}
    properties: list[CacheEntry] = []
    help_lines: list[str] = []

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            help_lines.clear()
            continue
        if line.startswith("//"):
            help_lines.append(line[2:])
            continue
        if line.startswith("#"):
            continue
        parsed = parse_entry_line(line)
        if parsed is None:
            help_lines.clear()
            continue
        name, type_, value = parsed
        entry = CacheEntry(name=name, type=type_, value=value, help="\n".join(help_lines))
        help_lines.clear()
        if type_ == "INTERNAL" and name.endswith(_PROPERTY_SUFFIXES):
            properties.append(entry)
        entries[name] = entry

    for prop in properties:
        base, _, suffix = prop.name.rpartition("-")
        target = entries.get(base)
        if target is None:
            continue
        if suffix == "ADVANCED":
            target.advanced = is_on(prop.value)
        elif suffix == "STRINGS":
            target.strings = [s for s in prop.value.split(";") if s != ""]

    return CMakeCache(path=path, entries=entries)


def cache_path(build_dir: str | Path) -> Path:
    return Path(build_dir) / CACHE_FILENAME


def read_cache(build_dir: str | Path) -> CMakeCache | None:
    """Read the cache in *build_dir*, or return None if there is none."""
    path = cache_path(build_dir)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return parse_cache_text(text, path)
