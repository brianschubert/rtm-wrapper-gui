from __future__ import annotations

import ast
import builtins
import keyword
import logging
import re
import traceback
from typing import Final, Iterable

import black
import isort
import numpy
import xarray as xr
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from rtm_wrapper import simulation as rtm_sim
from rtm_wrapper.engines import base as rtm_engines
from rtm_wrapper_gui import util
from rtm_wrapper_gui.simulation import workers
from rtm_wrapper_gui.simulation.base import SimulationProducerMixin

_EXAMPLE_SWEEPS: Final[dict[str, str]] = {
    "Basic": """\
import numpy as np

from rtm_wrapper.engines.sixs import PySixSEngine, pysixs_default_inputs
from rtm_wrapper.simulation import SweepSimulation

sweep = SweepSimulation(
    {
        "wavelength.value": np.arange(0.2, 2.5, 0.005),
    },
    base=pysixs_default_inputs(),
)

engine = PySixSEngine()
""",
    "Ozone Sweep": """\
import numpy as np

import rtm_wrapper.parameters as rtm_param
from rtm_wrapper.engines.sixs import PySixSEngine, pysixs_default_inputs
from rtm_wrapper.simulation import SweepSimulation

sweep = SweepSimulation(
    {
        "wavelength.value": np.arange(0.5, 0.65, 0.0025),
        "atmosphere.ozone": np.arange(0.4, 0.61, 0.04),
    },
    base=pysixs_default_inputs().replace(atmosphere=rtm_param.AtmosphereWaterOzone(water=2.0)),
)

engine = PySixSEngine()
""",
    "Profile Grid": """\
import numpy as np

import rtm_wrapper.parameters as rtm_param
from rtm_wrapper.engines.sixs import PySixSEngine, pysixs_default_inputs
from rtm_wrapper.simulation import SweepSimulation

sweep = SweepSimulation(
    {
        "wavelength.value": np.arange(0.2, 2.5, 0.005),
        "atmosphere.name": ["MidlatitudeSummer", "SubarcticWinter", "Tropical"],
        "aerosol_profile.name": ["Maritime", "Urban", "Continental"],
    },
    base=pysixs_default_inputs(),
)

engine = PySixSEngine()
""",
}


class ScriptSimulationProducer(SimulationProducerMixin, QtWidgets.QWidget):
    script_textedit: ScriptTextEdit

    run_button: QtWidgets.QPushButton

    check_button: QtWidgets.QPushButton

    format_button: QtWidgets.QPushButton

    example_button: QtWidgets.QPushButton

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

        self.example_button = QtWidgets.QPushButton()
        self.example_button.setIcon(
            self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DirOpenIcon)
        )
        self.example_button.setText("Example")
        button_layout.addWidget(self.example_button)

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
        self.example_button.clicked.connect(self.load_example)

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

    def load_example(self) -> None:
        logger = logging.getLogger(__name__)

        selection, clicked_ok = QtWidgets.QInputDialog.getItem(
            self, "Select example", "Example:", list(_EXAMPLE_SWEEPS.keys())
        )

        if not clicked_ok:
            logger.debug("user cancelled example load")
            return

        logger.debug("loading example '%r'", selection)
        self.script_textedit.setText(_EXAMPLE_SWEEPS[selection])

    def _on_run_click(self) -> None:
        try:
            job = workers.ExecJob(
                compile(
                    self.script_textedit.toPlainText(), "<user script>", mode="exec"
                ),
                globals={
                    "display": lambda obj: QtWidgets.QMessageBox.about(
                        None, "Script display", f"<pre>{obj}</pre>"
                    ),
                    "logger": logging.getLogger(f"{__name__}.<user script>"),
                },
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
        self.setText('# Click "Example" to load an example script.')

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
                (_common_ident_pattern(), builtins_format),
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


def _common_ident_pattern() -> str:
    """
    Return regex pattern for matching commons identifiers.

    The returned pattern matches both Python builtins and top-level numpy identifiers.
    """

    builtin_alts = "|".join(dir(builtins))
    builtins_pattern = f"(?:{builtin_alts})"

    numpy_alts = "|".join(dir(numpy))
    numpy_pattern = rf"(?:n(?:p|umpy)\.(?:{numpy_alts}))"

    return rf"\b(?:{builtins_pattern}|{numpy_pattern})\b"
