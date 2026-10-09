import json

from vibecmake.cmake.presets import load_configure_presets


def test_example_presets(example_source):
    presets = {p.name: p for p in load_configure_presets(example_source)}
    assert set(presets) == {"debug", "release"}  # hidden and Windows-only are excluded
    debug = presets["debug"]
    assert debug.label == "Debug"
    assert debug.generator == "Ninja"
    assert debug.binary_dir == str(example_source / "build" / "debug")
    assert presets["release"].cache_variables["HELLO_ENABLE_EXTRAS"] == "ON"


def test_user_presets_include_and_env(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_TEST_ROOT", "/tmp/vibe")
    (tmp_path / "CMakePresets.json").write_text(json.dumps({
        "version": 6,
        "include": ["more.json"],
        "configurePresets": [{"name": "a", "binaryDir": "out/${presetName}"}],
    }))
    (tmp_path / "more.json").write_text(json.dumps({
        "version": 6,
        "configurePresets": [{"name": "b", "binaryDir": "$env{VIBE_TEST_ROOT}/${sourceDirName}"}],
    }))
    (tmp_path / "CMakeUserPresets.json").write_text(json.dumps({
        "version": 6,
        "configurePresets": [{"name": "mine", "inherits": "a", "displayName": "Mine"}],
    }))
    presets = {p.name: p for p in load_configure_presets(tmp_path)}
    assert presets["a"].binary_dir == str(tmp_path / "out" / "a")
    assert presets["b"].binary_dir == f"/tmp/vibe/{tmp_path.name}"
    assert presets["mine"].binary_dir == str(tmp_path / "out" / "mine")
    assert presets["mine"].label == "Mine"


def test_no_presets(tmp_path):
    assert load_configure_presets(tmp_path) == []
