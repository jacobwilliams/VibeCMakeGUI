from pathlib import Path

from vibecmake.cmake.command import CacheOverride, ConfigureRequest, build_args, configure_args, format_command


def test_configure_args_full():
    req = ConfigureRequest(
        build_dir=Path("/b"),
        source_dir=Path("/s"),
        generator="Ninja",
        toolchain_file="/tc.cmake",
        overrides=[CacheOverride("A", "BOOL", "ON"), CacheOverride("B", "UNINITIALIZED", "x y")],
        removals=["OLD"],
    )
    assert configure_args(req) == [
        "-S", "/s", "-B", "/b", "-G", "Ninja",
        "-DCMAKE_TOOLCHAIN_FILE:FILEPATH=/tc.cmake",
        "-U", "OLD", "-DA:BOOL=ON", "-DB=x y",
    ]


def test_configure_args_preset_and_fresh():
    req = ConfigureRequest(build_dir=Path("/b"), source_dir=Path("/s"), preset="debug", fresh=True)
    assert configure_args(req) == ["--preset", "debug", "-S", "/s", "-B", "/b", "--fresh"]


def test_build_args():
    assert build_args(Path("/b"), target="hello", config="Debug", jobs=4) == [
        "--build", "/b", "--target", "hello", "--config", "Debug", "--parallel", "4",
    ]
    assert build_args(Path("/b")) == ["--build", "/b"]


def test_format_command_quotes():
    assert format_command("cmake", ["-DX=a b"]) == "cmake '-DX=a b'"
