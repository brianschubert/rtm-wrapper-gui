"""
QThread workers.
"""

from __future__ import annotations

import dataclasses
import itertools
import logging.config
import threading
import types
from dataclasses import dataclass
from typing import Any

import xarray as xr
from PySide6 import QtCore, QtTest, QtWidgets

import rtm_wrapper.engines.base as rtm_engine
import rtm_wrapper.execution as rtm_exec
import rtm_wrapper.simulation as rtm_sim


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


@dataclass
class SimulationJob:
    engine: rtm_engine.RTMEngine
    sweep: rtm_sim.SweepSimulation


class RtmSimulationWorker(QtCore.QObject):
    send_job = QtCore.Signal(SimulationJob)

    progress_changed = QtCore.Signal(int)

    results = QtCore.Signal(xr.Dataset)

    exception = QtCore.Signal(Exception)

    max_workers: int | None = None

    def __init__(
        self, max_workers: int | None = None, parent: QtWidgets.QWidget | None = None
    ) -> None:
        super().__init__(parent)

        self.max_workers = max_workers

        self.send_job[SimulationJob].connect(self.run_simulation)

    @QtCore.Slot(SimulationJob)
    def run_simulation(self, job: SimulationJob) -> None:
        logger = logging.getLogger(__name__)
        runner = rtm_exec.ConcurrentExecutor(self.max_workers)

        step_counter = itertools.count(1)

        logger.debug("running sweep")
        try:
            runner.run(
                job.sweep,
                job.engine,
                step_callback=lambda _: self.progress_changed.emit(next(step_counter)),
            )
        except Exception as ex:
            logger.warning("exception raised during simulation job", exc_info=ex)
            self.exception.emit(ex)
            return

        logger.debug("finished sweep")

        results = runner.collect_results()
        self.results.emit(results)
