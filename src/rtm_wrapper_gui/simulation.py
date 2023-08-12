"""
GUI elements for running simulations and loading simulation results.
"""

from __future__ import annotations

import ast
import base64
import builtins
import dataclasses
import datetime
import gzip
import itertools
import keyword
import logging
import pathlib
import pickle
import pprint
import re
import traceback
import typing
from typing import Any, ClassVar, Final, Iterable, Iterator

import black
import isort
import xarray as xr
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

import rtm_wrapper.engines.base as rtm_engines
import rtm_wrapper.parameters as rtm_param
import rtm_wrapper.simulation as rtm_sim
from rtm_wrapper.engines.base import RTMEngine
from rtm_wrapper_gui import util, workers


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

    _SPECIAL_IDENTS: Final = ["sweep", "engine"]

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
from rtm_wrapper.simulation import SweepSimulation

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

        builtins_format = QtGui.QTextCharFormat()
        builtins_format.setForeground(Qt.GlobalColor.darkMagenta)

        string_format = QtGui.QTextCharFormat()
        string_format.setForeground(Qt.GlobalColor.darkGreen)

        number_format = QtGui.QTextCharFormat()
        number_format.setForeground(Qt.GlobalColor.blue)

        comment_format = QtGui.QTextCharFormat()
        comment_format.setForeground(Qt.GlobalColor.darkGray)
        comment_format.setFontItalic(True)

        special_format = QtGui.QTextCharFormat()
        special_format.setFontWeight(QtGui.QFont.Weight.Bold)

        self._highlighter = RegexHighlighter(
            [
                (rf"\b(?:{'|'.join(keyword.kwlist)})\b", keyword_format),
                (rf"\b(?:{'|'.join(dir(builtins))})\b", builtins_format),
                ("([\"'])[^\\1]*?\\1", string_format),
                (r"\b[0-9]+\b", number_format),
                # TODO improve handling with quotes.
                # Only highlight comments on lines that don't contain ' or ".
                (r"^(?:[^'\"]*)\#.*$", comment_format),
                (rf"\b(?:{'|'.join(self._SPECIAL_IDENTS)})\b", special_format),
            ],
            self.document(),
        )

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        # Replace tabs with spaces.
        # https://stackoverflow.com/q/45880941/11082165
        if event.key() == Qt.Key.Key_Tab:
            event = QtGui.QKeyEvent(
                event.type(),
                Qt.Key.Key_Space,
                event.modifiers(),
                "    ",
            )
        super().keyPressEvent(event)


