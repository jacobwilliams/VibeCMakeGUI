"""Item model for editing cache entries, with pending-change tracking."""

from __future__ import annotations

from dataclasses import dataclass, field

from qtpy.QtCore import QAbstractItemModel, QModelIndex, QSortFilterProxyModel, Qt, Signal
from qtpy.QtGui import QColor, QFont, QPalette
from qtpy.QtWidgets import QApplication

from ..cmake.cache import CacheEntry, CMakeCache, is_on
from ..cmake.command import CacheOverride

NAME_COLUMN = 0
VALUE_COLUMN = 1

EntryRole = Qt.ItemDataRole.UserRole + 1
AdvancedRole = Qt.ItemDataRole.UserRole + 2
IsGroupRole = Qt.ItemDataRole.UserRole + 3

UNGROUPED = "Ungrouped Entries"


@dataclass(eq=False)
class EntryItem:
    """A cache entry as shown in the GUI, plus any pending edit."""

    name: str
    type: str
    value: str
    help: str = ""
    advanced: bool = False
    strings: list[str] = field(default_factory=list)
    original: str | None = None  # None means the entry was added in the GUI
    is_new: bool = False  # appeared during the most recent configure
    removed: bool = False

    @classmethod
    def from_entry(cls, entry: CacheEntry, is_new: bool = False) -> EntryItem:
        return cls(
            name=entry.name,
            type=entry.type,
            value=entry.value,
            help=entry.help,
            advanced=entry.advanced,
            strings=list(entry.strings),
            original=entry.value,
            is_new=is_new,
        )

    @property
    def added(self) -> bool:
        return self.original is None

    @property
    def modified(self) -> bool:
        return self.added or self.removed or self.value != self.original


@dataclass(eq=False)
class Group:
    name: str
    items: list[EntryItem] = field(default_factory=list)


def group_name(name: str) -> str:
    prefix, sep, _ = name.partition("_")
    return prefix if sep and prefix else UNGROUPED


