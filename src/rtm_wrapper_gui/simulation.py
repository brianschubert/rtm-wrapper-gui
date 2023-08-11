"""
GUI elements for running simulations and loading simulation results.
"""

from __future__ import annotations

import ast
import datetime
import itertools
import keyword
import logging
import pathlib
import re
import traceback
from typing import Any, ClassVar, Iterable, Iterator

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
            display: ResultsSummaryDisplay = self.results_tabs.widget(tab_index)  # type: ignore
            self.active_results.value = display.results


class SimulationProducer(QtWidgets.QWidget):
    new_results = QtCore.Signal(util.RtmResults)


class SimulationProducerTabs(QtWidgets.QTabWidget):
    new_results = QtCore.Signal(util.RtmResults)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)

        self.addTab(
            FileSimulationProducer(),
            self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_FileIcon),
            "File",
        )
        self.addTab(
            InteractiveNewSimulationProducer(),
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


class FileSimulationProducer(SimulationProducer, QtWidgets.QWidget):
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
            logger.error("failed to load dataset", exc_info=ex)
            return
        logger.debug("loaded dataset\n%r", dataset)

        results = util.RtmResults(dataset, path)
        self.new_results.emit(results)


class InteractiveNewSimulationProducer(SimulationProducer):
    known_engines: list[RTMEngine]


class RegexHighlighter(QtGui.QSyntaxHighlighter):
    """
    Syntax highlighter that applies formatting to regular expression matches.

    References
    ----------

    - https://doc.qt.io/qtforpython-6/PySide6/QtGui/QSyntaxHighlighter.html
    - https://doc.qt.io/qtforpython-6/examples/example_widgets_richtext_syntaxhighlighter.html
    - https://github.com/PySide/Examples/blob/master/examples/richtext/syntaxhighlighter.py
    """

    _patterns: list[tuple[re.Pattern, QtGui.QTextCharFormat]]

    def __init__(
        self,
        patterns: Iterable[tuple[re.Pattern | str, QtGui.QTextCharFormat]],
        parent: QtGui.QTextDocument | None = None,
    ) -> None:
        super().__init__(parent)
        self._patterns = [
            (re.compile(pattern), text_format) for pattern, text_format in patterns
        ]

    def highlightBlock(self, text: str) -> None:
        for pattern, text_format in self._patterns:
            for match in pattern.finditer(text):
                start, end = match.span()
                self.setFormat(start, end - start, text_format)


class ScriptTextEdit(QtWidgets.QTextEdit):
    _highlighter: RegexHighlighter

    def __init__(
        self,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.setAcceptRichText(False)
        self.setFont(QtGui.QFont("Monospace"))
        self.setLineWrapMode(QtWidgets.QTextEdit.LineWrapMode.NoWrap)
        self.setText(
            """\
import numpy as np

from rtm_wrapper.engines.sixs import PySixSEngine, pysixs_default_inputs

sweep = SweepSimulation(
    {
        "wavelength__value": np.arange(0.2, 2.5, 0.005),
    },
    base=pysixs_default_inputs(),
)

engine = PySixSEngine()
"""
        )

        keyword_format = QtGui.QTextCharFormat()
        keyword_format.setFontWeight(QtGui.QFont.Weight.Bold)
        keyword_format.setForeground(Qt.GlobalColor.darkBlue)

        string_format = QtGui.QTextCharFormat()
        string_format.setForeground(Qt.GlobalColor.darkGreen)

        number_format = QtGui.QTextCharFormat()
        number_format.setForeground(Qt.GlobalColor.blue)

        self._highlighter = RegexHighlighter(
            [
                (rf"\b(?:{'|'.join(keyword.kwlist)})\b", keyword_format),
                ("([\"'])[^\\1]*?\\1", string_format),
                ("[0-9]+", number_format),
            ],
            self.document(),
        )


class ScriptSimulationProducer(SimulationProducer):
    script_textedit: ScriptTextEdit

    run_button: QtWidgets.QPushButton

    check_button: QtWidgets.QPushButton

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_widgets()
        self._init_signals()

    def _init_widgets(self) -> None:
        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)
        self.script_textedit = ScriptTextEdit(self)

        layout.addWidget(self.script_textedit)

        button_layout = QtWidgets.QHBoxLayout()
        layout.addLayout(button_layout)

        self.run_button = QtWidgets.QPushButton()
        self.run_button.setIcon(
            self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_CommandLink)
        )  # SP_MediaPlay
        self.run_button.setText("Run")
        button_layout.addWidget(self.run_button)

        self.check_button = QtWidgets.QPushButton()
        self.check_button.setIcon(
            self.style().standardIcon(
                QtWidgets.QStyle.StandardPixmap.SP_DialogHelpButton  # SP_MessageBoxQuestion
            )
        )  # SP_MediaPlay
        self.check_button.setText("Check")
        button_layout.addWidget(self.check_button)

    def _init_signals(self) -> None:
        self.check_button.clicked.connect(self._on_check)

    def _on_check(self) -> None:
        logger = logging.getLogger(__name__)
        try:
            tree = ast.parse(self.script_textedit.toPlainText())
        except SyntaxError as ex:
            tb_exc = traceback.TracebackException.from_exception(ex)
            dialog = QtWidgets.QMessageBox()
            dialog.setWindowTitle("Script syntax error")
            dialog.setFont(QtGui.QFont("Monospace"))
            dialog.setIcon(QtWidgets.QMessageBox.Icon.Warning)
            dialog.setText(
                f"Script contains a syntax error!"
                f"\n\n"
                f"<user script>:{tb_exc.lineno}:{tb_exc.offset}: {tb_exc.text}"
            )
            dialog.setDetailedText("\n".join(tb_exc.format()))
            dialog.exec()
            return

        # assignments = [
        #     target.id
        #     for node in tree.body
        #     if isinstance(node, ast.Assign)
        #     for target in node.targets
        # ]

        dialog = QtWidgets.QMessageBox()
        dialog.setWindowTitle("Script OK")
        dialog.setFont(QtGui.QFont("Monospace"))
        dialog.setText("No issues found!")
        dialog.setIcon(QtWidgets.QMessageBox.Icon.Information)
        dialog.exec()


