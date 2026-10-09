A better GUI for [CMake](https://cmake.org).

Let's face it, CMake's default GUI isn't great, and seemingly hasn't added any new features in 20 years. This project aims to fill that gap by providing a modern, intuitive interface for CMake users.
Build using Qt/Pyside6 and Python, this is intended to provide a more user-friendly interface for managing CMake projects.

## Running

```sh
pixi run start                      # launch the GUI
pixi run start path/to/project      # open a source folder, build folder or CMakeCache.txt
pixi run python -m vibecmake -S src -B build --preset debug
pixi run test                       # run the test suite
```

## Features

* **Cache editor** – grouped or flat view, instant search (name *and* value), advanced toggle,
  type-aware editors (checkboxes for `BOOL`, drop-downs for `STRINGS` properties, browse buttons for
  `PATH`/`FILEPATH`), help text for the selected entry, and add/remove entries.
* **Pending changes** – edits are tracked (bold) until the next Configure, with per-entry and
  global revert. Entries that appeared in the last configure are highlighted (like cmake-gui's red rows).
* **Configure presets** – `CMakePresets.json` / `CMakeUserPresets.json` (with `include`, `inherits`,
  macros and host conditions) are listed and selecting one picks its build folder.
* **Build** – build any target (discovered through the CMake File API), choose the configuration for
  multi-config generators, stop a running build, open Xcode / Visual Studio projects.
* **Problems panel** – CMake errors/warnings and compiler diagnostics are extracted from the output;
  double-click to jump to the file (VS Code if available).
* **Reproducible** – *CMake ▸ Show Command Line* gives the exact `cmake` invocation equivalent to
  pressing Configure, for scripts and CI.
* **Quality of life** – recent projects, drag and drop of folders, `--fresh` configure, delete cache,
  live reload when `CMakeCache.txt` changes on disk, and remembered window layout.

## Layout

| Path | Contents |
| --- | --- |
| `vibecmake/cmake/` | Qt-free core: cache parsing, command lines, presets, File API, problem parsing |
| `vibecmake/ui/` | Qt widgets (via `qtpy`): main window, cache model/delegate, panels, dialogs |
| `examples/hello/` | Small project with options, enum strings and presets for trying things out |
| `tests/` | pytest + pytest-qt suite; integration tests run the real `cmake` |

### References

* [CMake GitHub Repository](https://github.com/Kitware/CMake)
* [cmake-file-api(7)](https://cmake.org/cmake/help/latest/manual/cmake-file-api.7.html)
* [cmake-presets(7)](https://cmake.org/cmake/help/latest/manual/cmake-presets.7.html)
