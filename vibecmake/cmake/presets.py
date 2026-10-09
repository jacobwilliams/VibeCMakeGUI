"""Reading configure presets from ``CMakePresets.json`` / ``CMakeUserPresets.json``.

Only what the GUI needs is resolved: names, descriptions, the generator and the
binary directory (with macro expansion), and whether the preset's condition
holds on this host.
"""

from __future__ import annotations

import json
import os
import platform
import re
from dataclasses import dataclass, field
from pathlib import Path

PRESET_FILES = ("CMakePresets.json", "CMakeUserPresets.json")

# Fields that are not inherited from parent presets.
_NOT_INHERITED = {"name", "hidden", "inherits", "description", "displayName"}

_MACRO_RE = re.compile(r"\$(env|penv|vendor)?\{([^}]*)\}")


@dataclass
class ConfigurePreset:
    name: str
    display_name: str = ""
    description: str = ""
    generator: str | None = None
    binary_dir: str | None = None
    cache_variables: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return self.display_name or self.name


def host_system_name() -> str:
    return {"Darwin": "Darwin", "Windows": "Windows", "Linux": "Linux"}.get(
        platform.system(), platform.system()
    )


def _read_preset_file(path: Path, seen: set[Path], raw: dict[str, tuple[dict, Path]]) -> None:
    path = path.resolve()
    if path in seen or not path.is_file():
        return
    seen.add(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for include in data.get("include", []):
        _read_preset_file(path.parent / include, seen, raw)
    for preset in data.get("configurePresets", []):
        if "name" in preset:
            raw[preset["name"]] = (preset, path)


def _resolve(name: str, raw: dict[str, tuple[dict, Path]], stack: tuple[str, ...] = ()) -> dict:
    """Return the preset with inherited fields merged in."""
    preset, _ = raw[name]
    merged: dict = {}
    inherits = preset.get("inherits", [])
    if isinstance(inherits, str):
        inherits = [inherits]
    # Earlier parents take precedence over later ones.
    for parent in reversed(inherits):
        if parent in raw and parent not in stack:
            parent_fields = _resolve(parent, raw, stack + (name,))
            cache_vars = {**merged.get("cacheVariables", {}), **parent_fields.get("cacheVariables", {})}
            env = {**merged.get("environment", {}), **parent_fields.get("environment", {})}
            merged.update({k: v for k, v in parent_fields.items() if k not in _NOT_INHERITED})
            merged["cacheVariables"] = cache_vars
            merged["environment"] = env
    cache_vars = {**merged.get("cacheVariables", {}), **preset.get("cacheVariables", {})}
    env = {**merged.get("environment", {}), **preset.get("environment", {})}
    merged.update(preset)
    merged["cacheVariables"] = cache_vars
    merged["environment"] = env
    return merged


def expand_macros(text: str, preset: dict, source_dir: Path, file_dir: Path) -> str:
    environment = preset.get("environment", {})

    def replace(match: re.Match) -> str:
        namespace, key = match.group(1), match.group(2)
        if namespace == "env":
            value = environment.get(key)
            if value is None:
                return os.environ.get(key, "")
            return value if isinstance(value, str) else ""
        if namespace == "penv":
            return os.environ.get(key, "")
        if namespace == "vendor":
            return match.group(0)
        return {
            "sourceDir": str(source_dir),
            "sourceParentDir": str(source_dir.parent),
            "sourceDirName": source_dir.name,
            "presetName": preset.get("name", ""),
            "generator": preset.get("generator", ""),
            "hostSystemName": host_system_name(),
            "fileDir": str(file_dir),
            "dollar": "$",
            "pathListSep": os.pathsep,
        }.get(key, match.group(0))

    return _MACRO_RE.sub(replace, text)


def evaluate_condition(cond, preset: dict, source_dir: Path, file_dir: Path) -> bool:
    if cond is None:
        return True
    if isinstance(cond, bool):
        return cond

    def x(value: str) -> str:
        return expand_macros(value, preset, source_dir, file_dir)

    kind = cond.get("type")
    if kind == "const":
        return bool(cond.get("value"))
    if kind in ("equals", "notEquals"):
        result = x(cond.get("lhs", "")) == x(cond.get("rhs", ""))
        return result if kind == "equals" else not result
    if kind in ("inList", "notInList"):
        result = x(cond.get("string", "")) in [x(s) for s in cond.get("list", [])]
        return result if kind == "inList" else not result
    if kind in ("matches", "notMatches"):
        result = re.search(cond.get("regex", ""), x(cond.get("string", ""))) is not None
        return result if kind == "matches" else not result
    if kind == "anyOf":
        return any(evaluate_condition(c, preset, source_dir, file_dir) for c in cond.get("conditions", []))
    if kind == "allOf":
        return all(evaluate_condition(c, preset, source_dir, file_dir) for c in cond.get("conditions", []))
    if kind == "not":
        return not evaluate_condition(cond.get("condition"), preset, source_dir, file_dir)
    return True


def load_configure_presets(source_dir: str | Path) -> list[ConfigurePreset]:
    """Return the visible, applicable configure presets for *source_dir*."""
    source_dir = Path(source_dir)
    raw: dict[str, tuple[dict, Path]] = {}
    seen: set[Path] = set()
    for filename in PRESET_FILES:
        _read_preset_file(source_dir / filename, seen, raw)

    presets: list[ConfigurePreset] = []
    for name, (preset, path) in raw.items():
        if preset.get("hidden"):
            continue
        resolved = _resolve(name, raw)
        file_dir = path.parent
        if not evaluate_condition(resolved.get("condition"), resolved, source_dir, file_dir):
            continue
        binary_dir = resolved.get("binaryDir")
        if binary_dir:
            binary_dir = expand_macros(binary_dir, resolved, source_dir, file_dir)
            if not Path(binary_dir).is_absolute():
                binary_dir = str(source_dir / binary_dir)
            binary_dir = os.path.normpath(binary_dir)
        presets.append(
            ConfigurePreset(
                name=name,
                display_name=preset.get("displayName", ""),
                description=preset.get("description", ""),
                generator=resolved.get("generator"),
                binary_dir=binary_dir,
                cache_variables=resolved.get("cacheVariables", {}),
            )
        )
    return presets