class ScriptSimulationProducer(SimulationProducer):
    script_textedit: ScriptTextEdit

    run_button: QtWidgets.QPushButton

    check_button: QtWidgets.QPushButton

    format_button: QtWidgets.QPushButton

    exec_worker: workers.PythonExecWorker
    exec_thread: QtCore.QThread

    sim_worker: workers.RtmSimulationWorker
    sim_thread: QtCore.QThread

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_widgets()
        self._init_workers()
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
            self.style().standardIcon(
                QtWidgets.QStyle.StandardPixmap.SP_CommandLink
            )  # SP_MediaPlay
        )
        self.run_button.setText("Run")
        button_layout.addWidget(self.run_button)

        self.check_button = QtWidgets.QPushButton()
        self.check_button.setIcon(
            self.style().standardIcon(
                QtWidgets.QStyle.StandardPixmap.SP_DialogHelpButton  # SP_MessageBoxQuestion
            )
        )
        self.check_button.setText("Check")
        button_layout.addWidget(self.check_button)

        self.format_button = QtWidgets.QPushButton()
        self.format_button.setIcon(
            self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_BrowserReload)
        )
        self.format_button.setText("Format")
        button_layout.addWidget(self.format_button)

    def _init_workers(self) -> None:
        # Exec worker.
        self.exec_thread = QtCore.QThread()

        self.exec_worker = workers.PythonExecWorker()
        self.exec_worker.moveToThread(self.exec_thread)

        self.exec_thread.setObjectName(f"{self.__class__.__name__}-ExecWorker")
        self.exec_thread.start()

        # Simulation worker.
        self.sim_thread = QtCore.QThread()

        self.sim_worker = workers.RtmSimulationWorker()
        self.sim_worker.moveToThread(self.sim_thread)

        self.sim_thread.setObjectName(f"{self.__class__.__name__}-SimWorker")
        self.sim_thread.start()

        # Make the Python thread name match the QThread object name.
        workers.ThreadNameSyncWorker.sync_thread_names(self.exec_thread)
        workers.ThreadNameSyncWorker.sync_thread_names(self.sim_thread)

    def _init_signals(self) -> None:
        self.check_button.clicked.connect(self.check_script)
        self.run_button.clicked.connect(self._on_run_click)
        self.format_button.clicked.connect(self.format_script)

        self.exec_worker.finished[workers.ExecJob].connect(self._on_exec_job_finished)
        self.exec_worker.exception.connect(
            lambda ex: QtWidgets.QMessageBox.warning(
                self,
                "Error running script",
                f"Exception raised during script interpretation: <pre>{ex}</pre>",
            )
        )

        self.sim_worker.results[xr.Dataset].connect(self._on_sim_finished)
        self.sim_worker.exception.connect(
            lambda ex: QtWidgets.QMessageBox.warning(
                self,
                "Error running simulation",
                f"Exception raised during simulation execution: <pre>{ex}</pre>",
            )
        )

        QtCore.QCoreApplication.instance().aboutToQuit.connect(self._on_about_to_quit)

    @QtCore.Slot()
    def _on_about_to_quit(self) -> None:
        logger = logging.getLogger(__name__)
        logger.debug("quitting exec thread")
        self.exec_thread.quit()
        logger.debug("waiting on exec thread")
        self.exec_thread.wait()
        logger.debug("exec thread terminated")

        logger.debug("quitting sim thread")
        self.sim_thread.quit()
        logger.debug("waiting on sim thread")
        self.sim_thread.wait()
        logger.debug("sim thread terminated")

    @QtCore.Slot()
    def check_script(self) -> bool:
        try:
            tree = ast.parse(self.script_textedit.toPlainText())
        except SyntaxError as ex:
            tb_exc = traceback.TracebackException.from_exception(ex)
            pos = f":{tb_exc.lineno}:{tb_exc.offset}"
            QtWidgets.QMessageBox.warning(
                self,
                "Script syntax error",
                f"Script contains a syntax error!"
                f"<br><br>"
                f"<pre>"
                f"&lt;user script&gt;{pos}:&nbsp;{tb_exc.text.replace(' ', '&nbsp;')}\n"
                f"{'&nbsp;' * (14 + len(pos) + tb_exc.offset)}^"
                f"<pre>",
            )
            return False

        assignments = [
            target.id
            for node in tree.body
            if isinstance(node, ast.Assign)
            for target in node.targets
        ]
        for ident in self.script_textedit._SPECIAL_IDENTS:
            if ident not in assignments:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Missing required assigment",
                    f"Missing assignment to required identifier <tt>{ident}</tt>"
                    f"<br><br>"
                    f"Make sure the script includes and assignment of the form <pre>{ident} = ...</pre>",
                )
                return False

        QtWidgets.QMessageBox.information(self, "Script OK", "No issues found!")

        return True

    @QtCore.Slot()
    def format_script(self) -> None:
        try:
            formatted_text = black.format_str(
                self.script_textedit.toPlainText(), mode=black.FileMode()
            )
            isort_config = isort.settings.Config(known_first_party=["rtm_wrapper"])
            formatted_text = isort.code(formatted_text, config=isort_config)
            self.script_textedit.setText(formatted_text)
        except AttributeError as ex:
            # Black does not currently expose a public API.
            # The internal API that we're using may change unexpectedly.
            QtWidgets.QMessageBox.warning(
                self,
                "Failed to format script",
                f"Unable to access black internal API. <pre>{ex}</pre>",
            )
        except black.parsing.InvalidInput as ex:
            QtWidgets.QMessageBox.warning(
                self,
                "Failed to format script",
                f"Failed to parse scrupt. <pre>{ex}</pre>",
            )

    def _on_run_click(self) -> None:
        try:
            job = workers.ExecJob(
                compile(
                    self.script_textedit.toPlainText(), "<user script>", mode="exec"
                ),
            )
        except Exception as ex:
            QtWidgets.QMessageBox.warning(
                self,
                "Cannot execute script",
                f"<pre>{ex}</pre>",
            )
            return
        progress_bar = QtWidgets.QProgressDialog(
            "Interpreting script", None, 0, 0, self
        )
        progress_bar.setWindowModality(Qt.WindowModality.WindowModal)
        progress_bar.setMinimumDuration(0)
        progress_bar.setValue(0)

        self.exec_worker.finished.connect(progress_bar.deleteLater)
        self.exec_worker.exception.connect(progress_bar.deleteLater)
        self.exec_worker.send_job.emit(job)

    def _on_exec_job_finished(self, job: workers.ExecJob) -> None:
        logger = logging.getLogger(__name__)
        logger.debug("received finished jobs with locals %r", list(job.locals.keys()))

        try:
            sweep = job.locals["sweep"]
        except KeyError:
            QtWidgets.QMessageBox.warning(
                self,
                "Bad script",
                "Script must define <tt>sweep</tt>",
            )
            return

        try:
            engine = job.locals["engine"]
        except KeyError:
            QtWidgets.QMessageBox.warning(
                self,
                "Bad script",
                "Script must define <tt>engine</tt>",
            )
            return

        if not isinstance(sweep, rtm_sim.SweepSimulation):
            QtWidgets.QMessageBox.warning(
                self,
                "Bad script",
                "<tt>sweep</tt> must be an instance of <tt>SweepSimulation</tt>",
            )
            return

        if not isinstance(engine, rtm_engines.RTMEngine):
            QtWidgets.QMessageBox.warning(
                self,
                "Bad script",
                "<tt>engine</tt> must be an instance of <tt>RTMEngine</tt>",
            )
            return

        reply = QtWidgets.QMessageBox.question(
            self,
            "Confirm simulation",
            f"Requested simulation has {sweep.sweep_size} steps."
            f"<br><br>"
            f"{'<br>'.join(f'<tt>{dim_name}: {dim_size}</tt>' for dim_name, dim_size in sweep.sweep_spec.indexes.dims.items())}"
            f"<br><br>"
            f"Run simulation?",
        )
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            # TODO customize progress bar to show sims/s, runtime, and ETA.
            progress_bar = QtWidgets.QProgressDialog(
                "Running Simulation", None, 0, sweep.sweep_size, self
            )
            progress_bar.setWindowModality(Qt.WindowModality.WindowModal)
            progress_bar.setMinimumDuration(0)
            progress_bar.setValue(0)

            self.sim_worker.results.connect(progress_bar.deleteLater)
            self.sim_worker.exception.connect(progress_bar.deleteLater)
            self.sim_worker.progress_changed[int].connect(progress_bar.setValue)
            self.sim_worker.send_job.emit(
                workers.SimulationJob(engine=engine, sweep=sweep)
            )

    def _on_sim_finished(self, sim_results: xr.Dataset) -> None:
        self.new_results.emit(util.RtmResults(sim_results, None))


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
            self._load_dims(),
            self._load_coords(),
            self._load_base_inputs(),
            self._load_attributes(),
        ]
        self.insertTopLevelItems(0, top_items)
        # self.expandAll()

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

        top_item.setIcon(
            0, self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_FileIcon)
        )
        return top_item

    def _load_dims(self) -> QtWidgets.QTreeWidgetItem:
        dims = list(self.results.dataset.indexes.dims.items())
        top_item = QtWidgets.QTreeWidgetItem(
            ["Sweep Dimensions", f"({len(dims)})"],
        )
        for dim_name, dim_size in dims:
            top_item.addChild(QtWidgets.QTreeWidgetItem([dim_name, f"{dim_size}"]))

        top_item.setIcon(
            0,
            self.style().standardIcon(
                QtWidgets.QStyle.StandardPixmap.SP_FileDialogContentsView
            ),
        )
        return top_item

    def _load_coords(self) -> QtWidgets.QTreeWidgetItem:
        coords = list(self.results.dataset.coords.values())
        top_item = QtWidgets.QTreeWidgetItem(
            ["Sweep Coordinates", f"({len(coords)})"],
        )
        for coord in coords:
            simplified_dims = [
                dim if rtm_sim._PARAMETER_AXES_SEP not in dim else ":"
                for dim in coord.dims
            ]
            coord_branch = QtWidgets.QTreeWidgetItem(
                [coord.name, f"({', '.join(simplified_dims)})"]
            )
            coord_branch.addChild(
                QtWidgets.QTreeWidgetItem(
                    ["type", f"{coord.dtype.name} {repr(coord.shape)}"],
                )
            )
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
            top_item.addChild(coord_branch)

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
