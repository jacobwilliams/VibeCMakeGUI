"""Small reusable widgets and the cache value delegate."""

from __future__ import annotations

from pathlib import Path

from qtpy.QtCore import QModelIndex, Qt, Signal
from qtpy.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QStyledItemDelegate,
    QToolButton,
    QWidget,
)

from .cache_model import VALUE_COLUMN, EntryItem, EntryRole


class PathEdit(QWidget):
    """Line edit with a browse button, for PATH and FILEPATH values."""

    editingFinished = Signal()

    def __init__(self, is_file: bool, parent=None, caption: str = "") -> None:
        super().__init__(parent)
        self._is_file = is_file
        self._caption = caption or ("Choose File" if is_file else "Choose Directory")
        self.line_edit = QLineEdit(self)
        self.line_edit.editingFinished.connect(self.editingFinished)
        browse = QToolButton(self)
        browse.setText("…")
        browse.setToolTip(self._caption)
        browse.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        browse.clicked.connect(self.browse)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self.line_edit, 1)
        layout.addWidget(browse)
        self.setFocusProxy(self.line_edit)
        self.setAutoFillBackground(True)

    def text(self) -> str:
        return self.line_edit.text()

    def setText(self, text: str) -> None:
        self.line_edit.setText(text)

    def browse(self) -> None:
        start = self.text() or str(Path.home())
        if self._is_file:
            path, _ = QFileDialog.getOpenFileName(self, self._caption, start)
        else:
            path = QFileDialog.getExistingDirectory(self, self._caption, start)
        if path:
            self.setText(path)
            self.editingFinished.emit()


class CacheValueDelegate(QStyledItemDelegate):
    """Type-aware editors: enum combos for STRINGS, browse buttons for paths."""

    def createEditor(self, parent, option, index: QModelIndex):
        item: EntryItem | None = index.data(EntryRole)
        if item is None or index.column() != VALUE_COLUMN:
            return super().createEditor(parent, option, index)
        if item.strings:
            combo = QComboBox(parent)
            combo.addItems(item.strings)
            combo.activated.connect(lambda _=0, c=combo: self._commit(c))
            return combo
        if item.type in ("PATH", "FILEPATH"):
            editor = PathEdit(item.type == "FILEPATH", parent, caption=item.name)
            editor.editingFinished.connect(lambda e=editor: self._commit(e))
            return editor
        return QLineEdit(parent)

    def _commit(self, editor) -> None:
        self.commitData.emit(editor)

    def setEditorData(self, editor, index: QModelIndex) -> None:
        value = index.data(Qt.ItemDataRole.EditRole) or ""
        if isinstance(editor, QComboBox):
            if editor.findText(value) < 0:
                editor.addItem(value)
            editor.setCurrentText(value)
        elif isinstance(editor, (PathEdit, QLineEdit)):
            editor.setText(value)
        else:
            super().setEditorData(editor, index)

    def setModelData(self, editor, model, index: QModelIndex) -> None:
        if isinstance(editor, QComboBox):
            model.setData(index, editor.currentText())
        elif isinstance(editor, (PathEdit, QLineEdit)):
            model.setData(index, editor.text())
        else:
            super().setModelData(editor, model, index)

    def updateEditorGeometry(self, editor, option, index: QModelIndex) -> None:
        editor.setGeometry(option.rect)
