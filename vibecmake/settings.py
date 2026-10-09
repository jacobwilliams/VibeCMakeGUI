"""Persistent application settings."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from qtpy.QtCore import QByteArray, QSettings

MAX_RECENT = 12


@dataclass
class RecentProject:
    source: str
    build: str
    preset: str = ""


class AppSettings:
    def __init__(self, settings: QSettings | None = None) -> None:
        self._s = settings or QSettings("VibeCMakeGUI", "VibeCMakeGUI")

    def _get(self, key: str, default, type_):
        value = self._s.value(key, default)
        if type_ is bool:
            return value in (True, "true", "1", 1)
        try:
            return type_(value)
        except (TypeError, ValueError):
            return default

    @property
    def cmake_path(self) -> str:
        return self._get("cmake/path", "", str)

    @cmake_path.setter
    def cmake_path(self, value: str) -> None:
        self._s.setValue("cmake/path", value)

    @property
    def build_jobs(self) -> int:
        return self._get("build/jobs", 0, int)

    @build_jobs.setter
    def build_jobs(self, value: int) -> None:
        self._s.setValue("build/jobs", value)

    @property
    def show_advanced(self) -> bool:
        return self._get("view/showAdvanced", False, bool)

    @show_advanced.setter
    def show_advanced(self, value: bool) -> None:
        self._s.setValue("view/showAdvanced", value)

    @property
    def grouped(self) -> bool:
        return self._get("view/grouped", True, bool)

    @grouped.setter
    def grouped(self, value: bool) -> None:
        self._s.setValue("view/grouped", value)

    def window_state(self) -> tuple[QByteArray | None, QByteArray | None, QByteArray | None]:
        return (
            self._s.value("window/geometry"),
            self._s.value("window/state"),
            self._s.value("window/splitter"),
        )

    def save_window_state(self, geometry: QByteArray, state: QByteArray, splitter: QByteArray) -> None:
        self._s.setValue("window/geometry", geometry)
        self._s.setValue("window/state", state)
        self._s.setValue("window/splitter", splitter)

    def recent_projects(self) -> list[RecentProject]:
        try:
            data = json.loads(self._get("recent/projects", "[]", str))
            return [RecentProject(**d) for d in data][:MAX_RECENT]
        except (TypeError, ValueError):
            return []

    def add_recent(self, project: RecentProject) -> None:
        recent = [r for r in self.recent_projects() if r.build != project.build]
        recent.insert(0, project)
        self._s.setValue("recent/projects", json.dumps([asdict(r) for r in recent[:MAX_RECENT]]))

    def remove_recent(self, build: str) -> None:
        recent = [r for r in self.recent_projects() if r.build != build]
        self._s.setValue("recent/projects", json.dumps([asdict(r) for r in recent]))

    def clear_recent(self) -> None:
        self._s.setValue("recent/projects", "[]")

    def build_dir_for_source(self, source: str) -> RecentProject | None:
        return next((r for r in self.recent_projects() if r.source == source), None)
