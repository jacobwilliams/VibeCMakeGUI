"""Extracting errors and warnings from CMake and compiler output."""

from __future__ import annotations

import re
from dataclasses import dataclass

_CMAKE_HEADER_RE = re.compile(
    r"^CMake (?P<sev>Error|Warning|Deprecation Warning|Deprecation Error)"
    r"(?: \((?:dev|dev-warning)\))?"
    r"(?: at (?P<file>.+?):(?P<line>\d+) \((?P<cmd>[^)]*)\))?:\s*(?P<msg>.*)$"
)
_GCC_RE = re.compile(
    r"^(?P<file>(?:[A-Za-z]:)?[^:\s][^:]*?):(?P<line>\d+):(?:(?P<col>\d+):)?\s+"
    r"(?:fatal )?(?P<sev>error|warning):\s+(?P<msg>.*)$"
)
_MSVC_RE = re.compile(
    r"^\s*(?P<file>[^()]+?)\((?P<line>\d+)(?:,(?P<col>\d+))?\)\s*:\s*"
    r"(?:fatal )?(?P<sev>error|warning)\s+(?P<code>\w+)\s*:\s*(?P<msg>.*)$"
)
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


@dataclass
class Problem:
    severity: str  # "error" or "warning"
    message: str
    file: str | None = None
    line: int | None = None
    column: int | None = None
    source: str = "cmake"  # "cmake" or "build"

    @property
    def location(self) -> str:
        if not self.file:
            return ""
        loc = self.file
        if self.line is not None:
            loc += f":{self.line}"
            if self.column is not None:
                loc += f":{self.column}"
        return loc


class ProblemParser:
    """Feed lines of output; collect :class:`Problem` objects."""

    def __init__(self) -> None:
        self.problems: list[Problem] = []
        self._current: Problem | None = None
        self._lines: list[str] = []
        self._in_call_stack = False

    def feed(self, line: str) -> list[Problem]:
        """Process one line. Returns any problems completed by it."""
        line = strip_ansi(line.rstrip("\r\n"))
        if self._current is not None:
            if line.startswith(" ") or not line.strip():
                if line.strip().startswith("Call Stack"):
                    self._in_call_stack = True
                elif line.strip() and not self._in_call_stack:
                    self._lines.append(line.strip())
                return []
            done = self._flush()
            started = self._match(line)
            return [p for p in (done, started) if p is not None]
        started = self._match(line)
        return [started] if started is not None else []

    def finish(self) -> list[Problem]:
        done = self._flush()
        return [done] if done is not None else []

    def _match(self, line: str) -> Problem | None:
        m = _CMAKE_HEADER_RE.match(line)
        if m:
            severity = "error" if "Error" in m.group("sev") else "warning"
            self._current = Problem(
                severity=severity,
                message="",
                file=m.group("file"),
                line=int(m.group("line")) if m.group("line") else None,
            )
            self._lines = [m.group("msg")] if m.group("msg") else []
            self._in_call_stack = False
            return None
        m = _GCC_RE.match(line) or _MSVC_RE.match(line)
        if m:
            problem = Problem(
                severity=m.group("sev"),
                message=m.group("msg").strip(),
                file=m.group("file").strip(),
                line=int(m.group("line")),
                column=int(m.group("col")) if m.group("col") else None,
                source="build",
            )
            self.problems.append(problem)
            return problem
        return None

    def _flush(self) -> Problem | None:
        problem = self._current
        if problem is None:
            return None
        problem.message = " ".join(self._lines).strip() or "(no message)"
        self.problems.append(problem)
        self._current = None
        self._lines = []
        return problem
