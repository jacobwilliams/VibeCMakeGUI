from qtpy.QtCore import Qt

from vibecmake.cmake.cache import parse_cache_text
from vibecmake.ui.cache_model import VALUE_COLUMN, CacheFilterProxy, CacheModel

CACHE = parse_cache_text("""\
CMAKE_BUILD_TYPE:STRING=Debug
CMAKE_INSTALL_PREFIX:PATH=/usr/local
CMAKE_VERBOSE_MAKEFILE:BOOL=FALSE
CMAKE_VERBOSE_MAKEFILE-ADVANCED:INTERNAL=1
BUILD_TESTING:BOOL=ON
FOO_ONLY:STRING=x
""")


def make_model(qtbot=None):
    model = CacheModel()
    model.load(CACHE)
    return model


def test_grouping(qapp):
    model = make_model()
    groups = [model.index(r, 0).data() for r in range(model.rowCount())]
    # Single-entry groups are folded into "Ungrouped Entries".
    assert groups == ["Ungrouped Entries", "CMAKE"]
    model.set_grouped(False)
    assert model.rowCount() == 5


def test_bool_toggle_keeps_original_spelling(qapp):
    model = make_model()
    model.set_grouped(False)
    item = model.find("CMAKE_VERBOSE_MAKEFILE")
    index = model.index_of(item, VALUE_COLUMN)
    assert index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Unchecked
    model.setData(index, Qt.CheckState.Checked.value, Qt.ItemDataRole.CheckStateRole)
    assert item.value == "ON" and item.modified
    model.setData(index, Qt.CheckState.Unchecked.value, Qt.ItemDataRole.CheckStateRole)
    assert item.value == "FALSE" and not item.modified


def test_pending_changes_and_revert(qapp):
    model = make_model()
    model.set_value(model.find("CMAKE_BUILD_TYPE"), "Release")
    model.remove([model.find("FOO_ONLY")])
    model.add_entry("NEW_ONE", "BOOL", "ON")
    assert {(o.name, o.value) for o in model.pending_overrides()} == {("CMAKE_BUILD_TYPE", "Release"), ("NEW_ONE", "ON")}
    assert model.pending_removals() == ["FOO_ONLY"]
    model.revert_all()
    assert model.pending_items() == []
    assert model.find("NEW_ONE") is None


def test_reload_keeps_unapplied_edits_and_marks_new(qapp):
    model = make_model()
    model.set_value(model.find("CMAKE_BUILD_TYPE"), "Release")
    model.load(CACHE)  # e.g. file watcher reload
    assert model.find("CMAKE_BUILD_TYPE").value == "Release"

    after = parse_cache_text("CMAKE_BUILD_TYPE:STRING=Release\nBRAND_NEW:BOOL=ON\n")
    model.load(after, mark_new=True, keep_pending=False)
    assert not model.pending_items()
    assert model.find("BRAND_NEW").is_new
    assert not model.find("CMAKE_BUILD_TYPE").is_new


def test_proxy_filters_advanced_and_search(qapp):
    model = make_model()
    model.set_grouped(False)
    proxy = CacheFilterProxy()
    proxy.setSourceModel(model)
    names = lambda: {proxy.index(r, 0).data() for r in range(proxy.rowCount())}  # noqa: E731
    assert "CMAKE_VERBOSE_MAKEFILE" not in names()
    proxy.set_show_advanced(True)
    assert "CMAKE_VERBOSE_MAKEFILE" in names()
    proxy.set_search("usr nothing")
    assert names() == set()
    proxy.set_search("prefix LOCAL")
    assert names() == {"CMAKE_INSTALL_PREFIX"}
