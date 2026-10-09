"""Running cmake asynchronously with line-buffered output."""

from __future__ import annotations

import time

from qtpy.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal


class ProcessRunner(QObject):
    """Wraps QProcess; emits complete lines of stdout/stderr."""

    started = Signal()
    line = Signal(str, bool)  # text, from stderr
    finished = Signal(int, bool, float)  # exit code, ok, elapsed seconds

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._process: QProcess | None = None
        self._buffers = {False: "", True: ""}
        self._start_time = 0.0
        self._cancelled = False

    def is_running(self) -> bool:
        return self._process is not None

    def run(self, program: str, args: list[str], cwd: str | None = None, env: dict[str, str] | None = None) -> None:
        if self._process is not None:
            raise RuntimeError("A process is already running")
        process = QProcess(self)
        process.setProgram(program)
        process.setArguments(args)
        if cwd:
            process.setWorkingDirectory(cwd)
        environment = QProcessEnvironment.systemEnvironment()
        # Most tools only colourise for terminals; keep the log plain.
        environment.insert("CLICOLOR", "0")
        for key, value in (env or {}).items():
            environment.insert(key, value)
        process.setProcessEnvironment(environment)
        process.readyReadStandardOutput.connect(lambda: self._read(False))
        process.readyReadStandardError.connect(lambda: self._read(True))
        process.finished.connect(self._on_finished)
        process.errorOccurred.connect(self._on_error)
        self._process = process
        self._buffers = {False: "", True: ""}
        self._cancelled = False
        self._start_time = time.monotonic()
        process.start()
        self.started.emit()

    def stop(self) -> None:
        process = self._process
        if process is None:
            return
        self._cancelled = True
        process.terminate()
        QTimer.singleShot(3000, lambda: self._process is process and process.kill())

    def _read(self, is_err: bool) -> None:
        if self._process is None:
            return
        raw = self._process.readAllStandardError() if is_err else self._process.readAllStandardOutput()
        text = self._buffers[is_err] + bytes(raw.data()).decode("utf-8", errors="replace")
        *lines, self._buffers[is_err] = text.replace("\r\n", "\n").split("\n")
        for line in lines:
            self.line.emit(line, is_err)

    def _flush(self) -> None:
        for is_err in (False, True):
            if self._buffers[is_err]:
                self.line.emit(self._buffers[is_err], is_err)
                self._buffers[is_err] = ""

    def _on_finished(self, exit_code: int, exit_status) -> None:
        if self._process is None:
            return
        self._read(False)
        self._read(True)
        self._flush()
        ok = exit_status == QProcess.ExitStatus.NormalExit and exit_code == 0 and not self._cancelled
        self._done(exit_code, ok)

    def _on_error(self, error) -> None:
        if error == QProcess.ProcessError.FailedToStart and self._process is not None:
            self.line.emit(f"Failed to start {self._process.program()}: {self._process.errorString()}", True)
            self._done(-1, False)

    def _done(self, exit_code: int, ok: bool) -> None:
        process, self._process = self._process, None
        if process is not None:
            process.deleteLater()
        self.finished.emit(exit_code, ok, time.monotonic() - self._start_time)

    @property
    def cancelled(self) -> bool:
        return self._cancelled
