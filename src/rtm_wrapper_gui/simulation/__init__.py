"""
GUI elements for running simulations and loading simulation results.
"""

from __future__ import annotations

import base64
import datetime
import gzip
import itertools
import logging
import pathlib
import pickle
import typing
from typing import ClassVar, Iterator

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

import rtm_wrapper.parameters as rtm_param
import rtm_wrapper.simulation as rtm_sim
from rtm_wrapper_gui import util

from .base import SimulationProducerMixin
from .file import FileSimulationProducer
from .interactive import InteractiveSimulationProducer
from .script import ScriptSimulationProducer


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
            display: ResultsSummaryDisplay = self.results_tabs.widget(tab_index)  # type: ignore
            self.active_results.value = display.results


class SimulationProducerTabs(SimulationProducerMixin, QtWidgets.QTabWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)

        self.addTab(
            FileSimulationProducer(),
            self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_FileIcon),
            "File",
        )
        self.addTab(
            InteractiveSimulationProducer(),
            self.style().standardIcon(
                QtWidgets.QStyle.StandardPixmap.SP_FileDialogDetailedView
            ),
            "Run",
        )
        self.addTab(
            ScriptSimulationProducer(),
            self.style().standardIcon(
                QtWidgets.QStyle.StandardPixmap.SP_ToolBarHorizontalExtensionButton,
            ),
            "Script",
        )

        for idx in range(self.count()):
            self.widget(idx).new_results.connect(self.new_results)


class ResultsTabSelection(QtWidgets.QTabWidget):
    tab_counter: ClassVar[Iterator[int]] = itertools.count(1)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)

        # Make tabs closable.
        # Closing tabs automatically changes the current tab.
        self.setTabsClosable(True)
        self.tabCloseRequested[int].connect(self.close_tab)
        self.tabBarDoubleClicked[int].connect(
            lambda index: self.widget(index)._prompt_save()  # type: ignore
        )

    @QtCore.Slot()
    def close_tab(self, index: int) -> None:
        # TODO maybe set background when all tabs are closed
        # https://stackoverflow.com/q/73530138/11082165

        widget: ResultsSummaryDisplay = self.widget(index)  # type: ignore
        tab_name = self.tabText(index)
        if widget.results.file is None:
            reply = QtWidgets.QMessageBox.question(
                self,
                "Close unsaved results",
                f"Close '{tab_name}' without saving?",
                QtWidgets.QMessageBox.StandardButton.Discard
                | QtWidgets.QMessageBox.StandardButton.Cancel,
                QtWidgets.QMessageBox.StandardButton.Cancel,
            )
            if reply != QtWidgets.QMessageBox.StandardButton.Discard:
                return

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
        summary.details_changed.connect(self.refresh_current_label)
        if results.file is not None:
            tab_name = results.file.name
        else:
            tab_name = f"*Unsaved {next(self.tab_counter)}"
        index = self.addTab(summary, tab_name)
        self.setCurrentIndex(index)

    @QtCore.Slot()
    def refresh_current_label(self) -> None:
        idx = self.currentIndex()
        widget: ResultsSummaryDisplay = self.currentWidget()  # type: ignore
        self.setTabText(idx, widget.results.file.name)


