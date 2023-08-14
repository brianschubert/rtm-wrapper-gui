from __future__ import annotations

import logging
import pathlib
from typing import Any, Iterable

import packaging.version
import xarray as xr
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

import rtm_wrapper
from rtm_wrapper_gui import util
from rtm_wrapper_gui.simulation.base import SimulationProducerMixin


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

        if role == Qt.ItemDataRole.DisplayRole.FontRole and index.column() == 0:
            font = QtGui.QFont()
            font.setBold(True)
            return font

        return super().data(index, role)

    def _is_special_data(self, index: QtCore.QModelIndex) -> bool:
        file_info = self.fileInfo(index)
        return file_info.isFile() and file_info.suffix() in self.data_suffixes


class FileSimulationProducer(SimulationProducerMixin, QtWidgets.QWidget):
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
        selected_file = _show_open_file_dialog(
            caption="Select results file", filter="netCDF File (*.nc);;Any File (*)"
        )
        if selected_file is not None:
            self._load_dataset(selected_file)

    def _load_dataset(self, file: str | pathlib.Path) -> None:
        logger = logging.getLogger(__name__)

        path = pathlib.Path(file)

        try:
            dataset = xr.open_dataset(path)
        except Exception as ex:
            QtWidgets.QMessageBox.warning(
                self,
                "Invalid netCDF file",
                f"<tt>{file}</tt> is not a valid netCDF file.",
            )
            logger.warning("failed to load dataset", exc_info=ex)
            return
        logger.debug("loaded dataset\n%r", dataset)

        confirm_load = _interactive_confirm_version(self, dataset)

        if confirm_load:
            results = util.RtmResults(dataset, path)
            self.new_results.emit(results)


def _show_open_file_dialog(caption: str, filter: str) -> pathlib.Path | None:
    logger = logging.getLogger(__name__)

    dialog = QtWidgets.QFileDialog()

    selected_file, _selected_filter = dialog.getOpenFileName(
        None,
        caption,
        str(pathlib.Path.cwd()),
        filter,
    )
    if selected_file == "":
        # Dialog was closed / cancelled.
        logger.debug("file selection cancelled")
        return None

    return pathlib.Path(selected_file)


def _interactive_confirm_version(
    parent: QtWidgets.QWidget, dataset: xr.Dataset
) -> bool:
    try:
        version_attr: str = dataset.attrs["version"]
    except KeyError:
        reply = QtWidgets.QMessageBox.question(
            parent,
            "Missing version",
            "Dataset has no recorded version tag. Load anyway?",
        )
        return reply == QtWidgets.QMessageBox.StandardButton.Yes

    try:
        parsed_version = packaging.version.parse(version_attr)
    except (AttributeError, ValueError):
        reply = QtWidgets.QMessageBox.question(
            parent,
            "Malformed version",
            f"Could not interpret dataset generation version '{version_attr}'. Load anyway?",
        )
        return reply == QtWidgets.QMessageBox.StandardButton.Yes

    current_version = packaging.version.parse(rtm_wrapper.__version__)

    if parsed_version.is_devrelease and not current_version.is_devrelease:
        reply = QtWidgets.QMessageBox.question(
            parent,
            "Confirm development version",
            f"Results were generated with a developmental version ({parsed_version})."
            f" The contents may not be compatible with the current version ({current_version}). "
            f"Load anyway?",
        )
        return reply == QtWidgets.QMessageBox.StandardButton.Yes

    if current_version.major != parsed_version.major:
        reply = QtWidgets.QMessageBox.question(
            parent,
            "Confirm different major version",
            f"Results were generated with a different major version ({parsed_version})."
            f" The contents may not be compatible with the current version ({current_version}). "
            f"Load anyway?",
        )
        return reply == QtWidgets.QMessageBox.StandardButton.Yes

    return True
