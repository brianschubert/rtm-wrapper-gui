"""
Misc utilities.
"""
from __future__ import annotations

import argparse
import dataclasses
import importlib.metadata
import logging.config
import pathlib
import subprocess
import threading
import types
from dataclasses import dataclass
from typing import Any, Final, Generic, TypeVar

import xarray as xr
from PySide6 import QtCore, QtTest, QtWidgets

DISTRIBUTION_NAME: Final[str] = "rtm_wrapper_gui"

T = TypeVar("T")


@dataclass
class RtmResults:
    dataset: xr.Dataset
    file: pathlib.Path | None = None


class WatchedBox(QtCore.QObject, Generic[T]):
    _value: T

    value_changed = QtCore.Signal(object)

    def __init__(self, initial_value: T, parent: QtCore.QObject | None = None) -> None:
        self._value = initial_value
        super().__init__(parent)

    @property
    def value(self) -> T:
        return self._value

    @value.setter
    def value(self, value: T) -> None:
        self.set_value(value)

    @QtCore.Slot(object)
    def set_value(self, value: T) -> None:
        self._value = value
        self.value_changed.emit(self._value)


@dataclass
class ExecJob:
    source: str | types.CodeType
    globals: dict[str, Any] = dataclasses.field(default_factory=lambda: {})
    locals: dict[str, Any] = dataclasses.field(default_factory=lambda: {})


class PythonExecWorker(QtCore.QObject):
    """
    Worker run ``exec``ing some Python code in a separate QThread.
    """

    send_job = QtCore.Signal(ExecJob)

    finished = QtCore.Signal(ExecJob)

    exception = QtCore.Signal(Exception)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.send_job.connect(self.exec)

    @QtCore.Slot(ExecJob)
    def exec(self, job: ExecJob) -> None:
        logger = logging.getLogger(__name__)
        logger.debug("running exec job")
        try:
            exec(job.source, job.globals, job.locals)
        except Exception as ex:
            logger.warning("exception raised during exec job", exc_info=ex)
            self.exception.emit(ex)
            return
        logger.debug("finished exec job")
        self.finished.emit(job)


class ThreadNameSyncWorker(QtCore.QObject):
    """
    Worker whose only job is the set name of the Python thread that it's running
    in to match the name of the current QThread object.
    """

    do_sync = QtCore.Signal()

    sync_finished = QtCore.Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.do_sync.connect(self.sync_names)

    @classmethod
    def sync_thread_names(cls, thread: QtCore.QThread) -> None:
        logger = logging.getLogger(__name__)

        if not thread.isRunning():
            raise ValueError("thread must already be running")

        worker = cls()
        worker.moveToThread(thread)
        worker.do_sync.emit()

        logger.debug(f"waiting on thread name sync for Qt thread {thread.objectName()}")
        spy = QtTest.QSignalSpy(worker.sync_finished)
        spy.wait(0)
        logger.debug(f"thread name sync finished for {thread.objectName()}")

    @QtCore.Slot()
    def sync_names(self) -> None:
        logger = logging.getLogger(__name__)

        current_thread = threading.current_thread()
        qt_name = QtCore.QThread.currentThread().objectName()

        logger.debug(f"renaming {current_thread.name} to {qt_name}")
        current_thread.name = QtCore.QThread.currentThread().objectName()

        self.sync_finished.emit()


def setup_debug_root_logging(level: int = logging.NOTSET) -> None:
    """
    Configure the root logger with a basic debugging configuration.

    All records at the given level or above will be written to stdout.

    This function should be called once near the start of an application entry point,
    BEFORE any calls to ``logging.getLogger`` are made.

    Disables any existing loggers.
    """
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": True,
            "formatters": {
                "console": {
                    "format": "[{asctime},{msecs:06.2f}] {levelname:7s} ({threadName}:{name}) {funcName}:{lineno} {message}",
                    "style": "{",
                    "datefmt": "%Y-%m-%d %H:%M:%S",
                    "validate": True,
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "console",
                    "level": "NOTSET",  # Capture everything.
                    "stream": "ext://sys.stdout",
                }
            },
            "root": {"handlers": ["console"], "level": level},
        }
    )


def log_level(raw_arg: str) -> int:
    """
    Validate that the given CLI argument is a valid log level.

    Accepts both integer levels and level names.

    References
    ==========

    1. https://docs.python.org/3/library/logging.html#logging.getLevelName

    >>> log_level("10")
    10
    >>> log_level("INFO")
    20
    >>> log_level("FOO")
    Traceback (most recent call last):
    ...
    argparse.ArgumentTypeError: unable to interpret log level: FOO
    """
    try:
        # Even though standard log levels are limited to {0, ..., 50}, we don't
        # validate the value of the integer. Log levels like -1 or 1000 are permitted.
        return int(raw_arg)
    except (TypeError, ValueError):
        pass

    # Attempt to lookup log level from string.
    resolved_level = logging.getLevelName(raw_arg)
    if isinstance(resolved_level, int):
        # A log level was found for the given level name.
        return resolved_level

    raise argparse.ArgumentTypeError(f"unable to interpret log level: {raw_arg}")


def dev_build_tag() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            text=True,
            check=True,
            capture_output=True,
        )
        build_commit = result.stdout.strip()
        return f"{build_commit}"
    except (FileNotFoundError, subprocess.SubprocessError):
        return None


def make_detailed_version(distribution_name: str) -> str:
    """Generate version info string for the given distribution."""
    dep_str = ", ".join(
        f"{dep} {importlib.metadata.version(dep)}"
        for dep in _dist_dependencies(distribution_name)
    )

    dist_version = importlib.metadata.version(DISTRIBUTION_NAME)
    dev_commit = dev_build_tag()
    if dev_commit is not None:
        dist_version = f"{dist_version}+{dev_commit}"

    return f"{distribution_name} {dist_version} ({dep_str})"


def _dist_dependencies(distribution_name: str) -> list[str]:
    """Retrieve the names of the direct dependencies of the given distribution."""
    requirements = importlib.metadata.requires(distribution_name)
    return [req.partition(" ")[0] for req in requirements]
