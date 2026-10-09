"""Dialogs: generator selection, adding entries, preferences, command line."""

from __future__ import annotations

from dataclasses import dataclass

from qtpy.QtCore import Qt
from qtpy.QtGui import QFontDatabase, QGuiApplication
from qtpy.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
)

from ..cmake.capabilities import CMakeInfo
from .widgets import PathEdit


@dataclass
class GeneratorChoice:
    generator: str
    platform: str | None
    toolset: str | None
    toolchain_file: str | None


class GeneratorDialog(QDialog):
    """Pick a generator for a new build tree (cmake-gui's first-configure dialog)."""

    def __init__(self, info: CMakeInfo, default: str | None, build_dir: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Choose Generator")
        self._info = info

        intro = QLabel(
            f"<b>{build_dir}</b> has not been configured yet.<br>"
            "Choose how CMake should generate the build system."
        )
        intro.setWordWrap(True)

        self.generator = QComboBox()
        self.generator.addItems([g.name for g in info.generators])
        if default:
            self.generator.setCurrentText(default)
        self.platform = QComboBox()
        self.platform.setEditable(True)
        self.toolset = QLineEdit()
        self.toolset.setPlaceholderText("Default")
        self.toolchain = PathEdit(is_file=True, caption="Choose Toolchain File")
        self.toolchain.line_edit.setPlaceholderText("None — use native compilers")

        form = QFormLayout()
        form.addRow("Generator:", self.generator)
        form.addRow("Platform (-A):", self.platform)
        form.addRow("Toolset (-T):", self.toolset)
        form.addRow("Toolchain file:", self.toolchain)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Configure")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(buttons)

        self.generator.currentTextChanged.connect(self._update)
        self._update()
        self.resize(520, self.sizeHint().height())

    def _update(self) -> None:
        gen = self._info.generator(self.generator.currentText())
        self.platform.clear()
        self.platform.setEnabled(bool(gen and gen.platform_support))
        if gen and gen.supported_platforms:
            self.platform.addItems(["", *gen.supported_platforms])
        self.platform.lineEdit().setPlaceholderText("Default" if self.platform.isEnabled() else "Not supported")
        self.toolset.setEnabled(bool(gen and gen.toolset_support))

    def choice(self) -> GeneratorChoice:
        return GeneratorChoice(
            generator=self.generator.currentText(),
            platform=(self.platform.currentText().strip() or None) if self.platform.isEnabled() else None,
            toolset=(self.toolset.text().strip() or None) if self.toolset.isEnabled() else None,
            toolchain_file=self.toolchain.text().strip() or None,
        )


class AddEntryDialog(QDialog):
    TYPES = ("BOOL", "PATH", "FILEPATH", "STRING")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Cache Entry")
        self.name = QLineEdit()
        self.name.setPlaceholderText("e.g. BUILD_TESTING")
        self.type = QComboBox()
        self.type.addItems(self.TYPES)
        self.type.setCurrentText("STRING")

        self.bool_value = QCheckBox("ON")
        self.bool_value.toggled.connect(lambda on: self.bool_value.setText("ON" if on else "OFF"))
        self.path_value = PathEdit(is_file=False)
        self.file_value = PathEdit(is_file=True)
        self.string_value = QLineEdit()
        self.value_stack = QStackedWidget()
        for widget in (self.bool_value, self.path_value, self.file_value, self.string_value):
            self.value_stack.addWidget(widget)
        self.type.currentIndexChanged.connect(self.value_stack.setCurrentIndex)
        self.value_stack.setCurrentIndex(self.type.currentIndex())
        self.help = QLineEdit()
        self.help.setPlaceholderText("Optional description")

        form = QFormLayout()
        form.addRow("Name:", self.name)
        form.addRow("Type:", self.type)
        form.addRow("Value:", self.value_stack)
        form.addRow("Description:", self.help)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.name.textChanged.connect(self._validate)
        self._validate()

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.buttons)
        self.resize(460, self.sizeHint().height())

    def _validate(self) -> None:
        name = self.name.text().strip()
        ok = bool(name) and not any(c in name for c in '=:"')
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ok)

    def entry(self) -> tuple[str, str, str, str]:
        type_ = self.type.currentText()
        value = {
            "BOOL": "ON" if self.bool_value.isChecked() else "OFF",
            "PATH": self.path_value.text(),
            "FILEPATH": self.file_value.text(),
            "STRING": self.string_value.text(),
        }[type_]
        return self.name.text().strip(), type_, value, self.help.text().strip()


class PreferencesDialog(QDialog):
    def __init__(self, cmake_path: str, jobs: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.cmake_path = PathEdit(is_file=True, caption="Choose CMake Executable")
        self.cmake_path.setText(cmake_path)
        self.cmake_path.line_edit.setPlaceholderText("Find cmake on PATH")
        self.jobs = QSpinBox()
        self.jobs.setRange(0, 512)
        self.jobs.setSpecialValueText("Generator default")
        self.jobs.setValue(jobs)

        form = QFormLayout()
        form.addRow("CMake executable:", self.cmake_path)
        form.addRow("Parallel build jobs:", self.jobs)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.resize(520, self.sizeHint().height())


class CommandDialog(QDialog):
    """Shows the equivalent command line so it can be reused in scripts/CI."""

    def __init__(self, command: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Equivalent Command Line")
        label = QLabel("Running this in a terminal does the same as pressing Configure now:")
        label.setWordWrap(True)
        text = QPlainTextEdit(command)
        text.setReadOnly(True)
        text.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        copy = QPushButton("Copy")
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(command))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.addButton(copy, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(label)
        layout.addWidget(text)
        layout.addWidget(buttons)
        self.resize(720, 260)
        text.setFocus(Qt.FocusReason.OtherFocusReason)
