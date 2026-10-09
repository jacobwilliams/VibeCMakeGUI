"""Building ``cmake`` command lines."""

from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class CacheOverride:
    """A ``-D`` definition to pass on the command line."""

    name: str
    type: str
    value: str

    def to_arg(self) -> str:
        if self.type and self.type != "UNINITIALIZED":
            return f"-D{self.name}:{self.type}={self.value}"
        return f"-D{self.name}={self.value}"


@dataclass
class ConfigureRequest:
    build_dir: Path
    source_dir: Path | None = None
    generator: str | None = None
    platform: str | None = None
    toolset: str | None = None
    toolchain_file: str | None = None
    preset: str | None = None
    fresh: bool = False
    overrides: list[CacheOverride] = field(default_factory=list)
    removals: list[str] = field(default_factory=list)
    extra_args: list[str] = field(default_factory=list)


def configure_args(req: ConfigureRequest) -> list[str]:
    args: list[str] = []
    if req.preset:
        args += ["--preset", req.preset]
    if req.source_dir is not None:
        args += ["-S", str(req.source_dir)]
    args += ["-B", str(req.build_dir)]
    if req.generator:
        args += ["-G", req.generator]
    if req.platform:
        args += ["-A", req.platform]
    if req.toolset:
        args += ["-T", req.toolset]
    if req.toolchain_file:
        args.append(f"-DCMAKE_TOOLCHAIN_FILE:FILEPATH={req.toolchain_file}")
    if req.fresh:
        args.append("--fresh")
    for name in req.removals:
        args += ["-U", name]
    args += [o.to_arg() for o in req.overrides]
    args += req.extra_args
    return args


def build_args(
    build_dir: Path,
    target: str | None = None,
    config: str | None = None,
    jobs: int = 0,
    clean_first: bool = False,
) -> list[str]:
    args = ["--build", str(build_dir)]
    if target:
        args += ["--target", target]
    if config:
        args += ["--config", config]
    if jobs > 0:
        args += ["--parallel", str(jobs)]
    if clean_first:
        args.append("--clean-first")
    return args


def format_command(program: str, args: list[str]) -> str:
    """Render a command line that can be pasted into the user's shell."""
    argv = [program, *args]
    if os.name == "nt":
        return subprocess.list2cmdline(argv)
    return shlex.join(argv)
