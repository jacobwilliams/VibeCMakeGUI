"""Application entry point."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_API", "pyside6")

from qtpy.QtGui import QIcon  # noqa: E402
from qtpy.QtWidgets import QApplication  # noqa: E402

from . import __version__  # noqa: E402

ICON_PATH = Path(__file__).parent / "resources" / "icon.svg"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="vibecmake", description="A modern GUI for CMake.")
    parser.add_argument("path", nargs="?", help="a source folder, build folder or CMakeCache.txt")
    parser.add_argument("-S", dest="source", metavar="SOURCE", help="source folder")
    parser.add_argument("-B", dest="build", metavar="BUILD", help="build folder")
    parser.add_argument("--preset", help="configure preset to select")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    from .settings import AppSettings
    from .ui.main_window import APP_NAME, MainWindow

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("VibeCMakeGUI")
    app.setApplicationVersion(__version__)
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))

    window = MainWindow(AppSettings())
    if args.source:
        window.set_source_dir(Path(args.source), choose_build=not args.build)
    if args.preset:
        window._select_preset(args.preset, apply_binary_dir=not args.build)
    if args.build:
        window.set_build_dir(Path(args.build), sync_source=not args.source)
    if args.path:
        window.open_path(args.path)
    window.show()
    return app.exec()
