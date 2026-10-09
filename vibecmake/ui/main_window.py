"""The main application window."""

from __future__ import annotations

import shutil
from html import escape
from pathlib import Path

from qtpy.QtCore import QFileSystemWatcher, QModelIndex, QProcess, QSize, Qt, QTimer, QUrl
from qtpy.QtGui import QAction, QDesktopServices, QFont, QGuiApplication, QIcon, QKeySequence
from qtpy.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QCompleter,
    QFileDialog,
    QFileSystemModel,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStyle,
    QTabWidget,
    QToolBar,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..cmake.cache import CACHE_FILENAME, cache_path, read_cache
from ..cmake.capabilities import CMakeInfo, default_generator, find_cmake, query_cmake
from ..cmake.command import ConfigureRequest, build_args, configure_args, format_command
from ..cmake.fileapi import CodeModel, read_codemodel, write_query
from ..cmake.presets import ConfigurePreset, load_configure_presets
from ..cmake.problems import Problem, ProblemParser
from ..settings import AppSettings, RecentProject
from .cache_model import NAME_COLUMN, VALUE_COLUMN, CacheFilterProxy, CacheModel, EntryItem, EntryRole
from .dialogs import AddEntryDialog, CommandDialog, GeneratorChoice, GeneratorDialog, PreferencesDialog
from .panels import OutputPanel, ProblemsPanel, TargetsPanel
from .runner import ProcessRunner
from .widgets import CacheValueDelegate

WELCOME_PAGE, EDITOR_PAGE = 0, 1
APP_NAME = "VibeCMake"


def _icon(theme: QIcon.ThemeIcon, fallback: QStyle.StandardPixmap) -> QIcon:
    return QIcon.fromTheme(theme, QApplication.style().standardIcon(fallback))


class PathCombo(QComboBox):
    """Editable combo for directories with completion and a history."""

    def __init__(self, placeholder: str, parent=None) -> None:
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.lineEdit().setPlaceholderText(placeholder)
        fs_model = QFileSystemModel(self)
        fs_model.setRootPath("")
        fs_model.setFilter(fs_model.filter() & ~fs_model.filter().Files)
        completer = QCompleter(fs_model, self)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.setCompleter(completer)

    def set_history(self, paths: list[str]) -> None:
        text = self.currentText()
        self.blockSignals(True)
        self.clear()
        self.addItems(list(dict.fromkeys(paths)))
        self.setEditText(text)
        self.blockSignals(False)

    def set_path(self, path: Path | None) -> None:
        self.blockSignals(True)
        self.setEditText(str(path) if path else "")
        self.blockSignals(False)


