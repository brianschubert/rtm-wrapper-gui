"""
GUI elements for running simulations and loading simulation results.
"""

from __future__ import annotations

import logging
import pathlib
from typing import Any, Iterable

import xarray as xr
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from rtm_wrapper.engines.base import RTMEngine
from rtm_wrapper_gui import util


class SimulationPanel(QtWidgets.QWidget):
    sim_producers: SimulationProducerTabs

    results_tabs: ResultsTabSelection()

    active_results: util.WatchedBox[util.RtmResults]

    def __init__(
        self,
        results_box: util.WatchedBox[util.RtmResults],
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.active_results = results_box

        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)

        self.sim_producers = SimulationProducerTabs()
        layout.addWidget(self.sim_producers)

        self.results_tabs = ResultsTabSelection()
        layout.addWidget(self.results_tabs)

        self.sim_producers.new_results.connect(self.results_tabs.add_results)
        self.results_tabs.currentChanged[int].connect(self._on_result_selection_change)

    @QtCore.Slot(int)
    def _on_result_selection_change(self, tab_index: int) -> None:
        logger = logging.getLogger(__name__)
        logger.debug("selected results index %r", tab_index)
        if tab_index == -1:
            self.active_results.value = None
        else:
            display: ResultsSummaryDisplay = self.results_tabs.widget(tab_index)
            self.active_results.value = display.results


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


class DataFileSystemModel(QtWidgets.QFileSystemModel):
    """File system model that emphasizes particular data files."""

    data_suffixes: set[str]

    def __init__(self, suffixes: Iterable[str], *args: Any, **kwargs: Any) -> None:
        self.data_suffixes = set(suffixes)
        super().__init__(*args, **kwargs)

    def data(
        self,
        index: QtCore.QModelIndex,
        role: Qt.ItemDataRole = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if not self._is_special_data(index):
            return super().data(index, role)

        if role == Qt.ItemDataRole.DisplayRole.DecorationRole and index.column() == 0:
            return QtWidgets.QApplication.style().standardIcon(
                QtWidgets.QStyle.StandardPixmap.SP_FileDialogStart
            )

        if role == Qt.ItemDataRole.DisplayRole.FontRole:
            font = QtGui.QFont()
            font.setBold(True)
            return font

        return super().data(index, role)

    def _is_special_data(self, index: QtCore.QModelIndex) -> bool:
        file_info = self.fileInfo(index)
        return file_info.isFile() and file_info.suffix() in self.data_suffixes


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

        model = DataFileSystemModel(["nc"])
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


class ResultsTabSelection(QtWidgets.QTabWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)

        # Make tabs closable.
        # Closing tabs automatically changes the current tab.
        self.setTabsClosable(True)
        self.tabCloseRequested[int].connect(self.close_tab)

    @QtCore.Slot()
    def close_tab(self, index: int) -> None:
        # TODO maybe set background when all tabs are closed
        # https://stackoverflow.com/q/73530138/11082165

        widget = self.widget(index)
        widget.deleteLater()
        # Note: don't use removeTab - https://www.qtcentre.org/threads/35202-Removing-a-tab-in-QTabWidget-removes-tabs-to-right-as-well
        # self.tabBar().removeTab(index)

        # if self.tabBar().count() == 1:
        #     pass
        # TODO maybe add tab for help splash?

    @QtCore.Slot(util.RtmResults)
    def add_results(self, results: util.RtmResults) -> None:
        # Note: tab parent shouldn't be set.
        summary = ResultsSummaryDisplay(results)
        self.addTab(summary, f"Results {self.tabBar().count()}")


class ResultsSummaryDisplay(QtWidgets.QTextEdit):
    results: util.RtmResults

    def __init__(
        self, results: util.RtmResults, parent: QtWidgets.QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.results = results

        self.setText(repr(results))
        self.setLineWrapMode(QtWidgets.QTextEdit.LineWrapMode.NoWrap)
        self.setFont(QtGui.QFont("monospace"))
