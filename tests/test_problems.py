from vibecmake.cmake.problems import ProblemParser

LOG = """\
-- The C compiler identification is AppleClang 17.0.0
CMake Warning (dev) at CMakeLists.txt:12 (message):
  Something looks
  odd here.
Call Stack (most recent call first):
  foo.cmake:3 (include)
This warning is for project developers.  Use -Wno-dev to suppress it.

CMake Error at sub/CMakeLists.txt:3 (find_package):
  Could not find Foo.

CMake Error: The source directory "/nope" does not exist.
-- Configuring incomplete, errors occurred!
/src/main.c:4:10: error: expected ';' after expression
/src/util.c:7: warning: unused variable
C:\\src\\a.cpp(12,5): error C2065: 'x': undeclared identifier
"""


def parse(text):
    parser = ProblemParser()
    found = []
    for line in text.splitlines():
        found += parser.feed(line)
    found += parser.finish()
    assert found == parser.problems
    return found


def test_parses_cmake_and_compiler_problems():
    problems = parse(LOG)
    summary = [(p.severity, p.file, p.line) for p in problems]
    assert summary == [
        ("warning", "CMakeLists.txt", 12),
        ("error", "sub/CMakeLists.txt", 3),
        ("error", None, None),
        ("error", "/src/main.c", 4),
        ("warning", "/src/util.c", 7),
        ("error", "C:\\src\\a.cpp", 12),
    ]
    assert problems[0].message == "Something looks odd here."
    assert problems[2].message == 'The source directory "/nope" does not exist.'
    assert problems[3].column == 10
    assert problems[5].column == 5


def test_error_at_end_of_output_is_flushed():
    problems = parse("CMake Error at x.cmake:1 (foo):\n  boom")
    assert len(problems) == 1 and problems[0].message == "boom"