class CacheModel(QAbstractItemModel):
    """Flat or grouped tree of :class:`EntryItem` objects.

    Index internal ids: 0 for top-level rows, ``group_row + 1`` for entries
    under a group.
    """

    pendingChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._items: list[EntryItem] = []
        self._groups: list[Group] = []
        self._grouped = True

    # -- loading -----------------------------------------------------------

    def load(self, cache: CMakeCache | None, mark_new: bool = False, keep_pending: bool = True) -> None:
        """Replace the contents with *cache*.

        With *keep_pending*, edits that have not been applied yet survive the
        reload. With *mark_new*, entries that were not present before are
        flagged as new (the cmake-gui "red rows").
        """
        previous = {item.name: item for item in self._items}
        items: list[EntryItem] = []
        if cache is not None:
            for entry in cache.visible_entries:
                old = previous.get(entry.name)
                if mark_new:
                    is_new = old is None or old.added
                else:
                    is_new = old.is_new if old is not None else False
                item = EntryItem.from_entry(entry, is_new=is_new)
                if keep_pending and old is not None and not old.added:
                    if old.removed:
                        item.removed = True
                    elif old.value != old.original and old.value != entry.value:
                        item.value = old.value
                items.append(item)
        names = {i.name for i in items}
        if keep_pending:
            items += [i for i in previous.values() if i.added and i.name not in names]
        self.beginResetModel()
        self._items = items
        self._rebuild_groups()
        self.endResetModel()
        self.pendingChanged.emit()

    def clear(self) -> None:
        self.beginResetModel()
        self._items = []
        self._groups = []
        self.endResetModel()
        self.pendingChanged.emit()

    def set_grouped(self, grouped: bool) -> None:
        if grouped == self._grouped:
            return
        self.beginResetModel()
        self._grouped = grouped
        self._rebuild_groups()
        self.endResetModel()

    def is_grouped(self) -> bool:
        return self._grouped

    def _rebuild_groups(self) -> None:
        buckets: dict[str, list[EntryItem]] = {}
        for item in self._items:
            buckets.setdefault(group_name(item.name), []).append(item)
        ungrouped = buckets.pop(UNGROUPED, [])
        groups = []
        for name, items in buckets.items():
            if len(items) == 1:
                ungrouped += items
            else:
                groups.append(Group(name, items))
        groups.sort(key=lambda g: g.name.lower())
        if ungrouped:
            groups.insert(0, Group(UNGROUPED, ungrouped))
        self._groups = groups

    # -- queries -----------------------------------------------------------

    def items(self) -> list[EntryItem]:
        return list(self._items)

    def find(self, name: str) -> EntryItem | None:
        return next((i for i in self._items if i.name == name), None)

    def pending_items(self) -> list[EntryItem]:
        return [i for i in self._items if i.modified]

    def pending_overrides(self) -> list[CacheOverride]:
        return [
            CacheOverride(i.name, i.type, i.value)
            for i in self._items
            if i.modified and not i.removed
        ]

    def pending_removals(self) -> list[str]:
        return [i.name for i in self._items if i.removed and not i.added]

    def group_needs_attention(self, row: int) -> bool:
        """Whether the group at *row* holds new or modified entries."""
        if not self._grouped or not 0 <= row < len(self._groups):
            return False
        return any(i.is_new or i.modified for i in self._groups[row].items)

    def item(self, index: QModelIndex) -> EntryItem | None:
        if not index.isValid():
            return None
        if self._grouped:
            if index.internalId() == 0:
                return None
            group = self._groups[index.internalId() - 1]
            return group.items[index.row()]
        return self._items[index.row()]

    def index_of(self, item: EntryItem, column: int = NAME_COLUMN) -> QModelIndex:
        if self._grouped:
            for g, group in enumerate(self._groups):
                if item in group.items:
                    return self.createIndex(group.items.index(item), column, g + 1)
            return QModelIndex()
        if item in self._items:
            return self.createIndex(self._items.index(item), column, 0)
        return QModelIndex()

    # -- edits -------------------------------------------------------------

    def add_entry(self, name: str, type_: str, value: str, help_: str = "") -> EntryItem:
        existing = self.find(name)
        if existing is not None:
            existing.removed = False
            self.set_value(existing, value)
            return existing
        item = EntryItem(name=name, type=type_, value=value, help=help_, original=None)
        self.beginResetModel()
        self._items.append(item)
        self._rebuild_groups()
        self.endResetModel()
        self.pendingChanged.emit()
        return item

    def set_value(self, item: EntryItem, value: str) -> None:
        if item.value == value:
            return
        item.value = value
        self._item_changed(item)

    def remove(self, items: list[EntryItem]) -> None:
        dropped = [i for i in items if i.added]
        for item in items:
            if not item.added:
                item.removed = True
                self._item_changed(item, emit=False)
        if dropped:
            self.beginResetModel()
            self._items = [i for i in self._items if i not in dropped]
            self._rebuild_groups()
            self.endResetModel()
        self.pendingChanged.emit()

    def revert(self, items: list[EntryItem]) -> None:
        self.remove([i for i in items if i.added])
        for item in items:
            if item.added:
                continue
            item.removed = False
            item.value = item.original or ""
            self._item_changed(item, emit=False)
        self.pendingChanged.emit()

    def revert_all(self) -> None:
        self.revert(self.pending_items())

    def _item_changed(self, item: EntryItem, emit: bool = True) -> None:
        first = self.index_of(item, NAME_COLUMN)
        if first.isValid():
            self.dataChanged.emit(first, self.index_of(item, VALUE_COLUMN))
            parent = first.parent()
            if parent.isValid():
                self.dataChanged.emit(parent, parent.siblingAtColumn(VALUE_COLUMN))
        if emit:
            self.pendingChanged.emit()

    # -- QAbstractItemModel ------------------------------------------------

    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        if not parent.isValid():
            return self.createIndex(row, column, 0)
        return self.createIndex(row, column, parent.row() + 1)

    def parent(self, index: QModelIndex = QModelIndex()) -> QModelIndex:
        if not index.isValid() or not self._grouped or index.internalId() == 0:
            return QModelIndex()
        return self.createIndex(index.internalId() - 1, 0, 0)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if not parent.isValid():
            return len(self._groups) if self._grouped else len(self._items)
        if self._grouped and parent.internalId() == 0 and parent.column() == 0:
            return len(self._groups[parent.row()].items)
        return 0

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 2

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return ("Name", "Value")[section]
        return None

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        item = self.item(index)
        if item is None or index.column() != VALUE_COLUMN or item.removed:
            return flags
        if item.type == "BOOL":
            return flags | Qt.ItemFlag.ItemIsUserCheckable
        return flags | Qt.ItemFlag.ItemIsEditable

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        item = self.item(index)
        if item is None:
            return self._group_data(index, role)
        column = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if column == NAME_COLUMN:
                return item.name
            if item.type == "BOOL":
                return "ON" if is_on(item.value) else "OFF"
            return item.value
        if role == Qt.ItemDataRole.EditRole:
            return item.name if column == NAME_COLUMN else item.value
        if role == Qt.ItemDataRole.CheckStateRole and column == VALUE_COLUMN and item.type == "BOOL":
            return Qt.CheckState.Checked if is_on(item.value) else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.ToolTipRole:
            return _tooltip(item)
        if role == Qt.ItemDataRole.FontRole:
            font = QFont()
            font.setBold(item.modified and not item.removed)
            font.setStrikeOut(item.removed)
            return font
        if role == Qt.ItemDataRole.ForegroundRole:
            if item.removed:
                return QApplication.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
            return None
        if role == Qt.ItemDataRole.BackgroundRole:
            if item.modified and not item.removed:
                return _tint(QApplication.palette().color(QPalette.ColorRole.Highlight), 60)
            if item.is_new:
                return QColor(230, 60, 60, 70)
            return None
        if role == EntryRole:
            return item
        if role == AdvancedRole:
            return item.advanced
        if role == IsGroupRole:
            return False
        return None

    def _group_data(self, index: QModelIndex, role: int):
        group = self._groups[index.row()]
        if role == Qt.ItemDataRole.DisplayRole and index.column() == NAME_COLUMN:
            return group.name
        if role == Qt.ItemDataRole.FontRole:
            font = QFont()
            font.setBold(any(i.modified for i in group.items))
            return font
        if role == Qt.ItemDataRole.BackgroundRole and any(i.is_new for i in group.items):
            return QColor(230, 60, 60, 35)
        if role == IsGroupRole:
            return True
        return None

    def setData(self, index: QModelIndex, value, role: int = Qt.ItemDataRole.EditRole) -> bool:
        item = self.item(index)
        if item is None or index.column() != VALUE_COLUMN or item.removed:
            return False
        if role == Qt.ItemDataRole.CheckStateRole:
            checked = Qt.CheckState(value) == Qt.CheckState.Checked
            new_value = "ON" if checked else "OFF"
            # Keep the original spelling (e.g. TRUE/FALSE) when toggling back.
            if item.original is not None and is_on(item.original) == checked:
                new_value = item.original
            self.set_value(item, new_value)
            return True
        if role == Qt.ItemDataRole.EditRole:
            self.set_value(item, str(value))
            return True
        return False


