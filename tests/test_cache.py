from vibecmake.cmake.cache import is_on, parse_cache_text, parse_entry_line

SAMPLE = """\
# This is the CMakeCache file.

//Build type
CMAKE_BUILD_TYPE:STRING=Debug

//Enable foo
//over two lines
ENABLE_FOO:BOOL=ON

"QUOTED:NAME":STRING=x=y
EMPTY:PATH=
TRAILING:STRING=value   
SINGLEQ:STRING='  padded  '
CMAKE_BUILD_TYPE-STRINGS:INTERNAL=Debug;Release;;RelWithDebInfo
ENABLE_FOO-ADVANCED:INTERNAL=1
CMAKE_HOME_DIRECTORY:INTERNAL=/src
"""


def test_parse_entries_and_help():
    cache = parse_cache_text(SAMPLE)
    foo = cache.entries["ENABLE_FOO"]
    assert foo.type == "BOOL" and foo.value == "ON"
    assert foo.help == "Enable foo\nover two lines"
    assert foo.advanced
    assert cache.entries["CMAKE_BUILD_TYPE"].strings == ["Debug", "Release", "RelWithDebInfo"]
    assert cache.entries["QUOTED:NAME"].value == "x=y"
    assert cache.entries["EMPTY"].value == ""
    assert cache.entries["TRAILING"].value == "value"
    assert cache.entries["SINGLEQ"].value == "  padded  "
    assert cache.home_directory == "/src"


def test_visible_excludes_internal():
    names = {e.name for e in parse_cache_text(SAMPLE).visible_entries}
    assert "CMAKE_HOME_DIRECTORY" not in names
    assert "ENABLE_FOO-ADVANCED" not in names
    assert {"CMAKE_BUILD_TYPE", "ENABLE_FOO"} <= names


def test_parse_entry_line_rejects_garbage():
    assert parse_entry_line("not an entry") is None
    assert parse_entry_line("A:B=C") == ("A", "B", "C")


def test_is_on():
    assert all(is_on(v) for v in ("ON", "on", "1", "TRUE", "yes", "Y"))
    assert not any(is_on(v) for v in ("OFF", "0", "", "NO", "FOO-NOTFOUND", "2"))