class ResultsTabSelection(QtWidgets.QTabWidget):
    tab_counter: ClassVar[Iterator[int]] = itertools.count(1)

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
        summary.details_changed.connect(self.refresh_current_label)
        if results.file is not None:
            tab_name = results.file.name
        else:
            tab_name = f"*Unsaved {next(self.tab_counter)}"
        self.addTab(summary, tab_name)

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
            self._load_attributes(),
        ]
        self.insertTopLevelItems(0, top_items)
        # self.expandAll()

        for col in range(self.columnCount()):
            self.resizeColumnToContents(col)

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if (
            event.key() == Qt.Key.Key_S
            and event.modifiers() == Qt.KeyboardModifier.ControlModifier
        ):
            selected_path = _show_save_file_dialog(
                "Select save location", "netCDF File (*.nc);;Any File (*)"
            )
            self.results.dataset.to_netcdf(selected_path)
            self.results.file = selected_path

            _old_fileinfo = self.takeTopLevelItem(0)
            self.insertTopLevelItem(0, self._load_fileinfo())
            self.details_changed.emit()

    def _load_fileinfo(self) -> QtWidgets.QTreeWidgetItem:
        if self.results.file is None:
            return QtWidgets.QTreeWidgetItem(["File", "<not saved>"])

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

        return top_item

    def _load_outputs(self) -> QtWidgets.QTreeWidgetItem:
        top_item = QtWidgets.QTreeWidgetItem(
            ["Outputs", f"({len(self.results.dataset.data_vars)})"],
        )

        for name in sorted(self.results.dataset.data_vars.keys()):
            leaf = QtWidgets.QTreeWidgetItem([name])
            top_item.addChild(leaf)

        return top_item

    def _load_attributes(self) -> QtWidgets.QTreeWidgetItem:
        top_item = QtWidgets.QTreeWidgetItem(
            ["Attributes", f"({len(self.results.dataset.attrs)})"],
        )

        for name, value in self.results.dataset.attrs.items():
            leaf = QtWidgets.QTreeWidgetItem([name, value])
            top_item.addChild(leaf)

        return top_item


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


def _show_save_file_dialog(caption: str, filter: str) -> pathlib.Path | None:
    logger = logging.getLogger(__name__)

    dialog = QtWidgets.QFileDialog()

    selected_file, _selected_filter = dialog.getSaveFileName(
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