class MainWindow(QMainWindow):
    def __init__(self, settings: AppSettings) -> None:
        super().__init__()
        self.settings = settings
        self.info: CMakeInfo | None = None
        self.source_dir: Path | None = None
        self.build_dir: Path | None = None
        self.presets: list[ConfigurePreset] = []
        self.codemodel: CodeModel | None = None
        self._operation: str | None = None
        self._build_after_configure: str | None = None
        self._problem_parser = ProblemParser()

        self.runner = ProcessRunner(self)
        self.runner.line.connect(self._on_output_line)
        self.runner.finished.connect(self._on_process_finished)

        self.model = CacheModel(self)
        self.model.pendingChanged.connect(self._update_ui)
        self.proxy = CacheFilterProxy(self)
        self.proxy.setSourceModel(self.model)

        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(lambda _path: self._reload_timer.start())
        self._reload_timer = QTimer(self, singleShot=True, interval=400)
        self._reload_timer.timeout.connect(self._reload_cache_from_disk)

        self.setWindowTitle(APP_NAME)
        self.setAcceptDrops(True)
        self.setUnifiedTitleAndToolBarOnMac(True)
        self._create_actions()
        self._build_ui()
        self._build_menus()
        self._build_toolbar()
        self._build_status_bar()
        self._load_cmake()
        self._restore_state()
        self._refresh_recent()
        self._update_targets()
        self._update_ui()

    # ------------------------------------------------------------------ UI

    def _create_actions(self) -> None:
        def action(text, slot, shortcut=None, icon=None, tip=None, checkable=False) -> QAction:
            act = QAction(text, self)
            # Don't let Qt guess macOS app-menu roles from the text: it would
            # treat "Configure" as Preferences. Roles are set explicitly below.
            act.setMenuRole(QAction.MenuRole.NoRole)
            if shortcut:
                act.setShortcut(QKeySequence(shortcut))
            if icon is not None:
                act.setIcon(icon)
            if tip:
                act.setToolTip(tip)
                act.setStatusTip(tip)
            act.setCheckable(checkable)
            (act.toggled if checkable else act.triggered).connect(slot)
            return act

        TI, SP = QIcon.ThemeIcon, QStyle.StandardPixmap
        self.act_open_source = action("Open Source Folder…", self.browse_source, QKeySequence.StandardKey.Open,
                                      _icon(TI.FolderOpen, SP.SP_DirOpenIcon))
        self.act_open_build = action("Open Build Folder…", self.browse_build, "Ctrl+Shift+O")
        self.act_preferences = action("Preferences…", self.show_preferences, QKeySequence.StandardKey.Preferences)
        self.act_preferences.setMenuRole(QAction.MenuRole.PreferencesRole)
        self.act_quit = action("Quit", self.close, QKeySequence.StandardKey.Quit)
        self.act_quit.setMenuRole(QAction.MenuRole.QuitRole)

        self.act_configure = action("Configure", lambda: self.configure(), "F5",
                                    _icon(TI.ViewRefresh, SP.SP_BrowserReload),
                                    "Run CMake to configure and generate the build system (F5)")
        self.act_fresh = action("Fresh Configure…", lambda: self.configure(fresh=True), "Shift+F5",
                                tip="Discard the cache and configure from scratch (--fresh)")
        self.act_build = action("Build", lambda: self.build(), "F7",
                                _icon(TI.MediaPlaybackStart, SP.SP_MediaPlay),
                                "Build the selected target (F7)")
        self.act_stop = action("Stop", self.stop, "Ctrl+.", _icon(TI.ProcessStop, SP.SP_BrowserStop),
                               "Stop the running CMake process")
        self.act_command = action("Show Command Line…", self.show_command, "Ctrl+Shift+L",
                                  tip="Show the equivalent cmake command line")
        self.act_open_ide = action("Open in IDE", self.open_in_ide, "Ctrl+Shift+I",
                                   _icon(TI.DocumentOpen, SP.SP_FileDialogStart),
                                   "Open the generated project (Xcode / Visual Studio)")
        self.act_reveal_build = action("Show Build Folder", self.reveal_build_dir,
                                       icon=_icon(TI.FolderOpen, SP.SP_DirOpenIcon),
                                       tip="Open the build folder in the file manager")
        self.act_delete_cache = action("Delete Cache…", self.delete_cache, tip="Delete CMakeCache.txt and CMakeFiles/")
        self.act_reload = action("Reload Cache", self._reload_cache_from_disk, "Ctrl+Shift+R")

        self.act_add = action("Add Entry…", self.add_entry, "Ctrl+Shift+N", _icon(TI.ListAdd, SP.SP_FileDialogNewFolder),
                              "Add a new cache entry")
        self.act_remove = action("Remove Entry", self.remove_selected, QKeySequence.StandardKey.Delete,
                                 _icon(TI.ListRemove, SP.SP_TrashIcon), "Remove the selected cache entries")
        self.act_remove.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.act_revert = action("Revert Selected", self.revert_selected, tip="Undo pending changes to the selection")
        self.act_revert_all = action("Revert All Changes", self.revert_all, "Ctrl+Shift+Z",
                                     _icon(TI.DocumentRevert, SP.SP_DialogResetButton),
                                     "Discard all pending changes")
        self.act_find = action("Find Entry", lambda: (self.search.setFocus(), self.search.selectAll()),
                               QKeySequence.StandardKey.Find)

        self.act_advanced = action("Show Advanced Entries", self._set_show_advanced, "Ctrl+Shift+A", checkable=True)
        self.act_grouped = action("Group Entries", self._set_grouped, "Ctrl+Shift+G", checkable=True)
        self.act_changed_only = action("Show Only Changed/New", self._set_changed_only, checkable=True)

        self.act_docs = action("CMake Documentation", lambda: QDesktopServices.openUrl(
            QUrl("https://cmake.org/cmake/help/latest/")))
        self.act_var_docs = action("Look Up Selected Entry", self.lookup_docs, "F1")
        self.act_about = action("About VibeCMake", self.show_about)
        self.act_about.setMenuRole(QAction.MenuRole.AboutRole)

    def _build_ui(self) -> None:
        # Project header: source / preset / build
        self.source_combo = PathCombo("Folder containing the top-level CMakeLists.txt")
        self.source_combo.lineEdit().editingFinished.connect(self._source_edited)
        self.source_combo.activated.connect(lambda _i: self._source_edited())
        self.build_combo = PathCombo("Folder for the generated build system")
        self.build_combo.lineEdit().editingFinished.connect(self._build_edited)
        self.build_combo.activated.connect(lambda _i: self._build_edited())
        self.preset_combo = QComboBox()
        self.preset_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.preset_combo.currentIndexChanged.connect(self._preset_changed)
        self.preset_label = QLabel("Preset:")

        def browse_button(slot, tip):
            button = QToolButton()
            button.setText("Browse…")
            button.setToolTip(tip)
            button.clicked.connect(slot)
            return button

        header = QWidget()
        grid = QGridLayout(header)
        grid.setContentsMargins(10, 8, 10, 4)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        grid.addWidget(QLabel("Source:"), 0, 0)
        grid.addWidget(self.source_combo, 0, 1)
        grid.addWidget(browse_button(self.browse_source, "Choose the source folder"), 0, 2)
        grid.addWidget(self.preset_label, 1, 0)
        preset_row = QHBoxLayout()
        preset_row.addWidget(self.preset_combo)
        self.preset_description = QLabel()
        self.preset_description.setStyleSheet("color: palette(placeholder-text);")
        preset_row.addWidget(self.preset_description, 1)
        grid.addLayout(preset_row, 1, 1, 1, 2)
        grid.addWidget(QLabel("Build:"), 2, 0)
        grid.addWidget(self.build_combo, 2, 1)
        grid.addWidget(browse_button(self.browse_build, "Choose the build folder"), 2, 2)
        grid.setColumnStretch(1, 1)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_welcome_page())
        self.stack.addWidget(self._build_editor_page())

        self.output = OutputPanel()
        self.problems = ProblemsPanel()
        self.problems.problemActivated.connect(self.open_problem)
        self.problems.countChanged.connect(self._problem_count_changed)
        self.targets = TargetsPanel()
        self.targets.buildRequested.connect(lambda name: self.build(name))
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self.output, "Output")
        self.tabs.addTab(self.problems, "Problems")
        self.tabs.addTab(self.targets, "Targets")

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.addWidget(self.stack)
        self.splitter.addWidget(self.tabs)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setChildrenCollapsible(False)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(header)
        layout.addWidget(self.splitter, 1)
        self.setCentralWidget(central)

    def _build_welcome_page(self) -> QWidget:
        page = QWidget()
        title = QLabel(APP_NAME)
        font = title.font()
        font.setPointSizeF(font.pointSizeF() * 2.2)
        font.setWeight(QFont.Weight.Bold)
        title.setFont(font)
        subtitle = QLabel("Open a CMake project to get started — or drop a folder onto this window.")
        subtitle.setStyleSheet("color: palette(placeholder-text);")

        open_source = QPushButton("Open Source Folder…")
        open_source.setDefault(True)
        open_source.clicked.connect(self.browse_source)
        open_build = QPushButton("Open Existing Build Folder…")
        open_build.clicked.connect(self.browse_build)
        buttons = QHBoxLayout()
        buttons.addWidget(open_source)
        buttons.addWidget(open_build)
        buttons.addStretch(1)

        self.recent_list = QListWidget()
        self.recent_list.setMaximumWidth(720)
        self.recent_list.setAlternatingRowColors(True)
        self.recent_list.itemActivated.connect(lambda item: self.open_recent(item.data(Qt.ItemDataRole.UserRole)))
        self.recent_label = QLabel("<b>Recent projects</b>")

        inner = QVBoxLayout()
        inner.addStretch(1)
        inner.addWidget(title)
        inner.addWidget(subtitle)
        inner.addSpacing(12)
        inner.addLayout(buttons)
        inner.addSpacing(16)
        inner.addWidget(self.recent_label)
        inner.addWidget(self.recent_list, 3)
        inner.addStretch(1)
        outer = QHBoxLayout(page)
        outer.addStretch(1)
        outer.addLayout(inner, 4)
        outer.addStretch(1)
        return page

    def _build_editor_page(self) -> QWidget:
        page = QWidget()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search entries by name or value")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._search_changed)

        def toggle_box(act: QAction, label: str) -> QCheckBox:
            box = QCheckBox(label)
            # The macOS style lays out checkboxes by a rect smaller than the
            # widget, which makes neighbours overlap; use the real geometry.
            box.setAttribute(Qt.WidgetAttribute.WA_LayoutUsesWidgetRect)
            box.setToolTip(act.text())
            box.setChecked(act.isChecked())
            box.toggled.connect(act.setChecked)
            act.toggled.connect(box.setChecked)
            return box

        self.advanced_box = toggle_box(self.act_advanced, "Advanced")
        self.grouped_box = toggle_box(self.act_grouped, "Grouped")
        self.changed_box = toggle_box(self.act_changed_only, "Changed only")

        def tool_button(act: QAction) -> QToolButton:
            button = QToolButton()
            button.setDefaultAction(act)
            button.setAutoRaise(True)
            return button

        bar = QHBoxLayout()
        bar.setContentsMargins(10, 6, 10, 0)
        bar.setSpacing(10)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.advanced_box)
        bar.addWidget(self.grouped_box)
        bar.addWidget(self.changed_box)
        bar.addSpacing(8)
        bar.addWidget(tool_button(self.act_add))
        bar.addWidget(tool_button(self.act_remove))
        bar.addWidget(tool_button(self.act_revert_all))

        self.view = QTreeView()
        self.view.setModel(self.proxy)
        self.view.setItemDelegateForColumn(VALUE_COLUMN, CacheValueDelegate(self.view))
        self.view.setSortingEnabled(True)
        self.view.sortByColumn(NAME_COLUMN, Qt.SortOrder.AscendingOrder)
        self.view.setAlternatingRowColors(True)
        self.view.setUniformRowHeights(True)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.view.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._show_context_menu)
        self.view.header().setSectionResizeMode(NAME_COLUMN, QHeaderView.ResizeMode.Interactive)
        self.view.header().setStretchLastSection(True)
        self.view.setColumnWidth(NAME_COLUMN, 360)
        self.view.selectionModel().currentChanged.connect(lambda cur, _prev: self._show_entry_info(cur))
        self.view.addAction(self.act_remove)

        self.entry_info = QLabel()
        self.entry_info.setWordWrap(True)
        self.entry_info.setTextFormat(Qt.TextFormat.RichText)
        self.entry_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.entry_info.setContentsMargins(10, 4, 10, 6)
        self.entry_info.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.entry_info.hide()
        self.entry_info.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        hint = QWidget()
        hint_layout = QVBoxLayout(hint)
        hint_layout.addStretch(1)
        self.hint_label = QLabel()
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint_label.setWordWrap(True)
        hint_button = QPushButton("Configure")
        hint_button.clicked.connect(lambda: self.configure())
        hint_layout.addWidget(self.hint_label)
        hint_layout.addWidget(hint_button, 0, Qt.AlignmentFlag.AlignCenter)
        hint_layout.addStretch(2)
        self.view_stack = QStackedWidget()
        self.view_stack.addWidget(self.view)
        self.view_stack.addWidget(hint)

        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(bar)
        layout.addSpacing(4)
        layout.addWidget(self.view_stack, 1)
        layout.addWidget(self.entry_info)
        return page

    def _build_menus(self) -> None:
        bar = self.menuBar()
        file_menu = bar.addMenu("&File")
        file_menu.addActions([self.act_open_source, self.act_open_build])
        self.recent_menu = file_menu.addMenu("Open Recent")
        self.recent_menu.aboutToShow.connect(self._fill_recent_menu)
        file_menu.addSeparator()
        file_menu.addAction(self.act_reveal_build)
        file_menu.addSeparator()
        file_menu.addActions([self.act_preferences, self.act_quit])

        edit_menu = bar.addMenu("&Edit")
        edit_menu.addActions([self.act_add, self.act_remove, self.act_revert])
        edit_menu.addSeparator()
        edit_menu.addActions([self.act_revert_all, self.act_find])

        view_menu = bar.addMenu("&View")
        view_menu.addActions([self.act_advanced, self.act_grouped, self.act_changed_only])

        cmake_menu = bar.addMenu("&CMake")
        cmake_menu.addActions([self.act_configure, self.act_fresh, self.act_build, self.act_stop])
        cmake_menu.addSeparator()
        cmake_menu.addActions([self.act_command, self.act_open_ide, self.act_reload])
        cmake_menu.addSeparator()
        cmake_menu.addAction(self.act_delete_cache)

        help_menu = bar.addMenu("&Help")
        help_menu.addActions([self.act_var_docs, self.act_docs, self.act_about])

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main")
        toolbar.setObjectName("mainToolbar")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toolbar.setIconSize(QSize(18, 18))
        toolbar.addAction(self.act_configure)
        toolbar.addSeparator()
        toolbar.addAction(self.act_build)
        self.target_combo = QComboBox()
        self.target_combo.setToolTip("Target to build")
        self.target_combo.setMinimumContentsLength(14)
        self.target_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        toolbar.addWidget(self.target_combo)
        self.config_combo = QComboBox()
        self.config_combo.setToolTip("Configuration to build")
        self.config_action = toolbar.addWidget(self.config_combo)
        toolbar.addAction(self.act_stop)
        toolbar.addSeparator()
        toolbar.addAction(self.act_open_ide)
        toolbar.addAction(self.act_reveal_build)
        self.addToolBar(toolbar)

    def _build_status_bar(self) -> None:
        status = self.statusBar()
        self.pending_label = QLabel()
        self.generator_label = QLabel()
        self.cmake_label = QLabel()
        for label in (self.pending_label, self.generator_label, self.cmake_label):
            label.setContentsMargins(8, 0, 8, 0)
            status.addPermanentWidget(label)

    # ------------------------------------------------------------- state

    def _load_cmake(self) -> None:
        executable = find_cmake(self.settings.cmake_path or None)
        self.info = None
        if executable:
            try:
                self.info = query_cmake(executable)
            except Exception as exc:  # noqa: BLE001 - surface anything to the user
                self.output.append(f"Could not query {executable}: {exc}")
        if self.info:
            self.cmake_label.setText(f"CMake {self.info.version}")
            self.cmake_label.setToolTip(self.info.executable)
        else:
            self.cmake_label.setText("⚠ CMake not found")
            self.cmake_label.setToolTip("Set the CMake executable in Preferences")
        self.act_fresh.setEnabled(bool(self.info and self.info.has_fresh))

    def _restore_state(self) -> None:
        geometry, state, splitter = self.settings.window_state()
        if geometry is not None:
            self.restoreGeometry(geometry)
        else:
            self.resize(1100, 820)
        if state is not None:
            self.restoreState(state)
        if splitter is not None:
            self.splitter.restoreState(splitter)
        self.act_advanced.setChecked(self.settings.show_advanced)
        self.act_grouped.setChecked(self.settings.grouped)
        self.proxy.set_show_advanced(self.settings.show_advanced)
        self.model.set_grouped(self.settings.grouped)

    def _update_ui(self) -> None:
        running = self.runner.is_running()
        has_cache = self.build_dir is not None and cache_path(self.build_dir).exists()
        ready = self.info is not None and self.source_dir is not None and self.build_dir is not None

        self.stack.setCurrentIndex(EDITOR_PAGE if (self.source_dir or self.build_dir) else WELCOME_PAGE)
        if self.model.rowCount() or has_cache:
            self.view_stack.setCurrentIndex(0)
        else:
            self.view_stack.setCurrentIndex(1)
            if self.info is None:
                self.hint_label.setText("CMake could not be found. Set its location in Preferences.")
            elif self.source_dir and not (self.source_dir / "CMakeLists.txt").exists():
                self.hint_label.setText(f"No CMakeLists.txt in {escape(str(self.source_dir))}.")
            else:
                self.hint_label.setText(
                    "This build folder has not been configured yet.\n"
                    "Press Configure (F5) to run CMake and populate the cache."
                )
        self.stack.widget(EDITOR_PAGE).setEnabled(not running)

        self.act_configure.setEnabled(ready and not running)
        self.act_fresh.setEnabled(ready and not running and has_cache and bool(self.info and self.info.has_fresh))
        self.act_build.setEnabled(self.info is not None and has_cache and not running)
        self.act_stop.setEnabled(running)
        self.act_command.setEnabled(ready)
        self.act_delete_cache.setEnabled(has_cache and not running)
        self.act_reload.setEnabled(has_cache and not running)
        self.act_reveal_build.setEnabled(self.build_dir is not None and self.build_dir.exists())
        generator = self.model_generator()
        gen_info = self.info.generator(generator) if self.info else None
        self.act_open_ide.setEnabled(bool(gen_info and gen_info.can_open and has_cache))
        self.act_open_ide.setVisible(bool(gen_info and gen_info.can_open))

        pending = len(self.model.pending_items())
        self.act_revert_all.setEnabled(pending > 0)
        self.pending_label.setText(f"{pending} pending change{'s' if pending != 1 else ''}" if pending else "")
        self.generator_label.setText(generator or "")
        self.setWindowModified(pending > 0)
        project = self.model.find("CMAKE_PROJECT_NAME")
        name = (project.value if project else None) or (self.source_dir.name if self.source_dir else None)
        self.setWindowTitle(f"{name}[*] — {APP_NAME}" if name else APP_NAME)

        has_presets = bool(self.presets)
        self.preset_label.setVisible(has_presets)
        self.preset_combo.setVisible(has_presets)
        self.preset_description.setVisible(has_presets)
        self.config_action.setVisible(bool(self.codemodel and self.codemodel.multi_config))

    def model_generator(self) -> str | None:
        item = self.model.find("CMAKE_GENERATOR")
        if item is not None:
            return item.value
        if self.build_dir is not None:
            cache = read_cache(self.build_dir)
            if cache is not None:
                return cache.generator
        return self.codemodel.generator if self.codemodel else None

    # ---------------------------------------------------- project selection

    def browse_source(self) -> None:
        start = str(self.source_dir or Path.home())
        path = QFileDialog.getExistingDirectory(self, "Choose Source Folder", start)
        if path:
            self.set_source_dir(Path(path))

    def browse_build(self) -> None:
        start = str(self.build_dir or self.source_dir or Path.home())
        path = QFileDialog.getExistingDirectory(self, "Choose Build Folder", start)
        if path:
            self.set_build_dir(Path(path))

    def _source_edited(self) -> None:
        text = self.source_combo.currentText().strip()
        path = Path(text).expanduser() if text else None
        if path != self.source_dir:
            self.set_source_dir(path)

    def _build_edited(self) -> None:
        text = self.build_combo.currentText().strip()
        path = Path(text).expanduser() if text else None
        if path != self.build_dir:
            self.set_build_dir(path)

    def open_path(self, path: str | Path) -> None:
        """Open whatever the user pointed at: a source tree, build tree or file."""
        p = Path(path).expanduser().resolve()
        if p.is_file():
            if p.name == CACHE_FILENAME:
                self.set_build_dir(p.parent)
            elif p.name in ("CMakeLists.txt", "CMakePresets.json", "CMakeUserPresets.json"):
                self.set_source_dir(p.parent)
            else:
                self.statusBar().showMessage(f"Don't know how to open {p}", 5000)
            return
        if (p / CACHE_FILENAME).exists():
            self.set_build_dir(p)
        else:
            self.set_source_dir(p)

    def open_recent(self, recent: RecentProject) -> None:
        if not self._confirm_discard():
            return
        self.set_source_dir(Path(recent.source), choose_build=False, confirm=False)
        if recent.preset:
            self._select_preset(recent.preset, apply_binary_dir=False)
        self.set_build_dir(Path(recent.build), sync_source=False, confirm=False)

    def set_source_dir(self, path: Path | None, choose_build: bool = True, confirm: bool = True) -> None:
        if confirm and path != self.source_dir and not self._confirm_discard():
            self.source_combo.set_path(self.source_dir)
            return
        self.source_dir = path.resolve() if path else None
        self.source_combo.set_path(self.source_dir)
        self._load_presets()
        if choose_build and self.source_dir is not None:
            recent = self.settings.build_dir_for_source(str(self.source_dir))
            if recent is not None:
                if recent.preset:
                    self._select_preset(recent.preset, apply_binary_dir=False)
                self.set_build_dir(Path(recent.build), sync_source=False, confirm=False)
            else:
                preset = self._current_preset()
                default = Path(preset.binary_dir) if preset and preset.binary_dir else self.source_dir / "build"
                self.set_build_dir(default, sync_source=False, confirm=False)
        self._update_ui()

    def set_build_dir(self, path: Path | None, sync_source: bool = True, confirm: bool = True) -> None:
        if path is not None:
            path = path.resolve()
        if confirm and path != self.build_dir and not self._confirm_discard():
            self.build_combo.set_path(self.build_dir)
            return
        changed = path != self.build_dir
        self.build_dir = path
        self.build_combo.set_path(path)
        cache = read_cache(path) if path else None
        if cache is not None and sync_source and cache.home_directory:
            home = Path(cache.home_directory)
            if home != self.source_dir:
                self.source_dir = home
                self.source_combo.set_path(home)
                self._load_presets()
        if changed:
            self.model.clear()
            self.output.clear()
            self.problems.clear()
        self.model.load(cache, mark_new=False)
        self._expand_for_filter()
        self.codemodel = read_codemodel(path) if (path and cache) else None
        self._update_targets()
        self._watch_cache()
        self._update_ui()

    def _confirm_discard(self) -> bool:
        if not self.model.pending_items():
            return True
        answer = QMessageBox.question(
            self,
            "Discard Changes?",
            "You have pending changes that have not been applied by Configure. Discard them?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Discard

    # ------------------------------------------------------------ presets

    def _load_presets(self) -> None:
        self.presets = load_configure_presets(self.source_dir) if self.source_dir else []
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItem("No preset", "")
        for preset in self.presets:
            self.preset_combo.addItem(preset.label, preset.name)
            self.preset_combo.setItemData(self.preset_combo.count() - 1, preset.description,
                                          Qt.ItemDataRole.ToolTipRole)
        self.preset_combo.blockSignals(False)
        self.preset_description.setText("")

    def _current_preset(self) -> ConfigurePreset | None:
        name = self.preset_combo.currentData()
        return next((p for p in self.presets if p.name == name), None)

    def _select_preset(self, name: str, apply_binary_dir: bool) -> None:
        index = self.preset_combo.findData(name)
        if index < 0:
            return
        if not apply_binary_dir:
            self.preset_combo.blockSignals(True)
        self.preset_combo.setCurrentIndex(index)
        self.preset_combo.blockSignals(False)
        preset = self._current_preset()
        self.preset_description.setText(preset.description if preset else "")

    def _preset_changed(self, _index: int) -> None:
        preset = self._current_preset()
        self.preset_description.setText(preset.description if preset else "")
        if preset and preset.binary_dir:
            self.set_build_dir(Path(preset.binary_dir), sync_source=False)

    # ------------------------------------------------------- running cmake

    def _configure_request(self, fresh: bool, choice: GeneratorChoice | None) -> ConfigureRequest:
        assert self.build_dir is not None
        preset = self._current_preset()
        req = ConfigureRequest(
            build_dir=self.build_dir,
            source_dir=self.source_dir,
            preset=preset.name if preset else None,
            fresh=fresh,
            overrides=self.model.pending_overrides(),
            removals=[] if fresh else self.model.pending_removals(),
        )
        if choice is not None:
            req.generator = choice.generator
            req.platform = choice.platform
            req.toolset = choice.toolset
            req.toolchain_file = choice.toolchain_file
        return req

    def _needs_generator(self, fresh: bool) -> bool:
        has_cache = self.build_dir is not None and cache_path(self.build_dir).exists()
        preset = self._current_preset()
        return (fresh or not has_cache) and not (preset and preset.generator)

    def configure(self, fresh: bool = False) -> None:
        if self.runner.is_running() or self.info is None or not self.source_dir or not self.build_dir:
            return
        if not (self.source_dir / "CMakeLists.txt").exists():
            QMessageBox.warning(self, "No CMakeLists.txt", f"{self.source_dir} does not contain a CMakeLists.txt.")
            return
        choice = None
        if self._needs_generator(fresh):
            previous = self.model_generator() if fresh else None
            dialog = GeneratorDialog(self.info, previous or default_generator(self.info), str(self.build_dir), self)
            if fresh:
                dialog.setWindowTitle("Fresh Configure")
            if dialog.exec() != GeneratorDialog.DialogCode.Accepted:
                return
            choice = dialog.choice()
        req = self._configure_request(fresh, choice)
        try:
            self.build_dir.mkdir(parents=True, exist_ok=True)
            write_query(self.build_dir)
        except OSError as exc:
            QMessageBox.critical(self, "Cannot Create Build Folder", str(exc))
            return
        self._run("configure", configure_args(req), cwd=str(self.source_dir))

    def build(self, target: str | None = None) -> None:
        if self.runner.is_running() or self.info is None or self.build_dir is None:
            return
        if target is not None:
            index = self.target_combo.findData(target)
            if index >= 0:
                self.target_combo.setCurrentIndex(index)
        target = self.target_combo.currentData() or None
        if self.model.pending_items():
            answer = QMessageBox.question(
                self,
                "Apply Pending Changes?",
                "There are pending cache changes. Configure before building?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                return
            if answer == QMessageBox.StandardButton.Yes:
                self._build_after_configure = target or ""
                self.configure()
                return
        config = self.config_combo.currentText() if self.config_action.isVisible() else None
        args = build_args(self.build_dir, target=target, config=config or None, jobs=self.settings.build_jobs)
        self._run("build", args, cwd=str(self.build_dir))

    def stop(self) -> None:
        self._build_after_configure = None
        self.runner.stop()

    def _run(self, operation: str, args: list[str], cwd: str) -> None:
        assert self.info is not None
        self._operation = operation
        self._problem_parser = ProblemParser()
        self.output.clear()
        self.problems.clear()
        self.output.append(f"$ {format_command(self.info.executable, args)}")
        self.tabs.setCurrentWidget(self.output)
        if self._watcher.files():
            self._watcher.removePaths(self._watcher.files())
        self.statusBar().showMessage("Configuring…" if operation == "configure" else "Building…")
        self.runner.run(self.info.executable, args, cwd=cwd)
        self._update_ui()

    def _on_output_line(self, text: str, _is_err: bool) -> None:
        self.output.append(text)
        for problem in self._problem_parser.feed(text):
            self.problems.add(problem)

    def _on_process_finished(self, exit_code: int, ok: bool, elapsed: float) -> None:
        for problem in self._problem_parser.finish():
            self.problems.add(problem)
        operation, self._operation = self._operation, None
        verb = "Configure" if operation == "configure" else "Build"
        if self.runner.cancelled:
            summary = f"{verb} stopped"
        elif ok:
            summary = f"{verb} finished in {elapsed:.1f}s"
        else:
            summary = f"{verb} failed (exit code {exit_code})"
        self.output.append(("✔ " if ok else "✘ ") + summary)
        self.statusBar().showMessage(summary, 15000)

        if operation == "configure" and self.build_dir is not None:
            cache = read_cache(self.build_dir)
            self.model.load(cache, mark_new=True, keep_pending=False)
            self._expand_for_filter()
            self.codemodel = read_codemodel(self.build_dir)
            self._update_targets()
            if cache is not None and self.source_dir is not None:
                preset = self._current_preset()
                self.settings.add_recent(
                    RecentProject(str(self.source_dir), str(self.build_dir), preset.name if preset else "")
                )
                self._refresh_recent()
            show_advanced = self.act_advanced.isChecked()
            new_count = sum(1 for i in self.model.items() if i.is_new and (show_advanced or not i.advanced))
            if ok and new_count:
                self.statusBar().showMessage(
                    f"{summary} — {new_count} new entr{'ies' if new_count != 1 else 'y'} highlighted", 15000
                )
        if not ok and self.problems.topLevelItemCount():
            self.tabs.setCurrentWidget(self.problems)

        self._watch_cache()
        self._update_ui()
        if operation == "configure" and self._build_after_configure is not None:
            target, self._build_after_configure = self._build_after_configure, None
            if ok:
                self.build(target or None)

    # ------------------------------------------------------ cache editing

    def _selected_items(self) -> list[EntryItem]:
        items = []
        for index in self.view.selectionModel().selectedRows(NAME_COLUMN):
            item = index.data(EntryRole)
            if item is not None:
                items.append(item)
        return items

    def add_entry(self) -> None:
        dialog = AddEntryDialog(self)
        if dialog.exec() != AddEntryDialog.DialogCode.Accepted:
            return
        name, type_, value, help_ = dialog.entry()
        item = self.model.add_entry(name, type_, value, help_)
        self.view_stack.setCurrentIndex(0)
        index = self.proxy.mapFromSource(self.model.index_of(item))
        if index.isValid():
            self.view.scrollTo(index)
            self.view.setCurrentIndex(index)

    def remove_selected(self) -> None:
        items = self._selected_items()
        if items:
            self.model.remove(items)

    def revert_selected(self) -> None:
        self.model.revert(self._selected_items())

    def revert_all(self) -> None:
        self.model.revert_all()

    def _set_show_advanced(self, on: bool) -> None:
        self.settings.show_advanced = on
        self.proxy.set_show_advanced(on)
        self._expand_for_filter()

    def _set_grouped(self, on: bool) -> None:
        self.settings.grouped = on
        self.model.set_grouped(on)
        self._expand_for_filter()

    def _set_changed_only(self, on: bool) -> None:
        self.proxy.set_modified_only(on)
        self._expand_for_filter()

    def _search_changed(self, text: str) -> None:
        self.proxy.set_search(text)
        self._expand_for_filter()

    def _expand_for_filter(self) -> None:
        if self.search.text() or self.act_changed_only.isChecked():
            self.view.expandAll()
            return
        if not self.model.is_grouped():
            return
        # Otherwise expand only the groups that need attention.
        for row in range(self.proxy.rowCount()):
            group = self.proxy.index(row, NAME_COLUMN)
            if self.model.group_needs_attention(self.proxy.mapToSource(group).row()):
                self.view.expand(group)

    def _show_entry_info(self, index: QModelIndex) -> None:
        item: EntryItem | None = index.data(EntryRole) if index.isValid() else None
        if item is None:
            self.entry_info.setText("")
            self.entry_info.hide()
            return
        parts = [f"<b>{escape(item.name)}</b> &nbsp;<span style='color:palette(placeholder-text)'>{item.type}"
                 f"{' · advanced' if item.advanced else ''}{' · new' if item.is_new else ''}</span>"]
        if item.help:
            parts.append(escape(item.help).replace("\n", "<br>"))
        if item.strings:
            parts.append("<i>Allowed values:</i> " + escape(", ".join(item.strings)))
        if item.modified and not item.added and not item.removed:
            parts.append(f"<i>Current cache value:</i> <code>{escape(item.original or '')}</code>")
        self.entry_info.setText("<br>".join(parts))
        self.entry_info.show()

    def _show_context_menu(self, pos) -> None:
        index = self.view.indexAt(pos)
        item: EntryItem | None = index.data(EntryRole) if index.isValid() else None
        menu = QMenu(self)
        if item is not None:
            clipboard = QGuiApplication.clipboard()
            menu.addAction("Copy Name", lambda: clipboard.setText(item.name))
            menu.addAction("Copy Value", lambda: clipboard.setText(item.value))
            menu.addAction("Copy as -D Argument", lambda: clipboard.setText(
                f"-D{item.name}:{item.type}={item.value}"))
            menu.addSeparator()
            menu.addAction(self.act_revert)
            menu.addAction(self.act_remove)
            menu.addSeparator()
            menu.addAction(self.act_var_docs)
            menu.addSeparator()
        menu.addAction(self.act_add)
        menu.exec(self.view.viewport().mapToGlobal(pos))

    # -------------------------------------------------- watchers & reload

    def _watch_cache(self) -> None:
        if self._watcher.files():
            self._watcher.removePaths(self._watcher.files())
        if self.build_dir is not None:
            path = cache_path(self.build_dir)
            if path.exists():
                self._watcher.addPath(str(path))

    def _reload_cache_from_disk(self) -> None:
        if self.runner.is_running() or self.build_dir is None:
            return
        self.model.load(read_cache(self.build_dir), mark_new=False)
        self.codemodel = read_codemodel(self.build_dir)
        self._update_targets()
        self._watch_cache()
        self._update_ui()

    def _update_targets(self) -> None:
        targets = self.codemodel.targets if self.codemodel else []
        self.targets.set_targets(targets)
        self.tabs.setTabText(2, f"Targets ({len(targets)})" if targets else "Targets")
        current = self.target_combo.currentData()
        self.target_combo.clear()
        self.target_combo.addItem("Default target", "")
        buildable = [t for t in targets if t.type != "INTERFACE_LIBRARY"]
        if buildable:
            self.target_combo.insertSeparator(1)
        for target in buildable:
            self.target_combo.addItem(target.name, target.name)
        self.target_combo.addItem("clean", "clean")
        self.target_combo.addItem("install", "install")
        index = self.target_combo.findData(current)
        self.target_combo.setCurrentIndex(max(index, 0))

        configs = self.codemodel.configurations if self.codemodel else []
        current_config = self.config_combo.currentText()
        self.config_combo.clear()
        self.config_combo.addItems(configs)
        if current_config in configs:
            self.config_combo.setCurrentText(current_config)

    def _problem_count_changed(self, errors: int, warnings: int) -> None:
        total = errors + warnings
        text = "Problems"
        if total:
            bits = []
            if errors:
                bits.append(f"{errors} error{'s' if errors != 1 else ''}")
            if warnings:
                bits.append(f"{warnings} warning{'s' if warnings != 1 else ''}")
            text += f" ({', '.join(bits)})"
        self.tabs.setTabText(1, text)

    # ------------------------------------------------------------ misc

    def open_problem(self, problem: Problem) -> None:
        if not problem.file:
            return
        path = Path(problem.file)
        if not path.is_absolute():
            base = self.source_dir if problem.source == "cmake" else self.build_dir
            if base is not None:
                path = base / path
        if not path.exists():
            self.statusBar().showMessage(f"File not found: {path}", 5000)
            return
        code = shutil.which("code")
        if code and problem.line:
            QProcess.startDetached(code, ["-g", f"{path}:{problem.line}:{problem.column or 1}"])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def show_command(self) -> None:
        if self.info is None or self.build_dir is None:
            return
        choice = None
        if self._needs_generator(False):
            choice = GeneratorChoice(default_generator(self.info) or "", None, None, None)
        args = configure_args(self._configure_request(False, choice))
        CommandDialog(format_command(self.info.executable, args), self).exec()

    def open_in_ide(self) -> None:
        if self.info and self.build_dir:
            QProcess.startDetached(self.info.executable, ["--open", str(self.build_dir)])

    def reveal_build_dir(self) -> None:
        if self.build_dir and self.build_dir.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.build_dir)))

    def delete_cache(self) -> None:
        if self.build_dir is None:
            return
        answer = QMessageBox.warning(
            self,
            "Delete Cache?",
            f"Delete CMakeCache.txt and CMakeFiles/ from\n{self.build_dir}?\n\n"
            "All cache values will be lost and the next Configure starts from scratch.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            cache_path(self.build_dir).unlink(missing_ok=True)
        except OSError as exc:
            QMessageBox.critical(self, "Delete Failed", str(exc))
            return
        shutil.rmtree(self.build_dir / "CMakeFiles", ignore_errors=True)
        self.model.clear()
        self.codemodel = None
        self._update_targets()
        self._watch_cache()
        self._update_ui()

    def lookup_docs(self) -> None:
        index = self.view.currentIndex()
        item: EntryItem | None = index.data(EntryRole) if index.isValid() else None
        if item is None:
            return
        QDesktopServices.openUrl(QUrl(f"https://cmake.org/cmake/help/latest/search.html?q={item.name}"))

    def show_preferences(self) -> None:
        dialog = PreferencesDialog(self.settings.cmake_path, self.settings.build_jobs, self)
        if dialog.exec() != PreferencesDialog.DialogCode.Accepted:
            return
        self.settings.cmake_path = dialog.cmake_path.text().strip()
        self.settings.build_jobs = dialog.jobs.value()
        self._load_cmake()
        self._update_ui()

    def show_about(self) -> None:
        cmake = f"CMake {self.info.version}<br>{escape(self.info.executable)}" if self.info else "CMake not found"
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            f"<h3>{APP_NAME} {__version__}</h3><p>A modern GUI for CMake.</p><p>{cmake}</p>",
        )

    def _refresh_recent(self) -> None:
        recent = self.settings.recent_projects()
        self.source_combo.set_history([r.source for r in recent])
        self.build_combo.set_history([r.build for r in recent])
        self.recent_list.clear()
        for project in recent:
            label = Path(project.source).name or project.source
            item = QListWidgetItem(f"{label}\n{project.build}")
            item.setToolTip(f"Source: {project.source}\nBuild: {project.build}")
            item.setData(Qt.ItemDataRole.UserRole, project)
            self.recent_list.addItem(item)
        self.recent_label.setVisible(bool(recent))
        self.recent_list.setVisible(bool(recent))

    def _fill_recent_menu(self) -> None:
        self.recent_menu.clear()
        recent = self.settings.recent_projects()
        for project in recent:
            label = f"{Path(project.source).name}  —  {project.build}"
            act = self.recent_menu.addAction(label, lambda p=project: self.open_recent(p))
            act.setMenuRole(QAction.MenuRole.NoRole)
        if recent:
            self.recent_menu.addSeparator()
            self.recent_menu.addAction("Clear Recent", lambda: (self.settings.clear_recent(), self._refresh_recent()))
        else:
            self.recent_menu.addAction("No recent projects").setEnabled(False)

    # ------------------------------------------------------------- events

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls() and any(u.isLocalFile() for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.open_path(url.toLocalFile())
                event.acceptProposedAction()
                return

    def closeEvent(self, event) -> None:
        if self.runner.is_running():
            answer = QMessageBox.question(self, "CMake Is Running", "Stop the running process and quit?")
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.runner.stop()
        if not self._confirm_discard():
            event.ignore()
            return
        self.settings.save_window_state(self.saveGeometry(), self.saveState(), self.splitter.saveState())
        event.accept()