class ResultsSummaryDisplay(QtWidgets.QTreeWidget):
    results: util.RtmResults

    details_changed = QtCore.Signal()

    def __init__(
        self, results: util.RtmResults, parent: QtWidgets.QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.results = results

        self.setColumnCount(2)
        self.setHeaderLabels(["Field", "Value"])
        self.header().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.ResizeToContents
        )
        self.setIndentation(12)
        self.setStyleSheet(
            """
            QTreeView::item { padding: 2px 0px 2px 0px }
            """
        )

        top_items = [
            self._load_fileinfo(),
            self._load_outputs(),
            self._load_sweep(),
            self._load_base_inputs(),
            self._load_attributes(),
        ]
        self.insertTopLevelItems(0, top_items)

        # self.expandAll()
        for item in top_items:
            self.expandItem(item)

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if (
            event.key() == Qt.Key.Key_S
            and event.modifiers() == Qt.KeyboardModifier.ControlModifier
        ):
            self._prompt_save()

    def _prompt_save(self) -> None:
        if self.results.file is not None:
            suggested_name = self.results.file.name
        else:
            timestamp = datetime.datetime.fromisoformat(
                self.results.dataset.attrs["sim_start"]
            )
            suggested_name = f"results_{timestamp:%Y%m%dT%H%M%S.nc}"

        selected_path = _show_save_file_dialog(
            "Select save location", "netCDF File (*.nc);;Any File (*)", suggested_name
        )
        if selected_path is None:
            return

        self.results.dataset.to_netcdf(selected_path)
        self.results.file = selected_path

        _old_fileinfo = self.takeTopLevelItem(0)
        self.insertTopLevelItem(0, self._load_fileinfo())
        self.details_changed.emit()

    def _load_fileinfo(self) -> QtWidgets.QTreeWidgetItem:
        if self.results.file is None:
            top_item = QtWidgets.QTreeWidgetItem(["File", "<not saved>"])
            top_item.setIcon(
                0,
                self.style().standardIcon(
                    QtWidgets.QStyle.StandardPixmap.SP_MessageBoxWarning
                ),
            )
            return top_item

        top_item = QtWidgets.QTreeWidgetItem(
            ["File", self.results.file.name],
        )
        size = self.results.file.stat().st_size / 1024
        size_suffix = "KiB"
        if size >= 1024:
            size /= 1024
            size_suffix = "MiB"
        if size >= 1024:
            size /= 1024
            size_suffix = "GiB"

        top_item.addChild(QtWidgets.QTreeWidgetItem(["Path", str(self.results.file)]))
        top_item.addChild(
            QtWidgets.QTreeWidgetItem(["Size", f"{size:.2f} {size_suffix}"])
        )
        top_item.addChild(
            QtWidgets.QTreeWidgetItem(["Mode", f"{self.results.file.stat().st_mode:o}"])
        )
        top_item.addChild(
            QtWidgets.QTreeWidgetItem(
                [
                    "Modified",
                    datetime.datetime.fromtimestamp(self.results.file.stat().st_mtime)
                    .astimezone()
                    .isoformat(),
                ]
            )
        )

        top_item.setIcon(
            0, self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_FileIcon)
        )
        return top_item

    def _load_sweep(self) -> QtWidgets.QTreeWidgetItem:
        dims = list(self.results.dataset.indexes.dims.items())
        top_item = QtWidgets.QTreeWidgetItem(
            ["Sweep", f"({len(dims)})"],
        )
        for dim_name, dim_size in dims:
            assoc_coords = [
                coord
                for coord in self.results.dataset.coords.values()
                if dim_name in coord.dims
            ]
            dim_branch = QtWidgets.QTreeWidgetItem(
                [dim_name, f"size={dim_size} ({len(assoc_coords)})"]
            )
            top_item.addChild(dim_branch)

            for coord in assoc_coords:
                simplified_dims = [
                    f"{dim}={size}"
                    if rtm_sim._PARAMETER_AXES_SEP not in dim
                    else f"{size}"
                    for dim, size in coord.sizes.items()
                ]
                coord_branch = QtWidgets.QTreeWidgetItem(
                    [coord.name, f"{coord.dtype.name} ({', '.join(simplified_dims)})"]
                )
                dim_branch.addChild(coord_branch)

                # TODO replace with buttons to show details
                # Display values in first column so that resizing kicks in.
                # Last column is set to only stretch.
                values_branch = QtWidgets.QTreeWidgetItem(
                    ["values", "<click to expand>"],
                )
                values_branch.addChild(
                    QtWidgets.QTreeWidgetItem([repr(coord.values.tolist())])
                )
                coord_branch.addChild(values_branch)

                for attr_name, attr_value in coord.attrs.items():
                    coord_branch.addChild(
                        QtWidgets.QTreeWidgetItem(
                            [attr_name, str(attr_value)],
                        )
                    )

        top_item.setIcon(
            0,
            self.style().standardIcon(
                QtWidgets.QStyle.StandardPixmap.SP_FileDialogContentsView
            ),
        )
        return top_item

    def _load_outputs(self) -> QtWidgets.QTreeWidgetItem:
        top_item = QtWidgets.QTreeWidgetItem(
            ["Outputs", f"({len(self.results.dataset.data_vars)})"],
        )

        for output in self.results.dataset.data_vars.values():
            output_branch = QtWidgets.QTreeWidgetItem(
                [output.name, f"{output.dtype.name} {repr(output.shape)}"]
            )

            # TODO replace with buttons to show details
            # Display values in first column so that resizing kicks in.
            # Last column is set to only stretch.
            values_branch = QtWidgets.QTreeWidgetItem(
                ["values", "<click to expand>"],
            )
            values_branch.addChild(
                QtWidgets.QTreeWidgetItem([repr(output.values.tolist())])
            )
            output_branch.addChild(values_branch)

            for attr_name, attr_value in output.attrs.items():
                output_branch.addChild(
                    QtWidgets.QTreeWidgetItem(
                        [attr_name, str(attr_value)],
                    )
                )
            top_item.addChild(output_branch)

        top_item.setIcon(
            0,
            self.style().standardIcon(
                QtWidgets.QStyle.StandardPixmap.SP_DialogSaveButton
            ),
        )
        return top_item

    def _load_attributes(self) -> QtWidgets.QTreeWidgetItem:
        top_item = QtWidgets.QTreeWidgetItem(
            ["Attributes", f"({len(self.results.dataset.attrs)})"],
        )

        for name, value in self.results.dataset.attrs.items():
            leaf = QtWidgets.QTreeWidgetItem([name, value])
            top_item.addChild(leaf)

        top_item.setIcon(
            0,
            self.style().standardIcon(
                QtWidgets.QStyle.StandardPixmap.SP_FileDialogInfoView
            ),
        )
        return top_item

    def _load_base_inputs(self) -> QtWidgets.QTreeWidgetItem:
        # TODO add --safe flag to disable unpickling
        logger = logging.getLogger(__name__)

        try:
            base_payload = self.results.dataset.attrs["base_pzb64"]
        except KeyError:
            logger.debug("dataset missing base inputs")
            return QtWidgets.QTreeWidgetItem(["Base Inputs", "<not available>"])

        base_inputs = pickle.loads(gzip.decompress(base64.b64decode(base_payload)))

        children = list(_parameter_tree(base_inputs))
        top_item = QtWidgets.QTreeWidgetItem(["Base Inputs", f"({len(children)})"])
        top_item.addChildren(children)

        top_item.setIcon(
            0,
            self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_ArrowForward),
        )

        return top_item


def _show_save_file_dialog(
    caption: str, filter: str, default_name: str = ""
) -> pathlib.Path | None:
    logger = logging.getLogger(__name__)

    dialog = QtWidgets.QFileDialog()

    selected_file, _selected_filter = dialog.getSaveFileName(
        None,
        caption,
        str(pathlib.Path.cwd().joinpath(default_name)),
        filter,
    )
    if selected_file == "":
        # Dialog was closed / cancelled.
        logger.debug("file selection cancelled")
        return None

    return pathlib.Path(selected_file)


def _parameter_tree(param: rtm_param.Parameter) -> Iterator[QtWidgets.QTreeWidgetItem]:
    hints = typing.get_type_hints(type(param))

    for hint_name in hints.keys():
        value = getattr(param, hint_name)
        if isinstance(value, rtm_param.Parameter):
            branch = QtWidgets.QTreeWidgetItem([hint_name, type(value).__name__])
            for child in _parameter_tree(value):
                branch.addChild(child)
        else:
            branch = QtWidgets.QTreeWidgetItem([hint_name, repr(value)])
            for meta_key, meta_value in param.get_metadata(hint_name).items():
                branch.addChild(QtWidgets.QTreeWidgetItem([meta_key, meta_value]))
        yield branch
