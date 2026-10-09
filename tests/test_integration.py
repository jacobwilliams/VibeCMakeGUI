"""Runs the real cmake against the example project."""

import subprocess

from vibecmake.cmake.cache import read_cache
from vibecmake.cmake.capabilities import find_cmake, query_cmake
from vibecmake.cmake.command import CacheOverride, ConfigureRequest, configure_args
from vibecmake.cmake.fileapi import read_codemodel, write_query

from .conftest import requires_cmake


@requires_cmake
def test_configure_and_read_back(example_source, tmp_path):
    cmake = find_cmake()
    info = query_cmake(cmake)
    assert info.generators
    build = tmp_path / "build"
    build.mkdir()
    write_query(build)
    req = ConfigureRequest(
        build_dir=build,
        source_dir=example_source,
        generator="Ninja",
        overrides=[CacheOverride("HELLO_ENABLE_EXTRAS", "BOOL", "ON")],
    )
    subprocess.run([cmake, *configure_args(req)], check=True, capture_output=True)

    cache = read_cache(build)
    assert cache.project_name == "Hello"
    assert cache.entries["HELLO_FLAVOR"].strings == ["vanilla", "chocolate", "strawberry"]
    assert cache.entries["HELLO_DATA_DIR"].advanced
    assert cache.entries["HELLO_ENABLE_EXTRAS"].value == "ON"

    model = read_codemodel(build)
    assert model is not None and model.generator == "Ninja"
    assert {t.name: t.type for t in model.targets} == {
        "hello": "EXECUTABLE",
        "hello_extras": "STATIC_LIBRARY",
    }


@requires_cmake
def test_preset_with_source_dir_flag(example_source, tmp_path):
    """`--preset` together with `-S`/`-B` works from any working directory."""
    cmake = find_cmake()
    build = tmp_path / "pbuild"
    req = ConfigureRequest(build_dir=build, source_dir=example_source, preset="release")
    subprocess.run([cmake, *configure_args(req)], check=True, capture_output=True, cwd=tmp_path)
    cache = read_cache(build)
    assert cache.get("CMAKE_BUILD_TYPE") == "Release"
