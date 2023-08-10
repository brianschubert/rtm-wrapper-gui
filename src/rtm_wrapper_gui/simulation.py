"""
GUI elements for running simulations and loading simulation results.
"""

from __future__ import annotations

import logging
import pathlib

import xarray as xr
from PySide6 import QtCore, QtGui, QtWidgets

from rtm_wrapper.engines.base import RTMEngine
from rtm_wrapper_gui import util


class SimulationPanel(QtWidgets.QWidget):
    sim_producers: SimulationProducerTabs

    summary: ResultsSummary

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)

        self.sim_producers = SimulationProducerTabs()
        layout.addWidget(self.sim_producers)

        self.summary = ResultsSummary()
        layout.addWidget(self.summary)

        self.sim_producers.new_results.connect(self.summary.summarize_results)


class SimulationProducer(QtWidgets.QWidget):
    new_results = QtCore.Signal(util.RtmResults)


class SimulationProducerTabs(SimulationProducer):
    tabs: QtWidgets.QTabWidget

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)

        self.tabs = QtWidgets.QTabWidget()
        layout.addWidget(self.tabs)

        self.tabs.addTab(
            FileSimulationProducer(),
            self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_FileIcon),
            "File",
        )

        for idx in range(self.tabs.count()):
            self.tabs.widget(idx).new_results.connect(self.new_results)


class FileSimulationProducer(SimulationProducer):
    browse_button: QtWidgets.QPushButton

    file_tree: QtWidgets.QTreeView

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)

        self.browse_button = QtWidgets.QPushButton(self)
        self.browse_button.setText("Browse")
        layout.addWidget(self.browse_button)

        self.file_tree = QtWidgets.QTreeView(self)
        layout.addWidget(self.file_tree)

        model = QtWidgets.QFileSystemModel()
        # Only enable file watcher for CWD.
        model.setRootPath(QtCore.QDir.currentPath())
        self.file_tree.setModel(model)
        # Only display tree for CWD and below. For files outside the CWD, users
        # can use the browse button.
        self.file_tree.setRootIndex(model.index(QtCore.QDir.currentPath()))
        # Make sure full filenames are visible.
        self.file_tree.header().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.ResizeToContents
        )

        self._init_signals()

    def _init_signals(self) -> None:
        self.browse_button.clicked.connect(self._on_browse_button_clicked)
        self.file_tree.doubleClicked.connect(
            lambda index: self._load_dataset(self.file_tree.model().filePath(index))
        )

    @QtCore.Slot()
    def _on_browse_button_clicked(self) -> None:
        logger = logging.getLogger(__name__)
        dialog = QtWidgets.QFileDialog()

        selected_file, _selected_filter = dialog.getOpenFileName(
            None,
            "Select results file",
            str(pathlib.Path.cwd()),
            "netCDF File (*.nc);;Any File (*)",
        )
        if selected_file == "":
            # Dialog was closed / cancelled.
            logger.debug("file selection cancelled")
            return

        self._load_dataset(selected_file)

    def _load_dataset(self, file: str | pathlib.Path) -> None:
        logger = logging.getLogger(__name__)
        try:
            dataset = xr.open_dataset(file)
        except Exception as ex:
            logger.error("failed to load dataset", exc_info=ex)
            return
        logger.debug("loaded dataset\n%r", dataset)

        self.new_results.emit(util.RtmResults(dataset))


class InteractiveNewSimulationProducer(SimulationProducer):
    known_engines: list[RTMEngine]


class ResultsSummary(QtWidgets.QWidget):
    temp_textedit: QtWidgets.QTextEdit

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)

        self.temp_textedit = QtWidgets.QTextEdit()
        self.temp_textedit.setText("No simulation results loaded.")
        self.temp_textedit.setLineWrapMode(QtWidgets.QTextEdit.LineWrapMode.NoWrap)
        self.temp_textedit.setFont(QtGui.QFont("monospace"))
        layout.addWidget(self.temp_textedit)

    @QtCore.Slot(util.RtmResults)
    def summarize_results(self, results: util.RtmResults) -> None:
        self.temp_textedit.setText(repr(results))
