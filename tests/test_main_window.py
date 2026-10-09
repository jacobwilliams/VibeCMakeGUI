from qtpy.QtCore import QSettings
from qtpy.QtGui import QAction

from vibecmake.cmake.cache import read_cache
from vibecmake.settings import AppSettings
from vibecmake.ui import dialogs
from vibecmake.ui.main_window import EDITOR_PAGE, WELCOME_PAGE, MainWindow

from .conftest import requires_cmake


def make_window(qtbot, tmp_path):
    settings = AppSettings(QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    window = MainWindow(settings)
    qtbot.addWidget(window)
    return window


def wait_idle(qtbot, window):
    qtbot.waitUntil(lambda: not window.runner.is_running(), timeout=60_000)


def test_starts_on_welcome_page(qtbot, tmp_path):
    window = make_window(qtbot, tmp_path)
    assert window.stack.currentIndex() == WELCOME_PAGE


@requires_cmake
def test_configure_edit_reconfigure_build(qtbot, tmp_path, example_source, monkeypatch):
    window = make_window(qtbot, tmp_path)
    build = tmp_path / "b"
    window.set_source_dir(example_source, choose_build=False)
    window.set_build_dir(build, sync_source=False)
    assert window.stack.currentIndex() == EDITOR_PAGE
    assert window.preset_combo.isVisibleTo(window)

    # Accept the generator dialog with Ninja.
    monkeypatch.setattr(dialogs.GeneratorDialog, "exec", lambda self: (
        self.generator.setCurrentText("Ninja"), dialogs.GeneratorDialog.DialogCode.Accepted)[1])
    window.configure()
    wait_idle(qtbot, window)
    assert window.model.find("HELLO_FLAVOR") is not None
    assert all(i.is_new for i in window.model.items())
    assert "Configure finished" in window.output.view.toPlainText()

    # Edit an entry and reconfigure: the edit is applied and pending is cleared.
    window.model.set_value(window.model.find("HELLO_ENABLE_EXTRAS"), "ON")
    assert window.isWindowModified()
    window.configure()
    wait_idle(qtbot, window)
    assert read_cache(build).get("HELLO_ENABLE_EXTRAS") == "ON"
    assert not window.model.pending_items()
    assert not any(i.is_new for i in window.model.items())
    assert window.target_combo.findData("hello_extras") >= 0

    window.build("hello")
    wait_idle(qtbot, window)
    assert "Build finished" in window.output.view.toPlainText()
    assert (build / "hello").exists()

    # The project was remembered.
    assert window.settings.recent_projects()[0].build == str(build.resolve())


@requires_cmake
def test_configure_errors_reach_problems(qtbot, tmp_path, monkeypatch):
    source = tmp_path / "bad"
    source.mkdir()
    (source / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.21)\nproject(Bad NONE)\nmessage(FATAL_ERROR \"nope\")\n")
    window = make_window(qtbot, tmp_path)
    window.set_source_dir(source)
    monkeypatch.setattr(dialogs.GeneratorDialog, "exec", lambda self: dialogs.GeneratorDialog.DialogCode.Accepted)
    window.configure()
    wait_idle(qtbot, window)
    assert window.problems.topLevelItemCount() == 1
    item = window.problems.topLevelItem(0)
    assert item.text(0) == "nope"
    assert item.text(1) == "CMakeLists.txt:3"
    assert window.tabs.currentWidget() is window.problems


def test_only_intended_actions_get_macos_app_menu_roles(qtbot, tmp_path):
    """Qt would otherwise guess that "Configure" is the Preferences item."""
    window = make_window(qtbot, tmp_path)
    def menu_items(menu):
        for action in menu.actions():
            if action.menu() is not None:
                yield from menu_items(action.menu())
            elif not action.isSeparator():
                yield action

    items = list(menu_items(window.menuBar()))
    assert any(a.text() == "Configure" for a in items)
    roles = {a.text(): a.menuRole() for a in items if a.menuRole() != QAction.MenuRole.NoRole}
    assert roles == {
        "Preferences…": QAction.MenuRole.PreferencesRole,
        "Quit": QAction.MenuRole.QuitRole,
        "About VibeCMake": QAction.MenuRole.AboutRole,
    }
