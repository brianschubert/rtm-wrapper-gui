from __future__ import annotations

import logging
from typing import Any

from PySide6 import QtWidgets
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon

from rtm_wrapper_gui import util
from rtm_wrapper_gui.plot.widgets import RtmResultsPlots
from rtm_wrapper_gui.simulation import SimulationPanel


class MainWindow(QtWidgets.QMainWindow):
    central_widget: QtWidgets.QWidget

    simulation_panel: SimulationPanel

    plots_widget: RtmResultsPlots

    active_results: util.WatchedBox[util.RtmResults | None]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        self.active_results = util.WatchedBox(None, self)
        self.active_results.value_changed.connect(
            lambda: logging.debug("value changed")
        )

        self._init_window()
        self._init_central_widget()

        version_info = util.make_detailed_version(util.DISTRIBUTION_NAME).replace(
            " (", "\n("
        )
        self.plots_widget.figure_widget.show_splash(
            version_info,
            horizontalalignment="center",
            color="grey",
            fontstyle="italic",
            wrap=True,
        )

    def _init_window(self) -> None:
        self.setWindowTitle("RTM Wrapper GUI")
        self.setWindowIcon(QIcon.fromTheme("applications-science"))

    def _init_central_widget(self) -> None:
        # Setup central widget and layout.
        self.central_widget = QtWidgets.QWidget()
        top_layout = QtWidgets.QVBoxLayout()
        self.central_widget.setLayout(top_layout)
        self.setCentralWidget(self.central_widget)

        # Add main vertical splitter.
        self.simulation_panel = SimulationPanel(self.active_results, self)
        self.plots_widget = RtmResultsPlots(self)

        top_splitter = QtWidgets.QSplitter(Qt.Orientation.Horizontal, self)
        top_splitter.addWidget(self.simulation_panel)
        top_splitter.addWidget(self.plots_widget)
        top_splitter.setHandleWidth(10)
        top_layout.addWidget(top_splitter)

        # Only stretch plots.
        top_splitter.setStretchFactor(0, 0)
        top_splitter.setStretchFactor(1, 1)
        # Note: not actual sizes. Describes how missing space is distributed.
        top_splitter.setSizes([500, 500])

        # Set stylesheet.
        self.central_widget.setStyleSheet(
            # QWidget{border: 1px solid red;}
            """
            QSplitter::handle {
                background: #BBBBBB;
            }
            QSplitter::handle:hover {
                background: #BBBBDD;
            }
            """
        )
