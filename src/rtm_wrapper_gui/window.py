from __future__ import annotations

from typing import Any

from PySide6 import QtWidgets
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon

from rtm_wrapper_gui import util
from rtm_wrapper_gui.plot import FigureWidget
from rtm_wrapper_gui.simulation import SimulationPanel


class MainWindow(QtWidgets.QMainWindow):
    central_widget: QtWidgets.QWidget

    figure_widget: FigureWidget

    plot_button: QtWidgets.QPushButton

    active_results: util.WatchedBox[util.RtmResults | None]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        self.active_results = util.WatchedBox(None, self)

        self._init_window()
        self._init_central_widget()
        self._init_signals()

        version_info = util.make_detailed_version(util.DISTRIBUTION_NAME).replace(
            " (", "\n("
        )
        self.figure_widget.show_splash(
            version_info,
            horizontalalignment="center",
            color="grey",
            fontstyle="italic",
            wrap=True,
        )

    def _init_window(self) -> None:
        self.setWindowTitle("RTM Wrapper GUI")
        self.setWindowIcon(QIcon.fromTheme("applications-science"))

    def _init_signals(self) -> None:
        self.plot_button.clicked.connect(self.figure_widget.draw)
        # self.browse_button.clicked.connect(self._on_browse)

    def _init_central_widget(self) -> None:
        # Setup central widget and layout.
        self.central_widget = QtWidgets.QWidget()
        top_layout = QtWidgets.QVBoxLayout()
        self.central_widget.setLayout(top_layout)
        self.setCentralWidget(self.central_widget)

        # Add main vertical splitter.
        top_splitter = QtWidgets.QSplitter(Qt.Orientation.Horizontal)
        top_splitter.addWidget(SimulationPanel(self))
        # top_splitter.addWidget(self._init_data_widget())
        top_splitter.addWidget(self._init_plot_widget())
        top_splitter.setHandleWidth(10)
        top_layout.addWidget(top_splitter)

        # Set stylesheet.
        self.central_widget.setStyleSheet(
            """
            QSplitter::handle {
                background: #BBBBBB;
            }
            QSplitter::handle:hover {
                background: #BBBBDD;
            }
            """
        )

    def _init_plot_widget(self) -> QtWidgets.QWidget:
        frame_widget = QtWidgets.QWidget()
        frame_layout = QtWidgets.QVBoxLayout()
        frame_widget.setLayout(frame_layout)

        splitter = QtWidgets.QSplitter(Qt.Orientation.Vertical)
        splitter.setHandleWidth(10)
        frame_layout.addWidget(splitter)

        self.figure_widget = FigureWidget()
        splitter.addWidget(self.figure_widget)

        control_widget = QtWidgets.QWidget()
        controls_layout = QtWidgets.QHBoxLayout()
        control_widget.setLayout(controls_layout)
        splitter.addWidget(control_widget)

        self.plot_button = QtWidgets.QPushButton()
        self.plot_button.setText("Plot")
        controls_layout.addWidget(self.plot_button)

        return frame_widget