def _tint(color: QColor, alpha: int) -> QColor:
    tinted = QColor(color)
    tinted.setAlpha(alpha)
    return tinted


def _tooltip(item: EntryItem) -> str:
    from html import escape

    parts = [f"<b>{escape(item.name)}</b> <i>({escape(item.type)})</i>"]
    if item.help:
        parts.append(escape(item.help).replace("\n", "<br>"))
    if item.added:
        parts.append("<i>Added — will be set on next configure.</i>")
    elif item.removed:
        parts.append("<i>Will be removed on next configure.</i>")
    elif item.modified:
        parts.append(f"<i>Was:</i> {escape(item.original or '')}")
    return "<br>".join(parts)


class CacheFilterProxy(QSortFilterProxyModel):
    """Filters by search text and the "show advanced" toggle."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._terms: list[str] = []
        self._show_advanced = False
        self._modified_only = False
        self.setRecursiveFilteringEnabled(True)
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setDynamicSortFilter(False)

    def set_search(self, text: str) -> None:
        self._refilter(lambda: setattr(self, "_terms", text.lower().split()))

    def set_show_advanced(self, show: bool) -> None:
        self._refilter(lambda: setattr(self, "_show_advanced", show))

    def set_modified_only(self, only: bool) -> None:
        self._refilter(lambda: setattr(self, "_modified_only", only))

    def _refilter(self, change) -> None:
        if hasattr(self, "beginFilterChange"):  # Qt >= 6.10
            self.beginFilterChange()
            change()
            self.endFilterChange(QSortFilterProxyModel.Direction.Rows)
        else:
            change()
            self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        model: CacheModel = self.sourceModel()
        index = model.index(source_row, NAME_COLUMN, source_parent)
        item = model.item(index)
        if item is None:
            return False  # groups are shown only when a child matches
        if item.advanced and not self._show_advanced and not item.modified:
            return False
        if self._modified_only and not (item.modified or item.is_new):
            return False
        haystack = f"{item.name}\n{item.value}".lower()
        return all(term in haystack for term in self._terms)

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        # Keep "Ungrouped Entries" at the top.
        left_ungrouped = bool(left.data(IsGroupRole)) and left.data() == UNGROUPED
        right_ungrouped = bool(right.data(IsGroupRole)) and right.data() == UNGROUPED
        if left_ungrouped != right_ungrouped:
            return left_ungrouped
        return str(left.data() or "").lower() < str(right.data() or "").lower()
