"""Talking to CMake through its File API (``.cmake/api/v1``).

We drop a stateless query into the build tree before each configure; CMake
answers with JSON describing the targets and configurations it generated.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

CLIENT = "client-vibecmake"

_QUERY = {
    "requests": [
        {"kind": "codemodel", "version": 2},
        {"kind": "cmakeFiles", "version": 1},
        {"kind": "toolchains", "version": 1},
    ]
}


@dataclass
class Target:
    name: str
    type: str
    directory: str
    artifacts: list[str] = field(default_factory=list)


@dataclass
class CodeModel:
    generator: str | None
    multi_config: bool
    configurations: list[str]
    targets: list[Target]


def api_dir(build_dir: Path) -> Path:
    return Path(build_dir) / ".cmake" / "api" / "v1"


def write_query(build_dir: Path) -> None:
    query_dir = api_dir(build_dir) / "query" / CLIENT
    query_dir.mkdir(parents=True, exist_ok=True)
    (query_dir / "query.json").write_text(json.dumps(_QUERY, indent=2), encoding="utf-8")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_codemodel(build_dir: Path) -> CodeModel | None:
    """Read the most recent reply, or None if there isn't a usable one."""
    reply_dir = api_dir(build_dir) / "reply"
    try:
        indexes = sorted(reply_dir.glob("index-*.json"))
        if not indexes:
            return None
        index = _load(indexes[-1])
        responses = index["reply"][CLIENT]["query.json"]["responses"]
        codemodel_ref = next(r for r in responses if r.get("kind") == "codemodel")
        codemodel = _load(reply_dir / codemodel_ref["jsonFile"])
    except (OSError, KeyError, StopIteration, ValueError):
        return None

    generator = index.get("cmake", {}).get("generator", {})
    configurations = codemodel.get("configurations", [])
    targets: list[Target] = []
    if configurations:
        config = configurations[0]
        directories = config.get("directories", [])
        for ref in config.get("targets", []):
            try:
                detail = _load(reply_dir / ref["jsonFile"])
            except (OSError, KeyError, ValueError):
                detail = {}
            dir_index = ref.get("directoryIndex", 0)
            directory = directories[dir_index].get("source", ".") if dir_index < len(directories) else "."
            targets.append(
                Target(
                    name=ref["name"],
                    type=detail.get("type", "UNKNOWN"),
                    directory=directory,
                    artifacts=[a["path"] for a in detail.get("artifacts", [])],
                )
            )
    targets.sort(key=lambda t: t.name.lower())
    return CodeModel(
        generator=generator.get("name"),
        multi_config=bool(generator.get("multiConfig")),
        configurations=[c.get("name", "") for c in configurations],
        targets=targets,
    )
