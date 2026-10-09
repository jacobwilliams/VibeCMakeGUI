"""Bottom panels: build output, problems and targets."""

from __future__ import annotations

import re

from qtpy.QtCore import Qt, Signal
from qtpy.QtGui import QColor, QFont, QFontDatabase, QIcon, QSyntaxHighlighter, QTextCharFormat, QTextCursor
from qtpy.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QStyle,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..cmake.fileapi import Target
from ..cmake.problems import Problem, strip_ansi


class _LogHighlighter(QSyntaxHighlighter):
    _RULES = [
        (re.compile(r"^(CMake Error|.*\berror\b[: ]|.*\bfatal\b|FAILED:)", re.I), QColor(220, 60, 60), True),
        (re.compile(r"^(CMake (Deprecation )?Warning|.*\bwarning\b[: ])", re.I), QColor(214, 150, 20), True),
        (re.compile(r"^\$ "), QColor(90, 140, 230), True),
        (re.compile(r"^(-- (Configuring done|Generating done|Build files have been written)|✔)"), QColor(60, 170, 90), False),
        (re.compile(r"^-- "), None, False),
    ]

    def highlightBlock(self, text: str) -> None:
        for regex, color, bold in self._RULES:
            if regex.match(text):
                fmt = QTextCharFormat()
                if color is not None:
                    fmt.setForeground(color)
                if bold:
                    fmt.setFontWeight(QFont.Weight.DemiBold)
                if color is None:
                    fmt.setForeground(QColor(128, 128, 128))
                self.setFormat(0, len(text), fmt)
                return


class OutputPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.view = QPlainTextEdit(self)
        self.view.setReadOnly(True)
        self.view.setUndoRedoEnabled(False)
        self.view.setMaximumBlockCount(100_000)
        self.view.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.view.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self._highlighter = _LogHighlighter(self.view.document())

        self.find_edit = QLineEdit(self)
        self.find_edit.setPlaceholderText("Find in output")
        self.find_edit.setClearButtonEnabled(True)
        self.find_edit.returnPressed.connect(self.find_next)
        wrap = QCheckBox("Wrap", self)
        wrap.toggled.connect(
            lambda on: self.view.setLineWrapMode(
                QPlainTextEdit.LineWrapMode.WidgetWidth if on else QPlainTextEdit.LineWrapMode.NoWrap
            )
        )
        clear = QPushButton("Clear", self)
        clear.clicked.connect(self.view.clear)

        bar = QHBoxLayout()
        bar.setContentsMargins(6, 4, 6, 0)
        bar.addWidget(self.find_edit, 1)
        bar.addWidget(wrap)
        bar.addWidget(clear)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addLayout(bar)
        layout.addWidget(self.view, 1)

    def append(self, text: str) -> None:
        bar = self.view.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 4
        self.view.appendPlainText(strip_ansi(text))
        if at_bottom:
            bar.setValue(bar.maximum())

    def clear(self) -> None:
        self.view.clear()

    def find_next(self) -> None:
        text = self.find_edit.text()
        if text and not self.view.find(text):
            self.view.moveCursor(QTextCursor.MoveOperation.Start)
            self.view.find(text)


class ProblemsPanel(QTreeWidget):
    problemActivated = Signal(object)  # Problem
    countChanged = Signal(int, int)  # errors, warnings

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setHeaderLabels(["Message", "Location"])
        self.setRootIsDecorated(False)
        self.setAlternatingRowColors(True)
        self.setUniformRowHeights(True)
        self.setFrameShape(QTreeWidget.Shape.NoFrame)
        self.setColumnWidth(0, 640)
        self.itemActivated.connect(lambda item, _col: self.problemActivated.emit(item.data(0, Qt.ItemDataRole.UserRole)))
        style = self.style()
        self._icons = {
            "error": style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxCritical),
            "warning": style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning),
        }
        self._errors = self._warnings = 0

    def add(self, problem: Problem) -> None:
        item = QTreeWidgetItem([problem.message, problem.location])
        item.setIcon(0, self._icons.get(problem.severity, QIcon()))
        item.setToolTip(0, problem.message)
        item.setData(0, Qt.ItemDataRole.UserRole, problem)
        self.addTopLevelItem(item)
        if problem.severity == "error":
            self._errors += 1
        else:
            self._warnings += 1
        self.countChanged.emit(self._errors, self._warnings)

    def clear(self) -> None:
        super().clear()
        self._errors = self._warnings = 0
        self.countChanged.emit(0, 0)


_TARGET_TYPE_LABELS = {
    "EXECUTABLE": "Executable",
    "STATIC_LIBRARY": "Static library",
    "SHARED_LIBRARY": "Shared library",
    "MODULE_LIBRARY": "Module library",
    "OBJECT_LIBRARY": "Object library",
    "INTERFACE_LIBRARY": "Interface library",
    "UTILITY": "Utility",
}


class TargetsPanel(QTreeWidget):
    buildRequested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setHeaderLabels(["Target", "Type", "Directory"])
        self.setRootIsDecorated(False)
        self.setAlternatingRowColors(True)
        self.setUniformRowHeights(True)
        self.setSortingEnabled(True)
        self.setFrameShape(QTreeWidget.Shape.NoFrame)
        self.setColumnWidth(0, 260)
        self.setColumnWidth(1, 140)
        self.itemActivated.connect(lambda item, _col: self.buildRequested.emit(item.text(0)))
        self.setToolTip("Double-click a target to build it")

    def set_targets(self, targets: list[Target]) -> None:
        self.clear()
        for target in targets:
            item = QTreeWidgetItem([target.name, _TARGET_TYPE_LABELS.get(target.type, target.type), target.directory])
            if target.artifacts:
                item.setToolTip(0, "\n".join(target.artifacts))
            self.addTopLevelItem(item)
        self.sortByColumn(0, Qt.SortOrder.AscendingOrder)
